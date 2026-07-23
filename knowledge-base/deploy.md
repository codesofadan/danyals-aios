# Deploy & local dev

Grounded in `backend/CLAUDE.md`, `infra/deploy/README-deploy.md`, `infra/systemd/*`, and
`.github/workflows/backend-ci.yml`.

## Production — native systemd on one VPS (the authoritative path)

Production is **native (no Docker, no managed DB)**: a single VPS runs three systemd units
in front of native PostgreSQL 16 + native Redis, behind Caddy (auto-TLS).

| Unit | Process | File |
|---|---|---|
| `aios-api` | uvicorn (`app.main:app`) | `infra/systemd/aios-api.service` |
| `aios-worker` | celery worker | `infra/systemd/aios-worker.service` |
| `aios-beat` | celery beat (scheduler / Policy Radar + context dispatch) | `infra/systemd/aios-beat.service` |

- **All config in one root-owned file** `/etc/aios/aios.env` (`EnvironmentFile`); template
  at `infra/deploy/aios.env.example`.
- **Provision once:** `sudo bash infra/deploy/install.sh` — installs PG16 + Redis, applies
  `db/migrations/*` in order, runs the FORCE-RLS gate, seeds the owner, starts the 3 units.
- **TLS / reverse proxy:** `infra/deploy/Caddyfile`.
- **Recommended VPS:** Ubuntu 22.04+, 4 vCPU / 8–16 GB RAM / 100–160 GB NVMe.
- Full runbook: `infra/deploy/README-deploy.md`.

> A root `docker-compose.yml` and `infra/docker/*` also exist (Portainer stack + a
> migrate entrypoint) for containerized/dev orchestration, but the **production standard is
> the native systemd path above** per `backend/CLAUDE.md`. Treat compose as optional/dev.

## Redis DB separation (invariant #7)

App cache/health uses `REDIS_URL` (db 0); Celery uses `CELERY_BROKER_URL` (db 1) +
`CELERY_RESULT_BACKEND` (db 2), so a cache `FLUSHDB` can never wipe queued jobs. The
broker `visibility_timeout` MUST be ≥ the longest `task_time_limit` (invariant #8) or a
long job is redelivered and runs twice (double spend).

## The external audit engine

The audit module shells out to a **separate product** at `../danyals-audit-system`, run
with **its own interpreter + its own `.env`** (dependency isolation). It is never imported.
Until that engine's env is provisioned, Paid audit execution + the live audit test skip,
and the module runs mocked.

## Local dev gate (before any backend change)

The backend uses a local venv at `backend/.venv` (Windows + Git Bash). Always invoke tools
as `./.venv/Scripts/python -m <tool>` — never bare `python`.

```bash
cd backend
./.venv/Scripts/python -m ruff check .
./.venv/Scripts/python -m mypy app workers
./.venv/Scripts/python -m pytest -m unit -q          # unit subset — no Redis/Postgres
./.venv/Scripts/python -m uvicorn app.main:app --reload
```

The full local gate is **`ruff check .` && `mypy app workers` && `pytest -m unit`** (all
green). Integration tests (`-m integration`) need a real Redis + local Postgres and
auto-skip when their env vars are unset.

## CI

`.github/workflows/backend-ci.yml` runs ruff + mypy + unit tests (matrix 3.11/3.12), a
`db-rls` job (ephemeral Postgres → apply migrations → FORCE-RLS gate), an `integration`
job (ephemeral Postgres + minted EdDSA keypair → RLS-matrix + contract suites), and a
`security` job (pip-audit + gitleaks). Alerts: `infra/alerts/backend-alerts.yml`.

## Health

`GET /health` (liveness — touches nothing external) · `GET /health/ready` (readiness —
bounded, concurrent pings of Postgres + Redis; `not_configured` does not fail readiness in
dev) · `/metrics` (Prometheus, added inside RequestID).
