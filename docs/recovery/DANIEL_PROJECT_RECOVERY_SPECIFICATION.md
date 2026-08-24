# DANIEL PROJECT RECOVERY SPECIFICATION

**Document:** `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md`
**Phase:** 1 — Historical Context, Requirements and Product Intelligence
**Status:** Evidence-reconstructed. No implementation performed.
**Compiled:** 2026-08-23
**Subject system:** AIOS (AI Operating System) — Danyal deployment (`danyals-aios`), live at `app.qanry.com`
**Prepared for:** Zain Saeed (project owner, Xegents AI) → hand-off to a senior engineering agent

> ## ⚠️ READ `DECISIONS_LOG.md` FIRST
>
> On **2026-08-23** the project owner decided five of the thirteen conflicts recorded in §30.
> Where this document and `DECISIONS_LOG.md` disagree, **the decisions log wins.**
>
> **The v1 scope baseline is now fixed at five modules:**
> **Portal · Audit · Content (including the whole WordPress subsystem) · Citations · Web 2.0.**
> Everything else evidenced as committed to Danyal — GBP posts, the Indexing module, backlink
> monitoring, Sheets reporting, the financial audit report, Fiverr data import, extra CMS
> connectors — moves to **v1.1**, built after v1 ships to the client.
>
> Also decided: scale target **50–100 clients** with headroom architecture · citation cost
> **≤10¢ marginal, 20¢ hard fail line, loaded cost disclosed** · Web 2.0 accounts **tiered**
> (per-client on high-authority platforms) · Web 2.0 runs **per-campaign, not for every client**.
>
> Still open and blocking: **D-17** (is Policy Radar in v1? — it was sold to Danyal as Module 04
> of four), **D-4** (content QA gate), **D-6** (rankings source), **D-15** (credential rotation).


---

## HOW TO READ THIS DOCUMENT

Every material statement carries an evidence class:

| Class | Meaning |
|---|---|
| **CONFIRMED** | Explicitly established by a primary source (client call notes, a client-delivered document, an operator instruction, or verified source code). |
| **STRONG INFERENCE** | Not stated in one place, but supported by two or more independent pieces of evidence. |
| **PROPOSED** | A recommendation added by this analysis on engineering / SEO / UX / security / scale grounds. Not previously requested. |
| **UNKNOWN** | Insufficient evidence. Named as a question, never silently resolved. |
| **CONFLICTING** | Two or more sources disagree. Both positions are recorded; neither is silently discarded. |

Source shorthand used throughout:

| Tag | Source |
|---|---|
| `[SCOPE-CALL]` | `docs/meeting-notes/2026-07-03-scope-call.md` — Fathom recording of the Danyal kickoff, 61 min, 2026-07-03 |
| `[ARCH]` | `context/ARCHITECTURE-AND-PLAN.md` — v1 locked architecture |
| `[OVERHAUL]` | `context/PRODUCT-OVERHAUL-BACKLOG.md` — operator walkthrough 2026-07-23, areas A–Q |
| `[KB]` | `knowledge-base/*.md` — the in-repo module/architecture/cost/data-model knowledge base |
| `[PACK-JUL]` | The 9 July 2026 client document pack delivered to Danyal (Platform Overview, Service Tiers, Roles & Access Control, Responsibility Matrix, Operating Cost, Onboarding Checklist) |
| `[CIT-ECON]` | `Xegents-Citations-Web2-Automation-Plan.pdf` — 17 July 2026, delivered to Danyal |
| `[CIT-CRED]` | `danyal-AIOS-Citations-Web2-API-Guide.pdf` — off-page credentials guide |
| `[OFFPAGE-STATUS]` | `docs/deliverables/xegents-offpage-citations-web2.pdf` — built-and-deployed status report |
| `[RESEARCH-AUG]` | `AIOS-Content-Citations-Indexing-Research-Plan.pdf` — August 2026 v1, the most recent written plan |
| `[WA-ADAN]` | WhatsApp 1:1, Zain ↔ Adan (lead engineer), 30 Jun – 22 Aug 2026 |
| `[WA-TEAM]` | WhatsApp group "Team Dev", 30 Jun – 21 Aug 2026 |
| `[CODE]` | Direct inspection of the repository at HEAD `79d1036` (2026-08-23) |
| `[ENGINE]` | `danyals-audit-system/` — the separate audit engine product |
| `[AGENCYBOOK]` | `../AgencyBook - SaaS/docs/*` — the public SaaS research corpus (reference only, different product) |

**Two sources are deliberately quarantined.** Haseeb's project (`Storage Visibility`, `app.storagevisibility.com`, self-storage, ~15–20 facilities) and the AgencyBook public SaaS share a codebase lineage and a document template with Danyal's system. Several documents in Danyal's own pack contain figures copied from Haseeb's brief. Where that has happened it is flagged as **CONFLICTING**, never merged.

---

## 1. EXECUTIVE SUMMARY

### 1.1 What this project is

AIOS is a **white-labelled, single-agency SEO delivery platform** built by Xegents AI and deployed for one client, Danyal — an SEO agency owner whose public commercial identity runs through Fiverr (`fiverr.com/iamdaani`). The platform is meant to convert Danyal's manual, per-client SEO service delivery into a mostly self-running system: it audits websites, plans and writes and publishes content, builds directory citations and Web 2.0 properties, watches Google for policy changes, and gives every one of Danyal's own end-clients a branded self-serve portal. [CONFIRMED — `[SCOPE-CALL]`, `[ARCH]`, `[PACK-JUL]`]

The product name in the software is **AIOS**. The builder's name (`Xegents`) must never appear anywhere in the running software, its configuration, its tests, or its generated output. The agency name is operator-configurable. [CONFIRMED — `[OVERHAUL]` §A, stated as a hard rule]

### 1.2 What actually happened

- **2026-07-03** — Kickoff call. Three modules agreed: **Audit, Content, Portal**. Off-page was explicitly declared **out of scope** and parked for a later discussion. Build estimated at 3–5 weeks. [CONFIRMED — `[SCOPE-CALL]`]
- **2026-07-09** — Repository created; the six-document client pack delivered. A fourth module, **Policy Radar**, was added as mandatory platform core. [CONFIRMED — `[ARCH]` locked-decision 9, `[PACK-JUL]`]
- **2026-07-17** — An off-page capability-and-economics document was delivered to Danyal committing to citations and Web 2.0 automation at **under 10¢ per unit**. Off-page had, by this point, silently re-entered scope without a recorded scope-change decision. [CONFIRMED — `[CIT-ECON]`; the scope reversal is **STRONG INFERENCE**]
- **2026-07-23** — Operator walkthrough of the running system produced a 17-area defect and rework backlog (`A` through `Q`), whose recurring themes are *hardcoded data*, *demo content presented as real*, *buttons that do nothing*, and *modules that describe themselves rather than run work*. [CONFIRMED — `[OVERHAUL]`]
- **2026-07-28** — System live on `app.qanry.com`. [CONFIRMED — `[WA-ADAN]` 28/07]
- **2026-07-31** — Lead engineer reports "Danyal whole platform is done", pending client-supplied API keys. [CONFIRMED — `[WA-ADAN]` 31/07]
- **August 2026** — A further research plan re-opened four large workstreams: research-first bulk page generation, Elementor-editable publishing, real per-client citation account creation at 40–50+ directories, and a brand-new indexing module. Its own scorecard: **4 built · 3 partial · 4 new**. [CONFIRMED — `[RESEARCH-AUG]`]
- **2026-08-19** — **All scheduled automation was switched off.** `celery_app.conf.beat_schedule = {}`. [CONFIRMED — `[CODE]` `backend/workers/celery_app.py:173`, commit `d57a135`]
- **2026-08-21** — Owner sets an explicit acceptance bar: *"50 audits / pages / citations across 10 different businesses"* before testing phase 1 is even considered complete. [CONFIRMED — `[WA-TEAM]` 21/08]
- **2026-08-22** — Owner takes direct possession of the system and credentials. [CONFIRMED — `[WA-ADAN]` 22/08]

### 1.3 The honest state of the build

The repository is **not empty and not a prototype**. At HEAD it contains ~149,000 lines of Python backend, ~27,000 lines of TypeScript frontend, a separate ~20,000-line audit engine, 80 database migrations, 201 test files, and 321 commits across six weeks. [CONFIRMED — `[CODE]`]

The problem is therefore **not absence of code**. It is that **the code does not add up to a working, trustworthy delivery system**. Six categories of defect are evidenced:

1. **Nothing runs on a schedule.** The Celery beat schedule is empty. No nightly rank tracking, no daily Policy Radar, no weekly audit refresh, no monthly client report, no off-page sweep. Every "automation" in the product is a manual button. A platform sold as *"most of the work runs on its own"* currently runs nothing on its own. [CONFIRMED — `[CODE]`; directly contradicts `[PACK-JUL]` Platform Overview and `[OVERHAUL]` §D "Live, auto-updates DAILY"]
2. **Advertised capabilities are silently degraded in code.** `keywords.winnable` hard-codes `client_da=None`, making it a neutral difficulty screen rather than the promised difficulty-×-authority verdict. `local_seo` GBP sync "always holds — no reader wired". `competitor_intel` backlink-gap "returns an honestly EMPTY set". `on_page`'s drift guard is a plain string compare. A `keyword_research` cost-gate block is **silent** — the caller gets a 202 and no failure signal. [CONFIRMED — `[CODE]` `backend/CLAUDE.md` "KNOWN LIMITATIONS (honest, code-verified — do NOT assume these work)"]
3. **The quality gate that protects content is uncalibrated.** The content QA scorecard is a hard publish gate at a weighted total ≥ 85 with no dimension below 70 — but the threshold and the weight vector are marked **PROVISIONAL** and were never calibrated against a human SEO grade. A hard gate on an uncalibrated score either blocks good work or passes bad work; nobody knows which. [CONFIRMED — `[CODE]` `backend/CLAUDE.md` item 12]
4. **Off-page automation rests on unverified data.** The citation bot has ~50 directory form specifications against a catalogue of 155, and those specs are documented as *"best-effort starting points, not hand-verified against every site's current form"*. The two direct-API citation routes are partner-gated and unconfirmed — Foursquare's documented write endpoint returns 404. [CONFIRMED — `[CODE]` `backend/integrations/citation_bot.py`, `[CIT-CRED]` §4–5]
5. **Demo and dead surfaces reached the client-facing product.** The two most recent commits are literally cleanup of this: *"honest artifact flags (no dead PDF/report buttons)"* and *"production audit cleanup — real cost data … removed fake/unsupported modules"*. That such commits were needed in the final week is itself the evidence. [CONFIRMED — `[CODE]` commits `79d1036`, `62ae44b`; corroborates `[OVERHAUL]` §C, §E, §F, §K, §N]
6. **Scope was never re-baselined after it doubled.** Off-page, GBP posting, indexing, Elementor publishing, bulk page generation and a research module all entered the requirement set after the 3–5 week estimate was given, and the estimate was never restated. [STRONG INFERENCE — `[SCOPE-CALL]` vs `[CIT-ECON]`, `[OVERHAUL]`, `[RESEARCH-AUG]`]

### 1.4 The single most important structural finding

**The platform was built module-by-module against a UI, not workflow-by-workflow against an outcome.**

Evidence: the delivery instruction to the team was *"build the back-end replies to match the shapes already in the front-end's `lib/*` files exactly … the dashboard lights up with zero front-end changes — the fastest path to a working demo"* [`[WA-TEAM]` 11/07]. That is a demo-first instruction, and the product inherited its consequences: every screen has data, most screens have a button, and comparatively few buttons complete a real business outcome end-to-end.

The recovery must invert this. A capability is not "done" because an endpoint returns 200 and a row appears. It is done when **a named business outcome is reliably produced, at volume, with evidence, and survives failure**. This document therefore defines completion in outcome terms throughout (§27, §35).

### 1.5 What the recovery must deliver

Ranked by risk to the client relationship:

| # | Outcome | Why first |
|---|---|---|
| 1 | **Truthfulness** — no dead control, no fabricated number, no demo data, every degraded capability visibly degraded | A client who finds one fake number distrusts every number. This is cheapest to fix and highest in perceived quality. |
| 2 | **Scheduling and job reliability** — beat back on, idempotent, retried, observable, with a dead-letter path | Without it the product is a manual toolbox, not an operating system. |
| 3 | **Content → WordPress, genuinely editable, design-matched** | Named by the owner as ~90% remaining work and the module he is least satisfied with. |
| 4 | **Citations at real volume with proof and cost proof** | A hard written commitment (<10¢/unit) and a hard acceptance bar (50 citations × 10 businesses) already exist. |
| 5 | **Audit quality parity between free and paid, and between HTML and PDF** | The client-visible deliverable; the thing the agency is actually paid for. |
| 6 | **Web 2.0 at 50+ platforms without tripping site-reputation-abuse penalties** | Volume is easy; not harming clients is the hard part. |
| 7 | **Multi-client scale, isolation and credential safety at hundreds of clients** | Currently designed for one agency with ~15 clients. |

---

## 2. PROJECT HISTORY

### 2.1 Cast

| Person / entity | Role | Evidence |
|---|---|---|
| **Danyal** (also written Daniyal / Daniel) | The client. Agency owner. Public brand and lead flow run through Fiverr (`fiverr.com/iamdaani`). Owns the VPS and all accounts. | CONFIRMED — `[SCOPE-CALL]`, `[WA-TEAM]` 15/07 |
| **Zain Saeed** | Project owner / founder, Xegents AI. Sets scope, deadlines and the quality bar. Final approval authority. | CONFIRMED — `[SCOPE-CALL]`, `[WA-ADAN]` passim |
| **Muhammad Adan** | Lead engineer / director. Owns delivery, VPS, deployments, client technical comms. | CONFIRMED — `[WA-ADAN]`, `[WA-TEAM]` |
| **Huzaifa** | Developer — frontend, then AgencyBook SaaS. | CONFIRMED — `[WA-TEAM]` |
| **Arham (UET)** | Junior developer — backend, then the Xegents website. Performance and reliability concerns raised repeatedly; considered for removal from the paid internship 2026-08-01. | CONFIRMED — `[WA-TEAM]`, `[WA-ADAN]` 01/08 |
| **Haseeb Imran** | A *different* client (Storage Visibility). His brief is a sibling, not Danyal's. | CONFIRMED — `[WA-TEAM]` 04/07 |

### 2.2 What was agreed at kickoff — the baseline that governs

From `[SCOPE-CALL]`, 2026-07-03, all **CONFIRMED**:

- Cloud-hosted, not local. The stated reason is **API cost control**, not scalability.
- Three modules: **Audit**, **Content**, **Client Portal**. Reporting via **Google Sheets** as a cross-cutting layer.
- **Off-Page module explicitly out of scope**, to be documented for a future discussion.
- Audit produces **20–30+ page** reports covering on-page, off-page, technical, local and AI elements. Three report types: **Technical**, **Actionable**, **Financial** (financial deferred to Phase 2).
- Clients can run **free or paid** audits from the portal.
- Content targets **~90% automation**, hours→minutes per page, at an estimated **$10–50 per page**.
- Content has two publishing paths: **manual PDF** and **automated WordPress REST API**.
- **Upsells link to Fiverr gigs, not internal services** — a deliberate brand decision to protect the agency's Fiverr-centred public identity.
- Milestones auto-update; a super-admin dashboard monitors team activity and client status.
- New feature requests are documented for a future phase **to avoid delaying the core project**.

That last line is the governance rule the project subsequently broke.

### 2.3 Decisions locked after kickoff

From `[ARCH]`, all **CONFIRMED**:

1. Audit reuses the existing audit engine, wrapped as a cloud job.
2. Stack: Next.js + FastAPI + Postgres + Redis, Docker Compose on one VPS.
3. Agency pre-loads API keys into a central encrypted vault. **No payment gateway in v1**; the agency controls free vs paid tiers.
4. WordPress REST API for publishing in v1; other CMSs later.
5. Images AI-generated with automatic alt text.
6. Agency-provisioned accounts only. **No public signup.**
7. Financial audit report documented now, built Phase 2.
8. Off-page out of scope for v1.
9. **Policy Radar is mandatory core in every AIOS deployment.**
10. Deliverable audience: internal founder-grade architecture and build plan.

### 2.4 The scope events that were never re-baselined

| Date | Event | Scope effect | Estimate restated? |
|---|---|---|---|
| 2026-07-09 | Policy Radar declared mandatory core | +1 module (research worker, change detection, KB, Command Center) | No |
| 2026-07-17 | Citations & Web 2.0 economics delivered to client | Off-page re-enters scope, with a **written cost commitment** | No |
| 2026-07-23 | Operator walkthrough | 17 areas of rework + GBP module (§J) as a **new section** | No |
| 2026-08 | Research & Build Plan | +Research module, +bulk page fan-out, +Elementor output, +design matching, +per-client citation account creation, +**entire Indexing module** | No |
| Ongoing | Web 2.0 platform count | 8 clean → 16–17 → 40 → 50 platforms via successive commit batches | No |

[STRONG INFERENCE] The project never had a scope-change control point. Each addition arrived as an instruction and was absorbed into the same 3–5 week frame. This, more than any individual engineering defect, explains an outcome the owner describes as *"10–20% of scope"*: the denominator grew roughly threefold while the numerator was measured against the original three modules.

### 2.5 Process failures that shaped the code

All **CONFIRMED** from `[WA-TEAM]` / `[WA-ADAN]`:

- **Demo-first build order.** Backends were shaped to fit an existing mock-data frontend (11/07). Consequence: schemas that satisfy a screen rather than a workflow.
- **Deadlines habitually missed.** *"If I assign something for 5 days to complete, it should get done in 4, rather than exceeding the deadline up to 3–7 days"* (17/08). *"8 days over and not even one website is final"* (01/08).
- **Self-verification not performed.** *"test everything yourself manually, write every point, every use case"* (16/07) — followed later by *"even after that work quality is not up to the mark"* (17/08).
- **AI-tool budget treated as the constraint.** Repeated messages about Claude session limits, model downgrades to Haiku/Sonnet to conserve quota, and instructions to stop working to preserve the last 10%. Quality decisions were being made against a token budget.
- **Credential hygiene incidents.** Live admin, team, client and WordPress credentials were transmitted in plain WhatsApp messages on at least six occasions (05/08, 15/08, 22/08). A separate exchange (21/07) confirms client-supplied API keys were *not* to be shared with the wider team — meaning the team was operating with an explicit, informal secrets policy that the tooling did not enforce.
- **The owner's stated bar was never met before hand-off.** *"I want 50 audits / pages / citations built for 10 different businesses, and only then is testing phase 1 done, then it comes to me, then to the client for the 3rd wave of testing"* (21/08). No evidence exists that any such volume run was executed.

---
## 3. PRODUCT DEFINITION

### 3.1 What the Daniel system is

**AIOS (Danyal deployment) is a single-tenant, white-labelled SEO delivery operating system, owned and hosted by one agency, that runs the agency's recurring local-SEO service line end-to-end and exposes a self-serve portal to that agency's own customers.** [CONFIRMED — synthesis of `[SCOPE-CALL]`, `[ARCH]`, `[PACK-JUL]`]

Three sentences that bound it precisely:

- It is **one agency's system**, not a product sold to many agencies. (The multi-agency product is a separate project, AgencyBook.) [CONFIRMED — `[ARCH]` §8 "multi-tenant, single agency per deployment"]
- It is **delivery**, not acquisition. There is no CRM, no sales pipeline, no proposal engine, no invoicing in v1. Lead flow stays on Fiverr by deliberate decision. [CONFIRMED — `[SCOPE-CALL]` upsell decision; `[ARCH]` out-of-scope list]
- It is **human-gated**. Every artefact that reaches a client — report, email, published page, listing — passes a person first. This is stated identically in every client-facing document and is treated as non-negotiable. [CONFIRMED — `[PACK-JUL]`, `[ARCH]`, `[KB]`]

### 3.2 The problem it solves

| Problem | Evidence | The system's answer |
|---|---|---|
| Manual audits and content take hours per page | `[SCOPE-CALL]` | Automate the production, keep the judgement |
| Automated runs burn unpredictable API budget | `[SCOPE-CALL]` — the stated reason for cloud | A per-feature, per-client cost dial with a hard daily spend-stop |
| The agency's delivery capacity is bounded by its owner's hours | STRONG INFERENCE | Team portal + task queue + review gate so specialists execute and the owner approves |
| Clients ask "what are you doing for me?" | `[SCOPE-CALL]` portal + milestones | A live client portal with reports, milestones and evidence |
| Off-page work (citations, Web 2.0) is slow, repetitive and expensive to buy | `[CIT-ECON]` | Self-hosted automation at ~1¢/unit against $2–5 managed services |
| Google changes and the agency finds out late | `[ARCH]` §6 | Policy Radar: watch, diff, research, flag, recommend |

### 3.3 Users

| User | Who they are | Count today | Count at target |
|---|---|---|---|
| **Super Admin / Owner** | Danyal | 1 | 1 |
| **Admin** | Trusted operator with everything except owner-only vault reveal | 0–1 | 1–3 |
| **Manager / Lead** | Routes work, signs off review gates | 0 | 1–5 |
| **Specialist / Analyst / Team member** | Executes audits, content, off-page | 0 | 5–20 |
| **Client** | Danyal's own customer, portal-only | test data | **CONFLICTING: 15 vs hundreds** |

The client-count conflict is material to nearly every architectural decision and is escalated in §30 and `DECISIONS_REQUIRED.md`.

### 3.4 Core business workflows

Nine workflows constitute the product. Each is specified in §12–§19 and §21.

| # | Workflow | Trigger | Human gate | Output |
|---|---|---|---|---|
| W1 | **Free lead audit** | Public form / client portal | Optional | Condensed report + Fiverr upsell path |
| W2 | **Paid audit** | Staff or client, tier-gated | Review before send | Full report (HTML + PDF + findings JSON + remediation) |
| W3 | **Content: single page** | Staff | **Mandatory** review before publish | Published, editable, design-matched WordPress page + live URL |
| W4 | **Content: research-first bulk build** | Staff | Two gates — page-set approval, then draft review | N published pages + URL manifest |
| W5 | **Citation campaign** | Staff | Approve target list; finish-queue for gated directories | Live listings + proof screenshots + URLs + cost ledger |
| W6 | **Web 2.0 campaign** | Staff | **Mandatory** lead approval per property | Live articles with one editorial link each |
| W7 | **GBP posting** | Staff / schedule | Approve draft | Published GBP post |
| W8 | **Policy Radar loop** | Scheduled diff + on-demand | Acknowledge / Apply / Dismiss | KB entries + recommendations + audit overlays |
| W9 | **Client reporting** | Schedule / on demand | Approve before send | Branded report, Sheet, portal update, notification |

### 3.5 What the system automates vs what requires a human

**Automated (no human in the loop):** crawling, data fetching, SERP and rank queries, scoring, draft generation, image generation, schema construction, QA scoring, directory form filling, CAPTCHA solving, email-confirmation clicking, Web 2.0 API publishing, change detection, KB summarisation, cost accounting, Sheet writes, milestone advancement, notification dispatch. [CONFIRMED — `[ARCH]`, `[CIT-ECON]`, `[CODE]`]

**Human-gated (mandatory, in every tier):**
1. Content publish — the "final 10%". [CONFIRMED — universal across all sources]
2. Web 2.0 property go-live — lead approval. [CONFIRMED — `[KB]` modules §03]
3. Policy Radar recommendation application — nothing changes a live audit check or client advice without confirmation. [CONFIRMED — `[ARCH]` §6]
4. Any client-facing report or email. [CONFIRMED — `[PACK-JUL]`]
5. Citation submissions on directories that re-gate at the final step ("ready to finish" queue). [CONFIRMED — `[OFFPAGE-STATUS]`]
6. **PROPOSED:** any live-site mutation (on-page fix apply, page republish, GBP profile edit) and any spend above a per-run threshold.

