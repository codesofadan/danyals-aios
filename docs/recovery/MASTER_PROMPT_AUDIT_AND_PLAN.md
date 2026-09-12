# Master-prompt audit — architecture map, gap analysis, implementation plan

**Date:** 2026-09-12 · **Scope:** the 46-section master implementation prompt (grid
tracking · citations · extension · Web 2.0 · design replicator · content/SEO/schema ·
WordPress · jobs · testing).
**Method:** read-only sweep of the repository at `013c583`. Nothing was modified.

> This document is Phases 1–3 of the prompt (audit → problem categorisation →
> architecture plan). It exists so the build that follows is scoped against what is
> *actually in the tree*, not against the prompt's assumptions.

---

## 0 · The single most important finding

**Most of the master prompt is already built, and built well.** The prompt reads as a
greenfield brief; the repository is a ~110k-line production platform whose dominant
design principle is *exactly* the prompt's §2 and §45 — never claim a thing is true
unless it was verified against the real world.

Concretely, these master-prompt requirements are **already satisfied in code**:

| Prompt | Already built |
|---|---|
| §2 no fake data | `tests/test_no_synthetic_providers_in_production.py` — synthetic providers cannot reach a production path; every writing caller degrades instead |
| §7 citation lifecycle | 11-value evidence-driven submit-state enum incl. `ready_for_human`, `live`, `drifted`, `delisted` |
| §8 missing ≠ existing | evidence tiers (`0129`), `verifyFirst` / `byEvidenceLevel` gap analysis, a separate operator queue |
| §13 manual final submission | the extension **never** auto-submits and never touches a CAPTCHA — by construction |
| §14 awaiting-URL | `verification_method` ladder (`http_probe｜discovery｜human`), probe-verified completion, refusals that advance nothing |
| §19 truthful publication status | `published ≠ verified`; tri-state `link_found` |
| §27 navbar + hierarchy | `app/services/site_plan.py` + `site_navigation.py` → nested menu, `post_parent`, `menu_order`, `page_on_front`, applied idempotently by the WP plugin's `site-assembler.php` |
| §33 job states | `@aios_job`: idempotency key, DB-counted retries, DLQ, `completed｜degraded｜blocked｜failed｜cancelled`, CHECK constraints so a lie cannot be stored |
| §34 job persistence | jobs are DB rows claimed by workers; a closed tab cannot strand one; `reap_stale_job_runs` reclaims |
| §36 security | FORCE-RLS on 121 tables + CI gate, EdDSA auth, AES-256-GCM vault, SSRF guard with per-hop redirect revalidation, route-auth sweep |
| §5 platform curation | `0137` retires 19 paid / identity-gated / suspension-risk directories; `0135` classifies all 90 Web 2.0 rows into `api｜extension｜human｜unsupported` |
| §16 dynamic platform counts | mechanism + tier live in `web2_platforms`, not in code constants |

The honest conclusion: **do not rebuild these.** The remaining work is a much smaller,
sharper set than the prompt implies.

---

## 1 · Architecture map (as measured)

```
frontend/            Next.js 15 · React 19 · 37 app routes (admin / client / team / leads)
  lib/*.ts           the API response contract — backend response models are LOCKED to these
backend/
  app/routers/       38 routers  ─┐
  app/modules/       18 package-per-feature modules (router+service+repo+tasks+schemas)
                                  ├─ 416 route decorators under /api/v1
  app/services/      ~110 services (content · replica · web2 · citations · policy · context)
  app/jobs/          @aios_job — the one job vocabulary
  integrations/      41 external clients (Serper · DataForSEO · Google · Anthropic ·
                     WordPress · Firecrawl · Foursquare · Apify · Resend · B2 …)
  workers/           Celery; 5 queues BY DURATION (interactive｜standard｜long｜browser｜celery)
  tests/             333 test files
db/migrations/       137 ordered SQL migrations; RLS FORCE on every tenant table
extension/           Chrome MV3, TS+Vite, ~2.5k LOC — side panel, service-worker-only API
wordpress-plugin/    AIOS Publisher — core-connector · design-reconstruction ·
                     site-assembler · theme-adapter · auto-publisher
danyals-audit-system/ the audit engine: a SEPARATE product, invoked as a subprocess
```

