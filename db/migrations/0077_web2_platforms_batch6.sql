-- 0077_web2_platforms_batch6.sql - a SIXTH pass of real Web2Publisher adapters
-- (integrations/web2_publishers.py): 1 more platform, growing WEB2_PLATFORMS from
-- 53 to 54. Same two-part shape as prior passes.
--
-- WHAT WAS BUILT: WriteFreely - the identical open-source WriteFreely API
-- PLATFORM_WRITEAS (Write.as) already speaks, generalized to a caller-chosen
-- ``instance_url`` instead of hardcoding write.as itself. Several public
-- WriteFreely instances are individually EU-operator-run (e.g. Germany's
-- text.tchncs.de, per the official writefreely.org/instances directory) and
-- allow a fully anonymous post, same as Write.as. HONESTY: a public community
-- instance is volunteer-run with no SLA/contract and can vanish or go
-- invite-only at any time - a lead must pick and verify one live instance
-- before this platform is usable, unlike every corporate-operated platform
-- built so far.
--
-- WHAT WAS INVESTIGATED AND DELIBERATELY REJECTED THIS PASS (no catalog row for
-- any of these - see integrations/web2_publishers.py's module docstring):
--   * Qiita        - has a genuine, self-serve, token-based publish API
--                    (POST /api/v2/items), but its own Terms of Service
--                    (Article 11 S5-4) explicitly name "SEO-purpose or
--                    affiliate-purpose posting" as prohibited commercial
--                    solicitation - squarely the pipeline's own use case.
--   * Zenn          - no HTTP write API at all; the ONLY supported publishing
--                    path is a one-time manual GitHub-repo authorization in
--                    the web dashboard, then push-to-publish - a git-sync
--                    workflow, not a programmatic API a fresh account can use
--                    without a human bootstrap step.
--   * Bear Blog     - no documented write API, no Micropub, no XML-RPC; the
--                    only "automation" found anywhere is headless-browser form
--                    submission against the same editor a human uses.
--   * Substack      - no official publish API (the one official Developer API
--                    is an unrelated LinkedIn-profile lookup, gated behind a
--                    7-10 day manual approval); every "Substack API" client in
--                    the wild is an unofficial reverse-engineered wrapper
--                    hitting private endpoints, which the platform's own
--                    Acceptable Use Policy explicitly prohibits.
--   * Plume         - the project's own maintainers state it is no longer
--                    actively maintained and explicitly point users to
--                    WriteFreely instead; its own API docs are an unfinished
--                    stub with no concrete endpoints published.

-- --- Part A: enum growth --------------------------------------------------------
alter type public.web2_platform add value if not exists 'WriteFreely';

-- --- Part B: catalog upsert ------------------------------------------------------
insert into public.web2_platforms
  (name, homepage_url, signup_url, publish_url_or_method, auth_type, authority_tier, market, automation_ready, notes)
values
  ('WriteFreely','https://writefreely.org','https://writefreely.org/instances','api: WriteFreelyEuClient (integrations/web2_publishers.py) - POST {instance_url}/api/posts (or /api/collections/{target}/posts), the identical WriteFreely/Write.as protocol, optional Bearer token (anonymous posting supported)','api','medium','global',true,'Real Web2Publisher live. Generalizes PLATFORM_WRITEAS to a caller-chosen instance_url. Several open public instances are individually EU-operator-run (per the official writefreely.org/instances directory), but each is a volunteer-run community project with no SLA - pick and verify one live instance before use, and treat it as lower-reliability than every corporate-operated platform in this catalog.')
on conflict (name) do update set
  automation_ready = excluded.automation_ready,
  auth_type = excluded.auth_type,
  publish_url_or_method = excluded.publish_url_or_method,
  notes = excluded.notes;
