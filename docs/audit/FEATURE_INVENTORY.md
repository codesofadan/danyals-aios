# FEATURE INVENTORY — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit:** `79d1036`

**Status vocabulary:** WORKING · PARTIALLY WORKING · BROKEN · PLACEHOLDER · MOCK · UNUSED ·
DUPLICATED · OBSOLETE · MISSING

**Evidence basis.** Code-verified by reading source. The backend suite was **not executed**
(no compatible interpreter — see `REPOSITORY_ARCHITECTURE.md` preamble), so "WORKING" here means
*the code path is complete, guarded, tested in-repo and has no identified defect* — not
*observed running in production*. The frontend **was** typechecked and built.

**Test-coverage column** = whether a dedicated test file exists and what it exercises
(`unit-fake` = against injected fakes; `integration` = against real Postgres/Redis).

---

## A · PLATFORM CORE

| # | Feature | Location | Implementation | Deps | Status | Test coverage | Quality | Security | Perf | Req ID | Recommendation |
|---|---|---|---|---|---|---|---|---|---|---|---|
| A1 | Login / EdDSA token mint | `app/routers/auth.py`, `app/core/auth.py` | Argon2id verify + Ed25519 sign; `_ALLOWED_ALGS=["EdDSA"]`; dummy-hash constant-time path | Postgres | **WORKING** | `test_auth.py`, `test_auth_endpoints.py`, `test_login.py` | High | **Strong crypto; but never checks `status`** | Good | SEC-001 | **KEEP** + add status check |
| A2 | Session lifetime / revocation | `app/config.py:72` | 7-day TTL, no refresh, no `jti`, no denylist | — | **MISSING** | none | — | **P0** | — | SEC-016 | **ADD** |
| A3 | User provisioning | `app/services/provisioning.py` | Single `privileged_connection()` transaction; name+email+role+overrides atomically | Postgres | **WORKING** | `test_provisioning.py` | High | Good | Good | ADM-005 | **KEEP** |
| A4 | User **deactivation / offboarding** | — | Does not exist. Enum has no disabled state; no DELETE/deactivate endpoint; `manage_team` advertises it | — | **MISSING** | none | — | **P0** | — | *(unstated)* | **ADD** |
| A5 | RBAC matrix (17 features × 6 roles × 4 templates) | `app/rbac/matrix.py`, `app/routers/rbac.py` | Server-side `require_perm` / `require_role` / `require_feature`; per-user grants in `user_feature_grants` | Postgres | **WORKING** | `test_rbac_matrix.py`, `test_feature_grants.py` | High | Good | Good | ADM-030 | **KEEP** |
| A6 | Route auth coverage | all routers | 260/305 explicit guards; 17 auth-only RLS-scoped reads; runtime OpenAPI sweep test | — | **WORKING** | `test_route_auth_guard.py` | High | Good | Good | SEC-002 | **KEEP** |
| A7 | Tenant isolation (RLS) | `db/migrations/*`, `app/db/database.py` | 195 policies, every table ENABLE + FORCE, txn-local `app.user_id` via bound `set_config`, `RESET ALL` on return | Postgres | **WORKING** | `test_rls_check.py` + CI RLS gate | **Excellent** | Strong | Good | MT-001 | **KEEP** |
| A8 | Key vault (AES-256-GCM) | `app/services/vault.py`, `app/routers/vault.py` | Masked list on `manage_vault`; reveal owner-only; master key never in Postgres | Postgres | **WORKING** | `test_vault.py` | High | Good | Good | ADM-031 | **KEEP** |
| A9 | Activity log | `app/services/activity.py`, `db/0005` | Append-only; `record_activity` on mutations | Postgres | **PARTIALLY WORKING** | `test_activity.py` | Medium | Good | Good | ADM-032 | **FIX** — not every mutation path calls it; no DB-level enforcement |
| A10 | Cost gate | `app/services/cost_gate.py` | halt → dial → cache → cap → call → commit; typed 402 `spend_halted` | Redis, Postgres | **WORKING** | `test_cost_gate.py`, `test_dial_registration.py` | High | Good | Good | ADM-026/027 | **KEEP** |
| A11 | Runtime cost pricing | `app/services/pricing.py` | Real token/query-derived cost per provider | — | **WORKING** | `test_pricing.py` | High | Good | Good | ADM-025 | **KEEP** |
| A12 | Cost ledger truthfulness (free audit) | `workers/tasks/audit.py:517` | `_safe_record_cost(store,row,0.0)` on a run that **does** spend | — | **BROKEN** | none for this path | **P0** | Denial-of-wallet | — | ADM-025/026 | **FIX** |
| A13 | Rate limiting | `app/core/ratelimit.py` | Redis fixed-window; **fail-open on error**; applied to 6 endpoints only | Redis | **PARTIALLY WORKING** | `test_ratelimit.py` | Medium | Weak coverage | Good | SEC-* | **REFACTOR** |
| A14 | Structured logging + request id | `app/logging_setup.py`, `app/core/middleware.py` | structlog JSON, request-id outermost | — | **WORKING** | `test_metrics.py` | High | Good | Good | OPS-* | **KEEP** |
| A15 | Metrics | `app/core/metrics.py` | **3 metrics only** (count, latency, in-flight). Zero worker/queue/job/cost metrics | — | **PARTIALLY WORKING** | `test_metrics.py` | Low | — | — | OPS-* | **ADD** |
| A16 | Sentry | `app/core/observability.py` | DSN-gated, `traces_sample_rate=0.0` | — | **PARTIALLY WORKING** | — | Medium | Good (no PII) | — | OPS-* | **FIX** |
| A17 | Health / readiness | `app/routers/health.py` | Liveness independent of DB/Redis; readiness checks deps | — | **WORKING** | `test_health.py`, `test_ready.py` | High | Good | Good | OPS-* | **KEEP** |
| A18 | Backups | `app/services/backups.py`, `integrations/b2.py` | `pg_dump` subprocess, B2 offsite, owner-only restore with echoed-id confirm, PG* env (never argv) | Postgres, B2 | **PARTIALLY WORKING** | `test_backups.py` | High | Good | Good | ADM-033 | **FIX** — capability is sound, but **nightly never fires** (beat off); no verified restore drill |
| A19 | Notifications / alerts | `app/routers/notifications.py`, `app/services/notifications.py` | Per-user inbox (RLS `user_id=auth.uid()`), staff alert queue | Postgres | **WORKING** | `test_notifications.py`, `test_wave6_notifications.py` | High | Good | Good | — | **KEEP** |
| A20 | Email (Resend / SMTP / IMAP) | `integrations/{resend,smtp_email,imap_mailbox}.py` | Three transports | — | **PARTIALLY WORKING** | `test_email_client.py`, `test_smtp_email.py` | Medium | Good | Good | ADM-006 | **FIX** — footer leaks builder name (`email_templates.py:35`) |
| A21 | Skills / MCP gateway | `app/routers/skills.py`, `integrations/mcp_gateway.py` | Scoped 30-day skill tokens, cost-gated | Redis | **WORKING** | `test_skill_tokens.py`, `test_skills_plugin.py` | High | Good | Good | — | **KEEP** (out of v1 scope) |

