-- 0103_web2_platform_tiers.sql - per-client PLATFORM ELIGIBILITY (R2-03 / R2-04 / R2-05).
--
-- THE PROBLEM THIS SOLVES. The catalogue answers "can the pipeline publish here?"
-- (`automation_ready`). It cannot answer the question that actually decides whether a
-- placement is defensible: "should THIS client publish here at all?" Those are different
-- questions and conflating them is what produces the module's worst output - a plumber's
-- marketing article on a developer community, which dev.to's own Content Policy forbids
-- ("not designed primarily for the purposes of promotion or creating backlinks"),
-- Hashnode's forbids ("automated content generation for the purpose of manipulating
-- search results"), and GitHub's AUP forbids ("the primary focus ... should not be
-- advertising or promotional marketing"). The adapter is not the problem; using it for
-- the wrong client is.
--
-- SO ELIGIBILITY IS COMPUTED, NOT CONFIGURED (R2-04). A platform is eligible for a client
-- iff it is not `do_not_use` AND its topical scope is either `agnostic` (a real brand
-- blog suits anyone) or matches that client's declared scope. This is what lets the
-- product honestly offer the whole catalogue while still guiding a compliant selection:
-- a dev-tools SaaS legitimately unlocks the developer platforms, a local plumber does
-- not, and the board says WHY rather than silently hiding rows.
--
-- THE JOIN TRAP, AND WHY `platform_enum` EXISTS (R2-04). `web2_platforms.name` is FREE
-- TEXT and deliberately decoupled from the `public.web2_platform` enum (0062's header):
-- 90 catalogue rows against 54 enum values, several catalogue names being instance-level
-- ("Mastodon (mastodon.social)") with no enum value at all. Resolving eligibility by
-- matching NAME STRINGS would therefore silently fail for exactly those rows. The mapping
-- column makes the join explicit and total: populated where an enum value exists, NULL
-- where the catalogue lists a build target the pipeline cannot drive.
--
-- THE CLIENT SIDE. `public.clients.industry` (0003) and `client_business_profiles`
-- `.primary_category` (0051) are both FREE TEXT with no taxonomy behind them, so neither
-- can be matched against a scope enum. Inferring a scope from free text would be a
-- silent-wrong-answer machine - a "Software" plumber unlocking dev.to. The scope is
-- therefore an EXPLICIT column with the safest possible default: an unclassified client
-- gets the topic-agnostic set and nothing else, and widening it is a deliberate act.

-- --- Enums ----------------------------------------------------------------------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'web2_topical_scope') then
    --   agnostic  - a genuine branded blog is welcome (WordPress.com, Blogger, Tumblr,
    --               Telegra.ph). Fits any client, which is why it is the default.
    --   developer - developer communities + code hosts (dev.to, Hashnode, HackMD, the
    --               Pages/gist/snippet hosts). Off-topic promo is banned in their terms.
    --   research  - scholarly/preprint repositories (Zenodo, OSF, Figshare).
    --   creative  - portfolio/creative networks.
    --   niche     - anything whose fit must be judged case by case.
    create type public.web2_topical_scope as enum
      ('agnostic', 'developer', 'research', 'creative', 'niche');
  end if;
end $$;

-- --- Catalogue: ownership tier + topical scope + terms provenance -----------------
alter table public.web2_platforms
  add column if not exists ownership_tier text not null default 'do_not_use'
    check (ownership_tier in ('per_client', 'house', 'do_not_use'));

alter table public.web2_platforms
  add column if not exists topical_scope public.web2_topical_scope not null default 'niche';

-- WEB2-015: what the platform's OWN terms say about what we do, and when a human last
-- read them. A position with no date is folklore; the date is what makes it auditable.
alter table public.web2_platforms
  add column if not exists terms_position text not null default '';
alter table public.web2_platforms
  add column if not exists terms_source_url text not null default '';
alter table public.web2_platforms
  add column if not exists terms_checked_on date;

