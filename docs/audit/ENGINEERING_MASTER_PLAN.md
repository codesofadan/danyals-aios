# ENGINEERING MASTER PLAN — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit:** `79d1036` · **Status:** for owner approval before implementation

**Companion documents (read in this order):**
`REPOSITORY_ARCHITECTURE.md` → `FORENSIC_AUDIT.md` → `FEATURE_INVENTORY.md` →
`REQUIREMENT_GAP_ANALYSIS.md` → `SECURITY_AUDIT.md` · `AI_AUDIT.md` · `PERFORMANCE_AUDIT.md` ·
`TESTING_AUDIT.md` → `SALVAGEABILITY_MATRIX.md` → `TARGET_ARCHITECTURE.md` →
`MIGRATION_STRATEGY.md` → **this document**

> **Standing constraint.** Per the Phase 2 brief, **no large-scale implementation begins until this
> plan is approved.** Nothing in the audit modified production-critical code.

---

## 1 · CURRENT STATE

**The build is not a failure and it is not finished.** ~170k LOC Python, ~27k LOC TypeScript, a
separate 20k-LOC audit engine, 80 migrations, 77 tables with complete RLS, 305 endpoints, 219 test
files, and a working deployment on `app.qanry.com`.

**What is genuinely sound** — and must survive the recovery: EdDSA authentication with a hard
algorithm allow-list; RLS as a real, proven tenant boundary (verified from a client's own identity
against real Postgres); exemplary SQL safety with no ORM; a runtime cost model; 260 of 305
endpoints carrying explicit permission guards; 55 working Web 2.0 API publishers; a deterministic
audit engine; a pure, three-layer content guard; strict mypy and a genuine integration CI.

**What is broken**, stated as the audit found it:

| # | Defect | Evidence |
|---|---|---|
| 1 | **Nothing runs on a schedule.** | `workers/celery_app.py:173` — `beat_schedule = {}` |
| 2 | **Nothing retries.** All 39 Celery tasks carry no `autoretry_for`, `max_retries`, `retry_backoff` or `bind`. No dead-letter queue exists anywhere. | grep across `workers/`, `app/modules/*/tasks.py` |
| 3 | **The system reports success it did not achieve.** The WordPress publish path tries four transports, swallows each failure, and marks the job **complete** with `degraded=True` — an operator can hit a green board with zero live pages. | `workers/tasks/content.py:2160-2196` |
| 4 | **The free audit spends real money and logs $0.00.** It runs paid providers, bypasses the cost gate entirely, and commits `0.0`. It is unauthenticated, rate-limited only per-IP, and the limiter fails open. | `workers/tasks/audit.py:505-517`, `integrations/audit_engine.py:211-227` |
| 5 | **Citation automation covers 3 of 151 bot-fillable directories.** Signup specs are empty; both direct APIs are source-flagged unconfirmed. | `integrations/citation_bot.py` FORM_SPECS = `["n49","192.com","411.ca"]` |
| 6 | **A person cannot be removed from the system.** No disabled state in the enum, no deactivate endpoint, `login()` never checks status, and the 7-day token is irrevocable. | `db/0002:15`, `app/routers/admin_users.py`, `app/routers/auth.py:132` |
| 7 | **A hard publish gate rests on a self-declared uncalibrated score.** | `app/services/content_qa.py:99-111` |
| 8 | **The builder's name ships to end clients** — in every WordPress plugin listing and every outbound email footer. | `aios-publisher.php:6,8-9`, `email_templates.py:35` |

**Requirement coverage against the 126 P0 rows:** 43 MET · 41 PARTIAL · 38 NOT MET · 4 UNVERIFIED.

