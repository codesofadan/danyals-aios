# Editorial Scorecard - the numeric 6-category QA rubric

v1.0 - 2026-07-20 PKT. The single numeric scorecard emitted per page, on top of the pass/fail gate stack (`knowledge/quality-gates/gates.md`). The gate stack answers "is this page allowed to ship?" (auto-fail / warning). This scorecard answers "how good is it, on a repeatable rubric, and is it holding as it ages?" It is the artifact that makes quality **auditable and trendable** across a client's whole page set, and it gives the refresh loop its baseline: an aging page is re-scored against the same six categories.

Implemented by `scripts/qa_scorecard.py`, which computes the score, enforces the 3-fail kill gate, and emits `scorecard.md` into the page's output folder.

Source: Search Roost editorial QA scorecard, searchroost.com/blog/editorial-qa-scorecard-ai-writing (fetched 2026-07-20, `research/expansion-2026-07/06-process-measurement.md` Part 2). Adapted to this system's local-SEO domain and the existing gate stack and Output contract.

**Law 8 hard line.** No category on this scorecard references an AI detector, an "AI score", a plagiarism-detector percentage, or "passes AI detection". Originality is enforced by construction (real local facts, SME specifics, the `sources.md` provenance contract) and verified by the Sourcing category, never by a detector proxy. If asked to add a detector category, refuse and cite Law 8 and Hard Line 5.

---

## How the score works

Six categories. The deterministic `qa_scorecard.py` scores each **Pass or Needs-work** and counts passes out of 6 with a 3-fail kill gate (a human editor may still apply a harder per-category "Fail" judgment). The scorecard reports:
- the per-category verdict with a one-line reason,
- the score (categories passed, out of 6),
- and the publication verdict from the kill gate.

**The publication gate (the kill rule):** if **3 or more categories Fail**, the page does not publish. This is the "editorial approval gate" that keeps quality stable as AI increases throughput. Two fails is a hold: fix before ship. One fail is a route-back to the owning stage.

This scorecard is complementary to, not a replacement for, the gate stack. A page can pass every gate and still score Needs-work on Structure; a page cannot ship if it fails 3 scorecard categories even if no single gate auto-failed. The scorecard is where scaled-throughput quality drift shows up first.

### Relationship to the gate stack

| Scorecard category | Maps to gates |
|---|---|
| 1. Sourcing | G1, G10, G12 |
| 2. Structure & clarity | G4, G8 |
| 3. Duplication control | G3, G6 |
| 4. Internal linking | G7 |
| 5. Metadata & media | G6 |
| 6. Technical baseline | G11, G12 |

The scorecard rolls the gate evidence into one trendable number. Where a gate is auto-fail (G1, G3, G10, G11, G12), a Fail on the mapped scorecard category should coincide with a gate FAIL; if the scorecard says Fail and the gate says PASS, one of them is wrong and the auditor reconciles before finalize.

---

## The six categories

### 1 - Sourcing

