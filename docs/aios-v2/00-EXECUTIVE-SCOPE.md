# 00 · Executive Scope

**AIOS v2 — Agency Intelligence Operating System**
Approved 2026-09-16 · Owner: Zain Saeed · Client: Danyal (agency) · Build: greenfield

---

## 1. What this is

A multi-tenant SEO operations platform that one agency runs for 50–100 client
businesses. It replaces the manual work of an SEO team — auditing, planning, writing,
publishing, citation building, off-page placement, tracking and reporting — with
supervised automation, and it presents the result to the agency's own clients through a
branded portal.

**v2 is a rebuild, not a refactor.** v1 exists, runs at `app.qanry.com`, and proved the
domain. It also accumulated defects that are structural rather than local: data that was
synthesised and presented as measured, jobs that reported `done` when they had done
nothing, a job layer with no idempotency, and design capture that could not produce an
editable page. v2 keeps v1's domain knowledge and discards its architecture. See
[`14-SALVAGE-MAP.md`](14-SALVAGE-MAP.md).

---

## 2. Who it serves

| Actor | Who | What they need |
|---|---|---|
| **Owner** | Zain / Danyal | Everything. Provisioning, spend, keys, the truth about system state. |
| **Admin / Super-Admin** | Agency leadership | Client book, team workload, approvals, cost control. |
| **Manager** | Delivery lead | Assigns work, reviews drafts, presses publish. |
| **Staff (4 roles)** | SEO · Content · Off-page · Support | A queue of well-specified tasks and the tools to finish them. |
| **Client** | The end business | A portal showing what was done, what it achieved, and what is next. Never approves; never sees internals. |
| **Public visitor** | A lead | A free audit that is good enough to convert them. |

**Approval doctrine (fixed):** a human always approves before anything reaches a client's
live site or a third-party platform. That human is **always agency staff**, never the end
client. The client portal is informational.

---

## 3. The modules

Twelve modules. All are in scope. Sequencing is in
[`10-BACKLOG-ROADMAP.md`](10-BACKLOG-ROADMAP.md); depth targets are per-module.

| # | Module | Core promise | Spec |
|---|---|---|---|
| **M01** | **Portal & Platform Core** | Identity, RBAC, clients, team, tasks, milestones, notifications, activity, settings, key vault, cost control, the job engine's UI. Everything else mounts on this. | [M01](modules/M01-portal-and-platform-core.md) |
| **M02** | **Audit** | A free condensed audit as a public lead magnet, and paid audits in six types with full narrative, findings JSON, remediation sheets, HTML viewer and PDF from one source. | [M02](modules/M02-audit.md) |
| **M03** | **Content System** | Learn a client's existing design system from their previous site, plan a page set from a topical map, write against an SEO keyword bank with volumes, QA it, and publish it to WordPress as a **genuinely editable Elementor block tree** in the client's own design language. | [M03](modules/M03-content-system.md) |
| **M04** | **Citations** | An operator-run browser extension with a backend AI agent that **creates the directory account**, fills the form, captures proof, and re-verifies. Human presses submit. | [M04](modules/M04-citations.md) |
| **M05** | **Web 2.0 & Social Publishing** | 32 platforms through official APIs — social networks, blog properties, bookmarking, code/paste hosts and automation bridges — with images, internal linking, SEO fields, anchor strategy and human-paced scheduling. | [M05](modules/M05-web2-and-social.md) |
| **M06** | **Policy Radar** | Watch search-industry sources, detect change events, maintain a knowledge base, and turn changes into per-client recommendations and a daily brief. | [M06](modules/M06-policy-radar.md) |
| **M07** | **Rank & Grid Tracking** | Organic rank history (DataForSEO) and local-pack geo-grid heat maps (serper.dev), never mixed, always labelled, with a three-state measurement model. | [M07](modules/M07-rank-and-grid-tracking.md) |
| **M08** | **Keyword Research** | The source of the keyword bank: discovery, clustering, volume and difficulty, intent classification, SERP features, and the topical map that drives Content. | [M08](modules/M08-keyword-research.md) |
| **M09** | **Indexing** | Submit new and updated URLs to Google Indexing API, IndexNow and Bing; monitor index state; report what actually got indexed. | [M09](modules/M09-indexing.md) |
| **M10** | **Local SEO & GBP** | Google Business Profile posts, Q&A, reviews, categories and NAP as the canonical source that Citations consumes. | [M10](modules/M10-local-seo-and-gbp.md) |
| **M11** | **Reporting & Deliverables** | One rendering pipeline for every client-facing artefact: HTML, PDF, and scheduled email. | [M11](modules/M11-reporting-and-deliverables.md) |
| **M12** | **Billing, Tiers & Cost Control** | Service tiers, entitlements, money dials, per-client spend caps, loaded-cost accounting, upsells. | [M12](modules/M12-billing-tiers-and-cost.md) |