**The structural diagnosis** (confirming the recovery specification's §1.4): the platform was built
module-by-module against a UI rather than workflow-by-workflow against an outcome — **and the test
suite inherited exactly that shape.** 219 test files prove units behave; not one proves that an
audit produces a report a client can read, or that approved content reaches a client's website.

---

## 2 · TARGET STATE

A platform where:

1. **Work runs on its own**, on a schedule, with bounded retry, a dead-letter queue, and an
   operator surface that answers *what ran, what failed, what it cost*.
2. **Failure is visible.** `completed` · `degraded` · `blocked` · `failed` are distinct terminal
   states, and `degraded` never renders as success.
3. **Every number is true.** Cost is computed at runtime from real usage, on every path including
   the free funnel. No hardcoded price, no fabricated metric, no artefact offered that does not
   exist.
4. **Isolation holds at scale** — data isolation (already proven) plus workflow isolation
   (per-client concurrency caps, queue fairness).
5. **Identity has a lifecycle** — a person can be provisioned *and removed*, and their token dies
   with their access.
6. **Browsers and artefacts live off the API host**, so an audit cannot take down the dashboard and
   a report survives the machine that made it.
7. **The five v1 modules each produce a named business outcome, proven end to end at the owner's
   volume bar.**

**Definition of "done" is outcome-based throughout** (§20), per specification §27.

---

## 3 · ARCHITECTURE

Full detail in `TARGET_ARCHITECTURE.md`. The shape of the change:

```
KEEP UNCHANGED          PostgreSQL 16 + RLS · FastAPI layering · psycopg3 raw SQL ·
                        Celery + Redis · Next.js client-side · Docker Compose ·
                        the audit engine · the 55 Web 2.0 publishers · EdDSA auth

CHANGE THE CONTRACT     Job layer: 4 queues by duration class, retry + DLQ,
                        per-client in-flight caps, explicit terminal states

CHANGE THE TRANSPORT    Audit engine: subprocess+stdout+local disk
                          → job contract + object storage (ArtifactStore already exists)
                        WordPress: 4-way silent cascade
                          → capability discovery picks one transport explicitly

SPLIT THE IMAGE         api (no Chromium, no Playwright, no audit venv)
                        worker-browser (all three, own memory envelope)

ADD                     Token denylist · app CSP · locations entity ·
                        web2 accounts as entities · content versions ·
                        site capabilities · DLQ table · job/queue/cost metrics

REDESIGN                Citation submission: tiered strategy with a first-class
                        human-handoff queue and a LOADED cost model
```

**One subsystem is RED (rebuild the approach): citation submission.** Five are ORANGE. Twenty-two
are GREEN or YELLOW. **This is not a rewrite.**

---

## 4 · WORKSTREAMS

| WS | Name | Owns | Migrations |
|---|---|---|---|
| **WS-1** | **Truth** | Remove every false signal: publish cascade states, free-audit cost, demo/mock frontend data, builder branding, dead controls | M6, M5, M14 |
| **WS-2** | **Reliability** | Job contract (retry, DLQ, idempotency, terminal states), staged beat restore, queue split, browser-worker image | M1, M2, M3 |
| **WS-3** | **Identity & Security** | Offboarding, token revocation, app CSP, rate limiter fail-closed, activity log append-only, prompt-injection fencing, vault runbook | M8 |
| **WS-4** | **Data** | Transaction seam, locations entity, web2 accounts, content versions, site capabilities, DLQ table, FK indexes, migration hygiene | M7, M9, M10 |
| **WS-5** | **Content & WordPress** | QA gate calibration, research→job, capability discovery, publish v2, post-publish verification, versioning + revert, SEO-plugin fields | M11 |
| **WS-6** | **Citations** | Loaded cost model, client re-baseline, tiered strategy, human-handoff queue, spec health-checking, proof capture | M12 |
| **WS-7** | **Web 2.0** | Account entities, similarity gate (report-only→blocking), pacing + jitter, per-account caps, platform-mix policy | M13 |
| **WS-8** | **Observability** | Task/queue/DLQ/cost metrics, Sentry tracing, operator page, alerts | M15 |
| **WS-9** | **Testing** | Frontend CI, business-outcome E2E per module, failure-injection suite, provider cassettes, coverage floor | — |
| **WS-10** | **Scale** | Object storage, per-client concurrency caps, cursor pagination + totals, restore drill | M4 |

**Parallelism.** WS-1, WS-8, WS-9 and WS-4's hygiene items are independent and start immediately.
WS-2 is the critical path. WS-6 is blocked on an owner decision, not on engineering.

---

## 5 · DEPENDENCIES

```
  WS-1 Truth ──────────┐   independent, start now
  WS-8 Observability ──┤   independent, start now — makes everything else verifiable
  WS-9 Testing ────────┘   independent, start now (frontend CI is free: it already passes)

  WS-2 Reliability
    M1 job contract ──► M2 beat restore ◄── M5 cost truthfulness (WS-1, MUST precede)
          │                   │
          │                   └──► WS-7 Web 2.0 pacing (needs a scheduler)
          └──► M3 queue split ──► M4 object storage (WS-10)

  WS-4 Data
    M7 txn seam ──► M10 schema ──┬──► WS-5 WordPress publish v2
                                  └──► WS-6 Citations ◄── OWNER DECISION (loaded cost)

  WS-3 Identity — independent, internally sequenced; step 6 time-gated on a 7-day window
```

**Hard ordering rules:**

1. **M5 before M2.** Never restore a spending schedule while the cost ledger lies.
2. **M1 before M2.** Never restore a schedule for tasks that cannot retry and have nowhere to fail
   to.
3. **Restore drill before M10/M11.** Prove you can recover before you change schema and touch live
   client sites.
4. **WS-6 loaded cost before any citation build.** The number decides the design.

---

## 6 · PRIORITIES

### P0 — Blocking / critical foundation

| ID | Item | WS | Why P0 |
|---|---|---|---|
| P0-1 | Run the backend suite and record the result | WS-9 | 219 files whose pass/fail state is unknown. Everything downstream assumes a baseline |
| P0-2 | Free-audit cost hole: gate it, meter it, record real cost, fail the limiter closed | WS-1 | Live denial-of-wallet on an unauthenticated endpoint; defeats `ADM-026` and `MT-005` |
| P0-3 | Job contract: retry + backoff + DLQ + idempotency + terminal states | WS-2 | Prerequisite for every automation claim |
| P0-4 | Stop faking success: explicit `degraded`/`blocked`/`failed`; publish cascade fails visibly | WS-1 | `ERR-002`. Highest perceived-quality return per unit of effort |
| P0-5 | Staged beat restore, one entry per deploy | WS-2 | `AUTO-001`. The product's core promise |
| P0-6 | User offboarding: `suspended` state enforced at login and every request | WS-3 | A departing person currently keeps full access |
| P0-7 | Token revocation (`jti` + Redis denylist) | WS-3 | 7-day irrevocable token |
| P0-8 | Application CSP at the edge | WS-3 | Only mitigation for the token's blast radius |
| P0-9 | Remove builder branding from the plugin and email footer | WS-1 | Hard rule §1.1; visible to end clients today |
| P0-10 | Move the WhatsApp export out of the tree; rotate exposed credentials | WS-3 | `SEC-016`/`SEC-017` |
| P0-11 | QA gate → advisory until calibrated | WS-5 | Hard gate on an uncalibrated score |
| P0-12 | Citation loaded-cost model + client re-baseline | WS-6 | A commercial commitment cannot be honoured as specified |
| P0-13 | Backup schedule + failure alert + **restore drill** | WS-10 | Backups exist and have never been proven |
| P0-14 | Decide D-17 (Policy Radar in v1?) | — | One line of code; shipping 3 of 4 advertised modules is a client-facing problem |

### P1 — Required for core functionality

Queue split + browser-worker image · per-client concurrency caps · `unit_of_work` transaction seam ·
`locations` entity · Web 2.0 accounts as entities · content versioning + revert · WordPress
capability discovery · publish v2 with post-publish verification · SEO-plugin field population ·
Web 2.0 safety layer (report-only → blocking) · prompt-injection fencing · numeric-provenance
validator · AI retry at the `Summarizer` seam · research → job · object storage for artefacts ·
frontend CI · business-outcome E2E per module · failure-injection suite · job/queue/cost metrics ·
operator page · `visibility_timeout` boot assertion · activity log append-only · rate-limit coverage

### P2 — Important

Cursor pagination + totals (`ADM-039`) · unified approval queue (`ADM-038`) · 15 FK indexes ·
N+1 fixes · migration ordinal CI check · provider cassette tests · coverage floor including
`integrations/` · em-dash guard extended to email and ai-assist · internal near-duplicate check ·
factual-claim guard · self-hosted icon font · `integrations/`→`app.services` inversion · repository
hygiene (binaries, orphan dashboard, operator scripts) · vault custody runbook · per-batch cost
ceiling with pre-run confirm

### P3 — Enhancement

Skeleton loading states · list virtualisation · model IDs to settings · split
`web2_publishers.py` · mutation testing in CI · remove `tool_workspaces` duplication · remove the
orphaned site-builder backend

---

## 7 · DATABASE CHANGES

| Change | Priority | Method | Risk |
|---|---|---|---|
| `job_failures` (DLQ) table | P0 | Additive | None |
| `suspended` added to `user_status` | P0 | `ALTER TYPE ... ADD VALUE` | None |
| `locations` entity + backfill one per client | P1 | Expand → backfill → dual-read → contract | Medium — multi-location clients modelled as one need manual splitting |
| `web2_accounts` as a first-class entity + backfill from vault | P1 | Expand → backfill | Low |
| `content_versions` + revert | P1 | Additive | None |
| `site_capabilities` record | P1 | Additive | None |
| `degraded_reason` + terminal-state enum on jobs | P0 | Additive column | None |
| 15 FK indexes (`site_id`, `audit_id` first) | P2 | `CREATE INDEX CONCURRENTLY` | None |
| `activity_log` append-only (revoke UPDATE/DELETE from `authenticated`) | P1 | Grant change | Low — verify no path updates it |
| Migration ordinal-uniqueness CI check | P2 | CI only. **Do not renumber applied files** — the ledger keys on filename | None |

**Standing rule:** expand → migrate → contract. Additive tables and nullable columns only. No
applied migration file is ever renamed.

---

## 8 · API CHANGES

| Change | Priority |
|---|---|
| `POST /users/{id}/suspend` · `/reactivate` | P0 |
| Public audit funnel routed through the cost gate under its own dial + daily cap | P0 |
| `POST /content/research` and `/content/site-design` → 202 + job id + polled status | P1 |
| `GET /wp-connections/{client_id}/capabilities` (discovery result) | P1 |
| `POST /content/jobs/{code}/revert` | P1 |
| `GET /jobs/failures` (DLQ operator surface) | P1 |
| Every list endpoint returns a **total count**; cursor pagination added | P2 |
| `GET /approvals` — unified queue across content, web2, citations, gmb (`ADM-038`) | P2 |
| Uniform `ProviderHealth` on `GET /integrations` naming each missing key **and its consequence** (`ADM-024`) | P2 |

**Compatibility:** all additive except the research endpoints, which change shape. Version them
(`/content/research` → 202) and update the frontend in the same release; `test_contract_lock.py`
guards the rest.

---

## 9 · FRONTEND CHANGES

| Change | Priority |
|---|---|
| `frontend-ci.yml`: `tsc --noEmit` + `next build`, blocking — **both already pass today** | P0 |
| Delete `lib/store.tsx`, `lib/data.ts` seed arrays, `lib/vault.ts` mock keys, `lib/cost.ts` prices; unmount `AiosStoreProvider` | P0 |
| Render `degraded` as a warning with its reason — never a tick | P0 |
| Remove the "Coming soon" Audit Coverage panel (`ADM-014`) | P0 |
| Poll job status for research and site-design instead of blocking | P1 |
| Playwright smoke per portal, incl. a no-dead-controls assertion (`ADM-003`) | P1 |
| Totals + cursor pagination + bulk selection on every table (`ADM-039`) | P2 |
| Self-host the Material Symbols subset (`display=block` currently hides every icon until it loads) | P2 |
| Skeleton loading states | P3 |

---

## 10 · AI CHANGES

| Change | Priority | Requirement |
|---|---|---|
| QA gate → advisory; build a ~50-page human-graded golden set; fit threshold and weights; re-enable | P0 | `CONT-029`, D-4 |
| Production boot assertion: a configured AI dial with no reachable provider is a boot failure, not silent fake output | P1 | `AI-007` |
| Retry with jittered backoff at the `Summarizer` seam — one place, all callers | P1 | — |
| Untrusted-content fencing + CI injection corpus | P1 | `AI-010`, `SEC-020` |
| Numeric-provenance validator on structured output | P1 | `AI-006` |
| Per-batch cost ceiling with explicit pre-run confirmation | P1 | `CONT-010` |
| Em-dash guard extended to email and ai-assist | P2 | `CONT-017` |
| Internal near-duplicate check across a bulk run | P2 | `CONT-043` |
| Factual-claim guard (stats/prices/certifications) | P2 | `CONT-046` |
| Model IDs to settings | P3 | — |

**Preserve without change:** the single `Summarizer` door · universal cost gating · two-tier model
routing · the frozen cache-controlled prefix · the `content_guard` three-layer design · the policy
overlay-never-mutates rule · **`AI-011` — a model cannot trigger spend, publish or credential
access as a side effect.** `AI-011` is the control that keeps a successful prompt injection a
content problem rather than a breach.

---

## 11 · INTEGRATION CHANGES

| Change | Priority |
|---|---|
| `TransientProviderError` / `PermanentProviderError` split driving retry policy | P0 |
| Verify or remove Bing Places and Foursquare submitters (both source-flagged unconfirmed) | P0 |
| Remove `PLATFORM_MEDIUM` (declared, no client, no factory — fails at dispatch) | P1 |
| Uniform `ProviderHealth` surface | P2 |
| Cassette contract tests for every load-bearing provider | P2 |
| Invert `integrations/` → `app.services` dependency | P2 |
| Split `web2_publishers.py` (3,217 LOC) by platform family | P3 |

---

## 12 · WORDPRESS WORK

| Item | Priority |
|---|---|
| **Remove `Xegents AI` from the plugin header and `readme.txt`** — visible in every end-client wp-admin | P0 |
| Publish failures become visible failures; `degraded` is not "complete" | P0 |
| Capability discovery as a read-only probe first; validate against what the cascade actually chose; then let it pick the transport | P1 |
| Publish v2 behind a per-client feature flag; retire the cascade only once proven | P1 |
| Post-publish verification: renders · schema validates · images load · **opens editable in Elementor** · DOM bounded | P1 |
| Content versioning + revert (`WP-032`) | P1 |
| Populate the **active SEO plugin's** fields, not only plugin-private meta (`WP-016`) | P1 |
| Plugin shared-key rotation surface | P2 |
| CI fixture: containerised WordPress + Elementor for E2E | P1 |

**Preserve:** the canonical page model + Elementor/Gutenberg emitters (this is the right
architecture), the plugin's body-key + browser-UA transport (it solves a real, proven host
problem), and design preservation via `_aios_design_css`.

