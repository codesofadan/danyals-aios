# REQUIREMENTS TRACEABILITY MATRIX — Daniel Project Recovery

**Companion to** `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md`
**Compiled:** 2026-08-23

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


Every major requirement carries: **ID · REQUIREMENT · SOURCE · EVIDENCE CLASS · PRIORITY · DEPENDENCIES · ACCEPTANCE CRITERIA · OPEN QUESTIONS**.

**Priority:** P0 blocks acceptance · P1 required for v1 · P2 required for quality · P3 desirable.
**Class:** CONF = confirmed · SI = strong inference · PROP = proposed · CONFL = conflicting · UNK = unknown.
**Source keys** are defined in the specification's "How to read this document".

---

## ADM — ADMIN PORTAL

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| ADM-001 | Dashboard shows only live metrics; no hardcoded value anywhere, including costs | `[OVERHAUL]` §C | CONF | P0 | ADM-025, all modules | Every tile traced to a live query; a grep for hardcoded metrics returns nothing; a module outage shows "unavailable", never 0 | — |
| ADM-002 | Admin header carries no marketing subtitle | `[OVERHAUL]` §C | CONF | P3 | — | Subtitle absent | — |
| ADM-003 | Every rendered control performs a real action or is not rendered | `[OVERHAUL]` §F; commit `79d1036` | CONF | P0 | ADM-018, ADM-020 | Click-through audit of every control in admin, team and client; zero dead controls | — |
| ADM-004 | A feature must run real work, not describe itself | `[OVERHAUL]` §F | CONF | P0 | per-module | Each Features-page entry demonstrably executes its job on real data | — |
| ADM-005 | Provision users: name, email, role template, per-feature overrides, in one transaction | `[CODE]`, `[PACK-JUL]` | CONF | P1 | SEC-001, ADM-030 | New member signs in under 60s and sees exactly the enabled features | — |
| ADM-006 | Invites either genuinely send via Resend or the invite control is removed | `[OVERHAUL]` §L | CONF | P1 | INT-020 | Invite delivered end-to-end, or control absent | — |
| ADM-007 | Credentials shown once with copy buttons | `[OVERHAUL]` §L | CONF | P2 | ADM-005 | Copy button works; credential not re-displayable | — |
| ADM-008 | Client create/update/delete | `[OVERHAUL]` §L | CONF | P1 | DATA-002 | CRUD complete; delete is guarded and lists live artefacts before proceeding | — |
| ADM-009 | Collect the full business profile + NAP at client creation (~20 fields), feeding Citations, Local and Content | `[OVERHAUL]` §K/§L; `[RESEARCH-AUG]` | CONF | P0 | DATA-002, CIT-002 | Citations never again reports "no business profile"; every field reused downstream without re-entry | Q-8 |
| ADM-010 | One business profile **per location** for multi-location clients | `[CIT-CRED]` §7 | CONF | P1 | DATA-010 | A two-location client produces two profiles, two citation sets, two GBP records | Q-8 / D-9 |
| ADM-011 | Site connection with sealed credentials and capability discovery | `[RESEARCH-AUG]`; `[CODE]` | CONF | P0 | WP-001…WP-008 | Connection test names, in plain language, exactly which publishing capabilities this site supports | Q-15 |
| ADM-012 | Audit start asks which types; none selected = run all | `[OVERHAUL]` §H | CONF | P1 | AUD-005 | Selecting one runs only that; selecting none runs all | — |
| ADM-013 | Audit filters mirror the audit types | `[OVERHAUL]` §H | CONF | P2 | ADM-012 | Filter set equals type set | — |
| ADM-014 | Remove the "Audit Coverage" section | `[OVERHAUL]` §H | CONF | P3 | — | Section absent | — |
| ADM-015 | Free-audit page shows Danyal's real Fiverr gigs, not demo gigs | `[OVERHAUL]` §G | CONF | P0 | ADM-036 | Live gig URLs verified working | D-7 |
| ADM-016 | Remove the "Focus Areas" field; always audit everything | `[OVERHAUL]` §G | CONF | P2 | AUD-001 | Field absent; every free run is comprehensive | — |
| ADM-017 | Content wizard, review, edit and publish surfaces are complete and functional | `[OVERHAUL]` §I; `[CODE]` | CONF | P0 | CONT-* | A specialist completes brief→publish without leaving the dashboard | — |
| ADM-018 | Citations flow fixed; submit no longer fails | `[OVERHAUL]` §K | CONF | P0 | CIT-* | 50 citations across 10 businesses submitted, with proof | D-2 |
| ADM-019 | Web 2.0 status board: connected vs missing per platform, with honest fault attribution | `[OVERHAUL]` §K | CONF | P1 | WEB2-012 | Each platform shows connected/missing + reason + whose fault | D-5 |
| ADM-020 | Reports use real cron-driven data; no demo info | `[OVERHAUL]` §N | CONF | P0 | AUTO-001, AUTO-018 | Every figure traced to a completed job | — |
| ADM-021 | Reports surface shows which cron jobs exist, what they do, when scheduled, last run, last status | `[OVERHAUL]` §N | CONF | P1 | AUTO-007 | Operator can answer "what will run in 24h" from one screen | — |
| ADM-022 | Remove the Upsells section from Reports | `[OVERHAUL]` §N | CONFL | P3 | ADM-036 | Per owner decision | D-7 |
| ADM-023 | Remove the "Rotate Key" option | `[OVERHAUL]` §O | CONF | P3 | — | Control absent | — |
| ADM-024 | API management shows every connected API **and every missing one**, with the consequence of each absence | `[OVERHAUL]` §O | CONF | P1 | INT-001 | For each missing key: which capability is degraded and to what state | — |
| ADM-025 | Cost is computed at runtime only; no predefined or hardcoded price anywhere | `[OVERHAUL]` §E | CONF | P0 | AUTO-009, DATA-020 | The $1.50 audit estimate and every hardcoded cost removed; a grep finds none | — |
| ADM-026 | When provider spend is halted, **every** API stops — internal and external | `[OVERHAUL]` §E | CONF | P0 | AUTO-009 | With the stop armed, a negative test proves no provider is reachable | — |
| ADM-027 | Provider toggles, manual mode and API mode actually work | `[OVERHAUL]` §E | CONF | P0 | ADM-025 | Each dial position demonstrably changes behaviour | — |
| ADM-028 | Settings: remove Two-Factor Auth, Change Password, Security, Workspace | `[OVERHAUL]` §P | CONF | P3 | SEC-001 | Tabs absent | D-8 |
| ADM-029 | Settings: keep Client Access, Team Access, Roles, Permissions — showing only implemented features | `[OVERHAUL]` §P | CONF | P2 | ADM-030 | No unimplemented feature listed | — |
| ADM-030 | 17-feature permission matrix with per-person overrides over 6 roles and 4 templates | `[PACK-JUL]`; `[CODE]` | CONF | P1 | SEC-002 | Matrix in §9 enforced; negative test per boundary | Q-9 |
| ADM-031 | Key vault: agency-wide and per-client scopes, masked list, owner-only reveal | `[CODE]`; `[CIT-CRED]` | CONF | P0 | SEC-003 | Non-owner reveal returns 403; secret never in a log or a response | Q-18 |
| ADM-032 | Append-only activity log entry per mutation | `[KB]`; `[CODE]` | CONF | P1 | DATA-021 | Every mutation produces exactly one entry; no path bypasses it | — |
| ADM-033 | Backups: nightly, restore with confirmation, off-site | `[KB]` | CONF | P1 | AUTO-025, OPS-021 | A restore is performed and verified | — |
| ADM-034 | Command Center: Acknowledge / Apply / Dismiss per recommendation | `[ARCH]` §6 | CONF | P1 | AI-004 | Applying writes an audit overlay only, never mutating the engine or a stored audit | — |
| ADM-035 | Delivery tier per client (free/semi/fully), gating paid audit types | `[PACK-JUL]`; `[CODE]` | CONF | P1 | ADM-025 | A free-tier client cannot start a paid audit; enforced server-side | — |
| ADM-036 | Upsell manager: add, reorder, activate Fiverr cards | `[SCOPE-CALL]`; `[ARCH]` | CONF | P2 | — | Cards render in the client portal and link out correctly | D-7 |
| ADM-037 | Milestones auto-advanced from delivery events; never hand-edited | `[SCOPE-CALL]`; `[KB]` | CONF | P1 | AUTO-021 | Completing an audit advances the milestone with no human action | — |
| ADM-038 | Approval queue unified across content, Web 2.0, citations, GBP, reports and policy | `[CODE]` partial | PROP | P1 | all gated modules | A lead sees every pending approval in one place | — |
| ADM-039 | Server-side pagination, search and bulk selection on every list | scale | PROP | P1 | MT-012 | Usable with 500 clients and 10,000 jobs | Q-1 / D-3 |
| ADM-040 | Onboarding completeness meter naming which modules are blocked and why | UX | PROP | P2 | ADM-009 | "Citations blocked: address missing" shown at client level | — |

