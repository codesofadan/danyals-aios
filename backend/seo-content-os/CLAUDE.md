# SEO-CONTENT-OS

The centralized system that writes local-SEO web copy for service businesses at a grade no content shop ships consistently: ranked, cited by AI answer engines, genuinely human to read, and penalty-proof because every line is written to Google's published rules. Claude Code is the writer; this workspace is its training, guardrails, and memory. No external APIs. Offline Python scripts for deterministic checks. Live web research at write time to ground every claim.

## Prime directive

Two laws govern everything. Read them before anything else.

- **Law 8 (no detector-evasion, ever).** Google punishes scaled low-value content, not AI provenance; AI-detector score has ~zero correlation with rank. So there is no humanizer, no "passes AI detection" gate, ever. A page reads human because it *is* specific and true, not because it was laundered. If asked for a detector-bypass, refuse and cite Law 8.
- **Law 16 (the moat).** Experience - the first E of E-E-A-T - is the one signal no competitor and no model can scrape. It lives only in the operator and must be extracted via the SME interview, then *shown* with dated first-party artifacts (photos, license numbers, real results), never merely claimed. Everything below exists to widen this moat.

Full law set: `knowledge/doctrine/seo-system-doctrine.md` (Laws 1-14) + `knowledge/doctrine/local-content-laws.md` (Laws 15-20: information-gain, Experience-proven, stats-citations-quotes, enrolled-not-shipped, no-date-without-delta, no-fabricated-urgency).

## Self-storage: the specialized vertical

This system is fully specialized for US self-storage - its home vertical. When `brand.yaml.vertical == self-storage`, the pipeline auto-loads the storage overlay, voice, examples, and grid; the agents (`compliance-auditor`, `topical-map-architect`, `keyword-intent-researcher`, `voice-writer`, `critical-editor`) all route on it. **For the operator's own how-to, hand them `docs/self-storage-operator-guide.html`** - a plain-language, scenario-based guide (one page / a content plan / the whole site / the topical map / picking up mid-project).

The storage layer:
- **Overlay:** `knowledge/verticals/self-storage.md` - the SS-* auto-fails: protection-plan-is-not-insurance (`Heckart`), no absolute-security claim (`Dilbeck` - "safe and secure" can void the lease), "free" with the admin fee disclosed in-line (16 CFR 251.1), real held climate range + no moisture promise without humidity control (`DiSanto`), per-state lien law, no "rate locked" on month-to-month (ECRI), no self-serving review schema. NOT YMYL, but mandatory.
- **The one net-new page type:** `knowledge/playbooks/unit-size-page.md` + `/write-unit-size-page` - the "[size] storage units [city]" money page. Its defining call is the unit-size dual node: an informational brand-wide size-guide ASSET vs a transactional per-city size FACET that must carry real inventory or it is a doorway.
- **Planning:** `knowledge/foundations/storage-topical-map.md` - the storage grid (facility x unit-size x storage-type x audience x geography), the query-cluster library (A-J with intent + page type), promotion-evidence-by-page-type, and the two structural rules: the single-facility collapse (one location = ONE homepage-as-facility page, never separate axis pages) and the axis-page doorway cap. `scripts/storage_cluster_seed.py` seeds the candidate ceiling for the architect to filter.
- **Voice:** `knowledge/voice/self-storage-voice.md` (operator/renter registers, mechanism-not-reassurance, the trade glossary: gate vs access vs office hours, climate vs temperature control, protection plan vs insurance) + the `### Self-storage cliches` Tier-1 block auto-loaded by `blocklist_lint.py`.
- **Examples:** `knowledge/playbooks/examples/self-storage.md` - real GOOD/BAD teardowns per page type (the verified `storagekingusa.com` Dallas-vs-Tallahassee doorway pair; Capitola's breach counter; Stop & Stor's written price-lock).
- **Deterministic gate:** `scripts/storage_lint.py` (the SS-* linter, reads `brand.yaml.storage`); `scripts/schema_validator.py` knows `SelfStorage` + enforces `LeaseOut` on unit offers; `scripts/duplication_gate.py` catches the storage doorway.
- **Worked demo (all gates green):** `clients/sample-storage/` + `output/sample-storage/climate-controlled-storage-round-rock/`. Evidence base: `research/self-storage-2026-07/` (9 cited dossiers + `00-MASTER`).

