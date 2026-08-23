# DECISIONS LOG — Daniel Project Recovery

Owner decisions as made, in the owner's own words where the wording matters.
Each entry supersedes the corresponding item in `DECISIONS_REQUIRED.md` and the
corresponding conflict in specification §30.

---

# 2026-08-23 · Zain Saeed (project owner)

## ✅ D-1 · Delivery shape — **HYBRID: a complete, verified v1, then v1.1**

**Decided:** ship a fully verified v1, hand it to Danyal, then build the remainder as v1.1.

> *"For now, we stay limited to the full stack portal, audit, full stack content system, citations, and Web 2.0. This will be in version 1, and once it is done, we will ship it to Danyal. After that, if there is anything else that I have committed as well, we will build after that."*

> *"Whatever you find in the text that I have given to you via the chat and meetings, and you think that I have committed that thing to him, we should include it."*

### THE V1 SCOPE BASELINE — five modules

| # | Module | What it covers |
|---|---|---|
| **1** | **Full-stack Portal** | Admin / Super-Admin, Team, Client (Manager optional). 6 staff roles + client, 17-feature matrix, owner-only provisioning, task queue, review checkpoint, milestones, notifications, activity log, settings, cost control, key vault. |
| **2** | **Audit** | Free (condensed, ~10–15 pages, public lead magnet) and Paid (type-selectable, full multi-agent + narrative). HTML viewer and PDF from one source. Findings JSON, remediation sheets. |
| **3** | **Full-stack Content System** | Research module → page-set recommendation → bulk fan-out → drafting → QA → human review → WYSIWYG edit → **WordPress publish as genuinely editable, design-matched pages** (Elementor / Gutenberg). Includes the whole WordPress subsystem: connection, capability discovery, plugin, SEO surface, performance budgets, versioning, revert. |
| **4** | **Citations** | Business profile + canonical NAP → citation audit → gap analysis → prioritised directory set → per-client account creation → submission → proof → status → re-verification. Target ~100 valuable platforms. |
| **5** | **Web 2.0** | ~50 platforms, tiered account ownership, unique content, human-paced publishing, lead approval, account health. **Run per-client / per-campaign on demand, not as standing delivery for every client** (see D-16). |

### Deferred to v1.1 — "anything else I have committed"

Everything evidenced as committed to Danyal but outside the five: **GBP posts** (`[OVERHAUL]` §J), **Indexing module** (`[RESEARCH-AUG]`), **Backlink monitoring**, **Google Sheets reporting layer**, **Financial audit report** (already Phase 2 at kickoff), **Fiverr client-data import**, and additional CMS connectors.

### ⚠️ One item needs an explicit call: Policy Radar

Policy Radar is **not** in the five, but it was delivered to Danyal on 9 July as **Module 04 of four** in the Platform Overview, and the architecture calls it mandatory platform core. Shipping v1 without it means shipping 3 of 4 advertised modules.

**It is also already built** and currently runs on demand only — restoring its daily schedule is a one-line change (`_BEAT_SCHEDULE_DISABLED` → `beat_schedule`).

**Recommendation:** keep Policy Radar in v1 at its already-built level with the daily scheduler restored. Cost is near zero; the alternative is an unexplained gap against a document the client holds. **Flagged, not decided.**

### Superseded

- Specification §30.4 (off-page scope) — **resolved: citations and Web 2.0 are both in v1.**
- The earlier same-session answer placing Citations in v1.1 — **superseded by the more specific statement above.** Citations are v1.
- "35 days" in the transcript was a voice-transcription error for "Web 2.0". **There is no 35-day commitment.** The v1 date remains as previously extended and is recorded as still needing a written re-baseline with the client.

---

## ✅ D-16 · Web 2.0 runs per-client / per-campaign, not for everyone

**Decided:** Web 2.0 is on-demand delivery for selected clients and campaigns, not a standing service every client receives.

**Effect:**
- Acceptance criteria change: **no blanket 50×10 volume bar for Web 2.0.** Instead: prove the pipeline end-to-end on a representative campaign set, with the safety gates enforced.
- The client portal must not imply Web 2.0 is running for a client who is not on a campaign.
- Per-client account provisioning (D-5) happens **at campaign start**, not at onboarding — which materially reduces the onboarding cost noted in D-5.
- `WEB2-001` ("50+ platforms with live publishing") stays P0 as a *capability* target; per-client coverage is campaign-scoped.

---

## ✅ D-3 / Q-1 · Client scale — **50–100 now, architected to scale far beyond**

> *"We should make it super capable, but for now we can have somewhere around 50–100 clients. It should be scalable up to so much bigger. At that moment, we will upgrade the VPS and those kinds of things."*

**Build now (design-for-headroom — cheap now, painful to retrofit):**

