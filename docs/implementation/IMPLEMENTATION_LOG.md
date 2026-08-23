# PHASE 3 IMPLEMENTATION LOG

**Started:** 2026-08-23 · **Baseline commit:** `79d1036` · **Branch:** `main`

Governed by `docs/audit/ENGINEERING_MASTER_PLAN.md`, then `TARGET_ARCHITECTURE.md`,
`REQUIREMENTS_TRACEABILITY.md`, `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md`, and the owner
decisions in `DECISIONS_LOG.md`. Existing code is authoritative only where it is correct.

One section per completed working unit: what changed, why, what proves it, what it did not fix.

---

## Conflicts between source documents, and how they were resolved

Recorded rather than silently decided.

| # | Conflict | Resolution |
|---|---|---|
| **C-1** | `TARGET_ARCHITECTURE.md §4` says **"Renumber the colliding migrations"** (two `0070`, two `0072`). `ENGINEERING_MASTER_PLAN.md §7` and `§18` say **"Do not renumber applied files — the ledger keys on filename"**. | **Master plan wins** (priority 1 over priority 2). No applied migration is renamed. The collision is addressed by a CI ordinal-uniqueness check for *new* migrations only. Renaming an applied file would make the `deploy.schema_migrations` ledger re-apply it. |
| **C-2** | Master plan lists **"Free-audit shape"** as an open decision. `DECISIONS_LOG.md` D-1 already fixes the v1 scope baseline as **"Audit — Free (condensed, ~10–15 pages, public lead magnet) and Paid (type-selectable, full multi-agent + narrative)."** | **D-1 wins** (an explicit owner decision, priority 5, is more specific than the plan's open item). Free = condensed = genuinely free. This is also the plan's own recommendation. |
| **C-3** | Master plan §9 says to **delete** `lib/store.tsx`, the `lib/data.ts` seed arrays, `lib/vault.ts` mock keys and `lib/cost.ts` prices, describing them as "verified unreferenced". Only `store.tsx` and the seed arrays are unreferenced; `vault.ts` and `cost.ts` also export **live types and display metadata** used across 20+ components. | Deleted **surgically**: the fabricated data (seeds, mock keys, prices) is gone; the types and presentational metadata that the live screens depend on are kept. Deleting the whole modules would have broken the build. |

---

## WU-1 · P0-1 — Run the backend suite and record the result  ✅

**Workstream:** WS-9 · **Requirement:** the plan's first P0, and the precondition for every other claim.

The Phase-2 audit never executed the suite (Python 3.14 only; the dependency set does not resolve
on it), so all 219 backend test files were of unknown state. `uv` is present on this machine and
resolves that: `uv venv --python 3.12` gives the same interpreter the Docker image builds on.

**Result and full analysis:** `docs/implementation/TEST_BASELINE.md`.

| | |
|---|---|
| Baseline | **4,857 passed · 12 failed · 4 skipped · 1 collection error** (630 s on 8 workers) |
| Of which self-inflicted | 2 (this session's own frontend edits; fixed in the same unit) |
| **True pre-existing** | **10 failed + 1 collection error** |

**The single most useful finding:** **nine of the ten failures are the beat schedule.** The
repository's own tests — across `billing`, `local_seo`, `rank_tracker`, `context` and the
`scheduled_jobs` operator surface — already assert that `celery_app.conf.beat_schedule` is
populated. They were left red when cron was switched off on 2026-08-19 rather than updated.

Consequences the plan should absorb:

- **`P0-5` (staged beat restore) has a ready-made acceptance suite.** Nine tests turn green exactly
  when the schedule is correct, covering `AUTO-001` from four modules plus the operator surface.
- **The backend CI job has been red on `main` since 2026-08-19.**

**Fixed in this unit (test-only; no product code):**

1. `tests/test_public_endpoints.py` imported `fastapi.dependencies.utils.get_flat_dependant`, a
   **private** FastAPI helper **removed in 0.141**. The module failed to import, so **nine tests
   covering the unauthenticated public funnel's auth posture, SSRF rejection and report-token
   curation never ran at all.** Replaced with a local, cycle-safe walk of the dependency tree.
2. `tests/test_elementor.py` asserted the literal substring `"<h1>"` in the publish body. The
   Gutenberg emitter attributes its headings (`<h1 class="wp-block-heading">`), so the assertion
   was pinned to a formatting detail rather than the SEO property it meant to protect. Now matches
   an `<h1>` **element**. **The product was correct; the test was stale.**

**New risks raised:** `R-B1` the backend build is not reproducible (no lock file — this is the root
cause of finding 1 above), `R-B2` the suite takes >3 h serially so nobody runs it, `R-B3`
contract-lock tests depend on frontend TS files with no signal on the frontend side. All three are
recorded with proposed remedies in `TEST_BASELINE.md`; none is fixed yet.

---

## WU-2 · WS-1 (Truth) — remove every false signal from the dashboard  ✅

**Requirements:** `ADM-003` (no dead controls), `ADM-025` (every number traced to a live source),
Definition-of-Done **Gate 2 · Truth**. **Plan items:** §9 frontend deletions, §6 P0-9 branding,
P0-10 exposed client data.

### 2.1 · The client-side demo store

`lib/store.tsx` (360 lines) was a localStorage-backed parallel source of truth seeded from
`lib/data.ts`, mounted around every portal in `app/layout.tsx`. **Deleted**, and
`AiosStoreProvider` unmounted. Verified unreferenced beyond that mount.

*Why it mattered:* while mounted, a screen could render convincing data with the API completely
down. That is the exact failure mode `ADM-003` exists to prevent.

### 2.2 · Fabricated business data

| Deleted | What it was |
|---|---|
| `clientDirectory` | **Eight fake clients carrying plaintext portal passwords** shipped in the browser bundle (one was a real demo-client portal login; redacted here and rotated under D-15) |
| `teamMembers` | Eight fake staff with fabricated on-time / utilisation / quality percentages |
| `tasks_seed`, `activity_seed` | A fake task board and activity feed |
| `teamCredentials` | **Eight plaintext staff passwords**, keyed by member id |
| `operatorProfile` | A named operator with a real-shaped phone number |
| `clientReportGrants`, `memberGrants` | Per-client / per-member grants keyed to the fake ids |
| `securityDefaults`, `workspaceDefaults`, `notificationDefaults` | Settings values presented as the platform's, sourced from nothing |
| `audits`, `traffic`, `team`, `clients` | Four demo chart series |
| `vaultKeys` (`lib/vault.ts`) | **Twelve realistic fake secrets** — `sk-ant-api03-…`, `AIzaSy…`, WordPress application passwords |
| KPI values + table rows in `lib/tools.ts` `EXTRAS` | A fabricated `MRR $28.4k`, named clients with invoice amounts, named staff with task counts |

**`SecurityPolicy` and `WorkspaceSettingsData` were restored after deletion**: they are the
frontend half of a locked contract (`test_contract_lock.py` pins backend response models to them).
Only the fabricated *default values* were removed; the *types* are contract and stay. This is
recorded as risk `R-B3` — a frontend deletion can break a backend test with no local signal.

The `lib/tools.ts` values were already zeroed at render time, so they never reached a screen — but
they still shipped inside the client bundle. The **KPI labels were kept**: the backend workspace
adapters are pinned to them by `test_tool_workspace_contract.py` (156 tests), so the labels are
contract while the values were invention. `ToolKpi.value` is now optional and arrives only from
`GET /<slug>/workspace`.

### 2.3 · Fabricated unit prices — and a real replacement

`lib/cost.ts` shipped hardcoded provider prices. Measured against what the cost gate actually bills:

| Shown in the UI | Actually billed (`Settings` + `app/services/pricing.py`) | Error |
|---|---|---|
| `$0.30 / search` (Serper) | `$0.001 / query` | **~300×** |
| `$0.75 / task` (DataForSEO) | `$0.0006 / call` | **~1,250×** |
| `$0.17 / lookup` (Places) | `$0.005 / call` | ~34× |
| `~$0.02 / 1k tok` (Voyage) | `$0.06 / MTok` = `$0.00006 / 1k tok` | ~333× |
| `~$0.90 / page` (Anthropic) | billed per token, per model tier | not a per-page quantity at all |
| `~$1.50 / run` (audit engine) | derived at runtime from the run's own observables | no flat price exists |

A price written in the frontend also cannot track an env change, so it is wrong again the moment a
provider re-prices.

**Replaced with `GET /cost/pricing`** (`app/schemas/cost.py::provider_pricing`), which reads the
same `Settings` fields `pricing.py` computes committed spend from. Anthropic is served as six lines
(three tiers × input/output) plus web search, because that is genuinely how it bills — collapsing
it to one "per page" figure is what produced the fabricated number. Free-tier providers are stated
as free rather than left blank. The Cost Dial renders the live figure; while it loads, it shows
**no** price rather than a placeholder.

Also removed: the `~$0.90/pg` price baked into the backend's own **dial note** string, with a test
asserting no dial note quotes a price.

### 2.4 · A frozen clock behind every urgency label

`dueInfo()` compared every task due date to a hardcoded `PORTAL_TODAY = { m: 6, d: 10 }` —
**10 July 2026**. Every "Due today", "Due in 2d" and "*N*d overdue" label across six team-portal
components was computed against a fake date, and drifts further from the truth every day.

Rewritten to measure from the real current date, with whole-day deltas from local midnight. It
accepts an ISO date and also the legacy year-less `"Jul 12"` the API currently serves, inferring
the nearest year — so a December task read in January reads as three weeks late, not eleven months
early. An unparseable value now renders verbatim and sorts last instead of silently becoming
"99 days out".

**Not fixed here:** the API serves `due` as a **year-less display string** (`format_due` →
`"%b %d"`), so the frontend is inferring a year that the server already knows. The correct fix is
an additive ISO `dueDate` field on `TaskResponse`. Carried as a known limitation.

### 2.5 · P0-9 — the builder's name, and P0-10 — real client data

The hard rule (`context/PRODUCT-OVERHAUL-BACKLOG.md`, restated in the plan's platform-wide
Definition of Done) is that the builder's name appears nowhere in the running software, its
configuration, its tests, or its output. It had reached end clients on **two** surfaces:

- **The WordPress plugin header** — listed in every end client's wp-admin Plugins screen. `Author`
  is now the product; `Plugin URI` / `Author URI` are removed rather than replaced with an invented
  URL. `Contributors:` is dropped from `readme.txt` — it is a wordpress.org username field and the
  plugin is distributed privately, so no valid value exists and inventing a handle would be a
  second untruth.
- **The outbound email footer** — on every notification the platform sends a client.

Also cleared from `pyproject.toml` (ships in the built wheel), the test suite, and the READMEs.
**Deliberately not touched:** `docs/` and `context/`. Those are the project's own historical record
— including the backlog entry that *states* this rule. Rewriting history to satisfy a lint is
dishonest, not compliant.

**P0-10:** `tools/finish_citation.py` hardcoded one client's full NAP — a real street address and a
real phone number — in version control. Two defects at once: personal contact data committed to
the repo, and a per-client hardcode in a script meant for every client, which would stamp the
**wrong** business onto another client's directory listings — precisely the NAP inconsistency a
citation campaign exists to remove. The NAP now comes from the handoff export, and the script
**refuses to run** on an incomplete one rather than guessing.

### 2.6 · Mechanical enforcement — the part that makes it stick

The audit's diagnosis was that dead demo data kept reaching the client because **nothing enforced
its absence**. Deleting it once does not keep it deleted. Two new guard suites:

**`tests/test_frontend_truth_guard.py`** (14 tests) — no price literal anywhere in the frontend; no
credential-shaped literal in the bundle (Anthropic / Google / OAuth / OpenAI / AWS key shapes,
private-key blocks, literal passwords); the demo store stays deleted; urgency is not computed
against a frozen clock; nine named seed arrays cannot be re-exported.

**`tests/test_builder_branding.py`** (7 tests) — the builder's name is absent from everything that
ships (backend, frontend, plugin, infra, tooling, DB, CI); the plugin header names the product and
is not blank; the email footer still exists and is clean; the citation script carries no
phone-shaped literal and no hardcoded NAP; the credential-bearing handoff export is not committed.

Both suites **guard themselves** — each asserts that its file sweep is non-empty and covers the two
surfaces that actually reached clients, so a wrong root cannot make the rules vacuously pass.

**Both were proven non-vacuous by reintroducing the defect:** restoring the builder's name to the
email footer failed 2 tests; restoring `"$0.30 / search"` to `lib/cost.ts` failed 1. Reverted, green.

### 2.7 · Frontend CI (P0, WS-9)

`.github/workflows/frontend-ci.yml`: `npm ci` → `tsc --noEmit` → `next build`, blocking, on any
`frontend/**` change. Both steps already passed, so this costs nothing and locks in the current
health. The build is not a duplicate of the typecheck — it catches a bad `next.config.mjs`, a
server/client boundary violation, a missing font, a prerender crash. Environment is left at
production defaults so CI builds the same artefact the Dockerfile does.

### 2.8 · Verification

| Check | Result |
|---|---|
| `ruff check .` | **All checks passed** |
| `mypy app workers` (strict) | **Success — no issues in 267 source files** |
| `tsc --noEmit` | **clean** |
| `next build` | **clean** — 103 kB shared, all routes prerendered |
| `test_contract_lock.py` | 71 passed |
| `test_tool_workspace_contract.py` | 156 passed |
| `test_cost_endpoints.py` (incl. 5 new pricing tests) | 13 passed |
| Guard suites | 21 passed, both proven non-vacuous |

### 2.9 · What WS-1 did **not** fix

- **`P0-2` — the free-audit cost hole is still open.** `build_argv` still upgrades the public
  funnel's `--mode free` to `--mode auto` with `--serper --places --citations` on, and
  `execute_public_audit` still commits a hardcoded `0.0`. Next working unit.
- **`P0-4` — the publish cascade still fakes success.** `_publish_artifact(degraded=True)` writes
  `status="done"`.
- The task `due` wire format is still year-less (see 2.4).
- `lib/tiers.ts` still carries a local price catalogue. Unlike the deleted values it is *product
  catalogue* (a plan's list price), not a measured business metric, and the backend has no tier-price
  source to read from. Left in place deliberately; flagged for the owner.

---

## WU-3 · P0-2 — the free-audit cost hole  ✅

**Workstream:** WS-1 · **Requirements:** `AUD-001`, `AUD-002`, `MT-005`, `ADM-026` · **Decision:** D-1

### 3.1 · What was wrong

`POST /public/audits` is the platform's **only** unauthenticated route that causes real work. Four
things compounded:

1. **The engine ran with paid providers on.** `run_audit` resolved `tier="free"` to `mode="free"`,
   and then `build_argv` **silently upgraded it** to `--mode auto` with
   `--psi --serper --places --citations` and `--profile local` (which is what unlocks Places and
   citation discovery). The caller asked for free and got paid.
2. **The ledger recorded `0.0`.** `execute_public_audit` committed a **hardcoded** zero, so the
   spend from (1) was invisible in the cost log, the budget rollups and every dashboard number.
3. **The gate never saw it.** `PublicAuditStore.evaluate` returned an unconditional `call` — the
   one path in the system that could reach a provider without passing the cost gate. The
   agency-global spend halt did not reach it.
4. **The limiter failed open.** A Redis outage silently removed the only abuse control.

Together: **denial of wallet, from the internet, with no ledger entry to notice it by.**

### 3.2 · What changed

**The funnel is now condensed and genuinely free** (D-1: "Free — condensed, ~10–15 pages, public
lead magnet"). `build_argv`'s public branch emits `--mode free`, which the engine enforces by
hard-clearing `psi/moz/serper/places/citations` after parsing — an **engine-side** guarantee, not a
caller-side intention, so no flag added later can reintroduce spend on this path. The paid flags
are *also* passed explicitly off, so the intent is readable in the command line an operator sees.

**`build_argv` now honours its `mode` argument** instead of overriding it. Hardcoding `"free"`
would have been the same bug mirrored — a caller asking for `paid` silently downgraded. The light
path is public-only today; the function stays a faithful function of its arguments regardless.

**Crawl breadth is a separate knob.** `audit_free_max_pages` (15) is deliberately *not*
`audit_max_pages` (100), so tuning the paid audit's depth can never silently widen an
unauthenticated, unbilled crawl.

**The committed cost is derived, never asserted.** The worker now runs the same
`pricing.audit_cost` the paid path uses, over the engine's own `run.json` observables. A free run
logs `0.0` **because the run reported `mode="free"`** — and if this path is ever re-widened, the
ledger becomes truthful automatically. When the engine reports no mode at all (an older build, or a
run that died before writing `run.json`) the cost falls back to the mode we *invoked* it with,
rather than to the derived 21-agent paid estimate — charging a `--mode free` run for a fan-out it
cannot perform would be a fabricated cost in the other direction. **A non-zero cost on this path
logs a warning**, because that is exactly the condition that went unnoticed before.

**The funnel is gated, on its own dial.** A new `public_audit` dial feature is registered in
`DIAL_FEATURES` (registration is mandatory — an unregistered key resolves to `off` *and* is
rejected by `PATCH /cost/dials`, i.e. unswitchable-on). It is deliberately **not** the paid audit's
`tech_audit`: an operator must be able to switch the lead magnet off during an abuse episode
without disabling the paid product every client is paying for. The gate is consulted both in the
request path (before a row is created) and in the worker (before the engine is launched), so the
spend halt reaches the funnel like everything else.

**Two failing-closed controls.** The per-IP limiter gained an opt-in `fail_closed` posture, used
here and nowhere else — `auth_login` deliberately stays fail-open, because failing closed there
would turn a cache blip into a total lockout. And a new agency-wide **daily cap**
(`public_audit_daily_cap`, default 200) counted from Postgres: per-IP limiting bounds one abuser,
the daily cap bounds a distributed one. Both refuse when they cannot be evaluated. All refusals
return one uniform 503 that never reveals which control fired or where the ceiling sits.

**The request-path `$0` cost row is gone.** It asserted a cost before any work existed and
duplicated the worker's commit. The worker now writes exactly one ledger row per run.

### 3.3 · A defect found on the way

The error envelope (`_error_response`) rebuilt the response headers from scratch, **discarding
`exc.headers`**. Two live consequences, neither previously noticed:

- Every **401** the platform emitted was missing `WWW-Authenticate`, which **RFC 9110 §11.6.1
  requires**, despite `get_current_user` setting it correctly at the raise site.
- Every **429** from the rate limiter was missing `Retry-After`, so a throttled client had nothing
  to back off on — the retry storm the limiter exists to prevent.

Fixed by forwarding the raiser's headers, with `X-Request-ID` always winning so a raiser cannot
hijack the request's correlation id. Tested both ways.

### 3.4 · Evidence

| Check | Result |
|---|---|
| `ruff check .` · `mypy app workers` | clean · 267 files |
| `tests/test_public_endpoints.py` | 15 passed — incl. 7 new: closed dial, gate failure, daily cap, uncountable cap, `cap=0` means no ceiling, fail-closed limiter, own-dial |
| `tests/test_public_audit_task.py` | 13 passed — incl. 6 new: gate consulted before launch, spend halt blocks, off dial blocks, derived $0, **real cost recorded when the run did paid work**, no-mode fallback |
| `tests/test_audit_engine_adapter.py` | rewritten — the old test **asserted the defect** (it required `--mode auto` with providers on) |
| `tests/test_ratelimit.py` | +4: fail-closed opt-in, login stays fail-open, `Retry-After` present |
| `tests/test_health.py` | +2: `WWW-Authenticate` survives, raiser headers preserved, request-id not hijackable |

### 3.5 · Not fixed

- The engine's `--mode free` help text promises "free PSI (rate-limited)" but its code sets
  `psi = False`. PageSpeed is genuinely free-tier, so a condensed free audit *could* carry Core Web
  Vitals. **Not changed:** the audit engine is a separate product with its own CI, explicitly
  outside the recovery's change scope (`TARGET_ARCHITECTURE.md §15`). Recorded for the owner.

---

## WU-4 · The integration suite — first run, and a CI misconfiguration  ✅

**Workstream:** WS-9 · Not a planned item. It surfaced because Docker was available, so the suite
the Phase-2 audit could not run became runnable.

### 4.1 · Standing it up

PostgreSQL 17 + Redis 7 in throwaway containers; all **79 migrations applied cleanly in order** to
an empty database; **76 base tables, every one `ENABLE` + `FORCE` row-level security** (`rls_check`
green). The engine-, provider- and mail-dependent suites auto-skip.

*Caveat, stated plainly:* production targets **PostgreSQL 16**; this ran on **17.11** because the
16 image would not pull in time. Migration and RLS semantics are identical across the two, but this
is a proxy, not a production-version verification.

### 4.2 · The finding

The first run gave **12 failures**, eleven of them tenant-isolation assertions: a client identity
could read `clients`, `audits`, `activity_log`, `client_budgets`. Taken at face value that is a
catastrophic security regression.

It is not. `rls_connection` **does not issue a `SET ROLE`** — its pool applies row-level security
because it **logs in as the `authenticated` role** (stated explicitly in `app/db/database.py`'s
module contract). Pointed at a superuser DSN it silently becomes a BYPASSRLS connection.

**`.github/workflows/backend-ci.yml` pointed both DSNs at the `postgres` superuser**, under a
comment asserting that "the RLS pool SETs ROLE authenticated per request" — which the code has
never done.

Repointed at the real roles, **the same suite is green: 72 passed, 5 skipped.** The RLS design is
sound and the audit's claim about it holds. What has never held is CI's ability to demonstrate it.

**So the `integration` job has been red on `main`, alongside `lint-test` (nine beat-schedule
failures, see WU-1). Both of CI's substantive jobs were failing, and the eleven that failed were
precisely the tenant-isolation proofs.**

### 4.3 · The fix

`backend-ci.yml`: migrations now apply over a separate `MIGRATION_DSN` (superuser — it must create
roles and schemas), a step gives `authenticated` and `service_role` their login passwords, and the
two app DSNs name those roles.

Plus **a guard on the guard**, because this failure mode is invisible by construction — a BYPASSRLS
connection makes every isolation assertion pass *vacuously*:

```
bypass=$(psql "$DATABASE_URL" -tAc "select rolbypassrls from pg_roles where rolname = current_user")
if [ "$bypass" != "f" ]; then exit 1; fi
```

Verified both ways locally: passes as `authenticated`, fails as `postgres`.

### 4.4 · The twelfth failure — a stale contract, and a stale docstring

`test_route_contracts.py` expected `POST /clients/{id}/portal-users` to return **403** for an admin.
It returned **422**, because the test's "valid" body was **missing the required `username` field** —
so the case asserted neither the permission nor the shape, and had been masked by a validation
error for as long as both defects coexisted.

The endpoint is intentionally gated by `manage_clients`, not owner, so the wizard's final step
cannot 403 for the admin who was just allowed to create the client. The expectation was stale, not
the code. The case now sends a valid body and asserts **201 + `MemberResponse`**, and a **new
negative case** pins the boundary that actually matters: a `specialist` (no `manage_clients`) gets
403. `PortalUserRequest`'s docstring, which still said "owner-only", was corrected.

### 4.5 · Standing state

| Suite | Result |
|---|---|
| Integration (`-m integration`) | **72 passed · 5 skipped** (live-provider suites auto-skip) |
| `rls_check` | **76 tables, all FORCE RLS** |
| Migrations | **79 applied in order, clean, on an empty database** |

---

## WU-5 · WS-3 (Identity & Security) — P0-6, P0-7, P0-8  ✅

**Requirements:** offboarding (a gap the audit found **missing from the requirements
themselves**, not merely unbuilt), `SEC-011`, `SEC-016`.

### 5.1 · P0-6 — a person can now be removed

`user_status` carried only `active` / `away` / `invited` / `offline` — four **presence**
states, not one **access** state. `login()` never read status. `get_current_user` read it into
`CurrentUser` and then ignored it. So a departing team member kept full access to every client's
data until their token expired on its own, while `manage_team` advertised the capability in the UI.

Two additive migrations (`0078`, `0079` — split because PostgreSQL forbids *using* a
freshly-added enum label in the transaction that adds it, the same reason `0009` stands alone):
`suspended` joins the enum, and `users` gains `suspended_at` / `suspended_by` /
`suspended_reason` so an offboarding can be reconstructed later. **Both applied cleanly to a real
database.**

Suspension, not deletion: `tasks.assignee_id`, `activity_log.actor_id` and every audit trail
reference the user id. Deleting the row would cascade away history or break those references.

**Enforcement is at Postgres, on every authenticated request** — deliberately, not at login.
Refusing only at login would leave an already-issued token working for days. The check sits in
`get_current_user`, so it holds with Redis down and cannot be defeated by a stale cache. Login
refuses too, but **only after the password verifies**: checking before would turn the endpoint into
an oracle for which accounts exist and which are closed.

`POST /admin/users/{id}/suspend` · `/reactivate`, gated by `manage_team`, with three interlocks
that are **not** permission checks but prevent authorised-yet-catastrophic actions:

| Interlock | Why |
|---|---|
| No self-suspension | The operator would revoke their own session mid-request with no way back. A person leaving is offboarded *by* someone |
| Owner-only to suspend an owner/admin | The mirror of the existing provisioning escalation guard — if an admin cannot *create* an admin, an admin must not be able to *remove* one |
| Cannot suspend the last owner | Owner is the only role that can restore an owner. This would leave the platform permanently ownerless with no in-product recovery |

Suspend is idempotent (a retry after a timeout is a no-op, not an error), and the DB flip happens
**before** the Redis revocation so a cache failure can never leave a suspension half-applied.

### 5.2 · P0-7 — the token is no longer irrevocable

Tokens are stateless EdDSA JWTs with a multi-day life and no server-side session — which is why
nothing could stop one. Signing out cleared `localStorage` and left the token perfectly valid for
anyone who had copied it; changing a password did not close the sessions the old password opened.

`app/services/token_denylist.py` adds **two mechanisms, deliberately different**:

- **Per-token (`jti`)** — revokes one session. This is sign-out: the person keeps their account and
  their other devices.
- **Per-user epoch** — revokes every token issued at or before an instant, in **one write**, with
  no server-side session table. This is what suspension and password rotation need.

Every access token now carries a random `jti` (random, not derived — a derived one would collide
across simultaneous logins and let one sign-out kill another session) and `iat`. Every denylist key
carries a TTL, so the list cannot grow without bound.

**Wired into three places:** `POST /auth/logout` (new, revokes *this* token), suspension, and
password rotation — the last of which previously accomplished nothing against an attacker holding
a live token. The frontend's `logout()` now calls the server before clearing locally, fire-and-forget
so a network failure cannot trap someone in a session they are trying to leave.

**This layer fails open, and that is a decision, not an oversight.** The Postgres suspension check
is the boundary; failing closed here would mean a cache blip logs out every user of the platform.
Every result is reported **honestly** — `SuspensionResponse.tokensRevoked` and
`LogoutResponse.revoked` are `false` when Redis was unreachable, rather than claiming a revocation
that did not happen.

**A bug in this work was caught by its own test.** The revocation epoch was first written as
`now - 1`, which meant a token minted in the *same second* as a suspension **survived it** — the
unsafe direction. `test_a_token_issued_in_the_same_second_is_still_revoked` pins the corrected
behaviour, and the reasoning is recorded at both the implementation and the test.

### 5.3 · P0-8 — an application CSP

The app had none. That matters more here than usual because the multi-day bearer token lives in
`localStorage`, so any script running on the origin can read it and use it from anywhere.

Emitted by **Next.js itself** (`next.config.mjs`), not only at the edge, so the policy travels with
the app in every deployment topology instead of depending on one reverse proxy being configured
right. What it buys, stated honestly:

- **`connect-src 'self'`** — the important one. Injected script may read the token but cannot post
  it to an attacker-controlled host.
- `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'`, `form-action 'self'`.

**What it does not buy:** `script-src` keeps `'unsafe-inline'`, because Next.js injects inline
bootstrap scripts and removing it needs nonce-based middleware, which forces every route dynamic and
gives up the fully-static build this app produces. `img-src` allows `https:` because the product
genuinely renders images from arbitrary client sites. So this policy mitigates **exfiltration, not
injection** — recorded as a deliberate trade rather than left to look like a complete control.

The **API origin** gets a much stricter policy in the Caddyfile (`default-src 'none'`), set with
Caddy's `?` set-only-if-absent prefix so the audit report route's own narrower policy still applies.

**A mistake caught before it shipped:** the first version added an API-style `default-src 'none'`
to `infra/deploy/nginx.conf` too. That file fronts **`app.qanry.com` — the dashboard**, not the
API, and nginx's `add_header` *appends* rather than replaces, so browsers would have enforced the
**intersection** of the two policies and stripped the dashboard's own scripts, styles and fonts.
The file now carries an explicit comment explaining why no CSP belongs there.

### 5.4 · Evidence

| Check | Result |
|---|---|
| `ruff check .` · `mypy app workers` | clean · 268 files |
| `tsc --noEmit` · `next build` | clean · 103 kB shared |
| Migrations `0078`, `0079` | applied cleanly to a real PostgreSQL |
| `tests/test_offboarding.py` (new, 13) | jti revocation, session isolation, TTL bounds, the same-second boundary, per-user epoch, cross-user isolation, fail-open posture, honest failure reporting, unique `jti` per login, **and the Postgres refusal proven against `suspended` while `away`/`offline`/`invited` still work** |
| `test_route_auth_guard`, `test_contract_lock`, `test_team_members` | 81 passed |

---

## WU-6 · P0-11 — the QA gate was already advisory; the docs said otherwise  ✅

**Requirement:** `CONT-029`, D-4.

The plan lists "QA gate → advisory until calibrated" as a P0, on the audit's finding that *"a hard
publish gate rests on a self-declared uncalibrated score"*. **That finding is stale.**
`publish_content_job` already treats QA as advisory, and `PublishBlocked` is **raised nowhere in
the codebase** — it is an unreachable control signal.

What was genuinely wrong was the documentation. Three docstrings asserted that publish *"re-checks
the QA hard gate"* and *"BLOCKS a sub-threshold draft"*. An engineer reading them would reasonably
believe an automated quality gate stood between a bad draft and a client's live site. Nothing does.
Corrected, with the reason recorded at the check site.

`PublishBlocked` and its two catch sites are **kept, not deleted**: they are the seam a calibrated
gate (D-4) re-enables through, and the `acks_late` reasoning behind catching rather than re-raising
is still correct and worth not re-deriving. They are now labelled as currently unreachable.

**Still open, and named in the code:** D-4 asks for "advisory **+ mandatory acknowledgement**".
Only the advisory half exists — the verdict goes to the server log, and the lead approving the
draft is never shown it. Closing that needs a decision on the acknowledgement's shape, so it is
recorded rather than guessed at.

---

## Standing state at the end of this session

| Gate | Result |
|---|---|
| **Unit suite** | **4,928 passed · 9 failed · 4 skipped · 0 collection errors** |
| The 9 failures | All `beat_schedule = {}`. They are P0-5's acceptance suite and are deliberately left red — see `KNOWN_LIMITATIONS.md §2` |
| **Integration suite** | **72 passed · 5 skipped** (live-provider suites auto-skip) |
| **RLS gate** | **76 tables, all `ENABLE` + `FORCE`**, verified against a real database |
| **Migrations** | **81 applied in order, clean, to an empty database** (79 existing + 2 new) |
| `ruff check .` | clean |
| `mypy app workers` (strict) | clean · 268 files |
| `tsc --noEmit` · `next build` | clean · 103 kB shared |

**Baseline comparison:** the session began at 4,857 passed / 10 pre-existing failures / 1 collection
error, with the integration suite never having been run. It ends at 4,928 passed / 9 failures / 0
collection errors, with the integration suite green and the RLS boundary actually demonstrated.

**Net new test coverage:** 5 new files / ~60 new tests, of which the two guard suites were
**proven non-vacuous by reintroducing the defect they forbid** and watching them fail.

### Working units completed

| Unit | Plan item(s) |
|---|---|
| WU-1 | P0-1 — run the suite, record the baseline |
| WU-2 | WS-1 Truth (frontend), P0-9 branding, P0-10 exposed client data, frontend CI |
| WU-3 | P0-2 — the free-audit cost hole |
| WU-4 | The integration suite's first run, and the CI misconfiguration it exposed |
| WU-5 | P0-6 offboarding, P0-7 token revocation, P0-8 application CSP |
| WU-6 | P0-11 — stale finding; corrected the documentation it rested on |

### Not started, with reasons

See `KNOWN_LIMITATIONS.md §1`. In short: **P0-3** (job contract) is the critical path and the
largest remaining unit; **P0-4** (stop faking success) is analysed but needs an enum migration, a
trigger change and a frontend render change; **P0-5** is blocked on P0-3 by the plan's own ordering
rule; **P0-12** and **P0-14** are owner decisions; **P0-13** needs infrastructure this environment
does not have.

---

## WU-7 · P0-0 — synthetic providers could reach production and fabricate client data  ✅

**Workstream:** WS-1 (Truth) · **Requirement:** the highest-severity defect found in this
recovery. Not tracked as a numbered P0 by the master plan, which is itself notable — the
plan catalogued *dead* controls and *fake* dashboard tiles, but not the code path that
manufactured plausible data and then persisted or published it.

### The defect

Five production factories degraded to a `Fake*` provider when their vendor key was
absent, and no caller could tell. In every case the fake is deterministic and
plausible — derived from a hash of the input — which is precisely what made it
dangerous: the output is indistinguishable from a measurement once stored.

| Path | What a keyless deploy produced |
|---|---|
| `integrations/content_providers.py` | `FakeSerpResearcher` synthesises competitors from a SHA-256 of the keyword (`https://example.test/<hex>`, template snippets). The pipeline drafted a "SERP-grounded" article from it **and published it to the client's live WordPress site.** |
| `app/modules/rank_tracker/provider.py` | `FakeRankProvider` positions **written to the ranking ledger** and charted to the client as measured performance. |
| `app/modules/local_seo/provider.py` | `FakeLocalPackProvider` positions **written to `local_rankings`** as real map-pack history. |
| `integrations/keyword_data.py` | `FakeKeywordDataProvider` hashes a seed into plausible volume/difficulty/intent, **saved to the keyword bank** as the basis of a content strategy. |
| `app/modules/competitor_intel/tasks.py` | `serp_source_from_settings` returned `(provider, live)`; `discover_competitors` **discarded the flag** (`_live`) and wrote hash-derived domains into the client's competitor set. |

The root cause is a missing signal, not a missing key: the `SerpResearcher`,
`RankProvider`, `LocalPackProvider` and `KeywordDataProvider` protocols carry no
liveness property, so "degraded" was expressible only as a log line the caller ignored.

### What changed

The fakes stay — they are what keeps these modules unit-testable with no network and no
keys. What changed is that **no writing or publishing caller can reach one.**

- `content_providers_from_settings` now treats `SERPER_API_KEY` as a **gate, not an
  enrichment**: absent → the whole bundle degrades to `None`, exactly as a missing writer
  key already did, and the worker holds the job at `drafting` via the existing
  `_hold_degraded` path. Both key checks were also moved **before** any construction —
  previously the Anthropic client was built first, so a deploy merely missing the `[ai]`
  extra crashed instead of degrading.
- New explicit liveness helpers `local_pack_provider_is_live` and `keyword_data_is_live`,
  alongside the existing `rank_pricing_from_settings(...).live`.
- `check_keyword_rank`, `dispatch_rank_checks`, `refresh_local_ranks`,
  `research_keywords` and `discover_competitors` refuse and return `state="degraded"`
  rather than persisting. `dispatch_rank_checks` refuses **before claiming** — claiming
  marks rows checked for the day, so a degraded fan-out would have burned the nightly
  slot as well as filling the ledger.
- Every gate sits **inside** the task's existing never-re-raise guard. A first pass put
  them outside it and broke that invariant (`task_acks_late` would redeliver → double
  spend); `test_the_discovery_task_never_re_raises` caught it.
- Images deliberately keep their fake: the worker injects only a real hosted image and
  skips a fake or empty one, so a missing image key is a visible absence, not fabricated
  evidence. The WordPress fake also stays as the bundle default because per-site
  credentials live in the vault and the service layer builds the real publisher per
  publish.

### What proves it

`backend/tests/test_no_synthetic_providers_in_production.py` — an **auto-discovering**
guard in the style of `test_dial_registration.py` and `test_backlinks_own_profile.py`, so
a future module inherits it with no registration step:

1. An AST scan of `app/`, `integrations/` and `workers/` finds every `Fake*(...)`
   construction and fails on any not declared in `_DECLARED_SAFE` with a written reason.
   Declarations pin **which** fake classes are allowed per function, not just the
   location — an earlier version keyed on location alone and let a new fake inside an
   already-declared function through.
2. A staleness test deletes-by-failing any declaration whose call site is gone.
3. A named regression test for the specific content-research substitution.

**Proven non-vacuous**: reintroducing the original `FakeSerpResearcher()` substitution
fails both the static scan and the named test; restoring the fix returns all three to
green.

Four task-suite files gained an autouse fixture defaulting them to a live vendor (the
contracts they assert live *beyond* the new guard) plus a dedicated refusal test each.

| | |
|---|---|
| Suite before | 4,928 passed · 9 failed |
| **Suite after** | **4,932 passed · 9 failed** (+4 new tests, zero regressions) |
| The 9 | Unchanged: the documented pre-existing beat-schedule class (`TEST_BASELINE.md` §2.1) |

`ruff` and `mypy --strict` clean across every touched module.

### What this did NOT fix

- **The beat schedule is still empty.** Correct ordering: the job contract (P0-3) lands
  first, because restoring a schedule over a ledger that still mis-reports is how a
  double-spend happens.
- **`status="done"` on a credential-degraded publish (P0-4) is untouched.** A content job
  with no WordPress credentials still renders artifacts and reports `done`; only the
  `stage` string carries the caveat, while dashboards key off `status`. This is the next
  truth defect in line.
- **`client_da=None` is still hard-coded**, so `keywords.winnable` remains a neutral-DA
  screen rather than the promised difficulty × authority verdict.
- **GBP profile sync still always holds** — no reader is wired.
- The other 20 `Fake*` classes (GA4, GSC, Sheets, Slack, Resend, B2, IndexNow,
  Firecrawl, the citation/Web2/captcha/places seams, `FakePageFetcher`,
  `FakeWordPressEditor`, `FakeWordPressPluginPublisher`, `FakeBacklinkProvider`,
  `FakeResearcher`) are **not** in this class — verified by grep, each has **zero
  instantiations** anywhere in `app/`, `integrations/` or `workers/`. They exist purely
  as test doubles constructed by the suites. That is now enforced rather than assumed:
  the new AST guard fails the build the moment any of them is constructed on a
  production path.

---

## WU-8 · P0-3 — the job contract (spine item 1)  ✅

*Phase 2 item 1 of the AIOS v2 rescue plan. The plan's own words: "Nothing else
unblocks until this lands — and the beat schedule must not be restored before it."*

### What was wrong

39 Celery tasks, and the job layer had no idempotency key, no retry accounting, no
dead-letter queue, no correlation id, no per-client cap, and no shared status
vocabulary. Verified from the code, not assumed:

- `grep -rn "autoretry_for\|max_retries\|retry_backoff" workers/ app/modules/` → **zero
  matches**. Nothing retries.
- `grep -rln "dead_letter\|dlq" backend/ db/` → **zero files**. Nothing is replayable.
- `workers/celery_app.py:173` → `beat_schedule = {}`. Nothing runs on a schedule.
- Eighteen separate `*_status` enums across the migrations. `audit_status` says
  `done`, `site_job_status` says `completed`, `scheduled_job_status` says `ok` — and
  **not one of them can say `degraded`**. That is the mechanical reason a WordPress
  publish that reached no website recorded `done`: `done` was the only terminal word
  the schema had.

### What changed

**`db/migrations/0080_job_contract.sql`** — `job_status` (queued · running ·
completed · degraded · blocked · failed · cancelled), `job_queue` (interactive ·
standard · long · browser), and two tables: `job_runs` (the execution ledger, one row
per logical unit of work) and `job_dead_letters` (the replayable record of everything
that failed). Both server-written on `service_role`, staff-readable, ENABLE+FORCE RLS.

The point of the table is its CHECK constraints, which make specific lies
unrepresentable rather than merely discouraged:

| Constraint | The lie it refuses to store |
|---|---|
| `job_runs_reason_required_ck` | a `degraded`/`blocked` row with no written reason |
| `job_runs_error_required_ck` | a `failed` row with no error type |
| `job_runs_finished_ck` | terminal without `finished_at`, or `finished_at` while running |
| `job_dead_letters_resolution_ck` | a dead letter closed with no decision recorded |

**`app/jobs/`** — the contract, split so the hard part is Celery-free:

- `status.py` — the one vocabulary. `is_success()` returns True for `completed` and
  **nothing else**; `DOMAIN_TERMINAL_MAP` translates each module's terminal words into
  it. The duration classes own the time limits, so
  `BROKER_VISIBILITY_TIMEOUT = max(TIME_LIMITS) + 300` is derived rather than
  hardcoded (invariant #8 can no longer drift).
- `contract.py` — `JobOutcome` (terminal by construction: `completed()` takes no
  reason because there is nothing to explain; `degraded()`/`blocked()` cannot be built
  without one), the four exception classes, and `JobContext` with throttled
  `heartbeat()` / `cancelled()` / `checkpoint()`.
- `runner.py` — `run_job`: claim → start → execute → finish → dead-letter. Pure over a
  `JobRunStore` Protocol, never raises, and never performs the retry itself (it
  returns a `Disposition`).
- `celery_task.py` — `@aios_job`, `enqueue`, `enqueue_child`, and the router. The only
  Celery-aware module.

**`app/db/job_runs_repo.py`** — the privileged store the runner drives plus the
RLS-scoped read repo the API uses. **`app/routers/jobs.py`** + `app/schemas/jobs.py` —
the operator surface (8 endpoints). **`workers/tasks/job_maintenance.py`** — the
stuck-run reaper.

### Three defects found while building it

1. **`SOFT_TIME_LIMITS` was `hard - 60`, which is ZERO on the 60s interactive class.**
   Celery reads 0 as falsy — no soft limit at all, so an overrunning interactive job
   would be hard-killed with no chance to record an honest outcome. Now
   `hard - min(60, max(5, hard // 4))`, and a test asserts every class has a positive
   soft limit below its hard one.

2. **`JobContext` initialised its throttle clocks to `0.0`, so the FIRST heartbeat and
   the FIRST cancellation poll were both silently skipped** (a monotonic clock can
   legitimately start at 0). Now `-inf`.

3. **The DLQ-replay endpoint creates a run row without knowing the job's spec, which
   would violate `attempt <= max_attempts` on the job's second attempt.** `start()`
   now re-stamps `max_attempts` from the running code's spec — which also fixes the
   latent case of a queued row created before a job's budget was changed.

### One deployment hazard caught before it shipped

Setting `task_default_queue="standard"` looked tidy and was a live-deploy hazard: the
39 legacy tasks publish to the DEFAULT queue, so renaming it strands every message
already sitting on `celery` at the moment of a deploy — and `aios-worker.service`
starts `celery worker` with **no `-Q`**, which consumes only the default queue, so
every job routed to a duration class would have sat in Redis with nothing reading it.
The platform would have looked idle rather than broken.

Fixed both ways: the default queue stays `celery`, and the worker unit now passes
`-Q celery,interactive,standard,long,browser`. A test reads
`infra/systemd/aios-worker.service` and fails if a duration class is ever added
without being added there too — **proven non-vacuous** by removing `browser` from the
line and watching it fail.

### What proves it

| Suite | Count | Proves |
|---|---|---|
| `tests/test_job_contract.py` | 35 | Every runner branch against an in-memory store: idempotent skip, duplicate-delivery drop, retry ladder + budget exhaustion, permanent-vs-transient classification, cooperative cancellation, cap deferral vs honest block, ledger-outage handling, secret redaction |
| `tests/test_job_queues.py` | 12 | The visibility-timeout invariant against the LIVE config, Python↔Postgres enum parity read from the migration, the deployed worker's `-Q` |
| `tests/test_aios_job_decorator.py` | 8 | The Celery binding: registration, routing, time limits, reserved-kwarg stripping, a real `Retry` |
| `tests/test_jobs_endpoints.py` | 19 | The staff boundary, that `degraded` is never folded into a success count, and that replay cannot double-spend |
| `tests/integration/test_job_runs_store.py` | 18 | The SQL against **real PG16**: partial-index idempotency, the advisory-lock cap, every CHECK constraint, the heartbeat reaper |

`db/ci/verify_fresh_apply.py` against a throwaway PG16: **82 migrations apply in order
from zero, RLS gate green, 78 tables all FORCE**.

| | |
|---|---|
| Suite before | 4,932 passed · 9 failed · 4 skipped |
| **Suite after** | **5,005 passed · 9 failed · 4 skipped** (+73 tests, zero regressions) |
| The 9 | Unchanged, and **byte-for-byte the same test ids** as the baseline run: the documented pre-existing beat-schedule class (`TEST_BASELINE.md` §2.1) |

`ruff` clean across the tree; `mypy --strict` clean on 277 files.

### What this did NOT fix

- **The beat schedule is still empty.** Deliberate, and the correct ordering: the
  contract lands first, because restoring a schedule over a ledger that still
  mis-reports is how a double-spend happens. The 9 tests stay red until then.
- **No existing task has been migrated.** The contract is the envelope; moving the 39
  tasks into it is per-module work, and the router falls through for unregistered
  tasks so a half-migrated system works.
- **`content_status` still has no `degraded` label (P0-4).** A credential-less publish
  still records `done` on the module table. Until that lands a job records its
  degradation on the `job_runs` row, so the rollup is honest even while the module
  table is not. `DOMAIN_TERMINAL_MAP` carries an explicit note where the extra row
  will go.
- **The browser queue is not yet its own image.** It is a separate queue precisely so
  it can be peeled onto its own worker; today one unit serves all four.
- **No frontend.** The eight endpoints exist and are tested; nothing renders them yet.

### Amended after the Phase 1 research wave landed

The cross-track index (`docs/research/README.md`, "Requirements this wave imposes on
Phase 2") requires that **every block is a typed refusal with a stable machine code**,
and R3B independently specifies a closed fourteen-value `blocked_reason` vocabulary for
content publishing. So `job_runs.reason_code` and `job_dead_letters.reason_code` were
added **while the contract was still uncommitted and nothing depended on it** — later
it is a data migration.

`degraded` and `blocked` now require both halves: prose for a person (`reason`) and a
stable snake_case identifier for everything else (`reason_code`), enforced by
`job_runs_reason_code_required_ck` and a format check mirrored by a Python validator.
Deliberately NOT a Postgres enum — the closed vocabularies belong to the modules, and
pinning them in the contract would force a migration every time a module learns a new
way to refuse. `DOMAIN_TERMINAL_MAP["content_status"]` also gained its `degraded` row
ahead of P0-4's migration `0081`, because an unmapped terminal word silently vanishes
from every cross-module count.

This is the parallel-phase design working as intended: Phase 1 changed Phase 2's
schema before Phase 2 shipped it.

Full design + migration guide: `backend/docs/JOB-CONTRACT.md`.

---

## WU-9 · A false claim in an always-loaded doc, and how far it travelled  ✅

*Not planned work. Found while adding invariant #13 next to invariant #12.*

### The claim

`backend/CLAUDE.md` invariant #12 asserted, in its title and its body:

> "the QA gate is a **hard gate**" · "The **QA §11 scorecard is a hard publish gate**:
> `publish_content_job` re-checks `qa_score.passed` and **NEVER publishes a
> sub-threshold draft** (raises `PublishBlocked`)."

It is false, and was false at the audited commit. Verified rather than inferred:

```
$ grep -rn "raise PublishBlocked" app workers integrations
(no matches)
```

`PublishBlocked` is defined (`workers/tasks/content.py:382`) and caught twice
(`:2129`, `:2371`) but **raised nowhere**. `publish_content_job` reads the stored
score, emits `content_publish_qa_advisory` (`:2110`) and publishes regardless. The
code says so itself at `:47`, `:2102` and `:2358`.

WU-6 established exactly this and corrected three docstrings in `workers/tasks/content.py`.
It missed four other places, which is how the claim survived.

### How far it travelled

This is the part worth recording. The claim did not stay in one file:

| Where | What it said |
|---|---|
| `backend/CLAUDE.md` #12 (title + body) | "hard gate", "NEVER publishes a sub-threshold draft" |
| `backend/docs/CONTENT-MODULE.md` §"The QA gate (a hard publish gate)" | described the mechanism in detail — "it raises the typed `PublishBlocked`… the gate still refuses a draft that does not actually clear the bar" |
| `app/services/content_qa.py:72` | "EVERY dimension below MIN_DIMENSION_SCORE **blocks publish**" |
| `app/services/content_qa.py:723` | "**Publish** (`passed`) iff…" |

And then out of the codebase entirely, into the Phase 1 recovery specification —
**citing `backend/CLAUDE.md` item 12 as its evidence**:

- `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:95` — *"The content QA scorecard is a hard
  publish gate… **[CONFIRMED — `[CODE]` `backend/CLAUDE.md` item 12]**"*
- `:1748` CN-1, a **P1** finding — *"…yet enforced as a hard publish gate"*
- `:1933` records the contradiction explicitly — `[CODE]` said hard gate,
  `[RESEARCH-AUG]` said *"now advisory, not a blocker"* — and **resolved it in favour
  of the documentation.** The research note was right; the doc was wrong.
- `OPEN_QUESTIONS.md` Q-4 — *"the codebase **states** it is a hard gate"* (the wording
  is honest: the author read the documentation, not the call sites)
- `DECISIONS_REQUIRED.md` D-4 — *"**Context.** The code enforces it as a hard publish
  gate…"*

**D-4 is therefore not the decision it was framed as.** It was escalated as "hard gate
or advisory?" — and the answer to that half has been "advisory" the whole time. What is
genuinely open is narrower: whether to build D-4's *other* half (mandatory
acknowledgement) and, later, a calibrated hard gate. CN-1's premise — an uncalibrated
threshold *enforced* — is false, because nothing is enforced.

**Do not re-escalate D-4 on the strength of this.** The stale framing lives in
`DECISIONS_REQUIRED.md`'s original *Context* line, not in the plan the owner approved:
that plan's D-4 recommendation already reads *"advisory PLUS mandatory acknowledgement
— only the advisory half exists; the QA verdict goes to a server log and the approving
lead never sees it."* So the decision on record is already the narrow one. What this
finding changes is the SIZE of the job, not its scope: the score does not need plumbing
to the review surface, because it is already computed, stored at `needs_review` and
fetchable — the acknowledgement is a schema addition plus a gate, not a pipeline
change.

### What changed

Documentation only. **No behaviour was altered** and the QA scorecard still computes
`passed` exactly as before (70 / 85 / hard-gate floor, all PROVISIONAL).

- `backend/CLAUDE.md` #12 — title and body corrected, with the grep result and the
  file:line evidence inline so the next reader does not have to re-derive it.
- `backend/docs/CONTENT-MODULE.md` — section retitled "The QA score (ADVISORY — there
  is no automated publish gate)" with a dated correction note, and rewritten to state
  what actually happens: the score is stored at `needs_review` and fetchable at
  `GET /content/jobs/{code}/qa`, it is NOT in the 15-key `ContentJobResponse` the
  review endpoint returns, and publish only logs it.
- `app/services/content_qa.py` — both stale comments corrected; `passed` is labelled a
  verdict, not an enforcement.

`PublishBlocked` and its two catch sites are **kept**, per WU-6: they are the seam a
calibrated gate re-enables through.

### Deliberately NOT changed

- **The recovery specification, CN-1, Q-4 and D-4 are untouched.** They are Phase 1
  deliverables and a historical record of what that pass found; revising a P1 finding
  and re-scoping an escalated decision is an owner call, not a side effect of a
  documentation fix. Recorded here instead, and flagged to the owner.
- **The gate itself.** Making QA enforceable is P0-4 / D-4 and belongs to that work.

### The lesson worth keeping

The claim was believed because it was in `CLAUDE.md` — a file re-read every turn, by
every session. An always-loaded document is the highest-trust surface in the repo, so
a false statement in it is not one bug, it is a premise. This one propagated into a
P1 audit finding and an escalated owner decision **within one phase**, and the audit
even cited the doc back as its own evidence.

`ruff` clean; `tests/test_content_qa.py` 24 passed.

---

## WU-10 · P0-4 — a publish that reached nothing reported as `done`  ✅

**Workstream:** WS-1 (Truth) · **Plan item:** Phase 2 item 2, "stop faking success".
**Depends on:** WU-8's vocabulary (`app/jobs/status.py`) for the terminal word; the
`app/jobs/` *integration* is deliberately NOT in this unit — see "what this did not do".

### The defect

`publish_content_job` tries four transports to get a page onto the client's WordPress
site. When none is available — usually because no per-site credential is sealed in the
vault — it renders a PDF/Markdown artifact locally and wrote:

```python
store.update(code, {"status": "done", "stage": "Published (artifact-only — WordPress credentials pending)"})
```

The caveat lived **only in the free-text `stage`**. Every consumer keys off `status`:
the pipeline board, `/content/stats`, the `content_status` report series, the monthly
client report. So a job that put nothing on the client's website was indistinguishable
from one that did.

**It reached a human.** The same branch called `_emit_content_deliverable`
unconditionally, which emails the client *"a new piece of content has been published…
Sign in to your client portal to view it."* A client could therefore be told their page
was live, follow the notification, and find nothing — while the operator's board showed
the job green. That is worse than a wrong tile: it spends the client's trust, and it is
Danyal's relationship being spent, not ours.

The audit recorded the `status` half. The email was not in the record.

### What changed

| | |
|---|---|
| `db/migrations/0081_content_degraded_label.sql` | Adds `degraded` to `content_status`. Its own migration because Postgres refuses to USE a new enum label in the transaction that ADDS it (55P04) — the house pattern established by `0009_app_role_client.sql` and repeated at `0078`/`0079`. |
| `db/migrations/0082_content_degraded_transitions.sql` | Re-states `content_jobs_guard_update` with **one** added worker transition, `publishing -> degraded`. The lifecycle is enforced at the trigger, not in FastAPI (`service_role` bypasses policies but not triggers), so the label alone would have left every attempt raising `illegal system content transition`. |
| `workers/tasks/content.py` | `_publish_artifact` writes `degraded` instead of `done`. `_emit_content_deliverable` gained `live: bool`. |
| `app/schemas/content.py`, `frontend/lib/content.ts` | `degraded` added to both `JobStatus` definitions (contract-locked pair). |
| `frontend/lib/content.ts` | **New "Not Live" column** on the pipeline board. |

Two judgement calls worth recording:

**The deliverable is still emitted; only the email is suppressed.** The rendered
artifact is real work and the client should be able to open it. The *announcement* is
the falsehood. Suppressed rather than reworded, deliberately: whether to tell a client
about a degraded delivery, and in what words, is an operator's decision about their own
client relationship — not one for a worker to invent silently.

**The board needed a column, not just a tone.** `PipelineBoard` filters strictly by
`status`, so a status with no column matches nothing and **disappears**. Without it,
fixing the status would have moved the lie rather than removed it: the job would have
stopped claiming success by vanishing from the operator's board entirely. Labelled
"Not Live" rather than "Degraded" — the key keeps the platform vocabulary, the label
gives the operator the consequence.

`drafting -> degraded` was deliberately **not** added. A research or spend degradation
during drafting already HOLDS at `drafting` and is designed to resume when keys or
budget arrive; that is a pause, not an outcome.

### What proves it

**The trigger was exercised against a real built schema**, not asserted:

| transition (worker path) | result | expected |
|---|---|---|
| `publishing -> degraded` | ALLOWED | ALLOWED |
| `publishing -> done` | ALLOWED | ALLOWED |
| `drafting -> needs_review` | ALLOWED | ALLOWED |
| `queued -> degraded` | BLOCKED | BLOCKED |
| `drafting -> degraded` | BLOCKED | BLOCKED |
| `degraded -> done` | BLOCKED | BLOCKED |

Six for six — the guard was **widened by exactly one transition, not loosened**, and
`degraded` is terminal for the worker (only a lead can move it, which is the intended
recovery path once a credential lands).

`verify_fresh_apply` against a throwaway PG16: **84 migrations apply in order from
zero, RLS gate green, 78 tables all FORCE.** Run on port 55433, deliberately not the
`aios-migration-verify` instance owned by the parallel session; removed afterwards.

**Three existing tests asserted the defect** and were corrected:
`test_publish_degraded_no_wp_creds_is_artifact_only`,
`test_publish_degrades_cleanly_when_no_connection`, and
`test_plugin_push_failure_is_swallowed_and_job_advances` — the last being the clearest
case, since the plugin push actually *raised* and the job was still recorded `done`.
New: `test_a_degraded_publish_does_not_tell_the_client_their_content_is_live`, which
asserts the email is suppressed **and** the deliverable is still emitted.

`ruff` clean; `mypy --strict` clean; frontend `tsc --noEmit` clean.

### What this did NOT fix

- **No `app/jobs/` integration yet.** `JobOutcome.degraded(reason_code, reason)` and
  `is_success()` live in WU-8, which is **uncommitted** at the time of writing. Building
  against a file that exists only in the working tree would be building on sand — the
  parallel session amended that exact signature mid-flight, which is the hazard
  demonstrating the point. Deferred until WU-8 is committed; `reason_code` will adopt
  R3B's closed vocabulary (`no_transport`, `credential_invalid`) rather than inventing
  two words.
- **The second degraded exit** ("no artifact store configured") still holds at
  `publishing` with a stage marker. It is already honest at the DB level — it never
  claimed `done` — but it should route through the same vocabulary rather than remain a
  special case.
- **`DOMAIN_TERMINAL_MAP["content_status"]["degraded"]`** is owned by WU-8 and was added
  there, not here, to avoid mixing this work into that commit.
- **D-4's acknowledgement half** is untouched. `qa_score` is computed and stored at
  `needs_review` and fetchable via the artifact endpoint, but is not among
  `ContentJobResponse`'s 15 keys, so the approving lead still never sees it.
