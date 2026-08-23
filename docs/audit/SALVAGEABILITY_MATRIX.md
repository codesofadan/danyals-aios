# SALVAGEABILITY MATRIX — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit:** `79d1036`

**Classification**

| Band | Meaning |
|---|---|
| 🟢 **GREEN** | Safe to retain. Ship it. Changes are additive. |
| 🟡 **YELLOW** | Retain after refactoring. The design is right; specific defects need fixing. |
| 🟠 **ORANGE** | Significant redesign required. The abstraction is wrong or the coupling is fatal to the target scale, but the domain logic and data are worth carrying forward. |
| 🔴 **RED** | Rebuild recommended. What exists cannot reach the requirement by increments. |

**Guiding principle applied.** I have not recommended rebuilding anything merely because it is
imperfect, and I have not preserved anything merely because it took effort. The test is: *can the
requirement be reached by fixing this, or does fixing it cost more than replacing it?*

**Headline: 1 subsystem is RED. 4 are ORANGE. The remaining 22 are GREEN or YELLOW.**
This is not a rewrite candidate.

---

## The matrix

| # | Subsystem | Band | Technical reasoning |
|---|---|---|---|
| 1 | **Authentication (EdDSA + Argon2id)** | 🟢 GREEN | Single-entry algorithm allow-list defeats alg-confusion and `none`; `aud`/`iss`/`exp`/`sub` verified and required; constant-time login with a dummy-hash path. The only change needed is **additive**: check `status`, add a `jti` + denylist. Nothing here is wrong. |
| 2 | **Tenant isolation (RLS)** | 🟢 GREEN | 195 policies; every table `ENABLE` **and** `FORCE`; txn-local identity set through a **bound parameter** (chosen over `SET LOCAL` precisely because `SET LOCAL` cannot bind); `RESET ALL` on pool return; autocommit asserted off. Proven from a real client identity against real Postgres in `test_portal_isolation.py`. This is the best-engineered part of the system. |
| 3 | **Data-access layer (psycopg3 repos)** | 🟡 YELLOW | SQL safety is exemplary — every value bound, identifiers via `sql.Identifier`. The defect is structural: `rls_connection()` opens **a transaction per call**, so no business operation spanning two repos is atomic. Add a transaction seam (`with unit_of_work(user_id) as cur:`) that both repos accept; the SQL itself is untouched. |
| 4 | **RBAC / permission matrix** | 🟢 GREEN | 17 features × 6 roles × 4 templates, enforced server-side at 260/305 endpoints, with a runtime OpenAPI sweep test that fails the build on an unguarded route. Only gap is the **missing offboarding state**, which is an addition, not a redesign. |
| 5 | **Key vault (AES-256-GCM)** | 🟢 GREEN | Correct scoping, masked list, owner-only reveal, master key outside Postgres, secrets never logged. Needs a **custody and rotation runbook** — a document, not code. |
| 6 | **Cost gate + runtime pricing** | 🟡 YELLOW | The gate's ordering (halt → dial → cache → cap → call → commit) is right, and `pricing.py` computes real cost from real usage. Two defects, both fixable in place: the **public audit path bypasses the gate entirely** and commits `0.0`; and `POST /keyword-research/research` blocks silently. Neither is architectural. |
| 7 | **Celery job layer** | 🟠 ORANGE | The tasks themselves are well written and mostly idempotent. The **layer** is not viable as configured: schedule empty, **zero retry on all 39 tasks**, no dead-letter queue, one queue for 30-minute audits and 2-second syncs, no per-client fairness. Every task can be kept; the surrounding contract must be redesigned. |
| 8 | **Audit engine (`danyals-audit-system`)** | 🟢 GREEN | 20k LOC, 10 analyzers, 4 YAML checklists, deterministic severity-weighted scoring, its own CI. The domain logic is genuinely good and there is no reason to touch it. |
| 9 | **Audit engine *integration*** | 🟠 ORANGE | Subprocess + second interpreter + **stdout parsing** + **local-filesystem artefacts**. The adapter is defensively written (owns its timeout, never half-owns a run) but the contract pins every audit to one host, keeps artefacts out of backup, and puts Chromium in the API's container. Keep the engine; replace the transport with a job contract + object storage behind the existing `ArtifactStore` Protocol. |
| 10 | **Audit artefact serving (HTML/PDF)** | 🟢 GREEN | One source for both viewer and PDF; strict CSP on the served route; sandboxed `srcdoc` iframe **without** `allow-scripts`; honest artifact flags so a missing PDF is never offered. Correct and secure. |
| 11 | **Content generation + guard** | 🟢 GREEN | `content_guard`'s three-layer design (pure detection → selective writer rewrite → **unconditional** strip) gives a hard guarantee that does not depend on the model behaving. The generator is deterministic given a fixed writer. Extend the guard to emails and ai-assist; otherwise leave alone. |
| 12 | **Content QA gate** | 🟡 YELLOW | The rubric is deterministic and the dimensions are sensible. The defect is a **hard publish block at a self-declared uncalibrated threshold**. Ship it in advisory mode, build a ~50-page human-graded golden set, fit the threshold and weights, then re-enable. No code redesign. |
| 13 | **Content research** | 🟡 YELLOW | The research itself is right — live web search, strict JSON, SSRF-guarded, cost-gated, degrades honestly. The **shape** is wrong: a 40–60 s synchronous HTTP call that forced `proxyTimeout: 180_000`. Move to a job with polled status; the service function is reusable verbatim. |
| 14 | **Page model + Elementor/Gutenberg emitters** | 🟢 GREEN | A canonical builder-agnostic page model feeding two emitters is exactly the architecture `WP-006` asks for. `elementor.py` is pure, deterministic (SHA-1 ids, no `Date`/`random`), and design-profile aware. Needs verification against a live Elementor install — a test gap, not a design gap. |
| 15 | **WordPress plugin (AIOS Publisher)** | 🟡 YELLOW | Solves a **real, proven** problem: hosts that strip the Authorization header and disable Application Passwords. Shared key in the JSON body plus a browser UA is the correct workaround. Two fixes: **remove the builder's name** (it is visible in every client's wp-admin) and add key rotation. |
| 16 | **WordPress publish orchestration** | 🟠 ORANGE | The four-way fallback cascade **swallows every failure and marks the job complete** with `degraded=True`. An operator can hit a green board with zero live pages. Also missing: capability discovery, SEO-plugin field population, post-publish verification, and revert. The individual publishers (item 15, `wordpress.py`) are fine; the **orchestration** needs redesign around explicit, visible states. |
| 17 | **Web 2.0 publishers** | 🟢 GREEN | **55 concrete API client classes, 52 credential factories.** Real HTTP integrations — Ghost Admin, AT Protocol, Mastodon, Notion, Zenodo, Sanity, Storyblok, Hygraph, MetaWeblog, LiveJournal XML-RPC. This is the strongest asset in the off-page tree and the only off-page capability that plausibly scales as built. Remove the dangling `PLATFORM_MEDIUM`. |
| 18 | **Web 2.0 safety layer** | 🟠 ORANGE | Publishing works; **not harming clients** does not. No human-paced posting or jitter, no cross-property similarity gate (within or across clients), no enforced cap on properties per house account, no per-client platform-mix policy. At 50+ platforms this is what triggers site-reputation-abuse penalties. The publishers stay; the safety layer must be designed and built. |
| 19 | **Citation catalogue + audit/gap analysis** | 🟢 GREEN | 244 directories seeded with strategy metadata; discovery (904 LOC) and NAP-alignment analysis are real and useful. This is genuinely valuable data and logic. |
| 20 | **Citation submission automation** | 🔴 **RED** | **3 `FORM_SPECS` against 151 `bot_fillable` directories. `SIGNUP_SPECS` is empty. Both direct APIs are source-flagged unconfirmed** (Foursquare's documented write endpoint 404s). This cannot reach ~100 platforms by adding selectors — hand-maintained DOM specs for 100 sites is a permanent, unfunded maintenance burden, and the loaded cost is not 10¢/unit. **Rebuild the approach**, not the code: prioritise aggregators and documented APIs, treat browser automation as the exception with a human-handoff queue, and re-baseline the platform count and cost with the client before building. The `CitationSubmitter` Protocol, the job model, the status ledger, the CAPTCHA seam and the per-row claim worker are all reusable. |
| 21 | **Frontend application shell** | 🟡 YELLOW | Typechecks clean, builds clean, 103 kB shared bundle, a11y attributes in 53 of 136 components, one fetch seam, sensible error envelope handling. Needs: **delete the dead demo store, the mock vault keys and the hardcoded prices**; add CI; add a total count + cursor pagination. The architecture is fine. |
| 22 | **Frontend testing** | 🔴→🟡 | There is nothing to salvage because **nothing exists** — but `tsc` and `next build` already pass, so the first CI job is free. Classified YELLOW because the remedy is purely additive. |
| 23 | **Client portal** | 🟢 GREEN | `CurrentClientDep` pins `client_id` server-side and never accepts it from a body; portal views omit `mrr`/`cost`/`error`/`*_path`; proven by `test_portal_isolation.py` against real Postgres. Correct design, correctly proven. |
| 24 | **Task board + lifecycle** | 🟢 GREEN | Lifecycle enforced by **database triggers**, not just the API. Illegal transitions are rejected at the data layer. Exemplary. |
| 25 | **Policy Radar** | 🟢 GREEN | Built, working on demand, idempotent per UTC day, and its "Apply" writes an **overlay only** — an AI recommendation can never rewrite stored evidence. Restoring the daily schedule is one line. **Blocked on decision D-17, not on engineering.** |
| 26 | **Backups** | 🟡 YELLOW | Genuinely well built: `pg_dump` subprocess with the password via `PG*` env (never argv), traversal-safe root, B2 offsite, owner-only restore requiring an echoed snapshot id. Three fixes: **schedule it**, **alert on failure**, **extend scope to the artefact store**, and run a documented restore drill. |
| 27 | **Observability** | 🟠 ORANGE | Structured JSON logging with request-id propagation is good. Everything else is thin: **three** Prometheus metrics, all HTTP; **zero** worker, queue, job or cost metrics; Sentry optional with tracing off. For a platform whose value proposition is autonomous jobs, there is no way to see the jobs. Needs building, not fixing. |
| 28 | **Repository hygiene** | 🟠 ORANGE | Committed binaries (~1.6 MB of zips + a 436 kB PNG), one-off operator scripts carrying a real NAP and phone number, an orphaned second dashboard, a client's WP theme, a scratch directory, **duplicate migration ordinals (two `0070`, two `0072`) under a lexical-order runner**, and the WhatsApp export sitting in the working tree. None of this is hard to fix; all of it should be. |

---

## Band summary

| Band | Count | Subsystems |
|---|---|---|
| 🟢 **GREEN** | 13 | Auth · RLS · RBAC · Vault · Audit engine · Artefact serving · Content generation+guard · Page model+emitters · Web 2.0 publishers · Citation catalogue+analysis · Client portal · Task lifecycle · Policy Radar |
| 🟡 **YELLOW** | 9 | Repo layer · Cost gate · Content QA gate · Content research · WP plugin · Frontend shell · Frontend testing · Backups · *(Web 2.0 publisher registry cleanup)* |
| 🟠 **ORANGE** | 5 | Celery job layer · Audit engine integration · WordPress publish orchestration · Web 2.0 safety layer · Observability · Repository hygiene |
| 🔴 **RED** | 1 | Citation submission automation |

---

## What this means for the plan

**Do not rewrite this system.** Thirteen subsystems are ready to ship as they stand, including
every part of the security and isolation foundation — the part that is most expensive to build
and most dangerous to get wrong. A rewrite would consume the recovery budget reproducing work
that is already correct.

**The recovery is concentrated in three places:**

1. **The job layer (ORANGE).** Restore the schedule, add retry and a dead-letter queue, split the
   queue by duration class, add per-client fairness. This one workstream converts most
   "PARTIALLY WORKING" features to "WORKING" without touching the features themselves.
2. **Failure visibility (ORANGE, cross-cutting).** The publish cascade, the free-audit cost log
   and the AI degradation path all fake success. Fixing this is mostly deleting `except: pass`
   and adding explicit terminal states — cheap work with the highest perceived-quality return.
3. **Citations (RED).** This needs a **commercial** decision before an engineering one. The
   3-of-151 coverage gap cannot be closed by writing more selectors, and the <10¢ commitment
   cannot be honoured on a hand-maintained-DOM approach. Re-baseline with the client.

Web 2.0 is the pleasant surprise: 55 working API publishers is real, shippable capability, and
the gap there is a **safety layer**, not a publishing layer.