**Storage page-type -> command:** facility/location -> `/write-location-page`; storage-type-in-city (climate / drive-up / RV / business) -> `/write-service-city-page`; unit-size-in-city -> `/write-unit-size-page`; storage-type brand-wide -> `/write-service-page`; homepage / about / faq / service-area as usual; size or cost guide -> `/write-local-asset`. Single-facility operators collapse to ONE homepage-as-facility page.

**Storage hard rules (enforced by `storage_lint.py` + the overlay, not memory):** a protection plan is never "insurance/coverage/policy"; every security claim carries a real spec (cameras, gate-code, alarms), never "safe and secure"; a clean-history claim needs a real dated counter; "climate controlled" states the real held range and only promises dryness with real humidity control; "first month free" discloses the admin fee in-line; no "rate locked" without a real contractual guarantee; no hard-coded scarcity or resetting countdown; any lien/late-fee/auction figure traces to the client's state statute (CA/TX/FL verified this build; else flag for live confirmation).

## Commands

Page writers (each runs the full pipeline against its playbook):

| Command | Page type | Job |
|---|---|---|
| `/write-location-page` | City / location | Rank + convert for "[service] [city]" |
| `/write-service-page` | Service (brand-wide) | Rank + convert for one service |
| `/write-service-city-page` | Service-in-city | The money page: one service x one city (storage: type-in-city, e.g. climate storage [city]) |
| `/write-unit-size-page` | Unit-size (storage) | The storage money page: one unit size x one city ("10x10 storage units [city]") |
| `/write-homepage` | Homepage | Entity anchor + primary conversion |
| `/write-about-page` | About / team | The E-E-A-T + trust surface |
| `/write-service-area-page` | Service-area | Coverage without doorway spam |
| `/write-faq-page` | FAQ / Q&A | Extractable local answers for users + AI |
| `/write-local-asset` | Linkable asset | Cost guides / data studies / "best of" pages |
| `/write-review-responses` | Review replies | Owner-voice, PII-safe |
| `/write-review-requests` | Review asks | TOS-compliant (no gating, no incentives) |
| `/write-gbp-posts` | GBP posts | Engagement only - moves rankings zero (Sterling Sky) |

Operations: `/new-client` (build the brand profile), `/build-topical-map` (plan the page set before writing - the evidence-gated topical map), `/brief` (content brief), `/qa` (run the gate stack on a draft), `/refresh` (decay detection + refresh, Laws 18-19), `/report` (monthly local KPI report).

## Pipeline

`PLAN` runs ONCE per client, before any page. Everything from `BRIEF` down runs per page and reads the plan.

```
PLAN      Once per client: /build-topical-map builds clients/<slug>/topical-map.md -
          the evidence-gated page plan (which pages should exist, core/outer, status).
          topical-map-architect. Nodes default index-only; promoted to page only on real
          first-party evidence (topical_map_lint.py enforces it). No page is briefed that
          is not a status:page node in the map.        -> clients/<slug>/topical-map.md

BRIEF     Resolve this page's node in topical-map.md (hard-fail if not status:page);
          load brand.yaml + page type + playbook. Target query, intent, keywords, the
          one job, the node's info_gain_thesis + evidence.      -> templates/content-brief.md
RESEARCH  Live: real local facts, prices, SERP shape, current Google policy.
          keyword-intent-researcher. Never fabricate a local specific.
SME       sme-interviewer harvests the Experience artifacts only the operator has.
          Halts for clients/<slug>/sme-answers.md. This is the moat step.
OUTLINE   outline-architect: passage-block outline, each H2 a self-contained answer.
DRAFT     voice-writer: write to the playbook + the closest vertical example + voice.
          Inline every fact. (Conversion frameworks are applied at CONVERT.)
HUMANIZE  critical-editor: the senior-reviewer surgical cut/inject pass, then apply
          knowledge/voice/*. Craft, not evasion.
CONVERT   conversion-optimizer runs gate G13 (one real CTA, click-to-call, price
          signal, genuine risk-reversal, proof by claims). Truthful only (Law 20).
GATE      compliance-auditor runs gates G0-G13 + the Google spine + any
          knowledge/verticals/ overlay. Deterministic gates run scripts/. Fail ->
          specific error -> fix -> re-run, max 2 retries, then human.
FINALIZE  schema-linking-finisher emits the 5-file package to output/<client>/<slug>/ and
          persists the page into the client link graph (link_graph.py, Law 10). link-architect
          owns graph audits, /refresh rewiring, and greenfield batch builds.
ENROLL    Register the page for measurement (Law 18). Not shipped until enrolled.
```