---

## B · SCHEDULING & JOBS

| # | Feature | Location | Implementation | Status | Test | Req ID | Recommendation |
|---|---|---|---|---|---|---|---|
| B1 | Celery beat schedule | `workers/celery_app.py:173` | **`beat_schedule = {}`** — 11 entries preserved in `_BEAT_SCHEDULE_DISABLED` | **BROKEN (disabled)** | `test_celery.py`, `test_scheduled_jobs.py` | AUTO-001 | **FIX** — one-line restore, then verify each entry |
| B2 | Task retry / backoff | all 39 tasks | **Zero** `autoretry_for` / `max_retries` / `retry_backoff` / `bind` | **MISSING** | none | AUTO-* | **ADD** — P0 |
| B3 | Dead-letter queue | — | Does not exist anywhere in repo | **MISSING** | none | AUTO-* | **ADD** — P0 |
| B4 | Idempotency | per task | Real where present: `FOR UPDATE SKIP LOCKED` claims, per-day dedupe, run-claim mutex. **Uneven** — 8 of 20 task modules have no locking or claim | **PARTIALLY WORKING** | scattered | AUTO-004 | **REFACTOR** |
| B5 | Beat-overlap advisory lock | `workers/celery_app.py` (R6) | Present on the sweeps that need it | **WORKING** | — | AUTO-* | **KEEP** |
| B6 | Scheduled-job ledger | `db/0055`, `app/routers/reports.py` | `scheduled_job_runs`: last run + status + produced report | **WORKING** (but empty while beat is off) | `test_scheduled_jobs.py`, `test_report_tasks.py` | ADM-021 | **KEEP** |
| B7 | Queue topology | `workers/celery_app.py` | **One default queue.** No routing, no priority, no separation of 30-min audits from 2-s syncs | **PARTIALLY WORKING** | — | PERF-* | **REFACTOR** |

