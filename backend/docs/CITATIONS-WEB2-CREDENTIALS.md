# Citations & Web 2.0 — credentials checklist (7B-4)

Everything in `app/modules/citations/`, `integrations/web2_publishers.py`, and
`integrations/citation_*.py` is built and unit-tested against deterministic fakes —
it runs, degrades cleanly, and ships with **zero** external accounts. This doc is
the other half: the concrete list of accounts/keys a human (Danyal or Adan) has to
go create before a given engine goes from "holds at review / blocked" to actually
live. Nothing here can be done by an agent — every one of these needs a real person,
a real phone number, and in most cases a payment method.

Work top-to-bottom by leverage: Section 1 unblocks the 3 platforms already fully
wired (highest value for the least setup). Sections 2–4 are additive — add them
whenever the next client campaign needs that engine.

Every secret goes into the **vault**, not `.env`, unless marked "agency-wide" below.
Vault rows use `kind=client_access` for per-client credentials (add via the Key
Vault screen or `POST /vault/keys`), `kind=api_key` for agency-wide ones.

---

## 1. Web 2.0 — per-client OAuth (unblocks WordPress.com / Blogger / Tumblr TODAY)

These three platforms are fully coded and tested; they only need a credential
**per client, per platform** in the vault to go live. Nothing else to build.

Vault convention: `provider = "web2:<Platform>"`, `label = <web2_accounts.id>`,
`secret` = a JSON blob with the fields below. (The label was the CLIENT id until
2026-08-25; see the superseded note in §2 for why that changed.)

