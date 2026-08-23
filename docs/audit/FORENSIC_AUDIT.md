# FORENSIC AUDIT — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit:** `79d1036` · **Companion docs:** all files in `docs/audit/`

---

## 0. Headline

This is **not** a failed build. The foundation — authentication, tenant isolation, SQL safety,
the cost model, the provider seams, the test discipline in CI — is materially better than the
recovery specification's narrative implies, and rebuilding it would destroy real value.

The failure is narrower and sharper than "the code is bad":

> **The system was engineered to never fail loudly, and then had its clock switched off.**

Two decisions compound into everything else:

1. **Every scheduled job is disabled** (`workers/celery_app.py:173`, `beat_schedule = {}`).
2. **Every failure is absorbed rather than retried or surfaced.** All 39 Celery tasks are
   declared `@celery_app.task(name="…")` with **no `bind`, no `autoretry_for`, no `max_retries`,
   no `retry_backoff`**, and the prevailing in-code doctrine is "never re-raise". There is no
   dead-letter queue anywhere in the repository.

A platform sold as *"most of the work runs on its own"* currently runs nothing on its own, and
when a manually-triggered job hits a transient error it degrades silently and permanently
instead of retrying. That is the core finding. Everything below is either a consequence of it or
an independent defect of lower magnitude.

---

## 1. System map

### 1.1 Request path

```
Browser (Next.js, static-prerendered)
  └─ lib/api.ts  ── Bearer (localStorage, 7d) ──►  nginx  ──►  FastAPI
                                                                 │
      RequestIDMiddleware → MetricsMiddleware → CORS → TrustedHost
                                                                 │
                                         router guard (require_perm / require_role)
                                                                 │
                                                    service (pure where possible)
                                                                 │
                                       repo → rls_connection(user_id) → Postgres RLS
```

Identity is carried by the **repo dependency**, not only by the route signature: `ClientsRepoDep`
resolves `CurrentUserDep` transitively, so a route with no visible guard still cannot reach the
database without a verified `sub`. `tests/test_route_auth_guard.py` sweeps the whole OpenAPI
surface and asserts every non-public route 401s unauthenticated. This is a good design and it is
tested.

### 1.2 Job path

```
router  ──► .delay()  ──► Redis ──► celery worker (-c 4, single default queue)
                                       │
                          service ──► cost_gate.evaluate()
                                       │  halt? → dial? → cached? → cap? → call
                                       ▼
                                  integrations/* (provider)
                                       │
                                  cost_gate.commit(real cost)  → cost_log
```

`beat` is running as a container but has an empty schedule, so it fires nothing.

### 1.3 Audit path (the one that leaves the process)

```
worker ──subprocess──► /opt/audit-venv/bin/python -m audit_engine.cli … full
                          │ stdout: "Run UUID: <uuid>"   ← PARSED
                          ▼
        <engine_dir>/data/audits/<slug>/<uuid>/findings.json | run.json | report.{pdf,html}
                          │ read from LOCAL DISK
                          ▼
                    audits table + audit_artifacts service
```

### 1.4 Dependencies that matter

| Edge | Nature | Risk |
|---|---|---|
| worker → audit-engine subprocess | Second interpreter, second venv, stdout contract, filesystem artefacts | **Pins audits to one host.** No object storage, no horizontal scale, no artefact backup by default |
| `integrations/*` → `app.services.*` | Dependency inversion (`mcp_gateway.py:37-38`) | Adapter layer cannot be extracted or tested in isolation |
| `app/db/policy_repo.py` → `app.services.policy_baseline` | Repo → service inversion | Same |
| every repo call → its own txn | `rls_connection()` opens a connection **and a transaction** per call (`app/db/database.py`) | **No multi-statement business transaction.** See §4 |
| frontend → `lib/data.ts` | 52 files import it, but only for types/constants (`SERIES`, `TIER_COLOR`, `ROLE_META`) | Low: the mock arrays (`audits`, `traffic`, `team`, `clients`) are genuinely unreferenced |

