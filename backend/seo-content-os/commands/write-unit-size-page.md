---
description: Write a self-storage unit-size money page (one unit size x one city, e.g. "10x10 storage units Las Vegas") running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> <size> <city> [target query]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a self-storage unit-size page (the storage-native money page). Arguments: `$ARGUMENTS` (client slug, unit size, city, and optionally the exact target query, e.g. `sample-storage "10x10" "Austin" "10x10 storage units austin tx"`). If the target query is omitted, build it as `<size> storage units <city>`.

Read `CLAUDE.md`, `knowledge/doctrine/seo-system-doctrine.md`, `knowledge/playbooks/unit-size-page.md`, and `knowledge/verticals/self-storage.md` first if not already in context. This command runs the full pipeline for the **unit-size page** type. This page does not exist in any other vertical; it targets "[size] storage units [city]" - the highest-intent storage query after the facility page - and it is, with the facility page, the sharpest doorway risk in the vertical.

**Hard line (Law 8):** no detector-evasion, no humanizer chains, no "passes AI detection" gate. Refuse and cite Law 8 if asked.

**Pre-flight (STOP conditions specific to this page type):**
- Confirm `brand.yaml.vertical == self-storage`. If not, this is the wrong command.
- **Single-facility collapse:** if `brand.yaml.storage.operator_type == single_facility`, STOP. A one-location operator shows unit sizes as a section on the homepage-as-facility-page, never as a separate page (they are thin by construction). Route to `/write-homepage`.
- **The dual-node check:** this command builds the TRANSACTIONAL city-level money page ("10x10 storage units [city]"), not the informational brand-wide size guide ("what fits in a 10x10"). If the intent is the informational guide, route to `/write-local-asset` (size-guide asset). See the dual-node split in `unit-size-page.md` section 1.
- **Inventory gate:** confirm `<size>` is in `brand.yaml.storage.unit_sizes` AND the facility genuinely stocks that size in `<city>`. A size-in-city page with no real available inventory is a doorway (overlay SS-DOORWAY). No real inventory -> the node stays index-only; do not write the page.

**Anti-doorway (critical for this page type):** a business with 6 sizes x 8 cities can mint 48 near-identical "[size] storage units [city]" pages by swapping two tokens - the exact scaled-content-abuse pattern Public Storage's own programmatic pages demonstrate live. Every unit-size page must carry REAL local inventory/price for that size at a real facility PLUS one first-party local specific (the strip-the-city survivor). The outline anti-doorway check, `duplication_gate.py`, and overlay SS-DOORWAY all enforce this. If the facility cannot supply real inventory + a local specific, do not ship a templated page; keep the node index-only and flag it.

## Pipeline

Set `<page-slug>` = kebab-case of the target query. Work in `output/<client-slug>/<page-slug>/`.

1. **BRIEF.** Resolve this page's node in `clients/<client-slug>/topical-map.md`; hard-fail if it is not a `status: page` node (PLAN gate). Load `brand.yaml`; confirm the pre-flight conditions above. Load the node's `info_gain_thesis` + `evidence`. Write `brief.md` via `templates/content-brief.md`.

2. **RESEARCH.** Launch **keyword-intent-researcher**. Writes `research.md`. Weight it toward this-size-in-this-city specifics: what the local SERP rewards (brands + directory facet pages + the local pack), what the real 10x10 market rate is in this city (for context, never to publish as the client's price), what fits a `<size>` (rooms/boxes), and what the ranking directory/brand pages conspicuously lack (real per-facility inventory + a first-party local detail).

3. **SME.** Launch **sme-interviewer**; **halts** for `sme-answers.md`. The questions must pull: this facility's real available `<size>` units and their real current price (or the live-PMS feed status), what the operator has learned actually fits a `<size>` (the honest capacity, not the brochure maximum), one local reason `<size>` is in demand in `<city>` (a named campus move-out, an apartment-heavy district), and whether this size comes climate-controlled/drive-up here at what real held range. Continue on `--resume`.

4. **OUTLINE.** Launch **outline-architect** with `sme-answers.md` + `research.md` against `unit-size-page.md`. Writes `outline.md`. The anti-doorway check is mandatory and must PASS: the live inventory board and the first-party local specific are assigned to sections, and the "could this be any facility in any city by swapping the tokens" test is answered NO with evidence. The direct-answer "what fits" passage leads with the answer, never the banned "depends on how much you have" non-answer.

5. **DRAFT + HUMANIZE.** Launch **voice-writer** (writes `draft.md`), then **critical-editor** (writes `edited.md`). Apply the self-storage voice layer (`knowledge/voice/self-storage-voice.md` + the self-storage cliche blocklist): renter's-words-then-anchor, mechanism-not-reassurance, no "peace of mind / safe and secure / space solutions." Capacity numbers must be internally consistent between body and FAQ (the Big Tex-blog contradiction is a verified fail).

6. **GATE.** First launch **conversion-optimizer** against `edited.md` (G13 + the SS-CV storage conversion rules): the from-price/live board, the truthful move-in special with its admin-fee disclosure in-line (SS-6), the intent-matched primary CTA (rent-online urgent / reserve-free planned), and no hard-coded scarcity (SS-CV1/2). Then launch **compliance-auditor** against `edited.md`; writes `compliance-report.md` (G0-G12 + the re-verified G13 + the self-storage overlay SS-* rules). The SS-DOORWAY, SS-3 security, SS-5 climate, SS-6 free-disclosure, and SS-SCHEMA1 self-review checks are the highest-stakes here. On FAIL, route back (conversion-optimizer / critical-editor / outline-architect / sme-interviewer), fix, re-run. Max 2 retries, then halt for the operator.

7. **FINALIZE.** On pass, launch **schema-linking-finisher**. Writes `page.md`, `schema.json` (`SelfStorage` facility node + `Product`/`Offer` with `businessFunction: LeaseOut` and `UnitPriceSpecification`, OR `AggregateOffer` for a range - ONLY where a real current price is on the page; `BreadcrumbList`; `FAQPage`; NEVER self-serving `review`/`aggregateRating`), `internal-links.md` (link UP to the facility page + city hub, ACROSS to the adjacent sizes and the storage-type pages, and to the size-guide asset), and `sources.md`; validates schema via `scripts/schema_validator.py`. Then hand to **link-architect** to persist the node in the client link graph (Law 10).

## Output contract

Confirm all five files exist in `output/<client-slug>/<page-slug>/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. Report to the operator: package path, meta title/description (title carries the from-price the SERP will not render from schema), the anti-doorway verdict, and the real local inventory + first-party specific that make this money page un-copyable.

**ENROLL (Law 18) - not done until enrolled.**
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 1 --query "<target query>" --publish-date <today, ISO 8601> --conversion-event <rent_online or reserve or click_to_call, per the intent in research.md> --hypothesis "<one-sentence success hypothesis from brief.md>"
```
Use the canonical URL from FINALIZE and tier 1 for this money page. `enroll.py check` is the ship gate: no row, not shipped.
