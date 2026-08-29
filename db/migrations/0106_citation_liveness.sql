-- 0106_citation_liveness.sql - a listing is LIVE only when someone looked.
--
-- WHAT WAS BROKEN. This table could not hold the one fact the whole module exists to
-- produce: the public URL of a listing we built. It had `proof_url` (a screenshot) and
-- `external_ref` (a directory-side id) and nothing else, so the reporting layer reached
-- for the nearest string that looked like a link - the screenshot path - and rendered it
-- to operators under the heading "Live listings already earned"
-- (service.py compute_citation_gap -> CitationGap.live_urls -> CitationsTab). The value
-- it rendered was not even a URL: the Playwright bot's _screenshot() returned an
-- ABSOLUTE server filesystem path, so the "live listing" list was a list of
-- /var/lib/... paths. Broken links and a server-layout leak from one mis-wired field.
--
-- WHY A COLUMN AND NOT A FIX IN THE QUERY. There was nowhere honest to point the query.
-- `live_url` and `proof_url` are different facts with different lifetimes - a screenshot
-- is evidence that a submission happened, a live URL is evidence that a listing EXISTS -
-- and neither may ever be derived from the other. Keeping them apart is what makes the
-- regression test in tests/modules/citations possible to write at all.
--
-- WHY `submitted` STOPS MEANING DONE. Every write path we have returns `submitted`
-- honestly - Data Axle runs teleresearch for up to three business days, Apple returns
-- state SUBMITTED, Google requires verification before a location appears in Search or
-- Maps, and a form bot only knows that a page changed. None of those is a listing. `live`
-- is reserved for a row where an unauthenticated fetch of `live_url` returned the
-- business's own name and its phone or address. `drifted` and `delisted` are what the
-- re-check finds later, and they are the reason a re-check exists.
--
-- WHY THE CATALOGUE GAINS A ToS POSITION. An anti-scraping clause binds a form-filling
-- bot, because the bot must GET the form before it can fill it. Yelp, Trustpilot and
-- Houzz all publish such a clause; the catalogue currently seeds Yelp as `bot_fillable`.
-- That contradiction has to live in the data, checked and dated with the clause text and
-- its URL, or it will be re-litigated from memory every time. `unknown` is the honest
-- default for the ~214 rows nobody has read yet, and `unknown` is NOT automatable.
--
-- `route` is DERIVED, never hand-set: A (aggregator/API), B (verified open form),
-- C (human queue), F (never attempt). It is the field the worker blocks on - not
-- `tos_position` - because Google Business Profile and Apple are prohibited as BOT
-- targets while being perfectly legitimate over their own authenticated APIs.
--
-- Additive + idempotent. New enum values are ADDED here and deliberately NOT USED in
-- this file (PG 55P04, same rule 0064 documents); the partial index below keys on
-- `next_recheck_at` precisely so it needs no new enum value.

-- --- 1. the liveness vocabulary ------------------------------------------------
alter type public.citation_submit_status add value if not exists 'live';
alter type public.citation_submit_status add value if not exists 'drifted';
alter type public.citation_submit_status add value if not exists 'delisted';

-- --- 2. citations: the live listing, and how we know ---------------------------
alter table public.citations
  -- The PUBLIC URL of the listing. NEVER a screenshot path, never a local path.
  add column if not exists live_url             text not null default '',
  -- When an actual fetch last confirmed the above. NULL = never confirmed.
  add column if not exists live_url_verified_at timestamptz,
  -- How it was confirmed: http_probe | discovery | human. Empty = not confirmed.
  add column if not exists verification_method  text not null default '',
  -- {http_status, matched_fields:[...], checked_from, screenshot_key}. The receipt for
  -- the liveness decision, so "why is this live?" is answerable a year later.
  add column if not exists verification_evidence jsonb not null default '{}',
  add column if not exists next_recheck_at      timestamptz,
  add column if not exists recheck_count        int not null default 0,
  -- Derived from the directory's route at queue time; recorded per unit so a client
  -- report can say HOW each listing was built.
  add column if not exists route                char(1) not null default 'C',
  -- MACHINE-readable reason a queued unit stopped, distinct from the human-readable
  -- `error` (0045): missing_field:<name> | tos_prohibits | captcha_wall | waf_403 |
  -- account_required | no_verified_spec | directory_dead.
  add column if not exists blocked_reason       text not null default '',
  -- Why this directory was NOT attempted for this client (the client-report line).
  add column if not exists skip_reason          text not null default '';

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'citations_route_check') then
    alter table public.citations
      add constraint citations_route_check check (route in ('A', 'B', 'C', 'F'));
  end if;
