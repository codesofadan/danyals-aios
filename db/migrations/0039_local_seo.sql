-- 0039_local_seo.sql - Part 8 Phase 2E (Local SEO): the map-pack RANK tracker +
-- the GBP PROFILE ledger.
--
-- The local_seo tool is the local-search surface: per client LOCATION (a GBP
-- profile) it tracks where the business sits in Google's local pack for a keyword,
-- audits the profile's completeness / categories / NAP, and reads the citation
-- consistency KPI off the EXISTING 0018 `citations` ledger (this migration does NOT
-- create a second citations table - the off-page module owns that one).
--
--   * gbp_profiles      - one row per client LOCATION. location_label is the
--     `[Location]` display column; client_name is a display SNAPSHOT so client_id
--     never has to be surfaced. google_location_id / place_id are the provider
--     handles. The NAP triple + categories + hours + website are the audited
--     fields; completeness_score (0-100) + audit (per-field findings) are DERIVED
--     by the service's deterministic checklist. oauth_connected/oauth_vault_ref
--     record that a per-client Google refresh token was sealed IN THE VAULT -
--     the ref is a POINTER (a vault key id); the SECRET ITSELF NEVER LANDS HERE.
--   * local_rankings    - the CURRENT map-pack state, ONE row per
--     (profile, keyword, geo). `geo` is a SINGLE representative locale, NOT a grid
--     point: this module deliberately tracks one position per keyword/location and
--     has NO geo-grid / lat-lng fan-out / heatmap (out of contract scope). `rank`
--     is NULLABLE and NULL means "checked successfully, NOT found in the local
--     pack" - it is never written for a provider ERROR (that would fabricate a
--     phantom ranking loss); in_map_pack is the top-3 flag; top_competitors is the
--     top-3 pack names, which is how displacement is trended WITHOUT a grid.
--   * local_rank_history - the APPEND-ONLY rank timeline (one row per successful
--     check) the history endpoint charts. No update/delete policy: history is
--     immutable by construction.
--
-- Shapes are SERVER-AUTHORITATIVE (no frontend/lib type mirrors this module); the
-- module's schemas.py owns the wire shape and its own shape/enum unit tests. The
-- `[Location]|[Client]|[Keyword]|[Rank]` cells ARE what the tool workspace renders.
--
-- SCOPE GUARD (pinned by tests/modules/local_seo/test_schemas.py): GBP here is
-- PROFILE MANAGEMENT + NAP, READ-ONLY. There are deliberately NO `gbp_posts` and
-- NO `gbp_review_replies` tables - GBP posting and auto review-replies are NOT in
-- the contract and must not be re-introduced by a later migration.
--
-- RLS mirrors 0018_offpage / 0035_keyword_research exactly: any STAFF may READ
-- (is_staff()); only LEADS (owner/admin/manager) may INSERT/UPDATE. Clients get NO
-- base-table policy, so the whole local surface is staff-only. The refresh worker
-- writes on service_role (BYPASSRLS) via ServiceLocalStore. No delete policy in v1.

