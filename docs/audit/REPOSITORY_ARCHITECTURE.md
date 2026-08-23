# REPOSITORY ARCHITECTURE — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit at audit:** `79d1036` · **Branch:** `main`
**Method:** static inspection of every source tree, AST analysis of the route/guard surface,
SQL inspection of all 80 migrations, plus a real `tsc --noEmit` and `next build` of the frontend.

> **Audit limitation, stated up front.** The backend test suite was **not executed**. The only
> interpreter on this machine is Python 3.14; the project pins `>=3.11` and its dependency set
> (psycopg, celery/kombu, pydantic-core) does not resolve cleanly on 3.14, and no venv was
> present. Every backend claim below is therefore **code-verified, not run-verified**. The
> frontend **was** built and typechecked successfully. Anywhere a claim depends on runtime
> behaviour I have said so explicitly rather than asserting it.

---

## 1. Top-level layout

| Path | What it is | Size |
|---|---|---|
| `backend/` | FastAPI API + Celery workers + provider integrations | ~62k LOC app, ~13k LOC integrations, ~68k LOC tests |
| `frontend/` | Next.js 15 / React 19 dashboard (admin, team, client portals) | ~27k LOC TS/TSX, 136 components |
| `danyals-audit-system/` | **Separate Python product** — the SEO audit engine | ~20k LOC |
| `db/` | 80 ordered SQL migrations + a synced `schema.sql` snapshot | 77 tables |
| `wordpress-plugin/aios-publisher/` | Companion WordPress plugin (PHP) | ~1.5k LOC |
| `infra/` | nginx + Caddy + systemd units + Portainer/compose docs | — |
| `dashboard/` | A separate 3-file Python/HTML ops bridge (`bridge.py`, `worker.py`) | ~430 LOC |
| `tools/`, `spotino-theme/`, `scratchpad-hero/`, `*.bat`, `*.ps1`, `*.zip` | Loose operator scripts, a WP theme, build artefacts | — |
| `context/`, `knowledge-base/`, `docs/` | Requirements, decisions, client deliverables | — |

**Observation.** The repository root is not clean. It carries committed binaries
(`SEO-CONTENT-OS.zip` 1.1 MB, `spotino-theme.zip`, `aios-publisher.zip`, a 436 KB PNG),
one-off operator scripts (`Finish-Citations.bat`, `push-to-wordpress.ps1`,
`tools/finish_citation.py`), and a second, unrelated mini-dashboard (`dashboard/`) that no
documented deployment references. None of this is wired into CI or the Docker image.

---

## 2. Runtime topology (`docker-compose.yml`)

```
                          ┌──────────────────────────────┐
   Internet ── 443 ──────►│ nginx  (jonasal/nginx-certbot)│  app.qanry.com
                          └───────┬──────────────┬────────┘
                                  │ /            │ /api/v1
                          ┌───────▼──────┐ ┌─────▼────────────────┐
                          │ web          │ │ api                  │
                          │ Next.js 15   │ │ uvicorn --workers 2  │
                          │ standalone   │ │ FastAPI              │
                          └──────────────┘ └───┬──────────┬───────┘
                                               │          │
   ┌───────────┐   ┌───────────┐   ┌───────────▼──┐  ┌────▼───────┐
   │ beat      │──►│ redis 7   │◄──│ worker       │  │ postgres16 │
   │ celery    │   │ broker +  │   │ celery       │──►│  RLS       │
   │ beat      │   │ ratelimit │   │ -c 4         │  └────────────┘
   └───────────┘   └───────────┘   └──────┬───────┘
                                          │ subprocess
                                   ┌──────▼────────────────────┐
                                   │ /opt/audit-venv/bin/python│
                                   │ danyals-audit-system CLI  │
                                   └───────────────────────────┘
   migrate  (one-shot, ON_ERROR_STOP, deploy.schema_migrations ledger)
   volumes: pgdata · redisdata · aios_state · nginx_secrets
```

**Seven services.** `db`, `redis`, `migrate` (one-shot), `api`, `worker`, `beat`, `web`, `nginx`.
Healthchecks exist on `db`, `redis`, `api`. Restart policy `unless-stopped` everywhere except
`migrate` (`no`). A single host; no orchestration beyond Compose.

---

## 3. Stack inventory