### 3.6 Information in / information out

**In:** client business identity and canonical NAP; websites and CMS credentials; Google access (GSC owner, GA4 viewer, GBP manager) via service account; target keywords, cities, competitors; brand assets; agency API keys; CSV/XLSX imports (Fiverr client data, Ahrefs/SEMrush backlink exports, Screaming Frog crawls, rank exports); Web 2.0 and directory account credentials; operator instructions and approvals.

**Out:** audit reports (HTML, PDF, findings JSON, remediation sheets); published WordPress pages and posts with schema, images and metadata; GBP posts; directory listings with proof URLs and screenshots; Web 2.0 articles with editorial links; indexing submissions; client-facing Google Sheets; branded periodic reports; email and in-app notifications; a cost ledger; an append-only activity log.

**External systems touched:** Google Search Console, Google Analytics 4, Google Business Profile / Places, Google PageSpeed Insights / CrUX, Google Indexing API, IndexNow (Bing/Yandex), serper.dev, DataForSEO, Moz (optional), Firecrawl, Apify, Anthropic Claude, OpenAI images, Voyage embeddings, Pinecone, Google Sheets, Resend, SMTP/IMAP, Slack, Backblaze B2, WordPress (REST / XML-RPC / custom plugin), ~155 citation directories, ~50 Web 2.0 platforms, a CAPTCHA solver, a residential proxy pool. [CONFIRMED — `[CODE]` `backend/integrations/`, `[KB]` apis-and-keys]

### 3.7 Expected business outcomes

| Outcome | Target | Source | Class |
|---|---|---|---|
| Content effort | Hours → minutes per page; ~90% automated | `[SCOPE-CALL]` | CONFIRMED |
| Content cost | $10–50 per page | `[SCOPE-CALL]` | CONFIRMED |
| Citation unit cost | **< 10¢** per successful citation | `[CIT-ECON]` (written to client) | CONFIRMED |
| Citation unit cost | ≤ 20¢ | Operator, 2026-08-23 | CONFLICTING — see §30.2 |
| Citation coverage | ~100 valuable platforms | Operator, 2026-08-23 | CONFIRMED |
| Web 2.0 coverage | 50+ platforms | Operator, 2026-08-23 | CONFIRMED |
| Platform running cost | ~$44–64/mo shared + $0/$20/$54 per client per tier | `[PACK-JUL]` Service Tiers | CONFIRMED (but see §30.1) |
| Acceptance volume | 50 audits, 50 pages, 50 citations across 10 businesses | `[WA-TEAM]` 21/08 | CONFIRMED |
| Client harm | Zero penalties, zero suspensions, zero NAP corruption | `[CIT-ECON]`, operator | CONFIRMED |

### 3.8 Danyal's private system vs the AgencyBook public SaaS — the separation rule

| Dimension | **Danyal AIOS (this project)** | **AgencyBook SaaS (separate)** |
|---|---|---|
| Tenancy | One agency per deployment | Many agencies, provider-hosted |
| Signup | None; owner provisions | Public self-serve |
| Billing | None in v1 | Subscription billing |
| Keys | Agency-owned, one vault | Per-tenant, swappable |
| Branding | White-label, operator-set | Product-branded |
| Isolation | App-layer + RLS within one org | Hard tenant boundary required |
| Governance | Owner's judgement | Product roadmap |

**Rule for the recovery team:** a capability may be *inspired* by the AgencyBook research corpus (which contains genuinely strong first-principles work on GBP account models, geo-grid build-vs-buy, WordPress integration and cost architecture) but **may not be imported into Danyal's scope** unless it serves a workflow in §3.4. Specifically **excluded** from Danyal v1 unless separately decided: subscription billing, public signup, tenant provisioning, per-tenant AI key swapping, agency marketplace features, and Haseeb-specific constructs (facility entity, PMS integration, unit-mix and storage seasonality intelligence, screenshot-based time tracking). [PROPOSED, grounded in `[SCOPE-CALL]` scope-management rule]

---

## 4. BUSINESS OBJECTIVES

| ID | Objective | Measure | Class |
|---|---|---|---|
| BO-1 | Deliver the agreed scope to a quality the client accepts, by the extended deadline | Client sign-off; zero P1 defects open | CONFIRMED |
| BO-2 | Make delivery capacity independent of any one person's hours | ≥ 3 concurrent client campaigns run by non-owner staff without owner intervention | STRONG INFERENCE |
| BO-3 | Keep per-client running cost predictable and capped | 100% of paid calls pass a dial + cap + daily stop; zero unbudgeted spend events | CONFIRMED — `[SCOPE-CALL]`, `[OVERHAUL]` §E |
| BO-4 | Produce SEO work that actually ranks, not merely output that exists | Rank/impression movement on a tracked cohort; human SEO grade on sampled artefacts | STRONG INFERENCE — operator's repeated "results" framing |
| BO-5 | Never harm a client's search presence | Zero manual actions, zero listing suspensions, zero NAP inconsistencies introduced | CONFIRMED — `[CIT-ECON]` site-reputation-abuse rule |
| BO-6 | Protect the agency's Fiverr-centred brand | Upsells route to Fiverr; builder brand absent from all surfaces | CONFIRMED — `[SCOPE-CALL]`, `[OVERHAUL]` §A |
| BO-7 | Hand over a system the client fully owns and can operate | All accounts in client's name; runbook; no builder lock-in | CONFIRMED — `[PACK-JUL]` |
| BO-8 | Make the system reusable as the agency's product line | Time to stand up client #3 measured in days | STRONG INFERENCE — `[WA-ADAN]` 15/08 |

---

## 5. SCOPE

### 5.1 In scope — recovery v1

**Portals and access**
- S-1 Four role-scoped portals on one app and one login: Client, Team, Manager (may fold into Admin), Admin/Super-Admin. [CONFIRMED]
- S-2 Six staff roles + `client`; a 17-feature permission matrix with per-person overrides; four role templates. [CONFIRMED — `[PACK-JUL]`, `[CODE]`]
- S-3 Owner-only provisioning. No public signup. [CONFIRMED]

**Audit**
- S-4 Free audit: one condensed report (~10–15 pages), no type split, download + in-dashboard paginated HTML viewer, real Fiverr gigs as the upsell. [CONFIRMED — `[OVERHAUL]` §G]
- S-5 Paid audit: type-selectable (on-page / technical / off-page / local / GEO / strategy); none selected = run all. [CONFIRMED — `[OVERHAUL]` §H]
- S-6 PDF and in-dashboard HTML must be the *same document*. [CONFIRMED — `[OVERHAUL]` §H]
- S-7 Findings JSON + role-based remediation sheets. [CONFIRMED — `[CODE]`]
- S-8 Every finding carries evidence; no invented metrics. [CONFIRMED — `[KB]`]

**Content**
- S-9 Research module: pick a content type, system studies site + competitors, recommends the page set, operator ticks. [CONFIRMED — `[RESEARCH-AUG]`]
- S-10 Bulk one-click fan-out across selected pages, returning a URL manifest. [CONFIRMED — `[RESEARCH-AUG]`]
- S-11 Content types: service, location, service×location, service-area, GSC-opportunity, blog, FAQ, GBP post, titles/meta in bulk. [CONFIRMED]
- S-12 Draft against local-SEO copy frameworks (AIDA and siblings), JSON-LD schema, AI images with alt **and title** text, internal links. [CONFIRMED]
- S-13 **Zero em dashes** anywhere; AI-sounding detection with section-by-section rewrite on failure. [CONFIRMED — `[OVERHAUL]` §I]
- S-14 One mandatory human review gate with a true in-dashboard preview and a WYSIWYG editor. [CONFIRMED]
- S-15 Publish to WordPress as **fully editable** pages — Elementor widget tree and/or native Gutenberg blocks — never flat HTML. [CONFIRMED — `[RESEARCH-AUG]`]
- S-16 Design matching: read and reuse the site's existing style kit; else generate a niche-appropriate clean layout. [CONFIRMED — `[RESEARCH-AUG]`]
- S-17 Manual PDF/Markdown export path retained. [CONFIRMED — `[SCOPE-CALL]`]
- S-18 Scheduling, versioning, republish, rollback. [CONFIRMED — `[CODE]`; **PROPOSED** for rollback]

**WordPress**
- S-19 One-time per-site connection with sealed credentials; capability discovery (Elementor? Gutenberg? ACF? theme? SEO plugin?). [CONFIRMED — `[RESEARCH-AUG]`, `[WA-ADAN]` 08/07 ACF exchange]
- S-20 Companion plugin for what REST cannot do safely. [CONFIRMED — `[CODE]` `wordpress-plugin/aios-publisher`]
- S-21 SEO surface: slug, canonical, meta title/description, robots directives, schema, sitemap, internal links, media library, alt + title. [CONFIRMED]
- S-22 Performance discipline: DOM size, page weight, Core Web Vitals, no raw CSS dumped into post content, responsive breakpoints. [CONFIRMED — `[WA-TEAM]` 07/07 client questions; `[CODE]` commit `faeec43`]
- S-23 Draft → preview → publish → revision history → revert. [CONFIRMED + **PROPOSED** for revert]

**Citations**
- S-24 Canonical business profile per client (and per location) with ~20 fields, not just NAP. [CONFIRMED — `[RESEARCH-AUG]`]
- S-25 Citation audit: what exists, where, and what is inconsistent — prioritised generic → country → niche. [CONFIRMED — `[OVERHAUL]` §K, `[RESEARCH-AUG]`]
- S-26 Build only where not already listed. [CONFIRMED — `[OVERHAUL]` §K]
- S-27 Per-client account creation with a readable mailbox and automatic confirmation-link clicking. [CONFIRMED — `[RESEARCH-AUG]`]
- S-28 Submission across ~100 valuable platforms, with proof URL + screenshot per unit. [CONFIRMED — operator; `[CIT-ECON]`]
- S-29 A "ready to finish" handoff queue for directories that gate the final click. [CONFIRMED — `[OFFPAGE-STATUS]`]
- S-30 Per-unit cost accounting against the ceiling. [CONFIRMED]
- S-31 Duplicate detection, NAP drift monitoring, re-verification. [CONFIRMED — `[KB]`]

**Web 2.0**
- S-32 50+ platforms with live publishing. [CONFIRMED — operator]
- S-33 Per-client identity and platform mix; never a templated blast. [CONFIRMED — `[CIT-ECON]`]
- S-34 Unique content per property, human-paced. [CONFIRMED — `[CIT-ECON]`]
- S-35 Lead approval before go-live. [CONFIRMED — `[KB]`]
- S-36 Account health monitoring and honest per-platform failure attribution. [CONFIRMED — `[OVERHAUL]` §K]

**GBP**
- S-37 GBP post generation following Google policy; operator-reviewed. [CONFIRMED — `[OVERHAUL]` §J]

**Indexing**
- S-38 IndexNow + Google Indexing API + sitemap ping on every publish, with status tracking. [CONFIRMED — `[RESEARCH-AUG]`]

**Intelligence**
- S-39 Policy Radar: **daily** live source diff, Claude categorisation, versioned KB, region/severity/category flags, Command Center, audit overlays, human confirm. [CONFIRMED — `[ARCH]` §6, `[OVERHAUL]` §D]

**Platform**
- S-40 Encrypted key vault; agency-wide and per-client scopes; owner-only reveal. [CONFIRMED]
- S-41 Cost dial per feature per client; client cap; daily spend-stop that halts **every** API. [CONFIRMED — `[OVERHAUL]` §E]
- S-42 **Runtime-computed cost only. No predefined or hardcoded price anywhere.** [CONFIRMED — `[OVERHAUL]` §E]
- S-43 Task queue, board, assignment, review checkpoint, live team metrics. [CONFIRMED]
- S-44 Milestones auto-advanced from delivery events. [CONFIRMED]
- S-45 Google Sheets reporting; cron-driven real reports showing which jobs ran, what they do, when scheduled. [CONFIRMED — `[OVERHAUL]` §N]
- S-46 Email + in-app + Slack notifications; every required notification enabled. [CONFIRMED — `[OVERHAUL]` §Q]
- S-47 Append-only activity log on every mutation. [CONFIRMED]
- S-48 Backups with restore. [CONFIRMED]
- S-49 PWA with mobile notifications (bonus). [CONFIRMED — `[WA-ADAN]` 04/08]
- S-50 No hardcoded data anywhere in admin, team or client surfaces. [CONFIRMED — `[OVERHAUL]` §C]

### 5.2 Out of scope — v1

| Item | Reason | Class |
|---|---|---|
| Self-serve payment gateway / Stripe | Locked out | CONFIRMED |
| Public self-signup | Locked out | CONFIRMED |
| Financial audit report (market capacity + revenue) | Deferred to Phase 2 at kickoff | CONFIRMED |
| Non-WordPress CMS connectors as a headline capability | Phase 2 | CONFIRMED |
| Sales pipeline / CRM / proposals / invoicing | Not Danyal's scope; brand stays on Fiverr | STRONG INFERENCE |
| Screenshot/clock-in employee surveillance | Haseeb's brief, not Danyal's | CONFIRMED — quarantine rule |
| Facility entity, PMS integration, storage-specific intelligence | Haseeb's brief | CONFIRMED |
| Per-client custom domains for portals | Not in Danyal's evidence | UNKNOWN → treat as out until decided |
| Outreach email sequencing / link-building outreach | Listed as "later phase" in tiers | CONFIRMED |
| Multi-agency tenancy | That is AgencyBook | CONFIRMED |

### 5.3 Explicitly undecided (blocks work if unresolved)

Numbered in `DECISIONS_REQUIRED.md`. Headlines: true client count; the citation cost ceiling of record; the single rankings source; whether Manager is a distinct portal; whether the client portal is per-client branded; whether Upsells are in or out; the Elementor-vs-Gutenberg default; whether GBP publishing uses owned API access or drafts only.

---
## 6. OUT-OF-SCOPE ITEMS — RATIONALE AND GUARD

Recorded separately because scope leakage is the project's primary failure mode.

**Guard rule (PROPOSED, adopt as governance):** any capability not traceable to a requirement ID in `REQUIREMENTS_TRACEABILITY.md` is a change request. It gets an ID, an evidence class, an estimate, and a written owner decision **before** code. New instructions arriving mid-sprint are logged, not absorbed.

| Category | Excluded | Why | Revisit when |
|---|---|---|---|
| Commerce | Stripe, subscriptions, dunning, self-serve plans | No payment gateway in v1 [CONFIRMED] | Danyal asks to sell portal seats |
| Acquisition | CRM, deals, proposals, e-sign, outreach sequencing | Brand deliberately stays on Fiverr | Danyal moves off Fiverr |
| Workforce | Screenshots, clock-in, pulse surveys, skill matrix | Haseeb's brief only | Never for Danyal without explicit request |
| Vertical | Facility entity, PMS, unit-mix, seasonality, pricing intel | Haseeb's vertical | Never |
| Platform | Multi-tenant provisioning, per-tenant AI keys, tenant billing | AgencyBook's product | Never in this repo |
| Reporting | Bespoke charting engine | Google Sheets chosen deliberately for v1 | Client rejects Sheets |
| Content | Video, podcast, social scheduling beyond GBP | Not evidenced | On request |
| SEO | Paid link buying, PBNs, scaled templated Web 2.0 networks | **Prohibited** — causes client harm | Never |

The last row is a hard prohibition, not a scope choice. It is grounded in the March 2026 Site Reputation Abuse enforcement cited in `[CIT-ECON]` and in BO-5.

---

## 7. EVIDENCE CLASSIFICATION SUMMARY

Counts across this document's requirement set (full detail in `REQUIREMENTS_TRACEABILITY.md`).

| Class | Approx. count | What it means for the recovery team |
|---|---|---|
| CONFIRMED | ~150 | Build to this. It is what was agreed or what the code provably does. |
| STRONG INFERENCE | ~45 | Build to this, but state the inference in the build plan so the owner can veto. |
| PROPOSED | ~70 | Do not build without an owner decision. Each is justified on reliability, safety, scale, UX or SEO outcome. |
| CONFLICTING | 13 | **Blocking.** Listed in §30. Do not silently resolve. |
| UNKNOWN | 24 | Listed in `OPEN_QUESTIONS.md`. Some are blocking, most are answerable in one sentence. |

### 7.1 Source-priority ladder applied in this document

1. Explicit current business requirement (operator instruction, 2026-08-23).
2. Explicit client requirement (Danyal, in call or in a delivered document).
3. Explicit final decision by the project owner (Zain).
4. A requirement repeated consistently across conversations.
5. Product/business logic implied by the workflow.
6. Agency Book and research material.
7. Technical discussions between developers.
8. Previous implementation decisions.
9. Casual statements, guesses, abandoned ideas.

**Applied consequences, worth stating explicitly:**

- The **10¢ citation ceiling** (level 2 — written to the client) outranks the **20¢ ceiling** (level 1 — current operator statement) *as a commitment*, while 20¢ is the current business constraint. The engineering target is therefore **≤10¢, with 20¢ as the hard fail line**. [Resolution proposed; needs owner confirmation — D-2]
- **Off-page being out of scope** (level 1/3, 2026-07-03) is superseded by the operator's current instruction and by a document already delivered to the client (level 2, 2026-07-17). Off-page is **in scope**.
- **"Remove the Upsells section (for now)"** (level 3, 2026-07-23) conflicts with the Fiverr upsell decision (level 2, 2026-07-03). Unresolved — D-6.
- **The existing implementation's choices carry no requirement weight.** Level 8. Where the code contradicts the brief, the brief wins; where the brief is silent, the code is evidence of intent only, not of correctness.

---

## 8. USER ROLES

### 8.1 The role set

Six staff roles plus one client role are implemented and evidenced. [CONFIRMED — `[CODE]` `app/rbac/matrix.py`, mirrored in `frontend/lib/data.ts`]

| Role | Purpose | Key boundary |
|---|---|---|
| **Owner (Super Admin)** | Danyal. Everything. | **All-on and locked** — cannot be reduced. Only role that can reveal a vault secret. |
| **Admin** | Full operational control | No vault reveal; cannot modify Owner |
| **Manager / Lead** | Assigns work, signs off review gates | Cannot manage keys or provision Owners |
| **Specialist** | Executes audits, content, off-page | Cannot approve own work |
| **Analyst** | Reads data, builds reports | No live-site mutations |
| **Viewer** | Read-only staff | No mutations at all |
| **Client** | Danyal's customer | Own data only; hard-walled from the staff namespace |

Three role *templates* are documented client-side (SEO Specialist, Content Creator, Virtual Assistant) as fast starting points over the 17-feature matrix; a fourth template exists in code. [CONFIRMED — `[PACK-JUL]` Roles & Access Control; `[CODE]` "17-feature matrix + 6 roles + 4 templates"]

### 8.2 Two-layer model

**Layer 1 — role**: sets a sensible default across 17 features.
**Layer 2 — per-person feature grants**: each of the 17 features can be set Full / View / Off for an individual, overriding the template. [CONFIRMED — `[PACK-JUL]`]

**PROPOSED additions** (`SEC-*`, §22):
- A **deny always wins** rule so an override can only narrow, never widen, beyond the role ceiling — except by Owner action, which is logged.
- **Separation of duties**: the actor who created or drafted an artefact may not be the actor who approves it. Currently the content trigger enforces that a non-lead can drive nothing, but does not prevent a lead approving their own draft. [`[CODE]` item 12 — the trigger permits it]
- **Break-glass**: a time-boxed elevated session, logged, notified, auto-expiring.

### 8.3 The client role is a different kind of principal

Clients are not staff with fewer switches. Every client-facing route sits behind a distinct dependency and is scoped to the caller's own `client_id`, with base tables unreachable and internal fields (`mrr`, `cost`, `error`, artefact paths) never on the wire. An integration test provisions two client tenants and proves, using each client's own database identity, that cross-client reads return zero rows. [CONFIRMED — `[CODE]` `tests/integration/test_portal_isolation.py`, verified live]

This is the single strongest piece of engineering in the current build and **must be preserved through any rewrite**.

---

## 9. PERMISSION MATRIX

### 9.1 Feature × role

`F` = full · `V` = view only · `—` = no access · `O` = owner only

| # | Feature | Owner | Admin | Manager | Specialist | Analyst | Viewer | Client |
|---|---|---|---|---|---|---|---|---|
| 1 | Dashboard (agency) | F | F | F | V | V | V | — |
| 2 | Clients & sites | F | F | V | V | V | V | — |
| 3 | Client business profile / NAP | F | F | F | F | V | V | V* |
| 4 | Audit — run | F | F | F | F | — | — | F† |
| 5 | Audit — read reports | F | F | F | F | F | V | own only |
| 6 | Content — create / draft | F | F | F | F | — | — | request only |
| 7 | Content — **approve / publish** | F | F | F | — | — | — | — |
| 8 | On-page — apply to live site | F | F | F | — | — | — | — |
| 9 | Citations — audit / plan | F | F | F | F | V | V | V* |
| 10 | Citations — **submit (spend)** | F | F | F | — | — | — | — |
| 11 | Web 2.0 — plan / draft | F | F | F | F | V | V | — |
| 12 | Web 2.0 — **approve / publish** | F | F | F | — | — | — | — |
| 13 | GBP — draft | F | F | F | F | V | V | — |
| 14 | GBP — publish | F | F | F | — | — | — | — |
| 15 | Keyword research | F | F | F | F | F | V | — |
| 16 | Rank tracker | F | F | F | F | F | V | V* |
| 17 | Competitor intel | F | F | F | F | F | V | — |
| 18 | Local SEO / geo-grid | F | F | F | F | F | V | V* |
| 19 | Reports — build | F | F | F | F | F | V | — |
| 20 | Reports — **send to client** | F | F | F | — | — | — | — |
| 21 | Tasks — own queue | F | F | F | F | F | V | — |
| 22 | Tasks — assign | F | F | F | — | — | — | — |
| 23 | Milestones | F | F | F | V | V | V | V |
| 24 | Data import | F | F | F | F | F | — | — |
| 25 | Cost dials & caps | F | F | V | — | — | — | — |
| 26 | Key vault — list (masked) | F | F | — | — | — | — | — |
| 27 | Key vault — **reveal** | **O** | — | — | — | — | — | — |
| 28 | Integrations / API management | F | F | V | — | — | — | — |
| 29 | Team & access management | F | F | V | — | — | — | — |
| 30 | Policy Radar — read | F | F | F | F | F | V | — |
| 31 | Policy Radar — **apply recommendation** | F | F | F | — | — | — | — |
| 32 | Activity log | F | F | V | — | — | — | — |
| 33 | Backups — run / restore | **O** | F‡ | — | — | — | — | — |
| 34 | Settings — agency identity | F | F | — | — | — | — | — |
| 35 | Tickets / requests | F | F | F | F | F | V | own only |
| 36 | Upsells manager | F | F | — | — | — | — | V |
| 37 | Indexing submissions | F | F | F | F | — | — | — |

\* Read-only view of their own record.
† Tier-gated: a client on the Free delivery tier cannot start a Paid audit. Enforced server-side. [CONFIRMED — `[CODE]`]
‡ Restore requires a second confirmation step. [CONFIRMED — `[KB]`]

### 9.2 Invariants the matrix must hold

