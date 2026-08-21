-- 0072_web2_platforms_batch4.sql - a FOURTH pass of real Web2Publisher adapters
-- (integrations/web2_publishers.py): 10 more platforms, growing WEB2_PLATFORMS from
-- 40 to 50. Same two-part shape as 0068/0070 (enum growth is safe alongside the
-- catalog upsert in one file only because 0062's catalog `name` column is plain
-- text, decoupled from the public.web2_platform enum on purpose - see 0062's header).
-- NOTE: 0069/0071 are intentionally skipped here (reserved by an unrelated,
-- concurrently-built module in this shared repo) - this migration continues the
-- web2_platforms numbering from 0070 at the next number neither series has claimed.
--
--   Part A - grow the public.web2_platform PUBLISHING enum (0018/0045/0068/0070)
--   with the 10 new platform labels. Standalone ALTER TYPE ... ADD VALUE
--   statements, same reason as always: Postgres forbids reading a freshly-added
--   enum value back in the SAME transaction that adds it, and nothing in Part B
--   does.
--
--   Part B - flip the EXISTING catalog rows (public.web2_platforms) to
--   automation_ready=true where a row of that exact name already existed
--   (none did for this batch - every platform below is a brand-new catalog
--   insert), with publish_url_or_method/notes naming the real class each one is
--   now served by. `on conflict (name) do update` (not `do nothing`), same as
--   0068/0070, so re-applying this migration correctly upgrades any pre-existing
--   row of the same name.
--
-- WHAT WAS DELIBERATELY SKIPPED (verified non-viable or a bad content-model fit -
-- no catalog row is inserted for any of these; there is nothing to flip):
--   * CodeSandbox      - the MODERN sdk.sandboxes.create() product (the one this
--                        build was asked to verify) has no publicly documented
--                        raw HTTP endpoint reachable with just a CSB_API_KEY - the
--                        SDK does not clearly call a stable public REST/GraphQL
--                        route. The OLDER, keyless "Define API"
--                        (api/v1/sandboxes/define) IS documented, but it is a
--                        different, legacy code-demo product: not gated by any
--                        per-account credential (so it does not fit this vault's
--                        per-client credential model at all), and its sandboxes
--                        are not built to be a durable, citable static-article
--                        host the way Netlify/Neocities are - forcing it here
--                        would be exactly the fragile stretch this build avoids.
--   * GitBook          - creating a Space (POST /orgs/{orgId}/spaces) is
--                        confirmed and documented, but that alone is NOT a
--                        published article - only an empty public container.
--                        Pushing real page CONTENT into a space appears to be
--                        possible only via an undocumented change-request +
--                        content-operations + merge flow (only ever observed as
--                        a `gitbook` CLI command in the wild, e.g. `spaces
--                        change-requests content update ... insert_page`); no
--                        verifiable REST endpoint shape for that flow was found
--                        in GitBook's public API reference. Half-supporting this
--                        (a public space with no content) is not a real
--                        placement, so it is skipped rather than guessed at.
--   * Read the Docs    - POST /api/v3/projects/ creates a documentation PROJECT,
--                        not a live article - it still needs a connected git
--                        repo plus a Sphinx/MkDocs build trigger before anything
--                        is actually live. The SAME content-model mismatch that
--                        makes GitLab Pages CI-dependent-and-unverified here, but
--                        severe enough (no page-like unit at all, only a
--                        build pipeline) that skipping outright is the honest
--                        call rather than half-supporting it.
--   * Hive / Steemit   - both require signing a `condenser_api.broadcast_
--                        transaction(_synchronous)` blockchain operation with the
--                        account's private posting key (secp256k1 ECDSA) - the
--                        IDENTICAL class of custody-sensitive crypto signing that
--                        got Nostr long-form dropped in the 0070/batch3 pass.
--                        Nothing suitable already sits in pyproject.toml's
--                        dependencies, and hand-rolling raw elliptic-curve
--                        signing for these two is exactly the fragile
--                        implementation this build was told not to force -
--                        skipped for the identical reason, applied without
--                        exception.
--
-- WHAT WAS BUILT (10 real Web2Publisher clients - see web2_publishers.py):
--   Zenodo, Internet Archive, OSF, Figshare, Codeberg Pages, Livedoor Blog,
--   FC2 Blog, Seesaa Blog, Warpcast (via Neynar), Sourcehut Pages.

-- --- Part A: enum growth --------------------------------------------------------
alter type public.web2_platform add value if not exists 'Zenodo';
alter type public.web2_platform add value if not exists 'Internet Archive';
alter type public.web2_platform add value if not exists 'OSF';
alter type public.web2_platform add value if not exists 'Figshare';
alter type public.web2_platform add value if not exists 'Codeberg Pages';
alter type public.web2_platform add value if not exists 'Livedoor Blog';
alter type public.web2_platform add value if not exists 'FC2 Blog';
alter type public.web2_platform add value if not exists 'Seesaa Blog';
alter type public.web2_platform add value if not exists 'Warpcast';
alter type public.web2_platform add value if not exists 'Sourcehut Pages';

-- --- Part B: catalog upsert ------------------------------------------------------
insert into public.web2_platforms
  (name, homepage_url, signup_url, publish_url_or_method, auth_type, authority_tier, market, automation_ready, notes)
values
  ('Zenodo','https://zenodo.org','https://zenodo.org/signup/','api: ZenodoClient (integrations/web2_publishers.py) - POST https://zenodo.org/api/deposit/depositions to create a deposition, then POST .../actions/publish to make it live, Bearer token','api','high','global',true,'Real Web2Publisher live. CERN-operated, self-serve token, confirmed current in 2026. Publish is one-way - a second publish() call against an already-published record re-fetches instead of erroring.'),
  ('Internet Archive','https://archive.org','https://archive.org/account/signup','api: InternetArchiveClient (integrations/web2_publishers.py) - PUT https://s3.us.archive.org/{item}/{file} with an `Authorization: LOW key:secret` header (IA''s own S3-like scheme), auto-creates the item via x-archive-auto-make-bucket','api','high','global',true,'Real Web2Publisher live. A documented 503 SlowDown already falls inside the shared HTTP client''s universal 5xx transient-retry range - no special-case handling needed.'),
  ('OSF','https://osf.io','https://osf.io/register','api: OSFClient (integrations/web2_publishers.py) - POST https://api.osf.io/v2/nodes/ (JSON:API), Bearer token, explicitly sets public: true (OSF nodes default PRIVATE otherwise)','api','medium','global',true,'Real Web2Publisher live. Center for Open Science, self-serve personal access token, confirmed current in 2026.'),
  ('Figshare','https://figshare.com','https://figshare.com/account/register','api: FigshareClient (integrations/web2_publishers.py) - POST https://api.figshare.com/v2/account/articles (raw `token` auth, not Bearer), then an explicit POST .../publish call','api','high','global',true,'Real Web2Publisher live. Two-step create-then-publish, mirrors Zenodo''s own design. Public URL uses Figshare''s stable DOI convention rather than a guessed title-slug web path.'),
  ('Codeberg Pages','https://codeberg.page','https://codeberg.org/user/sign_up','api: CodebergPagesClient (integrations/web2_publishers.py) - Gitea Contents API, PUT /api/v1/repos/{owner}/{repo}/contents/{path} to commit a static file to the `pages` branch, `Authorization: token <TOKEN>`','api','medium','global',true,'Real Web2Publisher live. Non-profit, EU-hosted Gitea instance; mirrors GitHubPagesClient almost exactly (Gitea''s Contents API is API-compatible with GitHub''s).'),
  ('Livedoor Blog','https://blog.livedoor.com','https://member.livedoor.com/register/mail','api: LivedoorBlogClient (integrations/web2_publishers.py) - AtomPub POST https://livedoor.blogcms.jp/atompub/{blog}/article, HTTP Basic with the Livedoor ID + a separately-issued AtomPub API key (never the account password)','api','medium','jp',true,'Real Web2Publisher live. Same AtomPub protocol as HatenaBlogClient - reuses its Atom-entry XML builder/parser directly.'),
  ('FC2 Blog','https://blog.fc2.com','https://blog.fc2.com/','api: FC2BlogClient (integrations/web2_publishers.py) - legacy metaWeblog XML-RPC (metaWeblog.newPost/getPost) at http://blog.fc2.com/xmlrpc.php, username + password (no OAuth on this legacy protocol)','api','medium','jp',true,'Real Web2Publisher live. Shares the _MetaWeblogClient base with Seesaa Blog (identical protocol, different endpoint). getPost fetches the real permalink rather than guessing a subdomain URL pattern.'),
  ('Seesaa Blog','https://blog.seesaa.jp','https://blog.seesaa.jp/','api: SeesaaBlogClient (integrations/web2_publishers.py) - the SAME metaWeblog XML-RPC protocol as FC2 Blog, endpoint https://ssl.seesaa.jp/blog/rpc (the SSL endpoint, preferred over the plain-HTTP one), username + password','api','medium','jp',true,'Real Web2Publisher live. Shares the _MetaWeblogClient base with FC2 Blog.'),
  ('Warpcast','https://warpcast.com','https://warpcast.com/','api: WarpcastClient (integrations/web2_publishers.py) - POST https://api.neynar.com/v2/farcaster/cast via Neynar, `x-api-key` header (NOT Authorization Bearer) + a pre-approved signer_uuid credential','api','medium','global',true,'Real Web2Publisher live. Farcaster/Neynar confirmed current in 2026. The signer-approval handshake happens once, outside this system, by the account owner. Permalink uses the documented short-hash convention; falls back to verified=false if the response omits a username.'),
  ('Sourcehut Pages','https://srht.site','https://sr.ht/register','api: SourcehutPagesClient (integrations/web2_publishers.py) - GraphQL POST https://pages.sr.ht/query, a `publish(domain, content)` mutation taking a tarball Upload, sent as a standard GraphQL multipart request built entirely from the stdlib (tarfile + io.BytesIO)','api','medium','global',true,'Real Web2Publisher live. SourceHut confirmed operating in 2026; the GraphQL schema + the graphql-multipart-request-spec are both concretely documented, unlike GitBook''s content-push flow.')
on conflict (name) do update set
  automation_ready = excluded.automation_ready,
  auth_type = excluded.auth_type,
  publish_url_or_method = excluded.publish_url_or_method,
  notes = excluded.notes;