---

## TEAM — TEAM PORTAL

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| TEAM-001 | My queue across audits, content, citations, Web 2.0 and tasks | `[ARCH]` §5 | CONF | P1 | ADM-030 | A specialist sees exactly their work, ordered by deadline and blocker | — |
| TEAM-002 | Task board `todo → in_progress → review → done`, lifecycle enforced at the database | `[CODE]` | CONF | P1 | DATA-022 | Illegal transitions rejected by the trigger, not only the API | — |
| TEAM-003 | Task assignment lists team members correctly | `[OVERHAUL]` §M | CONF | P0 | ADM-005 | Every eligible member appears; assignment persists | — |
| TEAM-004 | Review every tab and function in Team Management | `[OVERHAUL]` §M | CONF | P1 | — | Each tab demonstrably functional | — |
| TEAM-005 | Team performance metrics update immediately on member changes | `[OVERHAUL]` §M | CONF | P1 | TEAM-002 | Metric reflects a change within one refresh | — |
| TEAM-006 | Review checkpoint: approve / request edit / reject, blocking publish | `[ARCH]` §5; `[CODE]` | CONF | P0 | CONT-040 | Nothing publishes without a lead decision | Q-11 |
| TEAM-007 | Run and deliver audits and content jobs | `[ARCH]` §5 | CONF | P1 | AUD-*, CONT-* | End-to-end from the team portal | — |
| TEAM-008 | Task timer / time on task | `[CODE]` commit `62ae44b` | CONF | P2 | TEAM-002 | Duration recorded and reportable | — |
| TEAM-009 | Deadline extension requests, lead-approved | `[CODE]` `0074` | CONF | P2 | TEAM-002 | Request → approval → new deadline, logged | — |
| TEAM-010 | Notifications: assignment, review requested, job failed, deadline near | `[OVERHAUL]` §Q | CONF | P1 | INT-020 | Each fires end-to-end | — |
| TEAM-011 | Messages and DMs merged into one unified structure | `[WA-TEAM]` 28/07 | CONF | P2 | — | One inbox; no duplicate surfaces | — |
| TEAM-012 | Alerts connected to the backend data pipeline | `[WA-TEAM]` 28/07 | CONF | P1 | OPS-005 | Alerts driven by real events | — |
| TEAM-013 | Approvals queue interactive, including the empty state | `[WA-TEAM]` 28/07 | CONF | P2 | ADM-038 | Empty state is informative, not a dead panel | — |
| TEAM-014 | Activity history per member and per artefact | `[ARCH]` §5 | CONF | P2 | ADM-032 | Full trail visible | — |
| TEAM-015 | Read-only tool workspaces backing all 17 tool slugs | `[CODE]` | CONF | P2 | — | Every slug resolves to real data | — |
| TEAM-016 | Manager client book: status across an assigned client set | `[ARCH]` §5 | CONF | P2 | ADM-030 | Manager sees only assigned clients | Q-9 |
| TEAM-017 | Every failure legible without escalation: what failed, whose fault, did it cost money, safe to retry, what the client can see | UX | PROP | P1 | OPS-006, ERR-* | A specialist resolves or correctly escalates a red job unaided | — |
| TEAM-018 | An approver may not approve their own draft | separation of duties | PROP | P2 | TEAM-006 | Self-approval rejected | — |

---

## CLIENT — CLIENT PORTAL

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| CLIENT-001 | Dashboard: site snapshot + latest audit score | `[ARCH]` §5 | CONF | P1 | AUD-* | Renders own data only | — |
| CLIENT-002 | Reports: every audit as a web page and a downloadable PDF | `[SCOPE-CALL]` | CONF | P1 | AUD-012 | Both formats open and are identical in content | — |
| CLIENT-003 | Milestones, auto-updated, never client-editable | `[SCOPE-CALL]` | CONF | P1 | ADM-037 | Advance without human action | — |
| CLIENT-004 | Run an audit, free or paid per the tier the agency allows | `[SCOPE-CALL]` | CONF | P1 | ADM-035 | Tier enforced server-side | — |
| CLIENT-005 | Fiverr upsell cards | `[SCOPE-CALL]` | CONF | P2 | ADM-036 | Links resolve to real gigs | D-7 |
| CLIENT-006 | Requests / tickets with status | `[CODE]` | CONF | P2 | — | Round-trip works | — |
| CLIENT-007 | Granted deliverables | `[CODE]` `0032` | CONF | P2 | — | Only granted items visible | — |
| CLIENT-008 | Hard isolation: base tables return zero rows to another client's identity; `mrr`, `cost`, `error` and artefact paths unreachable | `[CODE]` verified | CONF | P0 | SEC-004 | The existing isolation integration test passes against live Postgres | — |
| CLIENT-009 | Clients cannot edit canonical NAP directly; a change is a request | data integrity | PROP | P1 | DATA-011 | NAP edit produces a change request, not a silent write | Q-11 |
| CLIENT-010 | Per-client rate limit and monthly free-run allowance on audits | abuse control | PROP | P2 | SEC-005 | Excess runs blocked with a clear message | — |
| CLIENT-011 | Never offer an artefact that has not been verified to exist and be non-trivial | `[CODE]`; `[OVERHAUL]` | CONF | P0 | ERR-004 | No empty or missing download is ever offered | — |
| CLIENT-012 | Client-safe status vocabulary with expected durations | UX | PROP | P2 | AUTO-008 | No internal state names leak to a client | — |
| CLIENT-013 | Client approval of content and of publishing to their own site | scope | UNK | P1 | TEAM-006 | Per owner decision | Q-11, Q-12 |
| CLIENT-014 | Standing authorisation to act under the client's identity for listings and properties | legal | PROP | P1 | CIT-*, WEB2-* | Captured at onboarding, recorded, revocable | Q-12 |
| CLIENT-015 | Per-client portal branding / custom domain | Haseeb brief only | UNK | P3 | — | Out of scope unless decided | Q-10 |

---