| ID | Invariant | Class |
|---|---|---|
| PM-1 | Owner is all-on and cannot be reduced | CONFIRMED |
| PM-2 | Vault reveal is owner-only, always, in every tier | CONFIRMED |
| PM-3 | A client can never reach a staff route; staff routes require a permission no client holds | **PARTIAL — was marked "CONFIRMED — enforced + tested" and was false (measured 2026-08-24).** The second clause is the one that misled: a staff route did *not* require a permission, it required only authentication. `/rbac/{features,permissions,roles,templates}` and `/cost/pricing` returned the agency's access model and supplier unit prices to any signed-in principal, a portal client included, and served them from **in-process constants** so no RLS policy stood behind them. Closed by `require_staff()` with a negative test per boundary (D-19). **14 route handlers still carry `CurrentUserDep` alone** (AST-measured, listed in D-19): they are bounded by RLS rather than by the app layer — `/clients` returns zero rows to a client via `clients_select using (public.is_staff())` — and that has NOT been measured handler by handler against a built database. `/tiers` is deliberately client-readable (D-19). |
| PM-4 | Every spend-causing action requires an explicit permission, never merely "logged in" | STRONG INFERENCE |
| PM-5 | Every live-site or third-party mutation requires a lead-or-above and is attributed to that human | CONFIRMED for on-page (`0038` guard trigger); **PROPOSED** to generalise |
| PM-6 | Permission is enforced server-side; UI hiding is presentation only | CONFIRMED |
| PM-7 | **PROPOSED** — an approver may not be the author of the artefact they approve | PROPOSED |
| PM-8 | **PROPOSED** — permission changes are versioned and diffable, not just logged | PROPOSED |
| PM-9 | The matrix has exactly one source of truth; the frontend copy is generated from it, never hand-mirrored | **PROPOSED** — today it is mirrored by hand (`app/rbac/matrix.py` ↔ `frontend/lib/data.ts`), which is a drift bug waiting to happen |

---

## 10. ADMIN PORTAL

Each capability is specified as **INPUT → PROCESS → OUTPUT · PERMISSIONS · DEPENDENCIES · FAILURE CASES · EXPECTED UX**.

Cross-cutting rules that apply to every capability below, all **CONFIRMED** from `[OVERHAUL]`:

- **No hardcoded data.** Every metric is live, including costs.
- **No dead controls.** A rendered control performs its action or is not rendered.
- **No fixed prices.** Cost is computed at runtime from actual usage.
- **A feature must run real work**, not describe itself.

### ADM-A · Dashboard

- **INPUT** — authenticated staff identity; optional date range and client filter.
- **PROCESS** — aggregate live counts and rollups: active clients, sites, running/queued/failed jobs by type, audits this period, content in each pipeline state, citations live/pending/failed, Web 2.0 published/awaiting approval, open tasks by assignee, spend today vs cap, provider health, unread Policy Radar recommendations, recent activity.
- **OUTPUT** — a control surface where every tile is a live number and every tile is a link into the filtered list behind it.
- **PERMISSIONS** — Owner/Admin full; Manager full; Specialist/Analyst/Viewer read.
- **DEPENDENCIES** — activity log, job store, cost ledger, all module repositories.
- **FAILURE CASES** — a module's store unavailable → that tile shows *unavailable*, never zero (a false zero reads as "nothing happening"); a slow rollup must not block the page; stale caches must display their age.
- **EXPECTED UX** — the header carries no marketing subtitle [CONFIRMED — `[OVERHAUL]` §C]. Load under 1.5 s on cached rollups. Anything queued, failed or awaiting a human is surfaced above the fold, because those are the only things that need a human today.

### ADM-B · Users & team

- **INPUT** — name, email, role template, per-feature overrides.
- **PROCESS** — provision the credential and identity in one privileged transaction; apply the template; apply overrides; optionally dispatch an invite email; write an activity entry.
- **OUTPUT** — an account that can sign in and sees exactly the enabled features.
- **PERMISSIONS** — Owner/Admin.
- **DEPENDENCIES** — auth, RBAC matrix, Resend, activity log.
- **FAILURE CASES** — duplicate email; invite email fails (must not roll back the account — surface "created, invite failed, resend"); an override attempting to exceed the role ceiling must be rejected with a reason, not silently dropped; deactivation must reassign or explicitly orphan that user's open tasks. **Known defect:** task assignment does not list team members correctly [CONFIRMED — `[OVERHAUL]` §M].
- **EXPECTED UX** — under a minute from "add person" to "they can work". Credentials shown once with copy buttons. Either invites genuinely send or the invite control is removed [CONFIRMED — `[OVERHAUL]` §L].

### ADM-C · Clients

- **INPUT** — client name, contact, delivery tier, branding, **and the full business profile at creation**: legal/business name, canonical address (per location), phone, website, email, categories, description, hours, logo/photos, social profiles, year founded, payment types, service area, tagline. [CONFIRMED — `[OVERHAUL]` §K/§L, `[RESEARCH-AUG]`]
- **PROCESS** — create the client, seed the business profile, provision the portal login, seal any supplied credentials into the vault, create the default milestone set, register the Sheet workbook.
- **OUTPUT** — a client that Citations, Local SEO, Content and Reporting can all use **without asking for the same data again**.
- **PERMISSIONS** — Owner/Admin create/delete; Manager edit.
- **DEPENDENCIES** — vault, milestones, Sheets, citations profile.
- **FAILURE CASES** — the current defect is exactly here: *"No business profile yet for this client"* blocks citations because NAP was never collected [CONFIRMED — `[OVERHAUL]` §K]. Deleting a client with live listings, published pages and Web 2.0 properties must be a guarded, evidence-listing operation, never a cascade delete. Multi-location clients need one profile per location, not one per client.
- **EXPECTED UX** — one wizard, progressive, resumable, with a completeness meter that tells the operator which downstream modules are currently blocked and why.

### ADM-D · Sites / websites

- **INPUT** — domain, CMS type, credentials (application password or plugin token), optional staging URL.
- **PROCESS** — verify reachability; **discover capability** — WordPress version, REST availability, Elementor present and version, Gutenberg, ACF with `show_in_rest`, active SEO plugin, theme, caching layer, existing page inventory, sitemap, robots; seal credentials; store a design profile.
- **OUTPUT** — a connected site with a machine-readable capability record that the Content module reads before choosing an output format.
- **PERMISSIONS** — Owner/Admin/Manager.
- **DEPENDENCIES** — vault, WordPress adapters, site analyzer, Playwright.
- **FAILURE CASES** — REST disabled by a security plugin; application passwords disabled; Elementor present but the licence inactive; a page builder other than Elementor; ACF fields not exposed to REST; aggressive caching hiding a publish; a staging/production mismatch. **Every one of these must degrade to a named, actionable state** — never a generic failure.
- **EXPECTED UX** — a connection test that reports, in plain language, exactly which publishing capabilities this specific site supports.

### ADM-E · Audits

- **INPUT** — URL, client, tier (free/paid), audit types (none selected = all).
- **PROCESS** — validate the target is publicly resolvable (SSRF guard); check tier and budget; enqueue; the worker invokes the external audit engine as a subprocess with its own interpreter, owns the hard timeout, parses the run identifier, and collects artefacts.
- **OUTPUT** — findings JSON, `run.json` with the composite score, `report.html`, `report.pdf`, remediation sheets — all served from server-resolved paths that are never returned to the browser.
- **PERMISSIONS** — Owner/Admin/Manager/Specialist run; all staff read; clients read own only.
- **DEPENDENCIES** — audit engine, Serper, PageSpeed/CrUX, Places, Moz (optional), Anthropic.
- **FAILURE CASES** — the engine mints its own run id and does **not** catch its own top-level exceptions and does **not** time itself out, so the caller owns failure entirely [CONFIRMED — `[CODE]`]. No PDF backend present → run still succeeds, PDF absent — the UI must not offer a download that does not exist [CONFIRMED — this is what commit `79d1036` fixed]. Partial artefacts. Engine and platform drifting apart, since they are separate products with separate dependency sets.
- **EXPECTED UX** — the type picker on start; filters that mirror the types; no "Audit Coverage" block [CONFIRMED — `[OVERHAUL]` §H]; the on-screen paginated HTML viewer and the downloadable PDF are the **same document**.

### ADM-F · Content

- **INPUT** — client, site, content type, topic or keyword set, framework (or Auto), publish target, schedule.
- **PROCESS** — the pipeline `queued → drafting → needs_review → publishing → done` (plus `failed` / `rejected`), with SERP research, drafting against the content doctrine, JSON-LD, images, a 14-dimension QA scorecard, and one human gate. The three-actor lifecycle is enforced by a database trigger rather than by the API layer. [CONFIRMED — `[CODE]`]
- **OUTPUT** — a reviewed, published, editable page plus its live URL, or a PDF/Markdown export.
- **PERMISSIONS** — Specialist creates; **only a lead approves**; the worker can never approve.
- **DEPENDENCIES** — Anthropic, Serper, image provider, WordPress adapters, Elementor/Gutenberg composers, site design profile.
- **FAILURE CASES** — the QA gate is hard but **uncalibrated** [CONFIRMED — see §28.3]; cost-gate block holds at `drafting` at honest $0 rather than crashing (good); publish succeeding at WordPress but the response being lost (needs idempotency); images generated but not hosted; raw CSS leaking into post content (a fixed defect — commit `faeec43`); em dashes surviving into output.
- **EXPECTED UX** — a real preview, an in-dashboard WYSIWYG editor, edit-then-publish, and the live URL returned immediately with a one-click "open it" [CONFIRMED — `[OVERHAUL]` §I].

### ADM-G · Citations

