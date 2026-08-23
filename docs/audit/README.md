# PHASE 2 — REPOSITORY FORENSIC AUDIT

**Audit date:** 2026-08-23 · **Commit audited:** `79d1036` · **Branch:** `main`

No production-critical code was modified. This directory contains analysis only.

---

## Read in this order

| # | Document | What it answers |
|---|---|---|
| 1 | [REPOSITORY_ARCHITECTURE.md](REPOSITORY_ARCHITECTURE.md) | What is actually here — stack, topology, layering, deployment, CI |
| 2 | [FORENSIC_AUDIT.md](FORENSIC_AUDIT.md) | System map, dependencies, coupling, and every verified defect with evidence |
| 3 | [FEATURE_INVENTORY.md](FEATURE_INVENTORY.md) | Every feature classified WORKING / PARTIAL / BROKEN / PLACEHOLDER / MOCK / UNUSED / DUPLICATED / OBSOLETE / MISSING |
| 4 | [REQUIREMENT_GAP_ANALYSIS.md](REQUIREMENT_GAP_ANALYSIS.md) | All 126 P0 requirements: expected vs actual, gap, severity, root cause, action |
| 5 | [SECURITY_AUDIT.md](SECURITY_AUDIT.md) | Authn, authz, secrets, injection, isolation — strengths first, then 4 P0s |
| 6 | [AI_AUDIT.md](AI_AUDIT.md) | Every AI workflow: input, prompt, model, validation, failure, cost, retry, review |
| 7 | [PERFORMANCE_AUDIT.md](PERFORMANCE_AUDIT.md) | Measured frontend, structural backend, and the two risks that bind at 100 clients |
| 8 | [TESTING_AUDIT.md](TESTING_AUDIT.md) | What 219 test files prove, and the three classes they do not |
| 9 | [SALVAGEABILITY_MATRIX.md](SALVAGEABILITY_MATRIX.md) | 28 subsystems banded GREEN / YELLOW / ORANGE / RED with technical reasons |
| 10 | [TARGET_ARCHITECTURE.md](TARGET_ARCHITECTURE.md) | The target design, and — equally important — what deliberately does not change |
| 11 | [MIGRATION_STRATEGY.md](MIGRATION_STRATEGY.md) | 15 migrations: current → target, method, dependencies, risk, rollback, verification |
| 12 | [ENGINEERING_MASTER_PLAN.md](ENGINEERING_MASTER_PLAN.md) | The 20-section plan for approval, with P0–P3 and the Definition of Done |

---

## The finding in one paragraph

The build is **not a failure and not finished**. Authentication, tenant isolation (RLS, proven
from a real client identity against real Postgres), SQL safety, the runtime cost model, 260 of 305
guarded endpoints, 55 working Web 2.0 API publishers and a deterministic audit engine are all
genuinely sound and must be preserved. The failure is narrower: **the system was engineered never
to fail loudly, and then had its clock switched off.** All 39 Celery tasks carry zero retry
configuration, there is no dead-letter queue, `beat_schedule = {}`, and the prevailing doctrine is
"never re-raise" — so the WordPress publish path can swallow four consecutive failures and mark
the job complete, and the free audit can spend real money while recording $0.00. **One subsystem
of twenty-eight is a rebuild candidate** (citation submission: 3 form specs against 151
bot-fillable directories). This is a recovery, not a rewrite.

**P0 requirement coverage:** 43 MET · 41 PARTIAL · 38 NOT MET · 4 UNVERIFIED (of 126).

---

## Audit limitations — stated plainly

| Limitation | Consequence |
|---|---|
| **The backend test suite was not executed.** The only interpreter available was Python 3.14; the project pins `>=3.11` and its dependency set does not resolve on 3.14, and no venv was present | Every backend claim is **code-verified, not run-verified**. "WORKING" means *the path is complete, guarded, tested in-repo and has no identified defect* — not *observed running*. **P0-1 in the master plan is to run the suite and record the result** |
| **The frontend was fully verified.** `npm ci` → `tsc --noEmit` → `next build` all pass | Frontend claims are measured |
| **No live provider was called.** No live WordPress, Elementor, directory or Web 2.0 platform was exercised | Provider contract claims rest on source and on the code's own self-declarations |
| **No load test was run** | Performance findings are structural (what the architecture forces), not benchmarks. The repo contains a real probe at `backend/tests/perf/load_probe.py` |