### 1.5 Circular dependencies

No Python import cycle was found. The two inversions above are directional, not circular.

### 1.6 Duplicated logic

| Duplicate | Evidence |
|---|---|
| Two WordPress publish paths with overlapping responsibility | `integrations/wordpress.py` (REST/app-password + XML-RPC) and `integrations/wordpress_publisher.py` (custom plugin). `workers/tasks/content.py:2160-2196` cascades through **four** fallbacks in sequence |
| Two cost-price sources | `app/services/pricing.py` (runtime, correct) and `frontend/lib/cost.ts:19-27` (hardcoded `"$0.30 / search"`, `"~$0.90 / page"` display strings) |
| Two audit artefact readers | `app/services/audit_artifacts.py` and `app/services/audit_sheets.py` both parse `findings.json` |
| Two "workspace" endpoint families | `app/modules/tool_workspaces/router.py` exposes 9 `/…/workspace` endpoints that re-aggregate what the per-module `/stats` endpoints already return |
| A second, undocumented dashboard | `dashboard/bridge.py` + `dashboard/worker.py` + `dashboard/index.html`, referenced by no deployment |

### 1.7 Hidden coupling

- **The `[ai]` extra is optional but load-bearing.** Every AI seam lazy-imports `anthropic` and
  degrades to a `FakeSummarizer` when absent. A deployment that forgets `pip install -e '.[ai]'`
  produces *plausible deterministic fake content* rather than an error. The fake is the same
  class the tests use.
- **The `[automation]` extra is optional and load-bearing.** `integrations/citation_bot.py`
  lazy-imports Playwright and degrades to `None`. A deployment without
  `playwright install chromium` silently cannot submit any citation.
- **`AUDIT_ENGINE_DIR` / `AUDIT_ENGINE_PYTHON`** are plain env strings. A wrong value fails at
  audit time, not at boot.

### 1.8 Fragile components (ranked)

1. `integrations/citation_bot.py` — Playwright DOM automation against **3** hand-written form
   specs (see §5).
2. `integrations/audit_engine.py` — subprocess + stdout parsing + filesystem contract.
3. `workers/tasks/content.py` (2,400 LOC) — the four-way WordPress publish cascade, every branch
   swallowing its own exception class.
4. `frontend/lib/store.tsx` — dead demo store still mounted at the app root.
5. `integrations/web2_publishers.py` (3,217 LOC) — 55 provider clients in one file; a change to
   the shared `HttpProviderClient` touches all of them.

---

## 2. Verified defects — the truthfulness class

### 2.1 The free audit records $0.00 for a run that spends real money — **P0**

`workers/tasks/audit.py:505-517`:

```python
# crashes. COST NOTE: this now incurs real Serper/Places spend per run.
result = runner(_config_from_settings(settings), url=row["url"], tier="free")
…
# Log the run through the cost path once the engine actually started (Free -> $0).
if result.run_uuid is not None:
    _safe_record_cost(store, row, 0.0)
```

The adapter confirms it (`integrations/audit_engine.py:211-227`): the public funnel now runs
`--mode auto` with paid providers **on**, and the comment states *"this path is NO LONGER $0 …
the owner should know the free funnel is now a metered cost."*

Consequences, all of them live:
- The cost ledger and the Cost screen **understate real spend**, by an amount nobody can compute.
- The per-client budget cap and the global spend-halt **can never trip** on free-funnel traffic,
  because a `$0.00` commit never approaches a cap. This directly defeats **ADM-026**.
- `/api/v1/public/audits` is unauthenticated and rate-limited only at
  `rate_limit_ip("public_audit", 5)` — 5 per minute **per IP**. With rotating IPs this is an
  uncapped **denial-of-wallet** vector against the owner's Serper and Google Places keys.

This one defect violates ADM-001, ADM-025, ADM-026 and SEC/cost integrity simultaneously.

### 2.2 Advertised capabilities are silently degraded — **confirmed**

