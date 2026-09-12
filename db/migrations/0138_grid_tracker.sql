-- 0138_grid_tracker.sql - LOCAL SEARCH GRID TRACKING: where a business ranks in
-- Google's map pack ACROSS its service area, not at one representative point.
--
-- WHY THIS IS A SEPARATE MODULE AND NOT AN EXTENSION OF 0039.
-- `0039_local_seo` deliberately tracks ONE position per (profile, keyword, geo) and
-- says so in three docstrings and two scope-guard tests. That guard is CORRECT and
-- stays: `local_rankings` answers "where do we sit in this market", which is a
-- different, cheaper question than "where does our visibility fall off, and in which
-- direction". Widening 0039 would have made every existing local-pack row ambiguous
-- about whether it was one probe or an aggregate. So the grid gets its own tables,
-- its own money dial and its own worker, and 0039 keeps its promise unchanged.
--
-- THE COST SHAPE IS THE WHOLE DESIGN. One grid run is `points` PAID map-pack reads -
-- a 5x5 grid is 25 provider calls, not one. Everything below exists to make that
-- cost visible, bounded and attributable BEFORE it is spent:
--   * geometry lives on the DEFINITION (not on the run), so the point count - and
--     therefore the bill - is knowable and reviewable before anything is queued;
--   * `point_count` is a GENERATED column, so the estimate cannot drift from what
--     the worker will actually probe;
--   * a hard CHECK ceiling on rings/radius makes a 10,000-point request
--     unrepresentable rather than merely discouraged.
--
--   * grid_definitions - one standing grid per (profile, keyword). Geometry is a
--     CENTER (lat/lng) + concentric RINGS at a spacing, which is the shape a service
--     area actually has; the center is stored HERE rather than read from the profile
--     at run time so a re-run months later reproduces the same grid even if the
--     profile's address was edited. Center coordinates are resolved once at creation
--     from the profile's Places anchor, or entered by the operator - NEVER guessed
--     from a postal address at probe time.
--   * grid_runs - one execution. Summary counters are DERIVED from the points and
--     exist only so a list view does not aggregate 25 rows per card.
--   * grid_points - one row per probe. THE EVIDENCE. Append-only.
--
-- THE THREE-STATE POINT CONTRACT (the reason this table is not modelled like 0039).
-- 0039 writes NOTHING on a provider error, because one failed check simply means "no
-- observation today". A GRID cannot do that: dropping the 3 points that failed out of
-- a 25-point run silently changes the shape of the heat map and quietly improves
-- every statistic computed from it. So a point is explicitly one of:
--
--   'ranked'  - measured, found in the pack. `rank` IS NOT NULL (1..N).
--   'absent'  - measured, NOT in the pack. An honest, chartable observation. rank NULL.
--   'error'   - NOT MEASURED. The probe failed. rank NULL, `error` carries the reason.
--
-- A CHECK binds `rank` to the status so the three cannot blur: 'ranked' REQUIRES a
-- rank, the other two FORBID one. That is what stops a failed probe from ever being
-- read as "dropped out of the map pack" - the precise fabrication 0039's null
-- contract exists to prevent, restated for a shape that must keep its gaps.
--
-- Consequently every derived statistic divides by MEASURED points (ranked + absent),
-- never by total points: a run where the provider rate-limited 8 of 25 probes reports
-- coverage over the 17 it actually saw, and reports the 8 as unmeasured. A run is
-- `degraded`, never `completed`, when any point errored.
--
-- Shapes are SERVER-AUTHORITATIVE (no frontend/lib type mirrors this module, exactly
-- like 0039); the module's schemas.py owns the wire shape and its own unit tests.
--
-- RLS mirrors 0039 byte-for-byte: any STAFF may READ (is_staff()); only LEADS
-- (owner/admin/manager) may INSERT/UPDATE. Clients get NO base-table policy. The
-- worker writes on service_role (BYPASSRLS). No delete policy in v1.

