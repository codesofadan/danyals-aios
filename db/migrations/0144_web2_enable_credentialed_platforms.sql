-- 0144_web2_enable_credentialed_platforms.sql
--
-- OWNER DECISION, 2026-09-12: open the platforms we actually hold working credentials
-- for. Seven rows move from `do_not_use` to `house`, topic-agnostic, terms-settled.
--
-- WHAT `terms_checked_on` MEANS AFTER THIS MIGRATION. The column gates
-- `evaluate_platform`'s `not_reviewed` verdict - a null date means "nobody has settled
-- this platform, so it stays unusable by default". The date set below records that the
-- OWNER settled it on 2026-09-12, having supplied a working credential for each one.
-- It does NOT record that the agency read and summarised each platform's terms of
-- service. That distinction is written down here because the field cannot express it,
-- and a later reader deciding whether to trust the date deserves to know which of the
-- two happened. If a platform's terms are ever disputed, this migration - not a terms
-- review - is the provenance.
--
-- WHY `house` AND NOT `per_client`. Each of these is a SINGLE shared credential held by
-- the agency (one Ghost admin key, one Mastodon token, one Webflow token...). `house` is
-- what they are. Recording them `per_client` would need a client id per row and would
-- claim an ownership that does not exist; copying one credential into per-client rows is
-- precisely the shared-footprint pattern R2-06 removed. The cost is real and is accepted
-- deliberately: a suspension on one of these accounts affects every client published
-- through it, which is why `web2_accounts.max_properties` caps each at 10.
--
-- WHY `agnostic` SCOPE. These are general-purpose blog and CMS platforms - a plumber's
-- article on Ghost or Mastodon breaks no content policy. This is NOT extended to the
-- developer-scoped four (dev.to, GitHub Pages, GitLab Pages, Hashnode), which stay
-- `developer`: publishing a dentist's promotional article on dev.to would breach their
-- stated content policy, and holding a credential does not change that.
--
-- THREE PLATFORMS DELIBERATELY LEFT EXCLUDED, despite holding credentials:
--
--   * Hygraph, Sanity - `link_verifiable = false`. These are headless content APIs with
--     NO public rendered page. A placement produces no public URL, so the link check can
--     never find our link and the property would sit at "published, link not found"
--     forever. That is a physical fact about the platform, not a policy gate, so no
--     authorisation can clear it. Enabling them would manufacture permanently unverifiable
--     placements - exactly the fake-success state the module exists to refuse.
--
--   * Write.as - signups are closed and free-tier links are nofollow. There is nothing
--     to enable.
--
-- WriteFreely IS enabled and is the one row here needing no secret: its only credential
-- field is `instance_url`, and its client posts anonymously to a public instance. It is
-- link-verifiable, which is why it qualifies where the paste sites do not.
--
-- THE PASTE SITES STAY EXCLUDED (rentry.co, dpaste.org, paste.ee). They need no
-- credential, so they meet the letter of "free to post without creds", but their recorded
-- exclusion reason is that a paste-site backlink reads as a spam signal rather than a
-- citation. Enabling them would actively damage the link profile we are being paid to
-- build. Left to an explicit, separate decision.

update public.web2_platforms
set ownership_tier   = 'house',
    topical_scope    = 'agnostic',
    terms_checked_on = date '2026-09-12',
    -- The adapter exists and is not a stub for any of these; the three that were flagged
    -- unready (LiveJournal, Mataroa, Micro.blog) were marked so alongside the 2026-09-08
    -- exclusion, so the flag is cleared with the exclusion it travelled with.
    automation_ready = true,
    adapter_status   = ''
where name in (
  'Ghost',        -- Admin API key signs a per-call JWT; link-verifiable
  'Webflow',      -- free Starter gives a *.webflow.io page; link-verifiable
  'Mastodon',     -- OAuth2 bearer, mastodon.social; link-verifiable
  'LiveJournal',  -- LJ-protocol XML-RPC; link-verifiable
  'Mataroa',      -- documented REST API, bearer; link-verifiable
  'Micro.blog',   -- Micropub token; link-verifiable
  'WriteFreely'   -- instance_url only, posts anonymously; link-verifiable
)
  -- Belt and braces: never open a row the pipeline cannot actually drive, whatever the
  -- name list says. A row with no publishing-enum mapping or outside the API lane would
  -- reach `eligible` and then fail at plan time.
  and mechanism = 'api'
  and platform_enum is not null
  -- And never open one whose placements could not be verified. `link_verifiable = false`
  -- is the Hygraph/Sanity guard restated as a condition, so re-running this migration
  -- after a reclassification cannot quietly include them.
  and coalesce(link_verifiable, true) = true;

comment on column public.web2_platforms.terms_checked_on is
  'The date a HUMAN settled whether this platform may be used. Null = nobody has, so '
  'the platform stays unusable (evaluate_platform returns not_reviewed). A date does '
  'not by itself mean the terms were read and summarised: rows dated 2026-09-12 were '
  'settled by owner authorisation alongside a working credential - see migration 0144.';