-- The explicit catalogue -> publishing-enum mapping. NULL is meaningful: "catalogued as
-- a build target, but the pipeline has no publisher/enum value for it".
alter table public.web2_platforms
  add column if not exists platform_enum public.web2_platform;

create index if not exists web2_platforms_ownership_tier_idx
  on public.web2_platforms (ownership_tier);
create index if not exists web2_platforms_topical_scope_idx
  on public.web2_platforms (topical_scope);
create index if not exists web2_platforms_platform_enum_idx
  on public.web2_platforms (platform_enum) where platform_enum is not null;

-- --- Client side: the declared topical scope --------------------------------------
alter table public.clients
  add column if not exists web2_topical_scope public.web2_topical_scope not null default 'agnostic';

comment on column public.clients.web2_topical_scope is
  'Which Web 2.0 topical families this client may publish to. Defaults to agnostic - '
  'the safe set every real brand fits - because inferring it from the free-text '
  'industry column would unlock developer platforms for a plumber (R2-04).';

-- --- Populate the mapping for every catalogue name that IS an enum value -----------
-- Exact-name matches only. A catalogue row whose name does not equal an enum label
-- (the instance-qualified ones) correctly keeps platform_enum = NULL.
update public.web2_platforms p
   set platform_enum = e.label::public.web2_platform
  from (
    select unnest(enum_range(null::public.web2_platform))::text as label
  ) e
 where p.platform_enum is null
   and p.name = e.label;

-- The INSTANCE-QUALIFIED rows, mapped by hand. These are the concrete case the mapping
-- column exists for: the catalogue seeds them with an instance in the name (0070) while
-- the publishing enum carries the bare platform, so an exact-name join leaves four
-- genuinely publishable platforms unmapped and therefore permanently ineligible. They
-- are matched on a prefix rather than re-seeded so the catalogue keeps naming the actual
-- instance an operator would sign up on.
update public.web2_platforms set platform_enum = 'Misskey'
  where platform_enum is null and name like 'Misskey%';
update public.web2_platforms set platform_enum = 'Lemmy'
  where platform_enum is null and name like 'Lemmy%';
update public.web2_platforms set platform_enum = 'WhiteWind'
  where platform_enum is null and name like 'WhiteWind%';
update public.web2_platforms set platform_enum = 'Pixelfed'
  where platform_enum is null and name like 'Pixelfed%';
update public.web2_platforms set platform_enum = 'Mastodon'
  where platform_enum is null and name like 'Mastodon (%';

-- --- Seed the tiers from the verified terms review (R2 §3.2, read 2026-08-23) ------
-- Per-client (Tier A): a documented publish API drivable by a per-client credential,
-- terms that do not prohibit programmatic posting, and a client-branded property.
update public.web2_platforms set
    ownership_tier = 'per_client', topical_scope = 'agnostic',
    terms_checked_on = date '2026-08-23'
  where name in ('WordPress.com', 'Blogger', 'Tumblr');

update public.web2_platforms set
    terms_position = 'User Guidelines ban sites primarily dedicated to driving traffic '
      'or boosting SEO; a genuine client brand blog is permitted. Termination is at '
      'their sole discretion.',
    terms_source_url = 'https://wordpress.com/support/user-guidelines/'
  where name = 'WordPress.com';

update public.web2_platforms set
    terms_position = 'Content Policy bans unwanted promotional content and unwanted '
      'content created by an automated program. "Unwanted" is the operative word: '
      'genuine per-client content under human approval is the compliance argument.',
    terms_source_url = 'https://www.blogger.com/go/contentpolicy'
  where name = 'Blogger';

-- Tumblr is per-client but NOT batch-automatable: its API License requires a specific
-- user interaction plus explicit permission per post, and its User Guidelines forbid
-- programmatic registration outright. That is why the approval ceiling is one
-- web2_id per call and why no batch-approve endpoint exists.
update public.web2_platforms set
    terms_position = 'User Guidelines: "Don''t register accounts or post content '
      'automatically, systematically, or programmatically." API License s(s) permits '
      'posting on a user''s behalf only with explicit per-post permission - so strict '
      'per-post human approval, never batch, and manual registration.',
    terms_source_url = 'https://www.tumblr.com/policy/user-guidelines'
  where name = 'Tumblr';