-- --- Grid definitions: the standing grid ---------------------------------------
create table if not exists public.grid_definitions (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references public.clients (id) on delete cascade,
  -- Display SNAPSHOT, exactly as 0039 does it, so client_id never has to be surfaced.
  client_name     text not null default '',
  -- The LOCATION this grid is centred on. 0039 owns the location ledger; this module
  -- reads it and does not fork it.
  profile_id      uuid not null references public.gbp_profiles (id) on delete cascade,
  keyword         text not null check (length(keyword) between 1 and 200),

  -- --- geometry -------------------------------------------------------------
  -- Resolved ONCE at creation (Places anchor or operator entry) and then frozen, so
  -- a run in March and a run in September probe the same physical points and are
  -- therefore comparable. Bounds are the real WGS84 ranges - a swapped lat/lng pair
  -- is the classic defect here and a longitude of 140 in the latitude column fails.
  center_lat      double precision not null check (center_lat between -90 and 90),
  center_lng      double precision not null check (center_lng between -180 and 180),
  -- How the center was established, for evidence. 'places' = resolved from the
  -- profile's Places anchor; 'operator' = a human typed it.
  center_source   text not null default 'operator'
                  check (center_source in ('places', 'operator')),

  -- Concentric rings of 8 compass points each, plus the center: a grid of `rings`
  -- rings holds 1 + 8*rings points. The ceiling is deliberate and low - 5 rings is
  -- 41 paid probes per keyword per run.
  rings           integer not null default 2 check (rings between 1 and 5),
  -- Distance between rings. A service area is measured in kilometres, not degrees;
  -- the worker converts to a lat/lng offset per point.
  ring_spacing_km numeric(5,2) not null default 1.50
                  check (ring_spacing_km between 0.10 and 50.00),
  -- GENERATED, not stored by the caller: the estimate and the probe count cannot
  -- disagree, because there is only one of them.
  point_count     integer generated always as (1 + 8 * rings) stored,

  is_active       boolean not null default true,
  last_run_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  -- One standing grid per (profile, keyword). A second grid for the same keyword at
  -- the same location would double the bill and produce two disagreeing heat maps.
  unique (profile_id, keyword)
);

create index if not exists grid_definitions_client_id_idx
  on public.grid_definitions (client_id);
create index if not exists grid_definitions_profile_id_idx
  on public.grid_definitions (profile_id);
-- The dispatcher's claim predicate (active grids, least-recently-run first).
create index if not exists grid_definitions_active_idx
  on public.grid_definitions (is_active, last_run_at);

create trigger grid_definitions_set_updated_at
  before update on public.grid_definitions
  for each row execute function public.set_updated_at();

-- --- Grid runs: one execution --------------------------------------------------
create table if not exists public.grid_runs (
  id             uuid primary key default gen_random_uuid(),
  definition_id  uuid not null references public.grid_definitions (id) on delete cascade,
  client_id      uuid not null references public.clients (id) on delete cascade,

  -- Text + CHECK, never a new Postgres enum (55P04: a new enum label cannot be USED
  -- in the transaction that adds it, which is how a migration that looked correct
  -- fails on a fresh apply). Vocabulary mirrors the job contract's own terminal set
  -- so an operator reads one word in both places.
  status         text not null default 'queued'
                 check (status in ('queued', 'running', 'completed', 'degraded',
                                   'blocked', 'failed', 'cancelled')),
  -- Why a non-'completed' run ended that way. The job contract refuses to store a
  -- degraded/blocked/failed run without a reason; this mirrors that rule locally so
  -- the constraint holds even for a row written outside the contract.
  reason         text not null default '',

  -- The geometry AS RUN, copied from the definition at queue time. A definition
  -- edited next week must not silently rewrite the meaning of this run's points.
  center_lat      double precision not null,
  center_lng      double precision not null,
  rings           integer not null,
  ring_spacing_km numeric(5,2) not null,
  points_total    integer not null default 0,

  -- DERIVED counters, written once when the run finalises. `points_measured` is
  -- ranked + absent; `points_error` is what the provider never answered for. They
  -- are kept separate on purpose: every percentage in the UI divides by measured.
  points_ranked   integer not null default 0,
  points_absent   integer not null default 0,
  points_error    integer not null default 0,
  -- Mean position over RANKED points only (absent points have no position to average
  -- and error points were never seen). NULL when nothing ranked.
  avg_rank        numeric(4,1),
  -- Share of MEASURED points in the top 3. NULL when nothing was measured at all.
  share_top3      numeric(4,3) check (share_top3 is null or share_top3 between 0 and 1),

  provider        text not null default '',
  -- What this run actually cost, as logged through the cost gate. 0 for a blocked run.
  cost_usd        numeric(10,4) not null default 0,
  -- The job_runs correlation handle, so a run on this board and a run in the job
  -- ledger are the same thing rather than two stories.
  job_run_id      uuid,

  started_at      timestamptz,
  finished_at     timestamptz,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),

  -- The same rule the job contract enforces in `job_runs`: a non-clean terminal state
  -- cannot exist without a written reason. Bypassing the Python layer does not buy a
  -- silent failure.
  constraint grid_runs_reason_required_ck check (
    status not in ('degraded', 'blocked', 'failed') or length(trim(reason)) > 0
  )
);

