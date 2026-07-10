# infra

Deployment and operations for the AIOS platform.

## Approach

The backend runs **natively on a single VPS** (Hetzner) via **systemd** — no
Docker. Two services (`aios-api`, `aios-worker`) sit in front of a native Redis,
with **Caddy** as the reverse proxy providing automatic TLS. See
[`deploy/README-deploy.md`](deploy/README-deploy.md) for the full runbook.

- **systemd** units for the API (uvicorn) and the Celery worker
- **Redis** installed natively (broker db 1, results db 2, app cache db 0)
- **Caddy** reverse proxy with automatic TLS
- **CI** (GitHub Actions) at `.github/workflows/backend-ci.yml`: ruff + mypy +
  tests, plus a Redis-service integration job
- Secrets kept out of the repo; each environment supplies its own `.env`

## Layout

```
infra/
├── systemd/        # aios-api.service, aios-worker.service
└── deploy/         # install.sh (provision) + README-deploy.md (runbook)
```

Backend CI lives at the repo root under `.github/workflows/` (GitHub only
discovers workflows there).
