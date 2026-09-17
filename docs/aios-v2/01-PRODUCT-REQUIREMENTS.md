# 01 · Product Requirements

Every requirement has a stable id. Tasks, branches, tests and acceptance criteria all
cite it. **A change with no `REQ-*` id is out of scope.**

Priority: **P0** must ship in v2.0 · **P1** should ship in v2.0 · **P2** v2.1.

---

## 1. Personas and what they are trying to do

### Owner — "I need to know the system is not lying to me"
Provisions people, holds the keys, watches spend. Their recurring fear is discovering
that a number on a client report was never measured. Needs: a spend view that is real, a
capability truth table, an audit log, and a kill switch per module.

### Manager — "I need the work to move without me touching every piece"
Runs delivery for 20–40 clients. Assigns, reviews, approves, publishes. Their bottleneck
is review: they will not read 50 drafts, so the system must surface only what needs a
human. Needs: a queue sorted by what is blocked, a diff view, bulk approve with
per-item override.

### Staff — "Tell me exactly what to do next"
Four specialisms. They live in a task queue and a handful of tools. The citation operator
in particular spends their day in a browser with the extension open. Needs: unambiguous
task specs, tools that do not lose their work, and a way to say "this is wrong" that
reaches a human.

### Client — "Show me it is working"
Logs in occasionally, mostly reads the monthly report. Judges the agency on visible
proof: pages published, listings live, rankings moved. Needs: plain language, dated
evidence, no jargon, no internals.

### Public visitor — "Is my site any good?"
Arrives at a free audit form from an ad or a link. Converts if the audit tells them
something specific and true within a minute. Needs: speed, no signup wall before value,
one obvious next step.

---

## 2. The five journeys that define the product

### J1 · Onboard a client (target: under 15 minutes)
Create client → capture business profile and canonical NAP → connect WordPress → paste
the **previous website URL** for design analysis → run design extraction → human approves
the design profile → run keyword research → generate the topical map → select the first
page set. The system now knows the client well enough to work autonomously.

### J2 · Publish a page set (target: 50 pages, one working day, one reviewer)
Topical map proposes a page set → human approves the set → fan-out: each page runs
research → outline → draft → grounding check → QA scorecard → design composition →
Elementor block tree → staged as a WordPress draft → reviewer sees a rendered preview and
a QA summary → approve → publish live → index submission → internal-link proposals.

### J3 · Build citations (target: 100 live per client)
Load the client's canonical NAP → gap analysis against discovered existing listings →
prioritised directory set → operator opens directory in browser with extension →
**agent creates the account** → verifies email → fills the form → operator reviews the
filled fields → operator presses submit → proof captured → status tracked →
re-verification on schedule.

### J4 · Run a Web 2.0 / social campaign
Select client and campaign → select platforms from the 32 → provision per-client
identities (OAuth at campaign start) → content pipeline produces platform-shaped posts
with images, internal links and SEO fields → anchor plan assigns targets → pacing engine
schedules → publish via official API → link-liveness and account-health monitoring.

### J5 · Report (monthly, automatic)
Pull measured facts from every module → assemble one document model → render HTML and
PDF from that single source → email to the client → file in the portal. Anything not
measured this period is stated as not measured, never omitted silently.

---

## 3. Requirement register

### M01 · Portal & platform core