create index if not exists grid_runs_definition_idx
  on public.grid_runs (definition_id, created_at desc);
create index if not exists grid_runs_client_id_idx on public.grid_runs (client_id);

create trigger grid_runs_set_updated_at
  before update on public.grid_runs
  for each row execute function public.set_updated_at();

-- --- Grid points: the evidence, append-only ------------------------------------
create table if not exists public.grid_points (
  id            uuid primary key default gen_random_uuid(),
  run_id        uuid not null references public.grid_runs (id) on delete cascade,
  client_id     uuid not null references public.clients (id) on delete cascade,

  -- Where this probe actually was. Stored per point rather than recomputed from the
  -- run's geometry so the evidence survives any later change to the ring maths.
  lat           double precision not null check (lat between -90 and 90),
  lng           double precision not null check (lng between -180 and 180),
  -- Human-readable position in the grid: 'center', 'N-1', 'NE-2' … (direction-ring).
  label         text not null default '',
  ring          integer not null default 0 check (ring >= 0),

  -- THE THREE-STATE CONTRACT. See the header: 'error' is NOT 'absent'.
  status        text not null
                check (status in ('ranked', 'absent', 'error')),
  rank          integer check (rank is null or rank between 1 and 100),
  -- The pack at this point, newest observation. Empty for absent/error.
  top_competitors jsonb not null default '[]',
  found_url     text not null default '',
  -- Set ONLY for status='error'; a short sanitized reason, never a raw exception or
  -- a credential-bearing URL.
  error         text not null default '',

  checked_at    timestamptz not null default now(),

  -- The binding that stops a failed probe reading as a ranking loss. 'ranked' must
  -- carry a position; 'absent' and 'error' must not - so no query can ever count an
  -- unmeasured point as a measured absence, whatever the application layer believes.
  constraint grid_points_rank_matches_status_ck check (
    (status = 'ranked' and rank is not null)
    or (status in ('absent', 'error') and rank is null)
  ),
  -- An error must say what went wrong, and a successful probe must not carry one.
  constraint grid_points_error_matches_status_ck check (
    (status = 'error' and length(trim(error)) > 0)
    or (status in ('ranked', 'absent') and error = '')
  ),
  -- One probe per point per run.
  unique (run_id, label)
);

-- The heat-map read: every point of one run.
create index if not exists grid_points_run_idx on public.grid_points (run_id);

-- --- RLS -----------------------------------------------------------------------
-- Identical to 0039: clients are excluded by is_staff() (no base-table select
-- policy), any staff may READ, only leads may INSERT/UPDATE, and the router's
-- require_role gate mirrors this byte-for-byte so a caller who passes the app gate is
-- never rejected by Postgres with an opaque RLS error. The worker runs on
-- service_role (BYPASSRLS). No delete policy in v1.
alter table public.grid_definitions enable row level security;
alter table public.grid_definitions force row level security;
alter table public.grid_runs enable row level security;
alter table public.grid_runs force row level security;
alter table public.grid_points enable row level security;
alter table public.grid_points force row level security;

create policy grid_definitions_select on public.grid_definitions
  for select using (public.is_staff());
create policy grid_definitions_insert on public.grid_definitions
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy grid_definitions_update on public.grid_definitions
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy grid_runs_select on public.grid_runs
  for select using (public.is_staff());
create policy grid_runs_insert on public.grid_runs
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy grid_runs_update on public.grid_runs
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- APPEND-ONLY, for the same reason 0039's rank history is: a heat map whose points
-- can be rewritten after the fact is not evidence. Staff select + lead insert, and
-- DELIBERATELY no update/delete policy. The worker appends on service_role.
create policy grid_points_select on public.grid_points
  for select using (public.is_staff());
create policy grid_points_insert on public.grid_points
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