- **INPUT** — client, business profile, market, niche, directory selection or "recommended set".
- **PROCESS** — audit existing listings → compute the gap → prioritise generic/country/niche → create per-client accounts where needed (signup, CAPTCHA, IMAP confirmation) → submit → capture proof → track status → re-verify.
- **OUTPUT** — live listing URLs, proof screenshots, a per-unit cost ledger, and a handoff queue for gated directories.
- **PERMISSIONS** — Specialist plans; **lead submits** (submission spends money and creates a public record under the client's identity).
- **DEPENDENCIES** — Playwright + Chromium on a worker host, CAPTCHA solver, residential proxy, IMAP mailbox, Serper/Places/Foursquare for discovery, artefact storage.
- **FAILURE CASES** — form specs drift when a directory redesigns; CAPTCHA failure; email confirmation not arriving; duplicate listing already present; the directory demanding a paid claim; IP blocking; account bans. **Current known state:** the submit path has been reported as showing FAILED [CONFIRMED — `[OVERHAUL]` §K]; specs are unverified against live forms.
- **EXPECTED UX** — a guided Audit → Build → Finish → Monitor flow with an explicit, countable "ready to finish" queue.

### ADM-H · Web 2.0

- **INPUT** — client, platform selection, topic, target URL, anchor.
- **PROCESS** — plan → per-platform unique draft → lead approval → publish via API (or browser automation where no API) → verify the live URL → monitor account health.
- **OUTPUT** — live articles each carrying one editorial link, with per-platform status.
- **PERMISSIONS** — Specialist drafts; **lead approves each property**.
- **DEPENDENCIES** — per-platform credentials (house or per-client), Anthropic, publishers.
- **FAILURE CASES** — signup defended against bots on most serious platforms [CONFIRMED — `[OFFPAGE-STATUS]`]; Medium's publish API retired; token expiry; rate limits; platform policy change; **and the systemic risk — templated output across many properties triggering Site Reputation Abuse enforcement**.
- **EXPECTED UX** — a status board showing connected vs missing per platform with checkmarks, and, when something fails, an honest statement of whose fault it is — ours or the platform's [CONFIRMED — `[OVERHAUL]` §K].

### ADM-I · Integrations, credentials and API management

- **INPUT** — provider, scope (agency-wide or per-client), secret material.
- **PROCESS** — seal with AES-256-GCM under a master key; store masked; reveal only to Owner; test the connection; record health.
- **OUTPUT** — a board showing every connected API and, equally important, **every one that is missing** [CONFIRMED — `[OVERHAUL]` §O].
- **PERMISSIONS** — Owner/Admin manage; **Owner only reveals**; the "Rotate Key" control is to be removed [CONFIRMED — `[OVERHAUL]` §O].
- **FAILURE CASES** — a key present but invalid; quota exhausted; partner-gated write endpoints that accept a key but reject the operation (Foursquare, Bing Places) [CONFIRMED — `[CIT-CRED]`]; a key removed while jobs are in flight.
- **EXPECTED UX** — for every missing key, the exact consequence: *which capability is degraded and to what state.*

### ADM-J · Automations, jobs and scheduling

- **INPUT** — schedule definitions and manual triggers.
- **PROCESS** — a beat scheduler dispatching periodic work; a queue with bounded concurrency; idempotent tasks; a ledger of scheduled runs.
- **OUTPUT** — a Reports/Automations view showing which jobs exist, what each does, when it is scheduled, when it last ran and with what result [CONFIRMED — `[OVERHAUL]` §N].
- **CURRENT STATE — CRITICAL** — `beat_schedule = {}`. Nothing periodic runs. The full schedule is preserved in code as `_BEAT_SCHEDULE_DISABLED` for a one-line restore. [CONFIRMED — `[CODE]`]
- **FAILURE CASES** — the broker's visibility timeout must be ≥ the longest task time limit or a long job is redelivered and **runs twice, double-spending** [CONFIRMED — `[CODE]`]. Overlapping runs. A failed job with no dead-letter path. A silent failure with no alert.
- **EXPECTED UX** — an operator can see, in one place, everything the system will do on its own in the next 24 hours, and can pause any of it.

### ADM-K · Cost control

- **INPUT** — per-feature dial (`api` / `byhand` / `off`), per-client monthly cap, agency daily spend-stop.
- **PROCESS** — before **any** paid call: is this client's tier allowed → is the answer already cached → are we under the client cap → are we under today's limit. Only then call, then log actual cost.
- **OUTPUT** — a live cost surface with no predefined prices anywhere.
- **FAILURE CASES** — a provider path that bypasses the gate; a cost logged as an estimate rather than actual; a block that is **silent** (confirmed today for keyword research); a spend-stop that halts external calls but not internal ones — the requirement is that **every** API stops [CONFIRMED — `[OVERHAUL]` §E].
- **EXPECTED UX** — the operator can answer "what did this client cost me this month, and on what" without leaving the page.

### ADM-L · Reporting

- **INPUT** — client, period, template.
- **PROCESS** — pull real data from completed jobs, compose, human-approve, deliver to portal + Sheet + email.
- **FAILURE CASES** — reporting on stale data; sending a report when a source job failed (a report must refuse to build on incomplete data rather than quietly omit a section); Sheets quota; the write buffer losing updates.
- **EXPECTED UX** — no demo data; the report says what period it covers and how fresh each number is.

### ADM-M · Policy Radar / Command Center

- **INPUT** — a watched source list; a detected diff; an operator question.
- **PROCESS** — diff sources → fire a research job on change → summarise and categorise (severity, category, region) → version into the KB → raise a recommendation → human Acknowledge / Apply / Dismiss → an applied recommendation writes an **audit overlay only**; it never mutates the audit engine or a stored audit.
- **CURRENT STATE** — daily generation is off with the beat schedule; briefs are produced only on demand. This contradicts the stated requirement for a live daily radar [CONFIRMED — `[CODE]` commit `d57a135` vs `[OVERHAUL]` §D].
- **FAILURE CASES** — source layout change breaking the differ; false positives; an entry without a citable source (must be rejected); prompt injection from a watched page.
- **EXPECTED UX** — every entry shows what changed, why it matters, which regions, and the recommended action, with its source link.

### ADM-N · Settings, logs, health, backups, approvals

- **Settings** — agency identity, notification preferences, access and roles. Removed by instruction: Two-Factor Auth, Change Password, Security, Workspace tabs [CONFIRMED — `[OVERHAUL]` §P]. **PROPOSED — reinstate MFA for Owner and Admin before production hand-off**; removing it from the UI does not make credential theft less likely, and the vault master key is behind these accounts. This is recorded as a disagreement with the instruction, not a silent override (see §32.1).
- **Activity log** — append-only, one entry per mutation, feeding both the admin monitor and the AI context memory. [CONFIRMED]
- **System health** — liveness (touches nothing external) and readiness (bounded, concurrent dependency checks). A not-configured provider must not fail readiness. [CONFIRMED — `[CODE]`]
- **Backups** — nightly Postgres to off-site object storage, restore with confirmation. **PROPOSED — artefacts (reports, screenshots, images) must be backed up too**; they are currently on a VPS volume and are the client-visible evidence trail.
- **Approval queues** — one unified queue across content, Web 2.0, citations, GBP, reports and policy recommendations, so a lead has exactly one place to look. [CONFIRMED as a UI element; **PROPOSED** to unify it across every gated resource type.]

---
## 11. TEAM PORTAL

### 11.1 Purpose

The team portal is where the agency's own staff execute delivery. Its design test: **a specialist should be able to work a full day inside it without asking the owner a question.**

### 11.2 Capabilities

| ID | Capability | Detail | Class |
|---|---|---|---|
| TEAM-A | **My queue** | Audits, content jobs, citation campaigns, Web 2.0 properties, tasks assigned to me, sorted by deadline and blocker | CONFIRMED |
| TEAM-B | **Task board** | `todo → in_progress → review → done`; lifecycle enforced by a database trigger, not the API; `started_at` stamped once on the true work-start transition | CONFIRMED — `[CODE]` |
| TEAM-C | **Assignment** | Leads assign; specialists claim | CONFIRMED — **currently defective**, members do not appear correctly [`[OVERHAUL]` §M] |
| TEAM-D | **Run + deliver** | Start audits and content jobs, push deliverables | CONFIRMED |
| TEAM-E | **Review checkpoint** | Approve / request edit / reject — the human gate before anything reaches a client | CONFIRMED |
| TEAM-F | **Tools workspace** | Read-only adapters backing all 17 tool slugs | CONFIRMED — `[CODE]` |
| TEAM-G | **Deadline requests** | Request an extension; lead approves | CONFIRMED — `[CODE]` migration `0074` |
| TEAM-H | **Performance metrics** | Live, updating immediately on member changes | CONFIRMED — **currently defective** [`[OVERHAUL]` §M] |
| TEAM-I | **Notifications** | Assignment, review requested, job failed, deadline near | CONFIRMED |
| TEAM-J | **Activity history** | Every action I took, and by whom on my work | CONFIRMED |
| TEAM-K | **Collaboration** | Messages/DMs merged into one structure | CONFIRMED — `[WA-TEAM]` 28/07 task list |
| TEAM-L | **Client book** *(Manager)* | Status across an assigned set of clients | CONFIRMED — `[ARCH]` §5 |
| TEAM-M | **Time-on-task** | A task timer | CONFIRMED — `[CODE]` commit `62ae44b` |

### 11.3 Workflows the team portal must support end to end

**Audit workflow.** Receive assignment → confirm the client's site and tier → select audit types → run → wait with visible progress → read findings → triage into tasks → prepare the client narrative → submit for lead review → deliver. *Failure to specify today:* what a specialist does when an audit returns partial artefacts. **PROPOSED:** a partial run must produce a triage state with a named reason, not a silent success.

**Content workflow.** Brief or research → generate → read the QA scorecard **and understand it** → edit in the dashboard → submit for review → lead approves → publish → verify the live URL renders and is editable in the builder → submit for indexing → record in the report. *Gap:* the QA scorecard is currently advisory in some paths and a hard gate in others [CONFIRMED — `[RESEARCH-AUG]` says "now advisory, not a blocker"; `[CODE]` says hard gate]. **This inconsistency must be resolved** — §30.9.

**Citation workflow.** Run the citation audit → review the recommended directory set → remove anything inappropriate → request submission → monitor → work the "ready to finish" queue → record proof → schedule re-verification.

**Web 2.0 workflow.** Plan the platform mix for this client → generate genuinely distinct drafts → self-check for templating → submit for approval → publish on a human-paced schedule → verify links → monitor account health.

**Reporting workflow.** Confirm data freshness → generate → review AI narrative against the actual numbers → correct → submit for approval → send.

### 11.4 The team portal's hardest requirement

**Every job must be legible in failure.** A specialist looking at a red job must be able to answer, without escalating: *what failed, whose fault it was, whether it cost money, whether it is safe to retry, and what the client can see right now.* [PROPOSED — this is the single highest-leverage UX requirement in the team portal, and nothing in the current evidence shows it exists.]

---

## 12. CLIENT PORTAL

### 12.1 What clients can see

| ID | Capability | Detail | Class |
|---|---|---|---|
| CLIENT-A | Dashboard | Their site snapshot and latest audit score | CONFIRMED |
| CLIENT-B | Reports | Every audit as a web page and a downloadable PDF | CONFIRMED |
| CLIENT-C | Milestones | Delivery progress, auto-advanced by the system | CONFIRMED |
| CLIENT-D | Run an audit | Free or paid per the tier the agency allows | CONFIRMED |
| CLIENT-E | Upsells | Cards linking to **Danyal's real Fiverr gigs** | CONFIRMED — but see §30.6 |
| CLIENT-F | Requests / tickets | Raise a request, see its status | CONFIRMED — `[CODE]` |
| CLIENT-G | Deliverables | Documents the agency has granted them | CONFIRMED — `[CODE]` migration `0032` |
| CLIENT-H | Rank / traffic view | Basic in Free, full read-only above | CONFIRMED — `[PACK-JUL]` |

### 12.2 What clients can edit

Very little, by design: their own contact details, notification preferences, and requests. **They may not edit their canonical NAP directly** — a NAP change is a delivery event that must propagate to citations, schema, GBP and content, so it is a *request*, not a field edit. [PROPOSED, strongly recommended — an unmediated NAP edit would silently invalidate every existing citation.]

### 12.3 What clients can approve

| Item | Approve? | Class |
|---|---|---|
| Audit reports | View only | CONFIRMED |
| Content drafts | **UNKNOWN** — the agency's lead approves; whether the *client* also approves is unspecified | UNKNOWN — Q-11 |
| Publishing to their own site | **UNKNOWN** — publishing to a client's live site without their sign-off is a commercial risk | UNKNOWN — Q-12 |
| Citation submissions under their identity | **PROPOSED** — should require a one-time standing authorisation | PROPOSED |
| Milestones | Never — system-advanced | CONFIRMED |

### 12.4 What must remain private from clients

Absolutely, without exception: other clients' existence and data; internal cost and MRR; API keys and any credential; artefact filesystem paths; internal error text and stack traces; team member performance data; the agency's own margin; Policy Radar internals; the activity log; which providers are used and what they cost; other clients' presence in shared house accounts on Web 2.0 platforms. [CONFIRMED for the first six — `[CODE]` proves `mrr`, `cost`, `error`, `*_path` are unreachable; the rest **PROPOSED**.]

### 12.5 Client portal failure modes to design against

- A client running audits repeatedly and burning agency budget → **PROPOSED:** per-client rate limit and a monthly free-run allowance.
- A client seeing a job stuck in "running" for hours with no explanation → **PROPOSED:** client-safe status vocabulary with expected durations.
- A client downloading a report that is empty or fails to load — a real, previously observed failure [CONFIRMED — `[CODE]` notes `report-consolidated.pdf` collapsing to a near-empty page]. **The portal must never offer an artefact it has not verified exists and is non-trivial.**
- A client at a Free tier seeing paid features advertised and being unable to use them → tier-appropriate presentation.

---

## 13. AUDIT SYSTEM

### 13.1 Architecture as built

The audit is a **separate product** (`danyals-audit-system`), invoked by the platform as an external subprocess using its own Python interpreter and its own repository as the working directory. The platform never imports it. [CONFIRMED — `[CODE]` `backend/integrations/audit_engine.py`]

Contract facts, source-verified, that shape every requirement below:

- The engine **mints its own run identifier**; the platform cannot supply one. It prints it to stdout and the adapter parses it.
- The engine **does not catch its own top-level exceptions** and **never times itself out**. The caller owns the hard timeout and must treat a non-zero exit, a timeout, or a missing `run.json` as failure.
- `--mode free` forces every paid provider off (zero spend). `--mode paid` uses **the engine's own keys from its own `.env`** — not the platform vault.
- Artefacts land under `<engine_dir>/data/audits/<domain-slug>/<run_uuid>/`.
- PDFs are best-effort; a run can succeed with no PDF.

[All CONFIRMED — `[CODE]`]

**This is the deepest architectural issue in the audit module.** The engine is a Claude-Code-oriented CLI product with its own key store, its own run identity and no failure contract, wrapped by a platform that needs vault-managed keys, correlated job identity, hard timeouts and structured failure. The adapter compensates competently, but the seam is fragile: two dependency sets, two key stores, two release cycles, and a stdout-parsed contract. See §32.2 for the recommended options.

### 13.2 Free audit — requirements

| ID | Requirement | Class |
|---|---|---|
| AUD-F1 | One complete condensed report, ~10–15 pages. **No** Technical/On-Page/Off-Page/Actionable split | CONFIRMED — `[OVERHAUL]` §G |
| AUD-F2 | No "Focus Areas" input — always audit everything | CONFIRMED — `[OVERHAUL]` §G |
| AUD-F3 | Zero paid-provider spend | CONFIRMED |
| AUD-F4 | Download after completion | CONFIRMED |
| AUD-F5 | In-dashboard HTML preview: paginated, PDF-viewer-like, next/prev, **same content as the PDF** | CONFIRMED |
| AUD-F6 | Danyal's real Fiverr gigs as the upsell, not demo gigs | CONFIRMED |
| AUD-F7 | Usable as a public lead magnet with follow-up email sequencing | CONFIRMED — `[WA-ADAN]` 05/08 |
| AUD-F8 | **PROPOSED** — abuse controls: per-domain and per-IP rate limits, a queue cap, and domain validation, since this endpoint is public and spends compute | PROPOSED |
| AUD-F9 | **PROPOSED** — the free report must be genuinely useful, not deliberately crippled; the conversion mechanism is credibility | PROPOSED |

### 13.3 Paid audit — requirements

| ID | Requirement | Class |
|---|---|---|
| AUD-P1 | Type-selectable: on-page, technical, off-page, local, GEO, strategy. None selected = run all | CONFIRMED |
| AUD-P2 | Filters mirror the audit types | CONFIRMED |
| AUD-P3 | No "Audit Coverage" section | CONFIRMED |
| AUD-P4 | PDF and dashboard HTML are the same document — same UI, structure, layout, writing style | CONFIRMED |
| AUD-P5 | Same layout for free and paid | CONFIRMED |
| AUD-P6 | Writing style: direct about the issues, client-friendly | CONFIRMED |
| AUD-P7 | Full multi-agent evaluation and AI narrative on the full path | CONFIRMED — `[CODE]` passes `--agents on --ai-narrative on` for a full run |
| AUD-P8 | Role-based remediation sheets (XLSX + CSV) | CONFIRMED — `[CODE]` |
| AUD-P9 | Findings JSON available to staff | CONFIRMED |
| AUD-P10 | Every finding carries evidence; no invented metrics | CONFIRMED |

### 13.4 What a professional-grade local-SEO audit must contain

Assembled from the engine's own checklists (`on-page`, `technical`, `local`, `off-page`), the knowledge base (`core-web-vitals`, `eeat`, `geo-ai-search`, `google`, `local-seo`, `schema-org`, `2026-updates`), the AgencyBook research corpus, and standard practice. Marked **CR** = current requirement, **RE** = recommended enhancement.

**Crawl and inventory (CR)** — sitemap and robots parsing, page inventory, render diff (raw vs rendered DOM), status-code map, canonical map, orphan detection, crawl-depth distribution, parameter handling, pagination.

**Technical (CR)** — indexability and `noindex` audit, canonical correctness, redirect chains and loops, 404 and soft-404 inventory, HTTPS and mixed content, security headers, hreflang, structured-data validity, sitemap freshness and coverage, robots directives, server response times, JS-rendering dependency, DOM size and node counts, page weight, render-blocking resources.

**Core Web Vitals (CR)** — LCP, CLS, INP from PageSpeed Insights plus **field data from CrUX where available**; lab-vs-field divergence explicitly called out. **RE:** per-template rather than per-page-only, because fixing a template fixes many pages.

**On-page (CR)** — title and meta description quality and uniqueness, heading hierarchy, keyword-to-page mapping, cannibalisation, thin and duplicate content, internal linking structure and anchor distribution, image alt **and title** attributes, content depth against SERP competitors, schema per page type.

**Local (CR)** — Google Business Profile completeness, categories (primary and secondary), description, hours including special hours, attributes, services, products, photos and cadence, posts and cadence, Q&A, review count/velocity/rating/response rate, NAP consistency across citations, citation count and gap analysis, local-pack and map-pack position, geo-grid ranking across a city grid, service-area configuration, location-page quality for multi-location businesses, local schema (`LocalBusiness` and subtype).

**Off-page (CR)** — referring domains, backlink profile, anchor distribution, toxic-link screen, new and lost links, citation authority and consistency. **RE:** a competitor link gap — currently **returns an empty set by design** and is an open decision [CONFIRMED — `[CODE]`].

**GEO / AI search (CR)** — this is a genuine differentiator and is already built: AI Overview presence and citation tracking, passage citability, LLM-readable semantic HTML, AI-crawler access, `llms.txt`, AI-search authority. [CONFIRMED — `[CODE]` skills `aios-geo-audit`, engine `analyzers/geo_ai.py`, `ai_search.py`; `[WA-ADAN]` 10/07 llms.txt request]

**Competitors and keywords (CR)** — SERP competitor set, share of voice, content gaps, keyword research with intent classification and clustering, difficulty. **Known defect:** difficulty is a neutral screen, not authority-adjusted [CONFIRMED].

**Scoring and prioritisation (CR)** — a 0–100 composite. **RE, important:** the audit must prioritise by **estimated impact × effort**, not by severity alone. A 300-check audit that returns a flat severity-sorted list transfers the prioritisation problem to the client — which is precisely the work an agency is paid to do.

**AI interpretation (CR)** — narrative and strategy prose on the full path. **RE:** the AI must be constrained to interpret computed numbers, never to produce them. The governing principle already stated in the project's own analysis is *"Python computes the numbers, AI writes the narrative"* [CONFIRMED — `[WA-TEAM]` 04/07]. Any number appearing in narrative prose must be traceable to a finding.

**Human review (CR)** — before client delivery.

**Export and presentation (CR)** — HTML, PDF, findings JSON, remediation XLSX/CSV, and a Google Sheet.

### 13.5 Recommended audit enhancements

| ID | Enhancement | Rationale | Class |
|---|---|---|---|
| AUD-R1 | Delta audits — what changed since last run, what we fixed, what regressed | Turns a one-off deliverable into a retainer narrative; `/audit-track` already exists in the engine | PROPOSED |
| AUD-R2 | Impact×effort prioritisation with an explicit "do these five things first" | See above | PROPOSED |
| AUD-R3 | Fix verification — re-check a finding after remediation and mark it closed with evidence | Proves the agency's work | PROPOSED |
| AUD-R4 | Per-template grouping of on-page and CWV findings | One fix, many pages | PROPOSED |
| AUD-R5 | Confidence labelling on every finding (measured / inferred / sampled) | Protects credibility when a data source is degraded | PROPOSED |
| AUD-R6 | Competitor-relative scoring, not absolute | "You score 62" is meaningless; "you score 62, the pack leader scores 81" is actionable | PROPOSED |
| AUD-R7 | An explicit "what we could not check and why" section | Turns missing keys and blocked crawls into honesty rather than silent gaps | PROPOSED |
| AUD-R8 | Audit-to-task conversion with one click per finding | Closes the loop into the team portal | PROPOSED |
| AUD-R9 | Deterministic scoring — same input, same score | Two audits of an unchanged site must not disagree; required before delta audits mean anything | PROPOSED |

---

## 14. CONTENT SYSTEM

The operator's assessment: the current content module is *"very poor"*, *"not engineered properly"*, with roughly **90% of the work remaining**. This section specifies what it should be. [Operator statement, 2026-08-23 — CONFIRMED]

### 14.1 The core reframe

**Content is not an AI article generator. It is a page-production line whose output must rank, convert and be maintainable by the client afterwards.** Three properties follow, and the current system satisfies none of them fully:

1. **Research decides what to write** — before drafting, not after.
2. **The output is a real page in the client's real design**, editable in their real page builder — not text pasted into a box.
3. **Volume is a first-class mode** — one page, a category of pages, or an entire site.

### 14.2 Content planning and research

| ID | Requirement | Class |
|---|---|---|
| CONT-1 | A dedicated **Research module** runs before writing: study the site, study competitors, propose the page set | CONFIRMED — `[RESEARCH-AUG]` |
| CONT-2 | Operator picks a content type: service, location, service×location, service-area, GSC-opportunity, blog, FAQ, and more | CONFIRMED |
| CONT-3 | Competitor teardown: scan rival sites, enumerate their service and location pages | CONFIRMED |
| CONT-4 | Recommend the full page set with volume and difficulty per page, as checkboxes | CONFIRMED |
| CONT-5 | Keyword research per page, clustered into page topics | CONFIRMED |
| CONT-6 | Search-intent classification per cluster, and the page type must follow the intent | STRONG INFERENCE |
| CONT-7 | Service×location combinatorics: recommend the **winners**, not the full cross-product | CONFIRMED |
| CONT-8 | Location and service-area mapping to the towns and suburbs actually served | CONFIRMED |
| CONT-9 | Blog and FAQ topics mined from real questions and competitor gaps | CONFIRMED |
| CONT-10 | Cannibalisation check against the site's **existing** pages before proposing a new one | PROPOSED — high value; prevents the system competing with its own client |
| CONT-11 | A topical map / content cluster model with pillar-and-spoke structure | PROPOSED — the sibling project has this; it is standard practice and directly serves topical authority |
| CONT-12 | A content calendar with scheduling | CONFIRMED — `[CODE]` migration `0072` |
| CONT-13 | Location selection must weigh **buyer quality**, not population alone | CONFIRMED — `[WA-TEAM]` 05/07, an explicit practitioner point |

### 14.3 Content briefs and context

| ID | Requirement | Class |
|---|---|---|
| CONT-14 | A structured brief per page: target keyword set, intent, audience, required entities, competitor angle, internal-link targets, schema type, word-count band, CTA | STRONG INFERENCE |
| CONT-15 | **Brand voice** captured per client and enforced | CONFIRMED — `[PACK-JUL]` implies; sibling audit names its absence as a gap |
| CONT-16 | **Client context pack** — business facts, services, differentiators, service area, credentials — snapshotted into the job so drafts cite real facts | CONFIRMED — `[CODE]` `source_pack` |
| CONT-17 | Location context — real local references, not generic filler | STRONG INFERENCE |
| CONT-18 | Entity context — the business, its services, its locations as named entities for schema and topical coherence | PROPOSED |
| CONT-19 | **Proof / first-hand detail required before generation** | CONFIRMED — `[CODE]` commit `8835cb7` |

### 14.4 Generation quality

| ID | Requirement | Class |
|---|---|---|
| CONT-20 | Draft against local-SEO copy frameworks — AIDA, PAS, BAB — selected per page type, auto-resolvable | CONFIRMED |
| CONT-21 | **Zero em dashes** anywhere in output, site, emails or AI responses | CONFIRMED — stated twice, in `[OVERHAUL]` §I and `[WA-ADAN]` 01/08 |
| CONT-22 | AI-sounding detection; on failure, **rewrite section by section** using copywriting frameworks | CONFIRMED |
| CONT-23 | Heading hierarchy correct and semantic | CONFIRMED |
| CONT-24 | JSON-LD schema generated per page type and validated | CONFIRMED |
| CONT-25 | Meta title and description generated, length-checked, unique | CONFIRMED |
| CONT-26 | Internal links to relevant existing pages, with sensible anchors | CONFIRMED |
| CONT-27 | External references where they add credibility | STRONG INFERENCE |
| CONT-28 | Images generated — real photographic style, not infographics; landscape where appropriate; branded SVG icons rather than emoji | CONFIRMED — `[CODE]` commits `4a700f4`, `13fae71`, `faeec43` |
| CONT-29 | Image **alt text and title attributes** | CONFIRMED — `[WA-ADAN]` 21/08, `[CODE]` commit `79d1036` |
| CONT-30 | Responsive breakpoints in generated markup | CONFIRMED — `[CODE]` commit `79d1036` |
| CONT-31 | No raw CSS dumped into post content | CONFIRMED — `[CODE]` commit `faeec43` |
| CONT-32 | Multiple layout candidates generated, the better one chosen | CONFIRMED — `[OVERHAUL]` §I |
| CONT-33 | **PROPOSED** — plagiarism / duplicate-content check against the live web and against the client's own site | PROPOSED |
| CONT-34 | **PROPOSED** — factual-claim guard: any statistic, price, certification or guarantee must come from the client context pack or be omitted | PROPOSED — this is a legal exposure, not a quality nicety |
| CONT-35 | **PROPOSED** — reading-level and sentence-variance targets, since uniform sentence length is the strongest AI-text tell after em dashes | PROPOSED |

### 14.5 Quality control and approval

| ID | Requirement | Class |
|---|---|---|
| CONT-36 | A multi-dimension QA scorecard (14 dimensions today) | CONFIRMED |
| CONT-37 | The gate's status must be **unambiguous** — hard gate or advisory, one answer, everywhere | **CONFLICTING** — §30.9 |
| CONT-38 | The threshold and weight vector must be **calibrated against human SEO grading** before being enforced | CONFIRMED as outstanding — `[CODE]` marks them PROVISIONAL |
| CONT-39 | The gate is re-checked at publish, not only at draft | CONFIRMED |
| CONT-40 | Exactly one mandatory human review gate | CONFIRMED |
| CONT-41 | Review offers a true preview — embedded HTML in the dashboard preferred, PDF acceptable | CONFIRMED |
| CONT-42 | In-dashboard WYSIWYG editing, then publish | CONFIRMED — `[CODE]` commit `573ddf6` |
| CONT-43 | The three-actor lifecycle is enforced at the database, not in the API | CONFIRMED |
| CONT-44 | **PROPOSED** — the QA scorecard must be **explained** to the reviewer: which dimension failed, on what evidence, and what would fix it. A number without a reason cannot be acted on. | PROPOSED |
| CONT-45 | **PROPOSED** — an approver may not approve their own draft | PROPOSED |

### 14.6 Publishing, updating, versioning

| ID | Requirement | Class |
|---|---|---|
| CONT-46 | On approval, with WordPress connected, auto-publish and return the live URL for immediate testing | CONFIRMED |
| CONT-47 | Manual PDF/Markdown export path retained | CONFIRMED |
| CONT-48 | Scheduled publishing and republish | CONFIRMED — `[CODE]` |
| CONT-49 | Versioning: every draft and every published revision retained and diffable | STRONG INFERENCE |
| CONT-50 | **PROPOSED** — rollback: revert a published page to its previous state from the dashboard | PROPOSED |
| CONT-51 | **PROPOSED** — idempotent publish keyed on job id, so a lost response never creates a duplicate page | PROPOSED — this is a real, likely, client-visible failure |
| CONT-52 | Automatic indexing submission on publish | CONFIRMED |
| CONT-53 | **PROPOSED** — post-publish verification: fetch the live URL, confirm the page renders, the schema validates, the images load, and the page opens editable in the builder | PROPOSED — without this, "published" is an unverified claim |

### 14.7 Bulk generation — the volume mode

| ID | Requirement | Class |
|---|---|---|
| CONT-54 | Generate one selected page, several, or **all** recommended pages in one action | CONFIRMED |
| CONT-55 | Return a manifest of all live URLs | CONFIRMED |
| CONT-56 | Build a whole website, a category of pages, or a single page — operator's choice | CONFIRMED — operator, 2026-08-23 |
| CONT-57 | **PROPOSED** — bulk runs must be resumable, partially completable, and cost-estimated **before** starting, with an explicit operator confirmation of the estimate | PROPOSED — a 20-page fan-out at $10–50/page is a $200–1,000 decision |
| CONT-58 | **PROPOSED** — bulk output must be checked for **internal near-duplication**; 15 service pages written from one template is exactly the doorway-page pattern Google penalises | PROPOSED — this is the largest SEO risk in the whole content module |
| CONT-59 | **PROPOSED** — bulk publishing must be rate-paced, not a same-minute burst of 20 new pages | PROPOSED |

### 14.8 Weaknesses in the current conceptual approach

1. **Generation-first, not research-first.** Pages were produced before deciding which pages should exist. `[RESEARCH-AUG]` names this as the gap; the Research module is unbuilt.
2. **Output shape wrong.** Flat HTML rather than builder-native blocks — the client cannot maintain what they were sold. Named as *"today's biggest gap"* [CONFIRMED].
3. **Design ignorance.** Pages that do not inherit the site's style read as bolted-on, which is both a brand and a conversion problem.
4. **Volume was an afterthought.** The unit of work was one page; the business need is a page set.
5. **QA is a number without a meaning.** An uncalibrated hard gate.
6. **No post-publish truth.** Nothing verifies that what was published is what renders.
7. **No duplication defence.** Neither against the web, nor the client's own site, nor within a bulk run.
8. **No content maintenance model.** Content decays; NAP changes; hours change; schema goes stale. The sibling analysis makes this point explicitly and Danyal's system has no answer to it. [CONFIRMED — `[WA-TEAM]` 05/07: *"Updating schema also requires when NAP details changed but we mostly forget about"*]

---
## 15. WORDPRESS SYSTEM

WordPress is treated here as a major engineering problem, because it is the seam where the platform's output meets a live asset the agency does not control and cannot afford to break.

### 15.1 The requirement in one sentence

**Generate and manage high-quality pages on a client's existing WordPress site without destroying its design, SEO, performance or editability — and leave the client able to maintain those pages themselves.** [CONFIRMED — operator, 2026-08-23; `[RESEARCH-AUG]`]

### 15.2 Connection and authentication

| ID | Requirement | Class |
|---|---|---|
| WP-1 | One-time per-site connection; credentials sealed in the vault, never in logs, decrypted only at point of use | CONFIRMED |
| WP-2 | Primary auth: **WordPress Application Passwords** over REST | CONFIRMED — `[ARCH]` |
| WP-3 | Fallback: XML-RPC with a login password | CONFIRMED — `[RESEARCH-AUG]` |
| WP-4 | Third route: a companion plugin with its own token | CONFIRMED — `[CODE]` |
| WP-5 | **PROPOSED** — a connection health check that runs before every publish, not only at setup | PROPOSED |
| WP-6 | **PROPOSED** — least-privilege: an `aios_publisher` role with exactly the capabilities needed, rather than an administrator account | PROPOSED — a stolen admin application password is a full site compromise across every client |
| WP-7 | **PROPOSED** — per-site credential rotation with a documented procedure | PROPOSED |
| WP-8 | **PROPOSED** — outbound requests to client sites must pass the SSRF guard already present for audit targets | PROPOSED |

### 15.3 Capability discovery — the step that makes everything else safe

Before the system publishes anything it must know what this specific site is. [PROPOSED as a formal requirement; partially implemented as `site_analyzer` + design profile]

Discover and record: WordPress and PHP version; REST reachability and any security plugin blocking it; whether Application Passwords are enabled; Elementor presence, version, and whether the licence is active; Gutenberg availability; the active theme and whether it is a block theme; **ACF presence and whether field groups expose `show_in_rest`** [CONFIRMED — `[WA-ADAN]` 08/07, a direct client question with a prepared answer]; the active SEO plugin (Yoast / RankMath / SEOPress / AIOSEO) and therefore where canonical, meta and robots directives must be written; caching and CDN layers; existing page and post inventory; sitemap URL; robots.txt; media library constraints; upload size limits; any page-builder other than Elementor.

**Failure to discover must degrade to a named state.** "This site has Elementor 3.x, an active licence, Yoast, and WP Rocket — we will publish Elementor sections and write Yoast meta fields, and we will purge the cache after publish" is the standard. A generic "connected ✓" is not.

### 15.4 The architecture question — REST vs plugin vs Gutenberg vs Elementor

This is the decision the module hinges on. The trade-offs, stated honestly:

**Option A — WordPress REST API only**
*For:* no client-side install; officially supported; version-stable; works on managed hosts; simplest security surface.
*Against:* cannot write Elementor's `_elementor_data` reliably without also setting `_elementor_edit_mode` post-meta, and REST meta writes require the meta key to be registered — which usually needs a plugin anyway; cannot flush Elementor's CSS cache; cannot purge host caches; SEO-plugin meta fields often require plugin-specific REST support; media handling is workable but clumsy for many images.
*Verdict:* necessary, insufficient alone for the editable-page requirement.

**Option B — Custom companion plugin**
*For:* can register meta, write builder data correctly, regenerate Elementor CSS, purge caches, expose a capability-discovery endpoint, enforce a least-privilege role, and give a single stable contract regardless of theme and SEO plugin. A plugin already exists (`aios-publisher`, at version 1.7.0 by commit history) with a theme adapter, core connector, auto-publisher and a design-reconstruction module.
*Against:* the client must install and update it; a plugin conflict becomes the agency's problem; it is code running on someone else's production site — every bug is a client incident; it must be maintained across WordPress and Elementor versions.
*Verdict:* **required**, and already the de facto direction.

**Option C — Gutenberg blocks as the output format**
*For:* native, no dependency on a paid builder, forward-compatible with block themes, serialisable as post content without post-meta gymnastics, and genuinely editable.
*Against:* on a site whose entire design lives in Elementor, a Gutenberg page will not inherit that design and will look foreign — the exact failure the requirement exists to prevent.
*Verdict:* the right default for sites **without** Elementor; wrong for sites with it.

**Option D — Elementor widget tree**
*For:* on an Elementor site it is the only format that is truly editable in the way the client expects and that can inherit the site's style kit.
*Against:* `_elementor_data` is an undocumented internal JSON contract that Elementor may change; it requires post-meta writes; it requires CSS regeneration; and it couples the agency's output to a third-party plugin's internals.
*Verdict:* necessary for Elementor sites, and must be **version-pinned and regression-tested**.

**Recommended architecture — hybrid, capability-driven** [PROPOSED]

> Produce one **canonical, builder-agnostic page model** (a structured document of sections, headings, text, images, buttons, schema and metadata). Render that model into whichever target the discovered site supports: Elementor widget tree, native Gutenberg blocks, or — only as a last resort, and labelled as degraded — flat HTML. Deliver it through the companion plugin where installed, falling back to REST where it is not.

This is, notably, **the direction the codebase has already taken**: there is a `page_model.py` (742 lines), an `elementor.py` composer (1,255 lines, documented as a pure, deterministic, byte-reproducible builder), a `gutenberg.py` (316 lines), an `editor_mode.py` selector, `page_blueprints.py`, and `site_design.py` (680 lines) doing Playwright-based design analysis. [CONFIRMED — `[CODE]`]

The recommendation is therefore **not to rebuild this, but to finish and verify it**: the composers exist; what is missing is proof that the output opens editable, inherits the design, validates, performs, and survives an Elementor upgrade.

### 15.5 Design preservation and cloning

| ID | Requirement | Class |
|---|---|---|
| WP-9 | Read the site's existing style kit — fonts, colours, button styles, spacing — and apply it to generated pages | CONFIRMED |
| WP-10 | Where no usable design exists, generate a clean niche-appropriate layout | CONFIRMED |
| WP-11 | Page cloning: take an existing page as a structural template for new ones | CONFIRMED — operator, 2026-08-23 ("design properly documented, copied") |
| WP-12 | A stored, inspectable **design profile** per site | CONFIRMED — `[CODE]` `site_design.py`, `xegents-design-profile.json` artefact |
| WP-13 | **PROPOSED** — a visual regression check: screenshot the generated page and the reference page and flag material divergence | PROPOSED; `visual_validations` table exists (`0071`), so the foundation is present |
| WP-14 | **PROPOSED** — never write to global site styles, theme files, or existing pages. Generated pages must be additive only. | PROPOSED — this is the primary "don't destroy the site" guarantee |

### 15.6 SEO surface

| ID | Requirement | Class |
|---|---|---|
| WP-15 | Slug control, with collision handling | CONFIRMED |
| WP-16 | Meta title and description written to the **active SEO plugin's** fields, not just to WordPress core | STRONG INFERENCE — critical, since writing core fields on a Yoast site silently does nothing |
| WP-17 | Canonical URL control | CONFIRMED |
| WP-18 | Robots directives (`index`/`noindex`, `follow`/`nofollow`) | CONFIRMED |
| WP-19 | JSON-LD schema injected and validated | CONFIRMED |
| WP-20 | Internal links to existing pages | CONFIRMED |
| WP-21 | Images uploaded to the media library with alt and title | CONFIRMED |
| WP-22 | Featured image set | CONFIRMED |
| WP-23 | Tags and categories assigned from keyword research | CONFIRMED — `[CODE]` commit `db4ae1f` |
| WP-24 | Sitemap updated / regenerated after publish | CONFIRMED |
| WP-25 | Indexing submitted after publish | CONFIRMED |
| WP-26 | **PROPOSED** — a pre-publish SEO validation that blocks on: missing title, missing description, duplicate slug, invalid schema, missing alt text, or a canonical pointing off-site | PROPOSED |

### 15.7 Performance discipline

The client asked about this directly and specifically. [CONFIRMED — `[WA-TEAM]` 07/07: *"Speed optimization — what is considered to resolve? jQuery on e-commerce. Ajax jQuery — compress could break functions for gateway if file is compressed. Ensure functionality isn't lost with optimizing. DOM size. If optimization breaks functionality — is there a revert option?"*]

| ID | Requirement | Class |
|---|---|---|
| WP-27 | Bounded **DOM size** on generated pages, measured and asserted | CONFIRMED |
| WP-28 | Bounded page weight; images compressed and correctly sized; modern formats | STRONG INFERENCE |
| WP-29 | Core Web Vitals measured on the published page, not only estimated | PROPOSED |
| WP-30 | No render-blocking additions; no inline CSS dumps | CONFIRMED |
| WP-31 | Responsive at defined breakpoints | CONFIRMED |
| WP-32 | Lazy-loaded below-fold images | PROPOSED |
| WP-33 | Cache purge after publish where a caching layer is detected | PROPOSED |
| WP-34 | **A revert option for anything the system changes** — the client explicitly asked | CONFIRMED as a client question; **PROPOSED** as a requirement, since no evidence shows it was answered with a built capability |
| WP-35 | **PROPOSED** — a performance budget per page type, enforced as a publish gate | PROPOSED |

### 15.8 Publishing lifecycle

Draft → in-dashboard preview → WordPress draft → WordPress preview link → publish → post-publish verification → revision history → revert. [CONFIRMED for draft/preview/publish; **PROPOSED** for verification and revert.]

**Idempotency requirement (PROPOSED, high priority):** each publish carries the content job's identifier. Before creating a post, the system checks whether that identifier already produced one. A retried or redelivered job updates rather than duplicates. Without this, the documented broker redelivery risk (visibility timeout shorter than task time limit) produces **duplicate live pages on a client's site** — a visible, embarrassing, SEO-damaging failure.

### 15.9 Failure cases the module must name

REST blocked by security plugin · Application Passwords disabled · Elementor absent, or present with an inactive licence · a non-Elementor page builder · ACF fields not REST-exposed · SEO plugin meta not writable · upload size exceeded · media library rejecting a format · a caching layer serving a stale page after publish · a staging URL mistaken for production · a slug collision · a plugin version mismatch · a WordPress core upgrade changing REST behaviour · the client editing a generated page and the system later overwriting their edit.

That last one deserves emphasis. **PROPOSED:** once a human has edited a generated page in WordPress, the system must detect that and refuse to overwrite without explicit confirmation. The existing on-page drift guard is *"a plain string compare, not a hash/etag"* [CONFIRMED — `[CODE]`], which is not sufficient for this.

---

## 16. CITATION SYSTEM

### 16.1 The intended workflow

Business selection → client selection → canonical NAP and business profile → market and niche determination → citation audit (what exists, where, what is inconsistent) → gap computation → prioritised platform selection → account creation where required → submission → verification → status tracking → proof capture → error handling → re-verification → reporting. [CONFIRMED — composite of `[OVERHAUL]` §K, `[RESEARCH-AUG]`, `[OFFPAGE-STATUS]`]

### 16.2 Current state, verified

| Fact | Evidence |
|---|---|
| 155-directory catalogue seeded in the database | `[CODE]` — 155 rows across migrations `0046`, `0048`, `0065`, `0067` |
| Catalogue segmentation: 95 bot-fillable · 33 CAPTCHA-assisted · 17 manual-only · 8 aggregator · 8 API | `[RESEARCH-AUG]` |
| Country split: US 66 · CA 26 · UK 25 · AU 23 · Global 15 | `[RESEARCH-AUG]` |
| Playwright bot exists — real browser, data-driven form specs, CAPTCHA solving, screenshot proof, stealth fingerprinting | `[CODE]` `citation_bot.py` (1,083 lines), commit `20976e3` |
| Form specs: **~50** written (up from 12 in August) | `[CODE]` — 53 keys in `FORM_SPECS` |
| Form specs are **best-effort, not hand-verified against live forms** | `[CIT-CRED]` §5 — explicit |
| Account creation + IMAP email confirmation built | `[CODE]` commits `2833673`, `8c063b8`; `citation_signup.py`, `imap_mailbox.py` |
| Real audit discovery via Serper + Places + Foursquare + Claude (replacing BrightLocal) | `[CODE]` commit `c877665` |
| Handoff "ready to finish" queue + local headed-browser finisher | `[CODE]` commits `e9c28c9`, `0ac6f6f`; `tools/finish_citation.py` |
| Reported production run: **84 directories wired, 26 accounts created, 15 CAPTCHAs auto-solved** | `[OFFPAGE-STATUS]` |
| Citation submit reported as showing FAILED | `[OVERHAUL]` §K |
| Foursquare write endpoint `POST /v3/places` returns 404; Bing Places write is partner-gated | `[CIT-CRED]` §4 |
| Data Axle, Neustar/Localeze, OpenStreetMap have no automatable write path | `[CIT-CRED]` §4 |

**Honest read:** the machinery is genuinely built and is further along than the August plan. What is missing is **verified coverage at volume** — the difference between "the bot can submit" and "we submitted 50 citations for 10 businesses and here are 500 proof URLs."

### 16.3 Platform classification

The task brief asks for six classes. Applying them to the evidenced catalogue:

**A — Reliable API automation.** Bing Places, Foursquare (both **partner-gated and currently unverified** — treat as aspirational until a write succeeds in production). Push-once aggregators — Data Axle, Neustar/Localeze — which seed hundreds of downstream directories but are **portal-only, so effectively class D**. *Realistic count in class A today: 0–2.* [CONFIRMED — `[CIT-CRED]`]

**B — Reliable browser automation.** The bot-fillable long tail: Hotfrog, Brownbook, Cylex (all markets), MerchantCircle, EZLocal, ShowMeLocal, CitySquares, Callupcontact, Cybo, Storeboard, Tupalo, YellowBot, Opendi, Tuugo, n49, Ourbis, ProfileCanada, Weblocal, True Local, StartLocal, Aussie Web, Local.com.au, Thomson Local, FreeIndex, Scoot, 192.com, Applegate, and similar. *Catalogue says 95; specs exist for ~50; verified at volume: unknown.*

**C — Semi-automated (bot + CAPTCHA solver + human confirm).** Yelp, YellowPages/Superpages, Manta, and the ~33 CAPTCHA-gated entries. Bot prepares everything; a human clears the final gate. This is the "ready to finish" queue.

**D — Human verification required.** Phone or postcard verification; paid-claim directories; Data Axle and Neustar portals; anything requiring a verified business account (Google, Facebook, Apple, Bing consumer flows).

**E — Not worth automating.** Low-authority scraped directories, expired domains, and any listing that adds no discoverable value. **PROPOSED: the system must have an explicit "we deliberately skipped these and why" output**, because a client comparing 100 promised to 62 delivered needs the other 38 explained.

**F — Unsafe or inappropriate to automate.** Google Business Profile itself (use the owned API and manager access, never a bot); Apple Business Connect; Facebook; any platform whose terms forbid automated submission; OpenStreetMap (community rules forbid bulk inserts — explicitly noted) [CONFIRMED — `[CIT-CRED]`]; any directory where automation would create a listing the client does not want and cannot easily remove.

### 16.4 Reaching ~100 valuable platforms

The operator's target is ~100. The catalogue holds 155 with ~128 theoretically automatable. The realistic path:

1. **Verify the ~50 existing specs against live forms.** Specs are data, not code; verification is the bottleneck, not engineering. [PROPOSED as the first workstream]
2. **Write specs for the remaining bot-fillable entries** — roughly 45 more to reach 95.
3. **Prove the CAPTCHA-assisted path** on 10 representative directories, then extend to the 33.
4. **Accept that class D/E/F removes perhaps 25–30 from the achievable set.** A defensible delivery is therefore **~95–110 attempted, ~70–90 live, with every non-live unit explained.**
5. **Prioritise by value, not count.** A prioritised set of 60 high-authority, country-correct, niche-correct citations outperforms 100 indiscriminate ones — and the selection engine to do this already exists in part [CONFIRMED — `[RESEARCH-AUG]`].

**PROPOSED requirement:** the deliverable is a **ranked, explained citation plan** per client, not a raw count.

### 16.5 Cost model

The written commitment is **under 10¢ per unit**. The operator's current ceiling is 20¢. Evidenced unit economics [CONFIRMED — `[CIT-ECON]`]:

| Route | Cost per unit | Verdict |
|---|---|---|
| Own Playwright bot, marginal | 0.4 – 0.8¢ | Well under |
| Official API write | 0.5 – 1.9¢ | Under |
| Own bot, fully loaded (build cost amortised) | ~5¢ | Under |
| Apify off-the-shelf actor | 25¢ | **Over the 10¢ ceiling by 2.5×** |
| Managed service (BrightLocal / Whitespark) | $2 – $5 | Over by 20–50× |

Two important consequences:

- **Apify at 25¢ breaks the 10¢ commitment and sits above even the 20¢ ceiling.** The client has separately raised the Apify costing as a concern [CONFIRMED — `[WA-ADAN]` 04/08: *"apify wali costing usko issue h"*]. Apify must therefore be a **narrow, explicitly-approved fallback**, not a default path, and its use must be visible per unit in the cost ledger.
- **The 10¢ figure is a marginal cost.** It excludes CAPTCHA solver top-ups at scale, residential proxy bandwidth, mailbox costs, the browser worker's compute, and — most importantly — **the human minutes on the "ready to finish" queue.** [PROPOSED: the cost model must include a **loaded** cost per successful citation, with human time priced in, and report both marginal and loaded figures. Otherwise the ceiling is met on paper and missed in reality.]

**Feasibility verdict: the ≤20¢ target is achievable and the ≤10¢ marginal target is credible for classes A and B. It is not credible for class C once human time is counted, and class D should be priced separately as a manual service.** [STRONG INFERENCE from `[CIT-ECON]` plus the handoff-queue design]

### 16.6 Safety, quality and maintenance requirements

| ID | Requirement | Class |
|---|---|---|
| CIT-S1 | One canonical NAP record per client per location; every submission uses that exact record | CONFIRMED |
| CIT-S2 | Name and address mandatory; an empty profile blocks **before** any spend | CONFIRMED — `[CIT-CRED]` |
| CIT-S3 | Per-client accounts under the client's own identity; never shared across clients | CONFIRMED — `[CIT-ECON]`, stated as a ban-avoidance measure |
| CIT-S4 | Duplicate detection before submitting — never create a second listing where one exists | CONFIRMED — `[OVERHAUL]` §K |
| CIT-S5 | Proof per unit: live URL **and** screenshot | CONFIRMED |
| CIT-S6 | NAP drift monitoring and periodic re-verification | CONFIRMED — `[KB]` |
| CIT-S7 | Rate limiting and human pacing per directory and per IP | CONFIRMED — proxy design implies; **PROPOSED** to formalise |
| CIT-S8 | Honest failure attribution — ours vs the directory's | CONFIRMED — `[OVERHAUL]` §K |
| CIT-S9 | **PROPOSED** — a listing removal / correction workflow. Citations are permanent public records; the system that creates them must be able to fix them. | PROPOSED — this is a serious gap |
| CIT-S10 | **PROPOSED** — spec drift detection: when a directory's form changes, fail loudly with a diff, not silently | PROPOSED |
| CIT-S11 | **PROPOSED** — a per-client "citation ledger" the client can see: where they are listed, with what data, since when | PROPOSED |
| CIT-S12 | **PROPOSED** — legal and terms review of automated submission per directory class, recorded per directory | PROPOSED — this is currently undocumented and is a real exposure |
| CIT-S13 | **PROPOSED** — no fabricated business data, ever. If a directory demands a field the client has not supplied, the unit blocks rather than inventing a value. | PROPOSED — critical; fabricated NAP data actively harms local rankings |

---

## 17. WEB 2.0 SYSTEM

### 17.1 Framing

The goal is **not** random backlink automation. It is the legitimate local-SEO practice of building a small number of supporting brand properties carrying consistent NAP and one editorial link each — automated for speed and quality, not for volume-at-any-cost. [CONFIRMED — operator, 2026-08-23; `[CIT-ECON]`]

### 17.2 Current state, verified

| Fact | Evidence |
|---|---|
| Publisher framework supports ~50 platforms after successive batches | `[CODE]` migrations `0062`–`0077`, `web2_publishers.py` (3,217 lines) |
| Reported live: 20 Web 2.0 articles published with backlinks | `[OFFPAGE-STATUS]` |
| Live-today platforms: Telegra.ph (no signup), dev.to, Mataroa, Mastodon, Micro.blog, GitHub Pages, GitLab Pages, Hashnode | `[CIT-CRED]` §3 |
| Needing a one-time human OAuth run: WordPress.com, Blogger, Tumblr — the three highest-authority | `[CIT-CRED]` §2 |
| Needing manual signup: Ghost, Hatena, LiveJournal, Dreamwidth, Write.as | `[CIT-CRED]` §3 |
| Recent additions: Webflow, HubSpot CMS, Drupal, Joomla, Sanity, Storyblok, Hygraph, WriteFreely | `[CODE]` commits `74cb723`, `7c4cf76` |
| **Medium is dead** — publish API retired 2023 | CONFIRMED, stated in three separate documents |
| Weebly / Squarespace / Strikingly have no publishing API | `[CIT-ECON]` |
| Most serious platforms actively defend signup against bots | `[OFFPAGE-STATUS]` — Write.as returns "Bot detected"; Dreamwidth needs an invite code |
| House accounts shared across clients, seeded per client via CLI | `[CIT-CRED]` §1 |

### 17.3 Automation classification

**Fully automated** — Telegra.ph (anonymous), dev.to, Mataroa, Micro.blog, Mastodon instances, Hashnode, WriteFreely hosts, GitHub Pages, GitLab Pages, Ghost (with a key), and the headless-CMS class (Sanity, Storyblok, Hygraph, Webflow, HubSpot) where a token exists. *Publishing is automated; account creation generally is not.*

**Semi-automated** — WordPress.com, Blogger, Tumblr: one human OAuth run per client, then fully automated publishing. Highest authority in the set, so this is the highest-value manual step in the entire off-page module.

**Manual** — LiveJournal, Dreamwidth, Hatena, Write.as, and anything requiring invite codes or defeating bot detection at signup.

**Excluded** — Medium (no API), Weebly/Squarespace/Strikingly (no API), and any platform whose terms prohibit automated posting.

### 17.4 The 50+ target and the risk that comes with it

Reaching 50+ connected platforms is achievable — the publisher catalogue is already there. **The risk is not technical, it is penal.**

`[CIT-ECON]` states the rule plainly: *"Google's March 2026 Site Reputation Abuse update issues manual penalties for scaled, templated Web 2.0 networks. We stay clear of it by keeping every property distinct — unique content, human-paced posting, a different platform mix per client. It's a deliberate quality choice, and it's non-negotiable."*

Translating that into enforceable requirements [mix of CONFIRMED and PROPOSED]:

| ID | Requirement | Class |
|---|---|---|
| WEB2-1 | Unique content per property — never the same article spun across platforms | CONFIRMED |
| WEB2-2 | Human-paced posting — a schedule with jitter, never a burst | CONFIRMED |
| WEB2-3 | A **different platform mix per client** | CONFIRMED |
| WEB2-4 | One editorial link per property, contextually placed | CONFIRMED |
| WEB2-5 | Consistent NAP and brand across properties | CONFIRMED |
| WEB2-6 | Lead approval before each property goes live | CONFIRMED |
| WEB2-7 | **PROPOSED** — an automated cross-property similarity check that blocks publication above a similarity threshold, measured across the client's own property set **and** across all clients using the same house account | PROPOSED — this is the single most important safety control in the module |
| WEB2-8 | **PROPOSED** — house-account footprint analysis: if 30 clients publish from one dev.to account, that account is a footprint and a liability. Track properties-per-account and cap it. | PROPOSED — this is a systemic risk created by the shared-house-account design |
| WEB2-9 | **PROPOSED** — anchor-text distribution control across a client's link profile | PROPOSED |
| WEB2-10 | Account health monitoring — suspensions, deletions, link removals | CONFIRMED — `[OVERHAUL]` §K |
| WEB2-11 | **PROPOSED** — link liveness monitoring: verify each published link still exists on a schedule | PROPOSED |
| WEB2-12 | Honest per-platform status board: connected vs missing, with the reason and whose fault | CONFIRMED |
| WEB2-13 | **PROPOSED** — respect each platform's terms; record per platform whether automated posting is permitted, and refuse where it is not | PROPOSED |

### 17.5 The house-account decision

Today, Web 2.0 publishes through **shared house accounts** copied into each client's vault by a seeder CLI. [CONFIRMED — `[CIT-CRED]` §1]

`[CIT-ECON]`, delivered to the client, says something different: *"Per-client platform accounts under the client's own identity — never shared across clients (keeps them safe from bans)."*

**This is a CONFLICT between what was promised and what was built** (§30.11). It matters: shared accounts are a shared footprint and a shared failure domain. One client's ban is every client's ban, and a platform that links 30 unrelated local businesses from one account has been handed the pattern it looks for. **Recommendation: per-client accounts for the high-authority platforms (WordPress.com, Blogger, Tumblr, Ghost, Hashnode); house accounts acceptable only for anonymous or throwaway-tier platforms (Telegra.ph), and capped.**

---
## 18. AI SYSTEM

### 18.1 The governing principle

**Python computes the numbers. AI writes the narrative.** [CONFIRMED — `[WA-TEAM]` 04/07, stated as a system-wide rule]

Every AI component below must satisfy it: no metric, score, count, price or ranking may originate in a model's output. A model may interpret, classify, summarise, draft or route — never measure.

### 18.2 Where AI is used, and where it must not be

| ID | Component | Category | Why AI is needed |
|---|---|---|---|
| AI-1 | Content drafting | **Generation** | Producing ranking-grade long-form copy at volume is the product's core value; no deterministic alternative exists |
| AI-2 | Image generation + alt/title text | **Generation** | Licensed stock at volume is costlier and less specific |
| AI-3 | Audit narrative and strategy prose | **Generation** | Turning 300 findings into a client-readable story is judgement work |
| AI-4 | Policy-change categorisation (severity / category / region) | **Classification** | Unstructured Google announcements → structured, filterable KB entries |
| AI-5 | Policy-change summarisation | **Analysis** | Distil a documentation diff into "what changed, why it matters" |
| AI-6 | Content QA scoring across 14 dimensions | **Quality control** | Several dimensions (voice, depth, intent match) are not computable |
| AI-7 | AI-sounding / em-dash detection and section rewrite | **Validation + generation** | Detecting the tell requires judgement; rewriting requires generation |
| AI-8 | Search-intent classification | **Classification** | Intent is semantic |
| AI-9 | Keyword clustering into page topics | **Classification** | Semantic grouping |
| AI-10 | Citation directory discovery and matching | **Analysis** | Matching a messy listing to a canonical business is fuzzy |
| AI-11 | Page-set recommendation from competitor research | **Decision support** | Synthesis across many competitor sites |
| AI-12 | Review reply drafting | **Generation** | Tone-sensitive, human-approved |
| AI-13 | GBP post drafting | **Generation** | Policy-constrained short copy |
| AI-14 | Client-context memory (living summary + folded facts) | **Personalisation** | Keeps every module grounded in the same client truth |
| AI-15 | In-product assistant (`/ai/assist`) | **Orchestration** | Routes and summarises; the module engines do the work |
| AI-16 | Design profile interpretation | **Analysis** | Turning a scraped style into a reusable kit |

**Where AI must NOT be used** [PROPOSED, as explicit prohibitions]:
- Computing any score, rank, count, cost, volume or difficulty figure.
- Deciding whether to spend money.
- Deciding whether something is safe to publish (a model may advise; the gate is deterministic + human).
- Producing a NAP field, a phone number, an address, a price or a certification.
- Deciding permissions.
- Writing directly to a client's live site without a human gate.

### 18.3 Per-component contract

Each AI component must declare, in code and in documentation, the following. Stated once as a template and required of all sixteen:

**INPUT** — the exact structured payload, with untrusted content clearly demarcated.
**MODEL TASK** — the narrow job, the model tier chosen and why.
**OUTPUT** — a schema-validated structure, never free text where structure is possible.
**VALIDATION** — schema conformance; numeric claims cross-checked against computed values; refusal to accept an output that invents a metric.
**FAILURE MODE** — what happens on timeout, refusal, malformed output, or a cost block. The rule already established in the codebase — *degrade, do not crash* — is correct and must be universal. [CONFIRMED — `[CODE]`]
**HUMAN OVERRIDE** — who can accept, edit or reject, and where.
**COST** — which dial gates it, what a single run costs at runtime, and what the cache hit rate is.

Worked example for the highest-risk component:

> **AI-6 · Content QA scoring**
> **Input:** the draft, the brief, the SERP teardown, the client context pack. **Model task:** score 14 dimensions 0–100 with a one-line justification each. **Output:** `{dimension, score, justification, evidence_ref}[]` — schema-validated. **Validation:** every score must carry a justification; any justification containing a number not present in the input is rejected. **Failure:** on model failure the job holds at `needs_review` with the gate marked *unscored*, and a human decides — it must never auto-pass. **Override:** a lead may approve despite a failing score, and that override is logged with a reason. **Cost:** dial `content`; cached per draft hash.

### 18.4 Model routing and cost

| ID | Requirement | Class |
|---|---|---|
| AI-R1 | Multi-provider by design: Anthropic primary, with Gemini / DeepSeek / OpenAI available | CONFIRMED — `[WA-TEAM]` 04/07 |
| AI-R2 | Task-appropriate model tier — cheap models for classification, strong models for drafting | CONFIRMED |
| AI-R3 | Policy categorisation explicitly uses Haiku | CONFIRMED — `[OVERHAUL]` §D |
| AI-R4 | Aggressive caching of expensive responses | CONFIRMED |
| AI-R5 | Every AI call passes the cost gate before execution | CONFIRMED |
| AI-R6 | Actual token cost logged per call, per client, per feature | CONFIRMED |
| AI-R7 | **PROPOSED** — a per-job token ceiling, so one runaway generation cannot consume a client's monthly cap | PROPOSED |
| AI-R8 | **PROPOSED** — prompt and output retention policy: keep enough to debug, not so much that client data accumulates indefinitely | PROPOSED |

### 18.5 AI security — treated properly in §22

The system reads untrusted content from client websites, competitor sites, Google documentation, directory pages and Web 2.0 platforms, and feeds it to models whose output drives publishing and spending. The existing principle — *"website content and AI text are treated as data, not commands"* [CONFIRMED — `[ARCH]` §10] — is correct and must be enforced structurally, not by prompt wording alone. See SEC-P1…P4.

---

## 19. AUTOMATION SYSTEM

### 19.1 The critical current fact

**No automation currently runs on a schedule.** `celery_app.conf.beat_schedule = {}` as of 2026-08-19. The full schedule is preserved as `_BEAT_SCHEDULE_DISABLED` for a one-line restore, and all tasks remain registered and callable on demand. [CONFIRMED — `[CODE]`]

Restoring this is a precondition for the product being what it is sold as, and is listed as recovery priority 2 (§1.5).

### 19.2 Workflow catalogue

Each with **TRIGGER · INPUT · PROCESS · AI STEP · EXTERNAL API · DATABASE · HUMAN APPROVAL · OUTPUT · STATUS · RETRY · ERROR HANDLING · LOGGING · NOTIFICATION**. Abbreviated to the distinguishing fields; the full contract applies to all.

| ID | Workflow | Trigger | AI step | Human gate | Retry policy |
|---|---|---|---|---|---|
| AUTO-1 | Free lead audit | Public form | Narrative off | Optional | Retry on transient; never re-spend |
| AUTO-2 | Paid audit run | Manual / scheduled | Agents + narrative on | Before client send | Bounded retry; hard timeout owned by caller |
| AUTO-3 | Weekly audit refresh | **Beat (disabled)** | As above | Before send | Idempotent — dedupes on a recent audit |
| AUTO-4 | Content single job | Manual | Draft + QA + images | **Mandatory** before publish | Retry drafting; **never retry publish non-idempotently** |
| AUTO-5 | Content bulk fan-out | Manual | Per page | Per page or per batch | Resumable; partial completion is a valid state |
| AUTO-6 | Scheduled publish | Beat (disabled) | — | Approved earlier | Idempotent by job id |
| AUTO-7 | Citation audit | Manual | Discovery matching | Review target list | Safe to retry — read-only |
| AUTO-8 | Citation account creation | Manual / queued | — | — | Retry with backoff; never create duplicate accounts |
| AUTO-9 | Citation submission | Lead-approved | — | Lead approves; handoff queue for gated | **Never blind-retry a submission** — verify first |
| AUTO-10 | Citation re-verification | Beat (disabled) | — | On drift only | Safe to retry |
| AUTO-11 | Web 2.0 plan + draft | Manual | Draft per platform | — | Safe |
| AUTO-12 | Web 2.0 publish | Lead-approved | — | **Mandatory per property** | Idempotent; verify before republish |
| AUTO-13 | GBP post | Manual / scheduled | Draft | Approve | Idempotent per post id |
| AUTO-14 | Rank tracking sweep | **Beat (disabled)** | — | — | Idempotent per keyword-day |
| AUTO-15 | Rank history rollup | Beat (disabled) | — | — | Idempotent |
| AUTO-16 | Policy source diff | **Beat (disabled)** | Classify + summarise | Acknowledge/Apply/Dismiss | Safe; dedupe on content hash |
| AUTO-17 | Policy daily brief | **Beat (disabled)** | Summarise | Lead generates | Dedupe per day |
| AUTO-18 | Monthly client report | **Beat (disabled)** | Narrative | **Approve before send** | Dedupe per client × month |
| AUTO-19 | Off-page monitoring sweep | Beat (disabled) | — | On anomaly | Idempotent fan-out |
| AUTO-20 | Sheets sync | Event + buffer flush | — | — | Batched; must survive quota exhaustion |
| AUTO-21 | Milestone advancement | Event-driven | — | Never | Idempotent per event |
| AUTO-22 | Context compaction | Event-driven, debounced | Summarise + embed | — | Never re-raises — redelivery would double-spend |
| AUTO-23 | Indexing submission | On publish | — | — | Idempotent per URL |
| AUTO-24 | Notification dispatch | Event-driven | — | — | At-least-once with dedupe key |
| AUTO-25 | Nightly backup | Beat (disabled) | — | Restore confirms | Idempotent per day |
| AUTO-26 | Free-audit follow-up sequence | Cron | Personalise | — | Suppress on reply/unsubscribe |

### 19.3 Reliability requirements that apply to every job

| ID | Requirement | Class |
|---|---|---|
| AUTO-R1 | **Idempotency key** on every job that mutates external state | PROPOSED — critical |
| AUTO-R2 | Broker visibility timeout ≥ the longest task time limit, asserted at boot | CONFIRMED as a known hazard — **PROPOSED** to assert it |
| AUTO-R3 | `task_acks_late` + prefetch 1 for long jobs | CONFIRMED |
| AUTO-R4 | An overlap lock per scheduled job | CONFIRMED for some; **PROPOSED** to universalise |
| AUTO-R5 | Bounded, jittered exponential backoff; a maximum attempt count | PROPOSED |
| AUTO-R6 | A **dead-letter queue** with an operator surface | PROPOSED — nothing in evidence shows one exists |
| AUTO-R7 | Every run recorded in a `scheduled_job_runs` ledger with last-run and last-status | CONFIRMED |
| AUTO-R8 | A job's status vocabulary is identical across modules — `queued → running → needs_review → done / failed / blocked` | CONFIRMED as an intent; **PROPOSED** to enforce |
| AUTO-R9 | A cost-gate block is a **visible** state, never a silent no-op | CONFIRMED as a defect today for keyword research |
| AUTO-R10 | Jobs never re-raise into beat | CONFIRMED |
| AUTO-R11 | **PROPOSED** — a job that has spent money records that spend even if it later fails | PROPOSED |
| AUTO-R12 | **PROPOSED** — cancellation: an operator can stop a running or queued job, and the system stops spending | PROPOSED |
| AUTO-R13 | **PROPOSED** — per-client job concurrency caps so one client's bulk run cannot starve the queue | PROPOSED — mandatory at hundreds of clients |
| AUTO-R14 | **PROPOSED** — a "what will run in the next 24 hours" view, and a global pause | PROPOSED |

---

## 20. DATA MODEL

### 20.1 Entities

Reconstructed from `[ARCH]` §8, `[KB]` data-model and modules, and the 80 migrations. **Bold** = confirmed in migrations. *Italic* = proposed.

**Identity and access** — **users** (6 staff roles + client), **auth credentials** (separate schema), **user_feature_grants** (the 17-feature matrix), *role_templates*, **skill_tokens** (scoped per-client SHA-256 tokens for AI skill dispatch).

**Agency and customers** — **clients**, **client_business_profile** (NAP + the extended field set), **sites** (domain, CMS type, sealed WordPress credentials), *locations* (a client may have several — currently under-modelled; the sibling audit names the absence of a first-class location/facility entity as a top-three architectural gap, and Danyal's multi-location clients have the same need), *projects/engagements*, **milestones**, **upsells**, **tickets**, **client_report_grants**, **client_deliverables**.

**Audit** — **audits** (site, type, tier, status, run uuid, artefact path, scores), *audit_findings* (currently a JSON artefact; **PROPOSED** to normalise so findings can be tracked, assigned, fixed and re-verified across runs — this is what makes delta audits and fix verification possible), **public/free audits**, **audit overlay** (Policy-Radar-proposed checks).

**Content** — **content_jobs** (site, type, framework, target, status, published URL, cost estimate, source pack, QA score), **GBP-post extension**, *content_versions*, *content_briefs*, *topical_map / topic_cluster*, **content_schedule**, *page_model artefacts*, *design_profile per site*, **visual_validations**.

**Keywords and rankings** — **keyword research tables**, **rank_tracker tables**, **competitor_intel**, **local_seo** (3 tables: GBP, map-pack, geo-grid).

**Off-page** — **backlinks**, **citations**, **citation directories** (155 seeded), **directory strategy**, **citation campaigns**, **citation handoff**, **web2_properties**, **web2_platforms** (~50 seeded), **web2 publish records**, *web2_accounts* (needs first-class modelling given the house-account risk), *anchor_profile*.

**Intelligence** — **policy_sources**, **kb_entries** (versioned, hashed, severity/category/region flagged), **change_events**, **recommendations**.

**Platform** — **vault_secrets** (AES-256-GCM, agency and per-client `kind`), **cost_dials**, **budgets**, **cost_log**, **activity_log** (append-only), **notifications**, **settings**, **backups**, **tasks** (+ timestamps, deadline requests), **reports / SheetStore**, **scheduled_job_runs**, **entity_context** + **context_vectors** + **context_dirty** (the AI memory), **indexing** submissions, **billing** (invoice ledger — present but out of v1 scope), **data_import**, **client_onboarding**, **integrations**.

### 20.2 Data-model observations that matter

| ID | Observation | Class |
|---|---|---|
| DATA-1 | **Findings are artefacts, not rows.** Until findings are first-class, you cannot assign them, track fixes, verify remediation, or compute a delta. This blocks AUD-R1/R3/R8. | PROPOSED — high value |
| DATA-2 | **Location is under-modelled.** Multi-location clients need one business profile, one GBP, one citation set and one location page set **per location**. Modelling everything at client level will break at the first multi-branch client. | PROPOSED — high risk |
| DATA-3 | **Web 2.0 accounts need to be entities**, with a platform, an owner (house vs client), a health state and a property count — because footprint is the risk. | PROPOSED |
| DATA-4 | **Cost must be actual, not estimated.** `cost_log` exists and migration `0044` made it numeric; the requirement is that no estimate is ever displayed as a cost. | CONFIRMED |
| DATA-5 | **The activity log is the audit trail and the AI's memory.** It must be append-only, complete, and never truncated for performance. | CONFIRMED |
| DATA-6 | **Postgres is the source of truth; the vector index is derived** and fully reconstructable. This is correct and must survive. | CONFIRMED |
| DATA-7 | **PROPOSED** — a `client_change_event` entity for NAP/hours/service changes, so a single business-data change fans out to citations, schema, GBP and content updates instead of being forgotten. | PROPOSED — directly addresses the practitioner complaint in `[WA-TEAM]` 05/07 |
| DATA-8 | **PROPOSED** — soft-delete plus retention policy for clients, since off-boarding a client must not orphan live listings and published pages. | PROPOSED |
| DATA-9 | Migration count (80) with several parallel numbering collisions (`0070`, `0072` used twice) suggests migration hygiene is slipping. | CONFIRMED — `[CODE]`; **PROPOSED** to fix before more are added |

### 20.3 Isolation model

Row-Level Security is used, with two connection seams: a privileged `service_role` connection that **bypasses RLS** (server-only, never returned to a client, never logged) and an `rls_connection(user_id)` that binds the verified server-side identity transaction-locally via a bound parameter — never a string-formatted client value, so impersonation through a bound value is impossible. Crucially, `service_role` bypasses **policies, not triggers**, so guard-trigger-protected writes must use the RLS seam. [CONFIRMED — `[CODE]`]

This is well-designed and must be preserved verbatim through any refactor.

---

## 21. INTEGRATIONS

| Provider | Purpose | Auth | Failure behaviour required | Class |
|---|---|---|---|---|
| **Anthropic Claude** | Drafting, narrative, QA, classification, context | API key, agency-wide | Degrade to a hold at honest $0, never crash | CONFIRMED |
| **OpenAI images** | Content imagery | API key | Publish without images or hold — never a broken `<img>` | CONFIRMED |
| **Voyage embeddings + Pinecone** | Context vector index | API keys | Derived index; outage must not corrupt truth | CONFIRMED |
| **serper.dev** | SERP, maps, rank checks, discovery | API key | Free tier 2,500/mo; degrade to cached or hold | CONFIRMED |
| **DataForSEO** | Accurate rankings, keyword metrics, backlinks, audits | API key | Tier-gated | CONFIRMED — but see §30.3 |
| **Google Search Console** | Traffic, queries, impressions | Service account, Owner per site | Degrade with a named reason | CONFIRMED |
| **Google Analytics 4** | Sessions, conversions | Service account, Viewer + property id | Degrade | CONFIRMED |
| **Google Business Profile / Places** | GBP data, posts, reviews, local rank | Manager access / API | **Currently: sync always holds, no reader wired** | CONFIRMED defect |
| **PageSpeed Insights / CrUX** | Core Web Vitals | API key, free tier | Degrade | CONFIRMED |
| **Google Indexing API** | Request crawl | Service account | Quota-limited; queue and retry | CONFIRMED |
| **IndexNow** | Bing / Yandex instant ping | Key file on the site | Fire-and-verify | CONFIRMED |
| **Google Sheets** | Client-facing reporting | Service account | Redis write-buffer; batch inside quota; degrade to no-op | CONFIRMED |
| **WordPress** | Publishing | App password / plugin token / XML-RPC | Named degradation per capability | CONFIRMED |
| **Foursquare** | Citation write | API key, agency-wide | **Write endpoint unverified — 404** | CONFIRMED defect |
| **Bing Places** | Citation write | Partner API key | **Partner-gated, unverified** | CONFIRMED defect |
| **Apify** | Citation fallback actor | API token + actor id | 25¢/unit — over ceiling; explicit opt-in only | CONFIRMED |
| **CAPTCHA solver** (CapSolver / CapMonster) | Gated directory forms | API key + balance | Balance exhaustion must block, not silently fail | CONFIRMED |
| **Residential proxy** | Directory submission at scale | Endpoint + credentials | Bandwidth cost is real; meter it | CONFIRMED |
| **IMAP mailbox** | Reading confirmation emails | Mailbox + app password | Per-client or catch-all with plus-addressing | CONFIRMED |
| **Resend** | Transactional and report email | API key + verified domain (SPF/DKIM/DMARC) | Failure must not roll back the underlying action | CONFIRMED |
| **SMTP / IMAP (Hostinger / Titan)** | Two-way email | Mailbox credentials | — | CONFIRMED |
| **Slack** | Alerts | Webhook | Best-effort | CONFIRMED |
| **Backblaze B2** | Off-site backups | Key id + application key + bucket | Backup failure must alert loudly | CONFIRMED |
| **Firecrawl** | Crawling / extraction | API key | Degrade to own crawler | CONFIRMED |
| **Moz** | Domain authority, backlinks | API key, optional, off by default | Absent → authority-dependent features declare themselves degraded | CONFIRMED |
| **Otterly.AI** | AI search visibility | Optional | Degrade | CONFIRMED |
| **~50 Web 2.0 platforms** | Property publishing | Per-platform tokens | Per-platform honest status | CONFIRMED |
| **~155 citation directories** | Listings | Per-directory accounts | Per-directory honest status | CONFIRMED |

**Integration requirements, cross-cutting** [mostly PROPOSED]:

- INT-1 Every integration declares its **degraded behaviour** in code, and the UI shows it.
- INT-2 Every integration has a **connection test** callable from the admin surface.
- INT-3 Every integration reports **quota state** where the provider exposes it.
- INT-4 No integration is called without passing the cost gate.
- INT-5 Provider outages must be visible on the dashboard, not discovered through a failed client deliverable.
- INT-6 **Two Google auth models coexist** — service accounts for GSC/GA4/Sheets/Indexing and OAuth/manager access for GBP. This must be documented per client, because it is the single most common onboarding failure point.
- INT-7 **PROPOSED** — an integration health history, so "GBP has been failing for six days" is answerable.

---
## 22. SECURITY

### 22.1 What is already right — preserve it

| Control | State | Evidence |
|---|---|---|
| Own EdDSA (Ed25519) token minting and verification, hard `["EdDSA"]` allow-list defeating alg-confusion and `none` | Built | `[CODE]` |
| argon2id password verification | Built | `[CODE]` |
| No public signup; keyword-only privileged provisioning in one transaction | Built | `[CODE]` |
| Row-Level Security with two explicit connection seams; identity bound transaction-locally as a parameter, never string-formatted | Built | `[CODE]` |
| Client isolation proven by an integration test using each client's own DB identity | Built + verified live | `[CODE]` |
| AES-256-GCM vault under a master key; masked listing; owner-only reveal; decrypt at point of use only | Built | `[CODE]`, `[CIT-CRED]` |
| Secrets never logged; artefact paths never returned to a browser | Built | `[CODE]` |
| SSRF guard with public-host validation on outbound targets | Built | `[CODE]` |
| Fail-fast config validation in production on a missing required secret | Built | `[CODE]` |
| Docs and OpenAPI disabled in production | Built | `[CODE]` |
| Append-only activity log on every mutation | Built | `[CODE]` |
| Lead-attributed live-site writes enforced by a database guard trigger | Built (on-page) | `[CODE]` `0038` |

This is a genuinely strong security spine and is the strongest argument against a from-scratch rewrite.

### 22.2 Gaps and requirements

| ID | Requirement | Class |
|---|---|---|
| SEC-1 | **MFA for Owner and Admin.** Currently removed from Settings by instruction. The vault master key and every client credential sit behind these accounts. | **PROPOSED — recorded disagreement, §32.1** |
| SEC-2 | Credential rotation procedure per provider and per site, documented and executable | PROPOSED |
| SEC-3 | Vault master key management: where it lives, how it is rotated, what happens if it is lost, and whether a backup restore can decrypt | **UNKNOWN → PROPOSED**; this is a business-continuity risk, not just a security one |
| SEC-4 | Session lifetime and revocation. A 7-day session was introduced (commit `1c9c0c4`); there must be a way to revoke one. | PROPOSED |
| SEC-5 | Rate limiting on auth, on the public free-audit endpoint, and on client-portal actions that spend | PROPOSED |
| SEC-6 | Webhook signature verification on any inbound webhook | PROPOSED |
| SEC-7 | File-upload validation — type, size, content sniffing — for CSV/XLSX imports and logo uploads | PROPOSED |
| SEC-8 | CSRF protection on cookie-authenticated state-changing routes | PROPOSED |
| SEC-9 | Output encoding / XSS defence wherever AI-generated or client-supplied HTML is rendered in the dashboard — the WYSIWYG editor and the audit HTML viewer are both direct exposures | PROPOSED — high priority |
| SEC-10 | Parameterised queries everywhere; no string-built SQL | CONFIRMED as current practice; assert in CI |
| SEC-11 | API abuse controls per client at scale | PROPOSED |
| SEC-12 | Secrets scanning in CI (a `.gitleaks.toml` exists — ensure it runs and blocks) | CONFIRMED partial |
| SEC-13 | **Credential transmission policy.** Live credentials were repeatedly sent over WhatsApp. Every credential that appears in the chat exports must be treated as compromised and rotated before hand-off. | **CONFIRMED incident — PROPOSED remediation, urgent** |
| SEC-14 | Client credential separation: a per-client Web 2.0 or directory credential must never be visible to another client, nor to a staff member without a reason | PROPOSED |
| SEC-15 | Data-subject handling: what happens to a client's data when they leave | PROPOSED |
| SEC-16 | Backup encryption and restore testing — an untested backup is not a backup | PROPOSED |

### 22.3 AI-specific security

| ID | Requirement | Class |
|---|---|---|
| SEC-P1 | **Prompt injection**: content fetched from client sites, competitor sites, directory pages, Google documentation and Web 2.0 platforms is untrusted input. It must be structurally demarcated, never concatenated into an instruction position, and model output must never be executed as an instruction. | CONFIRMED as a principle; **PROPOSED** to enforce structurally |
| SEC-P2 | **Tool-use containment**: a model must not be able to trigger a spend, a publish, or a credential read as a side effect of interpreting a page. Capability must come from the caller, never from the content. | PROPOSED |
| SEC-P3 | **Output validation before action**: schema validation on every structured AI output; refusal on any output that invents a metric. | PROPOSED |
| SEC-P4 | **Data minimisation into prompts**: never send credentials, other clients' data, internal costs, or the vault into a model context. | PROPOSED |
| SEC-P5 | **The skills gateway** issues scoped, per-client SHA-256 tokens and cost-gates MCP dispatch — this is the right shape and must remain the only path. | CONFIRMED |

### 22.4 The highest-severity security finding

**Credentials for the live production system — admin, team, client, WordPress, VPS — were transmitted in plaintext over WhatsApp on multiple occasions and now exist in an exported chat archive sitting in the project directory.** [CONFIRMED — `[WA-ADAN]` 05/08, 15/08, 22/08; `[WA-TEAM]`]

Required before hand-off:
1. Rotate every credential that appears in those exports.
2. Move the chat export out of the repository working tree and ensure it is git-ignored (it is currently untracked but present, which is one `git add .` away from being committed).
3. Establish a credential-sharing channel that is not a messaging app.

---

## 23. MULTI-TENANCY AND SCALE

### 23.1 The framing problem

The architecture document says *"multi-tenant, single agency per deployment"* [CONFIRMED — `[ARCH]` §8]. The client-facing onboarding checklist says *"the starting set of 15 clients"* [CONFIRMED — `[PACK-JUL]`]. The operator says Danyal has **hundreds of clients** [CONFIRMED — 2026-08-23].

Fifteen and several hundred are different systems. This is CONFLICT §30.1 and the answer changes: the isolation model, the queue design, the cost model, the credential model, the reporting model, the UI's list-and-search design, and the backup strategy.

### 23.2 Requirements at the "hundreds" scale

| ID | Requirement | Class |
|---|---|---|
| MT-1 | Client isolation enforced at the database (RLS), not only in application filters | CONFIRMED — already built |
| MT-2 | Location isolation within a client | PROPOSED — see DATA-2 |
| MT-3 | Credential isolation per client, with no cross-client visibility | CONFIRMED |
| MT-4 | Per-client job concurrency caps, so one bulk run cannot starve every other client | PROPOSED |
| MT-5 | Per-client spend caps and a global daily stop | CONFIRMED |
| MT-6 | Per-client rate limiting against shared external providers | PROPOSED |
| MT-7 | **A failure for one client must not corrupt another client's data or workflow** | CONFIRMED as a principle |
| MT-8 | **PROPOSED** — shared house accounts on Web 2.0 platforms violate MT-7 by design: one client's ban is every client's ban. See §17.5. | PROPOSED — architectural |
| MT-9 | **PROPOSED** — a shared catch-all mailbox for citation confirmations is a similar shared failure domain; per-client plus-addressing or per-client mailboxes are safer | PROPOSED |
| MT-10 | Backups cover the database **and** the artefact store | PROPOSED |
| MT-11 | Disaster recovery: a documented, tested restore with a stated RTO and RPO | PROPOSED |
| MT-12 | **PROPOSED** — UI patterns that survive hundreds of rows: server-side pagination, search, saved filters, bulk selection. A client picker that renders 15 clients fine will be unusable at 400. | PROPOSED |
| MT-13 | **PROPOSED** — reporting and rollups must be pre-aggregated, not computed per page load | PROPOSED |
| MT-14 | **PROPOSED** — onboarding must be bulk-capable (CSV import of clients + sites + keywords), since manually onboarding hundreds is not viable. A `data_import` module exists; it must cover this path. | PROPOSED |
| MT-15 | Single-VPS deployment is a single point of failure; at hundreds of clients it is also a capacity ceiling — particularly for the Playwright browser workers | CONFIRMED as a stated risk; **PROPOSED** to plan a browser-worker pool separate from the API host |

### 23.3 The realistic scale bottlenecks

Ranked by when they will bite:

1. **Browser automation throughput.** Citation submission is a headless Chromium session per directory per client. At 100 directories × 100 clients that is 10,000 browser sessions. On one VPS this is the first hard wall.
2. **Cost.** At $54/client/month fully automated × 300 clients = $16,200/month. The tier model was priced for 15 clients. The cost architecture works; the business model at that volume has not been examined.
3. **Provider quotas.** Serper free tier is 2,500 searches/month total. Google Indexing API has a daily quota. Sheets has write quotas. All were sized for 15 clients.
4. **Human review capacity.** Every published artefact requires a human gate. At scale the gate, not the AI, is the bottleneck — which is a *good* design property but must be staffed and measured. **PROPOSED: measure review throughput and queue depth as a first-class operational metric.**
5. **Postgres RLS at volume.** Fine at hundreds; needs index review.

---

## 24. PERFORMANCE

| ID | Requirement | Target | Class |
|---|---|---|---|
| PERF-1 | Dashboard interactive load | < 1.5 s on cached rollups | PROPOSED |
| PERF-2 | Screen switching / navigation | Instantaneous; no visible delay | CONFIRMED — `[WA-TEAM]` 28/07 defect list |
| PERF-3 | Search triggers a visible loader | Always | CONFIRMED — same source |
| PERF-4 | API p95 for read endpoints | < 300 ms | PROPOSED |
| PERF-5 | Never block the event loop; sync DB seams offloaded to threads | Enforced | CONFIRMED |
| PERF-6 | Redis caching on expensive provider responses | ~90% cost reduction claimed | CONFIRMED |
| PERF-7 | Generated WordPress pages meet a DOM-size and page-weight budget | Asserted at publish | CONFIRMED requirement, **PROPOSED** enforcement |
| PERF-8 | Core Web Vitals on published pages measured post-publish | LCP / CLS / INP within Google's "good" thresholds | PROPOSED |
| PERF-9 | Responsive across all device sizes; no horizontal scroll | Every screen | CONFIRMED — `[WA-ADAN]` 01/08 |
| PERF-10 | Bulk operations report progress and are cancellable | Always | PROPOSED |
| PERF-11 | Audit run wall-clock, stated to the operator before starting | Estimated | PROPOSED |
| PERF-12 | The system must remain responsive while a bulk run is executing | Enforced by queue isolation | PROPOSED |

---

## 25. OBSERVABILITY

Almost nothing in the evidence addresses observability, and its absence is a direct cause of the "features don't work" experience: without it, a broken capability is discovered by a client rather than by the system.

| ID | Requirement | Class |
|---|---|---|
| OPS-1 | Structured logging with a correlation id spanning request → job → external call | PROPOSED |
| OPS-2 | Every job emits start / end / duration / outcome / cost | PROPOSED |
| OPS-3 | Per-provider metrics: call count, error rate, latency, quota consumed, spend | PROPOSED |
| OPS-4 | A queue-health surface: depth, oldest item age, failure rate, dead-letter count | PROPOSED |
| OPS-5 | Alerting on: job failure rate above threshold, spend approaching cap, provider down, backup failed, queue backed up, review queue stale | PROPOSED |
| OPS-6 | An error taxonomy — client-caused / provider-caused / ours — surfaced in the UI | CONFIRMED as a requirement for Web 2.0 (`[OVERHAUL]` §K); **PROPOSED** to generalise |
| OPS-7 | Data-freshness indicators everywhere a number is shown | CONFIRMED for context health; **PROPOSED** to generalise |
| OPS-8 | Readiness vs liveness distinction | CONFIRMED — already correct |
| OPS-9 | An operator runbook per failure mode | PROPOSED |
| OPS-10 | Retention: logs long enough to debug a client dispute (≥ 90 days) | PROPOSED |
| OPS-11 | **PROPOSED** — a weekly automated self-audit: "which capabilities have not successfully run in 7 days?" This directly catches the class of silent breakage that produced this recovery. | PROPOSED — high value, low cost |

---

## 26. ERROR HANDLING

### 26.1 The doctrine

Four rules, derived from what the codebase already gets right plus what it demonstrably misses:

1. **Degrade, never crash.** A missing key, an exhausted quota or a cost block holds the work in a named state at honest zero cost. [CONFIRMED — already the practice for content and context]
2. **Never fake success.** A job that could not do the work is `failed` or `blocked`, never `done`. A report that could not include a section says so. A button for an artefact that does not exist is not rendered. [CONFIRMED — commit `79d1036` is exactly this fix, applied late]
3. **Attribute the fault.** Every failure states whether it was the client's site, an external provider, or the platform. [CONFIRMED for Web 2.0; PROPOSED generally]
4. **Make it actionable.** Every failure state carries the next step: retry, supply a key, fix the site, contact the directory, or escalate.

### 26.2 Failure taxonomy

| Class | Examples | Required behaviour |
|---|---|---|
| **Configuration** | Missing key, invalid key, unverified partner endpoint | Block with the exact remediation; never spend; show which capability is degraded |
| **Budget** | Dial off, client cap hit, daily stop armed | Block **visibly**; hold at honest $0; notify. *Currently silent for keyword research — a defect.* |
| **Provider** | Quota, 5xx, timeout, rate limit | Bounded retry with backoff; then fail with provider attribution |
| **Target** | Site down, REST blocked, CAPTCHA unsolved, form changed, listing already exists | Named state; no blind retry; where relevant, route to the human handoff queue |
| **Content quality** | QA below threshold, AI-tell detected, schema invalid | Hold at review with the failing dimension and evidence |
| **Platform** | Bug, migration failure, worker crash | Fail loudly, dead-letter, alert |
| **Data** | Missing NAP, missing keywords, no design profile | Block before spend with the exact missing field |
| **Concurrency** | Duplicate delivery, overlapping run | Idempotency key absorbs it; overlap lock prevents it |

### 26.3 Specific error requirements

- ERR-1 A cost-gate block is always visible to the caller. [Fixes a confirmed defect]
- ERR-2 Publish operations are idempotent. [PROPOSED — prevents duplicate client pages]
- ERR-3 A submission is never blind-retried; verify first. [PROPOSED — prevents duplicate listings]
- ERR-4 An audit that produces no PDF does not offer a PDF. [CONFIRMED — fixed, must not regress]
- ERR-5 A report refuses to build on incomplete data rather than omitting a section silently. [PROPOSED]
- ERR-6 Every failed job is retryable from the UI by an authorised human, with the retry logged. [PROPOSED]
- ERR-7 Partial success is a first-class state — "17 of 20 pages published; here are the 3 and why." [PROPOSED]

---

## 27. QUALITY STANDARDS

### 27.1 What "done" is not

A feature is **not** complete because a button exists, an API responds 200, a database row was created, a page loads, or an AI response was generated. This is stated in the brief and is precisely the failure pattern the evidence shows. [CONFIRMED]

### 27.2 The nine-gate definition of done

Every major feature must pass all nine.

| Gate | Question | Evidence required |
|---|---|---|
| **1. Functional success** | Does the complete workflow produce the intended business outcome? | A recorded end-to-end run on real data |
| **2. Data success** | Is what was written correct, complete, consistent and queryable? | Post-run assertions on the stored state |
| **3. UX success** | Can the intended role complete it unaided, understand the state, and recover from failure? | A walkthrough by someone who did not build it |
| **4. Error handling** | Does every named failure mode degrade correctly and actionably? | Each failure mode deliberately triggered |
| **5. Security** | Permissions enforced server-side; secrets never exposed; untrusted input contained; isolation holds | A negative test per boundary |
| **6. Performance** | Within budget at expected volume, and it does not starve other work | Measured, not asserted |
| **7. Observability** | Can an operator tell it is working, and diagnose it when it is not, without reading code? | Logs, metrics, a status surface |
| **8. Testing** | Unit + integration + at least one true end-to-end path | Green in CI |
| **9. User acceptance** | The owner ran it at volume and accepted it | The owner's stated bar (§27.3) |

### 27.3 The owner's acceptance bar — adopt verbatim

> *"I want 50 audits / pages / citations built for 10 different businesses. Only then is testing phase 1 done. Then it comes to me. Then to the client for the third wave of testing."* [CONFIRMED — `[WA-TEAM]` 21/08]

Formalised:

| Module | Volume gate | Additional evidence |
|---|---|---|
| Audit | 50 audits across 10 real businesses | Both report formats identical; findings evidenced; no dead controls; per-run cost recorded |
| Content | 50 pages across 10 businesses | Live URLs; each opens editable in the site's builder; design matches; schema validates; zero em dashes; CWV within budget; indexing submitted |
| Citations | 50 citations across 10 businesses | Live URLs + screenshots; NAP identical everywhere; per-unit loaded cost recorded against the ceiling; every non-live unit explained |
| Web 2.0 | Across 10 businesses | Unique content proven by a similarity check; platform mix differs per client; links live |
| Policy Radar | 7 consecutive days of live daily runs | Real change events; sourced entries; recommendations actioned |
| Portals | Three real users, one per role | Each completes their workflow unaided |

**Then**, and only then, three waves: internal (team) → owner → client.

### 27.4 Engineering standards already in force

Ruff, mypy strict, import-linter contracts, pre-commit, a security test suite, isolation tests, 201 test files, ~244 unit tests cited in the module notes, and gitleaks configuration. [CONFIRMED — `[CODE]`] These are good. The gap is not code hygiene; it is **outcome verification**.

---
## 28. CURRENT KNOWN PROBLEMS

Every item below is either directly evidenced in the operator's own defect list, verified in the source, or stated in a delivered document. Severity: **P1** blocks client acceptance · **P2** materially degrades quality · **P3** should be fixed before hand-off.

### 28.1 Platform-wide

| # | Problem | Severity | Evidence |
|---|---|---|---|
| CP-1 | **All scheduled automation disabled** — `beat_schedule = {}`. No nightly ranks, no daily Policy Radar, no weekly audits, no monthly reports, no off-page sweeps, no backups. | **P1** | `[CODE]` |
| CP-2 | Hardcoded / demo data present across admin, team and client surfaces, including costs | **P1** | `[OVERHAUL]` §C, §E |
| CP-3 | Dead controls — buttons for artefacts that do not exist | **P1** | `[OVERHAUL]` §F; commit `79d1036` fixed a batch of these |
| CP-4 | Fixed prices hardcoded (e.g. a $1.50 audit estimate) instead of runtime cost | **P1** | `[OVERHAUL]` §E |
| CP-5 | Spend-stop does not provably halt **every** API, internal and external | **P1** | `[OVERHAUL]` §E |
| CP-6 | Provider toggles / manual mode / API mode "must actually work (not demo)" | **P1** | `[OVERHAUL]` §E |
| CP-7 | Email notifications off; required notifications not enabled | **P2** | `[OVERHAUL]` §Q |
| CP-8 | Features that describe themselves rather than run real work | **P1** | `[OVERHAUL]` §F |
| CP-9 | No dead-letter queue, no job cancellation, no global pause | **P2** | Absent from all evidence |
| CP-10 | No correlation-id tracing, no per-provider metrics, no alerting | **P2** | Absent |
| CP-11 | RBAC matrix hand-mirrored between backend and frontend — drift risk | **P3** | `[CODE]` |
| CP-12 | Migration numbering collisions (`0070`, `0072` duplicated) | **P3** | `[CODE]` |
| CP-13 | Live credentials transmitted over WhatsApp; export sits in the working tree | **P1** (security) | `[WA-*]` |
| CP-14 | MFA removed from Settings | **P2** | `[OVERHAUL]` §P |

### 28.2 Audit

| # | Problem | Severity | Evidence |
|---|---|---|---|
| AP-1 | Free audit still had demo Fiverr gigs, a Focus Areas field, a type split, and no download | **P1** | `[OVERHAUL]` §G |
| AP-2 | PDF and dashboard HTML were different documents | **P1** | `[OVERHAUL]` §H |
| AP-3 | "Audit Coverage" section to be removed | **P3** | `[OVERHAUL]` §H |
| AP-4 | Reports could be served empty (`report-consolidated.pdf` collapsing to a near-empty page) | **P1** | `[CODE]` |
| AP-5 | Engine and platform are separate products with separate key stores and dependency sets; engine has no failure contract | **P2** architectural | `[CODE]` |
| AP-6 | Findings are artefacts, not rows — no fix tracking, no delta, no verification | **P2** | Inferred from `[CODE]` |
| AP-7 | No abuse controls on the public free-audit endpoint | **P2** | Absent |

### 28.3 Content

| # | Problem | Severity | Evidence |
|---|---|---|---|
| CN-1 | **QA gate threshold and weights are PROVISIONAL and uncalibrated, yet enforced as a hard publish gate** | **P1** | `[CODE]` |
| CN-2 | The gate is described as a hard blocker in code and as "now advisory, not a blocker" in the August plan — contradictory | **P1** | `[CODE]` vs `[RESEARCH-AUG]` |
| CN-3 | No Research module — the system writes before deciding what to write | **P1** | `[RESEARCH-AUG]` |
| CN-4 | No bulk fan-out | **P1** | `[RESEARCH-AUG]` |
| CN-5 | Pages published as flat HTML, not builder-editable — "today's biggest gap" | **P1** | `[RESEARCH-AUG]` (composers have since been built; **verification at volume outstanding**) |
| CN-6 | No design/brand matching to the existing site | **P1** | `[RESEARCH-AUG]` (`site_design.py` since built; verification outstanding) |
| CN-7 | Raw CSS previously dumped into WordPress posts | **P2** | `[CODE]` commit `faeec43` |
| CN-8 | No duplicate-content defence: not against the web, the client's own site, or within a bulk run | **P1** SEO risk | Absent |
| CN-9 | No post-publish verification | **P2** | Absent |
| CN-10 | No publish idempotency — duplicate pages possible on redelivery | **P1** | Inferred from `[CODE]` broker note |
| CN-11 | No rollback of a published page | **P2** | Absent |
| CN-12 | Drift guard against human edits is a plain string compare | **P2** | `[CODE]` |
| CN-13 | No content maintenance model (stale NAP, hours, schema) | **P2** | `[WA-TEAM]` 05/07 |

### 28.4 Citations

| # | Problem | Severity | Evidence |
|---|---|---|---|
| CT-1 | Citation submit reported as showing FAILED | **P1** | `[OVERHAUL]` §K |
| CT-2 | "No business profile yet for this client" blocks citations — NAP not collected at client creation | **P1** | `[OVERHAUL]` §K/§L |
| CT-3 | Form specs are best-effort, unverified against live forms; ~50 of 155 | **P1** | `[CIT-CRED]`, `[CODE]` |
| CT-4 | Foursquare write endpoint 404s; Bing Places partner-gated — both unverified | **P2** | `[CIT-CRED]` |
| CT-5 | Data Axle / Neustar / OpenStreetMap have no automatable write path, so aggregator seeding is manual | **P2** | `[CIT-CRED]` |
| CT-6 | Apify fallback at 25¢ exceeds both the 10¢ commitment and the 20¢ ceiling; client has raised costing concerns | **P1** commercial | `[CIT-ECON]`, `[WA-ADAN]` |
| CT-7 | No listing removal/correction workflow | **P2** | Absent |
| CT-8 | No spec-drift detection | **P2** | Absent |
| CT-9 | Shared catch-all mailbox is a cross-client shared failure domain | **P2** | `[OFFPAGE-STATUS]` |
| CT-10 | Loaded cost (including human handoff time) never modelled | **P2** commercial | Inferred |
| CT-11 | No documented terms-of-service position per directory | **P2** legal | Absent |

### 28.5 Web 2.0

| # | Problem | Severity | Evidence |
|---|---|---|---|
| W2-1 | **House accounts shared across clients**, contradicting the per-client-identity promise made to the client | **P1** | `[CIT-CRED]` vs `[CIT-ECON]` |
| W2-2 | No cross-property similarity check — the primary defence against Site Reputation Abuse | **P1** SEO risk | Absent |
| W2-3 | No footprint analysis (properties per house account) | **P1** | Absent |
| W2-4 | No link-liveness monitoring | **P2** | Absent |
| W2-5 | Most platform signups are bot-defended; account creation remains manual | **P2** | `[OFFPAGE-STATUS]` |
| W2-6 | Per-platform status honesty was a defect to fix | **P2** | `[OVERHAUL]` §K |
| W2-7 | Anchor distribution uncontrolled | **P2** | Absent |

### 28.6 GBP, Local, Keywords, Competitors

| # | Problem | Severity | Evidence |
|---|---|---|---|
| LK-1 | `local_seo` GBP sync **always holds — no reader wired** | **P1** | `[CODE]` |
| LK-2 | `keywords.winnable` hard-codes `client_da=None` — a neutral screen, not the promised authority-adjusted verdict | **P2** | `[CODE]` |
| LK-3 | `competitor_intel` backlink-gap **returns an empty set by design**; open decision to fund an ingest or drop the endpoint | **P2** | `[CODE]` |
| LK-4 | `POST /local-seo/rankings/{id}/refresh` kicks the whole due sweep; the id only drives the 404 | **P3** | `[CODE]` |
| LK-5 | `keyword_research` cost-gate block is **silent** | **P2** | `[CODE]` |
| LK-6 | `intent_source` is DB-only; `llm` never written | **P3** | `[CODE]` |
| LK-7 | Geo-grid / map-pack tracking depth unproven at volume | **P2** | Inferred |

### 28.7 Team, Reports, Settings

| # | Problem | Severity | Evidence |
|---|---|---|---|
| TR-1 | Task assignment — team members do not appear correctly | **P1** | `[OVERHAUL]` §M |
| TR-2 | Team performance metrics do not update immediately | **P2** | `[OVERHAUL]` §M |
| TR-3 | Reports contained demo data; cron-driven real reports required | **P1** | `[OVERHAUL]` §N |
| TR-4 | Client invite emails either do not send or the control should be removed | **P2** | `[OVERHAUL]` §L |
| TR-5 | Screen-switching delay; missing search loader | **P2** | `[WA-TEAM]` 28/07 |
| TR-6 | Messaging/DM system needed a complete overhaul and merge | **P2** | `[WA-TEAM]` 28/07 |
| TR-7 | Notifications, alerts, approvals not fully wired end to end | **P1** | `[WA-TEAM]` 28/07 |

### 28.8 The meta-problem

Across all 60 items above, three root causes recur:

1. **Demo-first construction** — surfaces built before the workflows behind them.
2. **No outcome verification** — nothing proved a capability worked end to end at volume, so breakage was discovered by the operator, not the system.
3. **Uncontrolled scope with a fixed estimate** — the denominator tripled while the plan did not.

A recovery that fixes only the 60 items and not the three causes will produce a fourth list.

---

## 29. MISSING REQUIREMENTS

Requirements never explicitly discussed but necessary for a professional system. Each is justified; none is arbitrary.

### 29.1 Reliability

| ID | Requirement | Why it materially matters |
|---|---|---|
| MR-1 | Idempotency keys on all external-mutation jobs | Prevents duplicate live pages and duplicate directory listings — both client-visible and SEO-damaging |
| MR-2 | Dead-letter queue with an operator surface | Failed work currently disappears |
| MR-3 | Job cancellation and a global pause | The only way to stop a runaway spend today is to stop the worker |
| MR-4 | Bounded, jittered retry with a max attempt count | Prevents retry storms against directories and providers |
| MR-5 | Overlap locks on every scheduled job | Prevents double execution and double spend |
| MR-6 | Broker visibility timeout asserted ≥ longest task limit at boot | The codebase names this hazard; nothing enforces it |
| MR-7 | Partial-success as a first-class state | Bulk operations will partially fail; pretending otherwise loses work |
| MR-8 | Post-action verification (page renders, listing live, link exists) | "Published" must mean verified, not attempted |

### 29.2 Data integrity

| ID | Requirement | Why |
|---|---|---|
| MR-9 | Normalised audit findings | Enables fix tracking, delta audits, remediation verification — the retainer story |
| MR-10 | First-class location entity | Multi-location clients otherwise break silently |
| MR-11 | Client change events fanning out to citations, schema, GBP, content | Stops the "we forgot to update the schema after the NAP changed" failure the team itself identified |
| MR-12 | Content and page versioning with diff | Required for rollback and for proving what changed |
| MR-13 | Soft delete + retention for clients | Off-boarding must not orphan live public records |
| MR-14 | Duplicate prevention at every creation point (client, site, listing, page, account) | |
| MR-15 | A canonical NAP with change control | The single most load-bearing data item in local SEO |

### 29.3 Operations

| ID | Requirement | Why |
|---|---|---|
| MR-16 | Correlation-id tracing across request → job → provider | Debugging a client complaint currently requires reading code |
| MR-17 | Per-provider health, quota and spend metrics | Provider degradation is currently invisible until a deliverable fails |
| MR-18 | Alerting on failure rate, spend, queue depth, backup failure, stale review queue | |
| MR-19 | Weekly automated self-audit of capability liveness | Catches exactly the silent breakage that caused this recovery |
| MR-20 | Runbooks per failure mode | Required for hand-over and for non-owner operation |
| MR-21 | Tested restore with stated RTO/RPO | An untested backup is a hope |
| MR-22 | Artefact-store backup | Reports and proof screenshots are the client-visible evidence trail |

### 29.4 Safety and compliance

| ID | Requirement | Why |
|---|---|---|
| MR-23 | Cross-property similarity gate for Web 2.0 | The single most important defence against a client penalty |
| MR-24 | House-account footprint caps | Shared accounts are a shared penalty domain |
| MR-25 | Internal near-duplicate check across bulk-generated pages | Doorway-page risk |
| MR-26 | Factual-claim guard on generated copy | Legal exposure from invented prices, certifications or guarantees |
| MR-27 | Per-directory and per-platform terms-of-service position, recorded | Automating against explicit prohibition is a real risk |
| MR-28 | Listing removal / correction workflow | Citations are permanent public records |
| MR-29 | Client authorisation of record for acting under their identity | Publishing and listing under a client's name needs standing consent |
| MR-30 | No-fabrication rule enforced in code for NAP and business facts | Fabricated local data actively harms rankings |

### 29.5 Experience

| ID | Requirement | Why |
|---|---|---|
| MR-31 | A unified approval queue across every gated resource | A lead should have one place to look |
| MR-32 | Every failure legible to a specialist without escalation | The highest-leverage UX requirement in the product |
| MR-33 | Cost estimate + explicit confirmation before any bulk run | A 20-page fan-out is a four-figure decision |
| MR-34 | Data-freshness indicators wherever a number appears | |
| MR-35 | Server-side pagination, search and bulk selection everywhere | Survives hundreds of clients |
| MR-36 | Onboarding completeness meter showing which modules are blocked and why | Turns "no business profile yet" from a dead end into a task |
| MR-37 | Bulk client onboarding by import | Manual onboarding does not scale to hundreds |

---

## 30. CONFLICTING REQUIREMENTS

**None of these are resolved in this document.** Each needs an owner decision; each is carried into `DECISIONS_REQUIRED.md`.

### 30.1 Client count — 15 vs hundreds
Danyal's onboarding checklist and service-tier costing both say *"the starting set of 15 clients"* and price *"all 15 clients together"*. The operator states Danyal has **hundreds of clients**. The 15 figure appears identically in Haseeb's documents, which strongly suggests template reuse rather than a stated fact about Danyal.
**Impact:** isolation model, queue design, cost model, provider quotas, UI patterns, browser-worker capacity, backup strategy, and the entire commercial model.
**Sources:** `[PACK-JUL]` vs operator 2026-08-23.

### 30.2 Citation cost ceiling — 10¢ vs 20¢
A document delivered to the client on 17 July commits to **under 10¢ per citation and per backlink**, with a headline "Under 10¢" and a per-route table proving it. The operator now states a maximum of **20 cents**.
**Impact:** whether Apify (25¢) is ever permissible; whether class-C human-assisted citations are viable; what the client believes was promised.
**Recommended resolution:** engineer to ≤10¢ marginal, treat 20¢ as the hard fail line, and report **loaded** cost separately. Needs confirmation.

### 30.3 Rankings source — DataForSEO vs serper.dev
The service-tiers document flags this itself: *"The main plan and full tool list say use DataForSEO for rankings … the client setup checklist says serper.dev … please pick one official rankings source before we build, because the cost and the data pipeline both depend on it."* It was never picked.
**Impact:** cost model, accuracy claims, tier definitions, the geo-grid design.

### 30.4 Off-page scope
Kickoff: *"Off-Page module is out of scope for now."* Seven months of subsequent work, two delivered client documents, and the current instruction all treat it as central.
**Impact:** the baseline against which "percentage complete" is measured. Resolved in practice — **in scope** — but must be recorded as a formal scope change with an estimate.

### 30.5 Audit report length
Kickoff: 20–30+ pages. Overhaul: free = 10–15 pages condensed, paid = "the 400-page paid one". Engine: executive 10–15, full 40–80. `[CODE]` cites a real run at 69 pages.
**Impact:** what the client expects to receive.

### 30.6 Upsells — in or out
Kickoff locked Fiverr-gig upsells as a deliberate brand decision. The overhaul backlog says *"Remove the Upsells section (for now)"* under Reports, while the Free Audit section says replace demo gigs with Danyal's **real** gigs.
**Impact:** whether the client portal has an upsell surface at all.

### 30.7 Web 2.0 platform count
`[CIT-ECON]` (to client): 8 clean first-build, ~25–31 with live APIs. `[CIT-CRED]`: 16 publishers. Code: ~50 after successive batches. Operator: 50+.
**Impact:** what "connected" means, and whether count is being confused with working coverage.

### 30.8 Citation platform count
Catalogue 155; `[CIT-ECON]` "~180 dirs mapped"; `[RESEARCH-AUG]` target "40–50 live"; `[OFFPAGE-STATUS]` "84 directories wired, 26 accounts"; operator "up to 100".
**Impact:** the acceptance definition.

### 30.9 Content QA gate — hard or advisory
`[CODE]`: *"The QA §11 gate is a hard publish gate … re-checked at publish."* `[RESEARCH-AUG]`: *"a quality scorecard (now advisory, not a blocker)."*
**Impact:** whether good drafts are being blocked or bad drafts published. **This must be resolved before any volume run.**

### 30.10 Multi-tenancy framing
`[ARCH]`: *"multi-tenant, single agency per deployment."* Operator: hundreds of clients each needing isolation, and — implied — their own portal experience.
**Impact:** see 30.1.

### 30.11 Web 2.0 account ownership
`[CIT-ECON]` to client: *"Per-client platform accounts under the client's own identity — never shared across clients (keeps them safe from bans)."* `[CIT-CRED]` as built: *"The agency publishes Web 2.0 through shared house accounts."*
**Impact:** client safety, penalty blast radius, and a promise-vs-delivery gap.

### 30.12 MFA
`[OVERHAUL]` §P: remove Two-Factor Auth from Settings. Security requirement: the Owner account holds the vault master key.
**Impact:** credential-theft blast radius. Recorded as a disagreement, §32.1.

### 30.13 Content cost per page
Kickoff quoted **$10–50 per page** to the client. `[OVERHAUL]` §E forbids any predefined price and mandates runtime cost only.
**Impact:** these are reconcilable — the quote is a client-facing expectation, the rule is about what the software displays — but the reconciliation must be explicit, and actual per-page cost must be measured against the quote.

---
## 31. OPEN QUESTIONS

Full detail with context in `OPEN_QUESTIONS.md`. Summarised here by blocking status.

**Blocking (work cannot proceed correctly without an answer):**
Q-1 true client count · Q-2 citation ceiling of record · Q-3 rankings source · Q-4 QA gate hard or advisory · Q-5 Web 2.0 account ownership model · Q-6 whether the deadline is fixed or the scope is · Q-7 what exactly the client has already seen and been promised.

**High impact (answerable in a sentence, changes design):**
Q-8 multi-location clients — how many, and is per-location modelling needed now · Q-9 is Manager a distinct portal or folded into Admin · Q-10 per-client portal branding and custom domains · Q-11 does the client approve content · Q-12 does the client approve publishing to their own site · Q-13 upsells in or out · Q-14 GBP — owned API access or drafts only · Q-15 Elementor or Gutenberg default · Q-16 which markets beyond US/UK/CA/AU · Q-17 which niches, for niche directory selection.

**Operational:**
Q-18 vault master key custody and rotation · Q-19 who operates the system day to day after hand-off · Q-20 what the client is contractually owed · Q-21 hosting ownership and access after hand-off · Q-22 which credentials in the WhatsApp export are still live · Q-23 whether the audit engine ships as part of the deliverable or stays a Xegents asset · Q-24 what happens to the free-audit lead flow and who owns those leads.

---

## 32. RECOMMENDED IMPROVEMENTS

### 32.1 Recorded disagreements with existing instructions

Two instructions in the evidence should, in this analysis, be reconsidered. Both are flagged rather than overridden.

**32.1.1 — Removing MFA from Settings** (`[OVERHAUL]` §P). The Owner account can reveal every credential in the vault, including client WordPress passwords and directory logins. Removing MFA from the UI reduces surface clutter and increases blast radius. **Recommendation:** keep the Settings trim, but reinstate MFA for Owner and Admin only, before production hand-off. If the instruction stands, the risk is accepted knowingly.

**32.1.2 — "Remove the Upsells section (for now)"** (`[OVERHAUL]` §N) conflicts with a decision the client took in the kickoff call for brand reasons. **Recommendation:** confirm with the client rather than removing a feature they asked for.

### 32.2 Architectural recommendations

| ID | Recommendation | Rationale |
|---|---|---|
| IMP-1 | **Do not rewrite from scratch.** Fix forward. | The security spine, RLS isolation, cost gate, database-enforced lifecycles and the composer layer are genuinely good work. A rewrite discards them and adds months. The defects are concentrated in verification, scheduling, truthfulness and coverage — all fixable in place. |
| IMP-2 | **Resolve the audit-engine seam.** Three options: (a) keep the subprocess but give the engine a real failure contract, a passed-in run id and vault-sourced keys; (b) vendor the engine into the platform as a library; (c) run it as a service with an HTTP contract. | Two key stores and a stdout-parsed contract is the most fragile seam in the system. Option (a) is cheapest and sufficient. |
| IMP-3 | **Make the canonical page model the single content currency.** Everything renders from it: Elementor, Gutenberg, HTML, PDF, preview. | Already the direction; finishing it removes an entire class of format-drift bugs. |
| IMP-4 | **Promote findings to rows.** | Unlocks delta audits, fix verification, audit→task conversion — the three things that turn a one-off audit into a retainer. |
| IMP-5 | **Introduce a location entity.** | Multi-location local SEO is the vertical; modelling it at client level will break. |
| IMP-6 | **Separate the browser-worker fleet from the API host.** | Playwright at citation volume is the capacity wall. |
| IMP-7 | **One status vocabulary, one approval queue, one failure taxonomy across all modules.** | Currently each module invents its own; the operator pays the cost. |
| IMP-8 | **Generate the frontend permission data from the backend matrix.** | Removes a hand-mirroring drift bug. |
| IMP-9 | **Add a capability-liveness self-audit.** | The system should discover its own silent breakage before a client does. |
| IMP-10 | **Version the WordPress plugin against Elementor versions with a compatibility matrix and regression tests.** | The output format depends on a third party's internals. |

### 32.3 SEO-outcome recommendations

| ID | Recommendation | Rationale |
|---|---|---|
| IMP-11 | Impact×effort prioritisation in every audit | The agency is paid for judgement, not enumeration |
| IMP-12 | Competitor-relative scoring | Absolute scores are uninterpretable |
| IMP-13 | Internal near-duplicate gate on bulk content | Doorway-page risk is the biggest SEO exposure in the product |
| IMP-14 | Cross-property similarity gate on Web 2.0 | Site Reputation Abuse is the biggest off-page exposure |
| IMP-15 | Topical map / cluster model | Topical authority is how local content actually ranks |
| IMP-16 | Content maintenance loop — detect stale NAP, hours, schema, and raise tasks | The team named this gap themselves |
| IMP-17 | Fix verification — prove a finding was resolved | This is the reporting story that renews retainers |
| IMP-18 | GEO / AI-search as a headline differentiator | Already built and genuinely ahead of the market; currently under-sold |
| IMP-19 | Prioritised, explained citation plans rather than raw counts | Quality over count, and defensible to the client |
| IMP-20 | Rank and impression movement tracked on a cohort, so the platform can prove it works | BO-4 has no measurement today |

### 32.4 Commercial and delivery recommendations

| ID | Recommendation |
|---|---|
| IMP-21 | **Re-baseline the scope and the estimate in writing**, listing every addition since 2026-07-03 with its cost. This is the single highest-value action available and takes hours, not weeks. |
| IMP-22 | Adopt the owner's volume bar (§27.3) as the formal acceptance criteria and run it before, not after, the client sees the system. |
| IMP-23 | Deliver in verified vertical slices, each ending in a demonstrable outcome, rather than in module completeness. |
| IMP-24 | Publish a **capability truth table** to the client: what is live, what is degraded and why, what is manual, what is planned. Honesty here is recoverable; discovered overstatement is not. |
| IMP-25 | Rotate every exposed credential and fix the credential-sharing process before hand-off. |
| IMP-26 | Price the manual handoff time into the citation and Web 2.0 service, or the unit economics are wrong at volume. |

---

## 33. RISKS

| ID | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-1 | Deadline missed because scope was never re-baselined | High | Critical | IMP-21; explicit scope-vs-deadline decision (Q-6) |
| R-2 | Client discovers demo data or a dead control after hand-off | Medium | Critical | Truthfulness sweep as recovery priority 1; capability truth table |
| R-3 | A client is penalised by Google for templated Web 2.0 or doorway pages | Medium | **Catastrophic** — this ends the relationship and damages the client's business | IMP-13, IMP-14, MR-23/24/25 as hard gates |
| R-4 | Duplicate live pages or duplicate listings created by job redelivery | Medium-High | High | MR-1 idempotency, MR-6 visibility-timeout assertion |
| R-5 | Citation coverage falls far short of ~100 because specs are unverified | High | High | Verify existing 50 first; report attempted/live/skipped honestly |
| R-6 | Cost ceiling missed once human handoff time is counted | High | Medium | IMP-26; loaded-cost model; price class C separately |
| R-7 | Shared house accounts banned, taking every client's properties down at once | Medium | High | Per-client accounts for high-authority platforms; footprint caps |
| R-8 | Exposed credentials abused | Medium | High | SEC-13 rotation, urgent |
| R-9 | Single VPS fails; no tested restore | Low-Medium | Critical | MR-21, MR-22 |
| R-10 | Browser-worker capacity wall at volume | High at scale | High | IMP-6 |
| R-11 | Elementor internal format changes and every generated page becomes uneditable | Medium | High | IMP-10 version pinning + regression tests |
| R-12 | Provider quota exhaustion (Serper free tier, Indexing API, Sheets) at scale | High | Medium | INT-3 quota metrics; per-client rate limits |
| R-13 | Uncalibrated QA gate blocks good content or passes bad content | **Certain today** | High | CN-1/CN-2 resolution before any volume run |
| R-14 | Key-person dependency on the lead engineer | High | High | Runbooks, documentation, hand-over |
| R-15 | Team capacity and discipline issues recur | Medium-High | High | Volume acceptance gate before owner review; loom/report discipline already instituted |
| R-16 | Client asks a technical question the team cannot answer (the pattern the owner already tested them on) | Medium | Medium | Capability truth table; documented degradation states |
| R-17 | Vault master key lost or unrotatable | Low | Critical | Q-18; documented custody |
| R-18 | Legal exposure from automated submissions or fabricated claims | Low-Medium | High | MR-26, MR-27, MR-29, MR-30 |
| R-19 | The 15-vs-hundreds ambiguity is discovered late and forces re-architecture | Medium | Critical | Q-1, answer immediately |
| R-20 | Recovery fixes the 60 defects but not the three root causes, producing a fourth defect list | Medium-High | High | §28.8; adopt §27 gates and the scope-change guard |

---

## 34. ASSUMPTIONS

Every assumption made in producing this document, stated so it can be falsified.

| ID | Assumption | If wrong |
|---|---|---|
| A-1 | The repository at HEAD `79d1036` is the system to be recovered, and `app.qanry.com` runs approximately this code | The current-state findings may not describe production |
| A-2 | Danyal's system and Haseeb's system are separate products sharing lineage, and Haseeb's requirements do not apply to Danyal | Scope would expand substantially |
| A-3 | The AgencyBook SaaS is a separate product and its features are reference only | Scope would expand substantially |
| A-4 | Documents in Danyal's pack quoting "15 clients" inherited that figure from Haseeb's brief rather than stating a fact about Danyal | The scale requirements in §23 would relax |
| A-5 | The operator's 2026-08-23 statement is the current, authoritative business requirement | Priorities would change |
| A-6 | The extended deadline is measured in weeks, not months | Sequencing would change |
| A-7 | Danyal will supply the remaining API keys and access | Several modules stay permanently degraded |
| A-8 | The audit engine remains a separate product under Xegents' control | IMP-2 options change |
| A-9 | WordPress remains the only CMS target for v1 | Publishing scope expands |
| A-10 | Markets are US, UK, Canada and Australia | Directory and Web 2.0 catalogues change |
| A-11 | The client base is general local business, not a single vertical | Niche directory selection changes |
| A-12 | Off-page is definitively in scope | §16 and §17 become out of scope |
| A-13 | The human review gate is non-negotiable in every tier | The automation design changes fundamentally |
| A-14 | The team executing the recovery has access to the VPS, the vault and all provider accounts | Verification work is blocked |
| A-15 | No payment gateway and no public signup remain out of scope | New modules required |
| A-16 | The 300-check audit engine's checks are substantively correct — this analysis reviewed its structure, not every check | Audit quality claims would need re-examination |
| A-17 | Chat evidence in Roman Urdu was interpreted correctly; where a message was ambiguous it was classified UNKNOWN rather than inferred | Some CONFIRMED items may drop to STRONG INFERENCE |
| A-18 | Voice notes, videos and images in the WhatsApp export contain no requirement not also present in text or in a document. **This is the weakest assumption in the document** — the export contains several hundred audio files and one image-only PDF (`Danial Project discussion`) that could not be read | Requirements may be missing; see the note in `OPEN_QUESTIONS.md` |

---

## 35. DEFINITION OF DONE

### 35.1 Per feature

All nine gates in §27.2, evidenced, not asserted.

### 35.2 Per module

| Module | Done when |
|---|---|
| **Audit** | 50 audits across 10 real businesses; free and paid both complete; HTML and PDF byte-equivalent in content; every finding evidenced; type picker works; no dead controls; per-run actual cost recorded; a partial run produces a named state |
| **Content** | 50 pages across 10 businesses; research module recommends the set; bulk fan-out completes with a URL manifest; every page opens editable in the site's builder; design matches; schema validates; zero em dashes; internal near-duplication under threshold; CWV within budget; indexing submitted and confirmed; publish idempotent; rollback proven |
| **WordPress** | Capability discovery correct on 10 different real sites including at least three Elementor, two Gutenberg-only and one ACF site; no site's design, performance or existing content altered; revert proven |
| **Citations** | 50 citations across 10 businesses with live URLs and screenshots; NAP identical across all; duplicates avoided; loaded cost per unit recorded against the ceiling; every attempted-but-not-live unit explained; handoff queue works; re-verification runs |
| **Web 2.0** | Properties across 10 businesses; cross-property similarity below threshold; platform mix differs per client; all links verified live; account health monitored; per-platform status honest |
| **GBP** | Posts drafted, policy-checked, approved and published for 5 businesses |
| **Indexing** | Every published URL submitted via IndexNow and the Google Indexing API with status tracked |
| **Policy Radar** | 7 consecutive days of live daily runs producing real, sourced change events and recommendations; an applied recommendation writes an audit overlay and nothing else |
| **Portals** | One real user per role completes their full workflow unaided; permission matrix verified by negative tests; client isolation re-proven |
| **Cost control** | Every paid call passes the gate; the daily stop halts every API; no hardcoded price anywhere; a month of actual per-client cost reported |
| **Automation** | Beat restored; every job idempotent, retried, locked, ledgered and observable; a dead-letter queue with an operator surface; cancellation and global pause work |

### 35.3 Per project

The project is done when:

1. All P1 problems in §28 are closed with evidence.
2. All 13 conflicts in §30 have a written owner decision.
3. All blocking open questions in §31 are answered.
4. The owner's volume bar (§27.3) has been met and recorded.
5. Three testing waves have completed: internal → owner → client.
6. Every credential exposed in chat has been rotated.
7. A capability truth table has been delivered to the client, and it is accurate.
8. Runbooks, restore procedure and hand-over documentation exist and have been exercised by someone other than the author.
9. Every account, server and credential is in Danyal's name with no builder lock-in.
10. The scope has been re-baselined in writing and the client has accepted it.

### 35.4 The one-line test

> **Could a competent operator who has never met the development team run this agency's delivery for a month, at volume, without asking a question the system cannot answer — and would the resulting SEO work stand up to expert review?**

Until the answer is yes, the project is not done.

---

## APPENDIX A — EVIDENCE INVENTORY

| Source | Type | Read | Notes |
|---|---|---|---|
| `WhatsApp Chat - Adan (Software Engineer)/_chat.txt` | 2,502 lines | Full (filtered for substance) | 1:1 with lead engineer, 30 Jun – 22 Aug |
| `WhatsApp Chat - Team Dev/_chat.txt` | Team group | Full (filtered) | 30 Jun – 21 Aug |
| ~660 media files (Adan) + ~230 (Team Dev) | Audio/video/images | **Not read** | Several hundred `.opus` voice notes; see A-18 |
| `00000129-Danial Project discussion.pdf` | 2 pages | **Not readable** — image-only, no text layer | Potentially significant; see `OPEN_QUESTIONS.md` |
| `Xegents-Citations-Web2-Automation-Plan.pdf` | 4 pages | Full | Client-delivered, 17 Jul |
| `danyal-AIOS-*` (6 documents) | 45 pages | Full | Client pack, 9 Jul |
| `AIOS-Content-Citations-Indexing-Research-Plan.pdf` | 14 pages | Full | Aug 2026, most recent plan |
| `xegents-offpage-citations-web2.pdf` | 5 pages | Full | Built-state report |
| `AIOS-Backend-vs-Brief-Audit.pdf` | 7 pages | Full | **Haseeb's project** — method reference only |
| `AIOS-Complete-Operating-Dossier.pdf` | 48 pages | Header + contents | **Haseeb's project** — quarantined |
| `AIOS-System-Report-and-UIUX-Handoff.pdf` | 15 pages | Header | **Haseeb's project** — quarantined |
| `MARKETING-OS-Nano-Factory-Plan.pdf` | 69 pages | Not read | Unrelated product |
| `Xegents-Search-Visibility-Audit.pdf` | 265 pages | Not read | Xegents' own site audit; sample of engine output |
| `context/ARCHITECTURE-AND-PLAN.md` | 343 lines | Full | v1 locked architecture |
| `context/PRODUCT-OVERHAUL-BACKLOG.md` | 149 lines | Full | The operator defect list |
| `docs/meeting-notes/2026-07-03-scope-call.md` | 102 lines | Full | The governing baseline |
| `knowledge-base/*.md` | 6 files | modules.md full, others sampled | In-repo KB |
| `backend/` | 527 Python files, ~149k lines | Structure + key modules + `CLAUDE.md` | |
| `frontend/` | 218 TS/TSX files, ~27k lines | Route inventory | |
| `danyals-audit-system/` | 59 Python files, ~20k lines | Structure + README + checklists | |
| `db/migrations/` | 80 migrations | Inventory + citation/web2 seeds | |
| `wordpress-plugin/aios-publisher/` | 8 files | Inventory | v1.7.0 by commit history |
| Git history | 321 commits, 9 Jul – 23 Aug | Full log | |

## APPENDIX B — WHAT THIS PHASE DELIBERATELY DID NOT DO

No implementation code was written. No repository structure was changed. No existing technical decision was reversed. No conflict was silently resolved. No feasibility claim was made without evidence, and where evidence was insufficient the item was classified UNKNOWN rather than estimated.

Four artefacts were produced, all under `docs/recovery/`:
`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md` · `OPEN_QUESTIONS.md` · `DECISIONS_REQUIRED.md` · `REQUIREMENTS_TRACEABILITY.md`

## APPENDIX C — SECOND-PASS REVIEW

The brief required a self-review. Questions asked, and what changed as a result:

**"What important requirement could I have missed?"** → Added: content maintenance and decay (§14.8 item 8, MR-11); listing removal/correction (CIT-S9); link liveness (WEB2-11); post-publish verification (CONT-53); the artefact-store backup gap (MR-22); bulk client onboarding (MR-37).

**"What assumption did I treat as fact?"** → Corrected: an initial reading that the audit engine's multi-agent quality gates were disabled in the platform path. They are enabled for full paid runs and disabled only for the free path, which is correct cost control, not a defect. Also demoted "15 clients" from a fact about Danyal to a probable template artefact (A-4).

**"What requirement conflicts with another?"** → Thirteen conflicts recorded in §30; two previously unnoticed ones surfaced during review: the Web 2.0 account-ownership contradiction (§30.11) and the QA-gate contradiction (§30.9).

**"What would a senior local SEO agency owner expect that is missing?"** → Delta reporting and fix verification (AUD-R1/R3); competitor-relative scoring (AUD-R6); topical maps (CONT-11); anchor distribution control (WEB2-9); prioritised rather than counted citations (§16.4); and proof that the work moved rankings (IMP-20).

**"What would a senior software architect expect that is missing?"** → Idempotency, dead-letter handling, cancellation, correlation tracing, per-provider metrics, alerting, tested restore, per-tenant concurrency caps, and a single status vocabulary. All now in §29.

**"What would cause this system to fail at 100+ clients?"** → Browser-worker throughput first, then provider quotas, then human review capacity, then UI patterns that assume small lists, then cost. §23.3.

**"What would cause it to produce poor SEO results?"** → Bulk pages that near-duplicate each other; templated Web 2.0; fabricated or inconsistent NAP; an uncalibrated QA gate; audits that enumerate rather than prioritise; and content published but never verified or maintained. Each now has a named control.

**"What would cause client dissatisfaction?"** → Discovering demo data; a dead button; a report that will not open; a page that cannot be edited; a listing with the wrong phone number; a promised platform count not delivered without explanation; and — the largest — a Google penalty. §33.
