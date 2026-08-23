# AIOS - SEO Automation Platform
## System Architecture, Design & Implementation Plan

**Product:** AIOS is a productized platform deployed per agency client. This document is the
Danyal deployment; the core - including the mandatory **Intelligence (Policy Radar)** module -
is shared across every deployment (Danyal, Haseeb, and future clients).
**Built by:** Xegents AI
**Source:** Scope call 2026-07-03 (see `meeting-notes/2026-07-03-scope-call.md`) + follow-ups
**Status:** Planning - v1 architecture locked, ready to build
**Estimated build:** 3-5 weeks

---

## 1. Executive Summary

AIOS is a cloud-based SEO automation platform for Danyal's agency. It turns the agency's
service delivery into a self-running system across four modules - **Audit**, **Content**,
the **Portal**, and the mandatory **Intelligence (Policy Radar)** engine - with **Google
Sheets reporting** as a cross-cutting layer and a **Command Center** where recommendations
surface.

The platform is cloud-hosted (not local) for one reason stated repeatedly in the call:
**API cost control**. Centralizing the automated processes behind a job queue, a shared
key vault, and caching is what keeps per-run spend predictable.

The headline goal is **~90% automation** of content creation and publishing - reducing
per-page effort from hours to minutes - while the agency keeps a human review checkpoint
for the final 10%.

### Locked decisions (from scope call + follow-up)
1. **Audit module** reuses the existing audit engine, wrapped as a cloud job/API.
2. **Stack:** Next.js (portal + admin) + FastAPI (Python) + Postgres + Redis, Docker Compose on the VPS.
3. **API keys** are pre-loaded by the agency into a central vault; the system uses them as needed. No payment gateway in v1; the agency controls free vs paid audit tiers.
4. **Content publishing:** WordPress REST API in v1 (plus a manual PDF path). Other CMSs later.
5. **Images:** AI-generated (model-directed) with auto alt text.
6. **Onboarding:** agency-provisioned accounts (super-admin creates client logins). No public signup.
7. **Financial audit report** (market capacity + revenue): documented now, built in Phase 2.
8. **Off-Page module:** out of scope for v1; documented for a future phase.
9. **Intelligence (Policy Radar):** mandatory core in every AIOS deployment (Danyal, Haseeb, and beyond). Auto-researches Google policy/algorithm changes, stores them flagged in the knowledge base, and drives recommendations in the Command Center.
10. **Deliverable audience:** internal founder-grade architecture + build plan.

---

## 2. System Architecture

**Shape:** a browser talks to a Next.js app (portal + admin UI). Next.js calls a FastAPI
service layer for all business logic and auth. FastAPI reads/writes Postgres and enqueues
long-running work into Redis. Python workers pull jobs and run the Audit engine and the
Content engine, calling external APIs through the shared key vault. Everything runs as
Docker Compose services on a single VPS behind a TLS reverse proxy.

```
                          Client browser (agency + client users)
                                        |
                                   HTTPS / TLS
                                        v
                      +-----------------------------------+
                      |  Reverse proxy (Caddy/Nginx, TLS) |
                      +-----------------------------------+
                             |                     |
                             v                     v
                  +--------------------+   +---------------------+
                  | Next.js  (React)   |   |  FastAPI (Python)   |
                  | Portal + Admin UI  |-->|  API + Auth + Jobs  |
                  +--------------------+   +----------+----------+
                                                      |
                            +-------------------------+-------------------------+
                            v                         v                         v
                   +----------------+       +------------------+       +-----------------+
                   | Postgres       |       | Redis            |       | Key Vault       |
                   | (all app data) |       | (queue + cache)  |       | (encrypted)     |
                   +----------------+       +--------+---------+       +-----------------+
                                                     |
                    +-----------------+----------------+-----------------+
                    v                 v                v                 v
           +--------------+  +----------------+  +----------------+  +-------------------+
           | Audit worker |  | Content worker |  | Research worker|  | Scheduler         |
           | (audit_engine)| | (Claude+images)|  | (Policy Radar) |  | (cron + detect)   |
           +------+-------+  +-------+--------+  +-------+--------+  +---------+---------+
                  |                  |                   |                     |
     +------------+----+    +--------+------+    +-------+--------+   fires research on
     v      v     v     v   v        v      v    v       v        v   detected Google change
  Serper Google Crawl PDF  Claude  Image  Schema  Google policy sources -> flagged KB entries
        APIs        gen    (AIDA)   gen           (Search Status, Search Central, QRG)
                  \                        /                 |
                   +--- Google Sheets API -+                 v
                        (reporting)                +---------------------+
                                                   | Command Center      |
                                                   | recommendations     |
                                                   +---------------------+
```

