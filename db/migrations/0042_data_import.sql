-- 0042_data_import.sql - Part 8 Phase 2G (Data Import): the FILE-import pipeline -
-- upload -> sniff -> map -> validate -> commit into the modules that already exist.
--
-- This module is how the agency gets Search-Console / Semrush / Ahrefs data into the
-- platform WITHOUT an API: a human exports a CSV/XLSX and uploads it. There is NO
-- Google API client, NO OAuth and NO network call anywhere in this module - live
-- GSC/GA integration is explicitly OUT of contract scope, and this file-import path is
-- the contracted substitute, not a placeholder for it. Zero providers, zero keys, zero
-- spend: there is deliberately no cost-gate dial here, because nothing is ever bought.
--
--   * import_runs     - one row per uploaded file. client_id is NULLABLE: an
--     agency-global import (a keyword bank with no client yet) is valid, exactly like
--     0035's bank rows. client_name is a display SNAPSHOT so client_id never has to be
--     surfaced. `filename` is the ORIGINAL display name (safe to render);
--     `stored_path` is the SERVER-ONLY location under the controlled artifact root and
--     is NEVER serialized to the wire - no response model carries it (the module's
--     schema tests sweep every response model to prove it). detected_columns is the
--     sniffed header row; column_map is {source_header: target_field}; error_sample is
--     a BOUNDED sample of rejected rows (capped by the worker - an unbounded sample of
--     a million-row bad file would be a memory + jsonb bloat bug, not a feature).
--   * import_mappings - reusable saved templates. `source_signature` is a normalized
--     header fingerprint, so re-uploading next month's export of the SAME report
--     auto-applies last month's mapping instead of re-asking a human.
--   * search_console_rows - the file-imported GSC target. This gives the
--     `search_console` import type a real home: the rows land here from an UPLOADED
--     FILE, never from an API pull. import_run_id points back at the run that created
--     them (on delete set null - purging a run's audit trail must not silently delete
--     the client's performance data).
--
-- The commit WRITER runs on service_role (BYPASSRLS) in the worker, exactly like the
-- 0035 research ingest: the RLS insert policies on the TARGET tables (backlinks /
-- citations / keywords / tracked_keywords) are lead-only, and the worker holds no user
-- JWT. It stamps client_id + client_name itself. The columns it may write are frozen
-- in the module's constants.py ALLOW-LIST - a column_map can never name an arbitrary
-- column, which is the module's injection boundary.
--
-- RLS mirrors 0035_keyword_research / 0018_offpage exactly: any STAFF may READ
-- (is_staff()); only LEADS (owner/admin/manager) may INSERT/UPDATE. Clients get NO
-- select policy at all - an import ledger names other tenants' files, and is_staff()
-- never references client_id, so a NULL-client agency-global run is correctly visible
-- to staff yet invisible to clients. No delete policy in v1.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'import_source_type') then
    -- What the file IS, which selects the target table + the field allow-list.
    -- 'custom' stages only: it has NO target table and no downstream commit.
    create type public.import_source_type as enum
      ('search_console', 'keywords', 'backlinks', 'rankings', 'citations', 'custom');
  end if;
  if not exists (select 1 from pg_type where typname = 'import_status') then
    -- uploaded -> mapping -> validating -> importing -> imported | partial | failed.
    -- The last three are TERMINAL: the worker claims a run by moving it to
    -- 'importing' with a conditional UPDATE, so a Celery redelivery finds a
    -- non-claimable status and is a clean no-op instead of a double insert.
    create type public.import_status as enum
      ('uploaded', 'mapping', 'validating', 'importing', 'imported', 'partial', 'failed');
  end if;
end $$;