---

## C · AUDIT

| # | Feature | Location | Implementation | Status | Test | Req ID | Recommendation |
|---|---|---|---|---|---|---|---|
| C1 | Audit engine | `danyals-audit-system/` (~20k LOC) | 10 analyzers (onpage, technical, local, offpage, semantic_seo, ai_search, geo_ai, extras), 4 YAML checklists, 8 provider integrations | **WORKING** | own `ci.yml` | AUD-* | **KEEP** the engine |
| C2 | Engine adapter | `integrations/audit_engine.py` | **Subprocess + separate venv + stdout parse + filesystem artefacts** | **PARTIALLY WORKING** | `test_audit_engine_adapter.py` | AUD-* | **REFACTOR** — the biggest scale constraint |
| C3 | Scoring | `audit_engine/scorers/aggregator.py` | Severity-weighted (crit 3 / major 2 / minor 1 / info 0.5) mean of 0-10 finding scores, profile-weighted roll-up | **WORKING** — fully deterministic | — | AUD-* | **KEEP** |
| C4 | Free (public) audit | `app/routers/public.py`, `workers/tasks/audit.py:478+` | Comprehensive run at `--mode auto`, paid providers ON | **BROKEN (cost)** | `test_public_audit_task.py`, `test_public_endpoints.py` | AUD-*, ADM-015 | **FIX** — logs `$0.00`, ungated spend, IP-only rate limit |
| C5 | Paid audit + type picker | `app/routers/audits.py` | 6 types (onpage/offpage/technical/local/geo/strategy); none selected = all | **WORKING** | `test_audits_endpoints.py`, `test_audit_task.py` | ADM-012 | **KEEP** |
| C6 | HTML report viewer + PDF | `app/services/audit_artifacts.py` | Both rendered from the same `report.html`; CSP + `nosniff` on served artefacts; traversal-safe root | **WORKING** | `test_audit_artifacts.py` | AUD-* | **KEEP** |
| C7 | Remediation sheets | `app/services/audit_sheets.py` | Role-based sheets from the same `findings.json` | **WORKING** | `test_audit_sheets.py` | AUD-* | **KEEP** |
| C8 | Audit overlay (Command Center apply) | `db/0027`, `app/routers/command_center.py` | Overlay only — never mutates a stored audit | **WORKING** | `test_policy_overlay.py` | ADM-034 | **KEEP** |
| C9 | Weekly audit refresh | `workers/tasks/reports.py` | Idempotent (`min_age_days` dedupe) | **BROKEN (disabled)** | `test_report_tasks.py` | AUTO-* | **FIX** with B1 |
| C10 | "Audit Coverage" UI section | `frontend/components/audit/AuditCoverage.tsx:53` | Renders **"Coming soon"** | **PLACEHOLDER** | none | ADM-014 | **REMOVE** |

---

## D · CONTENT

