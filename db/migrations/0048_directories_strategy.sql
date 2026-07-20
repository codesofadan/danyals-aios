-- 0048_directories_strategy.sql - the STRATEGY layer on the citation catalog.
--
-- 0045/0046 gave every directory an AUTOMATION vocabulary (tier = how to submit).
-- The reference plan's actual SELECTION rules need a strategy vocabulary the catalog
-- did not carry: match the client's VERTICAL, build in AUTHORITY order, skip the
-- low-DA spam tail, treat aggregators + apply-gated locators as their own class, and
-- warn on lead-gen MARKETPLACES that compete for the client's own keywords. This
-- migration adds those five fields, backfills what is derivable in bulk, and enriches
-- the seeded niche rows with the reference plan's per-directory data.
--
-- All additive + idempotent: `add column if not exists`, and every UPDATE is keyed by
-- (name, market) so a re-run is a no-op and a row the seed does not (yet) contain is
-- silently skipped rather than erroring.

-- --- Columns ------------------------------------------------------------------
alter table public.directories
  -- Domain Authority proxy (0-100). NULLABLE on purpose: DA is directional and
  -- conflicts across tools (the reference plan says re-pull before quoting a client),
  -- so an un-scored row is honestly NULL, never a fabricated number.
  add column if not exists authority     smallint,
  -- Build ORDER, not authority score: core (global core + aggregators, build first
  -- everywhere) -> tier1 (the high-value workhorses / niche "build first") -> tier2
  -- (depth / reach). The selection query orders by this then authority desc.
  add column if not exists authority_tier text not null default 'tier2'
    check (authority_tier in ('core', 'tier1', 'tier2')),
  -- How a listing is OBTAINED, split out of the overloaded `manual_only` tier:
  -- open (self-serve form/API), apply_gated (association/manufacturer/editorial/sales
  -- - a human applies; often the HIGHEST value per the plan), aggregator (feeds
  -- downstream; reached via a platform, not a public form).
  add column if not exists access        text not null default 'open'
    check (access in ('open', 'apply_gated', 'aggregator')),
  -- Lead-gen marketplace: gives a citation but ALSO ranks for the client's keywords
  -- and usually charges (Angi, Zillow, ...). Surfaced so the operator opts in.
  add column if not exists is_marketplace boolean not null default false,
  -- Which verticals this directory serves (keys from citations/verticals.py). EMPTY
  -- = general (applies to every client); a niche directory names its verticals.
  add column if not exists verticals      text[] not null default '{}',
  -- Last time the catalog health-check confirmed the URL/form is live (P4). NULL =
  -- never verified; a stale row is a candidate for deactivation.
  add column if not exists last_verified  timestamptz;

create index if not exists directories_authority_tier_idx on public.directories (authority_tier);
create index if not exists directories_verticals_gin_idx  on public.directories using gin (verticals);

-- --- Derivable backfill (bulk, no per-row data) -------------------------------
-- The aggregator layer (push-once-fans-out, or fed-by another aggregator).
update public.directories set access = 'aggregator'
  where tier = 'aggregator' or submit_method like 'aggregator:%';
-- manual_only = no self-serve path at all: association / sales-rep / editorial /
-- portal-only signup -> apply-gated (a human onboards it).
update public.directories set access = 'apply_gated'
  where tier = 'manual_only';
-- The global core + aggregators are built first in EVERY market.
update public.directories set authority_tier = 'core' where market = 'GLOBAL';

-- --- Global core: Domain Authority (reference plan) ---------------------------
update public.directories set authority = 92 where name = 'Foursquare Places'          and market = 'GLOBAL';
update public.directories set authority = 93 where name = 'Bing Places for Business'    and market = 'GLOBAL';
update public.directories set authority = 99 where name = 'Apple Business Connect'      and market = 'GLOBAL';
update public.directories set authority = 95 where name = 'Facebook Business (Page)'    and market = 'GLOBAL';
update public.directories set authority = 93 where name = 'Yelp'                        and market = 'GLOBAL';
update public.directories set authority = 90 where name = 'OpenStreetMap'               and market = 'GLOBAL';
update public.directories set authority = 86 where name = 'HERE'                        and market = 'GLOBAL';
update public.directories set authority = 81 where name = 'TomTom'                      and market = 'GLOBAL';
update public.directories set authority = 92 where name = 'Waze'                        and market = 'GLOBAL';
update public.directories set authority = 77 where name = 'Yahoo Local'                 and market = 'GLOBAL';
update public.directories set authority = 95 where name = 'MapQuest'                    and market = 'GLOBAL';
update public.directories set authority = 89 where name = 'Superpages / YP Network (Thryv)' and market = 'GLOBAL';

-- --- US general: DA + tier1 promotion for the high-authority workhorses --------
update public.directories set authority = 92, authority_tier = 'tier1' where name = 'YellowPages.com'      and market = 'US';
update public.directories set authority = 87 where name = 'Manta'          and market = 'US';
update public.directories set authority = 88 where name = 'MerchantCircle' and market = 'US';
update public.directories set authority = 71 where name = 'Chamber of Commerce' and market = 'US';
update public.directories set authority = 73 where name = 'Hotfrog'        and market = 'US';
update public.directories set authority = 75 where name = 'ZoomInfo'       and market = 'US';

