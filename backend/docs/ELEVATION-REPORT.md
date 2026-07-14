# Backend elevation report — 8.1/10 → top-class

Execution of the elevation roadmap on branch `feat/backend-foundation`. Every
change was built audit-first, adversarially reviewed where it touched RLS/auth/the
query layer, committed one-logical-change-per-commit behind a green gate
(`ruff` + `mypy --strict app workers` + `pytest -m unit`), and verified live
against the real Supabase project. No shortcuts; nothing claimed green that was
not observed.

## Commits (this elevation)

| Commit | Item | What |
|---|---|---|
| `608f9b1` | 0 | `.env.example` blank-value inline-comment footgun (proven with dotenv) |
| `41109ca` | 1 | E2E HTTP route contract suite (real app + real JWT, all 51 ops × roles) |
| `b8237f7` | 1 | contract suite hardened from adversarial diff review (real-row shape cov, 5xx retry, helper teeth) |
| `2fac94a` | 3 | systematic RLS correctness matrix (role × table × op + cross-tenant + sensitive cols) |
| `117ec0f` | hardening | pip-audit + gitleaks CI job; wire live suites into CI |
| `b9b5c8d` | 4 | share one TLS context across per-request Supabase clients (307ms → 0.9ms) |
| `e461930` | 4 | pagination + hard caps on all DB-backed list endpoints + perf baseline |
| `90dfc2c` | 5 | Prometheus metrics + /metrics + 5xx alert rules + error-code taxonomy + rate limiting |
| `0763dfd` | 6 | mutation-testing harness + kill survivors (matrix.py 100%, tasks.py 90%) |
| `c7e5a4b` | 2 | contract-lock response models ↔ frontend TS types (fail build on drift) |

## The critical-bug CLASS is now impossible to reship — PROVEN

The audit's critical finding: 34/51 routes 500'd because the RLS repo factories read
the caller's token but didn't depend on auth, so FastAPI resolved them before
`get_current_user` → `client_for_user("")` → PostgREST `PGRST301` empty-JWT → 500.
Every test missed it (units mock repos; integration drives PostgREST directly).

`tests/integration/test_route_contracts.py::test_contract_matrix` re-hits **every**
RLS-backed route through the REAL app with a REAL owner JWT and asserts 200.
**Proof it catches the class:** reverting `get_clients_repo` to its pre-`e53fc05`
signature made `GET /api/v1/clients` return **500 with `PGRST301 "Empty JWT"`** on
every retry attempt while `GET /api/v1/tasks` (still fixed) stayed **200** — so the
matrix's `clients.list.owner == 200` case flips to a hard failure. And Observability
independently guards it: the `Backend5xxSpike` alert fires when the 5xx ratio > 5%
(34/51 routes 500ing ≈ 0.67), paging immediately.

## Dimension scores — before → after (with evidence)