| ID | Requirement | P |
|---|---|---|
| `REQ-CORE-001` | Email + password auth with argon2id, session rotation, and device-scoped refresh tokens | P0 |
| `REQ-CORE-002` | TOTP MFA, **mandatory** for Owner and Admin, optional for all other roles | P0 |
| `REQ-CORE-003` | Nine roles (Owner, Super-Admin, Admin, Manager, SEO, Content, Off-page, Support, Client) with a permission matrix expressed as capability strings, not role checks scattered in code | P0 |
| `REQ-CORE-004` | Owner-only user provisioning; invite by email with a single-use, expiring token | P0 |
| `REQ-CORE-005` | Client entity: profile, canonical NAP, categories, hours, services, brand assets, contacts, tier, status | P0 |
| `REQ-CORE-006` | Multi-location clients: a client may have N locations; NAP, GBP, citations and grid tracking are location-scoped | P1 |
| `REQ-CORE-007` | Bulk client import from CSV with a dry-run diff, per-row validation and a rollback | P1 |
| `REQ-CORE-008` | Task queue: assignment, priority, due date, blocked reason, SLA timer, and per-member workload view | P0 |
| `REQ-CORE-009` | Review checkpoint: a generic approve/reject/request-change surface any module can enqueue into | P0 |
| `REQ-CORE-010` | Milestones: a five-stage delivery timeline per engagement, auto-advanced from delivery events, never hand-edited | P1 |
| `REQ-CORE-011` | Notifications: in-app, email; per-user preferences; digest batching so one fan-out does not send 50 emails | P0 |
| `REQ-CORE-012` | Activity log: append-only, actor + action + target + before/after, queryable, exportable | P0 |
| `REQ-CORE-013` | Key vault: envelope-encrypted credentials, per-client sealing, scoped read API, audit row on every decrypt | P0 |
| `REQ-CORE-014` | Cost control: per-module money dials (`off` / `by_hand` / `on`), per-client monthly cap, global spend halt | P0 |
| `REQ-CORE-015` | Server-side pagination, search, sort and bulk selection on every list surface | P0 |
| `REQ-CORE-016` | Pre-aggregated rollups for every dashboard number; no dashboard computes across tenant rows at page load | P1 |
| `REQ-CORE-017` | Client portal: read-only view of deliverables, progress, reports and a request/ticket thread | P0 |
| `REQ-CORE-018` | Command Center: a single operator home showing blocked work, failing jobs, spend against caps and system health | P1 |
| `REQ-CORE-019` | Settings: agency branding, defaults per module, feature flags, provider key status (never key values) | P0 |
| `REQ-CORE-020` | Capability truth table: a live page stating which capabilities are fully operational, degraded, or unconfigured, derived from real probes | P0 |

### M02 · Audit

| ID | Requirement | P |
|---|---|---|
| `REQ-AUD-001` | Free audit: public form, no login, ~10–15 page condensed report, delivered in under 3 minutes | P0 |
| `REQ-AUD-002` | Free-audit abuse controls: per-IP rate limit, per-domain cooldown, email verification before delivery, and a spend ceiling per day | P0 |
| `REQ-AUD-003` | Paid audits in six types: technical · local · GEO (AI-search readiness) · content · off-page · full | P0 |
| `REQ-AUD-004` | Every audit produces a machine-readable `findings.json` as the single source; HTML viewer and PDF are renderings of it, never separately authored | P0 |
| `REQ-AUD-005` | Each finding carries: severity, evidence (URL, selector, measured value), the standard it violates, effort estimate, and a remediation instruction | P0 |
| `REQ-AUD-006` | Crawl budget and cost ceiling per audit type, enforced before the run starts and monitored during | P0 |
| `REQ-AUD-007` | A degraded section (missing provider, blocked crawl) renders as an explicit "not measured" block; it is never omitted and never estimated | P0 |
| `REQ-AUD-008` | Remediation sheet export (CSV/Sheets) grouped by owner and effort | P1 |
| `REQ-AUD-009` | Audit re-run and diff: what changed since the last audit of the same site and type | P1 |
| `REQ-AUD-010` | Findings feed the task queue: a finding can become an assigned task with one action | P1 |

### M03 · Content system