-- House (Tier B): publishing is anonymous, so a shared account misrepresents no
-- authorship. Capped, because a suspension here costs every client at once.
update public.web2_platforms set
    ownership_tier = 'house', topical_scope = 'agnostic',
    terms_position = 'Anonymous publishing, no account required. Value is indexation '
      'and reference diversity rather than link equity.',
    terms_source_url = 'https://telegra.ph/', terms_checked_on = date '2026-08-23'
  where name = 'Telegra.ph';

-- Developer-scope platforms stay reachable, but only for a client whose real industry
-- makes the placement genuine. Each is quoting its OWN terms, not our guess.
update public.web2_platforms set
    topical_scope = 'developer', ownership_tier = 'per_client',
    terms_checked_on = date '2026-08-23'
  where name in (
    'dev.to', 'Hashnode', 'GitHub Pages', 'GitLab Pages', 'HackMD', 'GitHub Gist',
    'GitLab Snippets', 'Codeberg Pages', 'Sourcehut Pages', 'Netlify', 'Neocities'
  );

update public.web2_platforms set
    terms_position = 'Content Policy: posts must not be "designed primarily for the '
      'purposes of promotion or creating backlinks". Off-topic promotional content for '
      'a non-developer client breaches this.',
    terms_source_url = 'https://dev.to/terms'
  where name = 'dev.to';

update public.web2_platforms set
    terms_position = 'Acceptable Use bans "automated content generation for the purpose '
      'of manipulating search results". Also independently requires human review of '
      'AI-generated content before publishing.',
    terms_source_url = 'https://hashnode.com/terms'
  where name = 'Hashnode';

update public.web2_platforms set
    terms_position = 'AUP: "the primary focus of the Content posted ... should not be '
      'advertising or promotional marketing", and bans automated bulk activity.',
    terms_source_url =
      'https://docs.github.com/en/site-policy/acceptable-use-policies/github-acceptable-use-policies'
  where name in ('GitHub Pages', 'GitHub Gist');

update public.web2_platforms set
    topical_scope = 'research', ownership_tier = 'per_client',
    terms_position = 'Scholarly repository: a deposit is permanent and is not an '
      'appropriate host for marketing content.',
    terms_checked_on = date '2026-08-23'
  where name in ('Zenodo', 'OSF', 'Figshare');

-- Medium: publish API retired (repository archived 2023-03-02), so it can never be a
-- live target regardless of tier. The catalogue's automation_ready is corrected here
-- because a boolean claiming otherwise is the kind of stale fact this rescue removes.
update public.web2_platforms set
    ownership_tier = 'do_not_use', automation_ready = false,
    terms_position = 'Publish API retired; the API repository was archived 2023-03-02 '
      'and no new integration tokens are issued. Draft-only.',
    terms_source_url = 'https://github.com/Medium/medium-api-docs',
    terms_checked_on = date '2026-08-23'
  where name = 'Medium';

-- Write.as: free tier signup closed and free-tier links are nofollow (do-follow is a
-- paid feature), so a free placement carries no link value at all.
update public.web2_platforms set
    ownership_tier = 'do_not_use',
    terms_position = 'Free tier signup "Closed for now"; do-follow links are a paid '
      'feature, so a free-tier placement is nofollow.',
    terms_source_url = 'https://write.as/pricing', terms_checked_on = date '2026-08-23'
  where name = 'Write.as';

comment on column public.web2_platforms.ownership_tier is
  'Who owns an account here: per_client (the client owns the property), house (shared, '
  'anonymous, capped), or do_not_use. Defaults to do_not_use so a newly catalogued '
  'platform is never publishable until someone reads its terms (R2-05).';

comment on column public.web2_platforms.platform_enum is
  'Explicit mapping to public.web2_platform. NULL means catalogued as a build target '
  'with no publisher/enum value. Eligibility MUST resolve through this column, never '
  'through a name string - 90 free-text names vs 54 enum labels (R2-04).';