| # | Feature | Location | Implementation | Status | Test | Req ID | Recommendation |
|---|---|---|---|---|---|---|---|
| D1 | Content research (page-set recommendation) | `app/services/content_research.py` (1,384 LOC), `app/routers/content.py` | Claude + Anthropic server-side `web_search`; strict-JSON page set; SSRF-guarded; cost-gated | **PARTIALLY WORKING** | `test_content_research.py` | CONT-* | **REFACTOR** — **synchronous 40–60 s HTTP call**; `next.config.mjs` raises the proxy timeout to 180 s to accommodate it. Must become a job |
| D2 | Content generation | `app/services/content_generator.py` (1,204 LOC) | Multi-call Claude draft; deterministic given a fixed writer | **WORKING** | `test_content_generator.py`, `test_content_golden.py` | CONT-* | **KEEP** |
| D3 | AI / em-dash guard | `app/services/content_guard.py` (755 LOC) | Pure detector + writer-assisted block rewrite + **unconditional** dash strip | **WORKING** — genuinely well built | `test_content_guard.py` | CONT-* | **KEEP** |
| D4 | QA scorecard + publish gate | `app/services/content_qa.py` (839 LOC) | Hard gate: no dim <70 **and** weighted ≥85 | **PARTIALLY WORKING** | `test_content_qa.py` | CONT-*, D-4 | **FIX** — thresholds + weights self-declared `PROVISIONAL`, never calibrated |
| D5 | Human review checkpoint | `app/routers/content.py` `/review`, `db/0017` | approve / request-edit / reject; blocks publish | **WORKING** | `test_content_endpoints.py` | TEAM-006 | **KEEP** |
| D6 | Page model / WYSIWYG edit | `app/services/page_model.py` (742 LOC) | GET/PUT page-model + preview | **WORKING** | `test_page_model.py`, `test_page_composer.py` | CONT-* | **KEEP** |
| D7 | Schema.org / SEO metadata | `app/services/content_schema.py` (882 LOC) | JSON-LD generation, carried into WP post meta | **WORKING** | `test_content_schema.py` | CONT-* | **KEEP** |
| D8 | Images | `app/services/content_images.py`, `integrations/images.py` | Topic deliberately excluded from image prompt | **WORKING** | `test_images.py` | CONT-* | **KEEP** |
| D9 | Site-design analysis | `app/services/site_design.py` (680 LOC) | Playwright-measured design profile → palette/layout | **WORKING** | `test_site_design.py` | CONT-* | **KEEP** |
| D10 | Scheduled publish | `db/0072_content_schedule`, `workers/tasks/content.py:2392` | 5-min sweep of approved+due jobs | **BROKEN (disabled)** | `test_content_worker.py` | CONT-* | **FIX** with B1 |
| D11 | Bulk / volume generation | `app/routers/content.py` | Job fan-out exists; no batch progress surface, no partial-failure report | **PARTIALLY WORKING** | — | CONT-* | **FIX** |
| D12 | Versioning / revert | `db/0017`, `0054_content_edit_instruction` | Edit instructions stored; **no content version history table**, no revert endpoint | **MISSING** | — | CONT-* | **ADD** |
| D13 | Internal linking | `content_generator.py:773-793` (`_links_block`), scored in `content_qa.py` (`internal_linking`, weight 0.04) | Builds a "Related resources" block from the source pack's keyword→URL registry (real URLs) plus cluster spokes mapped to slugs (pillar↔cluster topical map) | **PARTIALLY WORKING** | via `test_content_generator.py` / `test_content_qa.py` | CONT-* | **FIX** — spoke links are emitted as guessed `/{slug}` paths that are **not verified to exist** on the target site, so a generated page can ship internal links that 404 |

---

## E · WORDPRESS

