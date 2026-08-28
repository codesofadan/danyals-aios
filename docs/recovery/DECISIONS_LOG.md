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

---

# 2026-08-24 · Zain Saeed (project owner)

## ✅ D-18 / Q-11 / Q-12 / CLIENT-013 · The end client does **not** approve — staff approve everything

**Decided:** the end client never approves content drafts, and never approves publishing to
their own live site. A human still approves everything; that human is always agency staff.

**Read the attribution carefully, because it is not what the register assumes.**
`OPEN_QUESTIONS.md` marks both Q-11 and Q-12 **"Answerable by: Danyal."** This entry is the
*project owner's* decision to settle the engineering default, not Danyal's answer. It closes the
ambiguity that was blocking Phase 3.1 and it makes the behaviour deliberate rather than
accidental. **It does not close the client conversation**, and it should not be cited later as
though Danyal had agreed it.

**This decision also declines a standing recommendation**, which is worth recording rather than
leaving to be rediscovered. Q-12 carried one: *"a one-time standing authorisation captured at
onboarding, plus per-page approval as a configurable option."* That is not built, and this
decision defers it. If Danyal wants client sign-off before anything reaches a production site,
that recommendation is the shape to revisit — it is a change request, with a per-client
configuration axis, a notification and revision loop, and an approval audit trail attached.

### Why it needed deciding rather than assuming

The Phase 3.1 plan item read *"Client capability tiers: See / Tell / Ask on, **Decide-and-approve
off by default**."* The specification records the opposite kind of statement: §12.3 marks client
approval of content drafts (line 766) and of publishing to their own site (line 767) as
**UNKNOWN**, and `REQUIREMENTS_TRACEABILITY.md` classes CLIENT-013 as **UNK**, acceptance
criteria *"Per owner decision."* No entry in this log resolved either question
(`grep -c "Q-11|Q-12"` returned **0**).

So "off by default" was a plan assertion standing over a recorded UNKNOWN. Implementing it would
have settled a commercial question by writing code — the same failure as the always-loaded
`backend/CLAUDE.md` claim of a "17-feature matrix" that was really 11, one level up: not a wrong
number, but a decision nobody made appearing as a fact everyone inherited.

### What is consistent with it (and what is not)

Consistent — this decision matches, and is now the stated reason for, behaviour that already
existed: specification §9.1 row 7 puts the Client cell for *Content — approve / publish* at
`—` (no access); the Service Tiers pack of 9 Jul 2026 promises *"a person approves before it
reaches the client: Yes / Yes / Yes — always, never skipped"*; and the client portal's only two
writes are `POST /portal/audits` and `POST /portal/requests`, neither an approval.

Not consistent, and now corrected: the client role's inability to approve was enforced **nowhere**
— it fell out of a client holding no permissions at all. "Off by accident" and "off by design"
are indistinguishable until someone adds a route. `app/rbac/matrix.py` now carries
`CLIENT_MAY_APPROVE = False` citing this decision, and
`tests/test_rbac_single_source.py::test_a_client_never_approves_and_the_portal_offers_no_way_to`
fails if a client-facing approval or publish route is ever added — which is the moment to
reopen this entry, not the moment to discover it was never written.

## ✅ D-19 · The agency's access model is staff-only; tier pricing stays client-readable

**Decided:** `GET /rbac/{features,permissions,roles,templates}` return **403** to a portal
client. `GET /tiers` and `/tiers/feature-areas` remain readable by a client.

**The split is deliberate.** The access model — 8 permissions × 6 roles, 17 features, and every
role template's grants — is the agency's internal structure and has no client-facing purpose;
the portal never renders it. Tier and price data does have one: the client portal sells upsells,
and the delivered access matrix lists *"Click Fiverr upsells"* as a client capability. Locking
both would have been tidier and would have broken a product surface.

