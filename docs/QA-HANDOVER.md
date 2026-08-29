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
| Backend | `./.venv/bin/python -m pytest tests -q` | **6,816 passed · 9 failed · 144 skipped** (~10 min) |
| Frontend types | `npx tsc --noEmit` | clean, exit 0 |
| Frontend units | `npx vitest run` | green |

The backend suite takes **>3 hours single-process**. Use `pytest -n 8` (pytest-xdist)
or budget the time. This is defect **D-4** below.

---

## 4 · The 9 backend failures are EXPECTED — do not file them

All nine assert that Celery's periodic schedule is populated. It is deliberately empty:
`celery_app.conf.beat_schedule = {}` in `backend/workers/celery_app.py`. Cron was
switched off by owner instruction on 2026-08-19 and the full schedule is preserved
verbatim in `_BEAT_SCHEDULE_DISABLED` right below it.

```
tests/modules/billing/test_tasks.py::test_the_beat_schedule_wires_the_sweep
tests/modules/local_seo/test_tasks.py::test_the_beat_task_is_wired_into_the_schedule_and_the_include_list
tests/modules/rank_tracker/test_tasks.py::test_the_beat_schedule_registers_both_scheduled_tasks
tests/test_celery.py::test_context_dispatch_is_on_the_beat_schedule
tests/test_reports.py::test_scheduled_jobs_endpoint_lists_live_beat_schedule
tests/test_scheduled_jobs.py::test_scheduled_jobs_reflects_live_beat_schedule
tests/test_scheduled_jobs.py::test_beat_schedule_includes_the_autonomous_report_jobs
tests/test_scheduled_jobs.py::test_scheduled_jobs_surfaces_last_run_and_status
tests/test_scheduled_jobs.py::test_scheduled_jobs_flags_waiting_on_absent_provider_key
```

They are left red on purpose — they are the acceptance suite for restoring the
schedule. **Consequence for you: nothing in this system runs on a timer.** Every job is
event-driven or on-demand. Do not write test cases that wait for a scheduled run.

---

## 5 · Known-absent and known-broken — check here before filing

Full detail in `docs/implementation/KNOWN_LIMITATIONS.md`. The headlines:

| Area | State |
|---|---|
| **Scheduling** | Nothing runs autonomously (§4 above) |
| **Citations** | Submission is being rebuilt around data aggregators + a human work queue. The old DOM-spec approach is not the target |
| **Content → WordPress** | Design *capture* is real. Translating a captured design into a live page-builder block tree is **not built** |
| **QA gate on publish** | Advisory only. `PublishBlocked` is raised nowhere. The mandatory-acknowledgement half (D-4) is not built — a lead can approve a sub-threshold draft and is never shown the score |
| **Backups / restore** | Not started. Needs real infrastructure |
| **`TaskResponse.due`** | Served as a year-less string (`"Jul 12"`); the frontend infers the year |
| **Flaky under load** | `test_ready.py::test_ready_is_bounded_and_reports_sibling` and `test_context_worker.py::test_full_pipeline_activity_to_summarized_context` pass in isolation, flake under CPU contention |
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