The specification's claims were checked against source, not taken on trust:

| Claim | Verdict | Evidence |
|---|---|---|
| `keywords.winnable` hard-codes `client_da=None` | **CONFIRMED** | `app/modules/keyword_research/tasks.py:120`. The scorer assumes a neutral DA (`content_research.py:874-875`), so "difficulty × client authority" is really "difficulty ≤ 45" for every client alike |
| A `keyword_research` cost-gate block is silent | **CONFIRMED** | `POST /keyword-research/research` is fire-and-forget 202; no degrade signal reaches the caller |
| `competitor_intel` backlink-gap returns an empty set | **CONFIRMED** — the endpoint `GET /competitor-intel/competitors/{code}/backlink-gaps` exists and is reachable; nothing populates competitor-side rows |
| `local_seo` GBP sync always holds | **CONFIRMED** | `app/modules/local_seo/tasks.py:211` — *"A hold writes nothing and costs nothing"* |
| `on_page` drift guard is a string compare | **CONFIRMED** — not a hash/etag |

### 2.3 Dead demo surfaces still ship — **P2**

- `frontend/lib/store.tsx` (a localStorage demo store) is mounted at `app/layout.tsx:62` and
  seeded from `lib/data.ts` with hardcoded clients, team members, tasks, activity and
  **plaintext passwords for eight named users** (`teamCredentials`). No screen reads it.
- `frontend/lib/vault.ts:101-113` — eleven fake-but-realistic API keys with `secret:` fields.
- `frontend/lib/cost.ts:2` — *"Cost Controls mock data — swap for FastAPI/Postgres later"* — the
  file still hardcodes provider unit prices as display strings, contradicting **ADM-025**.
- `frontend/components/audit/AuditCoverage.tsx:53` — a **"Coming soon"** panel. **ADM-014**
  requires this section removed.

### 2.4 The builder's name reaches the client — **P1**

See `REPOSITORY_ARCHITECTURE.md §9`. `Xegents AI` is the plugin author string in every end-client
wp-admin, and the footer of every outbound email.

---

## 3. Verified defects — the reliability class

### 3.1 Zero retry, zero dead-letter — **P0**

All 39 tasks, enumerated from source:

```
workers/tasks/{audit,content,offpage,policy,reports,context,context_reconcile,ping}.py
app/modules/{billing,citations,competitor_intel,data_import,indexing,keyword_research,
             local_seo,on_page,rank_tracker,site_analytics,site_builder}/tasks.py
```

Every one is `@celery_app.task(name="…")` and nothing more. Grep for `autoretry_for`,
`max_retries`, `retry_backoff`, `self.retry`, `bind=True` across all of them returns **zero
hits**. Grep for `dead.letter|dlq` across `app/`, `workers/` and `db/migrations/` returns
**zero hits**.

The compensating design is "never re-raise" — e.g. `workers/tasks/content.py:2337`: *"block is
caught + returned (never re-raised: acks_late would redeliver)"*. That is a correct instinct
about `acks_late`, applied as a blanket policy. The net effect:

- A transient 503 from Serper permanently fails that job. No retry. No alert. The row shows
  `degraded` and the operator must notice.
- Because nothing re-raises, `task_acks_late=True` buys nothing: the only redelivery path left is
  a worker **crash**, and on crash the job re-runs from the top with no idempotency key on most
  paths.
- There is no queue in which a poisoned job accumulates for inspection.

### 3.2 The publish cascade hides failure — **P0**

`workers/tasks/content.py:2160-2196` tries, in order: per-client plugin → per-client REST →
single-site plugin → vault-resolved REST → artifact-only. **Each stage catches its own exception
and falls through with a `logger.warning`.** The terminal state is
`_publish_artifact(..., degraded=True)` — the job **completes**, a deliverable exists, and
nothing was published to WordPress.

An operator running the owner's acceptance bar ("50 pages across 10 businesses") can hit a green
board with zero live pages.

### 3.3 No multi-statement business transaction — **P1**