| # | Feature | Location | Implementation | Status | Test | Req ID | Recommendation |
|---|---|---|---|---|---|---|---|
| E1 | WP REST publish (app password) | `integrations/wordpress.py` (454 LOC) | REST v2 + HTTP Basic; XML-RPC sibling | **WORKING** | `test_wordpress_publisher.py` | WP-* | **KEEP** |
| E2 | AIOS Publisher plugin path | `integrations/wordpress_publisher.py`, `wordpress-plugin/` (1,475 LOC PHP) | Own `aios/v1` namespace, shared key **in the JSON body** (survives Authorization-header stripping), browser UA (defeats WAF) | **WORKING** — a genuinely good piece of engineering | `test_wp_connections.py` | WP-* | **KEEP** |
| E3 | Per-client connections | `app/routers/wp_connections.py`, `db/0058` | CRUD + `/test`; method = plugin \| app_password \| xmlrpc | **WORKING** | `test_wp_connections.py` | ADM-011 | **KEEP** |
| E4 | Capability discovery | `app/routers/wp_connections.py` `/test` | Connection test exists | **PARTIALLY WORKING** | — | WP-*, ADM-011 | **FIX** — does not report *in plain language which publishing capabilities this site supports* |
| E5 | Elementor output | `app/services/elementor.py` (1,255 LOC) | Pure, deterministic `_elementor_data` widget tree; `_elementor_edit_mode=builder`; design-profile-aware sectioning + palette | **WORKING** | `test_elementor.py` | WP-* | **KEEP** — strong |
| E6 | Gutenberg output | `app/services/gutenberg.py` | Block markup generation | **WORKING** | `test_gutenberg.py` | WP-* | **KEEP** |
| E7 | Design preservation | `app/services/site_design.py` + plugin `design-reconstruction.php` + `_aios_design_css` meta | Analyzed CSS enqueued on managed posts, works on any theme | **WORKING** | `test_visual_diff.py`, `test_site_analyzer.py` | WP-* | **KEEP** |
| E8 | **Publish failure handling** | `workers/tasks/content.py:2160-2196` | 4-way cascade; **every stage swallows its exception**; terminal state is `degraded=True` artifact-only, job marked complete | **BROKEN** | — | WP-*, ERR-* | **FIX** — P0. Silent non-publication |
| E9 | SEO metadata preservation | plugin `_aios_schema_jsonld`, `_aios_faq`, `_aios_cta`, `wp_head` injection | Written as post meta | **WORKING** | — | WP-* | **KEEP** |
| E10 | Plugin branding | `aios-publisher.php:6,8-9`, `readme.txt:2` | `Author: Xegents AI` visible in client wp-admin | **BROKEN (rule)** | — | §1.1 hard rule | **FIX** |

---

## F · CITATIONS

| # | Feature | Location | Implementation | Status | Test | Req ID | Recommendation |
|---|---|---|---|---|---|---|---|
| F1 | Directory catalogue | `db/0046` (155) + `0065` (57) + `0067` (29) + `0048` strategy | 151 `bot_fillable`, 51 `captcha_assisted`, 17 `manual`, 2 `api` | **WORKING** (data) | `test_web2_catalog.py` | CIT-* | **KEEP** |
| F2 | Business profile / canonical NAP | `db/0051`, `0060`, `app/modules/citations/router.py` | Per-client profile, `ensure-profile` | **WORKING** | `test_client_nap.py` | ADM-009 | **KEEP** — but creation path is non-atomic (§3.3) |
| F3 | Citation audit / gap analysis | `app/modules/citations/service.py`, `integrations/citations.py` | Read/monitor existing listings | **WORKING** | `test_citation_gap.py`, `test_citation_discovery.py` | CIT-* | **KEEP** |
| F4 | **Bot submission (Playwright)** | `integrations/citation_bot.py` (1,083 LOC) | **`FORM_SPECS` has 3 entries**: `n49`, `192.com`, `411.ca` — against 151 `bot_fillable` rows | **BROKEN (coverage)** | `test_citation_bot_stealth.py` | CIT-*, ADM-018 | **REBUILD approach** — see `MIGRATION_STRATEGY.md` |
| F5 | Account signup automation | `integrations/citation_signup.py` (287 LOC) | `SIGNUP_SPECS` structure defined; **no concrete entries** | **PLACEHOLDER** | `test_citation_signup.py` | CIT-* | **REBUILD** |
| F6 | Direct API submitters | `integrations/citation_apis.py` (128 LOC) | Bing Places + Foursquare, both source-flagged *"CONFIRM BEFORE LIVE USE"* / *"assumed endpoint"* | **PARTIALLY WORKING** | `test_citation_engines.py` | CIT-* | **FIX** — verify or remove |
| F7 | CAPTCHA solver | `integrations/captcha_solver.py` | Provider-swappable; ~$0.0003–0.003/solve, metered on the `citations` dial | **WORKING** | — | CIT-* | **KEEP** |
| F8 | Submission worker + status | `app/modules/citations/tasks.py`, `integrations/citation_status.py` | Per-row claim (exactly-once by id), status ledger | **WORKING** | `test_offpage_worker.py` | CIT-* | **KEEP** — **but no retry (B2)** |
| F9 | Duplicate prevention | `db/0018`, `0064_citation_handoff` | Ledger-level | **WORKING** | — | CIT-* | **KEEP** |
| F10 | Cost per unit (<10¢ commitment) | `app/services/pricing.py` + `captcha_solver` | Runtime-computed marginal cost | **PARTIALLY WORKING** | `test_pricing.py` | CIT-*, D-2 | **FIX** — marginal cost is computable; **loaded cost (human handoff at 151 unsupported directories) is not modelled** |

