# AIOS Product Overhaul — Backlog & Execution Plan

Master spec captured from the operator walkthrough (2026-07-23). White-label SEO
dashboard + AI SEO system. This file is the single source of truth for the overhaul;
each item is tracked to done. Grouped by area, then sequenced into phases below.

> Hard rule reaffirmed: the word **Xegents** (X-E-G-E-N-T-S) must NEVER appear
> anywhere in the software — admin, team portal, client portal, user pages, code,
> or generated output. This is a white-label product for another company; no
> builder branding. Product wordmark = **AIOS** (neutral); agency name is
> operator-configurable in Settings.

## A. Branding / white-label  — IN PROGRESS
- [ ] Remove every "Xegents" reference from the software (runtime + config + tests).
- [ ] Agency name / support email operator-set; no hard-coded builder brand.

## B. Repo structure · skills · knowledge base
- [ ] Move all skills into `.claude/skills/` (from `aios-skills/skills/`). Many small
      skills, one per feature, simple names: service-pages, local-area-service-pages,
      blogs, content, citations, backlinks, gmb-posts, etc. Split modules → own skill.
- [ ] Knowledge-base folder: one `.md` per topic; Claude Code AND the dashboard read
      the KB first to learn what exists / how each thing should work. System operates
      off that KB.
- [ ] Folder cleanup: shrink/remove `design/` (15 files, planning artifacts);
      consolidate `aios-skills/` into `.claude`. (NOTE: `aios/`, `daniyals-frontend/`,
      `github/` already don't exist — operator memory was of an older layout.)

## C. Dashboard — cross-cutting
- [ ] NO hardcoded data anywhere (admin, team, client). Every metric live — incl. costs.
- [ ] Admin header: drop "SEO Automation Agency Overview" subtitle; keep short.

## D. Policy Radar
- [ ] Live, auto-updates DAILY. Source = Google policy updates (prefer official Google
      policy APIs if free). Claude Haiku categorizes each update (urgent / informational
      / …). Not static, not baseline-coded.  [investigation running]

## E. Cost Control  (high priority — currently feels like a demo)
- [ ] NO predefined/fixed prices anywhere. Remove the fixed $1.50 audit estimate and
      every hard-coded cost. Cost is computed at RUNTIME only.
- [ ] When provider spend is halted → EVERY API (internal + external) auto-stops.
- [ ] Provider toggles / manual mode / API mode must actually work (not demo).
- [ ] Strengthen the whole section.

## F. Features page (admin)
- [ ] Keep only genuinely important items per module; remove filler.
- [ ] A feature (e.g. Backlinks) must RUN real work (backlink audit, citation audit,
      improvements), not just describe itself.

## G. Free Audit page
- [ ] Replace the 4 demo Fiverr gigs with Daniyal's REAL Fiverr gigs.
- [ ] Remove the "Focus Areas" field. Always audit everything.
- [ ] Condensed report (~10–15 pages max), not the 400-page paid one.
- [ ] ONE complete condensed audit — no Technical/On-Page/Off-Page/Actionable split.
- [ ] Download option after completion.
- [ ] HTML preview inside the dashboard: PDF-viewer-like with next/prev page controls;
      same report content as the PDF.  [investigation running]

## H. Audit module (admin)
- [ ] On start (URL + client) ask which audit type(s): Off-Page, On-Page, Local SEO,
      AI Analysis, etc. None selected → run ALL. One selected → only that one.
- [ ] Filters reflect the audit types.
- [ ] Remove the "Audit Coverage" section at the bottom.
- [ ] PDF report UI must MATCH the dashboard HTML preview EXACTLY — same UI, structure,
      layout, writing style, content as the Claude-Code-generated report. Stronger
      reports now that more APIs are wired. Same layout for free & paid. Writing style:
      direct on the issues, client-friendly.

## I. Content pipeline
- [ ] AI-sounding guard: detect over-AI content, esp. em dashes. ZERO em dashes anywhere
      on the site. On failure, rewrite section-by-section with local-SEO copywriting
      frameworks.
- [ ] Generate images, create drafts, check layouts, pick the better layout → Review.
- [ ] Review: proper preview, HTML embedded in dashboard (preferred) or PDF.
- [ ] Publishing: on approval + WordPress connected → auto-publish; show live URL; allow
      immediate test.

## J. Google Business Profile (GMB) — NEW section
- [ ] GMB post generation: operator prompts AI to generate GMB posts following Google
      policies / frameworks / rules / best practices.

## K. Citations & Web 2.0
- [ ] Fix the flow; better UI. Citation submit currently shows FAILED — fix.
- [ ] "No business profile yet for this client" — fix by collecting NAP/business info at
      client creation; Citations then auto-fetches stored info.
- [ ] Citation Builder: analyze existing citations (count + where) → find missing →
      create ONLY where not listed → show all citation URLs. Fully functional, no dummy.
- [ ] Web 2.0: show connected vs missing APIs (checkmarks), reason per issue (flag when
      it's the external API's fault, not ours). Production-ready.

## L. Clients
- [ ] Add / Delete / Update. Login credentials with COPY buttons.
- [ ] Invite: either actually send invite emails via Resend, OR remove Invite (manual
      credential share).
- [ ] Collect all business info + NAP at client creation (feeds Citations & Local).

## M. Team
- [ ] Fix task assignment — team members don't appear correctly.
- [ ] Review every tab & function in Team Management.
- [ ] Performance: team-member updates reflect immediately in metrics.

## N. Reports
- [ ] Remove demo info. Real data from cron jobs.
- [ ] Show which cron jobs run, what they do, when they're scheduled.
- [ ] Remove the Upsells section (for now).

## O. API Management
- [ ] Remove the "Rotate Key" option.
- [ ] Strengthen. Show every connected API + which are missing.

## P. Settings
- [ ] Remove: Two-Factor Auth, Change Password, Security, Workspace.
- [ ] Keep: Client Access, Team Access, Roles, Permissions — show only implemented features.

## Q. Email notifications
- [ ] Currently OFF. Enable every required email notification across the dashboard (Resend).

---

## Execution phases (proposed)

**Phase 0 (in flight now):** A branding removal; D+G investigation.

**Phase 1 — quick, safe UI removals (low risk, high visible progress):**
C (header subtitle), G (remove Focus Areas + demo Fiverr → real gigs), H (remove Audit
Coverage), N (remove Upsells), O (remove Rotate Key), P (trim Settings tabs).

**Phase 2 — Free Audit end-to-end:** G (single condensed report + download + in-dash
HTML page-viewer preview) — depends on the report-layout unification in H.

**Phase 3 — Audit module:** H (type picker: none=all, filters, unified PDF/HTML report UI).

**Phase 4 — Cost Control truthfulness:** E (kill hardcoded prices, runtime cost, hard
spend-stop across all providers, working toggles/manual/API modes).

**Phase 5 — Live Policy Radar:** D (Google sources + Claude Haiku daily categorization).

**Phase 6 — Citations & Web2 + Clients NAP:** K + L (NAP at client creation, real
citation gap-analysis, Web2 API status board).

**Phase 7 — Content pipeline + GMB:** I (AI/em-dash guard, section rewrite, layouts,
review preview, WP auto-publish) + J (GMB posts).

**Phase 8 — Team + Reports + Notifications:** M + N (cron-driven real reports) + Q (Resend emails).

**Phase 9 — Structure + KB + skills:** B (skills → .claude, KB folder, folder cleanup).
Deliberately near-last: it's a behavior-preserving reorg and safest once features settle.

**Cross-cutting (every phase):** C — replace any hardcoded/demo data touched with a live
source; never leave a new hardcoded number behind.