end $$;

-- Due-for-recheck lookup. Keyed on next_recheck_at (not submit_status) so this
-- migration never references an enum value it just added.
create index if not exists citations_next_recheck_idx
  on public.citations (next_recheck_at)
  where next_recheck_at is not null;

create index if not exists citations_live_url_idx
  on public.citations (client_id)
  where live_url <> '';

-- --- 3. directories: the terms position, dated and sourced ---------------------
alter table public.directories
  add column if not exists tos_position text not null default 'unknown',
  -- The exact clause text we read. Empty unless tos_position <> 'unknown'.
  add column if not exists tos_clause         text not null default '',
  add column if not exists tos_source_url     text not null default '',
  add column if not exists tos_checked_at     timestamptz,
  add column if not exists tos_checked_by     uuid references public.users (id),
  -- NULL = robots.txt not read yet. true = it Disallows the add path for User-agent: *.
  add column if not exists robots_disallows_add boolean,
  -- The add-listing URL, promoted out of the `signup:<url>` prefix in automation_note.
  add column if not exists add_url            text not null default '',
  add column if not exists add_url_status     smallint,
  add column if not exists add_url_checked_at timestamptz,
  add column if not exists route              char(1) not null default 'C';

do $$ begin
  if not exists (select 1 from pg_constraint where conname = 'directories_tos_position_check') then
    alter table public.directories
      add constraint directories_tos_position_check
      check (tos_position in ('prohibits', 'silent', 'permits', 'unknown'));
  end if;
  if not exists (select 1 from pg_constraint where conname = 'directories_route_check') then
    alter table public.directories
      add constraint directories_route_check check (route in ('A', 'B', 'C', 'F'));
  end if;
end $$;

create index if not exists directories_route_idx on public.directories (route);

-- --- 4. promote the researched signup: URLs out of automation_note -------------
-- 0065/0067 encoded the add-listing URL as `signup:<url>` inside a free-text note.
-- A URL we probe on a schedule is a field, not a note.
update public.directories
   set add_url = substring(automation_note from 'signup:(\S+)')
 where add_url = ''
   and automation_note like '%signup:%';

-- --- 5. the twelve hand-verified terms positions (2026-08-23) ------------------
-- Everything not named here stays 'unknown', and 'unknown' is not automatable.
-- Route F: the clause forbids automated access, OR only the business owner can clear
-- the identity/postcard/phone gate, OR community norms forbid bulk inserts.

update public.directories set
  tos_position = 'prohibits',
  tos_clause = 'Use any robot, spider, Service search/retrieval application, or other '
            || 'automated device, process or means to access, retrieve, copy, scrape, '
            || 'or index any portion of the Service (ToS s7.2(j), eff. 2026-01-01). '
            || 'robots.txt additionally closes with User-Agent: * / Disallow: /',
  tos_source_url = 'https://terms.yelp.com/tos/en_us/',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  robots_disallows_add = true,
  route = 'F'
where name like 'Yelp%';

