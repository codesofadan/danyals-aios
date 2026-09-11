-- 0135_web2_capability_matrix.sql - the Web 2.0 CAPABILITY MATRIX (off-page redesign
-- Phase 6, plan §6/§7).
--
-- WHAT THIS ANSWERS. The catalogue could say "a publisher class exists"
-- (automation_ready) and "who may own an account" (ownership_tier), but not the
-- question routing actually needs: BY WHAT MECHANISM does a placement happen here,
-- if at all? Four lanes, text + CHECK per the 0106 pattern (never a new Postgres
-- enum, 55P04):
--
--   ''            unclassified (the column default; the seed below leaves no row here,
--                 but the vocabulary keeps '' legal so a future catalogue INSERT is
--                 honestly "not yet classified" rather than forced into a guess).
--   'api'         the pipeline publishes through the platform's real API - a
--                 platform_enum mapping AND a Web2Publisher class both exist.
--   'extension'   no usable public write API; the OPERATOR publishes in their own
--                 logged-in browser session, assisted by the extension (Phase 7
--                 placement sessions; the server verifies the pasted public URL).
--   'human'       real platform, no API and no placement tooling yet: a person
--                 places it by hand and records the evidence URL.
--   'unsupported' do-not-use: the platform's terms, its link semantics, or the
--                 provider plan exclude it. adapter_status carries the REASON.
--
-- The other columns:
--   last_tested_at   when a credential/publish path here last passed a real check
--                    (stamped by credcheck/publish flows; NULL = never tested -
--                    honest, and deliberately not faked by this seed).
--   adapter_status   free-text status of the adapter/lane (paywall, retirement,
--                    thin-placement caveat, exclusion reason). '' = nothing to say.
--   link_verifiable  can a placement here ever be link-VERIFIED by fetching a public
--                    page? NULL = not assessed; false = structurally never (headless
--                    CMS entries, Pages hosts the pipeline cannot fetch) - those rows
--                    are excluded from link counts rather than counted on faith.
--   media_support    does the lane require/support media (only stamped where it is a
--                    VERIFIED structural fact - Pixelfed's image-mandatory posts);
--                    NULL = not assessed.
--
-- web2_properties.publish_method records, per placement, WHICH lane actually
-- published it ('api' | 'extension' | 'manual'). Default 'api' because every
-- pre-0135 row was published by the API pipeline - the only lane that existed.
--
-- THE SEED derives from VERIFIED reality (adapter code + credential state + the §6
-- provider plan), never from catalogue marketing claims:
--   * mechanism='api' for every row with a platform_enum mapping (the 54-value enum
--     set, each backed by a real Web2Publisher class) - EXCEPT the rows the provider
--     plan reclassifies: Medium (publish API retired) and the §6 do-not-use set.
--   * the structurally-limited api rows are labelled honestly: GitLab Pages, Notion,
--     Sanity, Storyblok, Hygraph get link_verifiable=false (no fetchable public page
--     => never 'verified'); Disqus and Gravatar are annotated as thin profile
--     placements in adapter_status.
--   * mechanism='extension' for the §6 extension-assisted list (Substack, Medium,
--     Wix, Weebly, Google Sites, Carrd, HubPages, Vocal.media, Behance) plus the
--     site-builder cluster (Site123, Strikingly, Jimdo, Webnode, Zoho Sites, Yola),
--     whose per-platform terms review is still pending - recorded in adapter_status,
--     keyed off the terms columns (terms_checked_on is null).
--   * mechanism='unsupported' with the reason in adapter_status for the §6
--     do-not-use set that exists in the catalogue: Write.as, the paste sites
--     (Pastebin.com / paste.ee / dpaste.org / rentry.co), Evernote, the
--     curation/bookmarking set (Flipboard, Scoop.it, Diigo, Bloglovin, Instapaper,
--     Wakelet), Newgrounds, and Nostr long-form. (Qiita and Zenn are also on the §6
--     do-not-use list but were never catalogued - 0077's header records their
--     rejection - so there is no row to classify.)
--   * mechanism='human' for the remainder: real platforms with no API and no
--     placement tooling yet (Wattpad, SlideShare, Issuu, About.me, Bear Blog,
--     JustPaste.it, Wikidot, Listed.to, diaspora*, Ucraft, Bravenet).
--
-- IDEMPOTENT RE-APPLY: every seed UPDATE is guarded `where mechanism = ''`, so
-- re-applying this file never clobbers a later manual reclassification (a row an
-- operator moved to another lane has mechanism != '' and is left alone). Additive
-- columns; both tables already run ENABLE+FORCE RLS (0062 / 0018), and new columns
-- inherit the existing policies, so no policy work is needed here.

-- --- columns -------------------------------------------------------------------

alter table public.web2_platforms
  add column if not exists mechanism       text not null default '',
  add column if not exists last_tested_at  timestamptz,
  add column if not exists adapter_status  text not null default '',
  add column if not exists link_verifiable boolean,
  add column if not exists media_support   boolean;

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'web2_platforms_mechanism_check'
  ) then
    alter table public.web2_platforms
      add constraint web2_platforms_mechanism_check
      check (mechanism in ('', 'api', 'extension', 'human', 'unsupported'));
  end if;
