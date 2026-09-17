# 08 · Testing and Quality

v1 had roughly 4,900 tests and still shipped fabricated data, dishonest terminal states and
a form-filler that reported success while filling a honeypot. **Test count is not the
metric.** What follows is.

---

## 1. The non-vacuity rule

> **Every test must fail when the defect it claims to catch is re-injected.**

This is the single most important rule in this document.

Before a test is merged, the author performs the re-injection: break the implementation in
the specific way the test exists to catch, run the test, confirm it fails, restore the
implementation. A test that still passes is **deleted**, not kept — it is worse than no
test, because it advertises coverage that does not exist.

Cases that produce vacuous tests, all of which v1 shipped:

| Trap | What happens | Fix |
|---|---|---|
| Asserting on a mock's return value | You tested the mock | Assert on the effect: a database row, an emitted event, a provider call's arguments |
| Testing in an environment where the code path is skipped | jsdom has no layout engine, so `offsetParent` is null and every visibility check "passes" | Stub the environment feature explicitly, and assert the stub is being exercised |
| Asserting a reference value the author derived themselves | Tests your arithmetic, not the transform | Verify by an independent path — two different algorithms converging on the same byte |
| Asserting `status == "ok"` | v1's publish returned `done` having done nothing | Assert the *effect* exists: the post is retrievable at the returned URL |
| Broad `pytest.raises(Exception)` | Passes on an unrelated crash | Assert the exact error type and its machine-branchable reason |

---

## 2. The pyramid

| Level | Count target | Runtime | What belongs here |
|---|---|---|---|
| **Unit** | ~70% | < 60 s total | Pure logic: scoring, parsing, colour transforms, token extraction, anchor distribution, ring geometry. No database, no network, no clock |
| **Integration** | ~25% | < 5 min | Real Postgres, real Redis, fake providers. Repositories, RLS policies, job engine semantics, graph flows, API handlers |
| **Contract** | small | < 2 min | OpenAPI conformance, generated-client freshness, provider response fixtures recorded from real calls |
| **End-to-end** | ~20 scenarios | < 15 min | Playwright through the real UI against the real stack: login, onboard, run an audit, propose and approve a page set, publish a page, record a citation |
| **Eval** | 6 suites | nightly full, cheap tier in CI | AI output quality (see `06-AI-STACK.md` §8) |
| **Chaos** | 8 scenarios | nightly | Kill workers mid-job; prove resume and no double-spend |

---

## 3. What must be tested, specifically

These are not suggestions. Each one maps to a defect class that has already occurred.

| # | Invariant | Test shape |
|---|---|---|
| 1 | **No synthetic data reaches a writing path** | Strip every provider key; exercise every writing caller; assert each returns `degraded` and that nothing was persisted as a value |
| 2 | **Terminal states are honest** | For each publish/submit path: remove the precondition, run it, assert the state is `blocked` with a named reason — never `succeeded` |
| 3 | **RLS holds** | For every tenant table, as client A, attempt read/update/delete of client B's row; assert zero rows and no mutation |
| 4 | **Jobs are idempotent** | Run each job kind twice with the same idempotency key; assert one side effect, one charge, identical result |
| 5 | **Jobs resume** | Kill the worker mid-execution; assert the lease expires, the job is re-picked, and it completes without repeating a confirmed side effect |
| 6 | **Cost gate cannot be bypassed** | For every paid call site, set the dial `off`; assert no provider call occurs and the error is `cost_blocked` |
| 7 | **Three-state measurement** | Inject a provider error for some grid points; assert those points are `error`, that ratios divide by measured only, and that the CHECK constraint rejects a blurred row |
| 8 | **Design token conformance** | Generate a page from a known DesignIR; assert every colour, face, radius and spacing value used exists in that DesignIR |
| 9 | **Elementor editability** | Publish to a real WordPress fixture; parse the stored `_elementor_data`; assert it is a valid widget tree and that each text, heading, image and button is an addressable widget — not one HTML widget |
| 10 | **Honeypot is never filled** | Fixture forms with hidden/decoy fields; assert the fill plan marks them `IGNORE` and the applied plan leaves them empty |
| 11 | **The extension cannot submit** | Assert no code path in the extension dispatches a submit event or clicks a submit control |
| 12 | **SSRF is blocked** | Private ranges, IPv6 forms, redirect-to-private, and DNS rebinding; assert all are refused |
| 13 | **Provenance is present** | Assert every API response field typed as a measurement carries a provenance object, and that the UI component throws without one |
| 14 | **Anchor distribution caps hold** | Generate a campaign; assert exact-match anchors never exceed the configured share |
| 15 | **Migrations apply from zero** | Empty database → full chain → diff against models; assert no drift |

---

## 4. Test data

- **Fixtures, not factories that hide meaning.** A fixture named `client_with_no_wordpress`
  is worth more than `make_client(wp=False)`.
- **Real provider responses, recorded.** Every provider has a fixture set captured from a
  real call, including its failure shapes (429 body, 403 body, malformed success). These
  are the contract tests' inputs.
- **Golden files for renderers.** Audit HTML, report PDF structure, Elementor block trees
  and Gutenberg markup are asserted against committed golden files, reviewed on change.
- **No test may call a live paid provider.** A CI guard fails the build if a test imports a
  real provider client without the fake marker.
- **Seed data is deterministic** — the same seed produces the same database, so a failing
  test reproduces.

---

## 5. Frontend quality

- Component tests with Testing Library; assertions on **what a user sees**, never on
  internal state.
- Every list surface tested for: empty state, loading state, error state, **degraded
  state**, and a page beyond the first.
- Accessibility: `axe` on every route in CI; keyboard navigation for every primary flow;
  colour contrast checked against the token set.
- Visual regression on the design-system primitives and the report renderer only — not on
  every page, which produces noise rather than signal.

---

## 6. Extension quality

- `tsc --noEmit` strict.
- Unit tests for the collector's digest (shape, PII absence), the fill applier, and the
  panel's confidence rendering.
- **jsdom caveat, learned the hard way:** jsdom has no layout engine (`offsetParent` is
  always null) and no `CSS.escape`. Both must be stubbed, and each test must assert the
  stub is exercised — otherwise the visibility matcher measures as crippled and every test
  passes vacuously.
- A fixture corpus of at least 25 real directory forms, including honeypot variants.

---

## 7. Performance testing

- A benchmark suite over the ten hottest endpoints, run on every PR, reporting p50/p95 as
  an advisory check with a hard fail at 2× the documented target.
- A load scenario at 100 clients' worth of data: dashboard load, client list, job list,
  report generation.
- A 50-page fan-out timed end to end, with the concurrency cap at its production value.

---

## 8. Quality gates recap

The seven blocking CI gates are defined in [`02-SDLC.md`](02-SDLC.md) §4. In short:
lint/format · types · unit+integration · migration fresh-apply · RLS · truth · contract+eval.

**No gate may be disabled, skipped with a marker, or weakened to turn a build green.** If a
gate is wrong, it is fixed in its own PR, with its own reasoning, reviewed on its own
merits.

---

## 9. Definition of a good bug fix

1. Write a failing test that reproduces the bug **first**.
2. Fix the cause, not the symptom. If the fix is a special case, the cause is elsewhere.
3. Ask what class the bug belongs to, and test the class — v1's `oklch()` colour-parsing
   bug was one line, but its class was "we never verified the parser against modern CSS
   colour syntax at all", which was ten more bugs.
4. Record it in `KNOWN-LIMITATIONS.md` if any part remains unfixed, with its requirement id.
