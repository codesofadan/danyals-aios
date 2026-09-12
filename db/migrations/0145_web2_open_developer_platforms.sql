-- 0145_web2_open_developer_platforms.sql
--
-- OWNER DECISION, 2026-09-12: open the developer-scoped Web 2.0 platforms to every
-- client, not only developer-scoped ones.
--
-- WHAT WAS REFUSING THEM. `evaluate_platform` compares `topical_scope` against the
-- client's own scope and refuses a mismatch with: "Restricted to developer clients;
-- this client is agnostic. Publishing off-topic promotional content here breaches the
-- platform's own content policy." So dev.to, GitHub Pages, GitLab Pages and Hashnode
-- were reachable only for a client classified `developer` - which is almost none of
-- them - even though we hold complete working credentials for all four.
--
-- THE RISK, RECORDED RATHER THAN ARGUED. That refusal was not arbitrary. dev.to and
-- Hashnode are developer-community publications whose content policies expect
-- technically relevant posts; a plumber's promotional article is off-topic there, and
-- the realistic consequences are post removal, account suspension, or (on a community
-- platform) being reported by readers. GitHub Pages and GitLab Pages are the milder
-- pair - they are static hosting, so "off-topic" carries far less weight, though both
-- forbid using the Pages product primarily for SEO link building.
--
-- The owner has weighed that and chosen to open all four. This migration records the
-- decision so the trade-off is recoverable later: if one of these accounts is
-- suspended, the cause is here, not in a mystery.
--
-- WHAT IS NOT WEAKENED. The scope CHECK itself stays in place for every other
-- platform - this changes four rows, not the rule. A future platform catalogued
-- `developer` is still refused for an agnostic client until someone decides
-- otherwise, deliberately, the way this was decided.
--
-- Ownership stays `per_client` for the two Pages platforms and moves to `house` for
-- dev.to and Hashnode, because that is what the credentials ARE: one dev.to API key
-- and one Hashnode PAT, held by the agency. The Pages credentials name a single
-- shared repo (`grillpublisher/qanry`), which is a real shared footprint the owner has
-- accepted; they stay `per_client` so a future per-client repo registers cleanly
-- without another migration.

update public.web2_platforms
set topical_scope    = 'agnostic',
    terms_checked_on = date '2026-09-12'
where name in ('dev.to', 'GitHub Pages', 'GitLab Pages', 'Hashnode')
  and mechanism = 'api'
  and platform_enum is not null
  -- The same guard 0144 carries: never open a platform whose placements could not be
  -- verified, whatever the name list says.
  and coalesce(link_verifiable, true) = true;

-- dev.to and Hashnode are a single agency-held key each, so `house` is the honest tier
-- and is what makes them eligible without inventing a per-client account.
update public.web2_platforms
set ownership_tier = 'house'
where name in ('dev.to', 'Hashnode')
  and ownership_tier = 'per_client';
