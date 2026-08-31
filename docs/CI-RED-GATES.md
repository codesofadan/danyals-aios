# The red CI gates on `main` — what each one is, and what to do about it

**As of `a6446dd`** (the merge of PR #1, 2026-08-31). Written for whoever picks up
the CI work. Everything below was reproduced locally, not read off the CI summary.

## Where things stand

| Job | Result | What it is |
|---|---|---|
| `Docker Build Test` | **pass** | was failing on several commits before `a6446dd` |
| `extension-ci` | **pass** | |
| `db-rls` | **pass** | the RLS role × table × op matrix |
| `backend-ci / lint-test (3.11, 3.12)` | fail | ruff, 24 errors |
| `backend-ci / security` | fail | gitleaks, 10 findings — **all false positives** |
| `backend-ci / integration` | fail | 7 failures + 3 errors, **not one root cause** |
| `frontend-ci` | fail | eslint, 0 errors + 19 warnings |

**None of these was caused by the PR #1 merge.** `security` and `integration` were
already failing on `main` at `ed19df3` and `9ddb87f` (2026-08-29), and the ruff and
eslint findings are in files the merge did not touch.

Nobody has been reading these gates for at least a week. That is the actual problem
to solve — a permanently red gate is one nobody reads, which is how the integration
failures below survived unnoticed.

---

## 1. `integration` — the one that matters

### Reproducing it locally (verified, takes about two minutes)

CI runs against an ephemeral Postgres with every migration applied. Do the same —
**do not point this at a dev database**, the suite writes.

```bash
docker run -d --name aios-ci-repro \
  -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=aios_test \
  -p 55499:5432 postgres:16-alpine

DSN="postgresql://postgres:postgres@127.0.0.1:55499/aios_test"
for f in db/migrations/*.sql; do psql "$DSN" -v ON_ERROR_STOP=1 -q -f "$f"; done   # 116 files
psql "$DSN" -c "alter role authenticated with login password 'ci_authenticated_pw';"
psql "$DSN" -c "alter role service_role  with login password 'ci_service_role_pw';"

cd backend
export DATABASE_URL="postgresql://authenticated:ci_authenticated_pw@127.0.0.1:55499/aios_test"
export DATABASE_ADMIN_URL="postgresql://service_role:ci_service_role_pw@127.0.0.1:55499/aios_test"
export REDIS_URL="redis://localhost:6379/14"
export TRUSTED_HOSTS="*"        # SEE THE TRAP BELOW — this line is load-bearing
pytest -m integration -q
```

Expected: **7 failed, 156 passed, 6 skipped, 3 errors.**

> ### The trap that will cost you an hour
>
> `backend/.env` sets `TRUSTED_HOSTS=app.qanry.com`, and pydantic reads `.env` even
> when you are running tests. CI has no `.env`, so it gets the default `"*"`.
>
> Without `TRUSTED_HOSTS="*"` every HTTP-level test returns **400 `Invalid host
> header`** and you will see **19 failures instead of 7** — twelve of them entirely
> self-inflicted and nothing to do with the code. The httpx `ASGITransport` uses
> `base_url="http://test"`, so the Host header is `test`, which `app.qanry.com` does
> not match. Setting `TRUSTED_HOSTS=testserver` does *not* fix it either.
>
> This is the same gap that makes a locally-started backend reject every request.

### What actually fails, and why

These are **three unrelated causes**, not one. Do not fix them as a batch.

#### (a) Stale seeds vs. the client-visibility gate — CONFIRMED

Migration `0096_audit_client_visibility.sql` added:

```sql
alter table public.audits
  add column if not exists visible_to_client boolean not null default false;
```

and `portal_audits` filters `where client_id = current_client_id() AND visible_to_client`.

The migration is a deliberate disclosure control, and its own header says so: *"an
audit reaches a client only when someone decides it should"*, default FALSE so a new
audit is internal until someone says otherwise. Existing rows were backfilled TRUE on
purpose, to avoid removing reports clients could already open.

The integration tests seed `audits` with **direct SQL that predates the migration** and
never sets the column, so every seeded row is `visible_to_client = false` and the
portal view correctly returns nothing. Measured in the test database after a run:
**21 audits, 0 with `visible_to_client = true`.**

**The product is right and the tests are stale.** This is not a tenant-isolation
defect. `portal_audits` is owned by `postgres` (BYPASSRLS) with `security_barrier`,
so the view — not row-level security — is doing the filtering, and it is filtering
exactly as designed.

Fix: add `visible_to_client` to the seed inserts, `true` for rows a client is expected
to see. There is no shared helper; each file seeds its own:

- `tests/integration/test_portal_isolation.py:111`
- `tests/integration/test_repo_sql_parity.py:138,146`
- `tests/integration/test_rls_matrix.py:150,161`
- `tests/integration/test_route_contracts.py:288,301`

Keep at least one seeded row `false` and assert the client *cannot* see it — otherwise
the fix deletes the coverage that migration 0096 exists to provide.

#### (b) Routes became staff-only, contracts not updated — NEEDS A DECISION

`test_contract_matrix` expects a `client` principal to get `200`:

```
[clients.list.client]  GET /api/v1/clients   → 403 "Staff only"  (expected 200)
[activity.client]      GET /api/v1/activity  → 403 "Staff only"  (expected 200)
```

Someone made these staff-only and did not update the contract matrix. Decide which is
right — if the routes are correctly staff-only, the matrix is simply out of date; if a
client is supposed to reach them, this is a live regression in the portal.

#### (c) A missing `client_id` returns 201 instead of 422 — LOOKS LIKE A REAL DEFECT

```
audits.missing.client_id: expected 422, got 201
{"id":"0b065ee7-...","client":"","url":"http://93.184.216.34","types":[],"tier":"Free","status":"queued"}
```

An audit POST with no `client_id` is **accepted** and creates a row with an empty
client. Of everything in this document this is the one that looks like an actual bug
rather than test debt, and it is worth looking at first.

#### (d) 3 errors in `test_citation_invariants.py` — NOT DIAGNOSED

```
psycopg.errors.InsufficientPrivilege: permission denied to set role "authenticated"
```

The `as_operator` fixture connects as `service_role` and issues `SET ROLE
authenticated`, which requires role membership that the migrations do not appear to
grant. Reproduced locally; **not confirmed to be the same in CI**, and not
investigated further. Either grant the membership in `0000`, or have the fixture log
in as `authenticated` directly the way `rls_connection` does.

---

## 2. `security` — 10 gitleaks findings, all false positives

Verified by running gitleaks 8.21.2 locally, unredacted. **No live credential is
exposed.** Do not rotate anything on account of this job.

- **3 findings** — `frontend/lib/hooks/offpage.ts:392,404`,
  `frontend/lib/hooks/siteAnalytics.ts:81`. The `generic-api-key` rule matching
  `queryKey: WEB2_CAMPAIGNS_KEY` / `GA4_PROPERTIES_KEY`. The "secret" it reports is
  the React Query constant *identifier*, 18 characters of screaming snake case.
- **7 findings** — `aios/app/lib/vault.ts`, a **deleted prototype path** that exists
  only in history. Mock UI fixtures with `masked` display strings and invented sites
  (`northpeakdental.com`, `brighthvac.com`). Provably fake by length: the `AIzaSy…`
  values are 24–25 chars where a real Google key is 39; the Serper value is 28 where a
  real one is 40 hex.

Fix: add an allowlist to `.gitleaks.toml` — a path rule for the historical
`aios/app/lib/vault.ts`, and a regex rule for `queryKey:\s*[A-Z0-9_]+_KEY`. Do not
disable the rule wholesale; it is the one that would catch a real key.

## 3. `lint-test` — 24 ruff errors

Pre-existing in platform source, on `main` before the merge. Mostly trivial (an unused
`MAX_MENU_DEPTH` import, an `N812` lowercase-imported-as-non-lowercase).

Note when comparing numbers: `main` showed **471** before PR #1 and **24** after, but
that is almost entirely the new `extend-exclude = ["seo-content-os"]` for the vendored
doctrine corpus — 447 of the 471 were in that one directory. It is not 447 fixes.

## 4. `frontend-ci` — 19 eslint problems, 0 errors

All 19 are **warnings**; the job fails only because CI treats warnings as fatal. Mostly
`react-hooks/exhaustive-deps` (wrap the initialiser in `useMemo`) plus one
`@typescript-eslint/no-explicit-any`. Four of the six files are untouched by PR #1.

---

## Suggested order

1. **(c)** the `201`-instead-of-`422` audit validation — the only likely real defect.
2. **(b)** decide whether `/clients` and `/activity` are staff-only — a wrong answer
   here is a live portal regression.
3. **(a)** the stale seeds — mechanical, but keep a negative assertion.
4. `.gitleaks.toml` allowlist, then ruff, then eslint — so the gate goes green and
   starts being read again.

## Also worth knowing

- **Running the backend locally** needs `TRUSTED_HOSTS=localhost,127.0.0.1,app.qanry.com`
  plus `DATABASE_URL` / `DATABASE_ADMIN_URL`. Committed config lists only
  `app.qanry.com`, so a backend started from it rejects every localhost request with
  `Invalid host header` — it looks like a broken build and is only a config gap.
- **The frontend vitest suite is timeout-flaky** — 10–20 failures per full run, a
  different set each time. Re-run any failure in isolation before filing it.
- **Do not run `next build` in a working checkout** with dev servers up. `tsconfig.json`
  includes the generated types of four `.next-*` dist dirs and the dev servers rewrite
  them concurrently, so the build fails on a type error that is purely a race. Build
  from a clean worktree.