| ID | Requirement | Priority |
|---|---|---|
| `MT-004` / `AUTO-015` | Per-client job concurrency caps | **P0** |
| `MT-010` / `ADM-039` | Server-side pagination, search, bulk selection everywhere | **P1** |
| `MT-011` | Pre-aggregated rollups, not per-page-load computation | **P1** |
| `MT-012` | Bulk client onboarding by import | **P1** — 100 clients is not viable by hand |
| `MT-006` | Per-client rate limits against shared providers | **P1** |
| `MT-013` | Browser-worker placement **config-driven and separable** from the API host | **P1 as a design property** (P0 deployment once citation volume is real) |

**Explicitly deferred:** multi-region, sharding, read replicas, horizontal database work. Revisit above ~500 clients. VPS sizing stays as-is; capacity is **monitored** (`OPS-003`, `OPS-004`) rather than pre-purchased, with a documented upgrade trigger.

**Quota consequence — these were sized for 15 clients and will not survive 100:**
- **serper.dev** free tier is 2,500 searches/month *in total*. At 100 clients this needs a paid plan. **Cost it before v1.**
- **Google Indexing API** daily quota needs measuring against expected publish volume.
- **Google Sheets** write quota — verify the existing Redis write-buffer under 100-client load.
- **CAPTCHA solver and proxy** balances become a real recurring line at citation volume.

---

## ✅ D-2 · Citation cost — **10¢ marginal target · 20¢ hard fail line · loaded cost disclosed**

**Decided:** engineer to ≤10¢ marginal per successful citation; 20¢ is the hard fail line; report loaded cost separately and proactively.

**Effect:**
- `CIT-013` runtime per-unit cost accounting — **P0**, measured against both lines.
- `CIT-014` loaded-cost model (human handoff minutes, proxy bandwidth, CAPTCHA balance, browser compute) — **P0**, promoted from PROPOSED to accepted.
- `CIT-015` **Apify (25¢) banned as a default path** — permitted only as an explicitly approved fallback with its cost visible per unit. This aligns with Danyal's own costing concern raised 2026-08-04.
- **Action:** tell Danyal the 17 July "Under 10¢" figure was a *marginal* cost, before he discovers it. Disclosing it is a credibility gain; being found out is a dispute.

---

## ✅ D-5 / Q-5 · Web 2.0 account ownership — **TIERED**

**Per-client accounts** (client's own identity, sealed per-client in the vault) on the platforms where a ban costs something and the property should carry the client's brand:
**WordPress.com · Blogger · Tumblr · Ghost · Hashnode · GitHub Pages · GitLab Pages**

**House accounts permitted** (capped and footprint-monitored) only on anonymous or low-stakes platforms:
**Telegra.ph · low-stakes Fediverse instances · throwaway-tier publishers**

**Effect:**
- `WEB2-009` resolved — the 17 July promise to the client is honoured where it matters.
- `WEB2-008` house-account footprint cap — **P0**.
- `DATA-016` Web 2.0 accounts as first-class entities (platform, ownership, health, property count) — **P0**; required to enforce the cap.
- `WEB2-017` one-time OAuth per client for WordPress.com / Blogger / Tumblr — **P1**, performed **at campaign start** (see D-16), roughly 10–15 minutes per client per campaign.
- **The existing `seed_web2_vault` CLI must be reworked.** It currently copies one house credential set into every client's vault — precisely the shared-footprint pattern being retired for the high-authority tier.

---

# Still open

| ID | Decision | Why it blocks | Recommendation |
|---|---|---|---|
| **D-17** | Is Policy Radar in v1? | It was sold as Module 04 of four; excluding it ships 3 of 4 | **Include** — already built, daily scheduler is a one-line restore |
| **D-4** | Content QA gate: hard or advisory, at what calibrated threshold | Blocks the 50-page content acceptance run — and content is the largest v1 module | Advisory + mandatory acknowledgement until calibrated on ~30 human-graded drafts, then hard |
| **D-6** | Single rankings source | Blocks rank tracking and tier definitions | serper.dev for local-pack/geo-grid; DataForSEO for organic rank; never mixed, always labelled |
| **D-15** | Authorise credential rotation for everything exposed in the WhatsApp exports | **Live security exposure** | Authorise today, independent of everything else |
| **D-14** | Adopt the 50×10 volume acceptance bar formally | Definition of done for v1 | Adopt verbatim for Audit, Content and Citations; campaign-based for Web 2.0 (D-16) |
| D-7 | Fiverr upsells in or out | Client portal surface | Keep in portal + free audit; remove only the Reports-tab instance |
| D-8 | MFA on Owner/Admin | Security posture at hand-off | Reinstate for those two roles only |
| D-9 | Multi-location modelling now or later | Depends on Q-8 | Model now if any client has >1 location |
| D-10 / D-11 | Audit-engine seam and ownership | Audit reliability; the "no lock-in" claim | Harden the subprocess contract now; decide ownership explicitly |
| D-12 | Elementor vs Gutenberg investment priority | Content output | Capability-driven; invest depth in Elementor |
| D-13 | Free audit as public lead magnet; lead ownership | Lead flow | Ship with abuse controls; confirm lead ownership |
