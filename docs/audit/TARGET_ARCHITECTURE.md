# TARGET ARCHITECTURE — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Scope baseline:** v1 = Portal · Audit · Content (incl. WordPress) ·
Citations · Web 2.0 (`DECISIONS_LOG.md` D-1) · **Scale target:** 50–100 clients with headroom (D-3)

---

## 0. The governing principle

> **Keep the foundation. Fix the job layer. Make failure visible. Move browsers and artefacts off
> the API host.**

This is an **evolution**, not a rewrite. Thirteen of twenty-eight subsystems ship unchanged (see
`SALVAGEABILITY_MATRIX.md`). Every decision below is justified against a requirement or a
measured defect — not against a preference.

Two design rules govern everything that follows, because they are the two the current build
violates:

1. **A job that could not do the work is failed or blocked — never completed.** (`ERR-002`)
2. **Every number a client sees is computed in Python and traceable to a source.** (`AI-001`,
   `ADM-001`, `ADM-025`)

---

## 1. Target topology

```
                                   ┌────────────────────────────────────────┐
   Internet ──── 443 ─────────────►│ edge (nginx/Caddy)                     │
                                   │ + HSTS, nosniff, X-Frame-Options,      │
                                   │   Referrer-Policy, **CSP** ← new       │
                                   └──────┬──────────────────────┬──────────┘
                                          │ /                    │ /api/v1
                             ┌────────────▼─────┐   ┌────────────▼──────────────┐
                             │ web (Next.js)    │   │ api (FastAPI, N workers)  │
                             │ unchanged        │   │ REQUEST PATH ONLY:        │
                             └──────────────────┘   │ no subprocess, no browser,│
                                                    │ no >2s synchronous call   │
                                                    └───┬────────────────┬──────┘
                                                        │                │
                    ┌───────────────────────────────────▼───┐   ┌────────▼────────┐
                    │ Redis — broker · cost cache · rate    │   │ PostgreSQL 16   │
                    │ limit · **token denylist** ← new      │   │ RLS (unchanged) │
                    └───┬──────────┬──────────┬─────────────┘   └────────┬────────┘
                        │          │          │                          │
        ┌───────────────▼──┐ ┌─────▼────────┐ ┌▼──────────────────┐      │
        │ worker: sync     │ │ worker:      │ │ worker: browser   │      │
        │ (short, 2-30s)   │ │ content      │ │ ← NEW, own image  │      │
        │ GSC/GA4, indexing│ │ (30s-5min)   │ │ Playwright+Chromium│     │
        │ notifications    │ │ gen, QA, pub │ │ audits, site design│     │
        └──────────────────┘ └──────────────┘ │ citations, web2 QA │     │
                                              └─────────┬──────────┘     │
        ┌──────────────────┐                            │                │
        │ beat  ← RESTORED │                            │                │
        └──────────────────┘                  ┌─────────▼─────────┐      │
                                              │ Object storage    │◄─────┘
        ┌──────────────────┐                  │ (S3/B2)           │
        │ DLQ + operator   │◄─ failed jobs    │ audit artefacts,  │
        │ surface  ← NEW   │                  │ reports, backups  │
        └──────────────────┘                  └───────────────────┘
```

**What changed and why**

| Change | Requirement it serves | Why |
|---|---|---|
| **Four queues by duration class**, not one | `MT-004`, `AUTO-015`, `MT-007` | A 30-min audit and a 2-s GSC sync currently compete for the same 4 slots. One client's bulk run starves everyone. Queue separation is the minimum fix; per-client in-flight caps sit on top |
| **A dedicated browser-worker image** | `MT-013` | Playwright + Chromium are currently baked into the **API** image. A memory spike takes the API down. Separating them also lets browser capacity scale independently — it is the expensive, bursty resource |
| **Object storage for artefacts** | `MT-008`, `DATA-004`, scale | Audit artefacts live on local disk inside the engine's own tree. That pins audits to one host and excludes them from backup. The `ArtifactStore` Protocol **already exists** — this is swapping an implementation, not inventing a seam |
| **A dead-letter queue with an operator surface** | `AUTO-012` | Today a poisoned job vanishes with a `logger.warning` |
| **Beat restored** | `AUTO-001` | The single highest-leverage change in the plan |
| **Redis token denylist** | `SEC-016`, offboarding | A 7-day token is currently irrevocable |
| **CSP at the edge** | `SEC-011` | The app has none; the team already applies a strict one to audit artefacts |