update public.directories set
  tos_position = 'prohibits',
  tos_clause = 'access, search or collect content from our platform by any means '
            || '(automated or otherwise) except as provided on our platform or '
            || 'specifically approved by us; separately bans text mining, data mining '
            || 'or web scraping. The definition of "you" expressly includes '
            || '"automated technologies such as AI agents or screen scrapers".',
  tos_source_url = 'https://corporate.trustpilot.com/legal/for-reviewers/terms-of-use-for-consumers',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  route = 'F'
where name like 'Trustpilot%';

update public.directories set
  tos_position = 'prohibits',
  tos_clause = 'You are expressly prohibited from any use of data mining, robots, '
            || 'scraping, or similar data gathering and extraction tools (Terms of Use s4).',
  tos_source_url = 'https://www.houzz.com/termsOfUse',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  route = 'F'
where name like 'Houzz%';

update public.directories set
  tos_position = 'prohibits',
  tos_clause = 'Community norms forbid bulk/automated POI inserts; imports require '
            || 'prior discussion and an import account.',
  tos_source_url = 'https://wiki.openstreetmap.org/wiki/Import/Guidelines',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  route = 'F'
where name = 'OpenStreetMap';

-- Owner-identity gated: only the business itself can clear the verification, so an
-- agency bot cannot lawfully complete these regardless of what the terms say.
update public.directories set
  tos_position = 'prohibits',
  tos_clause = 'Net-new listings are gated on an identity/phone/postcard verification '
            || 'only the business owner can clear; no agency automation path exists.',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  route = 'F'
where name in (
  'Facebook Business (Page)',
  'Nextdoor',
  'BBB (Better Business Bureau)',
  'Better Business Bureau (BBB)',
  'BBB Canada',
  'Dun & Bradstreet (D&B)'
);

-- Prohibited AS A BOT TARGET, but legitimate over their own authenticated APIs with
-- owned/manager access. tos_position records the bot position; route records the path
-- we actually take. The worker blocks on route, which is why these stay reachable.
update public.directories set
  tos_position = 'prohibits',
  tos_clause = 'Automated form submission is not permitted; the documented, '
            || 'authenticated API with owned/manager access is the only sanctioned '
            || 'write path. A created location requires verification before it is '
            || 'eligible to appear.',
  tos_source_url = 'https://developers.google.com/my-business/content/location-data',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  route = 'A'
where name = 'Google Business Profile';

update public.directories set
  tos_position = 'prohibits',
  tos_clause = 'Automated form submission is not permitted; the documented Apple '
            || 'Business Partner API is the sanctioned write path. A created location '
            || 'returns state SUBMITTED (reviewed before it is live).',
  tos_source_url = 'https://business.apple.com/docs/api/v1/location/create',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  route = 'A'
where name = 'Apple Business Connect';

-- Silent on automation in terms, but robots.txt disallows the add path -> Route C.
update public.directories set
  tos_position = 'silent',
  tos_clause = 'No automation clause found in the operator terms; robots.txt '
            || 'disallows /add, /claim-listing/, /edit/ and /login.',
  tos_source_url = 'https://www.hotfrog.com/robots.txt',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  robots_disallows_add = true,
  route = 'C'
where name like 'Hotfrog%';

-- Silent in terms AND robots permits the add path -> the only Route B candidates we
-- have evidence for. They still enter Route B only via a dated human DOM verification
-- plus one submission that produced a public URL (see directory_specs, a later
-- migration) - so they stay 'C' here. Nothing is automatable on this evidence alone.
update public.directories set
  tos_position = 'silent',
  tos_clause = 'robots.txt does not disallow the add-listing path; no reachable terms '
            || 'page publishes an automation clause.',
  tos_source_url = 'https://www.n49.com/robots.txt',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  robots_disallows_add = false,
  route = 'C'
where name like 'n49%';

update public.directories set
  tos_position = 'silent',
  tos_clause = 'robots.txt is User-agent: * / Disallow: (nothing disallowed).',
  tos_source_url = 'https://www.ourbis.ca/robots.txt',
  tos_checked_at = timestamptz '2026-08-23 00:00:00+00',
  robots_disallows_add = false,
  route = 'C'