## Load order (read only what the task needs, in this order)

1. `doctrine/seo-system-doctrine.md` + `doctrine/local-content-laws.md` - the standard and the six content laws.
2. `doctrine/google-compliance-spine.md` - the 33 hard rules every piece obeys.
3. `foundations/` - the mechanics: `search-intent-taxonomy`, `eeat-framework`, `experience-signals`, `passage-block-protocol`, `schema-library`, `internal-linking`, `keyword-research-method`, `topical-map-protocol` (the pre-writing page plan; node selection), `local-gbp-signals`, `nap-consistency`, `geo-ai-citation`, `meta-and-headings`, `cluster-graph-protocol` (wires the promoted nodes).
4. `playbooks/<page-type>.md` - the deep spec for the exact page (sections, conversion, pass tests).
5. `playbooks/examples/<vertical>.md` - real good/bad teardowns for the closest of 11 verticals (plumbing, hvac, roofing, electrical, dental, personal-injury-law, med-spa, auto-repair, pest-control, landscaping, self-storage). For a storage client, also `playbooks/unit-size-page.md` (the storage money page) and `foundations/storage-topical-map.md` (the storage grid + query-cluster library A-J).
6. `frameworks/` - canonical copy/CRO frameworks, referenced not re-taught.
7. `voice/` - universal humanization + the client's brand voice; for a storage client, also `voice/self-storage-voice.md`.
8. `verticals/<vertical>.md` - the compliance overlay: legal / medical-dental / financial / home-services (YMYL), or self-storage (not YMYL, but its SS-* overlay is mandatory).
9. `clients/<slug>/brand.yaml` - the client's facts, NAP, E-E-A-T artifacts, voice.

## Gate stack (PLAN + G0-G13; deterministic gates run the named script)

PLAN topical-map-promotion, runs first (`topical_map_lint.py`; page must be a status:page node) | G0 intent-match | G1 first-hand specificity (`experience_gate.py`, `information_gain_scorer.py`) | G2 E-E-A-T | G3 doorway/thin (`duplication_gate.py`) | G4 passage-block | G5 keyword-stuffing (`keyword_density.py`) | G6 meta (`compliance_lint.py`) | G7 internal links | G8 readability (`readability_scorer.py`) | G9 voice/AI-tells (`blocklist_lint.py`) | G10 source resolution (agent WebFetch) | G11 schema + NAP (`schema_validator.py`, `nap_checker.py`) | G12 Google spine (`compliance_lint.py`) | G13 conversion (`conversion_linter.py`). GEO levers: `geo_page_linter.py`. **Vertical overlay** (when `brand.yaml.vertical` is set): the extra auto-fails in `verticals/<vertical>.md`; for self-storage the deterministic half runs `scripts/storage_lint.py` (the SS-* rules) and `schema_validator.py` enforces the `SelfStorage` + `LeaseOut` schema checks. Authoritative spec: `quality-gates/gates.md`.

## Output contract