**Deliberately unchanged:** PostgreSQL + RLS, the FastAPI app structure, the Next.js frontend,
Celery as the job engine, Docker Compose as the deployment unit, raw psycopg3 over an ORM.
None of these is a limiting factor at 50–100 clients, and each replacement would cost more than
it returns.

---

## 2. Frontend

**Retain:** Next.js 15 App Router, React 19, TanStack Query, the single `lib/api.ts` fetch seam,
the three-portal layout split, self-hosted variable font.

| Decision | Rationale |
|---|---|
| **Delete `lib/store.tsx`, the `lib/data.ts` seed arrays, `lib/vault.ts` mock keys, and the hardcoded prices in `lib/cost.ts`** | `ADM-003`, `ADM-025`. Verified unreferenced. They ship plaintext demo passwords and fabricated prices |
| **Add `frontend-ci.yml`: `tsc --noEmit` + `next build`, blocking** | Both already pass. This is free and locks in the current health |
| **Add Playwright smoke tests per portal** | `ADM-003` has no mechanical enforcement today, which is exactly why dead controls kept reaching the client |
| **Add total count + cursor pagination to every list endpoint and table** | `ADM-039`. No endpoint returns a total, so no page control can exist |
| **Self-host the Material Symbols subset** | `display=block` from a third-party host hides every icon until it loads. The team already solved this for the body font |
| **Keep client-side data fetching; do not migrate to RSC** | Bundles are 103–148 kB and the build is clean. An RSC migration is a large change with no requirement behind it |
| **Add skeleton states** | 41 files handle `isLoading`; zero use a shaped placeholder |

---

## 3. Backend

**Retain:** the router → service → repo → RLS layering; the Protocol-fronted integration seams;
strict mypy; the pure-service discipline.

| Decision | Rationale |
|---|---|
| **Add a `unit_of_work(user_id)` transaction seam** that yields one cursor usable by several repos | Today `rls_connection()` opens a transaction **per repo call**, so client creation is three non-atomic writes with two `except: pass` blocks. `ADM-009`, `DATA-002`. The SQL is untouched — repos gain an optional `cur` parameter |
| **No endpoint may exceed ~2 s.** `POST /content/research` and `POST /content/site-design` become jobs with polled status | `PERF-*`. A 40–60 s synchronous call holds one of two uvicorn workers and forced `proxyTimeout: 180_000`. The service functions are reusable verbatim |
| **Invert the `integrations/` → `app.services` dependency** by moving the cost-gate Protocol into `integrations/` | `mcp_gateway.py` imports `app.services.cost_gate`; `app/db/policy_repo.py` imports `app.services.policy_baseline`. Small, mechanical, and it makes the seams extractable |
| **Boot-time assertions in `validate_settings`** | Three invariants are currently comments or nothing: `visibility_timeout ≥ task_time_limit` (`AUTO-011` — silent double spend when broken), a real AI provider is reachable in production (`AI-007`), and the audit engine path resolves |
| **Keep raw SQL; do not adopt an ORM** | The SQL safety discipline is exemplary and `test_repo_sql_parity.py` guards drift. An ORM would put an abstraction between the code and the RLS model that is the security boundary |

---

## 4. Database

**Retain:** PostgreSQL 16, RLS as the tenant boundary, 195 policies, the two-seam connection model,
lifecycle enforcement via triggers, migrations-as-source-of-truth.

| Change | Requirement | Rationale |
|---|---|---|
| **Renumber the colliding migrations and add a CI ordinal-uniqueness check** | — | Two `0070`, two `0072`, `0052` missing, applied in **lexical** order. The ordering guarantee the runner claims no longer exists |
| **Add a `locations` entity** (client → locations → business_profiles) | `DATA-010`, `CIT-001`, `ADM-010` | Multi-location clients cannot be modelled today. This is the single largest schema gap |
| **Promote Web 2.0 accounts to a first-class entity** (platform, ownership tier, health, property count) | `DATA-016` | An account is currently only a vault secret, so account health and per-account property caps — the controls that prevent site-reputation-abuse penalties — have nowhere to live |
| **Add a `content_versions` table with a revert path** | `WP-032`, `CONT-*` | Nothing can be undone today |
| **Add a `site_capabilities` record** | `WP-005`, `DATA-003` | Capability discovery has nowhere to store its result |
| **Add a `job_failures` (DLQ) table** | `AUTO-012` | — |
| **Index the 15 unindexed FK columns**, `site_id`/`audit_id` first | `PERF-*` | Postgres does not auto-index the referencing side; parent deletes sequential-scan children |
| **Make `activity_log` genuinely append-only** — revoke UPDATE/DELETE from `authenticated` | `DATA-021`, `ADM-032` | Append-only is currently a convention |
| **Add `suspended` to `user_status`** | offboarding | See §8 |

