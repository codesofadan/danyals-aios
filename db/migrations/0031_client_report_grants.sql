-- 0031_client_report_grants.sql - Part 8 (Client Portal): per-client report access.
--
-- The admin grants a client visibility into specific charts/graphs/reports
-- (frontend clientReportGrants[clientId] in lib/data.ts). A report whose key is
-- NOT granted stays locked on the portal and its data is NEVER surfaced. This is
-- the server-side home of that grant set: one row per (client, report_key).
--
-- THREAT MODEL (mirrors 0010/0021/0024): a portal client authenticates and could
-- hit the DB directly, so RLS - not the curated responses - is the boundary.
-- Clients are already excluded by is_staff() (redefined in 0010): they get NO
-- base-table select policy here and read the grant set ONLY through the
-- security-barrier portal_report_grants view (self-filtered to their own tenant).
-- Any staff may READ the grants; only the leads (owner/admin/manager = the
-- manage_clients holders) may INSERT/DELETE, so the app-layer 403 and this DB
-- boundary agree. Grants are a replace-set (delete-all-for-client + bulk insert),
-- hence a DELETE policy rather than an UPDATE one.

create table if not exists public.client_report_grants (
  -- Tenant linkage. ON DELETE CASCADE removes a client's grants with the client.
  client_id   uuid not null references public.clients (id) on delete cascade,
  -- The grantable report key (clientReports.key in lib/data.ts). Free text so a
  -- future report surface needs no migration; the app validates the known set.
  report_key  text not null,
  granted_at  timestamptz not null default now(),
  -- Who last granted it; ON DELETE SET NULL keeps the grant if the staffer leaves.
  granted_by  uuid references public.users (id) on delete set null,
  primary key (client_id, report_key)
);

create index if not exists client_report_grants_client_id_idx
  on public.client_report_grants (client_id);

-- --- RLS ---------------------------------------------------------------------
alter table public.client_report_grants enable row level security;
alter table public.client_report_grants force row level security;

create policy client_report_grants_select on public.client_report_grants
  for select using (public.is_staff());
create policy client_report_grants_insert on public.client_report_grants
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy client_report_grants_delete on public.client_report_grants
  for delete using (public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- Client read surface = the security-barrier view -------------------------
-- The portal reads ONLY its own granted keys; security_barrier guarantees the
-- current_client_id() tenant filter runs before any user predicate. Owned by the
-- BYPASSRLS migration role, so SELECT on the view is all a client needs.
create or replace view public.portal_report_grants
  with (security_barrier = true) as
  select report_key
  from public.client_report_grants
  where client_id = public.current_client_id();

comment on view public.portal_report_grants is
  'Client-safe view: the caller''s own granted report keys, self-filtered to current_client_id().';

grant select on public.portal_report_grants to authenticated, anon;
