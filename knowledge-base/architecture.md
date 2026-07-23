# Architecture

Source of truth: `backend/CLAUDE.md`, `backend/docs/ARCHITECTURE.md`,
`context/ARCHITECTURE-AND-PLAN.md`.

## Shape

A **modular monolith**: one deployable Python service (FastAPI API + Celery workers)
over native **PostgreSQL 16** (per-tenant Row-Level Security) + **Redis** (queue +
cache), with a **Next.js** dashboard/portal in front. Long, expensive provider work is
pushed off the request path into the Celery queue so the UI stays responsive and spend
stays inside concurrency + budget caps.

```
Browser (agency staff + client portal)
      │  HTTPS
      ▼
Caddy (auto-TLS reverse proxy)
   ├── Next.js  (frontend/ — dashboard + client portal)
   └── FastAPI  (backend/app — /api/v1 business routes; /health at root)
             │
     ┌───────┼─────────────────────────────┐
     ▼       ▼                             ▼
 PostgreSQL 16   Redis (queue db1 / cache db0 / result db2)   Key Vault (AES-256-GCM in PG)
     ▲                    │
     │        Celery workers (backend/workers) pull jobs:
     └────────  audit · content · context · offpage · policy
                        │ call external providers through key-gated seams
                        ▼
         Serper · Google · Anthropic(Claude) · Voyage · Pinecone · WordPress ·
         Resend · Slack · Backblaze-B2 · the external audit_engine (subprocess)
```

## The FastAPI app (`backend/app/`)

- `main.py` — `create_app()` factory + module-level `app`. A **lifespan** owns shared
  clients on `app.state` (one `httpx.AsyncClient`, the `redis.asyncio` client).
- Middleware order TrustedHost → CORS → RequestID (RequestID ends up **outermost**);
  `MetricsMiddleware` is inside RequestID.
- Business routes mount under **`/api/v1`** via the `api_v1` aggregator
  (`app/routers/__init__.py` + `app/modules/__init__.py`); health lives at root
  (`/health` liveness, `/health/ready` readiness — bounded, concurrent dependency pings).
- `config.py` — `Settings` (pydantic-settings, `.env`), `@lru_cache get_settings()`,
  `validate_settings()` fails fast in prod on a missing required secret. Secrets are
  `SecretStr`, never logged.

## The two DB seams (the whole data-access contract)

`backend/app/db/database.py` exposes exactly two connections:

| Seam | Postgres role | RLS | Use for |
|---|---|---|---|
| `rls_connection(user_id)` | `authenticated` | **applies** | tenant reads/writes as the verified server-side identity (`set_config('app.user_id', sub, true)`) |
| `privileged_connection()` | `service_role` | **BYPASSRLS** | server-only writes (workers, vault, activity append). Bypasses **policies, not triggers** |

RLS is the tenant boundary (invariant): every base table is `ENABLE`+`FORCE RLS`; a CI
gate (`app/db/rls_check.py`) fails on any unprotected `public` table. Clients never touch
a base table — they read three **security-barrier views** filtered by
`current_client_id()`.

## The module-per-feature layout (`backend/app/modules/`)

New features are self-contained packages: `router.py` (thin) · `schemas.py`
(contract-locked to `frontend/lib/*.ts` where a type exists) · `repo.py` (uses the two
seams) · `service.py` (cost-gate + activity/context feed) · `tasks.py` (Celery jobs) ·
`provider.py` (key-gated external seam). Contract + Definition of Done:
`backend/app/modules/README.md`. Older Parts 1–7 features still live in the layer-based
`app/routers/*` + `app/services/*` + `app/db/*_repo.py` and are migrating into modules.

## Workers (`backend/workers/`)

`celery_app.py` (broker/result on Redis; `task_acks_late=True`,
`worker_prefetch_multiplier=1`; broker `visibility_timeout ≥` the longest
`task_time_limit` so a long job is never redelivered mid-run and double-charged).
Worker cores **never re-raise** (a redelivery would double-spend) and **never leave a job
stuck** — they drive the legal DB transition and mark `failed` on error. The external
**audit engine** is a separate product invoked as a subprocess with its own interpreter
(never imported), the adapter owning the hard timeout.

## Auth + RBAC

The API mints and verifies its **own EdDSA (Ed25519) tokens** (`POST /api/v1/auth/login`,
argon2id verify) under a hard `["EdDSA"]` allow-list — no JWKS, no external IdP, no public
signup. `provision_user(...)` writes `auth.users` + `public.users` in one privileged
transaction. A **17-feature × 6-role matrix (+ a 7th `client` role)** lives as versioned
reference data in `app/rbac/matrix.py` (mirrored from `frontend/lib/data.ts`);
`require_perm`/`require_role`/`require_feature`/`require_owner` enforce with no DB
round-trip. **Owner is all-on and locked.** A portal **client** holds no staff permission
and is 403'd off the staff namespace.

## State lives at the DB, not the router

Content and Tasks lifecycles are enforced by **BEFORE-UPDATE triggers**, not FastAPI, so a
leaked credential hitting Postgres directly still can't make an illegal transition (the
worker on `service_role` is bound by the trigger too). The router drives only the *legal*
transition and lets the trigger enforce the rest. See `modules.md` (Content, Tasks).