## AUD — AUDIT

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| AUD-001 | Free audit: one complete condensed report, ~10–15 pages, no type split | `[OVERHAUL]` §G | CONF | P0 | AUD-012 | One document; page count in band | — |
| AUD-002 | Free audit spends zero on paid providers | `[ARCH]`; `[CODE]` | CONF | P0 | ADM-025 | Cost ledger shows $0 for every free run | — |
| AUD-003 | Free audit: download after completion | `[OVERHAUL]` §G | CONF | P1 | AUD-012 | File downloads and opens | — |
| AUD-004 | In-dashboard HTML preview: paginated, next/prev, same content as the PDF | `[OVERHAUL]` §G/§H | CONF | P0 | AUD-012 | Side-by-side comparison shows identical content | — |
| AUD-005 | Paid audit type-selectable: on-page, technical, off-page, local, GEO, strategy; none = all | `[OVERHAUL]` §H | CONF | P1 | ADM-012 | Each selection produces the matching scope | — |
| AUD-006 | Full paid runs use the multi-agent evaluation and AI narrative | `[CODE]` | CONF | P1 | AI-003 | Verified in the invocation and in the output | — |
| AUD-007 | Same report layout for free and paid | `[OVERHAUL]` §H | CONF | P2 | AUD-012 | Layout identical, depth differs | — |
| AUD-008 | Writing style: direct on the issues, client-friendly | `[OVERHAUL]` §H | CONF | P2 | AI-003 | Human review of 10 reports | — |
| AUD-009 | Every finding carries evidence; no invented metrics | `[KB]`; `[ARCH]` | CONF | P0 | AI-*, QA-004 | Sampled findings each trace to measured data | — |
| AUD-010 | Findings JSON available to staff | `[CODE]` | CONF | P2 | — | Downloadable, schema-valid | — |
| AUD-011 | Role-based remediation sheets (XLSX + CSV) | `[CODE]` | CONF | P2 | AUD-010 | Generated per run | — |
| AUD-012 | PDF and dashboard HTML rendered from one source | `[OVERHAUL]` §H; `[CODE]` | CONF | P0 | — | One source document, two renderers | — |
| AUD-013 | Caller owns the hard timeout; non-zero exit, timeout or missing `run.json` is failure | `[CODE]` | CONF | P0 | AUTO-005 | Injected hang produces a failed run, never a hung job | D-10 |
| AUD-014 | A run producing no PDF does not offer a PDF | `[CODE]` commit `79d1036` | CONF | P0 | CLIENT-011 | Negative test | — |
| AUD-015 | Coverage: crawl, technical, CWV, on-page, local, off-page, GEO/AI, competitors, keywords | `[ENGINE]`; `[SCOPE-CALL]` | CONF | P1 | INT-* | Each dimension present in a full run | — |
| AUD-016 | Public free-audit endpoint has rate limits, a queue cap and domain validation | abuse control | PROP | P1 | SEC-005 | Load test cannot exhaust the queue | D-13 |
| AUD-017 | Findings normalised as rows, not only artefacts | data model | PROP | P1 | DATA-005 | A finding can be assigned, fixed and re-verified | — |
| AUD-018 | Delta audits: what changed, what was fixed, what regressed | practitioner value | PROP | P1 | AUD-017, AUD-021 | Two runs on one site produce a meaningful delta | — |
| AUD-019 | Impact × effort prioritisation with an explicit top-five | practitioner value | PROP | P1 | AUD-017 | Every report opens with a prioritised action list | — |
| AUD-020 | Fix verification: re-check a finding and close it with evidence | practitioner value | PROP | P2 | AUD-017 | Closed findings carry proof | — |
| AUD-021 | Deterministic scoring — same input, same score | correctness | PROP | P1 | — | Two runs on an unchanged site agree | — |
| AUD-022 | Confidence label per finding (measured / inferred / sampled) | credibility | PROP | P2 | AUD-009 | Present on every finding | — |
| AUD-023 | Competitor-relative scoring | interpretability | PROP | P2 | INT-004 | Score shown against the pack leader | — |
| AUD-024 | "What we could not check, and why" section | honesty | PROP | P2 | INT-001 | Present whenever a source is degraded | — |
| AUD-025 | One-click conversion of a finding into a task | workflow | PROP | P2 | AUD-017, TEAM-002 | Task created with context | — |
| AUD-026 | Financial audit report (market capacity + revenue) | `[SCOPE-CALL]` | CONF | P3 | — | Phase 2 — documented, not built | — |

---

## CONT — CONTENT

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| CONT-001 | Research module: study the site and competitors, recommend the page set before writing | `[RESEARCH-AUG]` | CONF | P0 | INT-004 | For a real site it returns a defensible page set with volume and difficulty | — |
| CONT-002 | Content type picker: service, location, service×location, service-area, GSC-opportunity, blog, FAQ | `[RESEARCH-AUG]` | CONF | P0 | CONT-001 | Each type produces a type-appropriate recommendation | — |
| CONT-003 | Competitor page teardown feeding the recommendation | `[RESEARCH-AUG]` | CONF | P1 | INT-004 | Rival service/location pages enumerated | — |
| CONT-004 | Keyword research and clustering per recommended page | `[RESEARCH-AUG]` | CONF | P1 | INT-005 | Each page carries a keyword cluster and an intent | — |
| CONT-005 | Service×location recommends winners, not the full cross-product | `[RESEARCH-AUG]` | CONF | P1 | CONT-004 | Recommendation is a filtered subset with a stated rationale | — |
| CONT-006 | Location selection weighs buyer quality, not population alone | `[WA-TEAM]` 05/07 | CONF | P2 | CONT-005 | Rationale visible per recommended location | Q-16 |
| CONT-007 | Bulk fan-out: one, several or all recommended pages in one action | `[RESEARCH-AUG]` | CONF | P0 | CONT-001, AUTO-005 | 15 pages generated from one action | — |
| CONT-008 | Bulk run returns a manifest of all live URLs | `[RESEARCH-AUG]` | CONF | P1 | CONT-007 | Manifest complete and accurate | — |
| CONT-009 | Build one page, a category, or a whole website — operator's choice | operator 2026-08-23 | CONF | P1 | CONT-007 | Each mode demonstrated | — |
| CONT-010 | Cost estimated and explicitly confirmed before a bulk run starts | cost control | PROP | P0 | ADM-025 | No bulk run begins without an accepted estimate | — |
| CONT-011 | Bulk runs are resumable and support partial completion | reliability | PROP | P1 | AUTO-007 | Killing mid-run and resuming loses no completed page | — |
| CONT-012 | Structured brief per page: keywords, intent, audience, entities, competitor angle, internal links, schema type, length band, CTA | practice | SI | P1 | CONT-004 | Brief present and used | — |
| CONT-013 | Brand voice captured per client and enforced | `[PACK-JUL]` implied | SI | P1 | DATA-002 | Voice profile applied and checkable | — |
| CONT-014 | Client context pack snapshotted into every job | `[CODE]` `source_pack` | CONF | P1 | ADM-009 | Drafts cite only real client facts | — |
| CONT-015 | Proof / first-hand detail required before generation | `[CODE]` commit `8835cb7` | CONF | P1 | CONT-014 | Generation blocked without it | — |
| CONT-016 | Draft against local-SEO copy frameworks (AIDA, PAS, BAB), auto-selected by page type | `[SCOPE-CALL]`; `[CODE]` | CONF | P1 | — | Framework recorded per job | — |
| CONT-017 | **Zero em dashes** anywhere in output, on the site, in emails or in AI responses | `[OVERHAUL]` §I; `[WA-ADAN]` 01/08 | CONF | P0 | CONT-018 | Automated check across all output; zero occurrences | — |
| CONT-018 | AI-sounding detection with section-by-section rewrite on failure | `[OVERHAUL]` §I | CONF | P0 | AI-007 | Detection fires and rewrite improves the score | — |
| CONT-019 | JSON-LD schema per page type, validated | `[SCOPE-CALL]`; `[CODE]` | CONF | P1 | — | Validates against schema.org and Google's test | — |
| CONT-020 | Meta title and description generated, length-checked, unique | `[SCOPE-CALL]` | CONF | P1 | WP-016 | No duplicates across the site | — |
| CONT-021 | Internal links to relevant existing pages with sensible anchors | `[ARCH]` §4 | CONF | P1 | WP-020 | Links resolve; anchors varied | — |
| CONT-022 | Images generated in a real photographic style, landscape where appropriate, branded SVG icons not emoji | `[CODE]` commits `4a700f4`, `13fae71` | CONF | P1 | INT-002 | Visual review of 20 pages | — |
| CONT-023 | Image alt **and title** attributes | `[WA-ADAN]` 21/08; `[CODE]` | CONF | P1 | CONT-022 | Both present on every image | — |
| CONT-024 | Responsive breakpoints in generated markup | `[CODE]` commit `79d1036` | CONF | P1 | WP-031 | Renders correctly at mobile, tablet, desktop | — |
| CONT-025 | No raw CSS dumped into post content | `[CODE]` commit `faeec43` | CONF | P1 | WP-004 | Post content inspected; no style blocks | — |
| CONT-026 | Multiple layout candidates generated, the better chosen | `[OVERHAUL]` §I | CONF | P2 | CONT-030 | Selection rationale recorded | — |
| CONT-027 | 14-dimension QA scorecard | `[CODE]` | CONF | P1 | AI-006 | Produced on every draft | — |
| CONT-028 | The gate's status is unambiguous across code and documentation | `[CODE]` vs `[RESEARCH-AUG]` | CONFL | P0 | — | One stated behaviour everywhere | D-4 |
| CONT-029 | Threshold and weights calibrated against human SEO grading before enforcement | `[CODE]` marks provisional | CONF | P0 | CONT-028 | ~30 graded drafts; published calibration | D-4 |
| CONT-030 | QA result explained to the reviewer: which dimension, on what evidence, what would fix it | UX | PROP | P1 | CONT-027 | Reviewer can act without asking | — |
| CONT-031 | Exactly one mandatory human review gate | universal | CONF | P0 | TEAM-006 | Nothing publishes without it | Q-11 |
| CONT-032 | True in-dashboard preview (embedded HTML preferred) | `[OVERHAUL]` §I | CONF | P1 | — | Preview matches the published result | — |
| CONT-033 | In-dashboard WYSIWYG editing then publish | `[CODE]` commit `573ddf6` | CONF | P1 | CONT-032 | Edit-then-publish round-trips | — |
| CONT-034 | Three-actor lifecycle enforced at the database, not in the API | `[CODE]` | CONF | P1 | DATA-022 | Worker cannot approve; non-lead can drive nothing | — |
| CONT-035 | On approval with WordPress connected, auto-publish and return the live URL for immediate testing | `[OVERHAUL]` §I | CONF | P0 | WP-* | URL returned and opens | — |
| CONT-036 | Manual PDF/Markdown export path retained | `[SCOPE-CALL]` | CONF | P2 | — | Export produced | — |
| CONT-037 | Scheduled publishing and republish | `[CODE]` `0072` | CONF | P2 | AUTO-006 | Scheduled item publishes on time | — |
| CONT-038 | Versioning: every draft and revision retained and diffable | practice | SI | P1 | DATA-012 | Diff viewable | — |
| CONT-039 | Rollback a published page to its previous state | client question `[WA-TEAM]` 07/07 | PROP | P1 | CONT-038, WP-034 | Revert proven on a live site | — |
| CONT-040 | Publish idempotent, keyed on the job id | reliability | PROP | P0 | AUTO-004 | Forced redelivery creates no duplicate page | — |
| CONT-041 | Post-publish verification: page renders, schema validates, images load, page opens editable | correctness | PROP | P0 | WP-* | Verification recorded per publish | — |
| CONT-042 | Indexing submitted on publish | `[RESEARCH-AUG]` | CONF | P1 | IDX-* | Submission logged with status | — |
| CONT-043 | Internal near-duplicate check across a bulk run | SEO risk | PROP | P0 | CONT-007 | Similarity above threshold blocks the batch | — |
| CONT-044 | Cannibalisation check against the site's existing pages before proposing a page | SEO risk | PROP | P1 | CONT-001 | Conflicting proposals flagged | — |
| CONT-045 | Plagiarism / duplicate check against the live web | SEO risk | PROP | P2 | INT-004 | Above-threshold matches block | — |
| CONT-046 | Factual-claim guard: statistics, prices, certifications and guarantees come from the context pack or are omitted | legal | PROP | P0 | CONT-014 | No invented claim survives review | — |
| CONT-047 | Reading-level and sentence-variance targets | AI-tell defence | PROP | P2 | CONT-018 | Metrics in band | — |
| CONT-048 | Topical map / cluster model with pillar-and-spoke structure | topical authority | PROP | P1 | CONT-001 | Cluster visible and used to plan | — |
| CONT-049 | Content calendar with scheduling | `[CODE]` `0072` | CONF | P2 | CONT-037 | Calendar drives publishing | — |
| CONT-050 | Content maintenance loop: detect stale NAP, hours and schema and raise tasks | `[WA-TEAM]` 05/07 | PROP | P1 | DATA-011 | A NAP change raises update tasks across affected pages | — |
| CONT-051 | Bulk publishing paced, not a same-minute burst | SEO risk | PROP | P2 | CONT-007 | Publish times distributed | — |
| CONT-052 | GBP post generation following Google policy, operator-reviewed | `[OVERHAUL]` §J | CONF | P1 | INT-008 | Posts drafted, approved, published for 5 businesses | Q-14 |