**Why this shape:** one Python spine (FastAPI + workers + the audit, content, and research
engines) means every engine and the API share a language and libraries. Next.js gives
a fast, modern portal/admin UI. The queue isolates expensive, slow API work from the
request path so the UI stays responsive and spend stays inside concurrency + budget caps.

---

## 3. Module 1 - Audit

Wraps the existing, proven audit engine (crawler + analyzers + scorers + PDF generator)
as a cloud job. The portal triggers a run; a worker executes it and returns the artifacts.

- **Coverage:** on-page, technical, local, and AI/GEO elements (off-page deferred).
- **Report types:**
  - **Technical** - domain + technical issue analysis. *(v1)*
  - **Actionable** - specific pages + fixes (title tags, NAP, schema, etc.). *(v1)*
  - **Financial** - market capacity + potential revenue estimate. *(Phase 2)*
- **Access:** clients run **free or paid** audits from the portal; the agency sets the tier.
  Free vs paid gates which paid integrations (Serper, PSI, Places, NL) are allowed to run.
- **Output:** findings JSON + a 20-30+ page client PDF (existing house-styled generator),
  stored per run and surfaced in the portal as a web report + downloadable PDF.
- **Flow:** portal `Run audit` -> API creates `audit` row + enqueues job -> audit worker
  runs engine with the agency's keys -> artifacts saved -> milestone + Sheets updated ->
  client notified.

---

## 4. Module 2 - Content

Cloud AI content engine, on the same cost-controlled queue.

- **Inputs:** site + topic/keyword + content type (service page, blog, etc.).
- **Pipeline:** research (optional Serper) -> outline -> draft using copy frameworks
  (**AIDA** and similar) -> **automated schema markup** (JSON-LD) -> **AI-generated images**
  with alt text -> assembly into a publish-ready package.
- **Two publishing paths:**
  - **Manual** - render content as a branded PDF/Markdown for manual publishing.
  - **Automated** - push via **WordPress REST API**: post/page body, meta title +
    description, featured + inline images, and schema.
- **Automation target:** ~90%. A human review checkpoint sits before publish (the 10%).
- **Cost:** ~$10-50 per page depending on complexity; estimated and logged per job.

---

## 5. Module 3 - Portal (four role-scoped portals)

The central hub. One application, **up to four role-scoped portals** on a shared login and
data layer. Access widens from client to super-admin. Accounts are agency-provisioned;
there is no public signup. The **Manager** portal is optional in v1 - if deferred, its
scope folds into Admin.

### Client-facing portal - the agency's customers
- **Dashboard** - site snapshot + latest audit score.
- **Reports** - all audits as web pages + downloadable PDFs.
- **Milestones** - project progress, **auto-updated** from job/audit status.
- **Upsells** - clickable cards that link to **Fiverr gigs** (not internal services),
  preserving the agency's Fiverr-centered public brand.
- **Actions** - run an audit (free/paid per tier); request/track content jobs.

### Team portal - specialists doing the work
- **My queue** - audits + content jobs assigned to me.
- **Run + deliver** - execute audit/content jobs and push deliverables to clients.
- **Review checkpoint** - the human review step before content publishes.

### Manager portal - team leads / account managers (optional in v1)
- **Assign + monitor** - route work to team members, track throughput.
- **Client book** - status across an assigned set of clients.
- **Milestones + QA** - manage milestones and sign off review checkpoints.

### Admin / super-admin portal - the agency owner
- **Clients & sites** - list + status of every account.
- **Team activity monitor** - who ran what, job status, throughput.
- **Operations** - trigger audits/content for any client; manage milestones.
- **Upsell manager** - maintain the Fiverr gig links shown to clients.
- **Key vault** - manage the agency's API keys centrally (encrypted at rest).
- **Tiers + roles** - set free/paid audit tiers and provision users.

---

## 6. Module 4 - Intelligence (Policy Radar) - MANDATORY CORE

