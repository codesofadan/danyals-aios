# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

The **AIOS** backend: a FastAPI API + Celery workers for a cloud SEO-automation platform (Xegents AI). It lives in a monorepo (`danyals-aios/`) alongside a Next.js `frontend/` and a nested, standalone SEO audit engine at `../danyals-audit-system/` (which has its own `CLAUDE.md`). This service is being built **foundation-first** ("Part 1"): a runnable, tested skeleton before any business logic (auth, DB tables, the module endpoints) lands.

Responsibilities (from `README.md`, mostly still to build): REST/JSON API for `../frontend`; orchestrates the SEO modules (Audit, Content, Off-page, Portal, Policy Radar) via a Celery+Redis job queue; talks to the audit engine, Claude, Serper, Google, and Google Sheets; auth + a per-client encrypted key vault + tier/role enforcement; per-client API budget caps + a daily spend-stop.

## Commands

Everything runs through the local venv at `backend/.venv` (Windows + Git Bash). Always invoke tools as `./.venv/Scripts/python -m <tool>` — do not use bare `python`.

```bash
./.venv/Scripts/python -m pip install -e ".[dev]"          # install (editable) + dev extras
./.venv/Scripts/python -m ruff check .                      # lint
./.venv/Scripts/python -m mypy app workers                  # type-check (strict)
./.venv/Scripts/python -m pytest -m unit -q                 # unit tests (NO external services)
./.venv/Scripts/python -m pytest -m integration -q          # integration tests (need Redis/Supabase)
./.venv/Scripts/python -m pytest tests/test_config.py::test_secrets_are_masked   # a single test
./.venv/Scripts/python -m uvicorn app.main:app --reload     # run the API (http://localhost:8000)
./.venv/Scripts/python -m celery -A workers.celery_app worker -l info   # run a worker (needs Redis up)
cp .env.example .env                                         # one-time: required for /health/ready
```

The full local gate before committing a change is: **`ruff check .` && `mypy app workers` && `pytest -m unit`** (all green; the unit subset needs no Redis/Supabase). CI at `../.github/workflows/backend-ci.yml` runs ruff + mypy + unit tests on 3.11/3.12 plus a Redis-service integration job.

**Deployment is native (no Docker):** production runs on a single VPS via systemd — `aios-api` (uvicorn) + `aios-worker` (celery) in front of a native Redis, behind Caddy (auto-TLS). Provision with `sudo bash ../infra/deploy/install.sh`; see `../infra/deploy/README-deploy.md`.

## Architecture (big picture)

- **`app/`** — the FastAPI app. `app/main.py` exposes a `create_app()` factory and a module-level `app`. A **lifespan** owns shared clients on `app.state`: a shared `httpx.AsyncClient` and the `redis.asyncio` client (constructed lazily at startup, closed at shutdown behind a `getattr` guard). Middleware is added in the order TrustedHost → CORS → RequestID, which (Starlette adds LIFO) makes **RequestID outermost**. Business routes mount under **`/api/v1`** via the `api_v1` aggregator in `app/routers/__init__.py` — one router per module; health lives at the root (`/health`, `/health/ready`).
- **`workers/`** — Celery app (`workers/celery_app.py`) with broker + result backend on Redis. The long-running Audit/Content/Off-page/Research jobs live here in later parts.
- **`integrations/`** — external API clients (Serper, Google, Google Sheets, Claude), added in later parts.
- **`app/config.py`** — `Settings` (pydantic-settings, reads `.env`), `@lru_cache get_settings()`, and `validate_settings()`. Secrets are `SecretStr`. **`app/logging_setup.py`** — structlog (console in dev, JSON in prod), request-id propagated via `structlog.contextvars`.
- **`app/core/`** — cross-cutting concerns: `security.py` (SSRF guard), `middleware.py` (request-id), `errors.py` (error envelope), `observability.py` (Sentry), `deps.py` (FastAPI dependencies), `redis.py` (async Redis).
- **`app/db/supabase.py`** — the two Supabase client seams (see invariants) + the async readiness ping.

**The load-bearing data decision:** Supabase (managed Postgres + Auth + Vault + Storage) holds identity, secrets, and the knowledge base; **Google Sheets** holds the client-facing operational records; **Redis** is the job queue + cache + a Sheets write-buffer. See `../context/ARCHITECTURE-AND-PLAN.md` and the `../docs/deliverables/*.pdf` for the full product plan. The frontend's `../frontend/lib/*.ts` types are the intended **API response shapes** — build endpoints to match them so the dashboard works unchanged.

## Invariants (the "why" — read before changing these)

