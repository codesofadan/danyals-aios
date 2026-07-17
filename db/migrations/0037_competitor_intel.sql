-- 0037_competitor_intel.sql - Part 8 Phase 2C (Competitor Intel): the per-client
-- competitor set + the keyword GAPS between each competitor and the client.
--
-- The competitor_intel tool answers three questions a client actually asks: who else
-- is winning our terms, what are they ranking for that we are not, and how much of
-- the visible market do we hold. It is deliberately built on top of what the platform
-- ALREADY paid for rather than a second pull:
--
--   * the COMPETITOR's ranked keywords come from the provider (DataForSEO Labs
--     `ranked_keywords` - Serper's /search cannot enumerate a domain's whole ranking
--     set, which is the one place this module leaves the house SERP vendor);
--   * the CLIENT's positions come FREE from the Rank Tracker's `tracked_keywords`
--     read model (0036). That reuse IS the design: a gap's `client_position` is a
--     column the client already pays for nightly, so re-buying it here would bill
--     them twice for the same fact.
--
--   * competitors  - one row per (client, domain). client_id is NOT NULL: a
--     competitor is always somebody's competitor - there is no un-owned competitive
--     set - and ON DELETE CASCADE means removing the client removes its rivals with
--     it rather than orphaning them. client_name is a display SNAPSHOT so client_id
--     never has to be surfaced. discovery_source records whether an analyst named the
--     domain (`manual`) or the SERP tally proposed it (`serp_auto`). overlap_pct /
--     keyword_gaps_count / share_of_voice / common_keywords are DENORMALISED
--     read-model columns rolled forward by the analysis worker so the board renders
--     without recomputing a Jaccard over every gap row.
--
--     `domain` is stored NORMALISED (host only, lowercased, `www.` and scheme
--     stripped - see service.normalize_domain). This is the same lesson 0036 learned
--     with `normalized_keyword`: without folding, "BrightSmile.com",
--     "www.brightsmile.com" and "https://brightsmile.com/" are three rows, three
--     analyses and three BILLS for one competitor.
--
--   * keyword_gaps - one row per (competitor, keyword): the analysed comparison.
--     client_position is NULLABLE and the NULL is LOAD-BEARING - it means the client
--     does NOT rank for the term at all (a PURE gap), which is the single most
--     valuable row in the table. It must never be coalesced to 0: position 0 does not
--     exist, and reading "not ranked" as "position 0" would rank a term the client
--     has never touched ahead of a #1 they own outright.
--
-- Both tables REUSE 0035's `public.search_intent` enum rather than declaring a
-- second, drifting copy: a gap's intent means exactly what a bank keyword's intent
-- means, and `promote` writes a gap straight into the `keywords` bank
-- (source='gap'), where a divergent enum would be an immediate cast error.
--
-- Shapes are SERVER-AUTHORITATIVE (no frontend/lib type mirrors this module); the
-- module's schemas.py owns the wire shape and its own shape/enum unit tests.
--
-- RLS mirrors 0035/0036 exactly: any STAFF may READ (is_staff()); only LEADS
-- (owner/admin/manager) may INSERT/UPDATE. Clients get NO policy on either table -
-- competitor intelligence is agency analysis, not a client deliverable, and the rows
-- carry another business's ranking data. The analysis worker writes on service_role
-- (BYPASSRLS) via ServiceCompetitorStore. No delete policy in v1.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'discovery_source') then
    -- How the competitor entered the set: an analyst named it, or the SERP tally
    -- proposed it. Kept distinct so an auto-proposed rival is never mistaken for a
    -- human's considered judgement about who the client actually competes with.
    create type public.discovery_source as enum ('manual', 'serp_auto');
  end if;
  if not exists (select 1 from pg_type where typname = 'gap_type') then
    -- missing  - the client does not rank for the term at all (client_position NULL).
    -- untapped - a `missing` term with real demand behind it (volume >= the module's
    --            untapped threshold): the subset worth acting on first.
    -- weak     - BOTH rank, but the competitor outranks the client.
    -- shared   - both rank and the client is level or ahead (the overlap evidence).
    create type public.gap_type as enum ('missing', 'weak', 'shared', 'untapped');
  end if;
