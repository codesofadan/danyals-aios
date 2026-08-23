# Danyal AIOS Platform

Cloud SEO automation platform for Danyal's agency: a Next.js dashboard over a
FastAPI backend, with the SEO audit engine vendored alongside as a separate
product with its own dependency set.

## Repository map

| Folder | What lives here | State |
|---|---|---|
| `frontend/` | The dashboard app (Next.js 15, App Router): modules for audit, content, off-page, clients, reports, policy radar, cost, tiers, and more, plus a Command Center and Settings. | Runnable |
| `backend/` | API service (FastAPI) that the frontend calls and that orchestrates the modules and jobs. ~82k lines across `app/`, `integrations/` and `workers/`; 202 test files. | Built |
| `db/` | Database schema and 81 ordered SQL migrations (self-hosted PostgreSQL 16), with row-level security enforced on every tenant table. | Built |
| `infra/` | Deployment and ops: systemd units, Caddy, CI. | Built |
| `context/` | Engineering context for the team and AI: architecture, data flow, API research, feature and workflow specs. Read these first. | Docs |
| `design/` | Document design system (Bricolage house styles) and the build scripts that render the PDFs in `docs/deliverables`. | Tooling |
| `docs/` | `deliverables/` (client-facing PDF pack + build timeline) and `meeting-notes/`. | Docs |

> The **audit engine** is a standalone product with its own interpreter and its own
> `.env`, at **`danyals-audit-system/`** inside this repo (an earlier version of this
> note placed it at `../danyals-audit-system`, outside the tree — it is not there).
> The backend never imports it; it is invoked as a subprocess. Note the seam: the
> engine mints its own run id, does not catch its own top-level exceptions and never
> times itself out, so the caller owns the timeout and the failure marking.

## Getting started (frontend)

```
cd frontend
npm install
npm run dev        # serves http://localhost:3000
```

Requires Node 18.17+ (tested on Node 24).

## Stack

- **Frontend:** Next.js 15.5, React 19, TypeScript, anime.js
  (an earlier version of this line said Next 14.2 / React 18 / three.js; the first two
  were a major version behind and `three` is not a dependency at all)
- **Backend:** FastAPI (Python 3.11+), Celery + Redis for jobs
- **Data:** self-hosted PostgreSQL 16 (identity, secrets, knowledge base) with RLS as the
  tenant boundary; Redis for the queue, cache and write-buffer
- **AI:** Claude (Anthropic)
- **Key external APIs:** Serper.dev, Google Cloud (PageSpeed / Places), and the audit engine's stack

## Status

**In recovery, ahead of a v1 delivery.** This section previously read "pre-build …
placeholders awaiting the build", which has not been true since July 2026 and
understated the system by roughly 100,000 lines.

What is actually here: a running platform deployed at `app.qanry.com`, with the five
v1 modules (Portal · Audit · Content + WordPress · Citations · Web 2.0) implemented to
varying depth, plus Policy Radar. ~82k lines of backend Python, ~30k of TypeScript
across 27 app routes, 81 migrations, a separate 20k-line audit engine, and a unit
suite of ~4,900 tests.

What is **not** true yet, and is being fixed in order:

| | |
|---|---|
| **Scheduling** | `celery_app.conf.beat_schedule` is empty — nothing runs on its own. Restoring it is gated on the job contract (retries, idempotency, dead-letter) landing first, so a restored schedule cannot double-spend. |
| **Citations** | The submission approach is being rebuilt around data aggregators plus a human work queue, rather than hand-maintained DOM specs. |
| **Content → WordPress** | Design capture is real; translating a captured design into a live page-builder block tree is not built yet. |
| **Reported success** | A publish with no WordPress credentials still records `status="done"`; this is being given its own terminal state. |

The honest current state per capability is tracked in `docs/recovery/` (specification,
requirements traceability, decisions) and `docs/audit/` (forensic audit, salvageability
matrix). **Read `docs/recovery/DECISIONS_LOG.md` first** — it records the scope and
architecture decisions that supersede older documents in this repo.

Recently closed: synthetic (`Fake*`) providers can no longer reach a production path.
A keyless deploy used to substitute hash-derived "research", rankings and keyword
metrics and persist or publish them as if measured; every writing caller now degrades
instead, guarded by `backend/tests/test_no_synthetic_providers_in_production.py`.
