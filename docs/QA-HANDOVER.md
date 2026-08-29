# QA HANDOVER — AIOS Platform

**Repository:** https://github.com/codesofadan/danyals-aios
**Branch to test:** `main` (the default branch — a plain `git clone` gives you the right code)
**Handed over:** 2026-08-29

Read this file before filing the first bug. Sections 4 and 5 list defects we already
know about. Filing those back costs you time and tells us nothing new.

---

## 1 · What this system is

A cloud SEO automation platform: a Next.js dashboard over a FastAPI backend, with a
separately-vendored SEO audit engine invoked as a subprocess.

| Layer | Where | Scale |
|---|---|---|
| Dashboard | `frontend/` | Next.js 15.5, React 19, TypeScript · **35 routes** |
| API | `backend/app/` | FastAPI (Python 3.12) · **36 routers**, **17 feature modules** |
| Workers | `backend/workers/` | Celery + Redis |
| Database | `db/migrations/` | PostgreSQL 16 · **106 ordered migrations**, RLS on every tenant table |
| Audit engine | `danyals-audit-system/` | Standalone product, own venv and `.env`. The backend never imports it — it shells out |

---

## 2 · Getting it running

Prereqs: Node 18.17+ (tested on 24), Python 3.12, PostgreSQL 16 on `:5432`, Redis on `:6379`.

```bash
git clone https://github.com/codesofadan/danyals-aios.git
cd danyals-aios

# backend
cd backend
cp .env.example .env            # fill in the values you have
uv venv --python 3.12 .venv     # 3.14 does NOT resolve the dependency set
VIRTUAL_ENV=.venv uv pip install -e ".[dev]"
psql "$DATABASE_URL" -f ../db/migrations/*.sql   # in filename order

# frontend
cd ../frontend && npm install && npm run dev     # http://localhost:3000
```

On Windows there are three double-click launchers at the repo root
(`Start-Backend.bat`, `Start-Dashboard.bat`, `Finish-Citations.bat`) — see `RUN-LOCALLY.md`.

**Python 3.14 will not work.** The dependency set does not resolve on it. Use 3.12.

---

## 3 · The test baseline you should reproduce

Measured on this exact commit, on macOS/arm64. If your numbers differ materially,
that is itself worth reporting.

| Suite | Command (from that folder) | Expected |
|---|---|---|
| Audit engine | `./.venv/bin/python -m pytest tests -q` | **859 passed**, 0 failed (~6s) |
| Backend | `./.venv/bin/python -m pytest tests -q -n 8` | **7,177 passed · 0 failed · 148 skipped** (~40 min) |
| Frontend types | `npx tsc --noEmit` | clean, exit 0 |
| Frontend units | `npx vitest run --no-file-parallelism` | **260 passed**, 37 files |
| Frontend build | `npx next build` | succeeds |

The backend suite takes **>3 hours single-process** - `-n 0` is not a realistic way to
run it. Use `-n 8` (pytest-xdist).

**Run the two suites one at a time.** Both are pool-parallel, and on a laptop they
will fight: running them concurrently pushed load average past 28 here and produced
**9 phantom frontend failures** that all passed on a serial re-run. If you see
failures, re-run the suite alone before believing them - and prefer
`--no-file-parallelism` for vitest when you want a number you can trust.

**Run against a clean checkout.** A test failure in a shared or dirty tree may be
true of no commit at all. The four failures measured here
(`test_builder_branding`, `test_citation_gap`, `test_web2_catalog` x2) came entirely
from another session's uncommitted edits; the same tests pass on a `git worktree` of
the same HEAD. `git status` before you file anything.

`npx next build` is a separate gate from `tsc` and catches things `tsc` does not - an
unused import failed the build here while types, units and a live HTTP 200 were all
green. A deployable frontend is not implied by a passing test suite.

---

## 4 · Nothing runs on a timer

Cron was switched off by owner instruction on 2026-08-19:
`celery_app.conf.beat_schedule = {}` in `backend/workers/celery_app.py`. The full
schedule is preserved verbatim in `_BEAT_SCHEDULE_DISABLED` right below it, and every
task stays registered and callable on demand via `.delay()`.

**Consequence for you: every job is event-driven or on-demand.** Do not write test
cases that wait for a scheduled run. Concretely, nothing re-sweeps citation liveness,
Policy Radar produces a brief only when a user asks for one, and no backup or
reconcile happens by itself.

`aios-beat` still starts and stays green under `systemctl status` while firing
nothing, so a quiet beat log is correct here rather than broken. See *Nothing runs on
a timer* in `infra/deploy/README-deploy.md` for the consequences in full and the
two-line re-enable - note that several parked jobs call paid APIs, so switching them
on moves the bill as well as the freshness.

*(An earlier revision of this document listed 9 expected beat-schedule failures. Those
tests were since repaired to assert the PRESERVED schedule instead of the live one -
strictly better, because the wiring is now checked even while cron is parked, so
turning it back on cannot silently skip a job. They pass. There are no expected
failures.)*

---

## 5 · Known-absent and known-broken — check here before filing

Full detail in `docs/implementation/KNOWN_LIMITATIONS.md`. The headlines:

