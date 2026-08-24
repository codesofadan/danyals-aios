# The Local AI-Citation Stack

This is the operational framework for getting a local page named inside an AI answer (Google AI Overviews and AI Mode, ChatGPT Search, Perplexity, Gemini), not just ranked on the blue links. It operationalizes doctrine Law 17 (add statistics, citations, operator quotes; never stuff) and Law 13 (optimize for the answer, not only the link), and it is the checklist form of `ai-search-reality-2026.md` Truth 6.

The one idea that governs everything here: **an AI citation is won on two tracks at once, and this system controls only one of them cleanly.** The page-controllable track is extractability and substance. The off-page ops track is entity corroboration. A page can be perfect on the first track and still never get cited because the second track is broken. So the framework separates the two, tells the writer exactly what to do on the page, and forces a flag on every ops-track item that is missing, so a silent off-page block never gets mistaken for a writing failure.

Grounding: all figures below trace to the research pass in `research/expansion-2026-07/04-geo-ai-search.md`, which fetched every source live 2026-07-20 PKT. The Princeton figures are the primary academic evidence; the per-engine figures are 2026 industry analysis, directional and fast-drifting. Labeled where it matters.

---

## The two tracks

### Track A: page-controllable levers (what this system owns)

These are the levers a writer pulls on the page itself. Every one has evidence behind it. They are ordered by evidence strength for the Business-and-Facts domain that local service pages live in.

1. **Direct-answer-first, extractable H2s.** Every H2 is a self-contained passage block that opens with a one-sentence direct answer to the real buyer question, holds one verifiable claim per paragraph, and closes on a citable fact. This is the retrieval boundary the engines lift. A flowing essay has no clean boundary and gets cited rarely; a page built as a federation of passages can be cited multiple times for multiple sub-queries. See `passage-block-protocol.md` for the full anatomy. This is the structural precondition for every other lever: a statistic buried in an essay is not extractable.

2. **Statistic density with sources.** Replace every vague claim with a concrete number, and where the claim is contestable, name the source. "Drain cleaning in Phoenix runs $150 to $350 depending on access" beats "affordable drain cleaning." In the Princeton study, Statistics Addition lifted position-adjusted word count to 25.9% from a 19.3% baseline (about +34%), and Cite Sources reached 24.9% (about +29%). For a local business the strongest statistics are its own operational data (job counts, response times, price ranges, warranty terms): first-hand, falsifiable, and doubling as the Experience marker Law 16 demands.

3. **Fluency.** Clean, readable prose measurably lifts citation. Fluency Optimization reached 25.1% in the study (about +30%), and it is one of the top movers specifically in the Business, Science, and Health domains (Table 2). This is the counterintuitive finding most GEO advice gets backwards: an "authoritative" confident tone alone was one of the *weakest* movers (21.8%, about +13%). Rhythm and clarity beat bravado. This is why the readability gate is a citation lever, not just a UX nicety.

4. **Operator and expert quotes.** Quotation Addition was the single highest mover in the study: 27.8%, about +44%. For a local page that means a real quote from the licensed operator, harvested in the SME interview ("In 1920s Highland Park homes we usually find the gas line predates code"). It lifts citation and doubles as a first-hand Experience marker no competitor and no model can scrape.

5. **Schema as machine-readable claims.** LocalBusiness JSON-LD (with geo, hours, areaServed, service list, sameAs) is how the page hands the engine clean, unambiguous facts about the entity. The engine treats schema as asserted claims and checks them against the corroborated web picture. Every field must match visible content and the real business. See `schema-library.md`. Schema is Track A in that you write it, but it is the bridge to Track B: its `sameAs` pointers are how the page connects to the entity graph.

6. **Freshness, earned.** AI systems cite older content less in 2026. A visible last-updated stamp with genuinely refreshed data and examples maintains citation eligibility. Per Law 19, the date only moves when the substance moves. A date-only bump is signal-gaming, crawlers discount it, and it is a low-value tactic under Law 8.

7. **The negative lever: never keyword-stuff.** Keyword stuffing was the only tested tactic that *reduced* citation: 17.8%, about -8% below baseline. It also trips compliance rule B3. Padding exact-match density to fake relevance is a citation-negative move, not a neutral one. `scripts/keyword_density.py` enforces the ceiling.

### Track B: the off-page ops track (what the page cannot fix, only flag)

The single most important 2026 local finding: **the biggest citation lever is entity corroboration, and it lives off the page.** Fewer than half the brands that lead traditional local search appear in AI recommendations, because AI answers cross-reference the business across many sources and default to the most-corroborated version of the facts. The page's job is to reinforce the same entity facts; it cannot manufacture corroboration that does not exist elsewhere. Each item below is an ops flag on every page brief, not a writing task.