-- --- GBP profiles: the per-location ledger ------------------------------------
-- Declared BEFORE local_rankings so local_rankings.profile_id can reference it.
create table if not exists public.gbp_profiles (
  id                   uuid primary key default gen_random_uuid(),
  client_id            uuid not null references public.clients (id) on delete cascade,
  client_name          text not null default '',
  -- The `[Location]` column the workspace renders (e.g. 'Karachi', 'Downtown').
  location_label       text not null,
  -- Provider handles: the GBP API location resource + the Places/Maps id the
  -- map-pack provider matches the client's own listing against.
  google_location_id   text,
  place_id             text,
  primary_category     text not null default '',
  secondary_categories text[] not null default '{}',
  -- The audited NAP triple. This profile is the CANONICAL NAP; the 0018 citations
  -- ledger records each directory's verdict against it.
  nap_name             text not null default '',
  nap_address          text not null default '',
  nap_phone            text not null default '',
  website_uri          text not null default '',
  regular_hours        jsonb not null default '{}',
  review_count         integer not null default 0,
  avg_rating           numeric(2,1),
  -- DERIVED by service.profile_completeness (a deterministic checklist), never
  -- provider-supplied: 0-100 with the per-field findings in `audit`.
  completeness_score   integer not null default 0
                       check (completeness_score between 0 and 100),
  audit                jsonb not null default '{}',
  -- oauth_vault_ref POINTS at the sealed per-client refresh token (a vault key id).
  -- The token itself lives ONLY in public.vault_keys, AES-GCM sealed. Never store a
  -- secret in this table.
  oauth_connected      boolean not null default false,
  oauth_vault_ref      text,
  last_synced_at       timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create index if not exists gbp_profiles_client_id_idx on public.gbp_profiles (client_id);

create trigger gbp_profiles_set_updated_at
  before update on public.gbp_profiles
  for each row execute function public.set_updated_at();

-- --- Local rankings: the CURRENT map-pack state -------------------------------
create table if not exists public.local_rankings (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references public.clients (id) on delete cascade,
  client_name     text not null default '',
  profile_id      uuid not null references public.gbp_profiles (id) on delete cascade,
  keyword         text not null,
  -- The SINGLE representative locale this keyword is checked at (e.g. 'Karachi, PK').
  -- NOT a grid point - there is no lat/lng fan-out anywhere in this module.
  geo             text,
  -- NULLABLE BY DESIGN. NULL = "checked, not present in the local pack" (an honest
  -- absence). A provider ERROR must write NO row at all - see workers/tasks: writing
  -- a failure as NULL would fabricate a ranking loss the business never suffered.
  rank            integer,
  previous_rank   integer,
  rank_change     integer not null default 0,
  in_map_pack     boolean not null default false,   -- top-3
  found_url       text not null default '',
  -- The top-3 pack names at the last check: trends WHO displaces the client without
  -- needing a geo-grid.
  top_competitors jsonb not null default '[]',
  provider        text not null default '',
  is_active       boolean not null default true,
  last_checked_at timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  -- One row per (profile, keyword, geo). NULLS NOT DISTINCT (PG15+) makes NULL =
  -- NULL for uniqueness so a geo-less row (geo NULL = the profile's default locale)
  -- dedupes exactly like a geo-scoped one. Under DEFAULT SQL NULL semantics every
  -- NULL is distinct, so the constraint would never fire for a geo-less row and
  -- `on conflict (profile_id, keyword, geo)` could never catch the duplicate - the
  -- exact class of bug already fixed once in 0035_keyword_research.
  unique nulls not distinct (profile_id, keyword, geo)
);

create index if not exists local_rankings_client_id_idx  on public.local_rankings (client_id);
create index if not exists local_rankings_profile_id_idx on public.local_rankings (profile_id);
-- The refresh worker's claim predicate (active rows, oldest check first).
create index if not exists local_rankings_active_idx
  on public.local_rankings (is_active, last_checked_at);

create trigger local_rankings_set_updated_at
  before update on public.local_rankings
  for each row execute function public.set_updated_at();

-- --- Local rank history: the APPEND-ONLY timeline ------------------------------
create table if not exists public.local_rank_history (
  id          uuid primary key default gen_random_uuid(),
  ranking_id  uuid not null references public.local_rankings (id) on delete cascade,
  client_id   uuid not null references public.clients (id) on delete cascade,
  rank        integer,          -- NULL = checked, not in the pack (never an error)
  in_map_pack boolean not null default false,
  provider    text not null default '',
  checked_at  timestamptz not null default now()
);

-- The history endpoint's access path: one ranking's timeline, newest first.
create index if not exists local_rank_history_ranking_idx
  on public.local_rank_history (ranking_id, checked_at desc);

-- --- RLS ---------------------------------------------------------------------
-- Clients are excluded by is_staff() (they get NO base-table select policy), so a
-- portal client can NOT read the local surface. Any staff may READ; only leads
-- (owner/admin/manager) may INSERT/UPDATE - which the router's require_role gate
-- mirrors byte-for-byte, so a caller who passes the app gate is never rejected by
-- Postgres with an opaque RLS error. The refresh worker runs on service_role
-- (BYPASSRLS). No delete policy in v1.
alter table public.gbp_profiles enable row level security;
alter table public.gbp_profiles force row level security;
alter table public.local_rankings enable row level security;
alter table public.local_rankings force row level security;
alter table public.local_rank_history enable row level security;
alter table public.local_rank_history force row level security;

create policy gbp_profiles_select on public.gbp_profiles
  for select using (public.is_staff());
create policy gbp_profiles_insert on public.gbp_profiles
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy gbp_profiles_update on public.gbp_profiles
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy local_rankings_select on public.local_rankings
  for select using (public.is_staff());
create policy local_rankings_insert on public.local_rankings
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy local_rankings_update on public.local_rankings
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- APPEND-ONLY: a select policy for staff + an insert policy for leads, and
-- DELIBERATELY no update/delete policy - a rank timeline that could be rewritten is
-- not evidence. The worker appends on service_role.
create policy local_rank_history_select on public.local_rank_history
  for select using (public.is_staff());
create policy local_rank_history_insert on public.local_rank_history
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
