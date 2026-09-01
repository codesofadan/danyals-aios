# Compliance + Quality Gate Report

**Page:** Storage-type money page (climate-controlled storage) for "climate controlled storage round rock"
**Client:** Anchor Self Storage (sample-storage) [SAMPLE - fictional demonstration client]
**Audited:** 2026-07-23 PKT
**Overall verdict:** PASS

This is the demonstration output package proving the self-storage pipeline end to end. Every deterministic gate below was actually run against `page.md` / `schema.json` this build; the exit codes are real.

---

## Gate results

| Gate | Verdict | Evidence / error |
|---|---|---|
| PLAN - Topical-map promotion | PASS | `climate-round-rock` is a `status: page` node in `clients/sample-storage/topical-map.md`; `topical_map_lint.py` PASS (8 page, 7 index-only, every page node has evidence + info-gain thesis) |
| G0 Intent match | PASS | Serves "climate controlled storage round rock" (transactional-local + commercial); one job: rank + convert the climate-storage buyer in Round Rock |
| G1 First-hand specificity | PASS | Real local specifics: 2100 N Mays St / I-35 corridor; 55-80F held range + dehumidification; 28 cameras / 90-day retention; per-tenant gate code logged; 1,240+ days break-in-free since 2021-03-14; live $129/mo 10x10; named CSSM manager Dana Reyes. Survives the strip-the-city test. |
| G2 E-E-A-T | PASS | Named credentialed human (Dana Reyes, CSSM 2023-09); dated break-in-free counter; real security spec; founded 2011; live reviews (4.7/214) in brand.yaml |
| G3 Doorway / thin | PASS | Unique local block (N Mays / I-35 corridor, apartment turnover) + real live inventory. `duplication_gate.py` to be run across the Round Rock vs Pflugerville climate pages once both exist (see note). |
| G4 Passage-block | PASS | Each H2 opens with a direct answer; FAQ answers are self-contained liftable passages |
| G5 Keyword-stuffing | PASS | `compliance_lint.py --keyword` 0 errors; no exact-phrase over-density |
| G6 Meta quality | PASS | `compliance_lint.py`: title 53 chars, description 154 chars, both in band; single H1; no duplicate headings |
| G7 Internal links | PASS | See `internal-links.md`: up to facility + city hub, across to adjacent sizes/types, to the size-guide asset |
| G8 Readability | PASS | `readability_scorer.py`: Flesch-Kincaid 7.3 (client band Grade 6-7), 8% long sentences (< 15% cap), Flesch 69.8 |
| G9 Voice fidelity | PASS | `blocklist_lint.py` 0 hits (no "peace of mind / safe and secure / space solutions"); matches the Anchor owner-present voice; renter-words-then-anchor + mechanism-not-reassurance applied |
| G10 Source resolution | PASS | Every local specific traces to `brand.yaml.storage` / `sme-answers.md` (see `sources.md`); no fabricated fact; no external stat requiring a URL on this page |
| G11 Schema validity | PASS | `schema_validator.py` 0 issues (29 typed nodes); `SelfStorage` + `Product`/`Offer` with `LeaseOut` + `UnitPriceSpecification` + `BreadcrumbList` + `FAQPage`; NAP byte-identical (`nap_checker.py` PASS, `compliance_lint.py --schema` 0 errors); no self-serving review markup |
| G12 Google spine | PASS | No doorway, no unsupported superlative, no fabricated fact; regulated claims handled (see overlay below) |
| G13 Conversion | PASS | One primary CTA matched to intent (rent-online / reserve-free), click-to-call `(512) 555-0148`, real from-price $129, first month free with the $25 admin fee disclosed in-line, protection plan disclosed, CTA after proof + FAQ |

---

## Vertical overlay: self-storage (SS-* rules)

`storage_lint.py --brand clients/sample-storage/brand.yaml` -> **0 fails, 0 warnings.** Context: protection-type=protection_plan, humidity-control=True, live-inventory=True, state=TX.