-- --- Import runs: one row per uploaded file -----------------------------------
create table if not exists public.import_runs (
  id               uuid primary key default gen_random_uuid(),
  -- NULLABLE: an agency-global import (e.g. filling the un-assigned keyword bank)
  -- belongs to no client. ON DELETE CASCADE drops a client's import ledger with them.
  client_id        uuid references public.clients (id) on delete cascade,
  client_name      text not null default '',
  -- The ORIGINAL upload name - a DISPLAY string only. It is never used to build a
  -- path (the store generates its own name), so a crafted "../../etc/passwd" here is
  -- inert text that renders as text.
  filename         text not null default '',
  -- SERVER-ONLY. The generated name under the controlled import root. NEVER
  -- serialized: no response model exposes it (tests/modules/data_import/test_schemas
  -- sweeps every model to prove it).
  stored_path      text not null default '',
  source_type      public.import_source_type not null,
  status           public.import_status not null default 'uploaded',
  detected_columns jsonb not null default '[]',   -- the sniffed header row
  column_map       jsonb not null default '{}',   -- {source_header: target_field}
  rows_total       integer not null default 0,
  rows_mapped      integer not null default 0,
  rows_error       integer not null default 0,
  -- BOUNDED by the worker (see tasks.py _ERROR_SAMPLE_MAX). A file with a million bad
  -- rows must not write a million-entry jsonb blob.
  error_sample     jsonb not null default '[]',
  content_sha256   text not null default '',      -- the stored bytes' digest
  uploaded_by      uuid references public.users (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists import_runs_client_id_idx  on public.import_runs (client_id);
create index if not exists import_runs_status_idx     on public.import_runs (status);
create index if not exists import_runs_created_at_idx on public.import_runs (created_at desc);

create trigger import_runs_set_updated_at
  before update on public.import_runs
  for each row execute function public.set_updated_at();

-- --- Saved mapping templates --------------------------------------------------
create table if not exists public.import_mappings (
  id               uuid primary key default gen_random_uuid(),
  source_type      public.import_source_type not null,
  name             text not null,
  -- A normalized fingerprint of the header row (see service.header_signature), so an
  -- identical export auto-applies this template on upload.
  source_signature text not null default '',
  column_map       jsonb not null default '{}',
  created_by       uuid references public.users (id) on delete set null,
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),
  -- One template per (source_type, name). NULLS NOT DISTINCT (PG15+; we deploy PG16)
  -- makes NULL = NULL for uniqueness. Under default SQL NULL semantics every NULL is
  -- DISTINCT, so a NULL member would silently admit a duplicate that
  -- `on conflict do nothing` could never catch. Neither column is nullable TODAY, but
  -- this exact defect was already found and fixed twice (0035, then 0036); the house
  -- rule is now unconditional so a later `alter column ... drop not null` cannot
  -- quietly re-open it a third time.
  unique nulls not distinct (source_type, name)
);

create index if not exists import_mappings_signature_idx
  on public.import_mappings (source_type, source_signature);

create trigger import_mappings_set_updated_at
  before update on public.import_mappings
  for each row execute function public.set_updated_at();

-- --- Search Console rows: the FILE-imported GSC target ------------------------
-- The `search_console` import type's home. Every row here came out of an uploaded
-- export - there is no API pull anywhere in this module. Deliberately flat + append-
-- shaped (no unique key): a GSC export is a report snapshot, and the run-claim in the
-- worker (not a constraint) is what makes a redelivery a no-op.
create table if not exists public.search_console_rows (
  id            uuid primary key default gen_random_uuid(),
  client_id     uuid references public.clients (id) on delete cascade,
  client_name   text not null default '',
  query         text not null default '',
  page          text not null default '',
  clicks        integer not null default 0,
  impressions   integer not null default 0,
  -- A FRACTION (0.0341 = 3.41%), not a percentage - the service coerces GSC's "3.41%"
  -- into 0.0341 on the way in. numeric(6,4) holds 4 decimals of a 0-1 ratio.
  ctr           numeric(6,4) not null default 0,
  -- NULLABLE and meaningful: the export had no average position for that row.
  position      numeric(6,2),
  date          date,
  -- ON DELETE SET NULL: purging a run's audit trail must not delete the client's
  -- performance data with it.
  import_run_id uuid references public.import_runs (id) on delete set null,
  created_at    timestamptz not null default now()
);

create index if not exists search_console_rows_client_date_idx
  on public.search_console_rows (client_id, date);

-- --- RLS ---------------------------------------------------------------------
-- Clients are excluded by is_staff() (they get NO base-table select policy): an import
-- ledger names other tenants' files and the GSC rows carry client_id, so neither is
-- client-readable. Any staff may READ; only leads (owner/admin/manager) may
-- INSERT/UPDATE - which mirrors the RLS write policies on every TARGET table this
-- module writes into (0018 backlinks/citations, 0035 keywords, 0036 tracked_keywords),
-- so the app gate and the database agree. The commit worker runs on service_role
-- (BYPASSRLS). No delete policy in v1.
alter table public.import_runs enable row level security;
alter table public.import_runs force row level security;
alter table public.import_mappings enable row level security;
alter table public.import_mappings force row level security;
alter table public.search_console_rows enable row level security;
alter table public.search_console_rows force row level security;

create policy import_runs_select on public.import_runs
  for select using (public.is_staff());
create policy import_runs_insert on public.import_runs
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy import_runs_update on public.import_runs
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy import_mappings_select on public.import_mappings
  for select using (public.is_staff());
create policy import_mappings_insert on public.import_mappings
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy import_mappings_update on public.import_mappings
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy search_console_rows_select on public.search_console_rows
  for select using (public.is_staff());
create policy search_console_rows_insert on public.search_console_rows
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy search_console_rows_update on public.search_console_rows
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