| ID | Requirement | P |
|---|---|---|
| `REQ-CNT-001` | **Design analysis input** is the client's *previous version of their site*; one primary URL per client, optional additional reference URLs | P0 |
| `REQ-CNT-002` | Analysis renders the page in a real browser (not an HTTP GET) and reads **computed styles**, with a vision pass over a screenshot as corroboration | P0 |
| `REQ-CNT-003` | Extract up to 5 pages of the reference site, auto-selected by type (home, service, blog, contact, one deep page) | P0 |
| `REQ-CNT-004` | **DesignIR** — the captured design system — must include: colour roles, typography scale, spacing scale, container widths, breakpoints, border radii, shadows, border treatment, button/CTA variants, form control styles, image treatment, icon style, nav and header variants, footer structure, section grammar and order, and motion/animation presence | P0 |
| `REQ-CNT-005` | Every DesignIR value carries provenance: `declared` (CSS custom property) beats `derived` (clustered computed style) beats `inferred` beats `defaulted` | P0 |
| `REQ-CNT-006` | DesignIR is reviewed and approved by a human before any page is built on it, and is editable in the dashboard (change a colour, swap a face, adjust a scale step) | P0 |
| `REQ-CNT-007` | DesignIR is versioned; re-analysis is on demand; a staleness badge appears after 90 days; published pages are never retro-restyled | P0 |
| `REQ-CNT-008` | **Fidelity target: same design system, new composition.** Output must pass a token-conformance test (every colour, face, radius and spacing value used by a generated page exists in the approved DesignIR) — not a pixel diff | P0 |
| `REQ-CNT-009` | A section type absent from the source (FAQ, comparison, pricing) is synthesised from DesignIR tokens and labelled `inferred` in the composition record | P0 |
| `REQ-CNT-010` | **Word bank = SEO keyword bank with volumes**, sourced from M08: head and long-tail terms, search volume, difficulty, intent stage, SERP features, and parent cluster | P0 |
| `REQ-CNT-011` | Word bank is per client, seeded from niche templates, human-editable, and versioned | P0 |
| `REQ-CNT-012` | Word bank carries a **banned list** (competitor names, compliance words, AI-tell phrases) enforced at draft time | P0 |
| `REQ-CNT-013` | Word bank carries an **entity / must-mention set** per cluster for topical completeness scoring | P1 |
| `REQ-CNT-014` | **Page set:** the AI topical map proposes a page set (type, target cluster, primary and secondary terms, intent, priority); a human approves before any drafting spends money | P0 |
| `REQ-CNT-015` | Page types: home · service · location · service×location · blog/article · about · contact · comparison · FAQ · category hub | P0 |
| `REQ-CNT-016` | Bulk fan-out: an approved page set of up to 50 pages runs as one durable job with per-page resumability and a per-client concurrency cap | P0 |
| `REQ-CNT-017` | Drafting pipeline stages: research → outline → draft → grounding/claims check → internal-link plan → schema → title/meta → QA scorecard | P0 |
| `REQ-CNT-018` | **Grounding:** every factual claim about the client (services, areas, hours, credentials) must resolve to the client profile or a cited source; unresolvable claims block the draft | P0 |
| `REQ-CNT-019` | QA scorecard: weighted dimensions with a per-dimension floor. **Advisory with mandatory acknowledgement** until calibrated against ≥30 human-graded drafts; then switchable to a hard gate at the calibrated threshold | P0 |
| `REQ-CNT-020` | The calibration set (human grades vs machine scores) is a first-class stored artefact with a drift report | P0 |
| `REQ-CNT-021` | Human review: rendered preview beside the QA summary, inline edit, approve / reject / request-change, with the reason captured | P0 |
| `REQ-CNT-022` | **Publish to WordPress as a genuinely editable Elementor block tree.** Acceptance: open the published page in Elementor, select any heading, text, image, button or section, and edit it natively | P0 |
| `REQ-CNT-023` | Gutenberg output as a fallback when Elementor is absent, subject to the same editability bar | P1 |
| `REQ-CNT-024` | Capability discovery per WordPress site: builder present, version, theme, plugin set, REST availability, upload limits — probed and stored before first publish | P0 |
| `REQ-CNT-025` | Publish defaults to a WordPress **draft**; going live is a second explicit action; every publish is versioned and revertible | P0 |
| `REQ-CNT-026` | A publish that cannot complete (no credentials, REST blocked, builder missing) ends in a **`blocked`** terminal state naming the cause — never `done` | P0 |
| `REQ-CNT-027` | Images: AI-generated by default with a per-image cost line; client-supplied and stock supported; alt text generated from page context; never scraped from the reference site | P0 |
| `REQ-CNT-028` | Internal linking: the topical map produces link proposals both between new pages and from existing pages; links **between new pages are applied automatically**, links **into existing pages are proposed and require approval** | P0 |
| `REQ-CNT-029` | Schema markup per page type (LocalBusiness, Service, FAQPage, Article, BreadcrumbList), validated before publish | P0 |
| `REQ-CNT-030` | Plagiarism / originality check before publish, with a configurable provider and a fail threshold | P1 |
| `REQ-CNT-031` | Every published page registers with M09 for index submission | P0 |

### M04 · Citations