---

## G · WEB 2.0

| # | Feature | Location | Implementation | Status | Test | Req ID | Recommendation |
|---|---|---|---|---|---|---|---|
| G1 | Platform publishers | `integrations/web2_publishers.py` (3,217 LOC) | **55 concrete API client classes** — WordPress.com, Blogger, Tumblr, dev.to, Ghost, Mastodon, Bluesky (AT Proto), Notion, Zenodo, Internet Archive, OSF, Figshare, Sanity, Storyblok, Hygraph, WriteFreely, GitHub/GitLab/Codeberg/Sourcehut Pages, MetaWeblog (FC2/Seesaa), LiveJournal XML-RPC (+Dreamwidth), Lemmy, Misskey, Pixelfed, Plurk, Warpcast, Netlify, Neocities, pastebins … | **WORKING** | `test_web2_publishers_expansion.py`, `test_web2_catalog.py` | WEB2-001 | **KEEP** — the strongest off-page asset |
| G2 | Credential factory | `integrations/web2_credentials.py` | 52 builders; per-client vault provider `web2:<platform>` | **WORKING** | `test_seed_web2_vault.py` | WEB2-* | **KEEP** |
| G3 | Medium | declared `PLATFORM_MEDIUM`, in `WEB2_PLATFORMS` | **No client class, no factory entry.** Only in `DRAFT_ONLY_PLATFORMS` | **BROKEN** | — | WEB2-* | **REMOVE** (Medium retired its write API) |
| G4 | Web 2.0 pipeline | `app/services/web2_pipeline.py` (777 LOC) | Cost-gated per-call wrapper around the generator | **WORKING** | `test_web2_pipeline.py` | WEB2-* | **KEEP** |
| G5 | Account signup | `integrations/web2_signup.py` (587 LOC) | Per-platform browser recipes; same "reconfirm before automating" caveat | **PARTIALLY WORKING** | `test_web2_signup.py` | WEB2-* | **FIX** |
| G6 | Platform status board | `app/routers/offpage.py` `/offpage/web2`, `db/0062-0077` | connected vs missing per platform | **WORKING** | `test_offpage.py` | ADM-019 | **KEEP** — verify fault attribution is honest |
| G7 | Footprint / site-reputation-abuse guard | `web2_publishers.py:3148` `FootprintChoice` | Footprint diversification exists | **PARTIALLY WORKING** | — | WEB2-* | **FIX** — no per-client velocity cap or penalty-risk gate found |
| G8 | Human-paced publishing | — | No scheduling jitter / pacing control found (and beat is off) | **MISSING** | — | WEB2-* | **ADD** |

---

## H · PORTALS