1. **Liveness ≠ readiness.** `GET /health` (liveness) touches no external service. `GET /health/ready` (readiness) checks Supabase + Redis with **bounded, concurrent** timeouts (`asyncio.gather` + per-check `wait_for`, budget = `settings.readiness_timeout_seconds`).
2. **Never block the event loop.** Async routes use `redis.asyncio` and async `httpx`. The SSRF guard's `socket.getaddrinfo` **blocks** — callers on async routes must offload it (`asyncio.to_thread`).
3. **Secret / RLS hygiene.** The Supabase `service_role` key **bypasses Row-Level Security** → server-only, never returned to a client, never logged (`get_admin_client`, `@lru_cache`). RLS-respecting calls use a **per-request anon-key client carrying the user JWT** (`client_for_user`) — never cached, never the service_role key.
4. **12-factor config.** Env-only; `@lru_cache` singleton; `validate_settings` **fails fast in prod** on a missing required secret and **warns in dev** (checks falsiness, since a blank env var is `""`/`SecretStr("")`, not `None`). `APP_ENV` drives docs, CORS, and log format; docs/openapi are disabled in prod.
5. **Observability.** Every request gets an `X-Request-ID` stored on **`request.state`** (so it survives the 500 path, after contextvars are cleared); JSON logs in prod; a global error envelope `{"error": {"type", "message", "request_id"}}` (generic 500 message — never leak `str(exc)`); Sentry initializes only if `SENTRY_DSN` is set. Secrets never appear in a log line.
6. **Readiness ping contract.** Every dependency ping is `async def ping(...) -> DependencyStatus` — **non-raising** (catches its own errors), only true success is `"ok"`, and `detail` is a short **sanitized** reason (never a connection URL, secret, or raw exception). `not_configured` does not fail readiness in dev.
7. **Redis DB separation.** App cache/health uses `REDIS_URL` (db 0); Celery uses `CELERY_BROKER_URL` (db 1) + `CELERY_RESULT_BACKEND` (db 2), so a cache `FLUSHDB` can never wipe queued jobs.
8. **Celery long-job safety.** `task_acks_late=True` + `worker_prefetch_multiplier=1`; the Redis broker's `visibility_timeout` **must be ≥ the longest `task_time_limit`**, or a long job is redelivered and **runs twice** (double API spend).
9. **Auth + RBAC (Part 2).** Access tokens are verified locally against the Supabase **JWKS** (ES256/RS256) — no shared secret, no per-request round-trip (`app/core/auth.py`, keys cached on `app.state`). A valid token → `CurrentUser` loaded via the **RLS** client; there is **no public signup** (a super-admin provisions users). The **17-feature matrix + 6 roles + 4 templates** live as versioned reference data in `app/rbac/matrix.py` (mirrored from `frontend/lib/data.ts`) — enforcement (`require_perm` / `require_role` / `require_owner` / `require_feature`) needs no DB round-trip; **Owner is all-on and locked**.
10. **Every tenant table has `ENABLE`+`FORCE RLS`** with explicit policies; a CI gate (`app/db/rls_check.py`, the `db-rls` job) fails on any unprotected `public` table. RLS helper functions are `SECURITY DEFINER` with an empty `search_path` to avoid policy recursion. **Vault** raw secrets live only in Supabase Vault (reached via service_role-only wrappers); a list is masked, reveal is owner-only, nothing is logged. The **activity log** is append-only (no write policy; only the server appends). The **cost-gate** (`app/services/cost_gate.py`) runs `dial → cache → client cap → daily spend-stop → call+log` before any paid call; a cached call costs 0.

## Conventions

- Tooling: **ruff** (line-length 110), **mypy strict** (`ignore_missing_imports`), **pytest** (`asyncio_mode=auto`, markers `unit`/`integration`). Mirror the sibling audit engine's Python style.
- `from __future__ import annotations` at the top of every module.
- **Reuse before rewriting.** `app/core/security.py` is ported verbatim from `../danyals-audit-system/audit_engine/security.py`; the async HTTP-client base in that repo's `integrations/base.py` (tenacity retry + circuit breaker + never-log-secrets) is the template for future API clients. The audit engine is later wrapped as a Celery job — invoke its CLI, don't rebuild it; note it **mints its own `run_uuid`** and **doesn't catch its own top-level exceptions**, so the worker must own timeouts and mark failures itself.

## Context discipline (keep the main thread lean)

The main conversation is a coordinator, not a workspace. Push reading, searching, and bulk work off it so its token budget stays low and long tasks don't hit the context limit. Prefer these over `/compact` (which is lossy) and never let the main thread fill with raw file dumps.