---

## WP — WORDPRESS

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| WP-001 | One-time per-site connection; credentials sealed, never logged, decrypted at point of use | `[ARCH]` §10 | CONF | P0 | ADM-031 | Credential never appears in a log or a response | — |
| WP-002 | Primary auth: WordPress Application Passwords over REST | `[ARCH]` | CONF | P1 | WP-001 | Connect and publish | — |
| WP-003 | Fallback: XML-RPC | `[RESEARCH-AUG]` | CONF | P2 | WP-001 | Works where REST is blocked | — |
| WP-004 | Companion plugin route with its own token | `[CODE]` | CONF | P0 | WP-001 | Plugin publishes builder-native output | — |
| WP-005 | Capability discovery: WP/PHP version, REST, app passwords, Elementor + version + licence, Gutenberg, theme, ACF `show_in_rest`, SEO plugin, caching, page inventory, sitemap, robots, upload limits | `[RESEARCH-AUG]`; `[WA-ADAN]` 08/07 | CONF | P0 | WP-001 | Correct on 10 different real sites | Q-15 |
| WP-006 | Canonical builder-agnostic page model as the single content currency | `[CODE]` `page_model.py` | PROP | P0 | CONT-* | All renderers derive from it | D-12 |
| WP-007 | Elementor widget-tree output producing a fully editable page | `[RESEARCH-AUG]`; `[CODE]` | CONF | P0 | WP-006 | Page opens editable in Elementor on a real site | D-12 |
| WP-008 | Native Gutenberg block output for non-Elementor sites | `[CODE]` | CONF | P1 | WP-006 | Page opens editable in the block editor | D-12 |
| WP-009 | Flat HTML only as an explicitly labelled degradation | quality | PROP | P1 | WP-006 | Labelled in the UI whenever used | — |
| WP-010 | Read and reuse the site's existing style kit | `[RESEARCH-AUG]`; `[CODE]` `site_design.py` | CONF | P0 | WP-005 | Generated page visually matches the site | — |
| WP-011 | Generate a clean niche-appropriate layout where no usable design exists | `[RESEARCH-AUG]` | CONF | P1 | WP-010 | Acceptable result on a bare site | — |
| WP-012 | Page cloning: use an existing page as a structural template | operator 2026-08-23 | CONF | P1 | WP-010 | Cloned structure reproduced | — |
| WP-013 | Stored, inspectable design profile per site | `[CODE]` | CONF | P1 | WP-010 | Profile viewable and re-usable | — |
| WP-014 | Visual regression check between generated and reference pages | quality | PROP | P2 | WP-013, `0071` | Divergence flagged | — |
| WP-015 | Never write to global styles, theme files, or existing pages — additive only | safety | PROP | P0 | — | Negative test on a real site | — |
| WP-016 | Meta title/description written to the **active SEO plugin's** fields | correctness | SI | P0 | WP-005 | Yoast/RankMath fields populated, verified in the plugin UI | — |
| WP-017 | Canonical URL control | `[ARCH]` | CONF | P1 | WP-016 | Canonical set correctly | — |
| WP-018 | Robots directives control | `[ARCH]` | CONF | P1 | WP-016 | index/noindex honoured | — |
| WP-019 | Slug control with collision handling | practice | CONF | P1 | — | No accidental `-2` slugs | — |
| WP-020 | Internal links to existing pages | `[ARCH]` §4 | CONF | P1 | CONT-021 | Links resolve | — |
| WP-021 | Images uploaded to the media library with alt and title; featured image set | `[ARCH]` §4 | CONF | P1 | CONT-023 | Media library entries correct | — |
| WP-022 | Tags and categories from keyword research | `[CODE]` commit `db4ae1f` | CONF | P2 | CONT-004 | Assigned on publish | — |
| WP-023 | Sitemap updated after publish | practice | CONF | P1 | WP-005 | New URL present in the sitemap | — |
| WP-024 | Bounded DOM size on generated pages, asserted | `[WA-TEAM]` 07/07 | CONF | P0 | WP-006 | Budget asserted at publish | — |
| WP-025 | Bounded page weight; compressed, correctly sized, modern-format images | practice | SI | P1 | CONT-022 | Budget met | — |
| WP-026 | Core Web Vitals measured on the published page | practice | PROP | P1 | INT-007 | LCP/CLS/INP within Google's "good" band | — |
| WP-027 | No render-blocking additions | `[WA-TEAM]` 07/07 | CONF | P1 | WP-025 | Verified in a PSI run | — |
| WP-028 | Lazy-load below-fold images | practice | PROP | P2 | CONT-022 | Attribute present | — |
| WP-029 | Cache purge after publish where a caching layer is detected | practice | PROP | P1 | WP-005 | New content visible immediately | — |
| WP-030 | Draft → preview → publish → revision history | `[ARCH]` | CONF | P1 | — | Full lifecycle works | — |
| WP-031 | Responsive at defined breakpoints | `[CODE]` | CONF | P1 | CONT-024 | Verified at three widths | — |
| WP-032 | **Revert option for anything the system changes** | `[WA-TEAM]` 07/07 client question | PROP | P0 | CONT-039 | Revert proven | — |
| WP-033 | Pre-publish SEO validation blocking on missing title, missing description, duplicate slug, invalid schema, missing alt, off-site canonical | quality | PROP | P1 | WP-016…WP-021 | Each condition blocks | — |
| WP-034 | Detect human edits to a generated page and refuse to overwrite without confirmation; use a hash/etag, not a string compare | `[CODE]` known limitation | PROP | P0 | CONT-038 | Human edit is never silently destroyed | — |
| WP-035 | Least-privilege publisher role rather than an administrator account | security | PROP | P1 | WP-001 | Publishing works with reduced capabilities | — |
| WP-036 | Per-site credential rotation procedure | security | PROP | P2 | ADM-031 | Documented and executed once | — |
| WP-037 | Outbound requests to client sites pass the SSRF guard | security | PROP | P1 | SEC-010 | Private addresses rejected | — |
| WP-038 | Plugin versioned against Elementor with a compatibility matrix and regression tests | reliability | PROP | P1 | WP-007 | Matrix published; tests green on two Elementor versions | — |