**Cross-cutting, not modules:** the job engine, the vault, the cost gate, the provenance
layer, the AI runtime, observability. These are platform primitives specified in
[`03-ARCHITECTURE.md`](03-ARCHITECTURE.md) and must exist before module work starts.

---

## 4. Explicitly out of scope for v2.0

Listed so nobody builds them by accident. Each may return as v2.1.

- **Multi-agency white-label tenancy.** One agency, many clients. The data model must not
  make this impossible, but no UI, billing or routing for it.
- **Multilingual content.** English only. Schema carries a `locale` column; nothing reads
  it yet.
- **Paid-ads management,** email marketing campaigns, CRM, or invoicing/payments
  collection. Mailchimp appears in M05 only as a *publishing destination*.
- **Browser automation of any platform whose terms forbid it.** If a platform has no API
  and forbids automation, it is skipped and marked `do_not_use`. No exceptions.
- **Claiming existing citation listings** (postcard / phone-PIN flows). We detect and
  report duplicates; claiming is a human task outside the tool.
- **Horizontal scaling:** sharding, read replicas, multi-region. Revisit above ~500
  clients.
- **Client-side approval workflows.** See the approval doctrine.

---

## 5. The ten principles

These are not style preferences. Each one is a defect class that v1 shipped, written as
a rule. A change that violates one of these is rejected in review regardless of whether
it passes tests.

### P1 · Never invent data
No code path may generate, hash-derive, sample or estimate a value and present it as
measured. A provider that is not configured produces a **degraded result**, never a
plausible number. This is enforced by a CI gate (`test_no_synthetic_data_reachable`) that
walks every writing path.

### P2 · Three states, never two
Any measurement is `measured` · `absent` (looked, not there) · `unmeasured` (never
looked). `absent` and `unmeasured` are different facts and must never collapse. Every
ratio divides by **measured** only. Enforced by CHECK constraints, not by convention.

### P3 · Degrade, never crash
Every external seam returns a typed result with `status: ok | degraded` and a
machine-branchable `reason`. No caller may distinguish failure modes by parsing a string.

### P4 · Terminal states are honest
A publish with no credentials is `blocked`, not `done`. A job that timed out is
`timed_out`, not `failed`. A run with partial output is `partial`. The state a row carries
is the state the user is told.

### P5 · Money is gated before it is spent
Every paid provider call passes a cost gate that knows the module dial, the client cap
and the global halt. The *estimate* gates; the *actual* is committed after the call. A
blocked call never reaches the provider.

### P6 · The database enforces tenancy
`FORCE ROW LEVEL SECURITY` on every table carrying `client_id`. Application code is the
second line of defence, never the first. A CI gate fails the build if any tenant table
lacks a FORCE policy.

### P7 · Every job is idempotent, durable and resumable
Jobs carry an idempotency key, persist their state in Postgres, retry with backoff, and
land in a dead-letter queue with the full failure context. Re-running a job must never
double-spend, double-publish or double-charge.

### P8 · Provenance on every value
Every stored fact records how it was obtained — `measured` · `derived` · `declared` ·
`inferred` · `defaulted` — with its source and timestamp. A value nobody can account for
six months later is a liability.

### P9 · Secrets are sealed, per-client, and audited
Envelope encryption with a KEK outside the database. Decryption is a service call that
writes an audit row. No secret is ever logged, returned by an API, or placed in a job
payload.

