-- 0070_web2_platforms_batch3.sql - a THIRD pass of real Web2Publisher adapters
-- (integrations/web2_publishers.py): 19 more platforms, growing WEB2_PLATFORMS from
-- 21 to 40. Same two-part shape as 0068 (enum growth is safe alongside the catalog
-- upsert in one file only because 0062's catalog `name` column is plain text,
-- decoupled from the public.web2_platform enum on purpose - see 0062's header).
--
--   Part A - grow the public.web2_platform PUBLISHING enum (0018/0045/0068) with
--   the 19 new platform labels. Standalone ALTER TYPE ... ADD VALUE statements,
--   same reason as always: Postgres forbids reading a freshly-added enum value
--   back in the SAME transaction that adds it, and nothing in Part B does.
--
--   Part B - flip the EXISTING catalog rows (public.web2_platforms, inserted by
--   0063/0066 with automation_ready=false, back when there was no client for any
--   of these yet) to automation_ready=true, with publish_url_or_method/notes
--   updated to name the real class each one is now served by. `on conflict
--   (name) do update` (not `do nothing`), same as 0068, so re-applying this
--   migration correctly upgrades the pre-existing rows.
--
-- WHAT WAS DELIBERATELY SKIPPED (verified non-viable or a bad content-model fit -
-- their catalog rows are left completely UNTOUCHED, still automation_ready=false):
--   * Evernote        - developer tokens are disabled; OAuth app keys need a
--                       manual, up-to-5-business-day human review. No instant
--                       self-serve path exists in 2026.
--   * Issuu           - the API is gated to PAID Issuu tiers (not the free plan),
--                       AND its content model is PDF/document flipbooks, not a
--                       plain HTML article - forcing a fit would need a fragile
--                       HTML-to-PDF conversion step for a paid-only API.
--   * Nostr long-form (YakiHonne / Habla.news, NIP-23) - doing BIP-340 Schnorr
--                       signing correctly needs a new, fairly heavy secp256k1
--                       dependency (e.g. pynostr/nostr-sdk); hand-rolling raw
--                       elliptic-curve signing for one platform is exactly the
--                       "fragile implementation" this build was told not to force.
--   * Mastodon (mastodon.social) / Mastodon (mas.to) - NOT new platforms at all:
--                       both are already fully servable by the EXISTING
--                       MastodonClient/PLATFORM_MASTODON (just a different
--                       instance_url credential) - zero new code, so their
--                       catalog rows are intentionally left as-is too.

-- --- Part A: enum growth --------------------------------------------------------
alter type public.web2_platform add value if not exists 'HackMD';
alter type public.web2_platform add value if not exists 'GitHub Gist';
alter type public.web2_platform add value if not exists 'GitLab Snippets';
alter type public.web2_platform add value if not exists 'paste.ee';
alter type public.web2_platform add value if not exists 'Pastebin.com';
alter type public.web2_platform add value if not exists 'Netlify';
alter type public.web2_platform add value if not exists 'Neocities';
alter type public.web2_platform add value if not exists 'rentry.co';
alter type public.web2_platform add value if not exists 'dpaste.org';
alter type public.web2_platform add value if not exists 'Misskey';
alter type public.web2_platform add value if not exists 'Lemmy';
alter type public.web2_platform add value if not exists 'Bluesky';
alter type public.web2_platform add value if not exists 'WhiteWind';
alter type public.web2_platform add value if not exists 'Disqus';
alter type public.web2_platform add value if not exists 'Plurk';
alter type public.web2_platform add value if not exists 'Pixelfed';
alter type public.web2_platform add value if not exists 'Notion';
alter type public.web2_platform add value if not exists 'Gravatar';
alter type public.web2_platform add value if not exists 'Minds';

-- --- Part B: catalog upsert ------------------------------------------------------
insert into public.web2_platforms
  (name, homepage_url, signup_url, publish_url_or_method, auth_type, authority_tier, market, automation_ready, notes)
values
  ('HackMD','https://hackmd.io','https://hackmd.io/','api: HackMDClient (integrations/web2_publishers.py) - POST /v1/notes at api.hackmd.io, Bearer PAT (self-issued, Settings > API), readPermission: guest for a publicly-viewable publishLink','api','medium','global',true,'Real Web2Publisher live. Token self-serve, no approval.'),
  ('GitHub Gist','https://gist.github.com','https://github.com/signup','api: GitHubGistClient (integrations/web2_publishers.py) - POST https://api.github.com/gists with a PAT Bearer, public:true','api','high','global',true,'Real Web2Publisher live. High-DA, self-serve PAT. Gist links are typically nofollow - best for reference/citation diversity.'),
  ('GitLab Snippets','https://gitlab.com','https://gitlab.com/users/sign_up','api: GitLabSnippetsClient (integrations/web2_publishers.py) - POST https://gitlab.com/api/v4/snippets with PRIVATE-TOKEN PAT, visibility=public','api','high','global',true,'Real Web2Publisher live. High-DA, self-serve PAT, no app approval.'),
  ('paste.ee','https://paste.ee','https://paste.ee/register','api: PasteEeClient (integrations/web2_publishers.py) - POST https://api.paste.ee/v1/pastes with X-Auth-Token header + sections[].contents','api','low','global',true,'Real Web2Publisher live. No documented edit endpoint - every publish is a new paste.'),
  ('Pastebin.com','https://pastebin.com','https://pastebin.com/signup','api: PastebinClient (integrations/web2_publishers.py) - POST https://pastebin.com/api/api_post.php (form-encoded, returns a bare text url) with api_dev_key + api_option=paste','api','medium','global',true,'Real Web2Publisher live. Classic api_dev_key still live for free accounts. No edit endpoint reachable with just the dev key - every publish is a new paste.'),
  ('Netlify','https://www.netlify.com','https://app.netlify.com/signup','api: NetlifyClient (integrations/web2_publishers.py) - the digest deploy flow (POST .../deploys with a sha1 file digest, PUT the file only if required) against an existing site_id','api','medium','global',true,'Real Web2Publisher live. One deploy replaces the whole site''s prior deploy - one branded property per Netlify site.'),
  ('Neocities','https://neocities.org','https://neocities.org','api: NeocitiesClient (integrations/web2_publishers.py) - multipart POST https://neocities.org/api/upload with a Bearer site API key','api','medium','global',true,'Real Web2Publisher live. Free static host, self-serve API key.'),
  ('rentry.co','https://rentry.co','https://rentry.co/','anonymous: RentryClient (integrations/web2_publishers.py) - POST https://rentry.co/api/new with a CSRF cookie handshake, no account/credential at all','anonymous','medium','global',true,'Real Web2Publisher live. Unofficial-but-actively-maintained endpoint (community clients still updated in 2026); the returned edit_code is the only write credential for later updates.'),
  ('dpaste.org','https://dpaste.org','https://dpaste.org/','anonymous: DpasteClient (integrations/web2_publishers.py) - POST https://dpaste.org/api/ with no key or cookie at all','anonymous','low','global',true,'Real Web2Publisher live. Simplest possible anonymous POST, confirmed current in the official docs. No edit endpoint - every publish is a new paste.'),
  ('Misskey (misskey.io)','https://misskey.io','https://misskey.io','api: MisskeyClient (integrations/web2_publishers.py) - POST /api/notes/create with the access token IN the JSON body (`i`), not a header - a documented Misskey quirk','api','medium','jp',true,'Real Web2Publisher live. Distinct fediverse software from Mastodon - its own client. No note-edit endpoint - every publish is a new note.'),
  ('Lemmy (lemmy.world)','https://lemmy.world','https://lemmy.world/signup','api: LemmyClient (integrations/web2_publishers.py) - POST /api/v3/user/login for a JWT, resolve the target community name to an id, then POST /api/v3/post as a link post (url=backlink, body=article text)','api','medium','global',true,'Real Web2Publisher live. Open self-serve signup confirmed current (Lemmy 1.0.0 open beta, May 2026); still exposes the same v3 API.'),
  ('Bluesky','https://bsky.app','https://bsky.app','api: BlueskyClient (integrations/web2_publishers.py) - AT Protocol: an App Password, com.atproto.server.createSession, then com.atproto.repo.createRecord/putRecord (app.bsky.feed.post)','api','high','global',true,'Real Web2Publisher live. Fully open, no dev portal/review/invite, confirmed stable in 2026. Folds title+body+link to ~300 graphemes with a real link facet.'),
  ('WhiteWind (Bluesky/ATProto long-form)','https://whtwnd.com','https://whtwnd.com','api: WhiteWindClient (integrations/web2_publishers.py) - reuses the SAME Bluesky/ATProto session, writes a com.whtwnd.blog.entry record via XRPC; renders as a public HTML article at whtwnd.com','api','medium','global',true,'Real Web2Publisher live. Confirmed still operating in 2026 (active repo/updates). The genuine long-form counterpart to Bluesky''s short post - no grapheme cap.'),
  ('Disqus','disqus.com','disqus.com/profile/signup','api: DisqusClient (integrations/web2_publishers.py) - OAuth2, POST /users/updateProfile.json (url + about fields) - a THIN PROFILE placement, not an article','oauth','low','global',true,'Real Web2Publisher live, but honestly a profile placement (Disqus has no article-publish endpoint for a 3rd-party integration). Self-serve OAuth2 app registration confirmed current, no manual review found.'),
  ('Plurk','plurk.com','plurk.com/signup','api: PlurkClient (integrations/web2_publishers.py) - OAuth1 (hand-rolled HMAC-SHA1 signing), POST plurkAdd to the account timeline','oauth','medium','global',true,'Real Web2Publisher live. Site confirmed active in 2026; the one OAuth1 (not OAuth2) platform in this catalog.'),
  ('Pixelfed (pixelfed.social)','https://pixelfed.social','https://pixelfed.social/register','api: PixelfedClient (integrations/web2_publishers.py) - Mastodon-compatible REST, but uploads a fixed brand placeholder_image_url as required media before POST /api/v1/statuses','api','medium','global',true,'Real Web2Publisher live. Requires an image per post (unlike Mastodon) - solved with a fixed brand placeholder image fetched + uploaded each publish.'),
  ('Notion','notion.so','notion.so/signup','api: NotionClient (integrations/web2_publishers.py) - api.notion.com Pages API creates a real page under a pre-existing parent_page_id; verified=False always (no API to flip "Share to web")','api','high','global',true,'Real Web2Publisher live, but always verified=False: confirmed against 2026 docs that making a page public is STILL a human, UI-only toggle - a person must open the created page and share it before it is a live, indexable placement.'),
  ('Gravatar','gravatar.com','gravatar.com/connect','api: GravatarClient (integrations/web2_publishers.py) - api.gravatar.com/v3 Bearer token, PATCH /me (description + a links[] entry) - a THIN PROFILE placement, not an article','api','medium','global',true,'Real Web2Publisher live, but honestly a profile placement (Gravatar has no article concept). Automattic''s 2024+ v3 REST API confirmed current in 2026.'),
  ('Minds','minds.com','minds.com/register','api: MindsClient (integrations/web2_publishers.py) - Bearer personal access token, POST /api/v3/newsfeed/activity to the account''s public channel','api','medium','global',true,'Real Web2Publisher live. Minds.com confirmed operating (status page + developer docs current) in 2026.')
on conflict (name) do update set
  automation_ready = excluded.automation_ready,
  auth_type = excluded.auth_type,
  publish_url_or_method = excluded.publish_url_or_method,
  notes = excluded.notes;