---

## CIT — CITATIONS

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| CIT-001 | Canonical NAP per client per location as the single source of truth | `[CIT-ECON]`; `[CIT-CRED]` | CONF | P0 | ADM-009, ADM-010 | Identical NAP on every submitted listing | Q-8 |
| CIT-002 | Extended business profile (~20 fields): description, logo, photos, email, socials, year founded, payment types, service area, tagline, hours | `[RESEARCH-AUG]` | CONF | P0 | ADM-009 | Directories requesting these fields receive them | — |
| CIT-003 | Name and address mandatory; an empty profile blocks **before** any spend | `[CIT-CRED]` §7 | CONF | P0 | CIT-001 | Zero wasted charges on incomplete profiles | — |
| CIT-004 | Citation audit: what exists, where, and what is inconsistent | `[OVERHAUL]` §K | CONF | P0 | INT-004 | Real discovery on 10 businesses | — |
| CIT-005 | Prioritised recommendation: generic → country → niche | `[RESEARCH-AUG]` | CONF | P1 | CIT-004 | An Australian plumber is not shown US-only directories | Q-16, Q-17 |
| CIT-006 | Build **only** where not already listed | `[OVERHAUL]` §K | CONF | P0 | CIT-004 | No duplicate listing created | — |
| CIT-007 | Per-client accounts under the client's own identity, never shared | `[CIT-ECON]` | CONF | P0 | ADM-031 | Vault holds per-client directory credentials | D-5 |
| CIT-008 | Account creation: signup, CAPTCHA solve, IMAP confirmation-link click | `[RESEARCH-AUG]`; `[CODE]` | CONF | P0 | INT-018, INT-019 | Account created end-to-end on 10 directories | — |
| CIT-009 | Submission across ~100 valuable platforms | operator 2026-08-23 | CONF | P0 | CIT-010 | 50 citations × 10 businesses achieved; coverage reported honestly | Q-2 |
| CIT-010 | Directory form specs verified against live forms before being trusted at scale | `[CIT-CRED]` §5 | CONF | P0 | — | Every spec used in a volume run has a dated verification | — |
| CIT-011 | Proof per unit: live URL **and** screenshot | `[OFFPAGE-STATUS]`; `[CIT-CRED]` | CONF | P0 | ADM-033 | Every successful unit carries both | — |
| CIT-012 | "Ready to finish" handoff queue for directories that re-gate the final click | `[OFFPAGE-STATUS]` | CONF | P1 | CIT-008 | Queue populated with login and one-click finish | — |
| CIT-013 | Per-unit cost accounted against the ceiling at runtime | `[CIT-ECON]`; `[OVERHAUL]` §E | CONF | P0 | ADM-025 | Cost ledger per unit; ceiling enforced | D-2 |
| CIT-014 | **Loaded** cost modelled and reported, including human handoff time, proxy bandwidth and CAPTCHA balance | commercial | PROP | P0 | CIT-013 | Marginal and loaded figures both reported | D-2 |
| CIT-015 | Apify permitted only as an explicitly approved, per-unit-visible fallback | `[CIT-ECON]`; `[WA-ADAN]` 04/08 | CONF | P1 | CIT-013 | Never a default path; its 25¢ visible in the ledger | D-2 |
| CIT-016 | NAP drift monitoring and periodic re-verification | `[KB]` | CONF | P1 | AUTO-010 | Drift detected and raised as a task | — |
| CIT-017 | Rate limiting and human pacing per directory and per IP | `[CIT-ECON]` implied | PROP | P1 | INT-019 | No directory receives a burst | — |
| CIT-018 | Honest failure attribution: ours vs the directory's | `[OVERHAUL]` §K | CONF | P1 | OPS-006 | Every failed unit states the cause | — |
| CIT-019 | Listing removal / correction workflow | gap | PROP | P0 | CIT-011 | An incorrect live listing can be corrected or removed from the dashboard | — |
| CIT-020 | Spec-drift detection: a changed form fails loudly with a diff | reliability | PROP | P1 | CIT-010 | Drift raises an alert, never a silent failure | — |
| CIT-021 | Client-visible citation ledger: where listed, with what data, since when | transparency | PROP | P2 | CIT-011 | Rendered in the client portal | — |
| CIT-022 | Per-directory terms-of-service position recorded | legal | PROP | P1 | — | Every automated directory has a recorded position | — |
| CIT-023 | **No fabricated business data, ever** — a missing required field blocks the unit | integrity | PROP | P0 | CIT-003 | Negative test: unit blocks rather than inventing | — |
| CIT-024 | Explicit "deliberately skipped, and why" output | honesty | PROP | P1 | CIT-005 | Every non-attempted directory explained | — |
| CIT-025 | Direct-API write endpoints (Foursquare, Bing Places) confirmed against live partner docs before being trusted | `[CIT-CRED]` §4 | CONF | P1 | INT-014 | A real write succeeds, or the engine is marked unavailable | — |
| CIT-026 | Aggregator seeding (Data Axle, Neustar) handled as a documented manual step | `[CIT-CRED]` §4 | CONF | P2 | — | Marked manual-only; no false automation claim | — |
| CIT-027 | Per-client mailbox or plus-addressing rather than one shared catch-all | isolation | PROP | P1 | INT-019 | One client's mailbox issue cannot block another's | — |

---

## WEB2 — WEB 2.0

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| WEB2-001 | 50+ platforms with live publishing | operator 2026-08-23; `[CODE]` | CONF | P0 | INT-024 | 50 platforms with a verified live publish each | Q-5 |
| WEB2-002 | Unique content per property; never spun or templated | `[CIT-ECON]` | CONF | P0 | WEB2-007 | Similarity check passes across the property set | — |
| WEB2-003 | Human-paced posting with jitter, never a burst | `[CIT-ECON]` | CONF | P0 | AUTO-012 | Publish timestamps distributed | — |
| WEB2-004 | A different platform mix per client | `[CIT-ECON]` | CONF | P0 | WEB2-008 | No two clients share an identical mix | — |
| WEB2-005 | One editorial link per property, contextually placed | `[CIT-ECON]` | CONF | P1 | CONT-* | Verified on every property | — |
| WEB2-006 | Consistent NAP and brand across properties | `[CIT-ECON]` | CONF | P1 | CIT-001 | Matches the canonical record | — |
| WEB2-007 | Cross-property similarity gate blocking above threshold, measured within a client **and** across clients on a shared account | SEO risk | PROP | P0 | WEB2-002 | Above-threshold draft cannot publish | — |
| WEB2-008 | House-account footprint analysis and a cap on properties per account | SEO risk | PROP | P0 | DATA-016 | Cap enforced; footprint reported | D-5 |
| WEB2-009 | Per-client accounts on high-authority platforms | `[CIT-ECON]` vs `[CIT-CRED]` | CONFL | P0 | ADM-031 | Per owner decision | D-5 |
| WEB2-010 | Lead approval before each property goes live | `[KB]` | CONF | P0 | TEAM-006 | Nothing publishes without it | — |
| WEB2-011 | Account health monitoring: suspensions, deletions, link removals | `[OVERHAUL]` §K | CONF | P1 | AUTO-019 | Health state per account | — |
| WEB2-012 | Per-platform status board: connected vs missing, with the reason and whose fault | `[OVERHAUL]` §K | CONF | P1 | OPS-006 | Every platform row is honest | — |
| WEB2-013 | Link-liveness monitoring on a schedule | gap | PROP | P1 | AUTO-019 | A removed link raises an alert | — |
| WEB2-014 | Anchor-text distribution control across a client's profile | SEO risk | PROP | P1 | DATA-017 | Distribution reported and bounded | — |
| WEB2-015 | Per-platform terms position recorded; refuse where automated posting is prohibited | legal | PROP | P1 | — | Position recorded for all 50 | — |
| WEB2-016 | Medium excluded (publish API retired); Weebly/Squarespace/Strikingly excluded (no API) | `[CIT-ECON]`; `[CIT-CRED]` | CONF | P2 | — | Not offered, and the reason shown | — |
| WEB2-017 | WordPress.com, Blogger and Tumblr wired via one-time OAuth per client | `[CIT-CRED]` §2 | CONF | P1 | ADM-031 | All three publish for a real client | D-5 |