| Platform | Vault secret JSON | How to get it |
|---|---|---|
| WordPress.com | `{"oauth_token": "...", "site": "clientblog.wordpress.com"}` | Register an app at [developer.wordpress.com/apps](https://developer.wordpress.com/apps), OAuth2 authorization-code flow as the CLIENT's own WordPress.com account, `site` is the client's site slug. |
| Blogger | `{"oauth_token": "...", "blog_id": "..."}` | Create a Google Cloud project → enable "Blogger API v3" → OAuth 2.0 client → consent as the client's Google account (scope `.../auth/blogger`). `blog_id` from the client's Blogger dashboard URL. |
| Tumblr | `{"oauth_token": "...", "blog": "myblog.tumblr.com"}` | Register an app at [tumblr.com/oauth/apps](https://www.tumblr.com/oauth/apps) → OAuth2 (scopes `basic write offline_access`) as the client's Tumblr account. |

**Do this first.** It's 3 accounts, no new code, and it unblocks the entire
plan → write → review → publish pipeline for every client going forward.

---

## 2. Web 2.0 — the 10 newly-added platforms (do per client, as needed)

Same vault convention (`provider = "web2:<Platform>"`, `label = <web2_accounts.id>`).

> **SUPERSEDED 2026-08-25 — the house-account fan-out is gone (R2-06).** This section
> used to tell you to put one set of shared HOUSE logins in
> `WEB2_HOUSE_CREDENTIALS_JSON` and run `app.cli.seed_web2_vault`, which COPIED that
> one credential into every client's vault row. That was the defect, not the feature:
> one shared login is one shared failure domain (a suspension takes every client's
> property down at once), and the per-client copies made the clients mutually
> identifiable. The setting, the CLI and its test have all been deleted.
>
> An account is now a row in `public.web2_accounts` (migration `0100`) whose
> credential is sealed **once** under `label=<web2_accounts.id>`:
>
> ```bash
> # a client-owned account (the default for WordPress.com / Blogger / Tumblr)
> python -m app.cli.web2_accounts register --platform "Blogger" \
>     --ownership per_client --client-id <uuid> --handle <client-brand-handle> \
>     --email web@clientdomain.co.uk --credential-file creds.json --yes
>
> # an agency house account, only where publishing implies no durable identity
> python -m app.cli.web2_accounts register --platform "Telegra.ph" \
>     --ownership house --handle aios-house-telegraph --max-properties 10 --yes
>
> python -m app.cli.web2_accounts list          # what exists, health, property caps
> python -m app.cli.web2_migrate_house          # dry run: reconcile the legacy rows
> ```
>
> A per-client handle is REJECTED if it embeds the platform name or a long hex run,
> and its registration email may not use the shared catch-all domain — those were the
> three keys that let a platform enumerate the whole client base from one suspended
> account. Existing legacy rows keep working (the publisher falls back to the old
> client-id label) until `web2_migrate_house --yes` attributes them.

| Platform | Vault secret JSON | How to get it |
|---|---|---|
| dev.to | `{"api_key": "..."}` | dev.to → Settings → Extensions → generate an API key. |
| Write.as | `{"token": "...", "alias": "..."}` | Sign up at write.as; `alias` is the collection/blog name. Anonymous posting needs neither field. |
| Telegra.ph | `{"access_token": "..."}` | No signup: `POST https://api.telegra.ph/createAccount` once, keep the returned `access_token`. |
| Mataroa | `{"api_key": "..."}` | mataroa.blog → account settings → generate an API key. |
| Ghost | `{"admin_api_key": "id:secret", "api_url": "https://x.ghost.io"}` | Ghost Admin → Settings → Integrations → "Add custom integration" (Ghost(Pro) needs the **Publisher** tier or higher, or a self-hosted instance). |
| Mastodon | `{"access_token": "...", "instance_url": "https://..."}` | On the chosen instance: Preferences → Development → New application (scope `write:statuses`). |
| GitHub Pages | `{"token": "...", "owner": "...", "repo": "..."}` | A fine-grained PAT with `contents:write` + `pages:write` on a repo that already exists with Pages enabled (or let the client create one first). |
| GitLab Pages | `{"token": "...", "project_id": "namespace/project"}` | A Project Access Token with `write_repository` scope; the project needs a `.gitlab-ci.yml` with a `pages` job already committed (this client builds/publishes via CI, not this seam). |
| Micro.blog | `{"token": "..."}` | micro.blog/account/apps → generate an app token (Micropub). |
| Hashnode | `{"pat": "...", "publication_id": "..."}` | hashnode.com/settings/developer → generate a PAT; `publication_id` from the client's existing publication/blog. |
| Hatena Blog | `{"hatena_id": "...", "blog_id": "...", "api_key": "..."}` | Blog settings → Advanced → AtomPub section shows the API key. |
| LiveJournal / Dreamwidth | `{"username": "...", "password": "..."}` | The client's own account credentials (legacy platforms, no OAuth). |

---

## 2b. Web 2.0 — the 4 newest platforms (Webflow / HubSpot CMS / Drupal / Joomla)

Same vault convention (`provider = "web2:<Platform>"`, `label = <web2_accounts.id>`).

| Platform | Vault secret JSON | How to get it |
|---|---|---|
| Webflow | `{"api_token": "...", "collection_id": "...", "site": "...", "url_path": "blog"}` | Project Settings → Apps & Integrations → API Access → generate a site API token (Data API v2). `collection_id` from the target CMS collection's settings panel. `site` is the `*.webflow.io` subdomain (Webflow's item response carries no absolute URL). `url_path` is optional (defaults to `"blog"`) — the collection's configured slug path. |
| HubSpot CMS | `{"access_token": "...", "content_group_id": "..."}` | Settings → Integrations → Private Apps → create one with the `content` scope. `content_group_id` is the target blog's id — HubSpot needs an existing blog to post into. |
| Drupal | `{"base_url": "...", "username": "...", "password": "...", "content_type": "article"}` | Create an API-only Drupal user (Basic-auth) with permission to create/edit content — Drupal core's JSON:API ships from core >= 8.7, no contrib module needed. `content_type` is optional (defaults to `"article"`), the node bundle machine name. |
| Joomla | `{"base_url": "...", "api_token": "...", "catid": "..."}` | Users → Edit your user → API Token tab → generate (Joomla 4.3+ core Web Services API). `catid` is the target category id, from that category's edit URL. |

---

## 2c. Web 2.0 — the third pass (19 more, Aug 2026)

Same vault convention (`provider = "web2:<Platform>"`, `label = <web2_accounts.id>`). Every
one below was web-verified live/self-serve at build time — see
`integrations/web2_publishers.py`'s module docstring for the platforms that were
investigated and deliberately **skipped** instead (Evernote, Issuu, Nostr long-form)
and why.

| Platform | Vault secret JSON | How to get it |
|---|---|---|
| HackMD | `{"token": "..."}` | hackmd.io → Settings → API → generate a token. |
| GitHub Gist | `{"token": "..."}` | A PAT (classic or fine-grained) with `gist` scope. |
| GitLab Snippets | `{"token": "..."}` | A PAT with `api` scope. |
| paste.ee | `{"api_key": "..."}` | paste.ee/account/api → generate a key. |
| Pastebin.com | `{"api_dev_key": "..."}` | pastebin.com/doc_api → your account's `api_dev_key`. No edit endpoint reachable with just this key — every publish is a new paste. |
| Netlify | `{"api_token": "...", "site_id": "..."}` | User settings → Applications → Personal access tokens; `site_id` is an existing site (create one by hand first). One deploy replaces the whole site's prior deploy. |
| Neocities | `{"api_key": "...", "sitename": "..."}` | Site Settings → API key; `sitename` is the account's own `{sitename}.neocities.org` subdomain. |
| rentry.co | `{}` | **Fully anonymous** — no credential at all, just a vault row (even an empty `{}`) to opt the client in. |
| dpaste.org | `{}` | **Fully anonymous** — no credential at all, same as rentry.co. |
| Misskey | `{"token": "...", "instance_url": "https://misskey.io"}` | On the instance: Settings → API → generate an access token. `instance_url` is optional (defaults to misskey.io). |
| Lemmy | `{"username": "...", "password": "...", "community": "...", "base_url": "https://lemmy.world"}` | Sign up on the instance; `community` is the target community's name (the backlink posts as a link-post into it). `base_url` is optional. |
| Bluesky | `{"identifier": "...", "app_password": "..."}` | bsky.app/settings/app-passwords → generate an **App Password** (never the main account password). |
| WhiteWind | `{"identifier": "...", "app_password": "..."}` | Reuses the SAME Bluesky account/App Password as above — not a separate signup, just a different XRPC record collection. |
| Disqus | `{"access_token": "...", "api_key": "...", "username": "..."}` | disqus.com/api/docs → register an app for a public/secret key pair, then OAuth2 for the `access_token`. A **thin profile placement**, not an article — updates the account's public profile `url`/`about` fields. |
| Plurk | `{"consumer_key": "...", "consumer_secret": "...", "access_token": "...", "access_token_secret": "..."}` | plurk.com/PlurkApp → register an OAuth1 app, then complete the OAuth1 dance for a user token. The one OAuth1 (not OAuth2) platform here. |
| Pixelfed | `{"access_token": "...", "placeholder_image_url": "...", "instance_url": "https://pixelfed.social"}` | Register an app on the instance for a token. `placeholder_image_url` is a fixed brand image URL — Pixelfed (unlike Mastodon) requires an image on every post, so this client fetches + uploads it each publish. |
| Notion | `{"integration_token": "...", "parent_page_id": "..."}` | notion.so/my-integrations → create an internal integration, then **share a parent page with it** (Notion can't create a page at the workspace root). Always publishes `verified=False` — a human must still open the created page and toggle "Share to web" (the API has no endpoint for that, confirmed against 2026 docs). |
| Gravatar | `{"api_token": "...", "username": "..."}` | Gravatar Developer Dashboard → API key. A **thin profile placement**, not an article — updates the profile's `description` + a public `links` entry. |
| Minds | `{"access_token": "..."}` | Settings → API → personal access token. |

---

## 2d. Web 2.0 — the fourth pass (10 more, Aug 2026)

Same vault convention (`provider = "web2:<Platform>"`, `label = <web2_accounts.id>`). Every
one below was web-verified live/self-serve at build time — see
`integrations/web2_publishers.py`'s module docstring for the platforms that were
investigated and deliberately **skipped** this pass instead (CodeSandbox, GitBook,
Read the Docs, Hive, Steemit) and why.

| Platform | Vault secret JSON | How to get it |
|---|---|---|
| Zenodo | `{"access_token": "...", "creator_name": "..."}` | zenodo.org → Applications → Personal access tokens. `creator_name` is optional (defaults to `"Editorial Team"`). Publish is one-way — a second `publish()` call against an already-published record re-fetches instead of erroring. |
| Internet Archive | `{"access_key": "...", "secret_key": "...", "item_prefix": "..."}` | archive.org/account/s3.php → your S3-like access/secret keys. `item_prefix` is optional — IA item identifiers are GLOBAL (not per-account), so a prefix avoids colliding with an unrelated existing item of the same bare slug. |
| OSF | `{"access_token": "..."}` | osf.io/settings/tokens → generate a personal access token. Always creates the node with `public: true` explicitly (OSF nodes default private). |
| Figshare | `{"access_token": "..."}` | figshare.com/account/applications → generate a personal token. Two-step create-then-publish; the public URL uses Figshare's stable DOI convention. |
| Codeberg Pages | `{"token": "...", "owner": "...", "repo": "..."}` | codeberg.org/user/settings/applications → generate a token with repo scope. Mirrors GitHub Pages, but commits to a dedicated `pages` branch and uses Gitea's `token <TOKEN>` auth scheme. |
| Livedoor Blog | `{"livedoor_id": "...", "blog_name": "...", "api_key": "..."}` | Blog settings → AtomPub section shows the API key (NOT the account login password). Same AtomPub protocol as Hatena Blog. |
| FC2 Blog | `{"blog_id": "...", "username": "...", "password": "..."}` | The account's own FC2 Blog credentials (legacy metaWeblog XML-RPC, no OAuth). Shares the `_MetaWeblogClient` base with Seesaa Blog. |
| Seesaa Blog | `{"blog_id": "...", "username": "...", "password": "..."}` | The account's own Seesaa Blog credentials — the identical metaWeblog XML-RPC protocol as FC2 Blog, different endpoint. |
| Warpcast | `{"api_key": "...", "signer_uuid": "..."}` | neynar.com dashboard → API key. `signer_uuid` needs a one-time signer-approval handshake completed by the account owner (outside this system) before it can be used here. |
| Sourcehut Pages | `{"token": "...", "domain": "..."}` | meta.sr.ht/oauth/personal-token → a token scoped to pages.sr.ht. `domain` is the target `*.srht.site` (or connected custom) domain already associated with the account. |

---

## 2e. Web 2.0 — the fifth pass (3 more, Aug 2026): headless CMSs

Same vault convention. All three are **headless** — the platform stores content but
renders no public page of its own, so (same honesty as Notion in §2c) every client
here **always returns `verified=False`**; `post_url` is a best-effort deep link into
the platform's own admin UI, not a guaranteed public URL. Each also assumes a
project-specific content schema (`doc_type`/`component`/`model`, all overridable) —
if the target project's schema differs, the call fails with a clear provider error
rather than silently succeeding.

| Platform | Vault secret JSON | How to get it |
|---|---|---|
| Sanity | `{"api_token": "...", "project_id": "...", "dataset": "production", "doc_type": "post"}` | sanity.io/manage → project → API → Tokens, create one with **Editor** (write) permission. `dataset` is usually `"production"`. `doc_type` must match an actual document type in the project's schema. |
| Storyblok | `{"token": "...", "space_id": "...", "component": "page"}` | app.storyblok.com → space Settings → Access Tokens → generate a **Management API** personal access token (not the public/preview token). `component` must match an actual content-type in the space's schema. |
| Hygraph | `{"endpoint": "...", "token": "...", "model": "post"}` | app.hygraph.com → project → Settings → API Access for the Content API `endpoint`, then Permanent Auth Tokens for `token` (needs create/publish mutation permission on the target model). `model` must be an existing content model exposing `title`/`slug`/`content` fields. |

---

## 2f. Web 2.0 — the sixth pass (1 more, Aug 2026): a EU-reachable WriteFreely instance

Same vault convention. Reuses the identical write.as/WriteFreely API `PLATFORM_WRITEAS`
already speaks (§1), just pointed at a caller-chosen `instance_url` instead of
write.as itself. Several public WriteFreely instances are individually EU-operator-run
(check the current list at writefreely.org/instances — e.g. Germany's
`text.tchncs.de`) and support a fully anonymous post, same as Write.as. **Honesty
caveat:** every one of these is a volunteer-run community project with no SLA — it can
go invite-only or vanish without notice. Pick one, sign up by hand, and re-verify it is
still open before depending on it for a client deliverable.

Candidates investigated and **rejected** this pass (no real HTTP publish API, or the
platform's own Terms of Service explicitly bans this pipeline's use case) — see
`integrations/web2_publishers.py`'s module docstring and migration `0077`'s header for
the full record: Qiita (ToS explicitly bans SEO/affiliate-purpose posting), Zenn (no
HTTP write API — GitHub-sync only, needs a manual per-account bootstrap), Bear Blog (no
write API of any kind), Substack (no official publish API; only unofficial
reverse-engineered clients exist, which the platform's own Acceptable Use Policy
prohibits), Plume (project no longer maintained; maintainers themselves recommend
WriteFreely instead).

| Platform | Vault secret JSON | How to get it |
|---|---|---|
| WriteFreely | `{"instance_url": "...", "token": "...", "target": "..."}` | Pick an open instance from writefreely.org/instances, sign up by hand (email only, no phone/ID). `token`/`target` are optional — a blank token posts anonymously (public-by-URL, not part of a listed blog); `target` is the collection alias if the account has one. |

---

## 3. Citations — direct-API engines (agency-wide keys, `.env`)

Unlike Web2 credentials, these two are **agency-wide** (one key covers every
client) — set them in `.env`, not the vault.

| Setting | How to get it |
|---|---|
| `BING_PLACES_API_KEY` | Bing Places for Business partner/API program. **Confirm the exact bulk-upload endpoint against the current partner docs at setup time** — `integrations/citation_apis.py`'s own docstring flags this as the one thing to re-verify before enabling. |
| `FOURSQUARE_API_KEY` | Foursquare developer account (developer.foursquare.com). **Same caveat** — Foursquare's public API is primarily a read/data product; confirm the current "add/claim a place" write path before relying on it. |

Data Axle and Neustar/Localeze are **deliberately not automated** — the reference
catalog tags both `manual_only` because neither exposes a public write API (portal
submission only). OpenStreetMap likewise has a real API but is tagged `manual_only`
on purpose — community norms explicitly forbid bulk/automated POI inserts.

---

## 4. Citations — the self-hosted Playwright bot (bot_fillable / captcha_assisted)

This is the highest-coverage engine (~120 of the 155 catalogued directories) and
needs the most setup. Three pieces:

1. **Install Playwright on the VPS** (not in the base install — see
   `pyproject.toml`'s `automation` extra):
   ```bash
   pip install -e .[automation]
   playwright install chromium
   ```
2. **A CAPTCHA-solver account** (for `captcha_assisted` directories only —
   `bot_fillable` directories need none of this):
   - Sign up at [capsolver.com](https://capsolver.com) (or capmonster.cloud — set
     `CAPTCHA_SOLVER_PROVIDER=capmonster`), fund the balance (a few dollars covers
     thousands of solves at the reference plan's own ~$0.0006–0.003/solve figures).
   - Set `CAPTCHA_SOLVER_API_KEY` in `.env` (agency-wide, not per-client).
3. **A budget residential proxy** (optional at low volume; recommended once
   submitting at scale to avoid one VPS IP hammering every directory):
   - Any budget residential provider from the reference plan's cost table
     (DataImpulse, IPRoyal, Webshare — all ~$1–2/GB).
   - Set `CITATION_PROXY_URL=http://user:pass@host:port` in `.env`.
4. **Set `CITATION_ARTIFACT_DIR`** to a writable path — every submission's proof
   screenshot lands here (surfaced in the dashboard as the citation's `proofUrl`).

**Per-directory login credentials** (a handful of `bot_fillable` directories ask
you to create an account before listing, distinct from the CAPTCHA-solver key
above) go in the vault as `kind=client_access`, `provider="citation:<Directory
Name>"`, `label=<client_id>` — not yet wired into `citation_bot.py`'s dispatch
(today's `FORM_SPECS` catalog only covers directories with a no-login public form).

**Extending coverage.** `integrations/citation_bot.py`'s `FORM_SPECS` dict currently
covers 12 representative US directories. Adding the rest of the catalog's
`bot_fillable`/`captcha_assisted` rows is DATA, not code — one `FormSpec` entry per
directory (URL + field selectors + submit button + success indicator), verified
against that directory's current live form before trusting it at scale (the
selectors shipped here are best-effort starting points, not hand-verified against
every site's current DOM — see the module's own docstring).

---

## A note on promises

Every entry above degrades cleanly without the key: the pipeline holds the
placement/citation at a clean `blocked`/`needs_review` state, never crashes, never
guesses. Nothing here is load-bearing for the platform to run — it's load-bearing
for a SPECIFIC engine to stop degrading. Prioritize by which client campaign needs
which engine next, not by working the whole list up front.