### P10 · Tests prove behaviour, not coverage
Every test must fail when its defect is re-injected. A test that passes against a broken
implementation is deleted, not kept. No test is weakened to make a build green.

---

## 6. Success criteria for v2.0

The build is done when all of these are demonstrably true on production data.

| # | Criterion | Measured how |
|---|---|---|
| S1 | **50-page content run.** 50 pages generated, QA'd, reviewed and published to a real WordPress site as editable Elementor block trees in the client's design system, with zero manual repair. | A recorded run against one client |
| S2 | **100 citations.** 100 live, verified directory listings built for one client through the extension, with proof artefacts and a loaded cost per citation inside the agreed ceiling. | Citation ledger export |
| S3 | **One Web 2.0 campaign** across ≥15 platforms with per-client identities, images, internal links and correct SEO fields, all via official APIs, no platform ban. | Campaign report |
| S4 | **Audit parity.** A paid audit of each of the six types completes inside its cost ceiling with no degraded sections on a fully-keyed environment. | Audit runs |
| S5 | **Isolation proof.** An adversarial test attempts cross-tenant reads on every table and fails on all of them. | `rls_gate` CI job |
| S6 | **Truth proof.** With every provider key removed, the system displays no number that is not labelled degraded, anywhere. | `keyless_smoke` CI job |
| S7 | **Recovery proof.** Kill the worker mid-run on each of the eight long-running job types; every one resumes or dead-letters correctly, none double-spends. | Chaos suite |
| S8 | **Restore proof.** A full restore from backup into a clean host, verified by a data-integrity check. | Quarterly drill, once before hand-over |

---

## 7. Fixed constraints

| Constraint | Value | Consequence |
|---|---|---|
| **Scale** | 50–100 clients now; architected to ~500 without redesign | Per-client concurrency caps, server-side pagination everywhere, pre-aggregated rollups |
| **Environments** | `app.qanry.com` is the **only** deployed environment | A staging profile must exist in compose and CI must be able to stand the full stack up ephemerally, because there is no second host to test on |
| **Rankings sources** | DataForSEO for organic rank · serper.dev for local pack and geo-grid | Never mixed in one series; every rank value carries its source |
| **Content QA gate** | Advisory with mandatory acknowledgement until calibrated on ≥30 human-graded drafts, then hard at the calibrated threshold | The gate ships switchable, with the calibration set as a first-class artefact |
| **Citation aggregators** | Out. Yext / Data Axle / Apify submission paths are not built | The extension is the only submission route |
| **Submit action** | A human presses submit, always | The agent may fill, verify and stage; it may not transmit |
| **Design fidelity** | Same design system, new composition — not pixel replication | Tokens and component grammar are extracted; layout is composed fresh |
| **Publish output** | Genuinely editable Elementor block tree | Styled-HTML-in-a-widget is an explicit failure |
| **AI runtime** | LangGraph for Content, Citations and Web 2.0; LangSmith tracing across all | Other paths use the model router directly but still emit traces |
| **Model routing** | Direct Anthropic key preferred; agentrouter.org supported as a configured fallback | The router is an abstraction with two backends, chosen by config, never by code |
| **Deadline** | None imposed. Quality is the constraint. | Milestones are exit-criteria based, not date based |

---

## 8. What changed from v1 — the short list

| v1 | v2 |
|---|---|
| Sheets-as-store, then Postgres, then both | **Postgres only.** Sheets is an export format, never a store |
| Celery + Redis with an empty beat schedule and no job contract | **Postgres-backed durable job engine** with idempotency, leases, retry, DLQ; Redis is cache and locks only |
| Direct model calls scattered across 40 services | **One model router + LangGraph agents** with checkpointed state |
| Design capture that ends in a styled HTML wrap | **DesignIR → Elementor block tree** with a round-trip fidelity test |
| Citation DOM specs hand-maintained per directory | **Structural fingerprint + AI field mapping with a learned cache**, plus account creation |
| Web 2.0 through house accounts and scrapers | **32 platforms, official APIs, per-client identity on anything that matters** |
| `status="done"` on a publish that published nothing | **Honest terminal states**, enforced by test |
| Synthetic providers reachable in production | **Degrade-only**, enforced by CI gate |
