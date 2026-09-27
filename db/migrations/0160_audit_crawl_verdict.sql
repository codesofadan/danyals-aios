-- 0160_audit_crawl_verdict.sql - a blocked crawl must not read like a clean site.
--
-- THE FAILURE. A site behind Cloudflare, basic auth or an aggressive firewall answers our
-- crawler with 403s. The run then completes NORMALLY in every visible respect: the engine
-- emits what it could, coverage is honestly low, the scores are honestly null, the page
-- list is honestly short. Each number is defensible on its own and the document as a whole
-- says something false - it reads as a thin audit of a simple site rather than a failed
-- look at a locked one.
--
-- That is the most dangerous shape a client-facing report can take, because nothing about
-- it appears broken. There was no single place that said "we were refused", so nobody -
-- operator or client - could tell the two apart.
--
-- THE VERDICT IS THREE WORDS, not a percentage (`app/services/audit_crawl_health.py`):
--
--   ok        we crawled enough of the site to say something about it
--   thin      we reached far fewer pages than planned - stated, not explained away
--   blocked   the site refused us; the findings describe our ACCESS, not their SEO
--
-- `blocked` changes what may be said to a client, so it takes the strict test: a majority
-- of the pages we touched came back refused (401/403/429/451) or unreachable, or nothing
-- beyond a single page could be fetched of a site we planned to crawl properly. Weaker
-- evidence stays `thin`, because "your site blocked us" is an accusation.
--
-- WHY ON `audits` AND NOT DERIVED AT READ TIME. Three surfaces need the same answer - the
-- report banner, the audit row in the dashboard, and the warning before a page is published
-- to a public URL - and deriving it three times is how they end up disagreeing. It is also
-- a property OF THE RUN: a re-crawl next month may be perfectly clean, and this run's
-- report must keep saying what was true when it was generated.
--
-- Additive, idempotent, defaulted to '' so every existing audit reads as "not assessed"
-- rather than as a clean bill of health.

alter table public.audits
  add column if not exists crawl_verdict text not null default '';

alter table public.audits
  add column if not exists crawl_note text not null default '';

comment on column public.audits.crawl_verdict is
  'ok | thin | blocked | '''' (not assessed - an audit that predates 0160 or whose ingest '
  'did not run). Computed at ingest from the run''s own page rows. Anything other than '
  '"ok" means the report must be read as a statement about what we could reach.';

comment on column public.audits.crawl_note is
  'The sentence to print when the verdict is not "ok": what was refused or missed, the '
  'usual causes, and how to read the findings that follow. Empty for a clean run - a '
  'banner with nothing to say is noise that trains people to skip banners.';
