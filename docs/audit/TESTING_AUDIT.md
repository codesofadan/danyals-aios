# TESTING AUDIT — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit:** `79d1036`

> **Limitation.** The suite was **not executed** — no compatible Python interpreter was available
> (see `REPOSITORY_ARCHITECTURE.md` preamble). Everything below comes from reading the tests, the
> CI workflow and the fixtures. I can say what is tested and how; I cannot say what currently
> passes. **The first action in any recovery plan should be to run this suite and record the
> result**, because a large, well-structured suite that has drifted red is worse than no suite.

---

## 0. Verdict

**The backend test discipline is genuinely good — materially better than the recovery
specification's tone would lead you to expect — and the gaps are specific, not general.**

| | |
|---|---|
| **Backend** | 219 files, 67,822 LOC. 161 unit-marked, 25 integration-marked. Real Postgres + Redis in CI. Tenant isolation proven from a client's own identity. A mutation-testing harness exists. |
| **Frontend** | **Zero tests. Zero CI. No test runner installed.** |
| **End-to-end** | One real stack test (`test_local_e2e.py`), but **no business-outcome E2E** — nothing proves audit→report, or content→published-page. |
| **Coverage gate** | **None.** `pytest --cov` runs with no `--cov-fail-under`. Coverage is reported and never enforced. |

The single most important gap is not quantity. It is that **the suite proves units behave and does
not prove an outcome is produced** — which is precisely the failure mode the specification's §1.4
identifies as the project's structural problem.

---

## 1. What exists

### 1.1 Composition

| Layer | Files | Note |
|---|---|---|
| Root unit suite | ~130 | One file per service/router/integration |
| `tests/integration/` | 23 | Against **real** local Postgres + Redis |
| `tests/modules/` | 13 subdirectories | Per-module suites for the Part-8 modules |
| `tests/fixtures/` | — | Shared seed data |
| `tests/perf/load_probe.py` | 1 | A real p50/p99/throughput probe on the RLS read path (not collected as a test) |
| `tests/mutation/run_mutation.py` | 1 | A dependency-free mutation tester (mutmut has no Windows support) |
| **Total** | **219** | **67,822 LOC** |

116 files inject deterministic fakes (`FakeSummarizer`, `FakeWeb2Publisher`,
`FakeCitationSubmitter`, `FakeWordPressPluginPublisher`, in-memory cost stores). This is the
right pattern — the fakes satisfy the same Protocols as the real clients, so the unit suite runs
offline and fast.

### 1.2 CI pipeline — `.github/workflows/backend-ci.yml`

| Job | Steps | Verdict |
|---|---|---|
| `lint-test` | `ruff check` → `mypy app workers` (**strict mode**) → `pytest -m "not integration" --cov` | Strong. Strict mypy on 62k LOC is real discipline |
| `integration` | Spins Postgres + Redis, applies **all 80 migrations**, mints an **ephemeral EdDSA keypair** and a vault master key, runs `pytest -m integration` | Strong. This is not a token integration job |
| `security` | `pip-audit` (fails the job on a vulnerable dependency) + `gitleaks` with a narrow allowlist | Strong |
| `db-rls` | Applies migrations, runs the RLS gate as a **script** and again as a **pytest** | Strong |

A separate `ci.yml` exists inside `danyals-audit-system/`.

### 1.3 The tests that genuinely earn their keep

| Test | What it proves | Why it matters |
|---|---|---|
| `test_route_auth_guard.py` | Walks the **live OpenAPI surface at runtime** and asserts every non-public operation 401s unauthenticated. Guards against the sweep going silently empty (`assert len(protected) > 50`) | Auto-covers every future route. This is the single best test in the repository |
| `integration/test_portal_isolation.py` | Two client tenants + one staff user against **real Postgres**, probing as the `authenticated` role with the client's own identity bound. Asserts (a)–(h): base tables return **0 rows** to a foreign tenant; `mrr`/`cost`/`error`/`*_path` are absent from portal views; a portal-run audit is written with a **server-pinned** `client_id`; a free-tier client is 403'd from a paid audit; staff still read every tenant | **This satisfies SEC-004 and CLIENT-008 properly.** It is a real trust-boundary proof, not a mock |
| `integration/test_local_e2e.py` | provision owner → `POST /auth/login` → real EdDSA token → drive the real app → create a client through the RLS path → cost gate blocks against a seeded over-cap budget → activity row written and read back | The only genuine full-stack test |
| `integration/test_rls_matrix.py`, `test_rls_gate.py` | RLS coverage and policy behaviour | Structural + behavioural |
| `integration/test_repo_sql_parity.py` | Repo SQL matches the real schema | Catches drift between hand-written SQL and migrations — a real risk with no ORM |
| `test_contract_lock.py` | Backend response shapes are pinned against the frontend's `lib/*.ts` contracts | The right mitigation for a demo-first-built API |
| `test_content_golden.py` | Golden-set content generation | Determinism proof for the writer path |
| `test_client_boundary.py`, `test_backlinks_own_profile.py` | Tenant-boundary units | — |
| `mutation/run_mutation.py` | Reports a mutation score by mutating function bodies and re-running the module's test file; survivors are the actionable output | Almost nobody builds this. It shows the team cared about *assertion quality*, not just line coverage |