---

## IDX — INDEXING

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| IDX-001 | IndexNow ping on every publish | `[RESEARCH-AUG]` | CONF | P1 | WP-023 | Submission logged with a response | — |
| IDX-002 | Google Indexing API request on every publish | `[RESEARCH-AUG]` | CONF | P1 | INT-011 | Submission logged; quota respected | — |
| IDX-003 | Sitemap ping | `[RESEARCH-AUG]` | CONF | P2 | WP-023 | Ping recorded | — |
| IDX-004 | Indexing status tracked per URL over time | `[RESEARCH-AUG]` | CONF | P1 | DATA-018 | Indexed / not-indexed visible per URL | — |
| IDX-005 | Idempotent per URL; quota-aware queueing and retry | reliability | PROP | P1 | AUTO-023 | Repeat submissions do not exhaust quota | — |

---

## AI — AI SYSTEM

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| AI-001 | **Python computes numbers, AI writes narrative** — no metric may originate in a model | `[WA-TEAM]` 04/07 | CONF | P0 | AUD-009 | Sampled narratives: every number traces to a computed finding | — |
| AI-002 | Multi-provider routing with task-appropriate model tiers | `[WA-TEAM]` 04/07 | CONF | P1 | INT-001 | Routing recorded per call | — |
| AI-003 | Policy categorisation uses Claude Haiku | `[OVERHAUL]` §D | CONF | P2 | AI-004 | Model recorded | — |
| AI-004 | Policy change summarised, categorised by severity, category and region, versioned into the KB | `[ARCH]` §6 | CONF | P1 | AUTO-016 | Entries carry all three flags and a source citation | — |
| AI-005 | Every AI component declares input, task, output schema, validation, failure mode, human override and cost | engineering | PROP | P1 | — | Documented for all 16 components | — |
| AI-006 | Structured AI output is schema-validated; an output inventing a metric is rejected | correctness | PROP | P0 | AI-001 | Negative test | — |
| AI-007 | AI failure degrades to a named hold state, never a crash and never an auto-pass | `[CODE]` | CONF | P0 | ERR-* | Injected failure holds at review | — |
| AI-008 | Every AI call passes the cost gate before execution, and actual cost is logged | `[CODE]` | CONF | P0 | ADM-025 | No ungated call exists | — |
| AI-009 | Per-job token ceiling | cost control | PROP | P1 | AI-008 | A runaway generation is capped | — |
| AI-010 | Untrusted fetched content is structurally demarcated and never placed in an instruction position | `[ARCH]` §10 | CONF | P0 | SEC-020 | Injection test suite passes | — |
| AI-011 | A model cannot trigger spend, publish or credential access as a side effect | security | PROP | P0 | AI-010 | Capability comes from the caller only | — |
| AI-012 | No credentials, other clients' data or internal costs in a model context | security | PROP | P0 | AI-010 | Prompt inspection | — |
| AI-013 | Context memory: living summary + keyed facts + vector index, kept fresh from the activity log | `[CODE]` | CONF | P1 | DATA-021 | Freshness lag queryable and bounded | — |
| AI-014 | Postgres is the source of truth; the vector index is derived and reconstructable | `[CODE]` | CONF | P1 | AI-013 | A vector-store outage does not corrupt state | — |
| AI-015 | Skills gateway: scoped per-client tokens, cost-gated dispatch, the only path | `[CODE]` | CONF | P1 | SEC-002 | No alternative path exists | — |
| AI-016 | Prompt and output retention policy | privacy | PROP | P2 | — | Policy documented and enforced | — |

---

## AUTO — AUTOMATION

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| AUTO-001 | **Restore the beat schedule** — all periodic jobs run again | `[CODE]`; `[OVERHAUL]` §D | CONF | P0 | AUTO-002…AUTO-007 | Every job in `_BEAT_SCHEDULE_DISABLED` runs and is ledgered | — |
| AUTO-002 | Policy Radar runs live and auto-updates **daily** | `[OVERHAUL]` §D | CONF | P0 | AUTO-001, AI-004 | 7 consecutive days of real runs | — |
| AUTO-003 | Nightly rank tracking and weekly rollup | `[PACK-JUL]` | CONF | P1 | AUTO-001, D-6 | Nightly data present | D-6 |
| AUTO-004 | Idempotency key on every job that mutates external state | reliability | PROP | P0 | — | Forced redelivery creates no duplicate | — |
| AUTO-005 | Bounded, jittered retry with a maximum attempt count | reliability | PROP | P1 | — | No retry storm under provider failure | — |
| AUTO-006 | Overlap lock on every scheduled job | reliability | PROP | P0 | AUTO-001 | Concurrent trigger does not double-run | — |
| AUTO-007 | Every run recorded in a `scheduled_job_runs` ledger with last-run and last-status | `[CODE]` | CONF | P1 | ADM-021 | Ledger complete | — |
| AUTO-008 | One status vocabulary across all modules: `queued → running → needs_review → done / failed / blocked` | consistency | PROP | P1 | — | No module invents its own | — |
| AUTO-009 | A cost-gate block is a **visible** state, never a silent no-op | `[CODE]` known defect | CONF | P0 | ADM-025 | Keyword-research block surfaces to the caller | — |
| AUTO-010 | Citation re-verification on a schedule | `[KB]` | CONF | P1 | AUTO-001, CIT-016 | Drift detected automatically | — |
| AUTO-011 | Broker visibility timeout asserted ≥ the longest task time limit at boot | `[CODE]` hazard | PROP | P0 | — | Boot fails loudly on a misconfiguration | — |
| AUTO-012 | Dead-letter queue with an operator surface | reliability | PROP | P0 | OPS-004 | Failed jobs land there and are actionable | — |
| AUTO-013 | Job cancellation, and spend stops on cancel | control | PROP | P1 | ADM-026 | Cancelling a running job halts further spend | — |
| AUTO-014 | Global pause of all automation | control | PROP | P1 | AUTO-001 | One switch, immediate effect | — |
| AUTO-015 | Per-client job concurrency caps | scale | PROP | P0 | MT-004 | One client's bulk run cannot starve the queue | D-3 |
| AUTO-016 | Policy source diff fires a research job immediately on change | `[ARCH]` §6 | CONF | P1 | AUTO-002 | Detected change triggers research without waiting for the next poll | — |
| AUTO-017 | Monthly client report, deduped per client × month, approved before send | `[PACK-JUL]` | CONF | P1 | AUTO-001, ADM-020 | Report built from real data, approved, sent | — |
| AUTO-018 | Sheets writes batched through a buffer, inside quota, degrading to no-op | `[KB]`; `[CODE]` | CONF | P1 | INT-012 | Quota exhaustion does not lose data | — |
| AUTO-019 | Off-page monitoring sweep | `[CODE]` | CONF | P1 | AUTO-001 | Backlink and listing changes detected | — |
| AUTO-020 | Free-audit follow-up email sequence, suppressed on reply or unsubscribe | `[WA-ADAN]` 05/08 | CONF | P2 | INT-020 | Sequence runs; suppression works | D-13 |
| AUTO-021 | Milestones advance idempotently from delivery events | `[SCOPE-CALL]` | CONF | P1 | ADM-037 | Repeated events do not double-advance | — |
| AUTO-022 | Context compaction event-driven, debounced, never re-raising | `[CODE]` | CONF | P1 | AI-013 | No double-spend on redelivery | — |
| AUTO-023 | Nightly backup, with the failure alerting loudly | `[KB]` | CONF | P0 | ADM-033, OPS-005 | A failed backup pages someone | — |
| AUTO-024 | Partial success is a first-class state | reliability | PROP | P1 | CONT-011 | "17 of 20 published, here are the 3 and why" | — |
| AUTO-025 | A job that spent money records the spend even if it later fails | accounting | PROP | P1 | ADM-025 | Ledger complete after an induced failure | — |
| AUTO-026 | A "what will run in the next 24 hours" view | control | PROP | P1 | ADM-021 | Operator can see and pause it | — |

---

