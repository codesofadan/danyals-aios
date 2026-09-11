-- 0129_citation_evidence_tiers.sql - evidence-tiered citation discovery (off-page
-- redesign Phase 1).
--
-- WHAT WAS BROKEN. Discovery found a business's real listing URLs and then THREW THEM
-- AWAY: `CitationRecord{directory, nap_status, note}` carried no URL, so a discovered
-- listing could never be probed, never enter the liveness re-check, and never become
-- `live`. Worse, the audit asserted a single flat verdict per directory when its
-- actual evidence ranged from "we fetched the page and matched the NAP" down to "one
-- unfetched search snippet" - all rendered identically.
--
-- THE TIER VOCABULARY (text + CHECK per the 0106 pattern - never a new Postgres enum,
-- 55P04). `evidence_level` says how much the discovery verdict is actually worth:
--
--   ''                 pre-existing row: written before evidence tiers existed and not
--                      re-judged since. Legacy nap_status semantics apply unchanged.
--   'confirmed'        a listing URL was found AND (the page was fetched with a NAP
--                      match, OR the same listing was corroborated by >= 2 independent
--                      sources with a NAP match).
--   'inconsistent_nap' a listing URL was found but its NAP has DRIFTED from canonical -
--                      the fix is a correction, not a fresh build.
--   'uncertain'        a hit exists but was never fetched / is low-confidence. These
--                      rows go to the "verify first" bucket, never straight to a build.
--   'no_evidence'      ZERO hits across ALL sources. A *candidate* gap only - absence
--                      of evidence is never proof of absence (a directory that blocks
--                      crawlers still lists businesses).
--
-- `discovered_url` is what discovery FOUND; it never grants `live`. Only the liveness
-- probe promotes a discovered row (live_url := discovered_url,
-- verification_method := 'discovery' - the value 0106 reserved for exactly this).
-- `discovery_evidence` is the receipt: {sources, queries, snippet, nap, classifier,
-- checked_at} - checked_at is stamped server-side at write time, never provider-supplied.
--
-- Additive + idempotent. `citations` already has ENABLE+FORCE RLS (0018); new columns
-- inherit the table's existing policies, so no policy work is needed here.

alter table public.citations
  add column if not exists discovered_url      text  not null default '',
  add column if not exists discovery_evidence  jsonb not null default '{}',
  add column if not exists evidence_level      text  not null default '',
  add column if not exists evidence_checked_at timestamptz;

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'citations_evidence_level_check'
  ) then
    alter table public.citations
      add constraint citations_evidence_level_check
      check (evidence_level in ('', 'confirmed', 'inconsistent_nap', 'uncertain', 'no_evidence'));
  end if;
end $$;

-- Discovered-but-unverified rows: the recheck sweep's promotion candidate set (a
-- discovered URL that has not yet earned live_url through a probe).
create index if not exists citations_discovered_unverified_idx
  on public.citations (client_id)
  where discovered_url <> '' and live_url = '';