| ID | Requirement | P |
|---|---|---|
| `REQ-CIT-001` | Canonical NAP per client (and per location) is the single source; every submission reads from it and nothing else | P0 |
| `REQ-CIT-002` | Citation audit: discover existing listings for the business, detect NAP inconsistencies and duplicates | P0 |
| `REQ-CIT-003` | Directory registry: name, URL, country, vertical, authority tier, submission mechanism, account requirement, verification requirement, terms status. Seeded with ≥160 directories | P0 |
| `REQ-CIT-004` | Gap analysis produces a prioritised directory set per client by authority, vertical fit and effort | P0 |
| `REQ-CIT-005` | **Chrome MV3 extension** authenticated by a short-lived, scope-limited operator token bound to a client and a session | P0 |
| `REQ-CIT-006` | Extension collects a **PII-free structural digest** of the page's forms; raw page content and typed values never leave the browser except as an explicit field-value payload the operator can see | P0 |
| `REQ-CIT-007` | **Account creation:** a dedicated action that registers a new account on the directory — fills the signup form, generates and vaults the credentials, and completes **email verification** automatically | P0 |
| `REQ-CIT-008` | Email identity: a per-client addressed mailbox on an agency-owned catch-all domain; the verification consumer reads it over IMAP, extracts the link or code, and completes verification | P0 |
| `REQ-CIT-009` | Phone/SMS verification is surfaced as a **human task** with the client's real number; no SMS-receive services | P0 |
| `REQ-CIT-010` | Form intelligence: heuristic match first, AI field-mapping second; mappings cached against a **structural fingerprint** (not URL, not class names) and reused | P0 |
| `REQ-CIT-011` | Honeypot and trap-field detection; a field the form asks to be left empty must be left empty, and a fill that touches one is a hard failure, not a success | P0 |
| `REQ-CIT-012` | CAPTCHA: automatic solving where permitted, with per-solve cost recorded; fall back to the human in the tab | P0 |
| `REQ-CIT-013` | **A human always presses submit.** The agent fills, self-checks and stages; the panel shows every value it will send, with low-confidence fields flagged and never silently typed | P0 |
| `REQ-CIT-014` | Description variants: 3 lengths (short / medium / long), each reused at most N times across directories, tracked to avoid duplicate-content footprints | P0 |
| `REQ-CIT-015` | Proof capture on submit: full-page screenshot, submitted field set, timestamp, resulting URL, and the directory's response | P0 |
| `REQ-CIT-016` | Liveness: scheduled re-verification at 7 / 30 / 90 days; a listing is `live` only when fetched and matched against NAP | P0 |
| `REQ-CIT-017` | Per-client browser identity: separate browser profile and, where used, a per-client proxy; no cross-client cookie or fingerprint sharing | P0 |
| `REQ-CIT-018` | Cost accounting per citation: marginal (CAPTCHA, proxy, model tokens) and **loaded** (operator minutes at a configured rate), both reported | P0 |
| `REQ-CIT-019` | Duplicate/existing listing detected → reported as a claim task, not submitted | P0 |
| `REQ-CIT-020` | Operator session board: queue of directories for this client, per-item state, and a resume point if the browser closes | P0 |
| `REQ-CIT-021` | Aggregator submission paths (Yext, Data Axle, Apify) are **not built**. A stub must not exist | P0 |

### M05 · Web 2.0 & social publishing