## SEC — SECURITY

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| SEC-001 | MFA for Owner and Admin | security | PROP | P1 | ADM-028 | Enrolment enforced on both roles | D-8 |
| SEC-002 | RBAC enforced server-side; UI hiding is presentation only | `[CODE]` | CONF | P0 | ADM-030 | Negative test per boundary | — |
| SEC-003 | Vault: AES-256-GCM, masked listing, owner-only reveal, decrypt at point of use | `[CODE]` | CONF | P0 | ADM-031 | Non-owner reveal 403s; no secret in logs | — |
| SEC-004 | Client isolation at the database via RLS, proven by an integration test using the client's own identity | `[CODE]` verified | CONF | P0 | DATA-024 | Test passes against live Postgres | — |
| SEC-005 | Rate limiting on auth, the public free-audit endpoint, and spend-causing client actions | security | PROP | P1 | AUD-016 | Limits enforced and observable | — |
| SEC-006 | EdDSA tokens verified under a hard algorithm allow-list | `[CODE]` | CONF | P0 | — | alg-confusion and `none` rejected | — |
| SEC-007 | No public signup; owner-only provisioning in one privileged transaction | `[CODE]` | CONF | P0 | ADM-005 | No self-registration path exists | — |
| SEC-008 | Session lifetime bounded and revocable | security | PROP | P1 | SEC-006 | A session can be revoked immediately | — |
| SEC-009 | CSRF protection on cookie-authenticated state-changing routes | security | PROP | P1 | — | Verified by test | — |
| SEC-010 | SSRF guard on every outbound target, including client sites | `[CODE]` | CONF | P0 | WP-037 | Private addresses rejected | — |
| SEC-011 | Output encoding / XSS defence wherever AI-generated or client HTML renders — the WYSIWYG editor and the audit HTML viewer especially | security | PROP | P0 | CONT-033, AUD-004 | XSS payload in a draft does not execute | — |
| SEC-012 | Parameterised queries only; asserted in CI | `[CODE]` practice | CONF | P1 | — | CI check present | — |
| SEC-013 | File-upload validation: type, size, content sniffing | security | PROP | P1 | ADM-* | Malicious upload rejected | — |
| SEC-014 | Webhook signature verification on inbound webhooks | security | PROP | P2 | — | Unsigned webhook rejected | — |
| SEC-015 | Secrets scanning in CI that blocks a merge | `[CODE]` `.gitleaks.toml` | CONF | P1 | — | A planted secret fails CI | — |
| SEC-016 | **Rotate every credential exposed in the WhatsApp exports** | `[WA-*]` incident | CONF | P0 | — | Enumerated list; all rotated; confirmed | Q-22, D-15 |
| SEC-017 | Move the chat export out of the repository tree and git-ignore it | `[CODE]` | CONF | P0 | — | Not present in the working tree | — |
| SEC-018 | A credential-sharing channel that is not a messaging app | process | PROP | P0 | — | Documented and adopted | — |
| SEC-019 | Credential rotation procedure per provider and per site | security | PROP | P2 | ADM-031 | Documented and exercised once | — |
| SEC-020 | Untrusted content treated as data, never as instructions | `[ARCH]` §10 | CONF | P0 | AI-010 | Injection test suite passes | — |
| SEC-021 | Vault master key custody, backup and rotation documented | continuity | PROP | P0 | — | Documented; a restore proven to decrypt | Q-18 |
| SEC-022 | Backups encrypted and restore-tested | continuity | PROP | P0 | ADM-033 | A restore is performed and verified | — |
| SEC-023 | Per-client credential separation, invisible to other clients and to staff without cause | isolation | PROP | P1 | SEC-003 | Verified by test | — |
| SEC-024 | Client data handling on off-boarding | privacy | PROP | P2 | DATA-013 | Policy documented | — |
| SEC-025 | Every spend-causing and live-site-mutating action requires an explicit permission and is attributed to a human | `[CODE]` partial (`0038`) | CONF/PROP | P0 | ADM-030 | Guard applies to content publish, citation submit, Web 2.0 publish, GBP publish, on-page apply | — |

---

## DATA — DATA MODEL

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| DATA-001 | Users, roles, feature grants, skill tokens | `[CODE]` | CONF | P0 | — | Matrix enforceable without a DB round-trip | — |
| DATA-002 | Clients + business profile with the extended field set | `[CODE]`; `[RESEARCH-AUG]` | CONF | P0 | ADM-009 | All ~20 fields present and used | — |
| DATA-003 | Sites with CMS type, sealed credentials and a capability record | `[CODE]`; `[RESEARCH-AUG]` | CONF | P0 | WP-005 | Capability record queryable | — |
| DATA-004 | Audits with type, tier, status, run uuid, artefact path and scores | `[CODE]` | CONF | P0 | AUD-* | Complete per run | — |
| DATA-005 | **Audit findings normalised as rows** | gap | PROP | P1 | AUD-017 | Findings assignable, trackable, verifiable | — |
| DATA-006 | Content jobs with type, framework, target, status, published URL, cost, source pack, QA score | `[CODE]` | CONF | P0 | CONT-* | Complete per job | — |
| DATA-007 | Content versions with diff | gap | PROP | P1 | CONT-038 | Diff retrievable | — |
| DATA-008 | Page model and design profile per site | `[CODE]` | CONF | P1 | WP-006, WP-013 | Stored and reusable | — |
| DATA-009 | Topical map / topic clusters | gap | PROP | P1 | CONT-048 | Cluster structure queryable | — |
| DATA-010 | **First-class location entity** | gap | PROP | P0 | ADM-010 | Multi-location client modelled correctly | Q-8, D-9 |
| DATA-011 | Client change events (NAP, hours, services) fanning out to citations, schema, GBP and content | gap | PROP | P1 | CONT-050 | A NAP change raises tasks across all affected artefacts | — |
| DATA-012 | Citation directories (155 seeded), strategy, campaigns, submissions, handoffs | `[CODE]` | CONF | P0 | CIT-* | Catalogue complete and classified | — |
| DATA-013 | Soft delete + retention for clients | gap | PROP | P1 | ADM-008 | Off-boarding does not orphan live records | — |
| DATA-014 | Backlinks, citations, NAP records with drift state | `[CODE]` | CONF | P1 | CIT-016 | Drift queryable | — |
| DATA-015 | Web 2.0 platforms (~50 seeded), properties and publish records | `[CODE]` | CONF | P0 | WEB2-* | Catalogue complete | — |
| DATA-016 | **Web 2.0 accounts as first-class entities** with platform, ownership, health and property count | gap | PROP | P0 | WEB2-008 | Footprint queryable per account | D-5 |
| DATA-017 | Anchor profile per client | gap | PROP | P1 | WEB2-014 | Distribution reportable | — |
| DATA-018 | Indexing submissions with per-URL status history | `[CODE]` `0061` | CONF | P1 | IDX-004 | History queryable | — |
| DATA-019 | Policy sources, KB entries (versioned, hashed, flagged), change events, recommendations | `[CODE]` | CONF | P1 | AI-004 | Every entry versioned and sourced | — |
| DATA-020 | Cost dials, budgets and a cost log holding **actual** cost | `[CODE]` | CONF | P0 | ADM-025 | No estimate displayed as a cost | — |
| DATA-021 | Append-only activity log | `[CODE]` | CONF | P0 | ADM-032 | No path bypasses it; never truncated | — |
| DATA-022 | Task and content lifecycles enforced by database triggers | `[CODE]` | CONF | P0 | TEAM-002, CONT-034 | Illegal transitions rejected at the DB | — |
| DATA-023 | Vault secrets with agency and per-client scope | `[CODE]` | CONF | P0 | SEC-003 | Scope enforced | — |
| DATA-024 | RLS on every table; two explicit connection seams | `[CODE]` | CONF | P0 | SEC-004 | A build check refuses to ship if a table is unprotected | — |
| DATA-025 | Milestones, upsells, notifications, tickets, settings, backups, reports, scheduled job runs | `[CODE]` | CONF | P1 | — | Present and used | — |
| DATA-026 | Migration hygiene: no duplicate numbers, forward-only, reversible where possible | `[CODE]` defect | CONF | P3 | — | `0070`/`0072` collisions resolved | — |

---

## MT — MULTI-TENANCY AND SCALE