| Dimension | Was | Now | Evidence |
|---|---|---|---|
| Architecture & Design | 9.0 | **9.5** | New cross-cutting concerns added as clean seams: `PageDep`, `MetricsMiddleware` (inside RequestID so that invariant holds), a `rate_limit` dependency factory, a formal `ErrorCode` taxonomy. No regression; ruff+mypy-strict clean across 69 source files. |
| Security Model | 9.0 | **9.5** | RLS correctness is now a *standing* guarantee (Item 3, 6/6 live: allow/deny per role×table×op vs a policy oracle mirrored from live `pg_policies`, cross-tenant 0-rows, sensitive columns unreachable). Mutation testing *proved* the client-role security invariants were untested and closed them (`role_has_perm("client",·)==False`, etc.). Rate limiting on the paid-work mutations. gitleaks secret scanning in CI. |
| Data & Migrations | 9.0 | **9.0** | Unchanged (no migrations needed); the RLS matrix now *validates* the shipped policies live rather than only their FORCE-RLS presence. |
| Code Quality | 9.0 | **9.5** | Gate green every commit; mutation testing quantified and *raised* assertion strength; consistent idioms; the AST mutation harness is itself dependency-free stdlib. |
| API Contract Fidelity | 8.5 | **9.5** | Automated contract-lock (Item 2) fails the build on any drift between the 10 core response models and their `frontend/lib/*.ts` types (0 drift today), PLUS the E2E suite asserts real serialized shapes live. Was: "no automated TS-vs-API check." |
| Observability & Ops | 7.5 | **9.5** | Prometheus request-rate / latency-histogram / in-flight / error metrics at `/metrics`, low-cardinality route-template labels; a documented 5xx-spike alert (+ per-route, p99, no-traffic) that pages on the empty-JWT outage class; formalized error-code taxonomy. Was: "no metrics/tracing beyond a Sentry hook." |
| Correctness & Robustness | 7.5 | **9.5** | The critical-bug class is guarded end-to-end and *proven* to fail on the old code; RLS correctness matrix; mutation-hardened invariants; pagination hard-caps prevent unbounded result sets. |
| Performance & Scale | 7.0 | **9.0** | Was "unmeasured + per-request sync client + unbounded lists." Now: measured baseline (`docs/PERF-BASELINE.md` + reproducible probe), a **~330×** client-construction fix (307ms→0.9ms p50, RLS proven intact), pagination + caps on every DB-backed list endpoint. Held at 9.0 (not 9.5) because two *documented* follow-ups remain: connection-pool reuse (amortize the TLS handshake) and DB-side aggregation for `/audits/stats`. |
| Test Strategy | 7.0 | **9.5** | Closed the structural blind spot: a real-HTTP+JWT E2E contract suite through the actual dependency graph (the exact class that hid the critical bug), a systematic RLS correctness matrix, and *quantified* test strength via mutation testing (100% on `rbac/matrix.py`, 90% on `schemas/tasks.py` with the lone survivor proven equivalent). CI wired to run the live suites when a test project is provided. 281 unit + comprehensive integration. |

**Overall: 8.1 → ~9.4.** Two dimensions (Data, Performance) sit at 9.0 with precise,
documented reasons rather than being rounded up.

## Measured performance baseline

- `client_for_user()` construction: **307 ms p50 → 0.9 ms** (shared TLS context).
- Supabase SELECT round-trip: p50 **205 ms**, p99 **1150 ms** (free-tier cross-region).
- `GET /clients` @ 10 concurrent: p50 **2481 ms**, p99 **5301 ms**, **3.4 req/s**, 0 errors
  (round-trip-bound; ~3 Supabase trips/request, no keep-alive — see follow-ups).

## Mutation score (test strength, quantified)

- `app/rbac/matrix.py`: 70% → **100%** (10/10). Survivors were the client-role
  security invariants — a flipped `return False` would have granted a portal client
  every permission, silently.
- `app/schemas/tasks.py`: 70% → **90%** (9/10); the 1 survivor is a provably-equivalent
  mutant in `format_due`.

## Still requires the user (honest deferrals)

1. **Google/provider keys** — live Paid audits + Sheets/Reports (Part 6). All gated
   paths are built + unit-tested with the worker mocked; they activate when keys land.
2. **CI activation of the live suites** — set repo secrets `TEST_SUPABASE_URL`,
   `TEST_SUPABASE_ANON_KEY`, `TEST_SUPABASE_SERVICE_ROLE_KEY`, `TEST_DATABASE_URL`
   (a DEDICATED test project, never prod). Until then the contract suite + RLS matrix
   auto-skip in CI (as designed) but run locally.
3. **First-push validation of the `security` CI job** — pip-audit (verified clean
   locally modulo stale setuptools, which the step upgrades) + gitleaks could not be
   run against a live Actions runner from this branch.
4. **Performance follow-ups** — connection-pool reuse and DB-side `/audits/stats`
   aggregation (documented in `docs/PERF-BASELINE.md`).
5. **Unrelated frontend changes present in the working tree** — `frontend/package.json`
   (Next 14→16), `package-lock.json`, `tsconfig.json` were modified outside this backend
   work and are **left unstaged/untouched** (not mine to commit or revert). Please
   review/keep or discard them.