---

## 13 · CITATION WORK

**Sequenced deliberately — the commercial decision comes first.**

| Step | Item | Priority |
|---|---|---|
| 1 | **Build the loaded cost model** against the real 244-row catalogue: API/aggregator cost, CAPTCHA balance, proxy bandwidth, **operator minutes per human-handoff unit** (`CIT-014`) | P0 |
| 2 | **Re-baseline with the client**: present the honest platform-count vs cost-per-unit curve; agree a target that the model supports. Record it as a decision | P0 |
| 3 | Verify or drop the two direct API routes | P0 |
| 4 | `locations` entity so multi-location NAP is modelled (`CIT-001`) | P1 |
| 5 | **Human-handoff queue as a designed state** — a paused, pre-filled browser profile an operator finishes — not a failure path | P1 |
| 6 | Spec health-checking: detect a broken selector **before** a campaign, not during | P1 |
| 7 | Proof per unit: live URL **and screenshot** (`CIT-011`) | P1 |
| 8 | Extend browser coverage, prioritised by the cost model, tier by tier | P1 |
| 9 | Signup automation (`SIGNUP_SPECS` is currently empty) with IMAP confirmation | P1 |

**Preserve:** the `CitationSubmitter` Protocol · the 244-row catalogue with strategy metadata ·
discovery + gap analysis · the per-row claim worker · the status ledger · duplicate prevention ·
the CAPTCHA seam.