| ID | Requirement | Source | Class | Pri | Depends | Acceptance criteria | Open Q |
|---|---|---|---|---|---|---|---|
| MT-001 | Client isolation enforced at the database | `[CODE]` | CONF | P0 | SEC-004 | Verified test | — |
| MT-002 | Location isolation within a client | gap | PROP | P1 | DATA-010 | Verified test | Q-8 |
| MT-003 | Credential isolation per client | `[CODE]` | CONF | P0 | SEC-023 | Verified test | — |
| MT-004 | Per-client job concurrency caps | scale | PROP | P0 | AUTO-015 | One client cannot starve the queue | D-3 |
| MT-005 | Per-client spend caps and a global daily stop | `[CODE]` | CONF | P0 | ADM-026 | Enforced and tested | — |
| MT-006 | Per-client rate limiting against shared providers | scale | PROP | P1 | INT-003 | Enforced | D-3 |
| MT-007 | A failure for one client cannot corrupt another's data or workflow | principle | CONF | P0 | MT-001…MT-006, WEB2-008 | Chaos test at the account and queue level | D-5 |
| MT-008 | Backups cover the database **and** the artefact store | gap | PROP | P0 | AUTO-023 | Restore includes reports and screenshots | — |
| MT-009 | Documented, tested disaster recovery with a stated RTO and RPO | gap | PROP | P0 | MT-008 | A full restore exercised | — |
| MT-010 | Server-side pagination, search and bulk selection everywhere | scale | PROP | P1 | ADM-039 | Usable at 500 clients | D-3 |
| MT-011 | Pre-aggregated rollups rather than per-page-load computation | scale | PROP | P1 | ADM-001 | Dashboard within budget at volume | D-3 |
| MT-012 | Bulk client onboarding by import | scale | PROP | P1 | `[CODE]` data_import | 100 clients imported with sites and keywords | D-3 |
| MT-013 | Browser-worker fleet separate from the API host | scale | PROP | P0 | CIT-009 | Citation volume does not degrade the API | D-3 |
| MT-014 | Human review throughput and queue depth measured as first-class metrics | scale | PROP | P1 | OPS-003 | Reported on the dashboard | Q-25 |

---

## PERF — PERFORMANCE

| ID | Requirement | Source | Class | Pri | Acceptance criteria |
|---|---|---|---|---|---|
| PERF-001 | Dashboard interactive < 1.5s on cached rollups | PROP | P2 | Measured |
| PERF-002 | Instantaneous screen switching across all modules | `[WA-TEAM]` 28/07 | CONF | P1 | No perceptible delay |
| PERF-003 | Visible loader on every search or transition | `[WA-TEAM]` 28/07 | CONF | P2 | Present |
| PERF-004 | API p95 < 300ms on read endpoints | PROP | P2 | Measured |
| PERF-005 | Never block the event loop; sync DB seams offloaded | `[CODE]` | CONF | P1 | Enforced |
| PERF-006 | Redis caching on expensive provider responses | `[CODE]` | CONF | P1 | Hit rate reported |
| PERF-007 | Responsive on all device sizes; no horizontal scroll | `[WA-ADAN]` 01/08 | CONF | P1 | Verified at three widths |
| PERF-008 | Bulk operations report progress and are cancellable | PROP | P1 | Demonstrated |
| PERF-009 | The system stays responsive during a bulk run | PROP | P1 | Load test |
| PERF-010 | Audit wall-clock estimated to the operator before starting | PROP | P2 | Shown |

---

## OPS — OBSERVABILITY AND ERROR HANDLING

| ID | Requirement | Source | Class | Pri | Acceptance criteria |
|---|---|---|---|---|---|
| OPS-001 | Correlation id spanning request → job → external call | PROP | P0 | One id traces a full workflow |
| OPS-002 | Every job emits start, end, duration, outcome and cost | PROP | P0 | Present in logs |
| OPS-003 | Per-provider metrics: calls, errors, latency, quota, spend | PROP | P1 | Dashboard surface |
| OPS-004 | Queue health: depth, oldest age, failure rate, dead-letter count | PROP | P0 | Dashboard surface |
| OPS-005 | Alerting on failure rate, spend near cap, provider down, backup failed, queue backed up, stale review queue | PROP | P0 | Each alert fires in a drill |
| OPS-006 | Error taxonomy surfaced in the UI: client / provider / ours | `[OVERHAUL]` §K | CONF | P1 | Every failure attributed |
| OPS-007 | Data-freshness indicators wherever a number is shown | CONF/PROP | P1 | Present |
| OPS-008 | Liveness vs readiness distinction; a not-configured provider does not fail readiness | `[CODE]` | CONF | P1 | Verified |
| OPS-009 | Operator runbook per failure mode | PROP | P0 | Exercised by someone other than the author |
| OPS-010 | Log retention ≥ 90 days | PROP | P1 | Configured |
| OPS-011 | Weekly automated self-audit: which capabilities have not run successfully in 7 days | PROP | P0 | Report produced |
| ERR-001 | Degrade, never crash | `[CODE]` | CONF | P0 | Injected failures hold, not crash |
| ERR-002 | Never fake success — a job that could not do the work is failed or blocked | `[OVERHAUL]`; `[CODE]` | CONF | P0 | Negative tests |
| ERR-003 | Every failure carries the next action | PROP | P1 | Present on every failure state |
| ERR-004 | Never offer an artefact that has not been verified to exist | `[CODE]` | CONF | P0 | Negative test |
| ERR-005 | A report refuses to build on incomplete data rather than omitting a section | PROP | P1 | Negative test |
| ERR-006 | Every failed job retryable from the UI by an authorised human, logged | PROP | P1 | Demonstrated |
| ERR-007 | Submissions and publishes never blind-retried; verify first | PROP | P0 | Negative test |

---

## QA — QUALITY GATES (apply to every requirement above)

| ID | Gate | Applies to | Acceptance |
|---|---|---|---|
| QA-001 | Functional success — the complete workflow produces the business outcome | All | Recorded end-to-end run on real data |
| QA-002 | Data success — what was written is correct, complete, consistent, queryable | All | Post-run assertions |
| QA-003 | UX success — the intended role completes it unaided and can recover from failure | All | Walkthrough by a non-builder |
| QA-004 | Error handling — every named failure mode degrades correctly and actionably | All | Each mode deliberately triggered |
| QA-005 | Security — permissions server-side, secrets contained, isolation holds | All | Negative test per boundary |
| QA-006 | Performance — within budget at expected volume, no starvation | All | Measured |
| QA-007 | Observability — an operator can tell it works and diagnose it when it does not | All | Logs, metrics, status surface |
| QA-008 | Testing — unit + integration + one true end-to-end path | All | Green in CI |
| QA-009 | User acceptance — the owner ran it at volume and accepted it | All | §27.3 volume bar met |

---

## COVERAGE SUMMARY

| Group | IDs | P0 | P1 | P2 | P3 |
|---|---|---|---|---|---|
| ADM | 40 | 12 | 17 | 5 | 6 |
| TEAM | 18 | 2 | 11 | 5 | 0 |
| CLIENT | 15 | 3 | 7 | 3 | 2 |
| AUD | 26 | 8 | 12 | 5 | 1 |
| CONT | 52 | 13 | 27 | 12 | 0 |
| WP | 38 | 9 | 22 | 7 | 0 |
| CIT | 27 | 12 | 12 | 3 | 0 |
| WEB2 | 17 | 7 | 8 | 2 | 0 |
| IDX | 5 | 0 | 4 | 1 | 0 |
| AI | 16 | 7 | 7 | 2 | 0 |
| AUTO | 26 | 9 | 14 | 3 | 0 |
| SEC | 25 | 12 | 10 | 3 | 0 |
| DATA | 26 | 12 | 10 | 3 | 1 |
| MT | 14 | 6 | 8 | 0 | 0 |
| PERF | 10 | 0 | 6 | 4 | 0 |
| OPS/ERR | 18 | 9 | 8 | 1 | 0 |
| QA | 9 | — gates, apply to all — | | | |
| **Total** | **382** | **121** | **183** | **59** | **10** |

**Requirements blocked on a decision:** 31 across D-1 to D-15.
**Requirements blocked on an open question:** 24 across Q-1 to Q-25.

**Recommended first wave — the 12 highest-leverage P0 items, none of which depend on an unanswered question:**
AUTO-001 (restore the schedule) · ADM-025 + ADM-026 + ADM-027 (truthful cost control) · ADM-003 + ERR-004 + CLIENT-011 (no dead controls, no phantom artefacts) · AUTO-009 (visible cost blocks) · AUTO-004 + CONT-040 (idempotency) · SEC-016 + SEC-017 (credential rotation and export removal) · ADM-009 (business profile at client creation, unblocking citations).
