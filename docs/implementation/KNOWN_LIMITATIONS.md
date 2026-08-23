# KNOWN LIMITATIONS

**As of:** 2026-08-23 · **Scope:** what this Phase-3 session found and did **not** fix.

This is deliberately not a "final" document — Phase 3 is partially complete (see
`IMPLEMENTATION_LOG.md` for what is done). Publishing a `FINAL_*` set now would misrepresent the
state of the work. Everything below is either a defect that remains open, a decision that is not
mine to make, or a trade I made deliberately and am naming rather than hiding.

---

## 1 · Master-plan P0 items still open

| ID | Item | State |
|---|---|---|
| **P0-3** | Job contract — retry, backoff, DLQ, idempotency, terminal states across all 39 Celery tasks | **Not started.** The critical path, and the prerequisite for P0-5 |
| **P0-4** | Stop faking success — the WordPress publish cascade still marks `status="done"` on an artifact-only degraded publish | **Not started.** Analysed; needs an enum migration, a trigger change, and a frontend render change |
| **P0-5** | Staged beat restore | **Blocked on P0-3** by the plan's own hard ordering rule ("never restore a schedule for tasks that cannot retry and have nowhere to fail to"). **Nine tests already assert it and are red** — see §2 |
| **P0-12** | Citation loaded-cost model + client re-baseline | **Blocked on an owner decision**, not on engineering (plan §13, risk R2) |
| **P0-13** | Backup schedule + failure alert + **restore drill** | **Not started.** Requires real infrastructure (B2 credentials, a live database) that this environment does not have |
| **P0-14** | Decide D-17 (Policy Radar in v1?) | **Owner decision.** One line of code either way |

**P0-11 needs no work and its plan entry is stale — see §3.**

---

## 2 · The nine red tests, and why they stay red

`beat_schedule = {}` in `workers/celery_app.py:173`. Nine tests across `billing`, `local_seo`,
`rank_tracker`, `context` and the `scheduled_jobs` operator surface assert the schedule is
populated. They were left red when cron was switched off on 2026-08-19.

**They are deliberately not "fixed".** Making them pass by weakening the assertion would delete the
only mechanical statement of `AUTO-001` in the repository. They are the acceptance suite for P0-5
and should turn green when the schedule is genuinely restored — after P0-3, per the plan's ordering
rule.

**Consequence to state plainly: the backend CI `lint-test` job has been failing on `main` since
2026-08-19**, and the `integration` job was failing for an unrelated reason (§4).

---

## 3 · Two audit findings that turned out to be stale

Recorded because the plan derives P0 items from them.

**Audit finding #7 / P0-11 — "a hard publish gate rests on a self-declared uncalibrated score".**
Not true at the audited commit. `publish_content_job` already treats QA as advisory, and
`PublishBlocked` is **raised nowhere in the codebase**. The plan's requested change is already the
state of the code.

What was genuinely wrong was the **documentation**: three docstrings claimed publish "re-checks the
QA hard gate and BLOCKS a sub-threshold draft". An engineer reading them would reasonably believe an
automated quality gate stood between a bad draft and a client's live site. Corrected.

**Still open, and a real gap:** D-4 asks for "advisory **+ mandatory acknowledgement** until
calibrated". Only the advisory half exists — the QA verdict goes to the server log, and the lead
approving the draft is never shown it or required to acknowledge a sub-threshold score. Closing it
needs a decision on the acknowledgement's shape (block the approve button? require a typed reason?),
so it is left open rather than guessed at.

**Audit finding: `tests/test_elementor.py` asserting `"<h1>"`.** The product was correct; the test
was pinned to a formatting detail. Fixed as a test, not as a product change.

---

## 4 · CI has never actually proven tenant isolation

`rls_connection` applies row-level security because its pool **logs in as the `authenticated`
role** — it issues no `SET ROLE`. `backend-ci.yml` pointed both DSNs at the `postgres` superuser,
under a comment asserting the opposite. A superuser bypasses RLS unconditionally, so **eleven
tenant-isolation tests were failing in CI**, and the ones that would have passed would have passed
*vacuously*.

Fixed, with a guard step that fails the job if `DATABASE_URL` ever names a BYPASSRLS role again.

**The design itself is sound** — pointed at the right roles, the full integration suite is green and
the isolation proofs hold. What had never been demonstrated was CI's ability to demonstrate it.

---

## 5 · Deliberate trades made in this session

Each is a choice with a cost, named here rather than buried.

| # | Trade | Cost accepted | Why |
|---|---|---|---|
| **T-1** | The CSP keeps `script-src 'unsafe-inline'` | Mitigates **exfiltration, not injection** | Removing it needs nonce-based middleware, which forces every route to render dynamically and gives up the fully-static build. `connect-src 'self'` still stops a stolen token being posted to an attacker host |
| **T-2** | The CSP allows `img-src https:` | An image-beacon exfiltration side channel remains | The product legitimately renders images from arbitrary client sites (WordPress media, audit screenshots). Closing it would break real functionality |
| **T-3** | Token revocation **fails open** on a Redis outage | A revoked token could survive a cache outage | It is not the boundary. Suspension is enforced against Postgres on every request. Failing closed would mean a cache blip logs out every user — trading a real total outage for a risk already covered |
| **T-4** | The revocation epoch errs toward **revoking too much** | A token minted in the same second as a revocation is killed; that person signs in again | `iat` has one-second resolution, so the boundary must fall one way. The alternative lets an offboarded person's just-issued token survive their suspension |
| **T-5** | The free audit loses **Core Web Vitals** | The lead magnet is weaker | `--mode free` hard-clears PSI at the engine. PageSpeed is genuinely free-tier, so this is an engine inconsistency (§6), not a necessary loss — but the audit engine is out of the recovery's change scope |
| **T-6** | KPI **labels** kept in `lib/tools.ts` while values were deleted | Dead-looking constants remain | They are the canonical spec that 156 backend contract tests pin the workspace adapters to. `tools` still passes `kpis: []` at render so the honest empty state is preserved |

