---
name: geo-optimize
description: Optimize a local-SEO page draft for AI-answer citation using the evidenced GEO levers. Use after a draft exists (or on an existing live page) to lift its odds of being named inside Google AI Overviews, ChatGPT, Perplexity, and Gemini answers. Injects sourced statistics and real operator quotes, converts essay sections into direct-answer-first passage blocks, adds an earned freshness stamp, kills keyword stuffing, then runs scripts/geo_page_linter.py to verify. Does NOT do detector-evasion (Law 8). Flags off-page entity gaps it cannot fix.
---

# geo-optimize

Rewrites a local page against the page-controllable levers that move AI-answer citation, then verifies with the linter. This is the action form of `knowledge/foundations/geo-ai-citation.md` (the Local AI-Citation Stack) and doctrine Law 17.

## When to use

- A page draft has cleared the base compliance and voice gates and you want to maximize AI-citation odds before finalizing.
- An existing live page ranks but is not being cited in AI answers (surfaced by `share_of_answer_tracker.py` as a per-engine gap).
- A brief flags a money query the client is absent from and you need to build or strengthen the passage block that answers it.

Do NOT use this to "pass AI detection." There is no such step. Per Law 8 and Truth 8, detector scores have near-zero correlation with rankings, and a detector-evasion feature is a hard line. This skill makes a page more specific and more extractable, which is why it reads human: because it is substantive, not because it was laundered.

## Read first

1. `knowledge/foundations/geo-ai-citation.md` - the two-track stack and the Princeton evidence table.
2. `knowledge/foundations/passage-block-protocol.md` - the anatomy of an extractable H2.
3. `knowledge/doctrine/local-content-laws.md` - Law 17 (add stats/citations/quotes, never stuff), Law 16 (prove experience), Law 19 (no date without a delta), Law 20 (no fabricated proof).
4. `clients/<client>/brand.yaml` and the SME interview notes - the source of every real statistic and quote. Never invent a local fact.

## The levers, in priority order

Apply these to the draft. Each maps to primary evidence (see the framework file).

1. **Direct-answer-first H2s.** Every H2 is a self-contained passage block whose first one or two sentences answer the real buyer question outright. Rewrite any section that opens with filler ("When it comes to...", "There are several factors...", "Every home is different..."). The lead sentence is what an AI Overview lifts verbatim.
2. **Statistic density with sources.** Replace vague claims with concrete numbers, each contestable one attributed. Pull the numbers from `brand.yaml`, the SME interview, or cited live research. A business's own operational data (price bands, response times, job counts, warranty terms) is the strongest kind: first-hand and falsifiable, and it doubles as the Law 16 Experience marker.
3. **Operator/expert quote.** Add at least one real quote from the licensed operator, harvested in the SME interview. Highest single mover in the Princeton study, and a first-hand marker no competitor can scrape. Never fabricate a quote.
4. **Fluency.** Clean, readable prose lifts citation in the business domain more than an "authoritative" tone does. Vary rhythm, one idea per sentence where it earns it. Verify with `scripts/readability_scorer.py`.
5. **Freshness, earned.** Add or update a visible last-updated stamp ONLY when the substance actually changed (Law 19). A date-only bump is signal-gaming and gets discounted.
6. **Kill keyword stuffing.** The only tactic that reduced citation in the study, and a compliance-rule-B3 spam signal. Rewrite exact-match repetition for variety. Verify with `scripts/keyword_density.py`.

## Off-page flag (the half the page cannot fix)

The biggest local-citation lever is entity corroboration, and it lives off the page (Track B of the stack). After optimizing the copy, surface any missing ops-track item so the citation is not silently blocked: GBP completeness, NAP consistency across directories, third-party reviews naming service + city, and a Wikidata / `sameAs` entity presence. State these as ops flags in the output; do not pretend the page alone wins the citation.

## Process

1. Read the framework file, the passage-block protocol, and the client's `brand.yaml` + SME notes.
2. Run the linter on the current draft to get a baseline: `python scripts/geo_page_linter.py <draft.md>`.
3. Apply the six levers, section by section, sourcing every new statistic and quote from real client facts. If a needed statistic or quote does not exist, add an SME-interview question rather than inventing it.
4. Re-run the linter until it passes: `python scripts/geo_page_linter.py <draft.md>`. Then confirm `readability_scorer.py` and `keyword_density.py` still pass.
5. Emit the optimized draft plus a short GEO note: which levers were pulled, the before/after linter result, and the off-page ops flags that still block full citation.

## Output

- The optimized `page.md` (or a diff against the original).
- A GEO note listing levers applied, the linter pass result, and the Track B ops flags outstanding.
- Any new SME-interview questions generated when a real statistic or quote was needed but not yet on hand.

## Guardrails

- No fabricated local facts, statistics, quotes, urgency, or proof (Laws 16, 20; compliance G1/G10).
- No detector-evasion or humanizer pass, ever (Law 8).
- No date advance without a real content delta (Law 19).
- Cite or do not claim: every external statistic carries its source URL in `sources.md`.