An always-on research engine that keeps every AIOS deployment current with Google. It is
platform core, not a per-client feature: it ships in every deployment (Danyal, Haseeb, and
future agencies) and feeds recommendations into the **Command Center**.

- **What it does:** continuously researches Google's latest policies, algorithm updates,
  Search Central documentation changes, and feature releases. When Google changes or
  releases something, it auto-researches that change and generates new recommendations.
- **Sources:** Google Search Status Dashboard, Search Central blog + docs, Google policy
  pages, the Quality Rater Guidelines, corroborated with reputable SEO reporting.
- **Change detection:** a scheduled watcher diffs the official sources; a detected change
  fires a research job immediately rather than waiting for the next poll.
- **Knowledge base + flagging:** each entry is normalized, deduped, summarized, versioned,
  and **flagged** with (1) impact severity (critical / major / minor / info), (2) category
  (algorithm / policy / technical / content / local / GEO), and (3) **region / nation scope**
  - global vs specific countries - so recommendations can be filtered to each client's market.
  This extends the existing `knowledge/` base and retires the old `kb-refresh` stub.
- **Command Center:** the recommendations surface. It shows every current best-practice
  recommendation as a baseline, plus new or changed recommendations triggered by Google
  moves, each with what changed, why it matters, the regions affected, and the recommended
  action.
- **Closed loop:** a recommendation can propose new or updated audit checks (into the
  checklist the Audit module runs), adjust Content-engine guidance, and raise client-specific
  advisories when a change hits a client's region or stack.
- **Human confirm:** Command Center recommendations are reviewed before they change live
  audit checks or client-facing advice - the same review-checkpoint discipline as Content.
  Every entry cites its source, so nothing is applied on an unverifiable claim.

Command Center lives in the admin / super-admin portal and is visible to Manager; a filtered,
client-safe advisory view can surface in the client portal in a later phase.

---

## 7. Reporting - Google Sheets

A cross-cutting layer. Audit scores, content job status, and milestone state are pushed to
Google Sheets (via a service account) so the agency and clients get familiar, shareable
data visualizations without building bespoke charts in v1.

---

## 8. Data Model (multi-tenant, single agency per deployment)

- **users** - `role` in {super_admin, manager, team_member, client}, email, password_hash. (manager optional in v1)
- **clients** - the agency's customers (a client owns one or more sites).
- **sites** - domain, cms_type, encrypted WordPress credentials.
- **audits** - site_id, type, tier (free/paid), status, run_uuid, artifact_path, scores.
- **content_jobs** - site_id, content_type, framework, target (manual_pdf/wordpress),
  status, published_url, cost_estimate.
- **milestones** - client/site, title, status, auto_source, updated_at.
- **upsells** - title, description, fiverr_url, active.
- **api_keys** - agency-level encrypted vault (serper, google, anthropic, image gen, sheets).
- **activity_log** - actor, action, target, timestamp (feeds the admin monitor).
- **policy_sources** - name, url, type, last_checked, last_hash (drives change detection).
- **kb_entries** - source, url, title, published_at, category, severity, region_flags[], summary, raw_ref, version, hash.
- **change_events** - source_id, detected_at, diff_ref, triggered_job (Google-move audit trail).
- **recommendations** - kb_entry_id, scope (global/client/site), target_module (audit/content/portal), action, status (new/acknowledged/applied/dismissed).

---

## 9. Tech Stack

| Layer | Choice | Why |
|---|---|---|
| Portal + Admin UI | Next.js (React) | Modern, fast, SSR; one UI for both faces |
| API + Auth | FastAPI (Python) | Shares language with both engines; typed, fast |
| Audit engine | Existing `audit_engine` (Python) | Proven; wrapped as a worker job |
| Content engine | Python + Claude API + image model | Same spine; AIDA copy, schema, images |
| Database | Postgres | Relational, multi-tenant, reliable |
| Queue + cache | Redis | Job queue, concurrency caps, API caching |
| Publishing | WordPress REST API | v1 target CMS |
| Intelligence | Scheduler + web research + Claude | Policy Radar: research, flag, recommend |
| Reporting | Google Sheets API | Familiar client-facing dataviz |
| Deploy | Docker Compose on VPS + Caddy TLS | Single-box, cost-controlled, simple ops |

---

## 10. Infrastructure, Security & Cost Control