---

## Second-pass review — corrections made to this audit

Per the brief's §22 instruction, I reviewed my own findings for missed requirements, hidden
dependencies, and incorrect assumptions. Four material corrections resulted, recorded here rather
than quietly edited:

| # | Initial finding | Corrected finding | How it was caught |
|---|---|---|---|
| 1 | **"273 endpoints have no authorization guard."** My first two AST passes reported a near-total absence of authz | **260 of 305 endpoints carry an explicit role/permission guard.** Guards are applied through module-level `Annotated[...]` aliases, and identity also arrives transitively through the repo dependency | Reading `app/routers/vault.py` to see the actual pattern, then rewriting the analyzer to resolve aliases. **Stopping at the first number would have produced a recommendation to rewrite the entire router layer** |
| 2 | **"One table lacks FORCE row-level security."** | **Every RLS-enabled table has both ENABLE and FORCE.** The earlier 76/77 count was a regex artefact — two migrations use `force  row level security` with a double space | Re-running the parse with `\s+` instead of a literal space |
| 3 | **"SEC-004 and CLIENT-008 are PARTIAL — the integration proof needs confirming."** | **Both MET.** `tests/integration/test_portal_isolation.py` proves exactly this against real local Postgres, probing as the `authenticated` role with a client's own identity bound, asserting (a)–(h) including that base tables return zero rows to a foreign tenant and that `mrr`/`cost`/`error`/`*_path` are absent from portal views | Listing `tests/integration/` rather than relying on the marker count |
| 4 | **"Internal linking is MISSING."** | **PARTIALLY WORKING.** `content_generator._links_block` builds a "Related resources" block from the source pack's keyword→URL registry plus cluster spokes, and `content_qa` scores it as a weighted dimension. The real defect is narrower: spoke links are emitted as guessed `/{slug}` paths **not verified to exist on the target site**, so a page can ship internal links that 404 | Grepping for `internal.link` across services during the second pass |

### What the second pass added

- **A requirement absent from the traceability matrix entirely:** there is **no way to offboard a
  user**. The `user_status` enum has no disabled value, no deactivate endpoint exists, `login()`
  never checks status, and the 7-day token is irrevocable — while `manage_team` advertises the
  capability. This is a gap in the requirements, not only in the build.
- **A hidden dependency:** the `[ai]` and `[automation]` extras are *optional in packaging but
  load-bearing in behaviour*. Without them the system produces deterministic fake content and
  cannot submit any citation — and in both cases it **degrades rather than erroring**.
- **A data-integrity risk that reads as a style choice:** `rls_connection()` opens a transaction
  **per repo call**, so client creation is three non-atomic writes with two `except: pass` blocks.
  This is why `ADM-009` ("Citations never again reports no business profile") cannot be guaranteed.
- **A scalability risk invisible from the API surface:** the audit engine's subprocess + local-disk
  contract pins every audit to one host and excludes artefacts from backup.
- **A test-gap reframing:** 219 test files sounds like strong coverage. 116 run against fakes,
  there is no coverage floor, `integrations/` (13.4k LOC) is excluded from measurement, there are
  no frontend tests, and there is no business-outcome end-to-end test. The suite proves units
  behave; it does not prove an outcome is produced — **the same structural defect the specification
  identifies in the product itself.**

---

## Decisions required before implementation begins

Full detail at the end of [ENGINEERING_MASTER_PLAN.md](ENGINEERING_MASTER_PLAN.md).

| Decision | Recommendation |
|---|---|
| **D-17** — Is Policy Radar in v1? | **Yes.** Built, near-zero cost, one line to schedule, and sold to the client as Module 04 of four |
| **D-4** — QA gate: hard block or advisory? | **Advisory** until calibrated on ~50 human-graded pages |
| **Free-audit shape** — condensed+free, or comprehensive+metered? | **Condensed + free.** Satisfies `AUD-001` and `AUD-002` as written and closes the denial-of-wallet vector |
| **Citation re-baseline** — what platform count at what loaded cost? | Build the loaded cost model **first**, then decide with the client. Do not build against the current number |