| Area | State |
|---|---|
| **Scheduling** | Nothing runs autonomously (§4 above) |
| **Citations** | Submission is being rebuilt around data aggregators + a human work queue. The old DOM-spec approach is not the target |
| **Content → WordPress** | Built end to end: capture → design system → layout → Elementor tree → oracle validation → push. `POST /replica` queues a job that publishes a **draft** Elementor page onto the client's connected site and returns a preview link; driven from the Design Replicator on `/admin/wordpress`. Needs the AIOS Publisher plugin (xmlrpc / app-password connections come back `blocked`) and `owner_confirmed_source: true` (copyright gate, 400 otherwise). Two real gaps: images are **hot-linked from the source** rather than sideloaded into the client's media library, and only the navbar is wired to the target's widget-capability probe - forms, sliders, galleries, tabs, price tables and post lists still take the free-tier fallback |
| **QA gate on publish** | Advisory **by design** - `PublishBlocked` is defined and caught but raised nowhere, and the approve endpoint never consults the score, so a lead *can* still approve a sub-threshold draft. The human sign-off is the gate. D-4's acknowledgement half is now built: all four approve surfaces show the weighted total and every sub-70 dimension before publishing (three via `ApproveGate`, and `ContentJobDetail` requires typing PUBLISH over a **failed** scorecard), and the acknowledgement is recorded as the activity entry's `meta`. Still missing: R3A-36's durable `qa_acknowledged_by/_at/_override_reason` columns - the activity note is the audit trail until they exist. The threshold itself is **uncalibrated** (P7A-11: the golden set holds 2 cases against the 30-50 asked for), which is why it must not become a hard gate yet |
| **Backups / restore** | Built and working, 47 tests green. `POST /backups/run` takes a real `pg_dump -Fc` snapshot; `POST /backups/{id}/restore` runs `pg_restore --clean --if-exists` and is doubly guarded - owner-only at the router *and* the request body's `confirm` must echo the snapshot id. Ledger in `backup_snapshots` / `backup_config` (migration 0026, RLS forced); UI at **Platform → Integrations → Backups**. Set `BACKUP_ARTIFACT_DIR` (install.sh creates it); the B2 offsite copy is optional and a missing credential does not fail the local snapshot. **The nightly snapshot does not fire** - same reason as everything else, see §4. No restore has been rehearsed on real data yet; do that before go-live |
| **`TaskResponse.due`** | Served as a year-less string (`"Jul 12"`); the frontend infers the year |
| **Flaky under load** | `test_ready.py::test_ready_is_bounded_and_reports_sibling` and `test_context_worker.py::test_full_pipeline_activity_to_summarized_context` pass in isolation and flake under CPU contention. The frontend suite flakes the same way - 9 failures under load, 0 serially. See §3: run one suite at a time, on a clean tree |
| **Free audit** | `--mode free` hard-clears PageSpeed, so the free tier loses Core Web Vitals even though PSI has a free tier |
| **Migration numbering** | `0070_` and `0072_` each name **two** files. Apply migrations in full-filename sort order |

### Features that exist on unmerged branches and are NOT in this build

Do not test for these — they are deliberately excluded from this drop:

- **Evidence primitive** (`recovery/2-3-evidence-primitive`) — evidence contract + immutability
- **Approval record** (`recovery/2-6-approval-record`) — DB-stamped approval actor
- **Three team/content UI components** (`recovery/3-2-audit-module`) — `MemberAccess.tsx`,
  `FeatureLevelGrid.tsx`, `QaApprove.tsx`

The first two collide with shipped migration numbers `0084`/`0085` and need renumbering
before they can merge.

---

## 6 · Test surface

**Admin** (`/admin/…`) — audit · clients · content · cost · leads · milestones · operations ·
policy-radar · reports · settings · tasks · team · vault · web2 · wordpress

**Client portal** (`/client/…`) — audits · milestones · reports · requests

**Team** (`/team/…`) — deliver · queue · review · tools/[slug]

Five v1 modules are implemented to varying depth: **Portal · Audit · Content+WordPress ·
Citations · Web 2.0**, plus **Policy Radar**.

### Two things worth aiming at

1. **Row-level security is the tenant boundary.** Every tenant table has RLS. Connecting
   as a superuser bypasses it unconditionally — CI once did exactly that and eleven
   isolation tests passed vacuously. Verify you are connected as `authenticated`, not
   `postgres`, before you trust any isolation result.
2. **Paid providers cost real money.** Audit depth decides dimensions, tier *and* engine
   mode. Deep/paid audits spend metered budget. Use `--mode free` / Basic depth unless
   you are deliberately testing spend.

---

## 7 · Where the real documentation is

| Read | For |
|---|---|
| `docs/recovery/DECISIONS_LOG.md` | **Read first.** Supersedes older documents in the repo |
| `docs/implementation/KNOWN_LIMITATIONS.md` | Every open defect and deliberate trade |
| `docs/implementation/TEST_BASELINE.md` | How the suite was made runnable |
| `backend/docs/JOB-CONTRACT.md` | Retry / idempotency / DLQ / terminal states |
| `README.md` | Repository map and stack |

> **Numbers in older docs are stale.** `README.md` says 81 migrations and ~4,900 tests;
> the real figures are 106 and ~7,700. Trust this file and the source, not the prose.