`rls_connection()` (`app/db/database.py`) opens a pooled connection **and an explicit
transaction** per call, committing on exit. Every repo method is one transaction. There is no
seam to compose two repo calls atomically.

Where this bites, verified:

- **Client creation** (`app/routers/clients.py:53-86`) is three separate writes —
  `insert_client`, `upsert_business_profile`, `seed_onboarding_for_client` — with the second and
  third wrapped in `try/except` and documented as *"BEST-EFFORT … never raises"*. A crash between
  them leaves a client with no NAP (which is exactly the state that makes Citations report
  "no business profile" — **ADM-009**) or no onboarding checklist.
- **`POST /upsells/reorder`** (`app/routers/upsells.py:85-87`) issues one `UPDATE` per id, each
  its own transaction. A mid-loop failure leaves a **partially reordered catalogue**.
- **`PUT /settings/notifications`** (`app/routers/settings.py:124-128`) — same shape.

`app/services/provisioning.py` shows the team knew: it drops to a single
`privileged_connection()` transaction for user provisioning, satisfying **ADM-005**. The pattern
was simply never generalised.

### 3.4 N+1 queries on the dashboard's own endpoint — **P2**

`app/routers/command_center.py:39-50` — `_resolve_assignees` runs `tasks_repo.get_user(uid)` in a
loop over distinct assignees. Each call is a fresh pooled connection + transaction. With 20 staff
that is 20 round trips to render one dashboard.

---

## 4. Verified defects — the security class

The security foundation is **strong** and should be preserved. See `SECURITY_AUDIT.md` for the
full treatment. The two findings that rise to P0 are:

### 4.1 There is no way to offboard a person — **P0**

- `db/migrations/0002_identity_rbac.sql:15` — `create type public.user_status as enum
  ('active','away','invited','offline')`. **There is no `suspended`, `disabled` or `deactivated`
  state.**
- `app/routers/admin_users.py` exposes GET, POST, `/invite`, grants, credentials, password —
  and **no DELETE and no deactivate**.
- `app/routers/auth.py:132-157` — `login()` verifies the password and mints a token. It **never
  reads or checks `status`**.
- `app/core/auth.py:177-190` — `get_current_user` loads `status` into `CurrentUser` and **no
  guard anywhere consults it** (grep across `app/core/`, `app/rbac/`, `app/routers/`).

Meanwhile `app/rbac/matrix.py:131` advertises the permission as *"Add, edit & **deactivate**
members"*. The capability does not exist.

**Consequence:** a departing team member keeps full access indefinitely. The only remedy is a
manual `DELETE` in psql, which will cascade or orphan across 77 tables.

### 4.2 A 7-day, non-revocable bearer token in `localStorage`, with no CSP — **P0**

- `app/config.py:72` — `jwt_access_ttl_seconds: int = 604_800` (7 days), with the comment *"there
  is no refresh route, so this IS the whole session"*.
- No `jti`, no denylist, no `token_version` column, no revocation path (grep returns nothing).
- `frontend/lib/api.ts` stores it in `localStorage` under `aios-token-v1`.
- `infra/deploy/nginx.conf:31-34` sets HSTS, `nosniff`, `X-Frame-Options`, `Referrer-Policy` —
  **and no `Content-Security-Policy`** (grep for CSP in `nginx.conf` and `Caddyfile`: 0 hits).
  A CSP *is* correctly set on served audit artefacts (`app/services/audit_artifacts.py:39`), so
  the team knows the header; it was simply never applied to the app itself.

**Consequence:** one XSS anywhere in the dashboard yields a stolen token that grants full account
access for up to seven days and **cannot be revoked** — not by password change, not by an admin
action, not at all.

---

## 5. Verified defects — the off-page class

### 5.1 The citation bot covers 3 directories, not 50 — **P0**

Counted directly from source:

```
integrations/citation_bot.py  FORM_SPECS entries: 3   → ["n49", "192.com", "411.ca"]
```