1. **Google Business Profile completeness.** The strongest single anchor. Gemini is grounded directly in Google Maps, so a thin or inactive GBP caps citation regardless of page quality. Google also increasingly cites its own properties for local: SE Ranking (via Digital Applied) found citations to google.com rose about 8.4x April to June 2026, driven by Business Profile and Product Knowledge Panel subpaths, outnumbering the next six domains combined. Consequence: the GBP is infrastructure, and the website's citation opening is the specific-answer query the GBP card cannot fully answer (pricing logic, process, edge cases, "how fast," "what's included"). Write the page for the questions the card cannot hold.

2. **NAP corroboration.** Business name, address, phone, hours, and service list must agree character-for-character across GBP, website schema, and every directory. When sources conflict, the engine distrusts the business or answers with a competitor's more-consistent data. Reported local-fact accuracy is uneven (around 68% on ChatGPT and Perplexity versus near-100% on Gemini). Inconsistent NAP is an ops flag, never something to paper over on one page.

3. **Third-party directories and reviews.** Corroboration across trusted third-party sources is the price of entry, and it is where nearly all local businesses are weak. Reviews that name the specific service and city feed the engines the entity-plus-context they cite. On ChatGPT, reviews act as a confidence *threshold* not a gradient: recommended locations average about 4.3 stars, and locations near 3.4 stars with response rates under 5% are effectively invisible.

4. **Wikidata and sameAs entity graph.** Wikidata is the highest-leverage sameAs target because it is a primary input to Google's Knowledge Graph; a Q-number entry effectively guarantees a Knowledge Graph entity. Organization schema with `sameAs`, `knowsAbout`, and pointers to authoritative external IDs (Wikidata, LinkedIn, Crunchbase) improves entity recognition, typically showing in Knowledge Graph references in about 4 to 12 weeks. This is the machine-readable backbone under Truth 4. The page emits the `sameAs`; the ops track earns the destinations worth pointing at.

---

## The Princeton GEO evidence (primary)

The foundational study is "GEO: Generative Engine Optimization" (Aggarwal, Murahari, Rajpurohit, Kalyan, Narasimhan, Deshpande), Princeton, Georgia Tech, Allen Institute for AI, and IIT Delhi, published at KDD 2024, arXiv 2311.09735. It tested 9 content tactics across about 10,000 queries (the GEO-BENCH benchmark) on a Bing-Chat-like generative engine, validated live on Perplexity. It introduced the metric the field now borrows: Position-Adjusted Word Count (how much of your source appears in the answer, weighted by position). Baseline visibility across sources was 19.3%.

| Tactic | Position-adjusted word count | Relative gain vs 19.3% baseline |
|---|---|---|
| Quotation Addition | 27.8% | about +44% |
| Statistics Addition | 25.9% | about +34% |
| Fluency Optimization | 25.1% | about +30% |
| Cite Sources | 24.9% | about +29% |
| Technical Terms | 23.1% | about +20% |
| Easy-to-Understand | 22.2% | about +15% |
| Authoritative tone | 21.8% | about +13% |
| Unique Words | 20.7% | about +7% |
| **Keyword Stuffing** | **17.8%** | **about -8% (hurts)** |

Three findings matter more than the ranking itself:

- **Gains are domain-dependent (Table 2).** No single tactic wins everywhere. For the Business, Facts, and Statement domains that local pages resemble, Fluency, Cite Sources, and Statistics are the highest-yield moves, and Authoritative tone alone is weak. This is the opposite of the "sound confident" advice most GEO blogs give.
- **The lift concentrates on lower-ranked sources (Table 3).** When all sources optimize at once, a rank-5 source gained about +115% (Cite Sources), +100% (Quotation), +98% (Statistics), while rank-1 sources *lost* 23 to 30% of their share. GEO is a leveler: a page that ranks #5 to #12 but is structured for extraction can take citation share from a #1 that is not. This is the mechanism behind Truth 2 (citation decoupled from top-10 rank).
- **Live Perplexity validation (Table 5):** Quotation +22% (position-adjusted), Statistics +37% (subjective impression). The lab result survived contact with a real engine.

**Critical caveat, do not overclaim to clients:** the paper predates the current engines (GPT-4o/5, Gemini 2.x, live AI Mode) and tested a Bing-Chat proxy. The *direction* (stats, quotes, citations, and fluency beat keyword stuffing, and the effect is domain-conditional) is robust and repeatedly re-observed. The exact percentages are historical, not a 2026 promise. Treat the tactics as validated priors and the numbers as history. Never quote "40% lift" to a client as a guarantee.

Sources:
- Primary paper (full text): https://ar5iv.labs.arxiv.org/html/2311.09735 and PDF https://arxiv.org/pdf/2311.09735v1
- Plain-English breakdown (cross-checks the numbers): https://derivatex.agency/blog/princeton-geo-paper-plain-english/
- Independent tactic summary: https://www.stackmatix.com/blog/generative-engine-optimization-paper
- Critical read of the evidence: https://sunilpratapsingh.com/guides/geo/what-research-says-about-generative-engine-optimization

---

## The per-engine reality: the engines disagree wildly

There is no single "AI search" to optimize for. The engines select and cite local sources by different mechanics, and citation share is only meaningful reported per engine (see `scripts/share_of_answer_tracker.py`). This is why blending engines produces fiction.