---

## 14 · WEB 2.0 WORK

| Item | Priority |
|---|---|
| Web 2.0 accounts as first-class entities (platform, ownership tier, health, property count) — `DATA-016` | P1 |
| Cross-property similarity gate, **report-only for two weeks**, then calibrated, then blocking — `WEB2-007` | P1 |
| Cap on properties per house account, enforced at dispatch — `WEB2-008` | P1 |
| Human-paced posting with jitter (needs beat restored) — `WEB2-003` | P1 |
| Per-client platform mix policy — `WEB2-004` | P1 |
| Per-client accounts on high-authority platforms, provisioned **at campaign start** (D-16) — `WEB2-009` | P1 |
| Remove `PLATFORM_MEDIUM` | P1 |
| Split `web2_publishers.py` by family | P3 |

**Preserve:** all 55 publisher clients and the credential factory. This is the strongest asset in
the off-page tree. **The gap here is a safety layer, not a publishing layer** — and the safety
layer is what stands between the product and penalising a client's site.

---

## 15 · SECURITY WORK

| Item | Priority |
|---|---|
| Public audit funnel behind the cost gate; limiter fails closed | P0 |
| `suspended` state enforced at login **and** every request; suspend/reactivate endpoints | P0 |
| `jti` + Redis denylist; revoke on suspend / password change / logout | P0 |
| Application CSP at the edge | P0 |
| WhatsApp export out of the tree; rotate exposed credentials; establish a non-messaging credential channel | P0 |
| Delete mock secrets (`lib/vault.ts`), demo passwords (`lib/data.ts`), the real NAP in `tools/finish_citation.py` | P0 |
| Shorter access TTL + refresh route | P1 |
| `activity_log` append-only at the database | P1 |
| Prompt-injection fencing + CI corpus | P1 |
| Rate-limit coverage on every spend-causing and write endpoint | P1 |
| Confirm OAuth `state` is signed, single-use and user-bound | P1 |
| Vault master-key custody and rotation runbook | P1 |
| Backups: scheduled, alerting, restore-drilled, covering the artefact store | P0/P1 |
| Upload content-type allow-list | P2 |