| Concern | Choice | Notes |
|---|---|---|
| **Framework (API)** | FastAPI (`>=0.111`) + uvicorn, 2 workers | App factory in `backend/app/main.py` |
| **Frontend** | Next.js 15.5 (App Router, `output: "standalone"`), React 19, TanStack Query 5 | No CSS framework — hand-written `globals.css`; self-hosted variable font |
| **Database** | PostgreSQL 16, self-hosted | 77 tables, 195 RLS policies, 139 indexes, 110 FK references, 70 triggers |
| **ORM** | **None.** Raw psycopg3 + hand-written SQL in 25 repo modules | Deliberate; all values bound, identifiers via `psycopg.sql.Identifier` |
| **Migrations** | 80 ordered `.sql` files, applied lexically by `infra/docker/migrate-entrypoint.sh` against a `deploy.schema_migrations` ledger | **Numbering is broken — see §7** |
| **Authentication** | Own Ed25519 (EdDSA) JWT, signed at `/auth/login`, verified with a static public key. Argon2id password hashing. No Supabase, no external IdP. | `backend/app/core/auth.py` |
| **Authorization** | Two layers: Postgres **RLS** (the real tenant boundary) + an app-layer 17-feature × 6-role permission matrix (`app/rbac/matrix.py`) | 260 of 305 endpoints carry an explicit role/permission guard |
| **API structure** | One `/api/v1` router tree: 32 routers in `app/routers/` + 15 feature modules in `app/modules/` | 305 endpoints (173 GET, 99 POST, 14 PATCH, 13 PUT, 6 DELETE) |
| **AI** | Anthropic Claude only, behind a single `Summarizer` Protocol (`integrations/llm.py`). Models: `claude-haiku-4-5` (cheap tier), `claude-sonnet-5` (heavy tier). Optional `[ai]` extra — absent SDK degrades to a deterministic fake. | Voyage/Pinecone embeddings exist but are **deliberately not deployed** |
| **External integrations** | 40 modules in `backend/integrations/`: Serper, DataForSEO, PageSpeed, Google Places/GSC/GA4/Indexing, Firecrawl, Moz, Resend/SMTP/IMAP, Slack, Backblaze B2, IndexNow, 55 Web 2.0 publishers, citation APIs + Playwright bot, CAPTCHA solver | |
| **Background workers** | Celery 5.4 on Redis. 39 registered tasks across `workers/tasks/` and `app/modules/*/tasks.py` | `task_acks_late=True`, `prefetch=1`, `visibility_timeout=3600` |
| **Queues** | Single default Celery queue. No routing, no priority lanes, no separate queue for long audits vs. short syncs. | |
| **Cron jobs** | Celery beat. **`beat_schedule = {}` — every scheduled job is off** (`workers/celery_app.py:173`). The 11-entry schedule is preserved verbatim in `_BEAT_SCHEDULE_DISABLED` immediately below. | |
| **Storage** | Local filesystem (`aios_state` volume) for audit artefacts, generated content images, backups. Backblaze B2 client exists (`integrations/b2.py`) for off-site backup. | Audit engine writes into its own repo tree |
| **Caching** | Redis, used for the cost-gate result cache and fixed-window rate limiting. No HTTP response cache, no query cache. | |
| **Config** | `pydantic-settings`, one 866-line `app/config.py`; `.env.example` (16 KB) + `.env.web2.example` (9.6 KB) document ~300 settings | Secrets are `SecretStr`; a `validate_settings` boot gate exists |
| **Deployment** | Docker Compose on a single host behind nginx+certbot. Systemd units also provided as an alternative. Portainer stack docs. | |
| **CI/CD** | GitHub Actions, `backend-ci.yml` only: ruff → mypy `--strict` → pytest+coverage → integration (real Postgres+Redis) → pip-audit → gitleaks → RLS gate. Plus a separate `ci.yml` inside the audit-engine subtree. | **No frontend CI at all** |
| **Testing** | 219 pytest files, 67.8k LOC. 161 unit-marked, 25 integration-marked, 24 in `tests/integration/`, 2 perf, 2 mutation. 116 files use injected fakes. | **Zero frontend tests; zero end-to-end tests** |
| **Logging** | `structlog`, JSON, request-id propagated by `RequestIDMiddleware` (outermost) | `app/logging_setup.py` |
| **Monitoring** | Prometheus `/metrics` with **three** metrics (request count, latency histogram, in-flight gauge). Sentry optional, DSN-gated, `traces_sample_rate=0.0`. | **No worker, queue, job, or cost metrics** |

---

## 4. Backend layering as built

```
app/routers/*  +  app/modules/*/router.py     ← HTTP, guards, activity logging
        │
app/services/*  (53 modules)                  ← business logic, pure where possible
        │
app/db/*_repo.py  (25 modules)                ← SQL, RLS-bound, one txn per call
        │
app/db/database.py                            ← rls_connection() / privileged_connection()
        │
PostgreSQL (RLS policies + guard triggers)
        ▲
integrations/*  (40 modules)                  ← outbound providers, Protocol-fronted
workers/*  +  app/modules/*/tasks.py          ← Celery tasks, compose services+integrations
```

The intent is clean hexagonal layering, and in the majority of the code it holds. Two
inversions are real and measurable:

- **`integrations/` imports `app/`.** `integrations/mcp_gateway.py:37-38` imports
  `app.services.cost_gate` and `app.services.skill_tokens`; nine further integration modules
  import `app.config` / `app.logging_setup`. The adapter layer depends on the application layer.