**Scheduling reality:** `celery_app.conf.beat_schedule` holds exactly **two** entries —
`dispatch_automations` (60 s) and `reap_stale_job_runs` (300 s). Every business schedule
lives as a row in `public.automations`, and **all of them are seeded `enabled = false`**
(migrations `0118` / `0128` / `0134`). Nothing recurring runs today. That is a recorded
owner decision (AUTO-001), not a defect.

---

## 2 · Gap analysis — what the prompt asks for that is NOT there

### G1 · Grid tracking — **MISSING** (prompt §4)

- `danyals-audit-system/audit_engine/integrations/geo_grid.py` exists (ring-grid maths +
  a Serper probe) and is **orphaned**: nothing imports it. The checklist row `LOC-029`
  ("Map pack ranking by geo grid") names an analyzer
  `audit_engine.analyzers.local_pack.geo_grid` — **that module does not exist**. The
  engine's own ledger records `LOC-029` honestly as `NEEDS_PROVIDER / "provider budget"`,
  so it simply never runs.
- `app/modules/local_seo/` deliberately has **no grid** — its docstrings say so in three
  places ("a SINGLE representative locale … no geo-grid / lat-lng fan-out").
- `app/modules/rank_tracker/` is organic-SERP position tracking. No geo dimension.
- A Part-8 scope guard asserts `0039` creates exactly 3 tables. **Corrected during the
  Phase-A build:** that guard and its sibling (`LocalRankingCreate` carries no grid
  parameters) are scoped to migration `0039` and to `local_seo`'s own wire model, so a
  grid module in its own migration does not trip either. No guard needed amending —
  `local_seo` keeps its single-locale promise exactly as written, which is the right
  outcome: the two modules answer different questions and are priced differently.
- The orphaned probe encodes each point as `location="lat,lng"` on Serper's `/search`.
  Serper's `location` expects a canonical location *name*; the file's own comment admits
  it does not know whether that works. **Building on it as-is would produce plausible,
  uniformly wrong grids** — the exact §2 failure mode.

**Provider decision (made from the repo, no question needed):** `DATAFORSEO_LOGIN` /
`DATAFORSEO_PASSWORD` are populated and DataForSEO is already integrated
(`integrations/backlinks.py`, `citations.py`, `citation_discovery.py`,
`keyword_data.py`). Its Google **Maps** SERP endpoint takes a real `location_coordinate`
(`lat,lng,zoom`) — it is the only configured provider that can express a grid point
truthfully. Google Places (keyed) supplies the business anchor.

### G2 · AI semantic form filling — **MISSING** (prompt §12, §18)

The extension's filler is genuinely good at the hard part everyone gets wrong: it writes
through the prototype's native setter so React's `_valueTracker` observes it, then **reads
the value back** and reports per-field truth. What it does not have is **where to put
things**.

The field plan is `{selector, valueKey, value}` produced server-side from
`public.directory_specs` — human-verified, immutable, "earned" specs. There are **0 active
specs**, and the code is explicit that no spec means `selector: ""`, no autofill,
**copy-buttons only**. So today the operator pastes every field by hand on essentially
every directory — which §12 names as the thing that must stop.

The earned-spec model is *correct* and must be kept (it is what makes drift detection and
fail-closed deactivation possible). What is missing is the **fallback lane**: semantic DOM
analysis → field mapping → fill, for the ~241-row catalogue that will never have a
hand-written spec.

### G3 · Extension UX — **THIN** (prompt §10)

`panel.ts` (861 lines) is one linear flow; there is no tab navigation. Session *kinds*
(`citation` / `web2`) exist server-side and the panel switches behaviour on them, but the
operator has no "Citation | Web 2.0" surface. §10 is a presentation-layer build on top of
data that already exists.

### G4 · Homepage detection & validation — **MISSING** (prompt §26)