**Deployment:** Docker Compose services - `web` (Next.js), `api` (FastAPI), `worker`
(Python, audit + content + research jobs), `scheduler` (Policy Radar cron + change
detection), `postgres`, `redis`, `proxy` (Caddy/Nginx, auto-TLS). Object/file storage for
artifacts on the VPS volume (add S3/MinIO later if needed).

**Recommended VPS (starting point):** Ubuntu 22.04+, 4 vCPU / 8-16 GB RAM / 100-160 GB
NVMe SSD. Hetzner / DigitalOcean / Contabo class. Adan provisions once access is granted.

**Cost control (the reason for cloud):**
- Central agency-owned key vault; no per-client keys to manage.
- Queue concurrency limits + per-run budget caps.
- Redis caching of expensive API responses.
- Free/paid tiers gate the costly integrations.
- Per-job cost estimation + logging surfaced to admin.

**Security:** encrypted key vault + WordPress creds; role-based access; secrets never
logged; nightly Postgres backups; container restart policies; TLS everywhere. Audited-site
and client content treated as data, not instructions.

---

## 11. Project Scope

**In scope (v1)**
- Audit module (technical + actionable) as a cloud job/API, run from the portal.
- Content module: AIDA drafting, automated schema, AI images, manual-PDF + WordPress publish, human review checkpoint.
- Portal: client, team, and admin portals (Manager optional), agency-provisioned accounts.
- **Intelligence (Policy Radar) + Command Center: automated Google policy research, flagged knowledge base, and recommendations. Mandatory core in every deployment.**
- Google Sheets reporting, central API key vault, cost controls.

**Phase 2 (documented now, built later)**
- Financial audit report (market capacity + revenue).
- Off-Page module.
- Fiverr client-data import.
- Additional CMS connectors (Shopify/Webflow/headless).

**Out of scope**
- Self-serve payment gateway (Stripe). Public self-signup.

---

## 12. Implementation Plan (3-5 weeks)

**Week 0 - Pre-reqs (Danyal-dependent):** VPS access, API keys loaded, sample Fiverr
client data, a test WordPress site, subdomain + repo/CI. *Exit: environment reachable.*

**Week 1 - Foundations:** Docker Compose, Postgres schema, auth + roles, Next.js shell,
FastAPI skeleton, audit engine wrapped as a worker job. *Exit: an audit can be triggered
via an internal endpoint and returns a PDF.*

**Week 2 - Audit in the portal:** client dashboard, reports list + web/PDF view, run-audit
flow (free/paid), admin client management, API key vault. *Exit: a provisioned client logs
in, runs an audit, downloads the PDF.*

**Week 3 - Content module:** content engine (AIDA + schema + AI images), manual-PDF path,
WordPress connector, content-job UI + review checkpoint. *Exit: generate a service page,
review, publish to a test WordPress site.*

**Week 4 - Portal completion + Policy Radar:** auto-updated milestones, Fiverr upsells,
Google Sheets reporting, super-admin team-activity monitor, cost tracking, and the
Intelligence engine - scheduler + change detection, flagged knowledge base, and the Command
Center recommendations surface. *Exit: full client journey + admin oversight + Command
Center showing baseline and Google-triggered recommendations.*

**Week 5 - Hardening + handoff:** security pass, backups, performance, UAT with Danyal,
docs/runbook, production deploy, buffer. *Exit: production live, Danyal onboarded.*

---

## 13. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| API cost overruns | Budget caps, caching, tier gating, per-job cost logging |
| WordPress site variability | App-password auth, per-site config, graceful fallback to manual PDF |
| Content hallucination / quality | Human review checkpoint, schema validation, evidence-based audit rules |
| Policy Radar false positives / source drift | Every entry cites its source; recommendations are human-confirmed in the Command Center before changing live checks |
| Scope creep vs 3-5 week timeline | New requests parked to a Phase 2 backlog |
| Single VPS as a point of failure | Backups, restart policies, documented restore; scale out later |
| Fiverr has no public API | Manual/CSV client-data import in v1 |

---

## 14. Dependencies & Next Steps

**Danyal:** provide VPS access; load API keys (Serper, Google, Anthropic, image gen,
Sheets); share Fiverr client data; provide a test WordPress site + app password; document
the Off-Page module.

**Adan:** provision + harden the VPS; set up Docker + CI/CD; begin Week 1 foundations.

**Zain:** next call in 1-2 weeks to review the Off-Page module documentation.