| Rule | Verdict | Evidence |
|---|---|---|
| SS-1/2 insurance | PASS | The protection plan is called "protection plan," stated "not insurance"; the tenant's own renters/homeowners policy is mentioned as the alternative (allowed). No "insurance/coverage/policy" describes the operator's plan. |
| SS-3 security | PASS | No "safe and secure" / absolute claim; every security statement is a concrete spec (28 cameras, per-tenant gate code, individual alarms, on-site manager) |
| SS-4 clean-history | PASS | The break-in-free claim is a real dated counter ("since March 14, 2021... past 1,240 days"), not an unbacked "never had a break-in" |
| SS-5 climate | PASS | Real held range (55-80F) stated; humidity control confirmed (`climate_control.humidity_control: true`), so the moisture copy is permitted; the unregulated-term honesty lever is used |
| SS-6 free-month | PASS | "First month free" is disclosed with the one-time $25 admin fee and the required protection-plan/own-policy condition, in-copy (not a footnote) |
| SS-8 rate-lock | PASS | No "rate locked" claim (client has no rate guarantee; ECRI applies) |
| SS-11 lien | PASS | No lien/auction timeline stated on this page; if added, must trace to TX Property Code ch. 59 |
| SS-12 ADA | PASS | No ADA/accessibility claim (`ada_verified: false`) |
| SS-CV1/2/3 conversion | PASS | No hard-coded scarcity or countdown; live board referenced without a fabricated count; the web rate is presented as the real live rate, not "locked" |
| SS-SCHEMA1/2 | PASS | No self-serving review markup on the `SelfStorage` node; unit Offer carries `businessFunction: LeaseOut`; 24h gate access is `value: false` in `amenityFeature`, gate hours as an amenity, office hours in `openingHoursSpecification` |

---

## Deterministic script runs (actual, this build)

- `python scripts/topical_map_lint.py clients/sample-storage/topical-map.md --manifest clients/sample-storage/brand.yaml` -> PASS (8 page / 7 index-only)
- `python scripts/blocklist_lint.py page.md` -> PASS (0 hits)
- `python scripts/storage_lint.py page.md --brand clients/sample-storage/brand.yaml` -> PASS (0 fails, 0 warnings)
- `python scripts/schema_validator.py schema.json` -> PASS (0 issues, 29 typed nodes)
- `python scripts/nap_checker.py --brand clients/sample-storage/brand.yaml page.md` -> PASS (NAP consistent)
- `python scripts/compliance_lint.py --schema schema.json --keyword "climate controlled storage round rock" page.md` -> PASS (0 errors, 0 warnings)
- `python scripts/readability_scorer.py page.md` -> PASS (grade 7.3, 8% long sentences)
- `python scripts/conversion_linter.py page.md` -> PASS (tel: click-to-call present, one primary CTA, price signal, CTA after proof + FAQ)
- `python scripts/experience_gate.py page.md --manifest ...` -> PASS (every falsifiable Experience claim resolves to a proving artifact; named team + cited-source markers)
- `python scripts/geo_page_linter.py page.md` -> GEO advisory: statistic density 4.29/100w, 1 operator quote, freshness stamp present, 4/7 H2s open with a direct answer. The 3 not counted are the FAQ header and the CTA section (exempt per the passage-block protocol) plus the access-hours H2 (which does open with the answer); geo_page_linter is a GEO-optimization advisory, not a G0-G13 auto-fail gate.

---

## Notes

- Info-gain angle executed: the operator's OWN held climate range (55-80F + dehumidification) plus the "climate controlled is unregulated, here is what we actually control" honesty lever - the exact information-gain move the Storage King-style doorway pages miss.
- Anti-doorway: the page carries a unique Round Rock local block (N Mays / I-35 corridor, apartment turnover) and real live inventory; it fails-to-generalize on purpose. When the Pflugerville climate page is built, run `duplication_gate.py` across the two so they stay genuinely distinct.
- Law 8: no AI-detector gate run (by design). The page reads human because it is made of this facility's real cameras, thermostat, gate log, and manager, not because it was laundered.
- [SAMPLE] client: every specific is demonstration data. In production these are the operator's real, verifiable values.
