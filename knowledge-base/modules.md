# Modules

Every module, what it does, the DB tables it owns (+ migration), its API namespace under
`/api/v1`, its cost dial (see `cost-and-dials.md`), and the provider key that lights it up
(see `apis-and-keys.md`). Grounded in `backend/app/modules/*`, `backend/app/routers/*`,
`db/migrations/*`, and the module docs. Where a module degrades without a key, that is the
default state today — keys are deferred.

## Platform kernel (Parts 1–6 — always on, no external key)

| Module | Does | Tables (migration) | API |
|---|---|---|---|
| **Auth + RBAC** | Local EdDSA login; 6 staff roles + `client`; 17-feature matrix; owner-only provisioning. No public signup. | `auth.users`, `public.users`, `user_feature_grants` (`0002`, `0016`); `client` role (`0009`) | `/auth`, `/rbac` |
| **Clients + Sites** | The agency's customers and their domains; WordPress creds sealed per-site. NAP/business profile at creation. | `clients`, `sites` (`0003`); `client_business_profile` (`0051`) | `/clients` |
| **Key Vault** | Agency + per-client secrets sealed app-layer with AES-256-GCM under `VAULT_MASTER_KEY`; masked list, owner-only reveal. | `vault_secrets` (`0004`, `0041` adds `kind`) | `/vault` |
| **Activity log** | Append-only audit trail; every mutation records one; feeds the Context memory. | `activity_log` (`0005`) | `/activity` |
| **Cost / money-dial** | The spend spine: dial → cache → client cap → daily spend-stop → call+log. | `cost_dials`, `budgets`, `cost_log` (`0006`, `0044` numeric) | `/cost` |
| **Service tiers** | Delivery tier (free/semi/fully) separate from subscription tier; gates paid audit types. | delivery tier (`0007`) | `/tiers` |
| **Context / AI-memory** | Per-entity living summary + keyed facts + vector index, kept fresh from the activity log; the one door the AI reads for current state. | `context_dirty` (`0013`), `entity_context` + `context_vectors` (`0014`) | `/context`, `/portal/context` |

Context degrades without `ANTHROPIC_API_KEY` + `EMBEDDINGS_API_KEY` (Voyage) +
`PINECONE_API_KEY`/`PINECONE_INDEX`; dials **`context`** + **`context_embed`**. Freshness:
`lag = max(latest_seq − event_watermark, 0)` via `GET /context/{type}/{id}/health`. Full:
`backend/docs/CONTEXT-MODULE.md`.

## Module 01 — Audit

Wraps the **external** `audit_engine` (a separate product at
`../danyals-audit-system`, invoked as a subprocess) as a cloud job. A user triggers a
URL audit (Free/Paid, type-selectable: on-page / technical / off-page / local / GEO);
a worker runs the engine and saves findings JSON + a branded PDF. Free vs Paid gates which
paid providers may run. Every finding carries evidence — no invented metrics.