**Preserve unchanged:** every control in `SECURITY_AUDIT.md §1`.

---

## 16 · TESTING

| Item | Priority |
|---|---|
| **Run the existing suite; record the result** | P0 |
| Frontend CI: `tsc --noEmit` + `next build`, blocking (**both already pass**) | P0 |
| **Business-outcome E2E, one per v1 module**: audit→readable report · content→live WordPress URL → opens editable · citation→live listing URL + screenshot · web2→published property · client logs in and sees their own audit | P1 |
| Failure-injection suite: provider 429/5xx · publish-cascade exhaustion · task exception · Redis down · subprocess timeout · spend halt armed | P1 |
| `visibility_timeout ≥ task_time_limit` boot assertion + test | P1 |
| Playwright smoke per portal incl. a no-dead-controls assertion | P1 |
| Provider cassette tests (Bing Places, Foursquare first) | P2 |
| Coverage floor, **including `integrations/`** (13.4k LOC currently unmeasured) | P2 |
| Negative tests for constructive invariants: `WP-015` additive-only · `AI-012` no-credentials-in-context · `CIT-023` missing-field-blocks | P2 |
| Containerised WordPress + Elementor CI fixture | P1 |
| Mutation testing on `rbac/matrix.py`, `cost_gate.py`, `content_qa.py` — the harness already exists | P3 |

