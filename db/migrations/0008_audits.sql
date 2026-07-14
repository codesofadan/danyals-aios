-- 0008_audits.sql - Module 01 Audit: the audit job-tracking table.
--
-- One row per audit the platform runs against the EXTERNAL audit engine
-- (danyals-audit-system), which a Celery worker invokes as a subprocess. This
-- table holds INFRA / job state - status, the engine's self-minted run_uuid,
-- artifact references, the composite score, cost and runtime - so the API can
-- report progress and serve results. The client-facing operational record
-- (the house-styled report in the client's Google Sheet) is produced later and
-- lives outside Postgres; this row is the durable job ledger.
--
-- Shapes mirror frontend/lib/audit.ts (AuditRow): types[], tier (Free/Paid),
-- status (queued/running/done/failed), a 0-100 composite score, pdf/json flags.
-- The per-audit `tier` (free|paid) is its OWN concept: it selects the engine
-- --mode (free = zero paid spend; paid = the engine's own provider keys). It is
-- NOT the subscription tier (clients.tier) nor the delivery tier
-- (clients.delivery_tier).

do $$ begin
  if not exists (select 1 from pg_type where typname = 'audit_tier') then
    create type public.audit_tier as enum ('free', 'paid');
  end if;
  if not exists (select 1 from pg_type where typname = 'audit_status') then
    create type public.audit_status as enum ('queued', 'running', 'done', 'failed');
  end if;
end $$;

create table public.audits (
  id           uuid primary key default gen_random_uuid(),
  -- Tenant linkage. ON DELETE SET NULL keeps the job ledger intact if a client
  -- or site is removed; client_name is snapshotted for display + the cost log.
  client_id    uuid references public.clients (id) on delete set null,
  site_id      uuid references public.sites (id) on delete set null,
  client_name  text not null default '',
  url          text not null,
  -- AuditTypeKey[]: technical | actionable | local | geo | backlink.
  types        text[] not null default '{}',
  tier         public.audit_tier not null default 'free',
  status       public.audit_status not null default 'queued',
  -- Engine linkage: the engine MINTS its own run_uuid and prints it + the
  -- artifact dir on stdout; the worker parses and stores them here.
  run_uuid     text,
  artifact_dir text,
  -- Stored artifact references (set once copied out of the engine's data dir);
  -- their presence drives the frontend pdf/json booleans.
  pdf_path     text,
  json_path    text,
  -- Results.
  score        integer,                      -- 0-100 composite; null while pending
  scores       jsonb not null default '{}',  -- per-category detail from run.json
  cost         numeric(10, 2) not null default 0,
  error        text,                         -- failure reason (server-side only; never leaked raw)
  -- Timing. runtime_seconds is wall-clock turnaround; null while pending.
  runtime_seconds integer,
  started_at   timestamptz,
  finished_at  timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index audits_client_id_idx on public.audits (client_id);
create index audits_created_at_idx on public.audits (created_at desc);

create trigger audits_set_updated_at
  before update on public.audits
  for each row execute function public.set_updated_at();

-- --- RLS ----------------------------------------------------------------------
-- Every provisioned staff member may read the audit list; run_audits holders
-- (owner/admin/manager/specialist/analyst - everyone but viewer) may create a
-- run via a user-JWT client. The worker updates rows with the service_role
-- client, which bypasses RLS by design.
alter table public.audits enable row level security;
alter table public.audits force row level security;

create policy audits_select on public.audits
  for select using (public.is_staff());

create policy audits_modify on public.audits
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager', 'specialist', 'analyst'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager', 'specialist', 'analyst'));