end $$;

-- Human-friendly stable code (CI-0001 ...), like the other module code sequences.
create sequence if not exists public.competitor_code_seq;

-- --- Competitors: the per-client competitive set -------------------------------
create table if not exists public.competitors (
  id                 uuid primary key default gen_random_uuid(),
  code               text not null unique
                     default 'CI-' || to_char(nextval('public.competitor_code_seq'), 'FM0000'),
  -- NOT NULL: a competitor is always somebody's competitor. ON DELETE CASCADE ends
  -- the competitive set with the client rather than orphaning rows nobody owns.
  client_id          uuid not null references public.clients (id) on delete cascade,
  client_name        text not null default '',
  -- NORMALISED host (see the header). NOT NULL: every operation this module performs
  -- - SERP matching, ranked-keyword pulls, the backlink gap - keys on the domain, so
  -- a competitor without one cannot be analysed at all.
  domain             text not null,
  label              text not null default '',
  discovery_source   public.discovery_source not null default 'manual',
  -- A proposed-but-not-yet-vetted rival can be parked with tracked=false: it stays in
  -- the set (so the SERP tally does not re-propose it every run) without joining the
  -- share-of-voice denominator or costing an analysis.
  tracked            boolean not null default true,
  -- The denormalised read model, rolled forward by run_gap_analysis.
  overlap_pct        numeric(5,2) not null default 0 check (overlap_pct between 0 and 100),
  keyword_gaps_count integer not null default 0,
  share_of_voice     numeric(5,2) not null default 0,
  common_keywords    integer not null default 0,
  last_analyzed_at   timestamptz,
  created_by         uuid references public.users (id) on delete set null,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now(),
  -- One row per (client, domain). NULLS NOT DISTINCT (PG15+; we deploy PG16) is the
  -- HOUSE RULE for every uniqueness key in this schema, and it is spelled out here
  -- because this exact defect has already been found and fixed TWICE (0035's bank
  -- key, then 0036's subscription key). Under default SQL NULL semantics every NULL
  -- is DISTINCT, so any nullable member silently admits a duplicate that
  -- `on conflict do nothing` can never catch - and a duplicate competitor is a
  -- duplicate PAID analysis. Both members are NOT NULL today, so this is currently
  -- belt-and-braces; it stays because the cost is zero and the failure it prevents
  -- reappears the moment either column is relaxed.
  unique nulls not distinct (client_id, domain)
);

create index if not exists competitors_client_id_idx on public.competitors (client_id);

create trigger competitors_set_updated_at
  before update on public.competitors
  for each row execute function public.set_updated_at();

-- --- Keyword gaps: the analysed competitor-vs-client comparison ----------------
create table if not exists public.keyword_gaps (
  id                  uuid primary key default gen_random_uuid(),
  competitor_id       uuid not null references public.competitors (id) on delete cascade,
  -- DENORMALISED so a client-scoped gap read / share-of-voice roll-up never has to
  -- join back through competitors (and so the client filter stays one index scan).
  client_id           uuid not null references public.clients (id) on delete cascade,
  keyword             text not null,
  volume              integer not null default 0,
  difficulty          numeric(5,2) not null default 0 check (difficulty between 0 and 100),
  -- REUSES 0035's enum (see the header): a gap's intent is the same fact as a bank
  -- keyword's intent, and `promote` writes this value straight into public.keywords.
  intent              public.search_intent,
  competitor_position integer,
  -- NULL IS LOAD-BEARING: the client does not rank for this term at all - a PURE gap
  -- and the most valuable row here. Never coalesce it to 0 (see the header).
  client_position     integer,
  gap_type            public.gap_type not null default 'missing',
  opportunity         numeric(5,2) not null default 0,
  -- Set ONCE the gap is promoted into the bank, so a second promote is a no-op and
  -- the board can show "already banked". ON DELETE SET NULL: dropping the banked
  -- keyword returns the gap to un-promoted rather than deleting the analysis.
  keyword_id          uuid references public.keywords (id) on delete set null,
  analyzed_at         timestamptz,
  created_at          timestamptz not null default now(),
  -- One row per (competitor, keyword) - the idempotency key that makes a redelivered
  -- analysis an UPSERT instead of a duplicate gap set. NULLS NOT DISTINCT per the
  -- house rule above.
  unique nulls not distinct (competitor_id, keyword)
);

create index if not exists keyword_gaps_client_id_idx     on public.keyword_gaps (client_id);
create index if not exists keyword_gaps_competitor_id_idx on public.keyword_gaps (competitor_id);

-- NOTE: no `updated_at` column and therefore no set_updated_at trigger, unlike
-- `competitors` above. A gap row is not edited; it is RE-ANALYSED, and `analyzed_at`
-- is the honest freshness stamp for that (it records when the comparison was last
-- computed, which an updated_at touched by an unrelated column write would not).

-- --- The competitor dimension on the EXISTING backlink ledger ------------------
-- The backlink GAP ("referring domains that link to my rivals but not to me") needs
-- to know WHICH domain a monitored link points at. 0018's `backlinks` is strictly
-- client-scoped - one row per (client, ref_domain) with no target dimension at all -
-- so as it stands the ledger physically cannot express "this domain links to
-- competitor X". Rather than stand up a second, divergent backlink table, the ledger
-- is REUSED and given the missing dimension: a NULL competitor_id means what every
-- existing row means (a link to the CLIENT's own site); a set competitor_id marks the
-- row as a link to that competitor.
--
-- HONEST STATUS: nothing populates competitor-side rows yet. The off-page monitor
-- (7B-3) only pulls the client's own profile, and pulling a competitor's is a NEW
-- PAID provider call that Phase 2C does not buy. So `GET /backlink-gaps` reads this
-- ledger, costs zero, and returns an honestly EMPTY gap set until such an ingest
-- lands - which is the correct behaviour: the alternative (presenting other clients'
-- referring domains as "your competitors' links") would fabricate a fact.
--
-- INVARIANT for whoever adds that ingest: every existing off-page read
-- (app/db/offpage_repo.py) is unfiltered on this column and correct ONLY while it is
-- NULL everywhere. The moment competitor rows are written, those reads MUST add
-- `competitor_id is null` or the client's backlink board will silently show its
-- rivals' links as its own.
alter table public.backlinks
  add column if not exists competitor_id uuid
  references public.competitors (id) on delete cascade;

-- PARTIAL: competitor-side rows are the minority (and today, none), so the index
-- stays as small as the set it actually serves.
create index if not exists backlinks_competitor_id_idx
  on public.backlinks (competitor_id)
  where competitor_id is not null;

-- --- RLS ---------------------------------------------------------------------
-- Clients are excluded by is_staff() (they get NO base-table select policy), so no
-- portal user can read the competitive set - these rows carry another business's
-- ranking data and the agency's own analysis. Any staff may READ; only leads
-- (owner/admin/manager) may INSERT/UPDATE, mirroring 0035/0036 byte-for-byte. The
-- analysis worker ingest runs on service_role (BYPASSRLS). No delete policy in v1.
alter table public.competitors enable row level security;
alter table public.competitors force row level security;
alter table public.keyword_gaps enable row level security;
alter table public.keyword_gaps force row level security;

create policy competitors_select on public.competitors
  for select using (public.is_staff());
create policy competitors_insert on public.competitors
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy competitors_update on public.competitors
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy keyword_gaps_select on public.keyword_gaps
  for select using (public.is_staff());
create policy keyword_gaps_insert on public.keyword_gaps
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy keyword_gaps_update on public.keyword_gaps
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
