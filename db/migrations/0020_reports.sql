-- 0020_reports.sql - Part 7 Module 04 (Reports): the operational-store layer -
-- per-client + master Google Sheets workbooks, written through a quota-safe Redis
-- write-buffer.
--
-- v1 reporting runs on Google Sheets via a service account: ONE workbook per client
-- plus a single MASTER ROLLUP workbook (the agency-global roll-up across clients).
-- The audit / content / milestone modules push their datasets here through a Redis
-- write-buffer that coalesces many writes into ONE batched Sheets `batchUpdate` per
-- workbook (quota-safe). Everything Google is KEY-GATED at the SERVICE layer
-- (integrations/sheets.py + app/services/sheetstore.py) and degrades cleanly with no
-- key; these two tables are the DB ledger of WHAT is synced + a per-push event log.
--
-- Shapes mirror frontend/lib/reports.ts (Workbook / SyncEvent / ReportType). The
-- internal client_id NEVER leaks - client_name is a display SNAPSHOT (like
-- content_jobs / offpage / milestones). The MASTER ROLLUP is itself a row in
-- report_workbooks (is_master = true, client_id NULL) so the connection endpoint can
-- surface it uniformly; a partial unique index guarantees exactly one.
--
-- RLS mirrors 0018_offpage exactly: any staff may READ; only leads (owner/admin/
-- manager) may INSERT/UPDATE. Clients are excluded by is_staff() (no base-table
-- select policy), so a portal client can NOT read the reporting ledgers. The actual
-- Sheets PUSH (the SheetStore flush) runs on the authenticated lead path here (sync
-- is lead-only) and, in a later worker chunk, on service_role (BYPASSRLS). No delete
-- policy in v1.

-- --- Enum (idempotent guard; enums have no "create ... if not exists") --------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'sync_status') then
    -- Verbatim from reports.ts SyncStatus.
    create type public.sync_status as enum ('synced', 'syncing', 'error');
  end if;
end $$;

-- --- report_workbooks: one row per client workbook + the master rollup ---------
create table if not exists public.report_workbooks (
  id                uuid primary key default gen_random_uuid(),
  -- Tenant linkage. ON DELETE CASCADE drops a client's workbook with it; NULL for
  -- the master rollup (is_master). client_name is a display SNAPSHOT so client_id
  -- never has to be surfaced to the API.
  client_id         uuid references public.clients (id) on delete cascade,
  client_name       text not null default '',
  -- The Google Sheets spreadsheet id (the "open sheet" affordance / the flush
  -- target). Empty until a workbook is provisioned.
  sheet_id          text not null default '',
  -- The datasets kept in sync on this workbook (contract `tabs`: a Dataset[] subset
  -- of audit|content|milestones), a jsonb array of dataset strings.
  tabs              jsonb not null default '[]'::jsonb,
  status            public.sync_status not null default 'synced',
  -- Rows synced today across all tabs (contract `rows`); a worker resets it daily.
  rows_synced_today integer not null default 0 check (rows_synced_today >= 0),
  last_sync         timestamptz,                  -- contract `lastSync` (relative)
  is_master         boolean not null default false,  -- the single master-rollup ref row
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists report_workbooks_client_id_idx on public.report_workbooks (client_id);
create index if not exists report_workbooks_last_sync_idx
  on public.report_workbooks (last_sync desc nulls last);
-- Exactly one master-rollup row (client_id NULL, is_master true).
create unique index if not exists report_workbooks_one_master
  on public.report_workbooks (is_master) where is_master;

create trigger report_workbooks_set_updated_at
  before update on public.report_workbooks
  for each row execute function public.set_updated_at();

-- Seed the single master-rollup ref row (idempotent; the partial unique index also
-- enforces uniqueness). Done BEFORE RLS is enabled below - the migration role writes
-- it, and a re-run is a no-op via the NOT EXISTS guard.
insert into public.report_workbooks (client_name, sheet_id, tabs, status, is_master)
select 'Master Rollup', '', '["audit","content","milestones"]'::jsonb, 'synced'::public.sync_status, true
where not exists (select 1 from public.report_workbooks where is_master);

-- --- report_sync_events: the per-push event log (contract SyncEvent) -----------
create table if not exists public.report_sync_events (
  id           uuid primary key default gen_random_uuid(),
  workbook_id  uuid references public.report_workbooks (id) on delete cascade,
  client_name  text not null default '',          -- display SNAPSHOT (contract `client`)
  -- The dataset this push wrote (contract `dataset`: audit|content|milestones). Kept
  -- as a checked text (not an enum) since only sync_status is a first-class enum.
  dataset      text not null check (dataset in ('audit', 'content', 'milestones')),
  rows         integer not null default 0 check (rows >= 0),  -- rows pushed in this event
  synced_at    timestamptz not null default now(),           -- contract `ago` (relative)
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists report_sync_events_workbook_id_idx
  on public.report_sync_events (workbook_id);
create index if not exists report_sync_events_synced_at_idx
  on public.report_sync_events (synced_at desc);

create trigger report_sync_events_set_updated_at
  before update on public.report_sync_events
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Clients are already excluded by is_staff() (redefined in 0010) - they never get a
-- base-table select policy here, so a portal client can NOT read the reporting
-- ledgers (mirrors 0011/0017/0018/0021). Any staff may READ; only leads (owner/admin/
-- manager) may INSERT/UPDATE - the same set the sync endpoints gate to; the app-layer
-- 403 is clean UX on top of this DB boundary. No delete in v1.
alter table public.report_workbooks enable row level security;
alter table public.report_workbooks force row level security;
alter table public.report_sync_events enable row level security;
alter table public.report_sync_events force row level security;

create policy report_workbooks_select on public.report_workbooks
  for select using (public.is_staff());
create policy report_workbooks_insert on public.report_workbooks
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy report_workbooks_update on public.report_workbooks
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy report_sync_events_select on public.report_sync_events
  for select using (public.is_staff());
create policy report_sync_events_insert on public.report_sync_events
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy report_sync_events_update on public.report_sync_events
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