end $$;

create index if not exists web2_platforms_mechanism_idx
  on public.web2_platforms (mechanism);

alter table public.web2_properties
  add column if not exists publish_method text not null default 'api';

do $$ begin
  if not exists (
    select 1 from pg_constraint where conname = 'web2_properties_publish_method_check'
  ) then
    alter table public.web2_properties
      add constraint web2_properties_publish_method_check
      check (publish_method in ('api', 'extension', 'manual'));
  end if;
end $$;

comment on column public.web2_platforms.mechanism is
  'How a placement happens here: api (pipeline publishes via the platform API), '
  'extension (operator publishes in their own logged-in session, extension-assisted), '
  'human (manual placement, evidence URL recorded), unsupported (do-not-use - the '
  'reason lives in adapter_status). '''' = not yet classified.';
comment on column public.web2_platforms.link_verifiable is
  'Whether a placement here can ever be link-verified by fetching a public page. '
  'NULL = not assessed, false = structurally never (no public rendered page) - such '
  'rows are excluded from link counts rather than counted on faith.';
comment on column public.web2_platforms.last_tested_at is
  'When a credential/publish path here last passed a real check. NULL = never - the '
  '0135 seed deliberately stamps nothing, because nothing was tested by a migration.';
comment on column public.web2_properties.publish_method is
  'Which lane actually published this placement: api | extension | manual. Default '
  'api because every pre-0135 property was published by the API pipeline.';

-- --- seed: 'unsupported' first (the do-not-use set, reasons recorded) ------------

update public.web2_platforms set
    mechanism = 'unsupported',
    adapter_status = 'Signups closed ("Closed for now") and free-tier links are '
      'nofollow (do-follow is a paid feature) - no defensible placement exists.'
  where mechanism = '' and name = 'Write.as';

update public.web2_platforms set
    mechanism = 'unsupported',
    adapter_status = 'Paste site: a link placement here reads as a spam signal, not '
      'a citation or a content property - excluded from link building by the '
      'provider plan.'
  where mechanism = ''
    and name in ('Pastebin.com', 'paste.ee', 'dpaste.org', 'rentry.co');

update public.web2_platforms set
    mechanism = 'unsupported',
    adapter_status = 'Investigated and rejected (batch3 record): a shared note is a '
      'private-app artifact, not a genuine publishing surface - excluded by the '
      'provider plan.'
  where mechanism = '' and name = 'Evernote';

update public.web2_platforms set
    mechanism = 'unsupported',
    adapter_status = 'Bookmarking/curation placement: typically a nofollow profile '
      'or list link with no content value - excluded as a link-building surface by '
      'the provider plan.'
  where mechanism = ''
    and name in ('Flipboard', 'Scoop.it', 'Diigo', 'Bloglovin', 'Instapaper', 'Wakelet');

update public.web2_platforms set
    mechanism = 'unsupported',
    adapter_status = 'Creator community whose blogs are not a defensible surface for '
      'client marketing content - excluded by the provider plan.'
  where mechanism = '' and name = 'Newgrounds';

update public.web2_platforms set
    mechanism = 'unsupported',
    adapter_status = 'Excluded by the provider plan: keypair-published protocol '
      'content with no moderation or takedown path is not a defensible client '
      'placement.'
  where mechanism = '' and name like 'Nostr%';

-- --- seed: 'extension' (operator publishes in their own session, Phase 7) --------

update public.web2_platforms set
    mechanism = 'extension',
    adapter_status = 'Publish API retired (repository archived 2023-03-02, no new '
      'integration tokens) - extension-assisted publishing in the operator''s own '
      'logged-in session.'
  where mechanism = '' and name = 'Medium';

update public.web2_platforms set
    mechanism = 'extension',
    adapter_status = 'No public post-write API, and the unofficial API is banned by '
      'the AUP - the operator publishes in their own logged-in session.'
  where mechanism = '' and name = 'Substack';

update public.web2_platforms set
    mechanism = 'extension',
    adapter_status = 'No public write API - the operator publishes in their own '
      'logged-in session, assisted by the extension.'
  where mechanism = ''
    and name in (
      'Wix', 'Weebly', 'Google Sites', 'Carrd', 'HubPages', 'Vocal.media', 'Behance'
    );

-- The site-builder cluster is extension-ASSISTED per §6, but which of the six make
-- the cut is a per-platform terms decision that has not been taken (terms_checked_on
-- is null on all of them) - so the pending review is recorded, not skipped.
update public.web2_platforms set
    mechanism = 'extension',
    adapter_status = case
      when terms_checked_on is null and terms_position = ''
        then 'Extension-assisted candidate - per-platform terms review pending before '
             'activation.'
      else adapter_status
    end
  where mechanism = ''
    and name in ('Site123', 'Strikingly', 'Jimdo', 'Webnode', 'Zoho Sites', 'Yola');

-- --- seed: the structurally-limited 'api' rows, labelled honestly ----------------

-- No fetchable public page => a placement here can never be link-verified. The rows
-- stay api-publishable (real adapters), but they are excluded from link counts.
update public.web2_platforms set
    mechanism = 'api',
    link_verifiable = false,
    adapter_status = 'Publishes into a Pages deployment the pipeline cannot fetch - '
      'verified stays pending by design, excluded from link counts.'
  where mechanism = '' and name = 'GitLab Pages';

update public.web2_platforms set
    mechanism = 'api',
    link_verifiable = false,
    adapter_status = 'Headless entry with no public rendered page - a placement here '
      'is never link-verified, so it is excluded from link counts.'
  where mechanism = '' and name in ('Notion', 'Sanity', 'Storyblok', 'Hygraph');

-- Thin placements: publicly fetchable (so link-verifiable), but a profile field is
-- not a content page - the annotation keeps reporting honest.
update public.web2_platforms set
    mechanism = 'api',
    link_verifiable = true,
    adapter_status = 'Thin placement: a profile field, not a content page - counted '
      'as reference diversity, not link equity.'
  where mechanism = '' and name in ('Disqus', 'Gravatar');

update public.web2_platforms set
    mechanism = 'api',
    link_verifiable = true,
    media_support = true,
    adapter_status = 'Image-mandatory: every post requires media - text-only '
      'placements are structurally impossible here.'
  where mechanism = '' and name like 'Pixelfed%';

update public.web2_platforms set
    mechanism = 'api',
    link_verifiable = true,
    adapter_status = 'API access paywalled since 2026-05-13 - publishing requires a '
      'paid plan (owner decision pending: pay, or demote to the human lane).'
  where mechanism = '' and name = 'Hashnode';

-- --- seed: the general 'api' lane ------------------------------------------------
-- Every remaining row with a publishing-enum mapping: the enum value AND a real
-- Web2Publisher class both exist (platform_enum is only ever populated when they
-- do - 0103's header), and a published page is publicly fetchable, so the link is
-- verifiable. last_tested_at stays NULL: this migration tested nothing.

update public.web2_platforms set
    mechanism = 'api',
    link_verifiable = true
  where mechanism = '' and platform_enum is not null;

-- --- seed: 'human' for the real remainder ----------------------------------------
-- Real platforms, no API, no placement tooling yet: Wattpad, SlideShare, Issuu,
-- About.me, Bear Blog, JustPaste.it, Wikidot, Listed.to, diaspora*, Ucraft,
-- Bravenet. A person places by hand and records the evidence URL. Deliberately a
-- catch-all over `mechanism = ''` rather than a name list, so EVERY catalogue row
-- leaves 0135 classified - an unclassified row would be invisible to routing.

update public.web2_platforms set
    mechanism = 'human',
    adapter_status = case
      when adapter_status = ''
        then 'Human lane: no API and no placement tooling yet - place it by hand '
             'and record the evidence URL.'
      else adapter_status
    end
  where mechanism = '';
