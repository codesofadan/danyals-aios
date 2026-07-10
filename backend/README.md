# AIOS backend

FastAPI API + Celery workers for the AIOS SEO-automation platform (Xegents AI).
This is the **Part 1 foundation**: a runnable, tested skeleton (config, logging,
request-id + error envelope, liveness/readiness, Supabase + Redis seams, a Celery
worker, dev Docker, CI). Business logic (auth, DB tables, the module endpoints)
lands in later parts.

## Responsibility

- REST / JSON API consumed by `../frontend`
- Orchestrates the SEO modules (Audit, Content, Off-page, Portal, Policy Radar)
  via a Celery + Redis job queue
- Talks to the audit engine, Claude, Serper, Google, and the Google Sheets store
- Auth, a per-client encrypted key vault, and tier / role enforcement
- Per-client API budget caps and a daily spend-stop

## Layout

```
backend/
├── app/
│   ├── main.py            # create_app() factory + module-level `app`; lifespan owns shared clients
│   ├── config.py          # Settings (pydantic-settings), get_settings(), validate_settings()
│   ├── logging_setup.py   # structlog: console in dev, JSON in prod, request-id aware
│   ├── core/
│   │   ├── deps.py        # FastAPI deps: settings, shared httpx client, shared redis client
│   │   ├── middleware.py  # RequestIDMiddleware (X-Request-ID + structlog contextvars)
│   │   ├── errors.py      # global error envelope {"error": {type, message, request_id}}
│   │   ├── observability.py  # Sentry (DSN-gated)
│   │   ├── security.py    # SSRF guard (ported from the audit engine)
│   │   └── redis.py       # shared async redis client + readiness ping
│   ├── db/supabase.py     # service-role + per-user (anon+JWT) client seams + readiness ping
│   ├── routers/           # one router per module; health at root, api_v1 under /api/v1
│   └── schemas/           # pydantic response models
├── workers/               # Celery app + tasks (workers/celery_app.py, workers/tasks/)
├── integrations/          # external API clients (added later)
└── tests/                 # unit (no external services) + integration (need Redis/Supabase)
```

## Run locally

Everything runs through the local venv at `backend/.venv` (Windows + Git Bash).
Invoke tools as `./.venv/Scripts/python -m <tool>` (do not use bare `python`).

```bash
# one-time
cp .env.example .env                                    # required for /health/ready + Docker
./.venv/Scripts/python -m pip install -e ".[dev]"

# gate before committing (all must be green)
./.venv/Scripts/python -m ruff check .
./.venv/Scripts/python -m mypy app workers
./.venv/Scripts/python -m pytest -m unit -q             # unit only (no Redis/Supabase)
./.venv/Scripts/python -m pytest -q                     # everything (integration needs Redis)

# run the API (http://localhost:8000 ; docs at /docs in dev)
./.venv/Scripts/python -m uvicorn app.main:app --reload

# run a worker (needs Redis up)
./.venv/Scripts/python -m celery -A workers.celery_app worker -l info
```

Liveness: `GET /health` (touches nothing). Readiness: `GET /health/ready` (pings
Supabase + Redis concurrently within `READINESS_TIMEOUT_SECONDS`; 200 when both
reachable, 503 naming the down dependency otherwise).

## Run via Docker (api + worker + redis)

```bash
cp .env.example .env                                    # one-time (from repo root: backend/.env)
docker compose -f infra/docker/docker-compose.dev.yml up --build
```

Brings up `redis`, `api` (port 8000, `--reload`, non-root), and `worker`. The
compose file overrides the Redis URLs to the `redis` service for both `api` and
`worker`, so they never point at localhost.

## Config

All settings come from the environment (12-factor); see `.env.example` for every
key. Secrets are `SecretStr` and never logged. In **prod** a missing required
secret fails fast at boot; in **dev** it warns and the dependent feature reports
`not_configured`. Redis uses separate logical DBs (app cache `/0`, Celery broker
`/1`, results `/2`) so a cache flush can never wipe queued jobs.
