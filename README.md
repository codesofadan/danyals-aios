# Danyal AIOS Platform

Cloud SEO operations platform for Danyal's agency: a Next.js dashboard over a FastAPI
backend, running in production at `app.qanry.com`. This repo hosts both the **running
v1** and the **v2 rebuild blueprint** — all new work follows the blueprint.

**Start here: [`docs/aios-v2/README.md`](docs/aios-v2/README.md).** When any other
document in this repo disagrees with that pack, the pack wins.

## Repository map

| Folder | What lives here |
|---|---|
| `frontend/` | The dashboard (Next.js 15, App Router): audit, content, off-page, clients, reports, policy radar, cost, tiers, Command Center, Settings. |
| `backend/` | The API service (FastAPI) + Celery workers + provider integrations. |
| `backend/danyals-audit-system/` | The SEO audit engine — a standalone product with its own interpreter and `.env`, invoked by the worker as a subprocess (never imported). The caller owns the timeout and failure marking; the engine never times itself out. |
| `db/` | Ordered SQL migrations (self-hosted PostgreSQL 16); FORCE row-level security on every tenant table. |
| `extension/` | The Chrome MV3 operator extension (citations + web2 placement assist). |
| `wordpress-plugin/` | The AIOS publisher companion plugin (Elementor meta + CSS cache handling). |
| `infra/` | Deployment and ops: `deploy/install.sh`, systemd units, Caddy/nginx, alerts. |
| `scripts/`, `tools/` | Local dev helpers; `tools/redis/` is the vendored local Redis (gitignored). |
| `docs/` | `aios-v2/` (the governing blueprint) · `scope/` (its discovery questionnaire) · `audit/fixtures/` (recorded runs the tests pin against). |

Everything the repo used to carry (v1 planning docs, forensic audits, research records,
client PDF pack) is preserved on branch **`v1-archive`** (tag `v1-final`).

## Running locally

See [`RUN-LOCALLY.md`](RUN-LOCALLY.md). Short version: local PostgreSQL 16 + the
vendored Redis, then `Start-Backend.bat`, `Start-Worker.bat`, `Start-Dashboard.bat`.

## Stack

- **Frontend:** Next.js 15.5, React 19, TypeScript
- **Backend:** FastAPI (Python 3.11+), Celery + Redis for jobs
- **Data:** self-hosted PostgreSQL 16 with RLS as the tenant boundary
- **AI:** Claude (Anthropic)
- **Key external APIs:** DataForSEO, Serper.dev, Google Cloud (PageSpeed / Places)

There is no hosted CI (removed 2026-09-17); the local gates in `backend/CLAUDE.md`
(`ruff check .` && `mypy app workers` && `pytest -m unit`) are the gates.
