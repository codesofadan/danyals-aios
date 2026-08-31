# R1b — Response to the "Citation Automation System" product brief

**Track:** R1 · Citation route (follow-on)
**Status:** Advisory — answers a client-supplied brief; does not supersede R1
**Date:** 2026-08-29
**Parent record:** `docs/research/R1-citation-route.md` (2026-08-23, *Decided — gates the Citation rebuild*)
**Reader-facing version:** published Artifact, "Before You Build Citations"

---

## 0. Why this record exists

The client supplied a 26-section *Citation Automation System — Product & Technical Brief*
proposing a human-in-the-loop citation platform with a Chrome MV3 extension as the execution
layer. This record answers it against the repository at HEAD and against R1's live
measurements, so the brief can be actioned without re-deriving either.

**R1 was decided and never implemented.** `git log --since=2026-08-22` shows zero commits
against `backend/app/modules/citations/`, `backend/integrations/citation_*.py`, or any citation
migration. All 34 of R1 §8's engineering requirements are outstanding, including the one it
called "the highest-priority single fix in the track".

---

## 1. What the brief gets right

Not to be re-litigated:

- Human-in-the-loop rather than an autonomous bot — matches the standing L3 ceiling.
- Deterministic code for CRUD, field mapping, selectors, validation, queue management and
  state transitions; AI only for research, NAP normalisation, duplicate reasoning and category
  mapping (brief §18). This is already how the module is built.
- Versioned, replaceable directory adapters rather than one monolithic script (§9). Right in
  principle; §3.3 below corrects *where* they live.
- Start with 5–10 directories and measure before scaling (§22, instructions 22–23). R1 reached
  the same conclusion independently from live measurement.
- **"The most important metric is cost + human time per successful live citation, not merely the
  number of attempted submissions" (§23).** The best line in the brief, and the axis the whole
  build should be judged on.

---

## 2. What already exists — measured at HEAD

| Brief asks for | Repository | Verdict |
|---|---|---|
| Canonical Business Profile (§4A, instr. 6) | `public.business_profiles` — `0045`, `0060`, `0051`; multi-location NAP, `hours jsonb`, `categories text[]`, socials, `nap_locked` | Built |
| Directory Registry (§8, instr. 7) | `public.directories` — **226 distinct rows** (`0045`/`0046`/`0065`/`0067`), enriched by `0048` with `authority`, `authority_tier`, `access`, `is_marketplace`, `verticals` | Built |
| Citation Audit (§5, instr. 8) | `backend/integrations/citation_discovery.py` (904 lines) — Places anchor → Serper → Foursquare → optional Firecrawl → Claude classification, deterministic fallback, degrades never raises | Built; R1 §3.8 calls it the best code in the module |
| Opportunity scoring (§7) | `backend/app/modules/citations/service.py` — vertical match, `DEFAULT_MIN_AUTHORITY = 30`, marketplace gate, core→tier1→tier2 order, `DEFAULT_CAMPAIGN_CAP = 45`, counted exclusion per filter | Built |
| Job state machine (§13, instr. 9) | `citation_submit_status` (8 values incl. `ready_for_human`); transitions in `citations/tasks.py:87-204` | Built |
| Durable queue (§13) | Celery `task_acks_late` + always-ack; job contract at `backend/app/jobs/` (idempotency, retry, DLQ, per-client caps) | Built |
| Security requirements (§21) | RLS `ENABLE + FORCE` CI-gated by `app/db/rls_check.py`; Ed25519 JWT, 6 roles, 17 features; AEAD vault; `record_activity()` on mutations | Built |
| Cost control (§21, §23) | `app/services/cost_gate.py` — halt → dial → cache → cap → call → log; `citations` registered in `DIAL_FEATURES` | Built |

Volume: **~4,800 lines** of citation backend, **~2,500 lines** of citation tests, **~910 lines**
of finished frontend components.

**Instructions 6–9 of the brief are therefore already satisfied.** Instruction 1 — "first
inspect the existing AIOS repository" — is the one that matters.

---

## 3. Corrections

### 3.1 The stack section (§20) is wrong

Backend is **Python 3.11 / FastAPI / Celery / raw psycopg3** with hand-written ordered SQL
migrations (`db/migrations/0000` → `0105`). No ORM, no Alembic, no Node, no BullMQ. Frontend is
Next.js 15.5 App Router with **no Tailwind and no component library**. Building to §20 as
written produces a second platform.

### 3.2 LangGraph (§19): no

The proposed reasoning layer (audit → research → competitor → scoring → reasoning → human
review) is already deterministic Python plus one Claude classification call. No multi-step
agentic loop exists for a graph to orchestrate. Adoption costs: a dependency tree deliberately
excluded for resolver weight (`backend/pyproject.toml:51`), a second orchestration model
competing with `@aios_job`, and no new capability. The brief's own §18 rule — deterministic
code for state transitions — argues against its §19.