---

## 2. What is not tested

### 2.1 The frontend — nothing at all — **P0**

- No `jest`, `vitest`, `playwright`, `@testing-library` — nothing in `frontend/package.json`.
- **No frontend CI workflow exists.** `tsc --noEmit` and `next build` are never run by CI; I ran
  them manually for this audit (both pass).
- 136 components, 27k LOC, three portals, zero assertions.

**Consequence:** the entire surface the client and the team actually touch is unverified.
Requirement `ADM-003` ("every rendered control performs a real action or is not rendered") has no
mechanical enforcement whatsoever — which is exactly why two separate cleanup commits were needed
to remove dead controls, and why `AuditCoverage.tsx` still renders "Coming soon".

### 2.2 No business-outcome end-to-end test — **P0**

`test_local_e2e.py` proves the *plumbing*. Nothing proves an *outcome*:

| Outcome the business is paid for | Tested end-to-end? |
|---|---|
| A site is audited and a readable report exists | **No** — `test_audit_engine_live.py` exists but auto-skips without live keys |
| Content is generated, reviewed, approved and **appears on the client's WordPress site** | **No** |
| A citation is submitted and a live listing URL is captured | **No** |
| A Web 2.0 property is published and verifiable | **No** |
| A client logs into their portal and sees their own audit and report | **Partially** — `test_portal_isolation.py` proves the boundary, not the journey |

This is the specification's §1.4 finding expressed as a test gap: *the system was built
module-by-module against a UI, not workflow-by-workflow against an outcome*, **and the test suite
inherits exactly that shape.**

### 2.3 Failure paths are structurally under-tested — **P0**

The system's defining behaviour is degradation. Its degradation is barely tested:

| Failure mode | Test found |
|---|---|
| The four-way WordPress publish cascade falling through every stage to `degraded=True` | **None** |
| A Celery task raising mid-run (no retry exists, so what happens?) | **None** |
| Provider 429/5xx during a batch | **None** |
| Redis down → rate limiter fails **open** | Partially — `test_ratelimit.py` |
| Cost gate blocking silently on `POST /keyword-research/research` | **None** |
| `visibility_timeout < task_time_limit` → double delivery, double spend | **None** — and this is an unasserted invariant |
| Audit engine subprocess timeout / non-zero exit / missing `run.json` | `test_audit_engine_adapter.py` covers the adapter's handling — **this one is done** |

`test_context_failure_modes.py` is the sole file dedicated to failure modes, and it covers one
module.

### 2.4 Coverage is measured and never enforced — **P1**

```yaml
run: pytest -m "not integration" --cov=app --cov=workers --cov-report=term-missing
```

No `--cov-fail-under`. Coverage prints to the log and no one is accountable to it. Also note the
`--cov` scope excludes `integrations/` — 13,416 LOC of provider clients, including the 3,217-LOC
`web2_publishers.py` and the 1,083-LOC `citation_bot.py`, are **not in the coverage measurement
at all**.

### 2.5 Multi-tenant isolation beyond the DB — **P1**

`test_portal_isolation.py` proves *data* isolation excellently. Nothing proves *workflow*
isolation (`MT-007`: "a failure for one client cannot corrupt another's data or workflow"):

- No test that one client's bulk run does not starve another's queue.
- No test of per-client concurrency caps (they do not exist).
- No test that a poisoned job does not block a worker slot indefinitely.

### 2.6 Specific untested requirements

| Requirement | Gap |
|---|---|
| `CONT-017` — zero em dashes **in emails and AI responses** | The guard is exhaustively tested on content; emails and ai-assist are not covered |
| `WP-015` — never write global styles/theme/existing pages | Holds by construction; no assertion |
| `AI-012` — no credentials or other clients' data in a model context | Holds by construction; no assertion |
| `CIT-023` — a missing required field blocks the unit | No negative test |
| `WP-007` — Elementor output opens fully editable | `test_elementor.py` verifies the **tree shape**; nothing verifies against a live Elementor install |
| `ADM-003` — no dead controls | No mechanical enforcement anywhere |
| `AUTO-011` — visibility timeout invariant | Not asserted, not tested |

### 2.7 Live-provider suites auto-skip