---

## 5. Services and workers

### 5.1 Queue topology

| Queue | Workload | Concurrency | Time limit |
|---|---|---|---|
| `sync` | GSC/GA4 sync, indexing, notifications, billing sweep | high | 120 s |
| `content` | generation, QA, guard, publish | medium | 600 s |
| `browser` | audits, site design, citation submits, visual QA — **own image** | low, memory-bounded | 1800 s |
| `beat` | dispatchers only; they fan out, never do work | 1 | 60 s |

Plus a **per-client in-flight cap** enforced at dispatch (`MT-004`), so one client's 50-page bulk
run cannot occupy every slot.

### 5.2 The job contract — every task, without exception

```python
@celery_app.task(
    name="…", bind=True,
    autoretry_for=(TransientProviderError, ConnectionError),
    retry_backoff=True, retry_backoff_max=300, retry_jitter=True,
    max_retries=5,
)
def task(self, …): ...
```

Six rules:

1. **Idempotency key** on every task that mutates external state (`AUTO-004`).
2. **Bounded retry with jittered backoff** on transient errors; **permanent errors do not retry**.
3. **Exhausted retries land in the DLQ** with the full context, and raise an alert (`AUTO-012`).
4. **Overlap lock** on every beat-driven job (`AUTO-006`).
5. **Terminal states are explicit and distinct**: `completed` · `degraded` · `blocked` · `failed`.
   **`degraded` is never rendered as success.**
6. **Every run writes to `scheduled_job_runs`** so the operator can answer "what ran, when, how".

This directly replaces today's "never re-raise" doctrine, which is why a transient Serper 503
currently fails a job permanently and silently.

---

## 6. AI layer

**Retain without change:** the single `Summarizer` Protocol door; the universal `GatedSummarizer`
wrapper; two-tier model routing (Haiku default, Sonnet heavy); the frozen cache-controlled system
prefix; **`AI-011` — a model cannot trigger spend, publish or credential access as a side effect**;
the `content_guard` three-layer design; the policy overlay-never-mutates rule.

| Change | Requirement |
|---|---|
| **Retry with jittered backoff at the `Summarizer` seam** — one place, all callers. `tenacity` is already a dependency | `AUTO-*` |
| **Untrusted-content fencing**: every crawled/fetched block wrapped in an explicit escaped delimiter, with a system-prompt rule that fenced content is data. Plus an injection corpus in CI | `AI-010`, `SEC-020` |
| **Numeric-provenance validator**: reject any number in a model's structured output that does not correspond to a computed input | `AI-006` |
| **Production boot assertion**: a configured AI dial with no reachable provider is a boot failure, not a silent degradation to fake output | `AI-007` |
| **Per-batch cost ceiling with explicit pre-run confirmation** for bulk content and Web 2.0 campaigns | `CONT-010` |
| **QA gate to advisory** until calibrated against ~50 human-graded pages | `CONT-029`, D-4 |
| **Model IDs move to settings** | maintainability |

---

## 7. Integration layer

**Retain:** the Protocol-per-provider pattern with a deterministic fake for every real client. It
is why the unit suite runs offline and why providers are swappable.

| Change | Rationale |
|---|---|
| **Cassette (recorded-response) contract tests for every load-bearing provider** | `CIT-010`. No provider contract is verified anywhere today — which is how Foursquare's documented write endpoint being a 404 reached the codebase |
| **A uniform `ProviderHealth` surface** — last success, last failure, degraded capability | `ADM-024` requires naming every missing key **and the consequence of its absence** |
| **Split `web2_publishers.py` (3,217 LOC) into one module per platform family** | A change to the shared `HttpProviderClient` currently touches 55 clients at once |

---

## 8. WordPress layer

