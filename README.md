# Danyal AIOS Platform

Cloud SEO automation platform for Danyal's agency: a Next.js dashboard over a
(planned) FastAPI backend, with the SEO audit engine running as a separate
product. Built by Xegents AI.

## Repository map

| Folder | What lives here | State |
|---|---|---|
| `frontend/` | The dashboard app (Next.js 14, App Router): modules for audit, content, off-page, clients, reports, policy radar, cost, tiers, and more, plus a Command Center and Settings. | Runnable |
| `backend/` | API service (FastAPI) that the frontend calls and that orchestrates the modules and jobs. | Scaffold |
| `db/` | Database schema and migrations (Postgres / Supabase) plus the Google Sheets operational store. | Scaffold |
| `infra/` | Deployment and ops: Docker, Caddy, CI. | Scaffold |
| `context/` | Engineering context for the team and AI: architecture, data flow, API research, feature and workflow specs. Read these first. | Docs |
| `design/` | Document design system (Bricolage house styles) and the build scripts that render the PDFs in `docs/deliverables`. | Tooling |
| `docs/` | `deliverables/` (client-facing PDF pack + build timeline) and `meeting-notes/`. | Docs |

> The **audit engine** (`SEO-AUDIT-OS`) is a standalone Claude Code product and
> lives OUTSIDE this repo, at `../danyals-audit-system`. It has its own API keys
> and setup (`docs/API_KEYS.md` inside that folder).

## Getting started (frontend)

```
cd frontend
npm install
npm run dev        # serves http://localhost:3000
```

Requires Node 18.17+ (tested on Node 24).

## Stack

- **Frontend:** Next.js 14.2, React 18, TypeScript, three.js, anime.js
- **Backend (planned):** FastAPI (Python 3.11+), Celery + Redis for jobs
- **Data (planned):** Postgres / Supabase (identity, secrets, KB), Google Sheets (run store)
- **AI:** Claude (Anthropic)
- **Key external APIs:** Serper.dev, Google Cloud (PageSpeed / Places), and the audit engine's stack

## Status

Pre-build. The frontend dashboard is scaffolded and runnable; `backend`, `db`,
and `infra` are placeholders awaiting the build. See each folder's README and
the `context/` docs for the full plan.