---

## 17 · DEPLOYMENT

| Item | Priority |
|---|---|
| Split the backend image: `api` (no Chromium/Playwright/audit-venv) and `worker-browser` (all three) | P1 |
| Four worker services by queue class | P1 |
| Object storage for artefacts and backups | P1 |
| Boot assertions become deployment gates — a misconfigured environment fails to start rather than running degraded | P1 |
| `frontend-ci.yml` | P0 |
| Migration ordinal-uniqueness CI check | P2 |
| **Do not adopt Kubernetes.** At 50–100 clients, Compose with four worker services is sufficient and far cheaper to operate | — |

---

## 18 · ROLLBACK

| Level | Mechanism |
|---|---|
| **Code** | Every change additive or feature-flagged. No working path is deleted before its replacement is proven |
| **Schema** | Expand → migrate → contract. New tables and nullable columns only. `CREATE INDEX CONCURRENTLY`. **No applied migration file renamed** — the `deploy.schema_migrations` ledger keys on filename |
| **Jobs** | Per-task decorator migration; **per-entry** beat restore. Blast radius is one task or one schedule entry |
| **Publishing** | Per-client feature flag; the cascade remains until v2 is proven client by client |
| **Web 2.0 gates** | Report-only before blocking |
| **Data** | Restore drill completed **before** schema work begins, not after |
| **The one and only one-way door** | Requiring `jti` on every token — time-gated behind a full 7-day expiry window |

