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

Vault convention: `provider = "web2:<Platform>"`, `label = <client_id>`, `secret` =
a JSON blob with the fields below.

| Platform | Vault secret JSON | How to get it |
|---|---|---|
| WordPress.com | `{"oauth_token": "...", "site": "clientblog.wordpress.com"}` | Register an app at [developer.wordpress.com/apps](https://developer.wordpress.com/apps), OAuth2 authorization-code flow as the CLIENT's own WordPress.com account, `site` is the client's site slug. |
| Blogger | `{"oauth_token": "...", "blog_id": "..."}` | Create a Google Cloud project → enable "Blogger API v3" → OAuth 2.0 client → consent as the client's Google account (scope `.../auth/blogger`). `blog_id` from the client's Blogger dashboard URL. |
| Tumblr | `{"oauth_token": "...", "blog": "myblog.tumblr.com"}` | Register an app at [tumblr.com/oauth/apps](https://www.tumblr.com/oauth/apps) → OAuth2 (scopes `basic write offline_access`) as the client's Tumblr account. |

**Do this first.** It's 3 accounts, no new code, and it unblocks the entire
plan → write → review → publish pipeline for every client going forward.

---

## 2. Web 2.0 — the 10 newly-added platforms (do per client, as needed)

Same vault convention (`provider = "web2:<Platform>"`, `label = <client_id>`).

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

## 5. Apify fallback (optional — only if self-hosting genuinely can't reach a directory)

Per the user's own call on this build (self-hosted primary, Apify as an occasional
fallback — the reference plan's cost model has self-hosted beating Apify ~2.5×):

| Setting | How to get it |
|---|---|
| `APIFY_API_TOKEN` | Apify account → Settings → Integrations → API tokens. |
| `APIFY_CITATION_ACTOR_ID` | The Citation Builder actor's id/slug from the Apify Store (or your own custom actor). |

Only set these once a specific directory has proven genuinely unreachable by the
self-hosted bot — routing a directory's `submit_method` to `"apify"` in the
`directories` catalog is a manual, deliberate per-row decision, not a default.

---

## A note on promises

Every entry above degrades cleanly without the key: the pipeline holds the
placement/citation at a clean `blocked`/`needs_review` state, never crashes, never
guesses. Nothing here is load-bearing for the platform to run — it's load-bearing
for a SPECIFIC engine to stop degrading. Prioritize by which client campaign needs
which engine next, not by working the whole list up front.