---

## 6 · Defects found but not fixed (out of scope)

| # | Defect | Why not fixed |
|---|---|---|
| **D-1** | The audit engine's `--mode free` help text promises "free PSI (rate-limited)" but the code sets `psi = False`. A condensed free audit could carry Core Web Vitals at zero cost | `danyals-audit-system` is a separate product with its own CI, explicitly outside the recovery's change scope (`TARGET_ARCHITECTURE.md §15`) |
| **D-2** | `TaskResponse.due` is served as a **year-less** display string (`"Jul 12"`). The frontend must infer a year the server already knows | Needs an additive `dueDate` ISO field on the wire plus a frontend switch. `dueInfo` now infers the nearest year, which is correct in every realistic case but is inference where a fact was available |
| **D-3** | The backend has **no dependency lock**. CI installs whatever is newest; today that is FastAPI 0.141 / pytest 9.1.1 — versions the code was never written against. One removed private API silently disabled an entire security test module | Proposed remedy (a committed constraints file CI installs from, with an unpinned job kept advisory) is a change to the build contract and should be an explicit decision |
| **D-4** | The unit suite takes **>3 hours single-process**; CI runs it that way. Nobody runs a 3-hour suite locally, which is how nine tests stayed red for four days | Adding `pytest-xdist` to `[dev]` and `-n auto` to CI is a one-line fix, deliberately deferred so the baseline was measured on the suite exactly as the project ships it |
| **D-5** | Two tests are **timing-sensitive and flake under CPU contention**: `test_ready.py::test_ready_is_bounded_and_reports_sibling` and `test_context_worker.py::test_full_pipeline_activity_to_summarized_context`. Both pass in isolation; both failed once while an 8-worker suite ran concurrently | Latent CI flakes. They need explicit clocks/fakes rather than wall-clock budgets |
| **D-6** | Contract-lock tests pin backend response models to **frontend TypeScript types**, with no signal on the frontend side. Deleting a TS type breaks a backend test with no local warning | Correct intent, one-directional enforcement. Cost me two failures during this session |

---

## 7 · Environment caveats on the verification

Stated so nobody reads more into the green than is there.

| Caveat | Consequence |
|---|---|
| The integration suite ran against **PostgreSQL 17.11**, not the production 16 | Migration and RLS semantics are identical across the two, but this is a proxy, not a production-version verification. The `postgres:16-alpine` image would not pull in this environment |
| **No live provider was called** — no Serper, Anthropic, Google, WordPress, directory or Web 2.0 platform | Five integration suites auto-skipped. Every provider-contract claim still rests on source, exactly as the Phase-2 audit noted |
| **The audit engine was never executed** | The free-audit change is verified at the `build_argv` and cost-computation seams, not by observing a real run produce a real `run.json` |
| **No load test, no volume run** | Nothing here speaks to the owner's 50×10 acceptance bar |
| `docs/`, `context/` and `docs/deliverables/` were deliberately **left untouched** by the branding sweep | They are the project's own historical record, including the backlog entry that states the branding rule. Rewriting history to satisfy a lint is dishonest, not compliant |

---

## 8 · What "done" does and does not mean in the implementation log

A working unit marked ✅ means: implemented, lint- and type-clean, covered by tests that fail when
the defect is reintroduced (proven, for the guard suites, by reintroducing it), and the full suite
re-run with no new failures.

It does **not** mean any of the nine Definition-of-Done gates in `ENGINEERING_MASTER_PLAN.md §20`
have been met for a whole capability. In particular **Gate 1 (Outcome)**, **Gate 6 (Performance)**
and **Gate 9 (Acceptance)** have not been exercised for anything in this session — no business
outcome was produced end to end on real data, nothing was measured at volume, and the owner has run
none of it.

---

## `dispatch_audit_refresh` and `dispatch_offpage_sweep` conflate two kinds of skip

*Found 2026-08-23 while migrating the report sweeps onto the job contract.*

Both cores count two different outcomes as `skipped`:

* a client **legitimately** passed over — audited recently, or with no domain to sweep;
* a client the sweep **could not process** — the per-client `try/except Exception`
  (`workers/tasks/reports.py`) swallows a failure, logs a warning, and increments the
  same counter.

So a systematic failure in which every client fails reports
`{"state": "ok", "queued": 0, "skipped": N}` — a run that reads as **successful and
did nothing**. Under the job contract that is precisely the shape that should be
`degraded` with a reason, and it cannot be, because the information does not survive
the core's return value.

**Not fixed here, deliberately.** Inventing a `degraded` signal the core cannot
substantiate would be the same class of defect the contract exists to remove — a
status asserting more than the data supports. The fix is to split the counter in the
CORE (`skipped_recent` vs `skipped_failed`, or a list of failures), which changes its
return shape and its own tests, and belongs with the reports module rather than riding
along on a task migration.

**Mitigated meanwhile:** the skip count is always surfaced in the run's `detail` and
`result`, and `tests/test_reports_jobs.py::test_a_sweep_that_skipped_everything_still_says_so`
pins that, so the number is visible on the operator surface even while its meaning is
ambiguous.
