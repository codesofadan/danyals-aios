-- 0019_policy.sql - Part 7 Module 05 (Policy Radar): the always-on SEO/algorithm
-- intelligence brain.
--
-- The platform's always-on loop is: WATCH curated sources -> DETECT a change
-- (content hash diff) -> RESEARCH it -> FLAG it as a versioned, deduped, cited KB
-- entry on THREE AXES (severity x category x region) -> RECOMMEND a concrete action
-- for a target module -> a human CONFIRMS -> the closed loop writes into audit
-- checks / content guidance / client advisories. Shapes mirror frontend/lib/
-- policy.ts (Source + ChangeEvent + KBEntry + Recommendation).
--
-- THIS CHUNK (7C-1, FOUNDATION) ships the DATA + read/transition surface + a
-- BASELINE set of evergreen recommendations (app/services/policy_baseline.py) so
-- the Command Center is populated PRE-LIVE. Two things are DEFERRED but the tables
-- are shaped to receive them:
--   * the change-detection WATCHER worker - it will run on service_role
--     (BYPASSRLS), so it fills policy_sources.last_hash, appends change_events, and
--     writes kb_entries + recommendations regardless of the human RLS policies
--     below (change_events.diff_ref / triggered_job and the *_id FKs are its hooks).
--   * the closed-loop AUDIT OVERLAY that a 'applied' recommendation writes to - a
--     LATER chunk. Postgres HARD RULE (Part 3): the danyals-audit-system ENGINE is
--     NEVER mutated; 'apply' will write to a SEPARATE overlay, never the engine.
--
-- Postgres is the KB (not a flat store) so the modules can JOIN a recommendation
-- back to its kb entry and source. Internal ids never leak: source_name/source_url
-- and kb_ref are display SNAPSHOTS (like content_jobs' client_name), and the *_id
-- FKs stay server-side.
--
-- RLS: any staff may READ (view_reports surface); only owner/admin/manager MANAGE
-- (the confirm/acknowledge/apply/dismiss actor set = the leads). Clients are
-- excluded by is_staff(); there is no client select policy. No delete in v1.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
-- All seven verbatim from policy.ts - §3 enum fidelity: each is a DISTINCT type
-- even where labels overlap (e.g. policy_scope 'global' vs policy_region 'global').
do $$ begin
  if not exists (select 1 from pg_type where typname = 'policy_severity') then
    create type public.policy_severity as enum ('critical', 'major', 'minor', 'info');
  end if;
  if not exists (select 1 from pg_type where typname = 'policy_category') then
    create type public.policy_category as enum
      ('algorithm', 'policy', 'technical', 'content', 'local', 'geo');
  end if;
  if not exists (select 1 from pg_type where typname = 'policy_region') then
    create type public.policy_region as enum ('global', 'national');
  end if;
  if not exists (select 1 from pg_type where typname = 'policy_target_module') then
    create type public.policy_target_module as enum ('audit', 'content', 'portal');
  end if;
  if not exists (select 1 from pg_type where typname = 'policy_scope') then
    create type public.policy_scope as enum ('global', 'client', 'site');
  end if;
  if not exists (select 1 from pg_type where typname = 'rec_status') then
    create type public.rec_status as enum ('new', 'acknowledged', 'applied', 'dismissed');
  end if;
  if not exists (select 1 from pg_type where typname = 'source_status') then
    create type public.source_status as enum ('ok', 'change');
  end if;
end $$;

-- --- policy_sources: the curated watch list ----------------------------------
-- One row per monitored source (Search Status Dashboard, Search Central, QRG, ...).
-- last_hash is the change-detection ANCHOR: the WATCHER (later, service_role)
-- re-fetches, compares the content hash to last_hash, and on a diff flips status to
-- 'change' + appends a change_event. last_checked is NULL until the first poll.
create table if not exists public.policy_sources (
  id           uuid primary key default gen_random_uuid(),
  name         text not null,
  kind         text not null default '',            -- source type/kind label (contract `kind`)
  url          text not null default '',
  icon         text not null default '',            -- material symbol (contract `icon`)
  last_checked timestamptz,                          -- last WATCHER poll (contract `lastChecked`, relative); null pre-live
  last_hash    text not null default '',            -- content hash of the last fetch (contract `lastHash`); the diff anchor
  status       public.source_status not null default 'ok',
  note         text not null default '',            -- latest human/system note (contract `note`)
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists policy_sources_status_idx     on public.policy_sources (status);
create index if not exists policy_sources_created_at_idx  on public.policy_sources (created_at desc);

create trigger policy_sources_set_updated_at
  before update on public.policy_sources
  for each row execute function public.set_updated_at();

-- --- change_events: the detected-diff ledger ---------------------------------
-- One row per detected source change. source_name is a display SNAPSHOT so
-- source_id never has to surface. diff_ref (pointer to the stored diff artifact)
-- and triggered_job (the research/KB job this change kicked off) are the WATCHER's
-- hooks - null in this chunk, filled by the deferred worker.
create table if not exists public.change_events (
  id             uuid primary key default gen_random_uuid(),
  source_id      uuid references public.policy_sources (id) on delete set null,
  source_name    text not null default '',           -- display snapshot (contract `sourceName`)
  summary        text not null default '',
  severity       public.policy_severity not null default 'info',
  detected_at    timestamptz not null default now(),  -- contract `detected` (relative)
  diff_ref       text not null default '',            -- pointer to the stored diff artifact (watcher)
  triggered_job  text,                                -- research/KB job kicked off by this change (watcher)
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists change_events_source_id_idx    on public.change_events (source_id);
create index if not exists change_events_detected_at_idx   on public.change_events (detected_at desc);

create trigger change_events_set_updated_at
  before update on public.change_events
  for each row execute function public.set_updated_at();

-- --- kb_entries: the versioned, deduped, cited knowledge base -----------------
-- One row per distilled finding on the THREE AXES severity x category x region.
-- region is the coarse axis (global|national); region_flags[] carries the specific
-- national markets in scope (supports future per-market targeting). hash + version
-- drive dedupe/versioning: the WATCHER bumps version + hash when a source re-states
-- the same finding rather than inserting a duplicate. source_name/source_url are
-- the citation SNAPSHOTS; source_id is the internal join back to policy_sources.
create table if not exists public.kb_entries (
  id           uuid primary key default gen_random_uuid(),
  source_id    uuid references public.policy_sources (id) on delete set null,  -- internal citation link
  title        text not null,
  summary      text not null default '',
  -- the 3 axes:
  severity     public.policy_severity not null default 'info',
  category     public.policy_category not null default 'algorithm',
  region       public.policy_region not null default 'global',
  region_flags text[] not null default '{}',          -- specific national markets in scope
  region_label text not null default '',              -- display label (contract `regionLabel`)
  source_name  text not null default '',              -- citation snapshot (contract `sourceName`)
  source_url   text not null default '',              -- citation snapshot (contract `sourceUrl`)
  version      text not null default 'v1',            -- KB entry version (contract `version`)
  hash         text not null default '',              -- dedupe/version anchor
  detected_at  timestamptz not null default now(),    -- contract `detected` (relative)
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists kb_entries_source_id_idx    on public.kb_entries (source_id);
create index if not exists kb_entries_severity_idx      on public.kb_entries (severity);
create index if not exists kb_entries_category_idx      on public.kb_entries (category);
create index if not exists kb_entries_detected_at_idx   on public.kb_entries (detected_at desc);

create trigger kb_entries_set_updated_at
  before update on public.kb_entries
  for each row execute function public.set_updated_at();

-- --- recommendations: the Command Center action queue ------------------------
-- One row per concrete action a kb entry recommends for a target module. kb_entry_id
-- is the internal FK (NULL for a BASELINE recommendation, which has no live KB
-- entry); kb_ref is the PUBLIC kbId snapshot (contract `kbId`) - a synthetic
-- "kb-base-*" for baseline, the kb entry's public id otherwise. Leads move status
-- new -> acknowledged -> applied (or -> dismissed) through the /policy router; the
-- 'applied' closed-loop overlay write lands in a LATER chunk.
create table if not exists public.recommendations (
  id               uuid primary key default gen_random_uuid(),
  kb_entry_id      uuid references public.kb_entries (id) on delete set null,  -- internal link (null for baseline)
  kb_ref           text not null default '',           -- public kbId snapshot (contract `kbId`)
  title            text not null,
  why              text not null default '',
  action           text not null default '',
  scope            public.policy_scope not null default 'global',
  target_module    public.policy_target_module not null default 'audit',  -- contract `target`
  region           public.policy_region not null default 'global',
  region_label     text not null default '',           -- display label (contract `regionLabel`)
  status           public.rec_status not null default 'new',
  affected_clients text not null default '',            -- display list (contract `clients`)
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now()
);

create index if not exists recommendations_kb_entry_id_idx on public.recommendations (kb_entry_id);
create index if not exists recommendations_status_idx        on public.recommendations (status);
create index if not exists recommendations_created_at_idx    on public.recommendations (created_at desc);

create trigger recommendations_set_updated_at
  before update on public.recommendations
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Uniform across all four tables: any staff may READ (is_staff() excludes portal
-- clients, so there is no client select policy); only owner/admin/manager MANAGE.
-- The deferred WATCHER runs on service_role, which BYPASSes these policies - it is
-- the only writer to sources/changes/kb in production, and the closed loop / manual
-- confirm is the lead-only write here. No delete policy in v1.
alter table public.policy_sources enable row level security;
alter table public.policy_sources force row level security;
alter table public.change_events enable row level security;
alter table public.change_events force row level security;
alter table public.kb_entries enable row level security;
alter table public.kb_entries force row level security;
alter table public.recommendations enable row level security;
alter table public.recommendations force row level security;

create policy policy_sources_select on public.policy_sources
  for select using (public.is_staff());
create policy policy_sources_insert on public.policy_sources
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy policy_sources_update on public.policy_sources
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy change_events_select on public.change_events
  for select using (public.is_staff());
create policy change_events_insert on public.change_events
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy change_events_update on public.change_events
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy kb_entries_select on public.kb_entries
  for select using (public.is_staff());
create policy kb_entries_insert on public.kb_entries
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy kb_entries_update on public.kb_entries
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy recommendations_select on public.recommendations
  for select using (public.is_staff());
create policy recommendations_insert on public.recommendations
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy recommendations_update on public.recommendations
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