```
   page_model (canonical, builder-agnostic)   ← KEEP, this is right
        ├── elementor emitter    (KEEP — pure, deterministic, design-aware)
        ├── gutenberg emitter    (KEEP)
        └── flat HTML + design CSS (KEEP)
                    │
        ┌───────────▼──────────────────────────────┐
        │ capability discovery  ← NEW, runs first  │  WP-005
        │ WP/PHP ver · REST · app passwords ·      │
        │ Elementor+ver+licence · Gutenberg ·      │
        │ theme · ACF show_in_rest · SEO plugin ·  │
        │ caching · page inventory · sitemap ·     │
        │ robots · upload limits                   │
        └───────────┬──────────────────────────────┘
                    │ picks ONE transport, explicitly
        ┌───────────▼──────────┬──────────────────┐
        │ AIOS Publisher plugin│ REST app-password│
        └───────────┬──────────┴──────────────────┘
                    │
        ┌───────────▼──────────────────────────────┐
        │ post-publish verification ← NEW  CONT-041│
        │ renders · schema validates · images load │
        │ opens editable · DOM bounded (WP-024)    │
        └───────────┬──────────────────────────────┘
                    │
              content_versions + revert  ← NEW  WP-032
```

**The single most important change: the four-way silent fallback cascade is replaced by
capability discovery choosing one transport explicitly.** Today `workers/tasks/content.py`
tries plugin → REST → plugin → REST → artifact-only, swallowing each failure, and finishes as
"complete". In the target, the transport is known **before** the publish, a failure is a
**failure**, and `degraded` is a distinct terminal state the UI renders as not-published.

