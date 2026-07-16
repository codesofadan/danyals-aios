-- 0026_backups.sql - Part 7 (7G-1): the Backups & Restore ledger + config.
--
-- System Architecture SS09 (Resilience): "Nightly Postgres backups, container
-- restart policies, documented restore, TLS everywhere." Artifacts live on the VPS
-- volume; a manual/weekly "Full" run also captures the file-artifacts volume, and
-- an OPTIONAL Backblaze B2 offsite copy is key-gated in the service layer. Shapes
-- mirror frontend/lib/backups.ts (Snapshot / backupConfig).
--
-- Two agency-global stores (backups protect the WHOLE platform, not a tenant, so
-- there is NO client_id - unlike every product-module table):
--
--   * backup_snapshots - one row per snapshot (nightly or manual): its type, scope,
--     size, duration, status, the controlled-root artifact key, and whether it was
--     synced offsite. The public API `id` is the row uuid (no tenant-leak concern).
--   * backup_config    - a single agency-global row (id pinned to 1): the nightly
--     schedule + retention, the nightly/offsite toggles, and the last/next-backup +
--     last-verified-restore markers that drive the config panel's derived counters.
--
-- RLS (mirrors 0025's threat model - a leaked credential can hit the DB direct, so
-- RLS is the real boundary): any staff READ both stores; only owner/admin MANAGE
-- them (run a snapshot, edit config). Clients are excluded by is_staff(). No delete
-- policies - retention pruning + the guarded restore run server-side (the privileged
-- pool / owner-gated router). FORCE so even the table owner is bound.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
-- SS3 enum fidelity: values mirror backups.ts VERBATIM (SnapStatus success|running|
-- failed; SnapType Nightly|Manual - note the capitalized labels).
do $$ begin
  if not exists (select 1 from pg_type where typname = 'snapshot_status') then
    create type public.snapshot_status as enum ('success', 'running', 'failed');
  end if;
  if not exists (select 1 from pg_type where typname = 'snapshot_type') then
    create type public.snapshot_type as enum ('Nightly', 'Manual');
  end if;
end $$;

-- --- Snapshot ledger ---------------------------------------------------------
create table if not exists public.backup_snapshots (
  id               uuid primary key default gen_random_uuid(),   -- public API id
  type             public.snapshot_type not null default 'Manual',
  scope            text not null default 'Database',   -- "Database" | "Full (DB + files)"
  size_bytes       bigint not null default 0,          -- artifact size; 0 -> "—" in the UI
  duration_seconds integer not null default 0,         -- wall-clock of the run
  status           public.snapshot_status not null default 'running',
  artifact_ref     text,                               -- controlled-root RELATIVE key (never absolute)
  offsite_synced   boolean not null default false,     -- copied to the B2 offsite bucket
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists backup_snapshots_created_at_idx on public.backup_snapshots (created_at desc);
create index if not exists backup_snapshots_status_idx on public.backup_snapshots (status);

create trigger backup_snapshots_set_updated_at
  before update on public.backup_snapshots
  for each row execute function public.set_updated_at();

-- --- Config singleton (agency-global) ----------------------------------------
-- Exactly one row (id pinned to 1 by the check), so a GET is a single-row read and
-- a PUT is a single-row upsert. Seeded with the frontend defaults so a GET always
-- finds a row even before the first save.
create table if not exists public.backup_config (
  id                integer primary key default 1 check (id = 1),
  nightly_time      text not null default '02:00 UTC',   -- contract `nightlyTime`
  retention_days    integer not null default 30,         -- contract `retentionDays`
  nightly_enabled   boolean not null default true,       -- contract `nightlyOn`
  offsite_enabled   boolean not null default false,      -- contract `offsiteOn`
  last_backup       timestamptz,                         -- last successful snapshot (drives `lastBackupAgoH`)
  next_backup       timestamptz,                         -- next scheduled run (drives `nextBackupInH`)
  restore_tested_at timestamptz,                         -- last verified restore (drives `restoreTested`)
  updated_at        timestamptz not null default now()
);

create trigger backup_config_set_updated_at
  before update on public.backup_config
  for each row execute function public.set_updated_at();

insert into public.backup_config (id) values (1) on conflict (id) do nothing;

-- --- RLS ---------------------------------------------------------------------
alter table public.backup_snapshots enable row level security;
alter table public.backup_snapshots force row level security;
alter table public.backup_config enable row level security;
alter table public.backup_config force row level security;

-- Any staff read; only owner/admin manage (mirrors the 0025 singleton policies).
create policy backup_snapshots_select on public.backup_snapshots
  for select using (public.is_staff());
create policy backup_snapshots_insert on public.backup_snapshots
  for insert with check (public.current_app_role() in ('owner', 'admin'));
create policy backup_snapshots_update on public.backup_snapshots
  for update
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));

create policy backup_config_select on public.backup_config
  for select using (public.is_staff());
create policy backup_config_insert on public.backup_config
  for insert with check (public.current_app_role() in ('owner', 'admin'));
create policy backup_config_update on public.backup_config
  for update
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));