- **`app/db/` imports `app/services/`.** `app/db/policy_repo.py:32` imports
  `app.services.policy_baseline`. A repository depends on a service.

Neither is a runtime cycle today, but both make the seams un-extractable and will bite on any
attempt to split the monolith.

---

## 5. Frontend architecture

- **Three portals in one Next.js app**: `/admin/*` (15 routes), `/team/*` (5 routes), `/client/*`
  (5 routes), plus `/` (public free-audit funnel) and `/login`. Each portal owns its own layout
  and navigation.
- **Every route is statically prerendered** (`○` in the build output) except
  `/team/tools/[slug]`. All data arrives client-side after hydration via TanStack Query hooks in
  `lib/hooks/*`. There is no server-side data fetching and no RSC data layer.
- **One fetch seam**: `lib/api.ts` injects the bearer token from `localStorage`, decodes the
  backend error envelope, bounces to `/login` on 401, and flags 503 as "dependency unconfigured".
- **Bundle size is healthy**: 103 kB shared, largest route 148 kB first-load. `tsc --noEmit`
  passes clean; `next build` succeeds.
- **A legacy client-side demo store is still mounted.** `lib/store.tsx` is a
  localStorage-persisted context seeded from hardcoded arrays in `lib/data.ts` — clients, team
  members, tasks, activity and **plaintext demo passwords** (`teamCredentials`). It is wrapped
  around the whole tree in `app/layout.tsx:62`. No screen consumes it (`useStore` has exactly
  one importer: the provider mount itself), so it is dead weight rather than a live data source
  — but it ships in the bundle and writes seeded credentials into every visitor's localStorage.

---

## 6. The audit engine is a second product

`integrations/audit_engine.py` does **not** import the engine. It shells out:

- Runs `danyals-audit-system`'s CLI as a **subprocess** under a **separate interpreter**
  (`AUDIT_ENGINE_PYTHON=/opt/audit-venv/bin/python`) with a separate dependency set, baked into
  the backend image as a second venv (`backend/Dockerfile:46-58`).
- **Parses stdout** for `Run UUID: <uuid>` (with `COLUMNS=1000` set to defeat `rich` wrapping)
  and reconstructs the artefact path from a deterministic slug.
- Reads results off the **local filesystem** at
  `<engine_dir>/data/audits/<domain-slug>/<run_uuid>/{findings.json,run.json,report.{pdf,html}}`.
- Owns the hard timeout itself, because "the engine does not catch its own top-level exceptions
  and never times out itself".

This is a working integration, and the adapter is defensively written. It is also the single
biggest constraint on horizontal scale: audits cannot run on a machine that is not the machine
holding the artefacts, and the report bytes never reach object storage.

---

## 7. Migration numbering is broken

```
0070_site_builder.sql          0072_content_schedule.sql
0070_site_templates.sql        0072_web2_platforms_batch4.sql
```

Two duplicate ordinals, and `0052` is absent. Migrations are applied **in lexical order**
(`infra/docker/migrate-entrypoint.sh:46`, `db/migrations/README.md`), so the two `0070` files
apply in filename-alphabetical order — which is an accident, not a decision. Today the pairs
happen to be independent, so the schema converges either way. The defect is that the ordering
guarantee the runner claims no longer exists, and the next collision will not be benign.

---

## 8. Configuration and secrets

- ~300 settings in one `app/config.py`; every secret typed `SecretStr`; a startup
  `validate_settings` gate.
- **No real secret is committed.** `.env` files are gitignored; only `.env.example` variants are
  tracked. A gitleaks job runs in CI with a narrow allowlist.
- Two hygiene defects, neither a live credential:
  - `frontend/lib/vault.ts:101-113` — a `vaultKeys` array of **realistic-looking fake API keys**
    (`sk-ant-…`, `AIzaSy…`, `ya29.…`, WordPress app passwords) with both `masked` and `secret`
    fields. Unimported, but present in the source tree and a permanent secret-scanner false
    positive.
  - `frontend/lib/data.ts` — `teamCredentials`, plaintext demo passwords for eight named users.

---

## 9. Branding rule violation

The specification's hard rule (§1.1): *the builder's name must never appear anywhere in the
running software, its configuration, its tests, or its generated output*. It appears in three
places that reach a runtime surface:

| Location | Exposure |
|---|---|
| `wordpress-plugin/aios-publisher/aios-publisher.php:6,8-9` — `Author: Xegents AI`, `Plugin URI: https://xegents.ai` | **Visible in every end-client's wp-admin plugin list** |
| `wordpress-plugin/aios-publisher/readme.txt:2` — `Contributors: xegentsai` | Shipped to client sites |
| `backend/app/services/email_templates.py:35` — `_FOOTER = "AIOS - Xegents AI. …"` | **Footer of every outbound email** |

Also in `backend/pyproject.toml` (author metadata) and several READMEs/tests, which are internal
and lower priority.
