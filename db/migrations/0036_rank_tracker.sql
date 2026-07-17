-- 0036_rank_tracker.sql - Part 8 Phase 2B (Rank Tracker): the tracked-keyword
-- SUBSCRIPTION list + its append-only ranking history.
--
-- The rank_tracker tool is the platform's first STANDING per-client cost: audits and
-- content are on-demand, but a tracked keyword is re-checked nightly FOREVER, and the
-- rank-check API bill is the CLIENT's. So a keyword here is a subscription, not a
-- lookup - which is why the module gates the monthly COMMITMENT at configuration time
-- (`project_monthly_cost`) as well as every individual check (the R5 pre-check).
--
--   * tracked_keywords - one row per (client, keyword, engine, device, location,
--     language): the subscription. client_id is NOT NULL (unlike 0035's keyword BANK,
--     a tracked keyword is always somebody's standing spend - there is no such thing
--     as an un-owned nightly bill). client_name is a display SNAPSHOT so client_id
--     never has to be surfaced. cadence + next_check_on drive the nightly dispatcher;
--     status pauses a subscription without losing its history. latest_position /
--     previous_position / best_position are DENORMALISED read-model columns rolled
--     forward by the check worker so the board renders without touching history.
--
--     latest_position NULL is MEANINGFUL and load-bearing: it means "successfully
--     checked, not found in the top-N" (unranked). It does NOT mean "the check
--     failed" - a provider error writes no history row and leaves the previous
--     position untouched (see the CRITICAL note on keyword_rankings below).
--
--   * keyword_rankings - the append-only daily history (one snapshot per keyword per
--     day, enforced by `unique (keyword_id, checked_on)`, which is what makes a Celery
--     redelivery a no-op instead of a double-charge). own_urls holds EVERY same-domain
--     hit in the SERP, so the module can flag cannibalization (two of the client's own
--     pages competing for one term) rather than only the best one. cost records what
--     the client was actually charged for that check.
--
-- NO PARTITIONING - deliberate. At the contracted scale (~1k tracked keywords x
-- ~275 checks/yr ~= 275k rows/yr) a partitioned table buys nothing an index does not,
-- and it would add a month-rollover failure mode (a missing future partition turns
-- every insert into an error at midnight on the 1st). Retention is handled instead by
-- the `rollup_rank_history` beat task, which is observable and has no cliff.
--
-- NO geo-grid / Local-Falcon grid tracking - out of scope by contract (a different
-- module owns basic local map-pack); `location` here is a single SERP locale string,
-- never a lat/lng grid.
--
-- Shapes are SERVER-AUTHORITATIVE (no frontend/lib type mirrors this module); the
-- module's schemas.py owns the wire shape and its own shape/enum unit tests.
--
-- RLS mirrors 0035_keyword_research: any STAFF may READ (is_staff()); only LEADS
-- (owner/admin/manager) may INSERT/UPDATE. keyword_rankings gets NO update/delete
-- policy at all - it is append-only history, and a rewritable rank history is a
-- falsifiable one. The check worker writes on service_role (BYPASSRLS) via
-- ServiceRankStore; the retention job's DELETEs likewise run as service_role, which
-- bypasses POLICIES (so the missing delete policy constrains staff, not the sweeper).
--
-- Clients get NO base-table policy (the base rows carry `cost` and `client_id`);
-- they read through the `portal_rank_keywords` security-barrier view instead, exactly
-- like the 0010 portal_* views.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'rank_engine') then
    create type public.rank_engine as enum ('google', 'bing');
  end if;
  if not exists (select 1 from pg_type where typname = 'rank_device') then
    create type public.rank_device as enum ('desktop', 'mobile', 'tablet');
  end if;
  if not exists (select 1 from pg_type where typname = 'rank_status') then
    create type public.rank_status as enum ('active', 'paused');
  end if;
  if not exists (select 1 from pg_type where typname = 'rank_cadence') then
    create type public.rank_cadence as enum ('daily', 'weekly');
  end if;
end $$;

-- Human-friendly stable code (RK-00001 ...), like the other module code sequences.
create sequence if not exists public.rank_keyword_code_seq;