| # | Feature | Location | Status | Test | Req ID | Recommendation |
|---|---|---|---|---|---|---|
| H1 | Admin portal — 15 routes | `frontend/app/admin/*` | **WORKING** (builds + typechecks clean) | none (no FE tests) | ADM-* | **KEEP** |
| H2 | Team portal — queue / review / deliver / tools | `frontend/app/team/*`, `app/routers/portal.py` | **WORKING** | `test_portal_endpoints.py`, `test_portal_part8.py` | TEAM-* | **KEEP** |
| H3 | Client portal — audits / reports / milestones / requests | `frontend/app/client/*`, `db/0010`, `0031-0034` | **WORKING**; `CurrentClientDep` pins `client_id` server-side, never from the body | `test_client_boundary.py`, `test_portal_provisioning.py` | CLIENT-* | **KEEP** — good design |
| H4 | Task board + lifecycle | `app/routers/tasks.py`, `db/0011`, `0012` guard triggers | **WORKING** — illegal transitions rejected **at the database**, not just the API | `test_tasks_schema.py`, `test_tasks_endpoints.py` | TEAM-002 | **KEEP** — exemplary |
| H5 | Milestones auto-advance | `app/routers/milestones.py`, `db/0021`, `0034` | **PARTIALLY WORKING** — auto-advance endpoint exists; the *event-driven* advance depends on jobs that do not run | `test_milestones.py` | ADM-037 | **FIX** with B1 |
| H6 | Unified approval queue | — | **MISSING** — approvals live per-module (content, web2, citations, gmb) with no single surface | — | ADM-038 | **ADD** |
| H7 | Server-side pagination on lists | `app/core/pagination.py` | **PARTIALLY WORKING** — hard-capped `limit≤200`/`offset` exists and is used; **no total count, no cursor, no bulk selection** | — | ADM-039 | **REFACTOR** |
| H8 | Legacy demo store | `frontend/lib/store.tsx` + `lib/data.ts` | **UNUSED / MOCK** — mounted at `app/layout.tsx:62`, seeds localStorage with 8 plaintext demo passwords; no screen reads it | — | ADM-003 | **REMOVE** |
| H9 | Mock vault keys | `frontend/lib/vault.ts:101-113` | **UNUSED / MOCK** — 11 realistic fake API keys with `secret:` fields | — | ADM-003 | **REMOVE** |
| H10 | Hardcoded provider prices in UI | `frontend/lib/cost.ts:19-27` | **MOCK** — `"$0.30 / search"`, `"~$0.90 / page"` as display strings | — | ADM-025 | **REMOVE** |

---

## I · MODULES OUTSIDE THE v1 FIVE (built, deferred to v1.1 by D-1)

| # | Module | Location | Status | Note |
|---|---|---|---|---|
| I1 | Policy Radar | `app/routers/policy.py`, `app/services/policy_{ask,generate,watch,radar,baseline}.py`, `db/0019`, `0050` | **PARTIALLY WORKING** | Built; on-demand only. Daily generator is a **one-line** restore. **D-17 undecided** — was sold as Module 04 of 4 |
| I2 | Keyword research | `app/modules/keyword_research/` | **PARTIALLY WORKING** | `client_da=None` hardcoded (`tasks.py:120`); silent cost-gate block |
| I3 | Rank tracker | `app/modules/rank_tracker/` | **BROKEN (disabled)** | Nightly dispatch + weekly rollup both in `_BEAT_SCHEDULE_DISABLED` |
| I4 | Local SEO / GBP | `app/modules/local_seo/` | **PARTIALLY WORKING** | GBP sync "always holds — no reader wired" (`tasks.py:211`) |
| I5 | Competitor intel | `app/modules/competitor_intel/` | **PARTIALLY WORKING** | Backlink-gap returns an honestly empty set; open funding decision |
| I6 | On-page fixes | `app/modules/on_page/` (2,100 LOC) | **PARTIALLY WORKING** | Live-site writes are lead-attributed and trigger-guarded (good); drift guard is a string compare, not a hash |
| I7 | GMB posts | `app/modules/gmb/` | **PARTIALLY WORKING** | AI draft + policy check + review gate work; **actual posting to Google is dormant** (self-declared) |
| I8 | Indexing | `app/modules/indexing/`, `db/0061` | **WORKING** | IndexNow + Google Indexing API + sitemap ping, all key-gated, ledgered |
| I9 | Site analytics (GSC/GA4) | `app/modules/site_analytics/` | **WORKING** | OAuth + per-property sync |
| I10 | Data import (CSV/XLSX) | `app/modules/data_import/` | **WORKING** | Traversal-safe upload root, run-claim mutex, streaming XLSX |
| I11 | Client onboarding checklist | `app/modules/client_onboarding/` | **WORKING** | 11-step versioned template, human-driven |
| I12 | Billing / invoices | `app/modules/billing/` | **WORKING** | Records only, no gateway (correct for v1) |
| I13 | Site builder | `app/modules/site_builder/`, `db/0069-0071` | **PARTIALLY WORKING** | Full state machine + visual QA. **Commit `5d01e16` removed Site Builder from the admin UI** — backend is now orphaned |
| I14 | Tool workspaces | `app/modules/tool_workspaces/` (778 LOC) | **DUPLICATED** | 9 `/…/workspace` endpoints re-aggregating existing `/stats` endpoints |
| I15 | Reports / Sheets | `app/routers/reports.py`, `integrations/sheets.py` | **PARTIALLY WORKING** | Ledger + download work; the monthly/weekly producers are disabled |
| I16 | Upsells (Fiverr cards) | `app/routers/upsells.py`, `db/0022` | **WORKING** | Reorder is non-atomic (§3.3). **D-7 undecided** |
| I17 | Tickets / support | `app/routers/tickets.py`, `db/0024`, `0033`, `0075` | **WORKING** | — |
| I18 | Context engine (living summaries) | `app/services/context_*.py`, `db/0013`, `0014` | **PARTIALLY WORKING** | Compaction works; **vector recall is deliberately not deployed** (Voyage/Pinecone excluded from the image) |

