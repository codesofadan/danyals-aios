# KNOWN LIMITATIONS

**As of:** 2026-08-23 · **§1 re-measured 2026-08-26** · **Scope:** what this Phase-3 session found and did **not** fix.

This is deliberately not a "final" document — Phase 3 is partially complete (see
`IMPLEMENTATION_LOG.md` for what is done). Publishing a `FINAL_*` set now would misrepresent the
state of the work. Everything below is either a defect that remains open, a decision that is not
mine to make, or a trade I made deliberately and am naming rather than hiding.

---

## 1 · Master-plan P0 items still open

| ID | Item | State |
|---|---|---|
| **P0-3** | Job contract — retry, backoff, DLQ, idempotency, terminal states across all 39 Celery tasks | **DONE** (re-measured 2026-08-26). Landed as **WU-8**, migration `0080_job_contract.sql`, documented in `backend/docs/JOB-CONTRACT.md`, on branch `recovery/p0-3-job-contract`. This row said "Not started" |
| **P0-4** | Stop faking success — the WordPress publish cascade marked `status="done"` on an artifact-only degraded publish | **DONE** (re-measured 2026-08-26). Landed as **WU-10** (`IMPLEMENTATION_LOG.md` §WU-10): the `degraded` label exists, `workers/tasks/content.py` writes it instead of `done`, and `tests/test_content_wp_push.py` + `tests/test_content_worker.py` assert the terminal status is **not** `done`. This row said "Not started" |
| **P0-5** | Staged beat restore | **No longer blocked by P0-3** (which is done) — but **still not wanted**. `beat_schedule = {}` at `backend/workers/celery_app.py:220` is an owner instruction, not a technical dependency; the plan's ordering rule is satisfied, and "unblocked" is not "approved". **Nine tests still assert a populated schedule and are red** — see §2. Needs an owner decision, not engineering |
| **P0-12** | Citation loaded-cost model + client re-baseline | **Still an owner decision** (R1 O-1 buy-vs-build, O-2 the Data Axle rate), but the engineering half moved 2026-08-29: `0106_citation_liveness.sql` + `app/services/citation_liveness.py` make a live citation *measurable*, so the loaded-cost model finally has a real denominator. `data_axle_add_cost_estimate` defaults to 0.0 and **blocks** the aggregator route rather than pricing it at zero, so no run can spend against an invented number. See `docs/research/R1b-citation-brief-response.md` §9 |
| **P0-13** | Backup schedule + failure alert + **restore drill** | **Not started.** Requires real infrastructure (B2 credentials, a live database) that this environment does not have |
| **P0-14** | Decide D-17 (Policy Radar in v1?) | **Owner decision.** One line of code either way |

**P0-11 needs no work and its plan entry is stale — see §3.**

> **Re-measured 2026-08-26.** Two rows above were stale: **P0-3** and **P0-4** both landed
> (WU-8 and WU-10) and this table still called them "Not started". A document that
> reports finished work as unstarted misroutes planning as badly as one that reports
> unfinished work as done. §2–§4 below have **not** been re-measured in this pass and
> should be treated as being as of 2026-08-23 until they are.

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

---

## `check_keyword_rank` has no per-client concurrency cap

*Found 2026-08-23 while migrating the rank tracker onto the job contract.*

Every other client-scoped job under `@aios_job` carries a `client_concurrency` cap, so
one client's bulk run cannot starve the others. The paid rank check does not, and it is
the job where the cap would matter most — it is the platform's largest line item.

**Why:** the cap needs a `client_id` at CLAIM time, and the job's `target` callable
receives only `keyword_id`. `dispatch_due` returns keyword ids, so resolving the client
would mean a database read inside `target`, which runs before the run row exists and on
whatever process enqueued the work.

**The fix, when someone takes it:** have `dispatch_due` return `(keyword_id, client_id)`
and pass the client through to `check_keyword_rank`. That is a change to the module's
core and its own tests, which is why it is recorded here rather than bodged into a task
migration.

**What holds meanwhile:** the daily idempotency key (`rank.check:<keyword>:<date>`)
bounds the spend per keyword per day regardless of how many times it is enqueued, and
`dispatch_rank_checks` claims in bounded batches (`rank_tracker_dispatch_batch`). So the
exposure is fairness between clients within a nightly sweep, not unbounded spend.

---

## `cost_log` is called "append-only" twice and is not — and the money is the reason it matters

**Found 2026-08-24, verified at source and measured by a parallel session against a built
database. Not fixed: the fix is a decision, not a correction.**

`db/migrations/0006_cost.sql` describes the per-call cost ledger as append-only in two places:

```
:6   -- Budget/daily writes flow through the service_role gate; cost_log is append-only.
:49  -- --- Per-call cost log (append-only) ----------------------------------------
```

Its only policy is `cost_log_select` (`:104`). There is **no update policy, no delete policy and
no trigger**. That reads as immutability, and it is not: the ledger's only writer runs on
`service_role`, which is `create role service_role login bypassrls`
(`0000_local_platform.sql:35`) and is granted `update, delete` (`:50`). **Policies are never
consulted for a `BYPASSRLS` connection**, so the absent policy constrains every principal except
the one that writes. Measured as `service_role`: a `cost_log` row was rewritten
(`cost=12.345678 → 0.000000`) and then deleted.

**Why this one is worse than the audit log.** `backend/CLAUDE.md` item 10 made the same claim
about `activity_log` and was corrected in `6b959df`. But `cost_log` is what the platform bills
against — it is the source for per-client actual spend, the daily stop, and the monthly
modelled-vs-actual reconciliation. "Append-only" on a money ledger implies a guarantee an auditor
would rely on, and the guarantee is app-tier convention only.

**Why it is not fixed here.** Three reasons, in order of weight:

1. **It is a decision, not a defect.** A `before update or delete` trigger — the pattern WU-16
   used for `evidence`, which fires for `BYPASSRLS` roles — would make it real. It would also
   block legitimate correction, and cost corrections demonstrably happen in this system
   (`de40d27` stopped a paid check being billed twice for one day; `0044` widened the money
   columns after sub-cent charges recorded as `$0.00`). Whether a billing ledger should be
   correctable, or corrected only by compensating entries, is an owner call with accounting
   consequences.
2. **The claims live in an applied migration.** Editing `0006`'s comments would make the file
   differ from what was applied. There is no checksum gate today, so it is possible — but the
   correction belongs where people look for current truth, which is here.
3. **It is not the module this session owns.** WU-14 locked the cost *read* surface; the ledger's
   durability model is a different question.

**What a fix looks like, for whoever takes it:** a trigger on `cost_log` mirroring
`evidence`'s, plus a decision recorded in `DECISIONS_LOG.md` about how a mis-billed row is
corrected — a compensating entry is the accounting-conventional answer and needs no exception to
immutability. Then correct the two comments, or supersede them in a later migration.

**The general rule, which has now produced four instances in one day:** *"no UPDATE policy" is
not immutability when the writer is `BYPASSRLS`.* The absent policy protects the table from
everyone except its only writer. Discovered by the evidence-primitive unit on
`keyword_rankings`, generalised to `activity_log`, and found again here.