- Tables: `audits` (`0008`); public/free audits (`0015`); audit overlay (`0027`).
- API: `/audits`, `/audits/{id}` (+ `/findings.json`, `/report.pdf`, `/stats`),
  `/public` (free lead audit), `/portal/audits` (client's own).
- Dial: **`tech_audit`** (DataForSEO live crawl/rank), **`cwv`** (PageSpeed, free tier).
- Skills: `.claude/skills/audit`, `technical-audit`, `local-audit`, `geo-audit`.

## Module 02 — Content (the crown jewel)

A content job runs an ~90%-automated pipeline (`queued → drafting → needs_review →
publishing → done`, + `failed`/`rejected`) with **one** human review gate. It researches
the SERP (top-10 teardown), drafts a ranking-grade page against `CONTENT-DOCTRINE.md`,
builds JSON-LD, generates images, and scores a **14-dimension QA scorecard**. The QA §11
gate is a **hard publish gate** (no dimension < 70, weighted total ≥ 85) re-checked at
publish. The 3-actor lifecycle (worker / lead / non-lead) is enforced by the
`content_jobs_guard_update` **trigger** (invariant #12), not FastAPI.

- Tables: `content_jobs` (`0017`); GBP-post extension (`0049`).
- API: `/content/jobs` (create=`publish_content`), `/content/jobs/{code}` +
  `/{draft|keywords|qa|schema}`, `/content/jobs/{code}/review` (LEAD approve/edit/reject),
  `/content/jobs/stats`.
- Dial: **`content`** (Claude drafting + images), **`content_research`** (Serper SERP).
  Degrades to a `drafting` hold at honest $0 without `ANTHROPIC_API_KEY`.
- Skills: `content`, `blog-post`, `local-service-page`, `titles-meta`.
- Full: `backend/docs/CONTENT-MODULE.md`, `backend/docs/CONTENT-DOCTRINE.md`.

## Module 03 — Off-page (backlinks · citations · Web 2.0)

Monitors the backlink/referring-domain profile, reconciles citation/NAP listings, and
runs the Web 2.0 property pipeline. **Publishing/submission is human-gated**: a lead
approves a Web2 property before it goes live; citation submission runs real CAPTCHA +
proxy spend. Every off-page query is pinned to the client's own profile
(`competitor_id is null`) so a rival's links never appear as the client's.

- Tables: `backlinks`, `citations` (`0018`); web2 publish (`0028`); citation+web2
  automation + directories seed/strategy (`0045`, `0046`, `0048`).
- API: `/offpage/kpis`, `/offpage/backlinks` (+ `/flag-toxic`), `/offpage/citations`
  (+ `/action`, `/bulk`), `/offpage/web2` (+ `/plan`, `/{id}/approve`),
  `/citation-builder/*` (business profiles, directories, campaigns).
- Dial: **`backlinks`** (monitoring + Web2 publish, default byhand), **`citations`**
  (auto-submit, CAPTCHA+proxy spend, default api).
- Keys: `SERPER_API_KEY`; Web2 house creds (`WEB2_HOUSE_CREDENTIALS_JSON` + per-client
  vault `web2:<Platform>`); citations `BING_PLACES_API_KEY`/`FOURSQUARE_API_KEY`/
  `CAPTCHA_SOLVER_API_KEY`/proxy/`APIFY_*`. Full: `backend/docs/CITATIONS-WEB2-CREDENTIALS.md`.
- Skills: `offpage`, `backlink-audit`, `citation-builder`, `citation-submit`, `web2-build`.

## Module 04 — Policy Radar (mandatory core)

An always-on watcher that diffs official Google policy/algorithm sources, distils each
change into a KB entry + recommendation (Claude Haiku), and surfaces it in the **Command
Center**. Closed loop: a recommendation can propose an **audit overlay** — Radar writes an
overlay only, it never mutates the audit engine or a stored audit. Every entry cites its
source; recommendations are human-confirmed before they change anything.

- Tables: policy sources/kb/change-events/recommendations (`0019`, seed `0050`); audit
  overlay (`0027`).
- API: `/policy/*`, `/command-center`.
- Dial: **`policy`** (change analysis, Claude Haiku; degrades without `ANTHROPIC_API_KEY`).
- Skills: `policy-radar`, `policy-brief`.

## Delivery + ops modules (Part 7)

| Module | Does | Tables (migration) | API | Dial / key |
|---|---|---|---|---|
| **Reports (Sheets)** | Push audit/content/milestone data to Google Sheets; a Redis write-buffer; client report grants. | reports + SheetStore (`0020`); client report grants (`0031`); client deliverables (`0032`) | `/reports`, `/portal/reports`, `/portal/deliverables` | `GOOGLE_SHEETS_SA_JSON` (degrades to no-op) |
| **Milestones** | Five-stage delivery timeline per engagement, auto-advanced from delivery events. | milestones (`0021`); portal views (`0034`) | `/milestones`, `/portal/milestones` | — |
| **Upsells** | Agency-global Fiverr-gig cards shown in the client portal. | upsells (`0022`) | `/upsells` | — |
| **Notifications / Email** | In-app + email (Resend) + Slack alerts; per-user prefs. | notifications (`0023`) | `/notifications` | `RESEND_API_KEY`, `SLACK_WEBHOOK_URL` |
| **Tickets** | Support tickets; client portal requests. | tickets (`0024`); portal support (`0033`) | `/tickets`, `/portal/requests` | — |
| **Settings** | Agency name, per-user notification prefs, access/roles. | settings (`0025`) | `/settings` | — |
| **Backups** | Off-site Postgres backups to Backblaze B2. | backups (`0026`) | `/backups` | `B2_KEY_ID` + `B2_APPLICATION_KEY` + `B2_BUCKET` |
| **Team + Tasks** | Task queue (`J-####`), board, review checkpoint; lifecycle enforced by the `tasks_guard_update` trigger; live team metrics. | tasks (`0011`, `0012`); member onboarding flags (`0029`) | `/tasks`, `/team`, `/me` | — |

Skills: `report`, `monthly-report`, `sheets-sync`, `rank-report`, `milestones`,
`upsells`, `team-status`, `assign-task`, `client-snapshot`.

## Tool modules (Part 8 — `app/modules/*`)

Each is a self-contained package; each paid one is gated by its own dial. **Known
limitations are documented in `backend/CLAUDE.md`** (e.g. `keywords.winnable` is a
neutral-DA screen, competitor backlink-gap returns an empty set) — do not assume more.

| Module | Does | Tables (migration) | API | Dial / key |
|---|---|---|---|---|
| **keyword_research** | SERP keyword + intent research, clusters, cannibalization. | (`0035`) | `/keyword-research` | **`keywords`** (Serper; default off) + DataForSEO metrics |
| **rank_tracker** | Nightly rank tracking — the first STANDING per-client cost; client pays; prices the monthly commitment before subscribe. | (`0036`) | `/rank-tracker` | **`rank_tracker`** (default off) |
| **competitor_intel** | Track rivals, share-of-voice, content gaps. | (`0037`) | `/competitor-intel` | **`competitor_intel`** (Serper) |
| **on_page** | On-page analysis → recommendations → apply to live WordPress. | (`0038`) | `/on-page` | **`on_page`**; WordPress per-site vault |
| **local_seo** | GBP + map-pack / local-pack lookups. | (`0039`, 3 tables) | `/local-seo` | **`local_seo`** (Places; default byhand) |
| **client_onboarding** | Onboarding runs/steps; seals credentials into the vault. | (`0040`, `0041`) | `/client-onboarding` | — |
| **data_import** | Column-mapped CSV import (Fiverr client data); commits rows. | (`0042`) | `/data-import` | — |
| **billing** | Invoice ledger (draft→open→paid). | (`0043`) | `/billing` | — |
| **gmb** | Google Business Profile post drafting (Claude), operator-reviewed. | GBP posts (`0053`) | `/gmb` | **`gmb`** (Anthropic; default byhand) |
| **site_analytics** | GSC / GA4 file-import (no live GSC/GA scraping). | (`0047`) | `/site-analytics` | **`site_analytics`**; `GOOGLE_OAUTH_*` |
| **tool_workspaces** | Read-only `/workspace` adapters so all 17 `tools.ts` slugs are backed. | — | `/workspace` | — |

Skills: `keyword-research`, `competitor-intel`, `on-page-fix`, `local-seo`,
`onboard-client`, `data-import`, `billing`.

## The AI/skills surface (Part 9)

- **Skills gateway** — scoped per-client sha256 skill tokens; cost-gated MCP dispatch.
  Tables: `skill_tokens` (`0030`). API: `/skills`.
- **In-product AI** — `POST /ai/assist` (dial **`ai_assist`**, Claude). Routes/summarizes;
  the module engines do the heavy work.