where name = 'Ourbis';

-- --- 6. the two direct-API submitters that do not exist ------------------------
-- Probed unauthenticated on 2026-08-23. A 404 means the path is absent; the control
-- probes (a Foursquare READ endpoint returning 401, a Data Axle bad path returning a
-- 404 HTML page against its real endpoint's 403) confirm these are not auth failures.
--   POST https://api.foursquare.com/v3/places        -> 404 "Endpoint '/v3/places' not found."
--   POST https://places-api.foursquare.com/places    -> 404 (current host, no write path)
--   POST https://ssl.bing.com/webmaster/places/api/v1/locations -> 301 -> 404
-- Foursquare routes place additions to community-moderated Placemaker review; Bing's
-- API is a partner programme reached by email. Neither is an endpoint to repair, so
-- the code is deleted and the catalogue stops claiming an automatable write path.
update public.directories set
  tier = 'manual_only',
  route = 'C',
  submit_method = 'manual',
  automation_note = 'Coded write endpoint returned 404 on a live probe 2026-08-23; '
                 || 'no public write API. Foursquare adds go through community-'
                 || 'moderated Placemaker review; Bing Places API access is a partner '
                 || 'programme via placesfeedback@microsoft.com. Human queue only.'
where name in ('Foursquare Places', 'Bing Places for Business');

-- --- 7. rows fed by an aggregator are COVERED, never submitted -----------------
-- automatable_directories() already refuses these; recording the route makes the
-- client report able to say "covered by aggregator, no separate submission", cost 0.
update public.directories
   set route = 'A'
 where submit_method like 'aggregator:fed_by_%';

-- --- 8. GBP and Apple must never reach the Playwright bot ----------------------
-- MEASURED DEFECT, not a hypothetical. `Apple Business Connect` was seeded
-- submit_method = 'bot:playwright+captcha', and submitter_for() dispatches anything
-- prefixed `bot:` to the Playwright engine - so a queued Apple row would today be
-- filled by a bot and its CAPTCHA paid for, against a platform whose only sanctioned
-- write path is an authenticated API. `Google Business Profile` was seeded
-- 'playwright', which matches no dispatch prefix and so blocked only by accident.
--
-- Both are re-pointed at their real (Phase 4, unbuilt) API engines. Until those exist
-- submitter_for() returns "no API submitter configured for ..." and the row blocks
-- cleanly - which is the honest state, and is strictly better than being botted.
update public.directories
   set submit_method = 'api:gbp',
       tier = 'api',
       automation_note = 'Owned/manager access only, never a bot. Create is POST '
                      || '/v1/accounts/{accountId}/locations; a created location must '
                      || 'be verified before it is eligible for Search and Maps, so it '
                      || 'is never `verified` on submit. Engine not built (Phase 4).'
 where name = 'Google Business Profile';

update public.directories
   set submit_method = 'api:apple_business',
       tier = 'api',
       automation_note = 'Apple Business Partner API, bearer token, never a bot. POST '
                      || '/api/v1/orgs/{orgId}/locations returns state SUBMITTED, so it '
                      || 'is never `verified` on submit. Engine not built (Phase 4).'
 where name = 'Apple Business Connect';

-- Data Axle is the verified Route A spine, but its price is unknown (R1 O-2) and the
-- engine is unbuilt. Point it at the real endpoint's engine key so it blocks cleanly
-- rather than silently falling through to a bot.
update public.directories
   set submit_method = 'api:data_axle',
       route = 'A',
       tier = 'aggregator',
       automation_note = 'Local Listings Premium: POST /api/1/submissions (A/R/U/D, 100 '
                      || 'per request, updates free). Verified live + auth-gated '
                      || '2026-08-23. PRICE UNKNOWN - engine must stay blocked until '
                      || 'the rate card is on file (R1 O-2). Engine not built (Phase 4).'
 where name like 'Data Axle%';
