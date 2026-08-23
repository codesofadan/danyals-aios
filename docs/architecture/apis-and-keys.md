# APIs & Keys — the provider → consumer map

Every external provider, the setting/vault key that lights it up, and what happens without
it. Grounded in `backend/app/config.py` (`Settings`) and
`backend/docs/CITATIONS-WEB2-CREDENTIALS.md`.

**Golden rule (invariant #5): keys are gated dormant→live.** A provider seam is built as
`*_from_settings() → real client | None`. When the key is absent the module **degrades**
to a deterministic fake or a no-op and reports it honestly ("ran on the deterministic fake;
live pending <KEY>") — it never crashes and never presents fake output as live. All
secrets are `SecretStr` (never logged, never in a repr); the token/secret is revealed only
at client construction.

## Provider keys (agency-wide, in `.env` / `/etc/aios/aios.env`)

| Setting (env) | Provider | Powers | Degrades to |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic **Claude** | content drafting + QA judge, context summaries, policy analysis, GMB posts, `/ai/assist` | fakes / holds job at `drafting` $0 |
| `SERPER_API_KEY` | **Serper.dev** | content research (top-10 SERP teardown), backlinks, citations SERP, keyword SERP | deterministic SERP fake |
| `EMBEDDINGS_API_KEY` | **Voyage AI** (`voyage-3`, dim 1024) | context chunk embeddings | `FakeEmbedder` |
| `PINECONE_API_KEY` + `PINECONE_INDEX` | **Pinecone** | derived context vector index (namespace `type:id`) | in-memory vector store |
| `IMAGE_GEN_API_KEY` | image model (`gpt-image-1`, OpenAI-compatible) | AI content images + alt text | artifact without images |
| `DATAFORSEO_LOGIN` + `DATAFORSEO_PASSWORD` | **DataForSEO** | keyword metrics + technical-audit live rank data | fake metrics / Serper fallback |
| `GOOGLE_SHEETS_SA_JSON` | Google Sheets (service account) | reporting push | Sheets sync = no-op |
| `GOOGLE_OAUTH_CLIENT_ID` + `_SECRET` + `_REDIRECT_URI` | Google OAuth | site-analytics GSC/GA4 import | analytics hold |
| `RESEND_API_KEY` (+ `RESEND_FROM_EMAIL`) | **Resend** | transactional email notifications | email leg skipped |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook | ops alerts | Slack leg skipped |
| `B2_KEY_ID` + `B2_APPLICATION_KEY` + `B2_BUCKET` (+ `B2_ENDPOINT_URL`) | **Backblaze B2** | off-site Postgres backups | backup upload skipped |

## Citations / Web 2.0 — extra keys

| Setting | Provider | Notes |
|---|---|---|
| `BING_PLACES_API_KEY` | Bing Places | direct-API citation submit (verify bulk endpoint at setup) |
| `FOURSQUARE_API_KEY` | Foursquare | direct-API citation submit (verify write path) |
| `CAPTCHA_SOLVER_API_KEY` (+ `CAPTCHA_SOLVER_PROVIDER` capsolver/capmonster) | CAPTCHA solver | for `captcha_assisted` directories (self-hosted Playwright bot) |
| `CITATION_PROXY_URL` | residential proxy | optional; recommended at scale |
| `CITATION_ARTIFACT_DIR` | local path | where submission proof screenshots land (`proofUrl`) |
| `APIFY_API_TOKEN` + `APIFY_CITATION_ACTOR_ID` | Apify | fallback engine, only for directories the self-hosted bot can't reach |
| `WEB2_HOUSE_CREDENTIALS_JSON` | Web2 house accounts | seeded into per-client vault rows by `app.cli.seed_web2_vault` |

Data Axle, Neustar/Localeze, OpenStreetMap are deliberately **`manual_only`** (no
automated write path).

## Per-client / per-site secrets — the VAULT, not `.env`

WordPress app-passwords, Web 2.0 OAuth tokens, and per-directory citation logins are
per-client/per-site and live **encrypted in the vault**, not settings:
- `kind=api_key` — agency-wide vault rows.
- `kind=client_access` — per-client rows (e.g. `provider="web2:<Platform>"` or
  `provider="citation:<Directory>"`, `label=<client_id>`). Add via the Key Vault screen or
  `POST /vault/keys`.

## Infra/auth secrets (prod-required — `validate_settings` fails fast without them)

`DATABASE_URL`, `DATABASE_ADMIN_URL` (the two DB seams), `JWT_PRIVATE_KEY` +
`JWT_PUBLIC_KEY` (EdDSA token signing/verify), `VAULT_MASTER_KEY` (AES-256-GCM vault
seal — env-only, NEVER in Postgres; rotating it re-seals existing secrets),
`REDIS_URL` (+ `CELERY_BROKER_URL` / `CELERY_RESULT_BACKEND` on separate Redis DBs).

## Consumer map (which module needs which key)

- **Content** → Anthropic (writer, the gate) + Serper (research) + image key + per-site
  WordPress (vault).
- **Audit** → the external audit_engine (its own venv/`.env`) + DataForSEO/PageSpeed for
  Paid.
- **Context** → Anthropic + Voyage + Pinecone.
- **Off-page / Citations / Web2** → Serper + Web2 house/vault creds + Bing/Foursquare/
  CAPTCHA/proxy/Apify.
- **Policy Radar / GMB / In-product AI** → Anthropic (Haiku).
- **Reports / Site-analytics** → Google (Sheets SA / OAuth).
- **Notifications** → Resend + Slack. **Backups** → Backblaze B2.

The authoritative, always-current list is `DIAL_FEATURES` in `app/schemas/cost.py` (each
entry names its `provider`) and the `Settings` fields in `app/config.py`.