-- --- Tracked keywords: the subscription list ---------------------------------
create table if not exists public.tracked_keywords (
  id                 uuid primary key default gen_random_uuid(),
  code               text not null unique
                     default 'RK-' || to_char(nextval('public.rank_keyword_code_seq'), 'FM00000'),
  -- NOT NULL: a tracked keyword is a standing per-client cost, so it always belongs
  -- to a tenant. ON DELETE CASCADE: removing the client ends the subscription (and
  -- its history) rather than orphaning a nightly bill nobody owns.
  client_id          uuid not null references public.clients (id) on delete cascade,
  client_name        text not null default '',
  site_id            uuid references public.sites (id) on delete set null,
  keyword            text not null,
  -- The case/whitespace-folded form the uniqueness key uses, so "Plumber " and
  -- "plumber" are ONE subscription (and one bill), not two.
  normalized_keyword text not null default '',
  target_url         text not null default '',
  engine             public.rank_engine not null default 'google',
  device             public.rank_device not null default 'desktop',
  location           text not null default '',
  location_code      integer,
  language           text not null default 'en',
  country            text not null default 'us',
  tags               text[] not null default '{}',
  cadence            public.rank_cadence not null default 'weekly',
  status             public.rank_status not null default 'active',
  search_volume      integer,
  cpc                numeric(10,2),
  -- The denormalised read model. latest_position NULL = checked, NOT in the top-N
  -- (unranked) - never "the check errored".
  latest_position    integer,
  latest_url         text not null default '',
  previous_position  integer,
  best_position      integer,
  best_position_at   date,
  latest_features    text[] not null default '{}',
  latest_checked_at  timestamptz,
  next_check_on      date,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  -- One subscription per (client, keyword, engine, device, location, language).
  -- NULLS NOT DISTINCT (PG15+; we deploy PG16) makes NULL = NULL for uniqueness, so
  -- the OPTIONAL columns still dedupe. Under default SQL NULL semantics every NULL is
  -- DISTINCT, so a row with a NULL member would silently admit a duplicate that
  -- `on conflict do nothing` could never catch - and a duplicate subscription is a
  -- duplicate nightly CHARGE. This exact defect was already found and fixed once in
  -- 0035; it is spelled out here so it is not reintroduced a third time.
  unique nulls not distinct (client_id, normalized_keyword, engine, device, location, language)
);

create index if not exists tracked_keywords_client_id_idx
  on public.tracked_keywords (client_id);

-- The nightly dispatcher's claim predicate. PARTIAL on status='active' so a paused
-- subscription costs nothing to skip and the index stays as small as the live set.
create index if not exists tracked_keywords_due_idx
  on public.tracked_keywords (next_check_on)
  where status = 'active';

-- The board's default ordering (a client's best positions first).
create index if not exists tracked_keywords_client_position_idx
  on public.tracked_keywords (client_id, latest_position);

create index if not exists tracked_keywords_tags_idx
  on public.tracked_keywords using gin (tags);

create trigger tracked_keywords_set_updated_at
  before update on public.tracked_keywords
  for each row execute function public.set_updated_at();

-- --- Ranking history: append-only --------------------------------------------
create table if not exists public.keyword_rankings (
  id            uuid primary key default gen_random_uuid(),
  keyword_id    uuid not null references public.tracked_keywords (id) on delete cascade,
  -- Denormalised so a history read / retention sweep never has to join back to the
  -- subscription (and so a client-scoped report stays one index scan).
  client_id     uuid,
  checked_on    date not null,
  -- NULL = successfully checked, not in the top-N (unranked). A provider FAILURE
  -- writes NO row here at all - writing one with position NULL would fabricate a
  -- phantom "lost ranking" and fire a false alert.
  position      integer,
  ranking_url   text not null default '',
  serp_features text[] not null default '{}',
  -- EVERY same-domain hit in the SERP, not just the best one -> cannibalization.
  own_urls      jsonb not null default '[]',
  delta         integer,
  provider      text not null default '',
  cost          numeric(12,6) not null default 0,
  created_at    timestamptz not null default now(),
  -- ONE snapshot per keyword per day. This is the idempotency key that makes a
  -- Celery redelivery a no-op (`on conflict (keyword_id, checked_on) do nothing`).
  unique (keyword_id, checked_on)
);

create index if not exists keyword_rankings_keyword_checked_idx
  on public.keyword_rankings (keyword_id, checked_on desc);

create index if not exists keyword_rankings_client_checked_idx
  on public.keyword_rankings (client_id, checked_on);

-- --- RLS ---------------------------------------------------------------------
alter table public.tracked_keywords enable row level security;
alter table public.tracked_keywords force row level security;
alter table public.keyword_rankings enable row level security;
alter table public.keyword_rankings force row level security;

create policy tracked_keywords_select on public.tracked_keywords
  for select using (public.is_staff());
create policy tracked_keywords_insert on public.tracked_keywords
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy tracked_keywords_update on public.tracked_keywords
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- History is READ-ONLY to every app role: a select policy and an insert policy for
-- leads, and DELIBERATELY no update/delete policy. Rank history is evidence a client
-- is billed against; it must not be editable from the app tier. The check worker and
-- the retention sweep both run as service_role, which bypasses policies.
create policy keyword_rankings_select on public.keyword_rankings
  for select using (public.is_staff());
create policy keyword_rankings_insert on public.keyword_rankings
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- The client read surface = a SECURITY-BARRIER VIEW (mirrors 0010) ---------
-- Clients have NO select policy on either base table, so this view is their entire
-- rank-tracking surface. It exposes only display columns and self-filters by
-- current_client_id(). EXCLUDES client_id, site_id, cost, provider, next_check_on and
-- every other operational/billing column: a client may see WHERE they rank, never
-- what the agency pays to find out.
create or replace view public.portal_rank_keywords
  with (security_barrier = true) as
  select
    code,
    keyword,
    target_url,
    engine::text  as engine,
    device::text  as device,
    location,
    tags,
    status::text  as status,
    latest_position   as position,
    previous_position,
    best_position,
    latest_url,
    latest_checked_at
  from public.tracked_keywords
  where client_id = public.current_client_id();

comment on view public.portal_rank_keywords is
  'Client-safe view of public.tracked_keywords, self-filtered to current_client_id(). No client_id/site_id/cost/provider/scheduling columns.';

grant select on public.portal_rank_keywords to authenticated, anon;