---

## J · ORPHANS AND DEAD WEIGHT

| Item | Location | Status | Recommendation |
|---|---|---|---|
| Second dashboard | `dashboard/{bridge,worker}.py`, `index.html` | **UNUSED** — no deployment references it | **REMOVE** |
| One-off operator scripts | `tools/finish_citation.py`, `Finish-Citations.bat`, `Start-*.bat`, `push-to-wordpress.ps1` | **OBSOLETE** — carry a hardcoded real NAP + phone number | **REMOVE** |
| Committed binaries | `SEO-CONTENT-OS.zip` (1.1 MB), `spotino-theme.zip`, `aios-publisher.zip`, `best-ai-agents-featured.png` (436 KB), `best-ai-agents-…html` | **OBSOLETE** | **REMOVE** from git |
| `spotino-theme/`, `scratchpad-hero/` | root | **OBSOLETE** — a client's WP theme and a scratch dir | **REMOVE** |
| `whatsapp chats, media and calls/` | root (untracked) | Project comms in the working tree, incl. 589 `.opus` + 26 `.mp4` | **MOVE OUT** of the repo working dir |
| Mock arrays in `lib/data.ts` | `audits`, `traffic`, `team`, `clients`, `operatorProfile`, `securityDefaults`, `workspaceDefaults`, `PORTAL_MEMBER_ID`, `PORTAL_TODAY` | **UNUSED** (verified: no importers) | **REMOVE** |

---

## K · INVENTORY ROLL-UP

| Status | Count | Notes |
|---|---|---|
| **WORKING** | 44 | Includes the entire security/RLS foundation and 55 Web 2.0 publishers |
| **PARTIALLY WORKING** | 30 | Dominated by "built but disabled" and "built but uncalibrated" |
| **BROKEN** | 8 | B1 beat, B2 retry, B3 DLQ, A12 free-audit cost, E8 publish cascade, E10 plugin branding, F4 bot coverage, G3 Medium |
| **MISSING** | 7 | A2 revocation, A4 offboarding, D12 content versioning/revert, G8 Web 2.0 pacing, H6 unified approval queue, plus B2 retry and B3 DLQ |
| **PLACEHOLDER** | 2 | C10 Audit Coverage, F5 signup specs |
| **MOCK / UNUSED** | 7 | H8, H9, H10, J-row items |
| **DUPLICATED** | 3 | WP publish paths, cost price sources, tool workspaces |
| **OBSOLETE** | 6 | J-row items |

**The single most important number in this table:** of the 8 BROKEN items, **three (B1, B2, B3)
are the same root cause** — the job layer was switched off and was never built to survive
failure. Fixing that one thing converts a large share of PARTIALLY WORKING to WORKING without
touching the code those features live in.
