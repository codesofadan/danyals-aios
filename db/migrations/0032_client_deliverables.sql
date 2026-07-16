-- 0032_client_deliverables.sql - Part 8 (Client Portal): the deliverables library.
--
-- Reports the client can open / download - audits, monthly rollups, content &
-- backlink profiles (frontend clientDeliverables in lib/client.ts). Producers
-- (the audit / content / reports / offpage workers) EMIT one row here at their
-- completion point via app.services.deliverables.emit_deliverable (best-effort,
-- server-only). A deliverable is visible to the client ONLY when its `requires`
-- report key is granted (0031) - so access is gated by the same grant set as the
-- charts.
--
-- THREAT MODEL (mirrors 0010/0021/0024): clients are excluded by is_staff() - no
-- base-table select policy - and read ONLY through the security-barrier
-- portal_deliverables view, which HIDES artifact_key / media_type / source_* (the
-- download path resolves the artifact server-side, never returning the key). Any
-- staff may READ; only the leads (owner/admin/manager) + the worker service_role
-- (BYPASSRLS) may INSERT/UPDATE.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'deliverable_kind') then
    create type public.deliverable_kind as enum
      ('Audit', 'Monthly', 'Content', 'Backlinks', 'Local');
  end if;
  if not exists (select 1 from pg_type where typname = 'deliverable_status') then
    create type public.deliverable_status as enum ('ready', 'generating');
  end if;
end $$;

-- --- Table -------------------------------------------------------------------
create table if not exists public.client_deliverables (
  id           uuid primary key default gen_random_uuid(),
  -- Tenant linkage. ON DELETE CASCADE removes a client's deliverables with it.
  client_id    uuid not null references public.clients (id) on delete cascade,
  title        text not null default '',
  kind         public.deliverable_kind not null,
  icon         text not null default '',            -- Material Symbols name (display)
  period       text not null default '',            -- human period this report covers
  issued_at    timestamptz,                         -- when issued; null while generating
  size_label   text not null default '',            -- file-size label (display only)
  status       public.deliverable_status not null default 'ready',
  -- Which grant key must be held for this deliverable to be VISIBLE (0031).
  requires     text not null,
  -- --- Server-only columns (never exposed through the portal view) ---
  artifact_key text,                                -- artifact-store key (resolved server-side)
  media_type   text not null default 'application/pdf',
  source_kind  text,                                -- producing worker (audit|content|report|offpage)
  source_id    uuid,                                -- the producing row's id (idempotency/trace)
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists client_deliverables_client_id_idx
  on public.client_deliverables (client_id);
create index if not exists client_deliverables_requires_idx
  on public.client_deliverables (requires);

create trigger client_deliverables_set_updated_at
  before update on public.client_deliverables
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
alter table public.client_deliverables enable row level security;
alter table public.client_deliverables force row level security;

create policy client_deliverables_select on public.client_deliverables
  for select using (public.is_staff());
create policy client_deliverables_insert on public.client_deliverables
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy client_deliverables_update on public.client_deliverables
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- Client read surface = the security-barrier view -------------------------
-- Exposes ONLY the safe display columns (mirrors ClientDeliverable in
-- lib/client.ts) and self-filters to the caller's own tenant AND to deliverables
-- whose `requires` key is granted. artifact_key / media_type / source_* are
-- deliberately NOT selected - the download endpoint resolves them server-side.
create or replace view public.portal_deliverables
  with (security_barrier = true) as
  select
    id,
    title,
    kind,
    icon,
    period,
    issued_at,
    size_label,
    status,
    requires
  from public.client_deliverables
  where client_id = public.current_client_id()
    and requires in (
      select report_key
      from public.client_report_grants
      where client_id = public.current_client_id()
    );

comment on view public.portal_deliverables is
  'Client-safe view of public.client_deliverables: safe display columns only, self-filtered to '
  'current_client_id() AND to a granted `requires` key. Hides artifact_key/media_type/source_*.';

grant select on public.portal_deliverables to authenticated, anon;