### 3.3 Adapters belong in the database, not in Python

`FORM_SPECS` (`backend/integrations/citation_bot.py:196-875`) holds 50 specs **in source**. A
spec is data, and specs rot — R1 §3.3 found 3 of the 50 point at directories that have been
acquired, absorbed or renamed. A `directory_specs` table lets a spec be verified, dated,
deactivated on drift, and added by an operator without a deploy.

### 3.4 "50+ directories" (§1) is not achievable and is not the right target

R1 §3.3, measured 2026-08-23:

| Probe | 2xx | 403 (WAF) | 404 | dead |
|---|---|---|---|---|
| 50 coded `FormSpec` URLs | **7** | **29** | **8** | **6** |
| 86 researched `signup:` URLs | **36** | **42** | **8** | — |

Hand-verified specs: **0**. Directories that have ever produced a proven live listing: **0**.

A 403 to a scripted client is the platform's answer, and clearing it is the anti-bot evasion
already ruled out — including by the brief's own §15. Separately (R1 §3.10) citation signals
are **~6%** of local pack weight and falling, and Google's spam policies (updated 2026-05-15)
name "low-quality directory or bookmark site links" as link spam.

**Target instead: 45–65 attempted, 35–50 live per client in 60 days, per market, with every
skipped row explained** (R1 §6).

### 3.5 Several major directories are prohibited in writing

Hand-verified primary sources (R1 §3.7): Yelp ToS §7.2(j) plus a blanket `robots.txt` disallow;
Trustpilot's definition of "you" expressly including "automated technologies such as AI agents
or screen scrapers"; Houzz §4. **An anti-scraping clause binds a form-filling bot**, because
the bot must GET the form before filling it. This must be a hard block in the worker, not a UI
warning — and the catalogue currently contradicts it (`Yelp for Business` US is seeded
`bot_fillable`).

### 3.6 Auto account creation + IMAP (§12, §14, instr. 13) is the wrong second step

Fastest route to banned accounts; most explicitly forbidden by directory terms; unnecessary
once the operator is in the loop. `SIGNUP_SPECS` has **one** entry today.

**New finding, verified 2026-08-29:** `backend/integrations/citation_signup.py:196` generates a
password, fills it at `:206`, and **never persists it**. No `citation_accounts` table exists and
no citation credential is in the vault. **Bot-created directory accounts currently have
irrecoverable logins.** Fix by copying `db/migrations/0100_web2_accounts.sql:58+`, which solved
exactly this for Web 2.0.

### 3.7 §15 states the right policy; the code contradicts it

`backend/app/config.py:672` ships `captcha_solver_provider: str = "capsolver"` — a live paid
solver as the **default**, not `none`. `citation_captcha_cost_estimate = 0.006` (`:682`) budgets
for solves and `citation_bot.py:1011` calls `.solve()`. Paying a solver is the evasion §15 bans.
Under the operator model the solver and `citation_proxy_url` (`:674`) both become unnecessary.
Default the provider to `none`.

### 3.8 The brief has no concept of "live" — and that is where the current fabrication lives

No column anywhere holds a listing URL. Instead:

```
citation_bot.py:1067-1076  _screenshot returns str(path)   -> ABSOLUTE server filesystem path
      :1007                assigned to proof_url
  tasks.py:180             written to citations.proof_url
  service.py:298           copied into CitationGap.live_urls
  router.py:471            serialised as liveUrls
  CitationsTab.tsx:271-272 rendered as a KPI tile: "Live listing URLs"
              :292         under the heading "Live listings already earned:"
```

So the finished UI is a **counter of screenshots labelled "Live listing URLs", above a list of
absolute server filesystem paths headed "already earned"** — broken links and a server-layout
leak in one field. One mis-wired field and one function returning the wrong kind of string.
`liveCitationRate`, the brief's own §23 metric, is unmeasurable until it is fixed.

