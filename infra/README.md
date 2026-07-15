# infra

Deployment and operations for the AIOS platform.

## Approach

The backend runs **natively on a single VPS** via **systemd - no Docker, no
Supabase**. Three services (`aios-api`, `aios-worker`, `aios-beat`) sit in front of
a native **PostgreSQL 16** + native **Redis**, with **Caddy** as the reverse proxy
providing automatic TLS. Everything lives on the box in the agency's own accounts:
no lock-in. See [`deploy/README-deploy.md`](deploy/README-deploy.md) for the full
runbook.

- **PostgreSQL 16** installed natively (loopback-only); RLS is the tenant boundary
- **Redis** installed natively (app cache db 0, broker db 1, results db 2)
- **systemd** units for the API (uvicorn), the Celery worker, and Celery beat
- **Caddy** reverse proxy with automatic TLS
- **CI** (GitHub Actions) at `.github/workflows/backend-ci.yml`: ruff + mypy +
  tests + the RLS gate, plus a Redis-service integration job
- Secrets kept out of the repo; each environment supplies its own
  `/etc/aios/aios.env` (see `deploy/aios.env.example`)

## Layout

```
infra/
├── deploy/            # install.sh + aios.env.example + Caddyfile + README-deploy.md
├── systemd/           # aios-api.service, aios-worker.service, aios-beat.service
└── alerts/            # backend-alerts.yml (Prometheus rules)
```

Backend CI lives at the repo root under `.github/workflows/` (GitHub only
discovers workflows there).
