# Running AIOS locally

**Windows:** five double-click batch files at the repo root (table below).
**macOS / Linux:** two scripts do the same job —

```bash
scripts/dev-doctor.sh   # health check: stray servers, starved worker queues, wiring
scripts/dev-up.sh       # starts backend :8000 + a full-coverage worker + frontend :3000
```

The doctor exists because this tree once ran TWO backends (:8000 stale, :8099 live)
and three workers that all consumed the same queue while two queues starved — and
nothing anywhere said so. Run it whenever things feel "quiet". It only reports;
kill commands are printed, never executed (concurrent sessions share this checkout).

| File | What it does |
|---|---|
| **Start-Dashboard.bat** | Runs the dashboard UI on `http://localhost:3000` and opens your browser. |
| **Start-Backend.bat** | Runs the local backend (the engine) on `http://localhost:8000`. |
| **Start-Worker.bat** | Runs the job worker that actually executes background work. |
| **Finish-Citations.bat** | ⚠️ Superseded — use the **Citation queue** page (`/admin/citations/queue`) + the Citation Assistant extension instead. The queue tracks who did what and verifies live URLs; this script predates it. |
| **Build-Extension.bat** | Builds the Citation Assistant browser extension and prints the folder to load into Chrome. |

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
   Redis is **not** a Windows service here - it is a portable build vendored at
   `tools/redis/` (gitignored). Start it with:
   ```
   tools/redis/redis-server.exe tools/redis/redis-local.conf
   ```
   That conf binds **`127.0.0.1` AND `::1`** on purpose. Bind IPv4 only and the app's
   *async* Redis client resolves `localhost` -> `::1` first and times out under the
   Windows Proactor loop, so `/health/ready` reports `redis: connection failed` while
   `redis-cli ping` happily answers PONG. Celery uses the same `localhost` URLs.
2. Double-click **Start-Backend.bat** (leave it running).
3. Double-click **Start-Worker.bat** (leave it running too — see above).
4. Double-click **Start-Dashboard.bat** — it opens `http://localhost:3000`, sending its API requests to your local backend.

**B) Local UI, cloud backend (no local database needed)**
1. Open **Start-Dashboard.bat** and set `BACKEND_ORIGIN=https://app.qanry.com`.
2. Double-click it — the local dashboard talks to the live cloud backend. (Skip Start-Backend.bat.)

## Finishing citations locally
Double-click **Finish-Citations.bat**, type a directory name (or `ALL`). A real browser opens, logged in and pre-filled — do the one human step (category / captcha), click **Publish**, then close the window to move to the next.

## Rebuilding the local database

The local DB drifts behind `db/migrations` (there is no ledger until you build one).
`scripts/local-db-rebuild.sh` is the native-Windows equivalent of the Docker stack's
`migrate` service: safety dump -> drop/recreate -> apply every migration in order
through `deploy.schema_migrations` -> set the authenticated/service_role passwords
from the DSNs -> RLS coverage gate -> seed the owner.

```
PGPASSWORD="$LOCAL_PG_SUPERUSER_PASSWORD" scripts/local-db-rebuild.sh
```

It needs the **`postgres` superuser** (kept as `LOCAL_PG_SUPERUSER_PASSWORD` in
`backend/.env`), not `service_role`: migration 0000 has an ownership invariant
requiring a BYPASSRLS superuser owner, or the SECURITY DEFINER helpers recurse
through `users_select`. Stop the API/worker/beat first so nothing holds a connection.

Prereqs are already installed: `frontend/node_modules`, the `backend/.venv` Python
environment, and `danyals-audit-system/.venv` (the audit engine's own isolated venv,
mirroring `/opt/audit-venv` in the prod image).