`frontend/parked.registry.ts:101-108` parks the UI for exactly this reason ("the module is
locked rather than shipping misleading data"). That was the right call.

---

## 4. The extension: right idea, wrong job description

§10 frames it as "the hands" — directory detection, adapter engine, workflow controller. Built
to that framing it is a bot with a nicer UI and inherits §3.4 and §3.5 entirely.

R1 §7.3 measures the loaded cost at 100 clients: **human queue time is 250 h/yr ($1,500) —
56% of loaded cost** — and names *minutes per queue item* as one of only two real levers.
Cutting queue *volume* does not move unit cost (numerator and denominator fall together);
cutting *minutes* does.

**Correct scope — operator autofill + evidence capture:** the operator opens the form
themselves in their own logged-in browser; the side panel shows the claimed item with every
field pre-computed and one Fill action; the human reviews, clears any CAPTCHA, and submits; the
extension captures the listing URL and a screenshot and posts both back.

This is a password manager's posture, not a crawler's. It sidesteps the WAF because the traffic
is a real human's real session, and it is what turns 5 minutes per item into ~90 seconds — the
difference between ~65¢ and ~40¢ per live citation.

---

## 5. Open items carried forward from R1

**O-1 — buy or build.** Moz Local Lite $199/location/yr (90+ directories, maintained,
correctable); Synup Scale $899/mo ≤50 locations with a documented API and white-label reseller
path. At 100 clients: **$19,900–$21,600/yr** vs self-build **~$2,655/yr + ~250 h/yr** of queue
work. *Settles it:* the per-client-per-month sale price, and whether the owner prefers vendor
cost or queue hours. **If "buy", most of Phases 2–4 should not be built.**

**O-2 — the Data Axle price.** The only aggregator with a verified live write API
(`POST https://local-listings-premium.data-axle.com/api/1/submissions`, A/R/U/D, 100/request,
updates free, teleresearch verification). Price published nowhere reachable. At $5/$10/$30 per
Add the Route A marginal cost is **$1.67/$3.33/$10.00 per unit** — 17×–100× the 10¢ commitment.
*Settles it:* a call to **(888) 274-5478** or an email to **contentfeedback@data-axle.com** for
the A and R rate card at ~150 records/year, plus whether an agency org may submit for
unaffiliated clients.

**To be said before the client counts:** the ≤10¢ figure is defensible only for the browser
route in isolation ($0.002/unit, compute only). The **loaded** cost is **53–65¢ per live
citation** at $5–$10 per Add. A 4–6× gap, better said now than discovered later.

---

## 6. Build sequence

Phases 0 and 1 are correct under either answer to O-1.

| Phase | Work | Gate |
|---|---|---|
| **0** | **LANDED 2026-08-29** — see §9 | done |
| **1** | **LANDED 2026-08-29** — see §10 | done |
| **2** | Operator queue as a product; `directory_specs`; `citation_accounts` + vault credentials; retire `tools/finish_citation.py` (one shared password per campaign, `:46`); measure minutes/item | O-1 |
| **3** | Chrome MV3 extension — scoped `X-Operator-Token`, server-computed field plan, evidence capture | O-1 |
| **4** | Route A spine — Data Axle / Apple / GBP; none may ever return `verified` | **O-2 (hard)** |

Full engineering detail: the approved plan at
`~/.claude/plans/i-want-a-brutul-async-frog.md`, and R1 §8's 34 numbered requirements.

---

## 7. Explicitly not doing

- **LangGraph** (§3.2).
- **A separate browser-worker VPS** — ~22 machine-hours/year, a 0.25% duty cycle; a $48/mo box
  is $0.109/unit on its own, larger than the entire 10¢ marginal commitment (R1 §7.2).
- **Paid CAPTCHA solving and residential proxies on the automated route** (§3.7).
- **Auto account creation + IMAP verification** until Phases 0–3 are proven (§3.6).

---

## 8. Sources

R1 (`docs/research/R1-citation-route.md`) for every external figure, live probe and ToS
citation; that record carries its own adversarial verification pass and its own
`[UNVERIFIED]` register.

Repository claims in this record re-resolved 2026-08-29 at branch
`recovery/p0-3-job-contract`: `backend/app/modules/citations/service.py:294-300` ·
`router.py:471` · `tasks.py:180` · `backend/integrations/citation_bot.py:196`, `:1011`,
`:1067-1076`, `:1007` · `backend/integrations/citation_signup.py:196`, `:206` ·
`backend/app/config.py:672`, `:674`, `:680-682` · `frontend/components/offpage/CitationsTab.tsx:271-272`,
`:292`, `:395-396` · `frontend/parked.registry.ts:97-108` · `frontend/lib/lockedInProd.ts:33-36` ·
`frontend/app/admin/` (no `citations/` directory) · `db/migrations/0064_citation_handoff.sql` ·
`db/migrations/0100_web2_accounts.sql:58+` · `backend/app/services/skill_tokens.py` ·
`backend/app/services/tokens.py:39` · `backend/app/core/auth.py` (no minting helper).


---

## 9. Phase 0, as built (2026-08-29)

Everything below is verified: the migration applies from an empty database, the RLS gate
passes, mypy is clean and the citations suite is green (116 tests, 45 of them new).

**`db/migrations/0106_citation_liveness.sql`** — `citations` gains `live_url`,
`live_url_verified_at`, `verification_method`, `verification_evidence`,
`next_recheck_at`, `recheck_count`, `route`, `blocked_reason`, `skip_reason`;
`citation_submit_status` gains `live`, `drifted`, `delisted`; `directories` gains
`tos_position`, `tos_clause`, `tos_source_url`, `tos_checked_at`, `robots_disallows_add`,
`add_url`, `add_url_status`, `route`. Verified against a rebuilt database:

- **16 rows are now route F** and can never be queued. Four of them
  (`Yelp for Business`, `BBB (Better Business Bureau)`, `Houzz`, `Houzz (Find Pros)`)
  were seeded `bot_fillable` — a campaign would have sent a bot at them.
- **71 rows** had their researched add-listing URL promoted out of the free-text
  `automation_note` into a real `add_url` column.
- Foursquare and Bing were demoted to `manual_only` / route C with the 404 probe and its
  date recorded in `automation_note`.

**A live defect found while writing the migration.** `Apple Business Connect` was seeded
`submit_method = 'bot:playwright+captcha'`, and `submitter_for` dispatches anything
prefixed `bot:` to the Playwright engine — so a queued Apple row would have been filled
by a bot and had its CAPTCHA paid for, against a platform whose only sanctioned write
path is an authenticated API. `Google Business Profile` was seeded `playwright`, which
matches no dispatch prefix and so blocked only by accident. Both now point at their real
(unbuilt) API engines and block cleanly.

**The fabrication is closed.** `service.py` reads `live_url` and only for
`submit_status = 'live'`; `citation_bot.py`'s `_screenshot` returns a relative key
instead of an absolute server path. Three existing tests **asserted the defect** and were
rewritten — `test_gap_missing_excludes_covered_by_id_and_name` literally asserted that
"the submitted row with a proof url surfaces as a live URL".

**`app/services/citation_liveness.py`** — the liveness ladder, pure and network-free:
unreachable host → `submitted` (a failure to look is not evidence of removal);
4xx/5xx → `delisted`; 2xx without the business name → `delisted` (the soft-404 case, and
the common one); 2xx with the name but no NAP match → `drifted`; name **and** phone or
address → `live`. Plus the re-check cadence (+3d, +14d, +60d, then monthly for route A /
`core`, quarterly otherwise) and `execute_liveness_recheck`, a bounded sweep that never
raises and holds a row rather than delisting it when the fetch fails.

**Two hard blocks in the worker**, both before the cost gate so a refused submission is
never even priced: `route = 'F'` (terms forbid it) and an unpriced aggregator row
(`data_axle_add_cost_estimate` is 0.0, which now *blocks* rather than reading as free).

**A bug caught in my own guard, and pinned.** The worker's query is `select c.*, d.…`,
so the joined row carries both `route` (the citation's own column, default `'C'`) and the
directory's. Reading a bare `route` would have read the citation's copy and the terms
guard would have silently never fired. `d.route` is now aliased `directory_route` and
`is_prohibited` prefers it.

**`skip_reason` is now a real output**, wired through `GapAnalysisResponse.skipped` to
`frontend/lib/offpage.ts`, with a test holding the backend and frontend label vocabularies
identical. A prohibited row reports its clause and source URL rather than vanishing.

**Config**: `captcha_solver_provider` now defaults to `"none"` — it shipped defaulting to
a live paid solver, which is the evasion the policy forbids. `citation_api_cost_estimate`
was deleted with the submitters it priced.

### Known limitation, pinned in a test rather than hidden

`_STREET_FORMS` in `local_seo` is US-centric, so AU/UK abbreviations (`Pde`, `Cres`, `Gr`)
do not expand and an abbreviated non-US address reads as `drifted` rather than `live`.
That is the safe direction — it under-claims, and `drifted` still counts as coverage —
but it will show as false drift across the UK and AU catalogues (48 of 226 rows). Fix by
extending the table, not by loosening the match.


---

## 10. Phase 1, as built (2026-08-29)

The module is reachable and what it reports is honest. Verified: 256/256 frontend tests,
`tsc` clean, the route compiles and prerenders, and the page was fetched from the running
dev server with every string confirmed in the served bundle.

**The redirect nobody would have found.** `next.config.mjs:126` carried
`{ source: "/admin/citations", destination: "/admin/web2" }` — so the page, the nav entry
and the components could all be correct while a rule three files away silently sent every
visitor somewhere else. `/admin/citations` returned **307 → /admin/web2** even after the
route existed. Its comment ("the module itself stays locked (no verified aggregator), so
its URL points at its nearest home") conflated a **submission path** being gated with the
**whole screen** being unreachable. Removed; the route now returns 200 and serves
`app/admin/citations/page.js`.

**A 500 I had introduced in Phase 0, caught here.** 0106 added `live`, `drifted` and
`delisted` to the Postgres enum, but `CitationSubmitStatus` — the Pydantic `Literal` the
API serialises through — still listed eight values. Nothing tied the two together, so the
**first re-check to write `live` would have failed validation and 500'd
`GET /offpage/citations`** for that client. Both the Literal and the frontend union now
carry all eleven, and `test_the_database_enum_and_the_wire_type_hold_the_same_values`
parses the migrations and holds them equal. Proven non-vacuous: removing `live` from the
Literal fails it with `db-only: ['live']`.

**The UI now separates facts that were collapsed.**

- Two tiles where there was one: **"Live — verified on the page"** (only rows whose public
  URL was fetched and found to carry the business) and **"Submitted, not yet confirmed"**.
  A third, **"Drifted or delisted"**, appears only when there is something to act on.
- `submitted` is labelled **"Sent — unconfirmed"** and is no longer styled as a success.
- A **skip ledger**: every catalogue directory not built for this client, grouped by
  reason, with the terms clause on hover and a link to the source for prohibited rows.
  This is what a client reads when they compare a promised count against a delivered one.
- No raw `authority` number is rendered — checked, and it never was, so nothing to change.

**Two stale comments corrected rather than deleted.** `lockedInProd.ts` claimed the
2026-08-27 restructure "folded Citations into /admin/web2 as a TAB; its lock card moved
with it" — neither half was true. `parked.registry.ts` claimed
`app/admin/citations/page.tsx` "renders a lock card", pointing at a file that did not
exist. The unpark entry records *why* the park no longer applies rather than vanishing.

**Guard confirmation.** With Phase 1 stashed, `parked.registry.test.ts` reports 5
unreachable components and 2 failing assertions; with it applied, 4 and 1 — the difference
being the three citation components, now reachable. (The remainder was a peer's in-flight
`content/flow/` work, since mounted.)


---

## 11. The answer-independent slice of Phase 2 (2026-08-29)

Phase 2's queue, spec whitelist and per-client credentials all assume we build listings
ourselves, so they stay behind O-1. **Two things do not**: whatever the delivery
mechanism, a client's NAP will change and listings will need correcting or removing.
Those were built.

**`db/migrations/0107_citation_corrections.sql`** — applies from empty, RLS gate green
(110 tables, all FORCE).

- **`client_change_events`** — the canonical-NAP change ledger. Editing
  `business_profiles` used to silently re-point canonical while every already-built
  listing kept carrying the old address, and nothing noticed. They do not go wrong
  gradually; they are wrong the moment Save is pressed. The edit and the fan-out are now
  one action: `PATCH /citation-builder/business-profiles/{id}` diffs the canonical fields
  **before** the write and flags every affected live listing in the same transaction.
- **`citation_removals`** — `method` is `api_delete | account_edit | support_ticket`,
  because removability is a property of the ROUTE, not a universal capability. A client is
  entitled to know which they are getting before we build, and afterwards to be told the
  truth about what we cannot undo. `evidence` holds the proof it actually came down —
  "we asked" is not "it is gone".

**Why `drifted` and not a new `correction_required`.** The observable fact is identical
(listing ≠ canonical, go fix it) and the operator does the same thing either way. A fourth
near-synonym would need adding to the Postgres enum, the Pydantic Literal and the frontend
union, and explaining forever. The *cause* differs, so the cause is recorded in
`verification_evidence` (`{"reason": "canonical_nap_changed"}`). A status should say what
IS, not how it got there.

**Only listings we believe exist are flagged.** `live` and `drifted` yes; `submitted` no —
nothing has confirmed a listing came back, and if one appears it will be checked against
the *new* canonical NAP anyway, which is the right comparison. Flagging it now would
invent work that may never exist.

**A third defect in my own Phase 0 work, caught here.**
`CitationsRepo.list_citations_for_client` — the query that feeds `compute_citation_gap` —
selected `proof_url` and **not** `live_url`. So the Phase 0 fix was correct and would have
produced an empty live list forever. That is a *worse* failure than the bug it replaced:
an empty result reads as "this client has no live citations" rather than as an error, so
nobody would investigate. Fixed, and pinned by a test that reads the query source.

### Found, not fixed — flagged for a decision

**`PATCH /business-profiles/{id}` is a full REPLACE, not a patch.**
`BusinessProfileRequest` defaults every field, so `model_dump()` always yields the
complete object and a PATCH that omits `addressLine1` genuinely asks for it to be blanked.
This is pre-existing and the UI form sends the whole object, so it is not currently
breaking anything — but combined with the fan-out it now has teeth: a partial PATCH from a
script would blank the NAP *and* correctly flag every live listing for correction. The
flag would be right; the blanking would not. Fixing it means changing the endpoint's
semantics (a real PATCH with `exclude_unset`), which is an API change and out of this
slice.


---

## 12. Phase 2 — the operator queue (2026-08-29)

`db/migrations/0110_citation_operator_queue.sql` + `/citation-builder/queue` (7 routes) +
`/admin/citations/queue`. Applied to the dev database and verified from empty (110
migrations, RLS gate green).

**What it replaces.** `tools/finish_citation.py` is **deleted**. It read an exported JSON
of every directory login for a campaign and printed `Password for all: …` — credentials
left the platform as a file, one password covered every account, and the work it did was
invisible. A guard test now keeps it retired rather than merely absent, because restoring
it from git history would restore the credential export with it.

**And a credential leak in the UI, found while removing it.** `CitationsTab.tsx` rendered
the directory **login and password in the page**, parsed out of the free-text `note`
column, with a copy button — beside a "Mark published" button that set a listing live on
the operator's word alone. Three defects in one panel: a credential in the DOM, a workflow
that only existed on one laptop, and a completion that was asserted rather than checked.
Replaced with a link to the queue.

**The design decisions worth keeping:**

- **The claim is a LEASE, not a lock** (20 min). An operator who closes their laptop must
  not strand an item forever; it returns to the pool and `human_attempts` records that
  someone had it and did not finish — which over time is how a directory earns its way
  *off* the offer list.
- **`for update … skip locked`** — verified against a real database with two simultaneous
  claims: they took *different* items and the third stayed free. Without `skip locked` the
  second operator blocks on the first's lock and then claims the row the first just took.
- **Completion is CHECKED, not asserted.** The operator supplies a URL; the same probe the
  re-check uses fetches it and looks for the business. If it is not there the completion is
  **refused and the item stays claimed** — the operator finds out while the tab is still
  open. The refusal is a normal response, not an error: the commonest cause is a directory
  that accepted the submission into moderation and has not published yet, and "not live
  yet" is then the honest answer.
- **Blocked is a first-class, one-click outcome** with a closed reason vocabulary. A queue
  whose only exit is success trains people to fake success.
- **`worked_seconds` is the point.** The loaded-cost model rests on minutes-per-item, and
  that number had never been measured — the "5 minutes" in every projection is an
  assumption. Time accumulates across claims and heartbeats, and the board shows the
  running **median** (not the mean: one operator going to lunch mid-claim would drag a mean
  far enough to make the cost model wrong). It reads **"not yet measured"** until something
  has actually been finished, never `0`.

**The re-check can now actually run.** Celery beat is empty by owner instruction, so a
scheduled-only re-check would be a feature that never fires. Rather than reverse that
decision, the sweep is also reachable at `POST /citation-builder/recheck`, and the beat
entry sits ready in `_BEAT_SCHEDULE_DISABLED` for whenever cron is switched back on.

**The dial was deliberately NOT changed.** Flipping `citations` to `byhand` was the obvious
safety move, but `api` is a *recorded client decision* ("no approval gate"). Overriding it
quietly would replace one honesty problem with another. The real defect was that an
unverified spec could run at all — which is gated where it belongs, in the whitelist.

### A note on enumeration, for whoever writes the next route test

`app.routes` is **not** the route table in this FastAPI version: included routers stay as
`_IncludedRouter` wrappers rather than being flattened, so walking it finds two entries and
reports every mounted route as missing. Enumerate via `app.openapi()["paths"]`, as
`tests/test_route_auth_guard.py` does.


---

## 13. Phase 2 completed: the earned whitelist and real credentials (2026-08-29)

Designed by a workflow that then attacked its own designs through security, correctness
and honesty lenses. It returned **34 findings, 12 blocking**. Two were serious enough to
justify the whole exercise, and one of them was already on disk.

### The SSRF that was nearly shipped

A form spec's `url` is a **browser navigation target**: `citation_bot` passes it to
`page.goto()`, types spec-controlled text into spec-controlled selectors, submits, and
stores a screenshot that a staff route serves back. Validating it as `https://…` stops
nothing — `https://169.254.169.254/latest/meta-data/` passes. A manager-level account
could have turned our authenticated headless browser into a screenshot-returning request
forgery inside our own network.

`0108_directory_specs.sql` binds a spec's host to its directory's host. Verified against
the live database: the metadata endpoint, `localhost` and a lookalike `evil-brownbook.net`
are all rejected; the directory's own host and a genuine subdomain pass.

**The host extractor was wrong on the first cut, and only a live test found it.**
`directories.url` is a bare domain for **155** rows (0046) and a full URL for **71**
(0065/0067). An extractor that only understood absolute URLs returned NULL for the bare
ones, so the binding check rejected *every* legitimate spec for them — blocking the honest
case far more thoroughly than the attack.

### The design agents wrote their unreviewed drafts to disk

`0108_directory_specs.sql` and `0109_citation_accounts.sql` were found sitting in
`db/migrations/` — the **pre-review** versions, carrying that exact SSRF. They would have
applied in filename order ahead of any corrected version. Deleted; both were rewritten by
hand with every blocking finding addressed.

### The finding that would have cost money

Engine resolution ran **after** the cost gate. Survivable while the bot fell back to 50
in-code specs and almost always had something to run; not survivable once the whitelist
starts **empty**, because "no spec" becomes the common case and the client would be billed
for a submission that could not physically happen. Resolution now happens first, with a
test asserting the gate is never reached and the row never passes through `submitting`.

### What is now true

- **`FORM_SPECS` is no longer a source of anything the bot will run.** The submitter
  defaults to an empty spec set and loads only `active = true` rows. All 50 in-code specs
  were imported as **inactive** by `app.cli.citation_specs_import` — a verification work
  queue, not coverage. Active specs: **0**. That is the honest number; it was always 0.
- **A spec earns its place** through a dated human DOM check *and* one submission that
  produced a public listing URL — enforced by a CHECK, not by Python, because
  `service_role` bypasses RLS but not constraints. `spec` is immutable after insert, so a
  revision is a new row and a verification can never be laundered onto different selectors.
- **Activation promotes the directory to route B in the same transaction.** Gating the
  loader on `route = 'B'` while nothing could ever *set* it produced a whitelist that
  could never have a member — measured: route B held zero rows.
- **`0111_citation_accounts.sql`** ends the irrecoverable-login defect. Vault coordinates
  are set by the database from the row's own id and are write-once, so a lead cannot
  repoint an account at another vault row and read it back through a citation route.
- **A CHECK I wrote was decoration, and my own test caught it.** `sealed_names_its_label`
  could never fail on INSERT, because the trigger fills the label before the constraint
  evaluates. The real invariant — sealing necessarily happens *after* the row exists,
  since the vault label is that row's id — is now enforced in the trigger.

### Operational note

`git stash` must not be used in this tree. Peers write continuously; a stash/pop to test
whether a failure was pre-existing lost the race twice and left a session's tracked edits
stranded in a stash entry. Use `git show HEAD:<path>` or a throwaway worktree.


---

## 14. Phases 3 and 4 (2026-08-30)

### Phase 3 — the extension

`extension/` at the repo root, with its own path-filtered CI. Three worlds, three
bundles, and the split IS the security design:

| bundle | sees the token | job |
|---|---|---|
| `service-worker.js` | **yes** | the only code that calls the API |
| `panel.js` | no | renders state, sends messages |
| `filler.js` | no | fills the form, reports what stuck |

A content script shares a renderer process with whatever JavaScript a directory serves,
so it receives selectors and values and returns an outcome — nothing else.
`tests/isolation.test.ts` asserts this against the **built bundles**, because a bundler
is exactly the thing that can quietly pull a shared import into two chunks. Verified:
`aios.operatorToken` appears in the worker and in neither of the others, and `filler.js`
contains no `/api/v1`, no `X-Operator-Token` and no `fetch(`.

**The failure the filler is shaped around.** Setting `el.value = x` on a React-controlled
input updates the DOM property and nothing else — React tracks values on an internal
`_valueTracker`, `onChange` never fires, and the component writes an empty string back on
the next render. The operator sees a filled form, submits, and the directory receives
nothing while the extension reports nine fields filled. So the filler writes through the
**prototype's** value setter and then **reads every value back after a frame**.
**Proven non-vacuous**: removing the read-back makes two tests fail, including one whose
fixture reverts the value exactly as React does.

**Auth reuses the queue rather than duplicating it.** The extension calls the SAME
`/citation-builder/queue/*` routes; only the credential differs. Building a parallel
`/citation-operator/*` surface would have meant a second copy of "a completion is checked
by fetching the URL", and two copies of a rule are a rule that will eventually differ.
`resolve_operator` accepts either credential and resolves both to the ordinary
`CurrentUser`; when no operator header is present it *calls `get_current_user` itself*, so
bearer auth on the queue is not a lookalike of the real path — it is the real path.

**Containment is structural.** `operator_tokens` (0112) is keyed to a USER, presented in
its own `X-Operator-Token` header, and carries a **closed** scope vocabulary of exactly
two values. There is no scope in existence that reaches the vault, the client roster or
the cost dials — not "no route grants it". The token is not a JWT, so `get_current_user`
rejects it everywhere else by construction. TTL is 12 hours, not the skill token's 30
days, because `chrome.storage.local` is plaintext on disk on a machine signed into ~50
third-party directories all day; the README says so, so nobody "improves" it later.
Revocation reuses the existing per-user epoch, so offboarding already kills every paired
device with no new code on that path.

**A gap I opened and closed.** Rewiring the queue routes to `resolve_operator` broke the
tests' `get_current_user` override, and my first fix stubbed `require_operator_lead` too —
which left the role gate untested. Added a test that overrides only `resolve_operator`, so
the gate runs for real: a specialist is refused claim, complete and blocked; a manager is
not.

**CORS**: `extension_origins` is additive exact strings, never a wildcard, and
`validate_settings` **refuses** a wildcard or a malformed id in production — verified
against `chrome-extension://*`, `*`, a short id and an uppercase id. Strictly it may not
be needed at all: a service-worker fetch to a `host_permissions` host is made with
extension privileges rather than being page-CORS-checked.

### Phase 4 — the aggregator spine, written and deliberately not running

`integrations/citation_aggregators.py` holds `DataAxleSubmitter` and
`AppleBusinessSubmitter` — the two of the three verified write paths that we can call
without an allowlist. Both are wired into `_api_submitters`, and today all three
`api:` methods block with an honest reason.

**Two rules hold it shut, and both are tested.**

1. **A key alone does not enable Data Axle.** Its per-Add price is published nowhere
   reachable, and at the modelled $5/$10/$30 the per-unit cost is 17×–100× the 10¢
   commitment — so the submitter is not even constructed until
   `data_axle_add_cost_estimate` is a real number. A key without a price is a way to
   spend money by accident.
2. **Nothing may ever return `verified`.** Data Axle telephones the business up to three
   times over three business days, Apple returns state `SUBMITTED`, Google requires
   verification before a location appears at all. A 200 means ACCEPTED, which is a
   different fact from a listing existing. Only the liveness probe promotes to `live`.

An existing record is **updated** (`U`), never re-added: updates are free, whereas a
second `A` would be billed, would duplicate, and would restart the verification clock.
Apple pins our own id as `partnersLocationId` so a retry is idempotent rather than
creating a second location.


---

## 15. An end-to-end run with a real client (2026-08-30)

Run against the dev database, through the real service, repo and router code. Nothing was
submitted to any directory; every write was to rows the script created and deleted.

Client: a printing business in Lahore, Pakistan.

**Every stage worked.** The client NAP derived into a submission profile; the selection
engine picked directories and explained every skip; a queued item was claimed and rendered
with all fields pre-filled; the liveness probe made a REAL fetch and correctly refused a
page that did not carry the business; a page carrying name+address+phone came back `live`
with all three matched; a page with a drifted phone came back `drifted`; changing the
canonical phone flagged the live listing as `drifted` with reason `canonical_nap_changed`.
Active specs: 0. Apple blocked with "no API submitter configured". Nothing ran that
should not have.

### The defect it found

**An unrecorded market defaulted to `US`.** The derived profile came out US, the campaign
selected **138 US+GLOBAL directories**, and the queue offered an operator YellowPages.com,
Chamber of Commerce, Manta and BBB — US-only directories — for a business in Pakistan.

Nobody ever said that client was American; `client_business_profiles.market`'s column
default and `derive_business_profile_fields`' `or "US"` did. That is the same class as
reporting a screenshot as a live listing: asserting a fact nothing established.

Fixed in `0113_market_defaults_to_global.sql` plus the derivation. The re-run selects **24
genuinely international directories** (Brownbook, Cylex, Cybo, Find-Us-Here, Express
Business Directory) instead of 45 including US-only ones.

**Why GLOBAL rather than US, or a required field.** Requiring it is the better long-term
answer and needs the onboarding wizard to ask — a separate change. Until then the two
defaults are not symmetric: defaulting to US produces a WRONG listing on a US directory
for a foreign business, which is NAP pollution — precisely the harm a citation campaign
prevents, and often unremovable (removability is a property of the route). Defaulting to
GLOBAL produces FEWER listings for a US client whose market was never recorded, which is
visible immediately in the gap report and fixed by setting the market. A missing listing
is recoverable; a wrong one on someone else's website frequently is not. Existing rows are
deliberately not rewritten.

### What this says about scope for a non-supported market

The enum holds US/UK/CA/AU/GLOBAL and the catalogue has no PK rows, so a Pakistani
business is honestly served by the GLOBAL set and nothing else: **24 buildable
directories**, not the 33–47 projected for a US client. That projection assumed a
supported market and should be quoted with that condition attached.

Raising it is a **catalogue** question, not an engineering one — adding South-Asian
directories is data. Nothing in the pipeline needs to change to use them.