Against the seeded catalogue in `db/migrations/0046|0065|0067`:

| `submission_method` | Rows seeded |
|---|---|
| `bot_fillable` | **151** |
| `captcha_assisted` | 51 |
| `manual` | 17 |
| `api` | 2 |

The module's own header is honest — *"EVERY SELECTOR HERE IS A BEST-EFFORT STARTING SPEC, not
hand-verified"* (`citation_bot.py:15`) — but the recovery specification's figure of "~50 form
specifications" is **overstated by roughly 16×**. `SIGNUP_SPECS` in
`integrations/citation_signup.py` is likewise empty of concrete entries.

The two `api` routes are both flagged unconfirmed in source: `BingPlacesSubmitter`
(*"CONFIRM BEFORE LIVE USE … partner/API-key gated"*) and `FoursquareSubmitter` (*"partner-gated
… whose exact write endpoint this implementation assumes"*).

**Honest current capability: automated citation submission works for 3 directories.** The
commercial commitment is ~100 platforms at <10¢/unit.

### 5.2 Web 2.0 is the strongest off-page asset and is being under-credited — **GREEN**

Counted from source: **55 platform constants, 55 concrete API client classes, 52 credential
factory builders** in `integrations/web2_credentials.py`. These are real HTTP API integrations
(Ghost Admin API, Bluesky/AT Protocol, Mastodon, Notion, Zenodo, Sanity, Storyblok, Hygraph,
MetaWeblog for FC2/Seesaa, the LiveJournal XML-RPC protocol shared by Dreamwidth …), not browser
automation. This is the one subsystem that plausibly scales as built.

One inconsistency: `PLATFORM_MEDIUM` is declared and is in `WEB2_PLATFORMS`, but there is **no
`MediumClient` and no factory entry** — it is only in `DRAFT_ONLY_PLATFORMS`. Selecting Medium
will fail at dispatch. (Medium retired its write API, so the correct fix is removal, not
implementation.)

---

## 6. Verified defects — the AI class

### 6.1 A hard publish gate on an admittedly uncalibrated score — **P1**

`app/services/content_qa.py:99-111`:

```python
# BOTH the thresholds AND the weight vector below are PROVISIONAL
WEIGHTED_TOTAL_THRESHOLD = 85
PROVISIONAL = True
DIMENSION_WEIGHTS: dict[str, float] = { … }
```

Publish is blocked unless *no dimension < 70 and weighted total ≥ 85*
(`content_qa.py:774`). The threshold and the weights were never calibrated against a human SEO
grade. A hard gate on an uncalibrated score either blocks acceptable work or passes unacceptable
work, and there is no measurement that tells you which.

### 6.2 The fake writer is indistinguishable from the real one at the seam — **P1**

`integrations/llm.py` defines `AnthropicSummarizer` and `FakeSummarizer` behind one Protocol. The
fake is deterministic and network-free. A deployment missing the optional `[ai]` extra or the
`ANTHROPIC_API_KEY` does **not** fail — the constructor raises `ProviderNotConfiguredError`, the
caller catches it, and the pipeline degrades. Content still gets produced by the guard/QA path.
There is no runtime assertion anywhere that says *"this environment must be using the real
provider"*.

### 6.3 What is genuinely good here

- **One door to the model.** No SDK call outside `integrations/llm.py` and
  `app/services/site_design.py`. Everything else goes through the `Summarizer` Protocol.
- **Every AI call is cost-gated** by a wrapper (`GatedSummarizer`, `context_cost.py:118`,
  `web2_pipeline.py:310`, `workers/tasks/content.py:304`) that evaluates before and commits the
  real token cost after.
- **Model tiering is real** — `claude-haiku-4-5` default, `claude-sonnet-5` for heavy folds.
- **Prompt-cache-aware** — frozen system prefix with `cache_control: ephemeral`.
- **The image pipeline deliberately excludes the article topic from the prompt**
  (`content_generator.py:803`) — a thoughtful hallucination/brand-safety control.

---

## 7. What is genuinely sound — preserve this

Stating this plainly matters, because the temptation after a specification like the recovery doc
is to rewrite everything.

| Subsystem | Why it is sound |
|---|---|
| **Authentication** | Own Ed25519 tokens, hard `_ALLOWED_ALGS = ["EdDSA"]` allow-list (defeats alg-confusion and `none`), `exp`/`sub`/`aud` required, Argon2id hashing, constant-time login with a dummy-hash path so timing does not leak user existence |
| **Tenant isolation** | RLS is the **real** boundary — 195 policies, every application table with both `ENABLE` and `FORCE`, a `rls_check` gate that runs in CI against an ephemeral Postgres and fails the build on any unforced table |
| **SQL safety** | No ORM, but every value is a bound param and every dynamic identifier goes through `psycopg.sql.Identifier`. The txn-local identity is set via `set_config(…, true)` with a **bound** parameter precisely because `SET LOCAL` cannot bind — a considered, correct decision |
| **Pool hygiene** | `RESET ALL` on connection return, autocommit asserted off, identity transaction-local so it cannot leak across checkouts |
| **Cost model** | `app/services/pricing.py` computes cost at runtime from real token/query counts. The `cost_gate` orders checks correctly: global halt → dial → cache → cap → call → commit |
| **Route auth coverage** | 260/305 endpoints carry an explicit role/permission guard; the remaining 17 authenticated-only reads are RLS-scoped; a runtime OpenAPI sweep test enforces it |
| **CI** | ruff + mypy `--strict` + unit + integration against real Postgres/Redis + pip-audit + gitleaks + an RLS gate. This is above the median for a project of this age |
| **Frontend build health** | `tsc --noEmit` clean, `next build` clean, 103 kB shared bundle, largest route 148 kB, a11y attributes present in 53 of 136 components |
| **Web 2.0 publishers** | 55 real API clients — the most valuable single asset in the off-page tree |

---

## 8. Second-pass review of this audit

Re-reading my own findings for the failure modes the brief names:

- **Missed requirement.** The specification's 382 requirements include Policy Radar, which
  `DECISIONS_LOG.md` leaves formally undecided (D-17) while noting it is built and one line from
  being scheduled. I have treated it as **in scope** in the plan and flagged the decision.
- **Incorrect assumption I made and corrected.** My first two route-guard analyses reported 273
  and then 270 "unguarded" endpoints. Both were wrong — guards are applied through module-level
  `Annotated[...]` aliases, and identity also arrives transitively through the repo dependency.
  The alias-resolving pass gives 260/305 guarded. **The correct reading is that authorization
  coverage is good, not bad.** I am recording the error because an audit that had stopped at the
  first number would have recommended a rewrite of the entire router layer.
- **Hidden dependency I nearly missed.** The optional `[ai]` and `[automation]` extras are
  load-bearing: without them the system produces fake content and cannot submit citations, and
  in both cases it degrades rather than erroring. This belongs in the deployment checklist as a
  boot-time assertion, not a README note.
- **Data-integrity risk I nearly under-rated.** The per-call transaction boundary is easy to read
  as a style choice. It is not — it is why client creation is three best-effort writes, and why
  ADM-009's "Citations never again reports no business profile" cannot be guaranteed today.
- **Operational requirement absent from both the spec and the code.** There is **no user
  offboarding**. Neither the requirements matrix nor the specification's §22 security section
  names it. It is a genuine gap in the requirements themselves, not only in the build.
- **Scalability risk I want on the record.** The audit engine's filesystem+subprocess contract is
  the single hardest constraint on the "hundreds of clients" target, and it is invisible from the
  API surface.
- **Test gap that changes the risk picture.** 219 backend test files sounds like strong coverage.
  116 of them run against injected fakes, there is **no coverage threshold** in CI
  (`pytest --cov` with no `--cov-fail-under`), **no frontend test at all**, and **no end-to-end
  test**. The suite proves the units behave; it does not prove a business outcome is produced.