-- --- US niche: verticals + DA + marketplace + build-order ----------------------
-- Legal
update public.directories set verticals = '{legal}', authority = 90, authority_tier = 'tier1' where name = 'Justia (Lawyers)'    and market = 'US';
update public.directories set verticals = '{legal}', authority = 88, authority_tier = 'tier1' where name = 'FindLaw'             and market = 'US';
update public.directories set verticals = '{legal}',                 authority_tier = 'tier1' where name = 'Martindale-Hubbell'  and market = 'US';
update public.directories set verticals = '{legal}', authority = 74, authority_tier = 'tier1' where name = 'Avvo'                and market = 'US';
update public.directories set verticals = '{legal}'                                           where name = 'Super Lawyers'       and market = 'US';
update public.directories set verticals = '{legal}'                                           where name = 'HG.org'              and market = 'US';
update public.directories set verticals = '{legal}'                                           where name = 'Nolo / Lawyers.com'  and market = 'US';
-- Medical / dental / mental health
update public.directories set verticals = '{medical,dental}', authority = 69, authority_tier = 'tier1' where name = 'Healthgrades'   and market = 'US';
update public.directories set verticals = '{medical}', is_marketplace = true, authority_tier = 'tier1'  where name = 'Zocdoc'         and market = 'US';
update public.directories set verticals = '{medical,dental}', authority = 94, authority_tier = 'tier1' where name = 'WebMD / Vitals'  and market = 'US';
update public.directories set verticals = '{medical}'                                                  where name = 'RateMDs'        and market = 'US';
update public.directories set verticals = '{medical}'                                                  where name = 'Wellness.com'   and market = 'US';
update public.directories set verticals = '{medical}'                                                  where name = 'FindaTopDoc'    and market = 'US';
update public.directories set verticals = '{mental_health}', authority_tier = 'tier1'                  where name = 'Psychology Today' and market = 'US';
-- Home services (Houzz spans remodel/landscaping; Angi/HomeAdvisor/Thumbtack/Porch are marketplaces)
update public.directories set verticals = '{general_contractor,landscaping,home_services}', authority = 89, authority_tier = 'tier1' where name = 'Houzz'       and market = 'US';
update public.directories set verticals = '{hvac,plumbing,roofing,electrical,general_contractor,landscaping,pest_control,cleaning,locksmith,moving}', authority = 89, is_marketplace = true, authority_tier = 'tier1' where name = 'Angi (Angie''s List)' and market = 'US';
update public.directories set verticals = '{hvac,plumbing,roofing,electrical,general_contractor,landscaping,pest_control,cleaning,locksmith,moving}', authority = 78, is_marketplace = true, authority_tier = 'tier1' where name = 'HomeAdvisor'          and market = 'US';
update public.directories set verticals = '{hvac,plumbing,roofing,electrical,general_contractor,landscaping,pest_control,cleaning,locksmith,moving}', authority = 85, is_marketplace = true, authority_tier = 'tier1' where name = 'Thumbtack'            and market = 'US';
update public.directories set verticals = '{hvac,plumbing,roofing,electrical,general_contractor,landscaping,cleaning,moving}', authority = 76, is_marketplace = true                     where name = 'Porch'                and market = 'US';
update public.directories set verticals = '{general_contractor}'                              where name = 'BuildZoom'      and market = 'US';
update public.directories set verticals = '{general_contractor,landscaping}'                  where name = 'HomeStars'      and market = 'US';
update public.directories set verticals = '{general_contractor}'                              where name = 'The Blue Book'  and market = 'US';
-- Restaurants / hospitality
update public.directories set verticals = '{restaurants,hospitality}', authority = 93, authority_tier = 'tier1' where name = 'TripAdvisor'  and market = 'US';
update public.directories set verticals = '{restaurants}', is_marketplace = true, authority_tier = 'tier1'      where name = 'OpenTable'    and market = 'US';
update public.directories set verticals = '{restaurants}'                                                       where name = 'Zomato'       and market = 'US';
update public.directories set verticals = '{restaurants}'                                                       where name = 'MenuPix'      and market = 'US';
update public.directories set verticals = '{restaurants}'                                                       where name = 'Allmenus / Restaurantji' and market = 'US';
update public.directories set verticals = '{restaurants}', is_marketplace = true                                where name = 'Grubhub'      and market = 'US';
-- Real estate
update public.directories set verticals = '{real_estate}', authority = 89, is_marketplace = true, authority_tier = 'tier1' where name = 'Zillow'       and market = 'US';
update public.directories set verticals = '{real_estate}', authority = 89, is_marketplace = true, authority_tier = 'tier1' where name = 'Realtor.com'  and market = 'US';
update public.directories set verticals = '{real_estate}', is_marketplace = true                                          where name = 'Trulia'       and market = 'US';
-- Automotive
update public.directories set verticals = '{automotive}', is_marketplace = true, authority_tier = 'tier1' where name = 'Cars.com / CarGurus' and market = 'US';
update public.directories set verticals = '{automotive}'                                                  where name = 'DealerRater'        and market = 'US';

-- --- Canonical NAP lock (reference plan step 2: "lock canonical NAP") -----------
-- Once a business profile's NAP is confirmed byte-for-byte, it is LOCKED: further
-- edits are rejected (the router 409s) until it is explicitly unlocked, so the
-- name/address/phone every citation submits against cannot silently drift - an
-- inconsistent citation is worse than none.
alter table public.business_profiles
  add column if not exists nap_locked boolean not null default false;