1. **Delegate reading and searching to subagents.** When answering means sweeping many files or exploring a subsystem, spawn a subagent (Task/Agent, or the `Explore`/`general-purpose` types). It reads in *its own* context and returns only the conclusion — the main thread grows by a paragraph, not 50k tokens. This is the single biggest lever.
2. **Externalize state to files, reference by path.** Write plans, findings, and intermediate results to the scratchpad dir or a repo doc, then point back at the path instead of pasting the content inline. Durable facts go to memory (`MEMORY.md` + memory files), which load as a compact index, not full bodies.
3. **Read narrowly.** Grep/Glob to locate first, then Read only the needed line range (`offset`/`limit`). Don't read whole files when a slice answers the question, and don't re-read a file you just edited — the harness already tracks its state.
4. **Session hygiene.** One session per distinct task; `/clear` when a task is done (save anything important to files/memory first); start fresh rather than growing one giant thread. Use `/compact` with a focus instruction only as a last resort.
5. **Keep this file and other always-loaded docs lean.** CLAUDE.md is re-read every turn — every line here is fixed overhead on every request. Add durable operating rules; move transient notes to the scratchpad or memory.

## Build state

Built in ordered "chunks" on branch **`feat/backend-foundation`**, one commit per chunk (`feat(backend): <desc> (Chunk N)`). **Part 1 (the runnable foundation) is complete — Chunks 1–10 committed and green** (ruff + mypy strict clean; 51 unit tests pass with no external services):

- 1–3: packaging, config + structlog logging, app factory + middleware + liveness `/health`.
- 4: SSRF guard (`app/core/security.py`) ported verbatim from the audit engine, with an async caller-contract docstring.
- 5: Supabase seams (`app/db/supabase.py`) — `get_admin_client` (service-role, cached, server-only) + `client_for_user` (anon+JWT, per-request, never cached) + async readiness ping.
- 6: shared `redis.asyncio` client (`app/core/redis.py`) + `RedisDep` + lifespan wiring + readiness ping.
- 7: concurrent, bounded `/health/ready` (`asyncio.gather`, 503 via `response.status_code` not `HTTPException`, `not_configured` doesn't fail readiness).
- 8: Celery skeleton (`workers/celery_app.py` + `workers/tasks/ping.py`), tasks via `include=[...]`, `visibility_timeout ≥ task_time_limit`.
- 9: **native systemd deploy (Docker was built then removed)** — `infra/systemd/*.service` + `infra/deploy/install.sh` + `README-deploy.md`; Caddy for TLS.
- 10: CI at `../.github/workflows/backend-ci.yml` (ruff + mypy + tests, matrix 3.11/3.12, Redis integration job) + README.

**Part 2 (the Shared Base) is complete — P2-1…P2-10 committed and green** (ruff + mypy strict clean; 136 unit tests, integration auto-skip). DB schema is ordered SQL in `../db/migrations/` (snapshot `../db/schema.sql`); apply with `psql`, then verify RLS with `python -m app.db.rls_check` (needs `DATABASE_URL`). CI's `db-rls` job spins an ephemeral Postgres (with the `../db/ci` Supabase shim), applies the migrations, and runs the gate.

- P2-1: migration tooling + conventions + the RLS coverage gate (`app/db/rls_check.py`).
- P2-2: identity (`users` ↔ `auth.users`) + `user_feature_grants`; the RBAC matrix (`app/rbac/matrix.py`).
- P2-3: auth (`app/core/auth.py` — JWKS verify, `CurrentUser`, `require_*`) + super-admin provisioning + `/api/v1/rbac/*` reference endpoints.
- P2-4: clients + sites CRUD (`app/routers/clients.py`, `app/db/clients_repo.py`) — the portal password is never persisted/revealed.
- P2-5: Key Vault (`app/services/vault.py`, `app/routers/vault.py`) over Supabase Vault — masked list, owner-only reveal.
- P2-6: append-only activity log (`app/services/activity.py`) wired into every mutation; `/api/v1/activity` feed.
- P2-7: cost-gate/money-dial (`app/services/cost_gate.py` + `/api/v1/cost/*`) — budgets, dial, spend-stop, cost log.
- P2-8: service tiers (`app/routers/tiers.py`) — delivery tier (free/semi/fully) kept separate from the subscription tier.
- P2-9: E2E + RLS integration tests (auto-skip). P2-10: harden + docs.

Business routers attach to `api_v1` in `app/routers/__init__.py`; each has a `*_repo.py` (RLS user-JWT reads, swappable for an in-memory fake in tests) and, where privileged, a service using the service_role admin client. Integration tests (`-m integration`) need a real Redis/Supabase/Postgres and auto-skip when their env var is unset. **Part 3** (the module operational tables in Google Sheets, the audit-engine worker wrapper, and the business-module endpoints) follows.