| ID | Requirement | P |
|---|---|---|
| `REQ-W2-001` | Platform registry covering the 32 target platforms with, per platform: auth mechanism, API capability, content model, media rules, link policy, rate limits, terms position, ownership tier | P0 |
| `REQ-W2-002` | All publishing via **official APIs**. A platform without a usable API is marked `unsupported`; it is never browser-automated | P0 |
| `REQ-W2-003` | Per-client identity on every platform where a ban costs something; house accounts only on anonymous/throwaway tiers, with a hard cap on properties per house account | P0 |
| `REQ-W2-004` | OAuth connection flow performed by **agency staff** at campaign start, with token refresh and an expiry alarm | P0 |
| `REQ-W2-005` | Campaign entity: client, platforms, target pages, anchor plan, schedule, budget, state | P0 |
| `REQ-W2-006` | Content for a property is produced by the M03 pipeline in a platform-shaped variant — never spun, never duplicated across properties | P0 |
| `REQ-W2-007` | **Images** on every post that supports them: generated or selected, correctly sized per platform, with alt text | P0 |
| `REQ-W2-008` | **SEO fields** per platform where they exist: title, slug, meta description, canonical, tags, categories, OG/Twitter cards | P0 |
| `REQ-W2-009` | **Internal linking** within the property (post-to-post on multi-post properties) plus the outbound link plan to the client site | P0 |
| `REQ-W2-010` | Anchor-text bank with a distribution policy (branded / naked / partial / exact caps) enforced at assignment time | P0 |
| `REQ-W2-011` | Pacing engine: human-plausible intervals, per-platform daily caps, jitter, and no two properties publishing the same minute | P0 |
| `REQ-W2-012` | Link liveness: scheduled re-check of every placed link; a removed link raises a task | P0 |
| `REQ-W2-013` | Account health: per-account state (active, limited, suspended), post success rate, and an eligibility gate that stops using a degrading account | P0 |
| `REQ-W2-014` | A manager approves the campaign plan and the first post per platform before the pacing engine is allowed to run | P0 |
| `REQ-W2-015` | Automation bridges (n8n, Make.com) are supported as **outbound destinations** (fire a webhook with the post payload), not as a dependency | P1 |
| `REQ-W2-016` | Content calendar view across all clients and platforms with drag-to-reschedule | P1 |
| `REQ-W2-017` | Per-platform analytics pull where the API offers it (impressions, engagement), stored with provenance | P1 |

### M06 · Policy Radar

| ID | Requirement | P |
|---|---|---|
| `REQ-POL-001` | Watched-source registry (Google Search Central, algorithm trackers, platform policy pages) with per-source fetch cadence | P0 |
| `REQ-POL-002` | Change detection producing dated change-events with a diff and a confidence | P0 |
| `REQ-POL-003` | Knowledge base of current guidance, updated from change-events, queryable by the rest of the platform | P0 |
| `REQ-POL-004` | Per-client exposure analysis: which clients are affected by a change and why | P1 |
| `REQ-POL-005` | Recommendation queue with acknowledge / dismiss / convert-to-task, lead-gated | P0 |
| `REQ-POL-006` | Daily brief generated on a schedule and surfaced in the Command Center | P0 |
| `REQ-POL-007` | On-demand policy question answered from the KB with citations; metered under the policy dial | P1 |

### M07 · Rank & grid tracking

| ID | Requirement | P |
|---|---|---|
| `REQ-RNK-001` | Organic rank tracking via **DataForSEO**; local pack and geo-grid via **serper.dev**; every stored value carries its source and the two are never averaged together | P0 |
| `REQ-RNK-002` | Keyword-to-client-to-location assignment with tier-based keyword allowances | P0 |
| `REQ-RNK-003` | Geo-grid: configurable grid shape and radius, per-point measurement, and a heat map | P0 |
| `REQ-RNK-004` | **Three-state points:** `ranked` · `absent` · `error`. CHECK constraints make blurring them impossible; every ratio divides by measured points only | P0 |
| `REQ-RNK-005` | Rank history is append-only; a re-run never mutates a past observation | P0 |
| `REQ-RNK-006` | SERP feature capture per tracked keyword (AI Overview, local pack, FAQ, video) | P1 |
| `REQ-RNK-007` | Competitor rank tracking for a configured competitor set | P1 |

### M08 · Keyword research

| ID | Requirement | P |
|---|---|---|
| `REQ-KW-001` | Seed expansion from client profile, existing site, and competitor SERPs | P0 |
| `REQ-KW-002` | Volume, CPC and difficulty from DataForSEO, stored with the date measured | P0 |
| `REQ-KW-003` | Intent classification per term (informational / commercial / transactional / navigational / local) | P0 |
| `REQ-KW-004` | Semantic clustering into topics, with a parent-child cluster tree | P0 |
| `REQ-KW-005` | **Topical map**: clusters mapped to page types, producing the page-set proposal M03 consumes | P0 |
| `REQ-KW-006` | Gap analysis against competitors: terms they rank for and the client does not | P1 |
| `REQ-KW-007` | The keyword bank is the single upstream of M03's word bank; M03 never sources terms independently | P0 |

### M09 · Indexing