Also: **populate the active SEO plugin's own fields** (Yoast/RankMath/AIOSEO) rather than only
writing plugin-private meta (`WP-016`), and **remove the builder's name** from the plugin header
(§1.1 hard rule — currently visible in every end-client's wp-admin).

---

## 9. Citation layer — the one genuine redesign

**Do not scale hand-written DOM selectors.** Three specs against 151 `bot_fillable` directories is
not a coverage shortfall to close by writing 148 more; it is a **maintenance model that does not
work**, because directory forms change without notice and every change silently breaks a
submission path.

```
                       canonical NAP (per LOCATION ← new entity)
                                    │
                          citation audit + gap analysis   ← KEEP, this is good
                                    │
                      ┌─────────────┴─────────────┐
                      │   prioritised target set  │
                      └─────────────┬─────────────┘
       ┌──────────────────┬─────────┴────────┬──────────────────────┐
       │ TIER 1           │ TIER 2           │ TIER 3               │
       │ documented APIs  │ aggregators      │ browser automation   │
       │ + partner writes │ (fan out to many)│ — the EXCEPTION      │
       │ deterministic    │ best $/listing   │ spec health-checked  │
       └────────┬─────────┴────────┬─────────┴──────────┬───────────┘
                │                  │                    │ fails / CAPTCHA
                └──────────────────┴────────────────────┤
                                                        ▼
                                          ┌─────────────────────────┐
                                          │ HUMAN HANDOFF QUEUE     │  ← first-class
                                          │ paused browser profile, │     not a failure
                                          │ pre-filled, operator    │
                                          │ finishes, cost recorded │
                                          └─────────────────────────┘
                                    │
                     proof per unit: live URL **+ screenshot**  (CIT-011)
                     loaded cost incl. human time               (CIT-014)
```

**Reusable as-is:** the `CitationSubmitter` Protocol, the 244-row catalogue with strategy
metadata, discovery and gap analysis, the per-row claim worker, the status ledger, duplicate
prevention, the CAPTCHA seam.

**Must be rebuilt:** the platform-tier strategy, spec health-checking, the human-handoff queue as
a designed state rather than a failure, and the **loaded** cost model.

**Commercial precondition.** `CIT-014` (loaded cost) must be modelled **before** the ~100-platform
target and the <10¢ figure are re-affirmed with the client. With 151 directories requiring human
handoff, operator time — not API spend — is the dominant cost term. See
`REQUIREMENT_GAP_ANALYSIS.md §13`.

---

## 10. Web 2.0 layer

**Retain:** all 55 publisher clients, the credential factory, per-client vault scoping, the
lead-approval gate.

**Build the safety layer** — this is what stands between the product and penalising the client's
site:

| Control | Requirement |
|---|---|
| **Web 2.0 account as a first-class entity** — platform, ownership tier, health, property count | `DATA-016` |
| **Cap on properties per house account**, enforced at dispatch | `WEB2-008` |
| **Cross-property similarity gate**, measured within a client **and** across clients sharing an account | `WEB2-007` |
| **Human-paced posting with jitter**, per platform and per account | `WEB2-003` |
| **Per-client platform mix policy** | `WEB2-004` |
| **Per-client accounts on high-authority platforms**, provisioned at campaign start (D-16) | `WEB2-009` |

Remove the dangling `PLATFORM_MEDIUM` (declared, no client, no factory — it will fail at dispatch).

---

## 11. Authentication and authorization

**Retain:** EdDSA with the single-entry algorithm allow-list, Argon2id, owner-only provisioning in
one privileged transaction, the 17×6 matrix, RLS as the real boundary, the runtime OpenAPI guard
sweep.

| Change | Requirement |
|---|---|
| **Add `suspended` to `user_status`; check it in `login()` **and** `get_current_user`; add suspend/reactivate endpoints** | offboarding — *currently absent from the requirements matrix entirely* |
| **`jti` claim + Redis denylist**, invalidated on suspend, password change and logout | `SEC-016` |
| **Shorten the access TTL and add a refresh route** | 7 days is the session because there is no refresh; shortening without one logs staff out mid-work |
| **Rate limiter fails closed on paid and auth paths** | currently fails open on any Redis error |
| **CSP at the edge** | `SEC-011` |

---

## 12. Observability

Today: three HTTP metrics, optional Sentry with tracing off, no job visibility at all.

| Layer | Target |
|---|---|
| **Metrics** | Per-task duration/failure/retry counters · queue depth by queue · DLQ depth · in-flight browser subprocesses · **cost committed per feature per client** · provider error rate |
| **Traces** | Sentry `traces_sample_rate > 0` in production; one trace per job spanning gate → provider → commit |
| **Logs** | Keep structlog + request-id; add a **job-id** propagated through every task log line |
| **Operator surface** | One page answering: what is scheduled · what ran in 24 h · what failed and why · what is in the DLQ · what spend was committed. `ADM-021` asks for exactly this |
| **Alerts** | Backup failure · DLQ depth > 0 · spend approaching cap · provider degraded · beat not firing |

**Why this matters more than it looks.** The product's value proposition is *"most of the work runs
on its own"*. There is currently **no way to see the work running.** That is why "nothing runs on a
schedule" could persist as a state of the world — nothing would have reported it.

---

## 13. Deployment

**Retain:** Docker Compose on a single host, nginx+certbot, the one-shot migrate service with a
`deploy.schema_migrations` ledger.

| Change | Rationale |
|---|---|
| **Split the backend image**: `api` (no Playwright, no Chromium, no audit venv) and `worker-browser` (all three) | `MT-013`. The API image currently carries Chromium; a browser memory spike takes the API with it. Also shrinks the API image substantially |
| **Object storage for artefacts and backups** | `MT-008` |
| **Add `frontend-ci.yml`** | `tsc --noEmit` + `next build`, blocking |
| **Boot assertions become deployment gates** | A misconfigured environment should fail to start, not run degraded |
| **Do not adopt Kubernetes** | At 50–100 clients, Compose with four worker services is sufficient and far cheaper to operate. Revisit only if the client count target changes materially |

---

## 14. Security

Preserve every control in `SECURITY_AUDIT.md §1` unchanged. Add:

1. User suspension enforced at login and at every request (§11).
2. Token revocation via `jti` + denylist (§11).
3. Application CSP (§11).
4. Public audit funnel behind the cost gate with its own budget — closes the denial-of-wallet
   vector (`SEC-C`).
5. Prompt-injection fencing (§6).
6. `activity_log` append-only at the database (§4).
7. Vault master-key custody and rotation runbook.
8. Backups: scheduled, alerting, restore-drilled, covering the artefact store.
9. Rate limiter fails closed on paid and auth paths.
10. WhatsApp export out of the repository; credentials rotated.

---

## 15. What is deliberately NOT changing, and why

Recording this matters as much as the changes — it is the guard against scope creep in the
recovery itself.

| Not changing | Why |
|---|---|
| PostgreSQL + RLS | The isolation model is correct and proven against real Postgres from a real client identity |
| Raw psycopg3 over an ORM | The SQL discipline is exemplary and `test_repo_sql_parity.py` guards drift. An ORM would obscure the RLS model that *is* the security boundary |
| Celery + Redis | The problem is the job **contract**, not the job **engine** |
| Next.js client-side fetching | Bundles are 103–148 kB, build and typecheck are clean, and no requirement asks for SSR |
| The audit engine itself | 20k LOC of deterministic, checklist-driven analysis with its own CI. Only its **transport** changes |
| The 55 Web 2.0 publishers | Real, working API integrations. Only the **safety layer** around them is new |
| FastAPI, the router/service/repo layering, Protocol-fronted integrations | Sound, tested, and not a limiting factor at the target scale |