`test_audit_engine_live.py`, `test_email_workflows_live.py`, `test_context_live.py` and the
provider integration tests all auto-skip without keys. The CI comment says this is intentional.
It is a defensible choice — but it means **no provider contract is verified anywhere**, and
provider contracts are exactly what broke in the citation module (`Foursquare`'s documented write
endpoint returning 404).

---

## 3. Test-quality assessment

**Do the tests test business behaviour, or implementation?**

Mostly behaviour, and better than average:

- `test_portal_isolation.py` asserts *the client cannot see another client's cost*, not *the query
  has a WHERE clause*.
- `test_rbac_matrix.py` asserts *role boundaries*, and the mutation harness exists specifically to
  find weak assertions in it.
- `test_content_golden.py` asserts *output stability against a golden set*.
- `test_contract_lock.py` asserts *the frontend's expected shape*, which is a behavioural contract.

Weaker areas: many per-module suites in `tests/modules/*` are CRUD round-trips against fakes,
which prove the repo layer wires up and little else.

**Are integrations tested?** The *seams* are (via Protocol fakes). The *providers* are not.

**Are error cases tested?** See §2.3 — this is the weakest dimension.

**Is multi-tenant isolation tested?** Data: **yes, properly**. Workflow: no.

---

## 4. The testing gap report

| # | Gap | Severity | Requirement | Recommended action |
|---|---|---|---|---|
| T-1 | **No frontend tests and no frontend CI** | **P0** | QA-008, ADM-003 | Add a `frontend-ci.yml` running `tsc --noEmit` + `next build` **today** (both already pass — lock it in). Then Playwright smoke tests per portal: login, each nav item loads, every button either acts or is absent |
| T-2 | **No business-outcome E2E** | **P0** | QA-008 ("one true end-to-end path"), QA-009 | Build one per v1 module against a disposable target: audit→report; content→WordPress→live URL; citation→listing URL. These double as the acceptance evidence for the owner's 50×10 bar |
| T-3 | **Failure paths untested** | **P0** | QA-004 ("each mode deliberately triggered") | A dedicated failure-injection suite: provider 429/5xx, publish-cascade exhaustion, task exception, Redis down, subprocess timeout, spend halt engaged |
| T-4 | **No coverage floor; `integrations/` excluded from measurement** | **P1** | QA-008 | Add `--cov=integrations` and `--cov-fail-under` at the current measured level, then ratchet |
| T-5 | **No provider contract tests** | **P1** | CIT-010, INT-* | Recorded-cassette tests (VCR-style) for every provider whose contract is load-bearing — Bing Places and Foursquare first, since both are flagged unconfirmed in source |
| T-6 | **Workflow isolation untested** | **P1** | MT-007 | Test per-client concurrency caps once they exist |
| T-7 | **The `visibility_timeout` invariant is neither asserted nor tested** | **P1** | AUTO-011 | A boot assertion plus a unit test on it |
| T-8 | **Elementor output never verified against a live Elementor** | **P1** | WP-007 | A containerised WordPress+Elementor fixture in CI, or a documented manual acceptance step |
| T-9 | **`ADM-003` (no dead controls) has no mechanical enforcement** | **P2** | ADM-003 | A Playwright crawl asserting every rendered `<button>` has a bound handler that issues a request or navigates |
| T-10 | **Constructive invariants unasserted** (WP-015 additive-only, AI-012 no-credentials-in-context, CIT-023 missing-field-blocks) | **P2** | — | One negative test each; cheap, and they are the invariants that protect the client |

---

## 5. Recommended target state

| Layer | Today | Target for v1 acceptance |
|---|---|---|
| Backend unit | 161 files, fakes, strict mypy | **Keep as is** — this is not the problem |
| Backend integration | 23 files, real Postgres+Redis, isolation proven | **Keep**, add failure injection |
| Provider contract | none | Cassette tests for every load-bearing provider |
| Business E2E | none | **One per v1 module**, run in CI against disposable targets |
| Frontend typecheck/build | manual only | **In CI, blocking** |
| Frontend component/E2E | none | Playwright smoke per portal |
| Coverage | measured, unenforced, `integrations/` excluded | Floor enforced, `integrations/` included |
| Mutation | harness exists, ad hoc | Run on `rbac/matrix.py`, `cost_gate.py`, `content_qa.py` in CI weekly |

---

## 6. One closing observation

The test suite tells you what the team valued. They valued **security boundaries** (proven from a
real client identity against real Postgres), **type safety** (strict mypy on 62k LOC),
**determinism** (golden sets, injected fakes, a mutation harness), and **schema integrity** (an
RLS gate and SQL-parity checks in CI).

They did not build tests for **failure**, for **the frontend**, or for **outcomes** — and those
three are exactly where the product's defects are concentrated. The correlation is not a
coincidence, and it is the most actionable thing in this document: **add the three missing test
classes and the class of defect they cover stops recurring.**
