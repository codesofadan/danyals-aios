-- 0010_client_portal.sql - the client trust boundary for the portal.
--
-- Depends on 0009 (the 'client' app_role label, added + committed separately).
--
-- A client login is a public.users row with role='client' linked to exactly one
-- public.clients row via users.client_id. Clients are NOT staff: is_staff() is
-- redefined to exclude them, so every staff-scoped policy shipped so far (0002,
-- 0003, 0008 ...) default-denies a client on the BASE tables.
--
-- THE THREAT MODEL: a client authenticates with a Supabase JWT and can query
-- PostgREST DIRECTLY with the public anon key (bypassing FastAPI), so RLS - not
-- the curated Pydantic responses - is the only boundary. The base rows carry
-- sensitive columns (clients.mrr, audits.cost/error/*_path, ...). Therefore we
-- give clients NO select policy on any base table; instead they read ONLY through
-- three SECURITY-BARRIER VIEWS that expose a safe column subset and self-filter
-- by current_client_id(). The views are owned by the migration role (postgres,
-- BYPASSRLS) and run with security_invoker left at its default (false), so the
-- view's own WHERE clause is the tenant boundary and staff callers simply get
-- zero rows (harmless).

-- --- D2: link a client login to its clients row -------------------------------
-- NULL for staff; set (and required) for role='client'. ON DELETE CASCADE: if a
-- client account is removed, its portal logins go with it.
alter table public.users
  add column if not exists client_id uuid references public.clients (id) on delete cascade;

create index if not exists users_client_id_idx on public.users (client_id);

-- CHECK mirrors the model exactly: client_id is set iff the role is 'client'.
-- Existing staff rows (role<>'client', client_id NULL) satisfy false=false, so
-- there is no migrate-time violation.
do $$ begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'users_client_id_role_chk' and conrelid = 'public.users'::regclass
  ) then
    alter table public.users
      add constraint users_client_id_role_chk
      check ((role = 'client') = (client_id is not null));
  end if;
end $$;

-- --- D3: redefine is_staff(); add current_client_id() -------------------------
-- SECURITY DEFINER + empty search_path (schema-qualified everywhere) so reading
-- public.users from INSIDE a users policy never recurses (owner is BYPASSRLS).
-- is_staff() now EXCLUDES clients, tightening every existing staff policy to
-- default-deny a client on the base tables.
create or replace function public.is_staff()
returns boolean
language sql stable security definer set search_path = ''
as $$ select exists (
  select 1 from public.users where id = auth.uid() and role <> 'client'
) $$;

comment on function public.is_staff() is
  'True if the caller (auth.uid()) is a provisioned STAFF user (role <> client). Used by RLS.';

-- The calling client's tenant id, or NULL for staff / anon. The views filter on
-- this; it is referenced by NO users policy, so it introduces no recursion.
create or replace function public.current_client_id()
returns uuid
language sql stable security definer set search_path = ''
as $$ select client_id from public.users where id = auth.uid() and role = 'client' $$;

comment on function public.current_client_id() is
  'The clients.id a portal client (auth.uid()) is scoped to, else NULL. Used by the portal_* views.';

-- --- D4: the client read surface = SECURITY-BARRIER VIEWS ONLY ----------------
-- No client select policy exists on clients/sites/audits; these views are the
-- entire client-visible surface. Each exposes only safe columns and self-filters
-- by current_client_id(). security_barrier=true guarantees the tenant filter runs
-- before any user-supplied predicate could leak a row.

-- portal_audits: EXCLUDES cost, error, artifact_dir, run_uuid, pdf_path,
-- json_path (surfaced only as has_pdf / has_json booleans).
create or replace view public.portal_audits
  with (security_barrier = true) as
  select
    id,
    client_id,
    url,
    types,
    tier,
    status,
    score,
    scores,
    runtime_seconds,
    created_at,
    started_at,
    finished_at,
    (pdf_path is not null)  as has_pdf,
    (json_path is not null) as has_json
  from public.audits
  where client_id = public.current_client_id();

comment on view public.portal_audits is
  'Client-safe view of public.audits, self-filtered to current_client_id(). No cost/error/paths.';

-- portal_client: EXCLUDES mrr, portal_admin, contact_*, tier, status, renews_at.
create or replace view public.portal_client
  with (security_barrier = true) as
  select
    id,
    name,
    industry,
    delivery_tier
  from public.clients
  where id = public.current_client_id();

comment on view public.portal_client is
  'Client-safe view of the caller''s own public.clients row (no mrr/contact/billing).';

-- portal_sites: only id + domain for the caller's own client.
create or replace view public.portal_sites
  with (security_barrier = true) as
  select
    id,
    domain
  from public.sites
  where client_id = public.current_client_id();

comment on view public.portal_sites is
  'Client-safe view of public.sites (id + domain) for the caller''s own client.';

-- PostgREST resolves the caller to the `authenticated` (JWT) or `anon` role; the
-- views run as their BYPASSRLS owner, so SELECT on the VIEW is all a client needs.
grant select on public.portal_audits to authenticated, anon;
grant select on public.portal_client to authenticated, anon;
grant select on public.portal_sites  to authenticated, anon;
