-- 0063_web2_platforms_seed.sql - seeds public.web2_platforms (0062) with 50 REAL web2
-- backlink properties. Mirrors 0046's directory-seed style: idempotent
-- (on conflict (name) do nothing) so re-running after an edit never duplicates rows;
-- changing a platform's tier/auth going forward is a NEW migration that UPDATEs by
-- name, not a hand-edit of this seed.
--
-- HONESTY RULES (same discipline as 0046's "note on promises"):
--   * Every platform is a genuine, currently-live web2 property with a real URL.
--   * auth_type is classified by how the automation would ACTUALLY authenticate, not
--     by wish: 'api' only where a documented key/token write exists, 'oauth' where an
--     OAuth flow issues the token, 'automation' where there is NO public write API (a
--     browser/editor publish - or a retired API, e.g. Medium's draft-only path), and
--     'anonymous' where no account is needed at all.
--   * automation_ready=true ONLY for the 17 platforms that have a real Web2Publisher
--     class + the web2_platform enum value TODAY (integrations/web2_publishers.py's
--     WEB2_PLATFORMS). The other 33 are catalogued build targets, not yet automated:
--     publishing to one needs the enum value + a publisher added later (0062 header).
--   * publish_url_or_method is DELIBERATELY short operational shorthand, not the
--     client-facing reference doc. Re-verify an API/endpoint against the live platform
--     before it drives a paid decision (the reference doc's caveat applies here too).

insert into public.web2_platforms
  (name, homepage_url, signup_url, publish_url_or_method, auth_type, authority_tier, market, automation_ready, notes)
values

-- --- automation_ready: the 17 with a real Web2Publisher + enum value today ---------
('WordPress.com', 'wordpress.com', 'wordpress.com/start', 'api:public-api.wordpress.com/rest/v1.1/sites/{site}/posts (OAuth2 bearer)', 'oauth', 'high', 'global', true, 'Hosted WordPress; free {user}.wordpress.com subdomain. Real WordPressComClient.'),
('Blogger', 'blogger.com', 'blogger.com', 'api:googleapis.com/blogger/v3/blogs/{blog_id}/posts (OAuth2 bearer)', 'oauth', 'high', 'global', true, 'Google Blogger; free {user}.blogspot.com. Real BloggerClient (OAuth2).'),
('Tumblr', 'tumblr.com', 'tumblr.com/register', 'api:api.tumblr.com/v2/blog/{blog}/post (OAuth2 bearer)', 'oauth', 'high', 'global', true, 'Microblog; free {user}.tumblr.com. Real TumblrClient (OAuth2).'),
('Medium', 'medium.com', 'medium.com', 'draft-only: publish API retired; pipeline prepares a DRAFT for a human to paste/publish', 'automation', 'high', 'global', true, 'In the web2_platform enum but DRAFT-ONLY - no live publisher; FakeWeb2Publisher marks it verified=false, draft_only=true. Never claimed live.'),
('dev.to', 'dev.to', 'dev.to/enter', 'api:dev.to/api/articles (api-key header, Forem API v1)', 'api', 'medium', 'global', true, 'Forem developer blog. Real DevToClient (plain api-key header, no OAuth).'),
('Write.as', 'write.as', 'write.as/new/signup', 'api:write.as/api/collections/{alias}/posts (bearer; anonymous posting also supported)', 'api', 'low', 'global', true, 'Write.as/WriteFreely. Real WriteAsClient (bearer token; empty target posts anonymously).'),
('Telegra.ph', 'telegra.ph', 'none (fully anonymous)', 'api:api.telegra.ph/createPage (anonymous access_token from createAccount)', 'anonymous', 'low', 'global', true, 'Telegraph publishing. Real TelegraPhClient - no OAuth at all, an anonymous access_token.'),
('Mataroa', 'mataroa.blog', 'mataroa.blog/accounts/create', 'api:mataroa.blog/api/posts/ (bearer token)', 'api', 'low', 'global', true, 'Minimalist blog with a documented REST API. Real MataroaClient (bearer).'),
('Ghost', 'ghost.org', 'ghost.org/pricing', 'api:{site}/ghost/api/admin/posts/ (short-lived Admin JWT from id:secret)', 'api', 'medium', 'global', true, 'Ghost(Pro) or self-hosted. Real GhostClient (Admin API key signs a per-call JWT).'),
('Mastodon', 'joinmastodon.org', 'joinmastodon.org/servers', 'api:{instance}/api/v1/statuses (OAuth2 bearer, per-instance)', 'oauth', 'medium', 'global', true, 'Federated microblog. Real MastodonClient (OAuth2 bearer, per-instance).'),
('GitHub Pages', 'pages.github.com', 'github.com/signup', 'api:api.github.com Contents API PUT (PAT) + ensure Pages enabled', 'api', 'high', 'global', true, 'Static site on {user}.github.io. Real GitHubPagesClient (PAT, two-step commit + enable).'),
('GitLab Pages', 'docs.gitlab.com/ee/user/project/pages', 'gitlab.com/users/sign_up', 'api:gitlab.com/api/v4 Repository Files (PAT) + a CI pages job', 'api', 'medium', 'global', true, 'Static site on {namespace}.gitlab.io. Real GitLabPagesClient (PAT; verified=false pending CI).'),
('Micro.blog', 'micro.blog', 'micro.blog/signup', 'api:micro.blog/micropub (Micropub bearer token, IndieWeb standard)', 'oauth', 'low', 'global', true, 'IndieWeb microblog. Real MicroBlogClient (Micropub; token issued via IndieAuth/OAuth).'),
('Hashnode', 'hashnode.com', 'hashnode.com/onboard', 'api:gql.hashnode.com GraphQL publishPost (RAW PAT header, not Bearer)', 'api', 'medium', 'global', true, 'Developer blog. Real HashnodeClient (GraphQL Public API; needs a publication_id).'),
('Hatena Blog', 'hatenablog.com', 'hatena.ne.jp/register', 'api:blog.hatena.ne.jp/{id}/{blog}/atom AtomPub (HTTP Basic)', 'api', 'medium', 'jp', true, 'Major Japanese blog host. Real HatenaBlogClient (AtomPub, HTTP Basic with the API key).'),
('LiveJournal', 'livejournal.com', 'livejournal.com/create.bml', 'api:livejournal.com/interface/xmlrpc LJ.XMLRPC.postevent (username+password)', 'api', 'medium', 'global', true, 'Legacy journal platform. Real LiveJournalClient (LJ-protocol XML-RPC, no OAuth).'),
('Dreamwidth', 'dreamwidth.org', 'dreamwidth.org/create', 'api:dreamwidth.org/interface/xmlrpc LJ.XMLRPC.postevent (username+password)', 'api', 'low', 'global', true, 'LiveJournal-fork journal. Real DreamwidthClient (shared LJ-protocol XML-RPC).'),

-- --- catalogued build targets (33): real properties, no publisher yet --------------
-- Hosted website builders (browser/editor publish; no public site-publish API).
('Wix', 'wix.com', 'wix.com/signup', 'automation: editor publish; free {user}.wixsite.com/{site}. No public site-publish API', 'automation', 'high', 'global', false, 'Leading hosted website builder; high-authority free subdomain property.'),
('Weebly', 'weebly.com', 'weebly.com/signup', 'automation: editor publish; free {user}.weebly.com', 'automation', 'high', 'global', false, 'Square-owned hosted builder; strong free-subdomain property.'),
('Site123', 'site123.com', 'site123.com', 'automation: guided builder publish; free subdomain', 'automation', 'medium', 'global', false, 'Simple hosted website builder with a free tier.'),
('Strikingly', 'strikingly.com', 'strikingly.com', 'automation: builder publish; free {user}.mystrikingly.com', 'automation', 'medium', 'global', false, 'One-page hosted site builder with a free tier.'),
('Jimdo', 'jimdo.com', 'jimdo.com', 'automation: builder publish; free subdomain', 'automation', 'medium', 'global', false, 'German hosted website/store builder with a free tier.'),
('Webnode', 'webnode.com', 'webnode.com', 'automation: builder publish; free subdomain', 'automation', 'medium', 'global', false, 'Hosted multilingual website builder with a free tier.'),
('Ucraft', 'ucraft.com', 'ucraft.com', 'automation: builder publish; free landing-page tier', 'automation', 'medium', 'global', false, 'Hosted website/landing-page builder with a free tier.'),
('Yola', 'yola.com', 'yola.com', 'automation: builder publish; free subdomain', 'automation', 'low', 'global', false, 'Long-running hosted website builder with a free tier.'),
('Zoho Sites', 'zoho.com/sites', 'zoho.com/sites', 'automation: builder publish (Zoho account)', 'automation', 'medium', 'global', false, 'Zoho suite website builder; drag-and-drop, no public write API.'),
('Google Sites', 'sites.google.com', 'accounts.google.com', 'automation: Workspace editor publish; sites.google.com/view/{slug}. No public write API', 'automation', 'high', 'global', false, 'High-authority Google-hosted site; editor publish only.'),
('Carrd', 'carrd.co', 'carrd.co', 'automation: one-page builder publish; free {slug}.carrd.co', 'automation', 'medium', 'global', false, 'Popular one-page site builder with a free tier.'),
('Bravenet', 'bravenet.com', 'bravenet.com/register', 'automation: hosted blog/website publish', 'automation', 'low', 'global', false, 'Long-standing free web-hosting/blog community.'),

-- Blogging / long-form publishing platforms.
('Substack', 'substack.com', 'substack.com/signup', 'automation: editor publish; free {user}.substack.com. No public post-write API', 'automation', 'high', 'global', false, 'Newsletter + blog; high-authority free publication.'),
('Notion', 'notion.so', 'notion.so/signup', 'api:api.notion.com pages + public share toggle; {slug}.notion.site', 'api', 'high', 'global', false, 'Public Notion pages/sites; API can create pages but public-share is a UI toggle.'),
('HubPages', 'hubpages.com', 'hubpages.com/signin', 'automation: article (hub) publish', 'automation', 'medium', 'global', false, 'Long-form article community (Maven/Arena network).'),
('Vocal.media', 'vocal.media', 'vocal.media/signup', 'automation: story publish', 'automation', 'medium', 'global', false, 'Creator publishing platform across topical communities.'),
('Wattpad', 'wattpad.com', 'wattpad.com/signup', 'automation: story publish', 'automation', 'medium', 'global', false, 'Large storytelling community; profile + story properties.'),
('Newgrounds', 'newgrounds.com', 'newgrounds.com/passport/signup', 'automation: blog post / profile publish', 'automation', 'low', 'global', false, 'Creator community with per-user blogs and profiles.'),

-- Content curation / bookmarking / magazine platforms.
('Wakelet', 'wakelet.com', 'wakelet.com', 'automation: collection publish', 'automation', 'medium', 'global', false, 'Content curation collections; public shareable URLs.'),
('Flipboard', 'flipboard.com', 'flipboard.com', 'automation: magazine curation / article flip', 'automation', 'medium', 'global', false, 'Magazine-style curation; public magazines.'),
('Scoop.it', 'scoop.it', 'scoop.it', 'automation: topic curation publish', 'automation', 'medium', 'global', false, 'Topic-based content curation with public topic pages.'),
('Diigo', 'diigo.com', 'diigo.com/sign-up', 'automation: bookmark + annotated notes (typically nofollow)', 'automation', 'low', 'global', false, 'Social bookmarking / annotation; public library links.'),
('Bloglovin', 'bloglovin.com', 'bloglovin.com', 'automation: blog claim + profile', 'automation', 'low', 'global', false, 'Blog discovery network; claimed-blog and profile links.'),
('Instapaper', 'instapaper.com', 'instapaper.com/user/register', 'automation: saved page / public profile (typically nofollow)', 'automation', 'low', 'global', false, 'Read-later service; public profile / folder links.'),
('Issuu', 'issuu.com', 'issuu.com/signup', 'api:api.issuu.com publications (upload/publish)', 'api', 'medium', 'global', false, 'Digital publications (PDF-to-flipbook) with a documented API.'),
('SlideShare', 'slideshare.net', 'slideshare.net', 'automation: presentation upload/publish', 'automation', 'high', 'global', false, 'Presentation-sharing (Scribd-owned); high-authority profile + decks.'),
('Behance', 'behance.net', 'behance.net', 'automation: project publish (Adobe account)', 'automation', 'high', 'global', false, 'Adobe creative portfolio; high-authority profile + projects.'),

-- Profile / social properties (identity + one editorial link).
('Gravatar', 'gravatar.com', 'gravatar.com/connect', 'api:api.gravatar.com profile (REST); public gravatar.com/{user} profile', 'api', 'medium', 'global', false, 'Global avatar/profile (Automattic); a linkable public profile page.'),
('About.me', 'about.me', 'about.me/signup', 'automation: profile page publish', 'automation', 'medium', 'global', false, 'Personal splash/profile page with a website link.'),
('Disqus', 'disqus.com', 'disqus.com/profile/signup', 'oauth:disqus.com/api (OAuth2) profile + website field', 'oauth', 'low', 'global', false, 'Comment platform; public profile carries a website link.'),
('Minds', 'minds.com', 'minds.com/register', 'api:minds.com API (blog/post); public channel', 'api', 'medium', 'global', false, 'Open-source social network with a blog/post API and public channels.'),
('Plurk', 'plurk.com', 'plurk.com/signup', 'api:plurk.com/API (OAuth1) timeline post', 'oauth', 'medium', 'global', false, 'Microblog with an OAuth1-authed API; public timeline + profile.'),
('Evernote', 'evernote.com', 'evernote.com/signup', 'api:api.evernote.com shared note -> public URL', 'api', 'medium', 'global', false, 'Notes app; a shared note exposes a public URL (API-scriptable).')

on conflict (name) do nothing;