Front-page *assignment* works end to end (`site_plan.front_page_slug` →
`aios_publisher_apply_front_page` → `show_on_front` / `page_on_front`), a `homepage`
blueprint exists, and `site_plan` deliberately refuses to take over a front page unless
asked. What does not exist is the **evaluation**: nothing inspects a site's current root
page, decides whether it is a real landing page or a page-directory, or preserves a good
one. §25's *generation* is mostly covered by the blueprint; §26's *detection* is not.

### G5 · Design replicator — **BUILT, with named limits** (prompt §20–24)

`docs/DESIGN-REPLICATOR.md` is an unusually honest 414-line reference. Measured pipeline:
capture (Chromium, 3 viewports) → layout infer → design system → Elementor tree →
capability probe → chrome → oracle validate → publish. The non-browser half runs in
~13 ms on a 611-node reference capture.

Real gaps against §21/§24:
- **One page per run, nothing cached** — whole-site replication re-opens and re-measures
  the same site per URL.
- **Responsive is partial**: tablet column widths, section min-height (full-height heroes
  collapse to content height), per-breakpoint gap / image sizing and breakpoint visibility
  are **not** emitted. §21 names several of these explicitly.
- **No replicate→inspect→refine loop** for the replicator. `visual_diff.py` +
  `run_visual_qa` exist but hang off `site_builder`, not off `replica`.
- `nav-menu` is withheld on Pro sites because the oracle lacks its control ids —
  correctly, since Elementor silently swallows an unknown widget.