**What this fixes.** Specification invariant **PM-3** — *"A client can never reach a staff
route"* — is marked **CONFIRMED, "enforced + tested."** On 2026-08-24 it was false: 21 routes
carried `CurrentUserDep` and nothing else, and `tests/integration/test_route_contracts.py` pinned
`/rbac/features` at **200 for a client** under a section header reading `# --- rbac reference
(CurrentUserDep) ---`. The contract had recorded the guard that existed rather than the guard
that was wanted.

**The finding worth keeping.** The exposure was bounded, and the reason is instructive: wherever
a database was involved the line held anyway. `GET /clients` returns **zero rows** to a client —
`clients_select` is `using (public.is_staff())` (`0003_clients_sites.sql:67`), and
`0010_client_portal.sql:69` records deliberately that no client select policy exists on
clients/sites/audits. So no MRR or client data ever leaked. The gap was exactly the routes that
serve **in-process constants**, where no query runs and RLS never gets a chance to act.

**RLS is the guard nobody has to remember. It failed precisely where there was no database** —
which is the argument for `require_staff()` being the app-layer twin of the `is_staff()` policy,
rather than a permission check invented per route.

### Extension applied the same day: `/cost/pricing`

The AST sweep that measured the guards found a **sixth** constant-serving route after this
decision was taken: `GET /cost/pricing` returns `provider_pricing(settings)` — the per-provider
unit prices the agency pays its suppliers — to any signed-in principal, with no query and so no
RLS. It is consumed only by the operator cost screen
(`frontend/components/cost/CostDial.tsx`); no client-portal surface reads it. **Locked to staff
under this decision's own reasoning** — what the agency *pays a supplier* has no client-facing
purpose, unlike the tier prices a client is *charged*. Flagged as an extension rather than folded
in silently, because the decision as put to the owner named five routes and this is a sixth.

### Measured 2026-08-24, and one classification was wrong

The 14 handlers carrying `CurrentUserDep` alone were recorded here as *"bounded by RLS, not
measured."* They have now been measured, against a built PostgreSQL 16: all 85 migrations
applied, two client tenants seeded, and the app's own identity mechanism reproduced exactly —
role `authenticated`, `select set_config('app.user_id', <uuid>, true)`, which is what
`rls_connection` does.

**Every table those handlers read returned ZERO rows to a portal client, and all rows to staff:**
`clients`, `sites`, `client_business_profiles`, `client_report_grants`, `client_budgets`,
`cost_dial`, `cost_log`, `cost_settings`, `activity_log`.

**And one handler was not bounded at all.** `cost.py::get_dial` reads an RLS-protected table but
merges the result with an **in-process catalogue**: with the policy returning zero rows,
`merge_dial({})` still returns **18 items** — every metered feature the platform has, each naming
the **provider** behind it. The table was protected; the response was not. *A route that serves
constants is never RLS-bounded, whatever its table does* — the same lesson as `/rbac/*`, found a
second time by measurement rather than by reading.

**Consequently the whole `cost.*` read surface is now `require_staff()`** — `get_dial`,
`get_spend_stop`, `list_budgets`, `list_cost_log`, alongside `get_pricing`. Three of the five were
genuinely RLS-bounded; locking them costs nothing and none has a client-portal consumer (every
caller is the operator cost screen). **This extends the decision a second time and is flagged,
not folded in.**

**Population: 14 → 10.** What remains, each on evidence:

| class | handlers | basis |
|---|---|---|
| RLS-bounded (**measured**) | `clients.list_clients`, `get_client`, `get_client_business_profile`, `get_report_grants`, `list_sites`; `activity.list_activity`; `tiers.list_tier_clients` | zero rows to a client against a built database |
| open by decision | `tiers.list_tiers`, `tiers.list_feature_areas` | D-19 — the portal sells upsells |
| open by design | `auth.logout` | a caller must be able to end its own session |

RLS-bounded still means *the database refuses, not the app layer*. That is a real guarantee — it
held throughout — but it is one an app-layer reading cannot confirm, so it is recorded here as
measured, with the date, rather than left to be re-derived or taken on trust.