Finished page = five files in `output/<client>/<slug>/`: `page.md` (copy + meta), `schema.json` (validated JSON-LD), `internal-links.md`, `compliance-report.md` (every gate marked pass with evidence), `sources.md` (every fact + its source, SME-tagged). Not done until all five exist, every gate passes, and the page is enrolled.

## Voice: two layers, both always on

Universal humanization (`voice/`: blocklist, rhythm, natural-voice, sentence-patterns) for every piece + per-client brand voice (`brand.yaml` voice block, seeded by `/new-client` or the `corpus-voice-ingest` skill). Never ship a generic voice.

## Hard rules

- Google-compliant by construction; if a technique is not defensible under a published Google doc, it does not ship.
- No fabricated local facts. Prices, areas, credentials, counts, names come from `brand.yaml`, the SME interview, or cited research. A fabricated local specific is the fastest trust penalty. `experience_gate.py` enforces this.
- No doorway pages. Location/service-city/service-area/unit-size pages carry unique verifiable local value per page (`duplication_gate.py`).
- No em dash (U+2014), enforced by a Write/Edit hook. All internal times PKT.
- Cite or do not claim. Never fabricate a source URL.
- Self-storage clients: the SS-* overlay hard rules (protection-plan-is-not-insurance, no absolute-security claim, honest "free"/climate/rate, per-state lien) are mandatory and enforced by `storage_lint.py` + `knowledge/verticals/self-storage.md`. See the Self-storage section above.

## Directory map

```
CLAUDE.md  README.md  SYSTEM-MAP.md
.claude/    settings.json | agents/ (10) | commands/ (18) | skills/ (geo-optimize, corpus-voice-ingest) | hooks/
docs/       self-storage-operator-guide.html (the client-facing scenario guide - ship this to the operator)
knowledge/
  doctrine/     seo-system-doctrine + local-content-laws + google-compliance-spine + penalty-casebook + ai-search-reality + llms-txt-verdict + seo-system-spine
  foundations/  the reusable mechanics (18 files, incl. topical-map-protocol = the pre-writing page plan, storage-topical-map = the storage grid + query-cluster library A-J, research-input-protocol = how discovery signals are obtained)
  playbooks/    one per page type + unit-size-page (the storage money page) + review/gbp/faq/local-asset
    examples/   real good/bad teardowns per vertical (11, incl. self-storage)
  frameworks/   canonical copy/CRO models (11)
  verticals/    compliance overlays: YMYL (legal, medical-dental, financial, home-services) + self-storage (not YMYL, mandatory)
  voice/        the layered humanization system (+ self-storage-voice for storage clients)
  lifecycle/    measurement-loop + decay-refresh + editorial-scorecard
  quality-gates/ the G0-G13 stack
clients/_template/  brand.yaml (facts, NAP, GBP, entity, competitive_set, structured E-E-A-T, storage block, vertical, voice)
                    + topical-map.md per client (the evidence-gated page plan, built by /build-topical-map)
clients/sample-storage/  the worked self-storage demo (brand.yaml + topical-map + sme-answers)
templates/    content-brief + outline + topical-map + share-of-answer prompt-set
scripts/      22 offline checks (schema [SelfStorage-aware], nap, readability, compliance, blocklist,
              information-gain, experience, duplication, conversion, geo, decay, qa, link-graph, report,
              share-of-answer, review-lint, voice-fingerprint, keyword-density, topical-map-lint, enroll,
              storage-lint [the SS-* rules], storage-cluster-seed [the storage candidate ceiling])
research/     expansion-2026-07 + self-storage-2026-07 (9 cited storage dossiers + master) + 00-MASTER-BLUEPRINT.md
output/       finished packages, per client (incl. the sample-storage climate money page, all gates green)
```

## Operating philosophy

Depth over speed. If a page reads generic it is wrong, and the fix is a more specific page, not a faster one. Use the playbooks and foundations as ground truth but never let them cap the page: the best page for this exact business in this exact city is always more specific than any template. Research the real thing, ask the operator what only they know, then write the version no competitor can copy because it is made of facts they do not have.