---

## 19 · RISKS

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **Beat restored before retry/DLQ/cost fixes** — silent failure and uncapped spend, at volume | Medium | **Critical** | Hard ordering rule: M1 and M5 before M2. Staged, one entry per deploy |
| R2 | **The citation commitment cannot be honoured.** ~100 platforms at <10¢ loaded is not supported by a hand-maintained-DOM model | **High** | **Critical (commercial)** | Loaded cost model **first**; re-baseline with the client before building. This is why WS-6 is decision-gated |
| R3 | **The existing test suite is already red.** 219 files whose state is unknown | Medium | High | P0-1: run it before anything else. If red, triage is the first engineering task |
| R4 | **Boards go amber when success stops being faked** — the owner may read honest reporting as regression | **High** | Medium | Tell the owner **before** shipping WS-1. Frame it explicitly: the numbers did not get worse, they got true |
| R5 | **Publish v2 breaks a live client site** | Low | High | Read-only capability probe first; compare against what the cascade chose; per-client flag; internal site first |
| R6 | **`locations` backfill mis-splits a multi-location client** | Medium | Medium | Dual-read for one release; manual review of any client with multiple addresses in its profile |
| R7 | **Scope creep during recovery** — the temptation to rewrite GREEN subsystems | **High** | High | `TARGET_ARCHITECTURE.md §15` lists what is deliberately not changing. Treat it as binding |
| R8 | **Undecided items block work**: D-17 (Policy Radar), D-4 (QA gate), D-6 (rankings source), D-15 (credential rotation) | **High** | Medium | Force decisions in the approval meeting for this plan. D-17 is one line of code and a client-facing gap |
| R9 | **Provider contract drift** — Foursquare's documented endpoint already 404s | Medium | Medium | Cassette contract tests; spec health-checking |
| R10 | **The audit engine's host coupling bites before M4 lands** | Medium | Medium | Prioritise object storage; cap concurrent subprocesses immediately |
| R11 | **A one-way door taken early** — requiring `jti` before legacy tokens expire logs everyone out | Low | Medium | Time-gate behind a 7-day window; it is the only irreversible step in the plan |
| R12 | **Recovery timeline is re-estimated without re-baselining with the client** — the original failure mode (spec §2.4) repeats | **High** | High | Any estimate for this plan is delivered **with** a written scope re-baseline, or not delivered |

---

## 20 · DEFINITION OF DONE

