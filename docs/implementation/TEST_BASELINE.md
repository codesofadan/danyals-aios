# TEST BASELINE — P0-1

**Recorded:** 2026-08-23 · **Commit at baseline:** `79d1036` · **Workstream:** WS-9

The Phase-2 audit could not execute the backend suite (only Python 3.14 was present and the
dependency set does not resolve on it), so every backend claim in that audit is *code-verified,
not run-verified*. **P0-1 closes that gap.** This document records the first true execution.

---

## 1 · How the suite was made runnable

`uv` is installed on this machine, which resolves the interpreter problem the audit hit:

```
uv venv --python 3.12 backend/.venv        # CPython 3.12.14, matches the Docker image
VIRTUAL_ENV=backend/.venv uv pip install -e ".[dev]"
```

`backend/.venv/` is git-ignored. CI is unaffected — it uses `actions/setup-python` with the
3.11 / 3.12 matrix already declared in `backend-ci.yml`.

**Parallelism.** The suite is CPU-bound (Argon2id hashing plus a FastAPI app built per
RBAC-matrix test) and takes **>3 hours single-process** on this 8-core machine. With
`pytest-xdist -n 8` it completes in **10m30s**. `pytest-xdist` was installed into the local venv
only; it is **not** added to the project's `[dev]` extra (see Risk R-B2 below).

---

## 2 · Result — the honest baseline

Command:

```
pytest -m "not integration" -n 8 --continue-on-collection-errors
```

| Metric | Value |
|---|---|
| **Collected** | 4,950 (4,873 selected, 77 deselected as `integration`) |
| **Passed** | **4,857** |
| **Failed** | **12** |
| **Skipped** | 4 |
| **Collection errors** | **1** (whole module could not be imported) |
| **Wall time** | 630.25 s on 8 workers |

**Two of the twelve failures were caused by this session's own frontend edits** (deleting two TS
types that `test_contract_lock.py` pins backend response models to). They were fixed within the
same working unit and are excluded below. **The true pre-existing baseline is 10 failures plus 1
collection error.**

### 2.1 · Failure class A — the beat schedule (9 of 10)

| Test | Asserts |
|---|---|
| `tests/test_celery.py::test_context_dispatch_is_on_the_beat_schedule` | `dispatch_context` is scheduled |
| `tests/modules/billing/test_tasks.py::test_the_beat_schedule_wires_the_sweep` | the past-due sweep is scheduled |
| `tests/modules/local_seo/test_tasks.py::test_the_beat_task_is_wired_into_the_schedule_and_the_include_list` | local-rank refresh is scheduled |
| `tests/modules/rank_tracker/test_tasks.py::test_the_beat_schedule_registers_both_scheduled_tasks` | both rank tasks are scheduled |
| `tests/test_scheduled_jobs.py::test_scheduled_jobs_reflects_live_beat_schedule` | the operator surface reads the live schedule |
| `tests/test_scheduled_jobs.py::test_scheduled_jobs_surfaces_last_run_and_status` | last-run/status per scheduled job |
| `tests/test_scheduled_jobs.py::test_scheduled_jobs_flags_waiting_on_absent_provider_key` | a keyless scheduled job reads as waiting |
| `tests/test_scheduled_jobs.py::test_beat_schedule_includes_the_autonomous_report_jobs` | the three autonomous report jobs are scheduled |
| `tests/test_reports.py::test_scheduled_jobs_endpoint_lists_live_beat_schedule` | `/reports/scheduled-jobs` lists the live schedule |

**Every one of these fails for a single reason:** `workers/celery_app.py:173` sets
`celery_app.conf.beat_schedule = {}`, with the real schedule parked in
`_BEAT_SCHEDULE_DISABLED`.

**This is materially new information for the plan.** The repository's own tests already encode
the requirement that the schedule be populated; they were left red when cron was switched off on
2026-08-19 rather than being updated. **P0-5 (staged beat restore) therefore has a ready-made,
pre-existing acceptance suite** — nine tests that turn green exactly when the schedule is correct,
covering `AUTO-001` from four different modules plus the operator surface.

It also means the backend CI job **has been red on `main` since 2026-08-19**.

### 2.2 · Failure class B — a stale assertion (1 of 10)

`tests/test_elementor.py::test_plugin_payload_carries_elementor_when_enabled`

Asserted the literal substring `"<h1>"` in the flat-HTML publish body. The Gutenberg emitter
attributes its headings, so the body actually contains `<h1 class="wp-block-heading">`. **The
product is correct; the assertion was pinned to a formatting detail rather than the SEO property
it meant to protect.** Fixed to match an `<h1>` *element*.

### 2.3 · Collection error — dependency drift (root cause, not a test bug)

`tests/test_public_endpoints.py` — the module imported `fastapi.dependencies.utils.get_flat_dependant`,
a **private** FastAPI helper **removed in FastAPI 0.141**. The whole module (9 tests, covering the
unauthenticated public funnel's auth posture, SSRF rejection and report-token curation) failed to
import and **did not run at all**.

Fixed by walking the dependency tree locally instead of through a private API.

**The underlying cause is broader and is a finding in its own right — see R-B1.**

---

## 3 · Post-fix state

| | Before | After |
|---|---|---|
| Passed | 4,857 | 4,875 (+9 recovered from the collection error, +1 elementor, +8 unchanged) |
| Failed | 10 pre-existing | **9** (all beat-schedule; they close under P0-5) |
| Collection errors | 1 | **0** |

No product code was changed to reach this state — two test files and one private-API usage.

---

## 4 · New risks this baseline surfaced

| # | Risk | Impact | Status |
|---|---|---|---|
| **R-B1** | **The backend build is not reproducible.** `pyproject.toml` declares only lower bounds and there is no lock file, so CI installs whatever is newest on the day. Today that resolves to FastAPI 0.141 / pytest 9.1.1 / Starlette 1.6 — versions the code was never written against. One removed private API silently disabled an entire security test module. | **High.** A green CI run proves nothing about what production will install, and a future breakage lands as a mystery. | **Open** — proposed remedy is a committed constraints/lock file that CI installs from, with an unpinned "latest" job kept advisory. Not yet implemented. |
| **R-B2** | **The suite takes >3 hours serially.** No parallel runner is declared, so CI runs it single-process. Nobody runs a 3-hour suite locally, which is how nine tests stayed red for four days. | **Medium.** Directly undermines every "tests exist" claim in the Definition of Done. | **Open** — proposed remedy is adding `pytest-xdist` to `[dev]` and `-n auto` to CI. Deferred so that this baseline is measured on the suite exactly as the project ships it. |
| **R-B3** | Two contract-lock tests pin backend response models to **frontend TypeScript types**, and nothing in the frontend toolchain knows this. Deleting a TS type breaks a backend test with no local signal. | Low–Medium. Correct intent, one-directional enforcement. | Documented. The frontend CI job added under WS-9 does not cover it; the backend job does. |