The prompt says "the quality has degraded". I found no evidence of regression in the tree;
I found *documented, bounded* limits plus a recent real fix (`ad72e1a` — "the Elementor
oracle was a TEST FIXTURE, so replication died in prod"). **Before any rework, run the
module's own reproducible A/B harness (§8 of that doc) against the URL that looked
wrong** — optimising stages 2/3/4/6/7 for a problem that actually lives in Chromium or in
a missing breakpoint fact would be wasted work.

### G6 · Design-aware content generation — **PARTIAL** (prompt §23)

`site_builder` produces a DesignIR with per-section slot capacity (`slots_for_kind`), and
its section-kind vocabulary is deliberately shared with `page_blueprints` so a generated
draft resolves through the same renderers. That is the right substrate for "3 pricing
cards ⇒ do not write 7 plans". What is not proven is that the **generator is bound by
those slot counts** — that binding needs tracing and, if absent, enforcing with a test.

### G7 · Scheduling — **owner decision, not a defect** (prompt §33/§34)

Everything recurring is paused. The job contract underneath is sound. Nine tests assert a
populated beat schedule and are deliberately red; they are the acceptance suite for the
restore. I will **not** flip this on unilaterally — turning on paid sweeps is a spend
decision. On-demand triggers already exist for the important ones (e.g.
`POST /citation-builder/recheck`).

### G8 · Extension auth — **LIKELY ALREADY MET** (prompt §15)

12 h default TTL (`MAX_TTL_SECONDS` 7 d), a **30-day install pairing** (`0131`), a rotate
endpoint issuing the raw token once, a rotation alarm in the extension, rotated-token
replay ⇒ install-chain revocation, and fail-**closed** revocation. §15 asks for secure +
revocable + refreshable + no unexpected expiry during active work. The remaining question
is only whether the rotation alarm reliably beats the 12 h expiry — a verification task,
not a rebuild.

---

## 3 · Problem categorisation (prompt Phase 2)

| Category | Items |
|---|---|
| **Working — do not touch** | job contract · RLS/auth/vault/SSRF · citation evidence model · operator queue + sessions · Web 2.0 capability matrix · site_plan/navigation/WP assembler · audit-engine seam |
| **Incomplete** | G2 AI filler · G3 extension tabs · G4 homepage detection · G5 replica responsive + QA loop · G6 slot-bound generation |
| **Missing** | G1 grid tracking (module, provider, storage, history, UI) |
| **Risky** | the orphaned `geo_grid.py` — building on its `location="lat,lng"` assumption yields confident wrong data |
| **Obsolete** | `geo_grid.py` itself (retire or rewrite; do not import) |
| **Blocked on owner** | G7 beat restore (spend) · P0-12 citation loaded-cost · P0-13 backup restore drill |

---

## 4 · Implementation plan

Ordered so each phase is independently shippable and green.

**Phase A — Grid tracking (G1).** New module `app/modules/grid_tracker/` following the
Part-8 package layout. Migration `0138`: `grid_definitions` (client · location anchor ·
keyword set · shape/radius/points) + `grid_runs` (job-linked) + `grid_points` (one row per
probe: lat, lng, position, observed-at). FORCE RLS; text + CHECK, never a new PG enum
(55P04). DataForSEO Google-Maps SERP provider driven by `location_coordinate`; the
business anchor resolved from the client's existing location / Places data captured at
onboarding. Runs as an `@aios_job` on the `long` queue, cost-gated behind a **newly
registered dial key** (`tests/test_dial_registration.py` would otherwise catch an
unregistered one and the paid path would be dead on arrival). History is the point of the
module, so runs are append-only and trended. Retire `geo_grid.py` in the engine with a note. Frontend: a real grid
heatmap on the client + admin dashboards, with honest empty / partial states — a point
that failed to probe renders as *unknown*, never as rank 20.

**Phase B — AI form intelligence (G2).** A `form_intelligence` service. The extension
ships a **structured, PII-free digest** of the open form (field kind, label text,
placeholder, name/id, aria, surrounding text, options, required, step) — never the whole
DOM. The server maps digest → canonical NAP keys with Claude, cost-gated, cached by
`(directory, form fingerprint)` so a repeat visit costs nothing. It returns the same
`{selector, valueKey, value}` plan the existing filler already consumes, so the read-back
honesty layer is unchanged. Confidence-scored: low-confidence fields fill but are flagged
for review; ambiguous ones stay copy-buttons. An earned spec, where one exists, always
wins. Panel states: *Analyzing form → Mapping fields → Filling → Ready for review* (§12).
Reused verbatim for Web 2.0 placements (§18) — which is why it is a service, not part of
the citations module.

**Phase C — Extension shell (G3).** Real `Citation` / `Web 2.0` tabs over the existing
session kinds; queue, batch progress, per-field fill outcome, completion + URL capture,
and *Awaiting URL* as a first-class state.

**Phase D — Homepage intelligence (G4).** A root-page evaluator: fetch `/`, classify it
(landing vs page-directory vs thin vs absent) against measurable signals, and generate
only when the evaluation says to. Generic by construction — no per-domain rules.

**Phase E — Replica quality (G5).** Start with the module's own A/B harness on a real
failing URL. Then, in measured order of loss: section min-height, tablet column widths,
per-breakpoint gap / image sizing, breakpoint visibility; a per-run capture cache so
whole-site replication stops re-measuring; and wire the existing `visual_diff` into a
bounded replicate→inspect→refine loop that applies only deterministic, safe corrections.

**Phase F — Slot-bound content + SEO/schema (G6).** Trace the generator against DesignIR
slot capacity; enforce with a test that a 3-card section cannot receive 7 items. Verify
SEO/schema are generated *inside* the content pipeline (they appear to be —
`content_schema.py`, `content_qa.py`) rather than bolted on afterwards.

**Phase G — Testing (prompt §41–43).** Unit tests land with each phase. The Playwright
E2E pass runs last, against the real app, per the prompt's "testing after implementation
is substantially complete".

---

## 5 · Standing constraints for the build

1. **Verify the commit, not the working tree** — the `c53eab0` lesson.
2. Never use a new Postgres enum label inside the migration that adds it (55P04); text + CHECK.
3. Every new paid path registers a dial key, or it is dead on arrival (`e8964de`).
4. Response models stay locked to `frontend/lib/*.ts` (`test_contract_lock.py`).
5. No automation is un-paused and no beat entry added without the owner saying so.
6. Gate before every commit: `ruff check .` && `mypy app workers` && `pytest -m unit`.