Adopting the specification's nine gates (§27.2) and the owner's acceptance bar (§27.3, `[WA-TEAM]`
21/08). **A capability is done when a named business outcome is reliably produced, at volume, with
evidence, and survives failure** — not when an endpoint returns 200.

### Per-feature gates — all nine must pass

| Gate | Bar |
|---|---|
| **1 · Outcome** | A named business outcome is produced end to end, demonstrated on real data |
| **2 · Truth** | Every number traced to a live source. No hardcoded value, no fabricated metric, no artefact offered that does not exist |
| **3 · Degradation** | Every named failure mode deliberately triggered and observed to degrade **visibly** — `degraded` never renders as success |
| **4 · Error handling** | Transient errors retry with backoff; permanent errors fail fast; exhausted retries land in the DLQ with an alert |
| **5 · Security** | Permissions server-side, secrets contained, isolation holds, one negative test per boundary |
| **6 · Performance** | Within budget at expected volume; no endpoint over ~2 s; no client starves another |
| **7 · Observability** | An operator can tell it works and diagnose it when it does not, from the operator page alone |
| **8 · Testing** | Unit + integration + **one true business-outcome E2E**, green in CI |
| **9 · Acceptance** | The owner ran it at volume and accepted it |

### v1 acceptance — the owner's bar, module by module

| Module | Bar |
|---|---|
| **Portal** | Six roles × 17 features enforced with a negative test per boundary. A team member is provisioned, works, and is **offboarded** — and their token stops working immediately |
| **Audit** | **50 audits across 10 businesses.** Every run produces a report readable in the dashboard **and** as a PDF from the same source. Free-audit cost is either genuinely zero or truthfully recorded |
| **Content + WordPress** | **50 pages across 10 businesses**, published to real WordPress sites, each returning a **live URL that opens editable in the site's builder**, design-matched, with SEO fields populated in the site's own SEO plugin, and **revertible** |
| **Citations** | **50 citations across 10 businesses**, each with a live URL **and screenshot**, and a **loaded** cost per unit inside the re-baselined ceiling |
| **Web 2.0** | A representative campaign published end to end with every safety gate enforced — pacing, similarity, account caps, lead approval (per D-16, no blanket 50×10 bar) |

### Platform-wide gates

- **Nothing runs manually that should run on a schedule.** Every beat entry fires, is idempotent,
  and writes a `scheduled_job_runs` row.
- **Nothing fails silently.** Every failure reaches the DLQ or a visible state, and an operator
  page shows it.
- **Nothing spends untracked.** Every provider call passes the gate and commits its real cost —
  the free funnel included.
- **Nobody keeps access they should not have.** Offboarding works and revokes immediately.
- **A restore has actually been performed** from a real backup covering the database **and** the
  artefact store, and the result verified.
- **The builder's name appears nowhere** in the running software, its configuration, its tests, or
  its output.

---

## Decisions required before implementation starts

| # | Decision | Blocks | Recommendation |
|---|---|---|---|
| **D-17** | Is Policy Radar in v1? | AUTO-002, the whole Policy workstream | **Yes.** It is built, it costs near zero, restoring its schedule is one line, and it was delivered to the client as Module 04 of four. Shipping 3 of 4 advertised modules is a client-facing problem, not an engineering one |
| **D-4** | Content QA gate: hard block or advisory? | CONT-029, WS-5 | **Advisory** until calibrated on ~50 human-graded pages, then re-enable with fitted thresholds |
| **Free-audit shape** | Condensed + genuinely free, or comprehensive + metered + disclosed? | AUD-001, AUD-002, M5 | **Condensed + free.** Satisfies both requirements as written and removes the denial-of-wallet vector outright |
| **Citation re-baseline** | What platform count at what loaded cost? | The entire WS-6 | Build the cost model first, then decide **with** the client. Do not build against the current number |
| **D-6** | Rankings source | Rank tracker (v1.1) | Deferred with the module |
| **D-15** | Credential rotation policy | SEC-016, SEC-018 | Decide alongside the vault custody runbook |