| ID | Requirement | P |
|---|---|---|
| `REQ-IDX-001` | Submit new and updated URLs to Google Indexing API, IndexNow and Bing, respecting per-provider daily quotas | P0 |
| `REQ-IDX-002` | Quota accounting with a pre-submit check; a submission that would exceed quota is queued, not dropped | P0 |
| `REQ-IDX-003` | Index-state verification (is the URL actually indexed) with a scheduled re-check | P0 |
| `REQ-IDX-004` | Automatic registration of every M03 publish and every M05 property URL | P0 |
| `REQ-IDX-005` | Sitemap generation/ping for client sites where we control the sitemap | P1 |

### M10 · Local SEO & GBP

| ID | Requirement | P |
|---|---|---|
| `REQ-LOC-001` | GBP connection per client location via Google OAuth | P0 |
| `REQ-LOC-002` | GBP profile read: categories, attributes, hours, services, photos — feeding the canonical NAP and the citation payload | P0 |
| `REQ-LOC-003` | GBP posts: create, schedule and publish, with images, from the content pipeline | P0 |
| `REQ-LOC-004` | Review monitoring and AI-drafted replies, **staff-approved before posting** | P1 |
| `REQ-LOC-005` | GBP Q&A seeding and monitoring | P1 |
| `REQ-LOC-006` | NAP consistency score across GBP, the client site and every live citation | P0 |

### M11 · Reporting & deliverables

| ID | Requirement | P |
|---|---|---|
| `REQ-REP-001` | One document model per report; HTML and PDF are two renderers over it, never separate templates | P0 |
| `REQ-REP-002` | Monthly client report assembled from measured facts only; unmeasured sections are stated as such | P0 |
| `REQ-REP-003` | Scheduled generation and email delivery, with the artefact filed in the client portal | P0 |
| `REQ-REP-004` | Agency branding applied (logo, colours, name) from settings | P0 |
| `REQ-REP-005` | Every figure in a report is click-traceable to the underlying record | P1 |
| `REQ-REP-006` | Export to Sheets/CSV as a format, never as a store | P1 |

### M12 · Billing, tiers & cost

| ID | Requirement | P |
|---|---|---|
| `REQ-BIL-001` | Service tiers with entitlements (keyword allowance, pages/month, citations/month, audit types, campaign eligibility) enforced at the API, not in the UI | P0 |
| `REQ-BIL-002` | Money dials per module: `off` · `by_hand` · `on`, with the dial state visible wherever a spend can occur | P0 |
| `REQ-BIL-003` | Per-client monthly spend cap with a hard stop and an operator alert at 80% | P0 |
| `REQ-BIL-004` | Global spend halt, owner-operated, that no code path can bypass | P0 |
| `REQ-BIL-005` | Per-unit cost accounting for every paid operation: estimated before, actual after, variance recorded | P0 |
| `REQ-BIL-006` | Loaded-cost model including human minutes at a configured rate, reported alongside marginal cost | P0 |
| `REQ-BIL-007` | Upsell surfaces in the client portal driven by tier gaps | P2 |
| `REQ-BIL-008` | Payment collection is **out of scope**; tiers are records, not charges | — |

### Cross-cutting

| ID | Requirement | P |
|---|---|---|
| `REQ-X-001` | Every long-running operation is a durable job: idempotency key, persisted state, lease, retry with backoff, dead-letter with full context | P0 |
| `REQ-X-002` | Per-client job concurrency caps and per-provider rate limits shared across clients | P0 |
| `REQ-X-003` | Every AI interaction is traced to LangSmith with the client, module, job and cost attached | P0 |
| `REQ-X-004` | Sentry error capture across backend, frontend and extension, with PII scrubbing | P0 |
| `REQ-X-005` | Structured JSON logs with a correlation id spanning request → job → provider call | P0 |
| `REQ-X-006` | Health and readiness endpoints that probe real dependencies, feeding the capability truth table | P0 |
| `REQ-X-007` | Nightly encrypted backups with a restore drill procedure and a documented RPO/RTO | P0 |
| `REQ-X-008` | Data retention policy per artefact class, with deletion on client offboarding | P1 |
| `REQ-X-009` | An eval suite for AI outputs (content quality, form-fill accuracy, design conformance) run in CI against fixed fixtures | P0 |
| `REQ-X-010` | Feature flags per module, per client, evaluated server-side | P1 |
