# Compliance Report - Dental Implants service page (sample-dental)

Run 2026-07-20 PKT. Page: `page.md`. Client: Sunbridge Dental [DEMONSTRATION - fictional]. Vertical: dental (YMYL) -> `knowledge/verticals/medical-dental.md` overlay applied.

**VERDICT: BLOCKED for publish.** Three gates fail, all from one root cause: this demo client has no real externally-verifiable artifacts. The copy itself passes every structural, voice, compliance, and conversion gate. See "Why this is the correct outcome" at the bottom.

## Base gate stack

| Gate | Result | Evidence |
|---|---|---|
| G0 Intent match | PASS | Commercial-informational service query; page answers "what, how, how much, what are the risks, how do I start". |
| G1 First-hand specificity / Experience | **FAIL** | `experience_gate.py`: 0 Experience markers (PHOTO=0, LICENSE_NUM=0, NAMED_TEAM=0, CITED_SOURCE=0) against 4 falsifiable claims. Law 16 violation. |
| G2 E-E-A-T presence | PARTIAL | Named providers with credentials and a clinical-review byline are present; the *proving artifacts* (license numbers, photos) are not on the page. |
| G3 Doorway / thin | PASS | Brand-wide service page, not part of a city-swap set. `duplication_gate.py` not applicable (no siblings yet). |
| G4 Passage-block | PASS (warn) | 5/9 H2 blocks open with a direct answer; 4 flagged WEAK by `geo_page_linter.py`, 2 of which are heuristic strictness (an FAQ header has no direct answer by nature). |
| G5 Keyword stuffing | PASS | `keyword_density.py`: "dental implants" 0.98%, "dental implants los angeles" 0.49%, both inside the 2.5% natural-use threshold. |
| G6 Meta quality | PASS | `compliance_lint.py`: 0 errors, 0 warnings. Title 52 chars, description 158 chars, single H1. |
| G7 Internal links | PASS | `internal-links.md` plans 11 outbound links (hub-up, alternatives-across, city-spokes-down) with descriptive anchors; exact-match used once at most. |
| G8 Readability | PASS | `readability_scorer.py`: Flesch 67.9, FK grade 7.8, avg 16.2 words/sentence. Inside the client band (grade 7-8). |
| G9 Voice fidelity | PASS | `blocklist_lint.py`: 0 Tier-1 hits across 108 terms. No client-banned phrase ("painless", "guaranteed", "#1", "best in LA", "world-class") present. |
| G10 Source resolution / no fabrication | **FAIL** | 0 inline citations. Efficacy claims (osseointegration timeline, survival rates, bone-loss prevention) are marked [VERIFY-AT-PUBLISH] in `sources.md`, not cited on the page. |
| G11 Schema + NAP | PASS | `schema_validator.py`: 19 typed nodes, no issues. `nap_checker.py`: NAP byte-consistent with `brand.yaml`. |
| G12 Google compliance spine | PASS | `compliance_lint.py`: no blocking issues. No doorway, cloaking, stuffing, or deceptive-claim pattern. |
| G13 Conversion | PASS | `conversion_linter.py`: 0 errors after adding `tel:` click-to-call. 1 warning (MISSING_PRICE_SIGNAL) judged a false negative: the page names 4 explicit cost drivers and an honest quote-after-scan reason, which the spec permits in place of a published price. |

## Vertical overlay: medical / dental (MED-1 to MED-6)

| Rule | Result | Evidence |
|---|---|---|
| MED-1 Licensed-provider clinical review | PASS | "Clinically reviewed by Dr. Elena Marquez, DDS, Board-Certified Periodontist" byline present and traces to `brand.yaml.eeat.reviewer`. |
| MED-2 No guarantee / cure / "painless" | PASS | Scanned clean. Page explicitly states "high is not the same as guaranteed" and names risks rather than erasing them. |
| MED-3 Health-claim substantiation | **FAIL** | Efficacy and safety statements have no substantiating source on the page. FTC requires competent and reliable evidence for health-benefit claims. Blocking. |
| MED-4 HIPAA consent for patient assets | PASS | Zero patient testimonials, review quotes, names, or before/after images on the page, because `brand.yaml.eeat.consents[]` is empty. The constraint was enforced at draft time, not patched afterward. |
| MED-5 No fabricated outcomes / patients | PASS | No patient stories, no composite cases, no invented results. |
| MED-6 No self-serving review markup | PASS | `schema_validator.py` confirms no `review`/`aggregateRating` on the Dentist node (spine D3). |

## Remediation required before publish

1. **G1 / Law 16 (Experience):** print Dr. Marquez's and Dr. Chen's real California DDS license numbers on the page (publicly verifiable via the Dental Board of California), add at least one dated, geotagged photo of a real case, and link the review count to the real Google profile.
2. **G10 / MED-3 (substantiation):** fetch and cite real clinical sources for the survival-rate, osseointegration, and bone-preservation statements, or remove the claims. Cite or do not claim.
3. **MED-4 note:** if the practice wants before/after images or a patient testimonial, it must first obtain signed HIPAA marketing authorizations and key them into `brand.yaml.eeat.consents[]`. No consent, no asset.
4. **State board check:** confirm the California Dental Board advertising rules for any close-to-the-line phrasing before publish (jurisdiction-dependent per the overlay).

## Why this is the correct outcome

The page is well-structured, on-voice, compliant, converting, and readable. It fails on exactly the thing this system exists to enforce: **it asserts Experience it cannot prove.** "6,000+ implants since 2009" and "board-certified periodontist" are strong claims with no artifact on the page that a reader or a rater could check, and the clinical claims carry no source.

Every competitor content tool would have shipped this page. The gate stack blocked it. That is Law 16 and Law 8 working as designed: the moat is not polished prose, it is provable first-party fact, and the system refuses to fake it.

## Tooling note from this run

`blocklist_lint.py` initially produced 26 false positives on this page (matching "at our practice", "at once", "from consult to final crown"). Root cause: `_split_head` comma-split the blocklist phrase "at [Brand], we understand that..." into the fragment "at [Brand]", which compiled to a 1-to-4-word wildcard. Fixed during this run: placeholder-bearing phrases are no longer comma-split, and any placeholder term with fewer than two literal anchor words is dropped as too generic. Self-test re-verified; hits on this page went 26 -> 0.
