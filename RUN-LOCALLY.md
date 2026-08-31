# Running AIOS locally

Four double-click batch files at the repo root:

| File | What it does |
|---|---|
| **Start-Dashboard.bat** | Runs the dashboard UI on `http://localhost:3000` and opens your browser. |
| **Start-Backend.bat** | Runs the local backend (the engine) on `http://localhost:8000`. |
| **Start-Worker.bat** | Runs the job worker that actually executes background work. |
| **Finish-Citations.bat** | Opens each ready citation in a real browser (logged-in + pre-filled) for the final click. |

## The worker is not optional

The backend **accepts** a job and returns immediately; the **worker** is what runs it.
Audits, content generation, citation audits, WordPress design replication, web2
publishing and report generation all go through it. With no worker running, those
jobs are recorded and stay **Queued** indefinitely — the dashboard is telling you
the truth, there is simply nothing there to pick them up.

So for anything beyond browsing existing data, run **Start-Worker.bat** alongside
the backend.

## Two ways to run the dashboard

**A) Full local (UI + backend on your machine, Claude Code drives it)**
1. Make sure local **PostgreSQL** (`:5432`) and **Redis** (`:6379`) are running (see `backend/.env`).
2. Double-click **Start-Backend.bat** (leave it running).
3. Double-click **Start-Worker.bat** (leave it running too — see above).
4. Double-click **Start-Dashboard.bat** — it opens `http://localhost:3000`, sending its API requests to your local backend.

**B) Local UI, cloud backend (no local database needed)**
1. Open **Start-Dashboard.bat** and set `BACKEND_ORIGIN=https://app.qanry.com`.
2. Double-click it — the local dashboard talks to the live cloud backend. (Skip Start-Backend.bat.)

## Finishing citations locally
Double-click **Finish-Citations.bat**, type a directory name (or `ALL`). A real browser opens, logged in and pre-filled — do the one human step (category / captcha), click **Publish**, then close the window to move to the next.

Prereqs are already installed: `frontend/node_modules` and the `backend/.venv` Python environment.