**Google AI Overviews and AI Mode.** AI Mode uses query fan-out: it decomposes "best emergency plumber in Phoenix" into many sub-queries and assembles the answer from several pieces of local evidence, so every service-in-city page is a potential citation surface. Local answers are grounded in the same infrastructure as Maps and the Knowledge Graph (GBP completeness, review volume and recency, NAP consistency). Google cites its own properties heavily for local (the 8.4x rise noted above; Travel = 53% of AI Mode answers cite Google). The page's opening is the specific-answer query the GBP card cannot fully hold.

**Perplexity.** Cites sources at a far higher rate than ChatGPT: one 34,234-response study found a 46x gap (ChatGPT 0.59% versus Perplexity 13.05% brand citation). Perplexity pulls from a diverse third-party set (review platforms, directories, industry press) and is the easiest engine to earn a local citation in. SOCi's 2026 Local Visibility Index: 7.4% location visibility on Perplexity versus 1.2% on ChatGPT versus 35.9% in Google's local 3-pack.

**ChatGPT Search.** Stingy with citations, high bar. Reviews act as a confidence threshold, not a gradient: recommended locations average about 4.3 stars; near 3.4 stars with response rates under 5% they are effectively invisible. Corroboration across multiple trusted third-party sources is the price of entry.

**Gemini.** Grounded in Google Maps, so local factual accuracy is near-100% (versus about 68% for ChatGPT and Perplexity). It wins or loses on the GBP and Knowledge Graph layer, not on page prose.

The cross-engine takeaway: single-channel strength is insufficient. The corroboration profile (third-party directories, reviews, consistent entity data) is where nearly all local businesses are weak, and it is mostly an ops or off-page job. The page's controllable lever is the specific extractable answer; the citation depends on the entity being corroborated off-page. Write the page assuming the entity work is a parallel ops track, and flag it when it is missing.

Sources:
- Google self-citation analysis: https://www.digitalapplied.com/blog/google-cites-itself-ai-mode-gbp-product-schema-visibility-2026
- Query fan-out: https://www.cheers.tech/geo-academy/what-is-query-fan-out-google-ai-mode
- Per-engine sourcing: https://www.leapd.ai/blog/ai-visibility/how-chatgpt-google-ai-overviews-and-perplexity-source-information-in-2026
- Cross-engine local ranking: https://www.soci.ai/blog/how-to-rank-in-chatgpt-perplexity-and-google-ai-overview/
- Perplexity citation mechanics: https://www.pleiadesconsultancy.com/blog/how-to-get-cited-by-perplexity-ai-2026
- Citation ROI statistics: https://www.demandlocal.com/blog/chatgpt-and-perplexity-citation-roi-statistics/

---

## The stack as a per-page checklist

Run this on every page brief. Track A items are pass/fail against the page-type playbook. Track B items are ops flags: mark each present, missing, or unknown, and surface the missing ones in the brief so no citation is silently blocked off-page.

**Track A (page, this system enforces):**
- [ ] Every H2 opens with a direct one-sentence answer (passage-block protocol; `scripts/geo_page_linter.py`).
- [ ] Statistic density meets the playbook minimum, each contestable stat sourced.
- [ ] At least one real operator or customer quote, harvested in the SME interview.
- [ ] Prose clears the readability band (`scripts/readability_scorer.py`).
- [ ] LocalBusiness + Service + BreadcrumbList schema, every field matching visible content (`scripts/schema_validator.py`), with `sameAs` pointers.
- [ ] Visible last-updated stamp, earned by a real content delta (Law 19).
- [ ] No keyword stuffing (`scripts/keyword_density.py`).

**Track B (ops, flag when missing):**
- [ ] GBP complete and active (categories, hours, services, photos, Q&A).
- [ ] NAP identical across GBP, site schema, and directories.
- [ ] Third-party directory listings and recent reviews naming service + city.
- [ ] Wikidata entry or a plan for one; `sameAs` targets that actually exist.

---

## Honest limits

- The Princeton numbers are 2023 to 2024 on a Bing-Chat proxy. Direction is robust; exact percentages are historical.
- Per-engine local stats (SOCi index, the 46x gap, Google's 8.4x self-citation) are 2026 industry analysis, directional, and drift fast. Re-verify quarterly.
- The biggest local-citation lever (entity corroboration and GBP) is mostly off the page this system controls. The honest positioning: SEO-CONTENT-OS owns the extractable-answer half of the stack and measures the whole, and it must flag the ops-track half rather than pretend a page alone wins the citation.
- llms.txt has no measurable citation benefit today. See `knowledge/doctrine/llms-txt-verdict.md`. Do not build it as a feature.

*Sources fetched live 2026-07-20 PKT via `research/expansion-2026-07/04-geo-ai-search.md`. Primary academic figures from arXiv 2311.09735 (KDD 2024). Industry-analysis figures are directional; re-verify before quoting to a client.*