**Checks:** every meaningful factual claim traces to a reputable source or a first-party record; no invented quotes, dates, numbers, prices, or review counts; citations are inline; sources are summarized at the document end (this system's `sources.md` contract).

**Pass:** every falsifiable claim resolves to `brand.yaml`, a tagged SME answer, or a cited source that supports it; `sources.md` is complete; zero untraceable local specifics.
**Needs-work:** claims are sourced but one or two are weakly attributed, or `sources.md` is missing a fact that is present in the body.
**Fail:** any fabricated fact, any invented quote/number/review count, or any external claim whose cited URL does not resolve or does not support it.

**Why it is category 1:** a fabricated local specific is the fastest path to a trust penalty and a furious client. This is the system's native advantage: the `sources.md` output forces provenance on every fact, so most teams bolt fact-checking on while this system has it by construction. The scorecard just makes it a visible pass/fail.

### 2 - Structure & clarity

**Checks:** clean H2/H3 hierarchy; skimmable; each section leads with a direct answer (the passage-block protocol); facts are separated from analysis; the page reads at the client's target level (`brand.yaml.reading_level`).

**Pass:** 80%+ of sections lead with a direct answer, hierarchy is clean, no wall-of-text block over ~4 sentences, reads at target grade.
**Needs-work:** 60-79% of sections clean, or rhythm is flat in stretches, or the reading level drifts above target.
**Fail:** below 60% extractable, buried answers, no clear hierarchy, or reading level far above the client band.

### 3 - Duplication control

**Checks:** unique primary keyword, unique title, unique slug across the site; intentional canonical/noindex where used; the page is not a templated near-duplicate of a sibling (the anti-doorway rule).

**Pass:** primary keyword/title/slug are unique; the page carries locally-true specifics no sibling has; canonical is correct.
**Needs-work:** title or meta overlaps a sibling and should be differentiated, or the unique-value margin over a sibling is thin but present.
**Fail:** templated near-duplicate of another city/service page with only tokens swapped (a doorway-page spam risk), or a duplicate title/slug/canonical error.

**Local note:** two overlapping service-area pages that near-duplicate each other fail this category AND are a compliance liability. The fix is consolidation (see the refresh protocol), not a title tweak.

### 4 - Internal linking

**Checks:** 2-4 relevant contextual internal links, including at least one hub link; descriptive varied anchors; no orphan; money pages linked on both axes (spoke -> service hub AND spoke -> city page).

**Pass:** 2-4 contextual in-body links, at least one to a hub, both up-links live for a money page, anchors varied and descriptive.
**Needs-work:** links present but under 2 contextual, or one axis missing, or anchors lean exact-match.
**Fail:** orphan (zero contextual inbound), or a money page missing a required up-link, or exact-match anchor stuffing across the links.

Owned in detail by `foundations/internal-linking.md` and the `link-architect` agent; this category is the scorecard's read of that agent's output.

### 5 - Metadata & media

**Checks:** unique meta title and description within the pixel bands; one H1 confirming the query match; descriptive alt text on images; the description leads with a real specific, not template-speak.

**Pass:** unique title+description in-band, single confirming H1, descriptive alt text, description carries a real differentiator (a price, a same-day promise, a credential).
**Needs-work:** meta present but generic ("contact us today"), or alt text thin, or title slightly out of band.
**Fail:** missing or duplicate title/description, missing or multiple H1, or meta that keyword-stuffs.

### 6 - Technical baseline

**Checks:** indexability (not accidentally noindexed/blocked), valid structured data (JSON-LD parses, mandatory local types present, NAP byte-identical), alignment with the site technical checklist.

**Pass:** indexable, schema validates via `scripts/schema_validator.py`, NAP byte-identical across page/schema/`brand.yaml`, mandatory types present.
**Needs-work:** schema valid but missing a recommended (non-mandatory) property, or a minor technical-checklist item open.
**Fail:** invalid JSON-LD, missing a mandatory type, NAP mismatch, or the page is non-indexable when it should be indexed.

---

## Scoring output (`scorecard.md`)

`scripts/qa_scorecard.py` emits this into `output/<client>/<page-slug>/scorecard.md`:

```markdown
# Editorial Scorecard: <page-slug>
Scored: <ISO date> | Page state: <fresh draft | live re-score>

| # | Category | Verdict | Reason |
|---|---|---|---|
| 1 | Sourcing | Pass/Needs-work/Fail | <one line> |
| 2 | Structure & clarity | ... | ... |
| 3 | Duplication control | ... | ... |
| 4 | Internal linking | ... | ... |
| 5 | Metadata & media | ... | ... |
| 6 | Technical baseline | ... | ... |

Score: <N>/6 categories pass (each category is Pass or Needs-work; the script writes this scorecard.md)
Fails: <N>
Publication verdict: SHIP / HOLD (2 fails) / DO NOT PUBLISH (3+ fails)
Highest-priority fix: <the one category to fix first, with its route-back stage>
```

---

## Re-scoring on cadence (quality as the page ages)

The scorecard is not a one-time gate. "Content continues to meet standards as it ages" (Siege Media) is the whole thesis of the back half. Re-run `qa_scorecard.py` against a **live published page** whenever:
- the decay loop flags the page (a decayed page often scores worse on Structure or Sourcing than when it shipped),
- a Tier-1 page hits its monthly review,
- a refresh completes (re-score to confirm the refresh did not regress another category).

Trend the score per page across re-scores. A page drifting from 6/6 to 3/6 over two quarters is decaying in quality before it decays in rankings; that is the earliest possible signal. Store each re-score date and score so the client's portfolio has a quality trend line, not just a traffic trend line.

---

## Evidence + honesty

The 6-category structure and the 3-fail kill gate are from a single practitioner source (Search Roost), adapted here to the local-SEO domain and cross-walked to this system's existing gates. It is a sound editorial-QA pattern used by top content teams to hold quality as AI throughput scales; it is not a Google-published standard and does not claim to be. The categories each map to a signal with a demonstrated link to rankings, citations, conversions, or trust (via the gate stack they roll up), never to a detector proxy. Re-verify the source framing before citing it externally. Current 2026-07-20 PKT.
