# GEO / AI-Answer-Engine Optimization for Local - Research and Build Map

Territory: Generative Engine Optimization (GEO) and AI-answer-engine citation for local service businesses. Goal: make SEO-CONTENT-OS the world's best at getting a local page named inside AI answers (Google AI Overviews, AI Mode, ChatGPT Search, Perplexity, Gemini), measured as share of answer, not blue-link rank alone.

Grounding: builds on `knowledge/doctrine/ai-search-reality-2026.md` (Truths 2, 3, 4, 6, 10) and doctrine Law 13 (optimize for the answer) and Law 8 (no detector games). This file adds the primary GEO research literature, the per-engine local citation mechanics, the entity/LLMO layer, and the one thing the doctrine names but does not yet operationalize: a manual, repeatable share-of-answer measurement method.

All web sources fetched live 2026-07-20 PKT. Academic figures are from the primary paper; per-engine and adoption figures are 2026 industry analysis, directional and fast-drifting. Labeled where it matters.

---

## 1. The GEO research literature: what actually moves citation (primary evidence)

The foundational study is "GEO: Generative Engine Optimization" (Aggarwal, Murahari, Rajpurohit, Kalyan, Narasimhan, Deshpande), Princeton + Georgia Tech + Allen Institute for AI + IIT Delhi, published KDD 2024, arXiv 2311.09735. First large-scale academic test of how to optimize content for AI citation: 9 content tactics across ~10,000 queries (the GEO-BENCH benchmark), on a Bing-Chat-like generative engine, validated live on Perplexity.

It introduced the metrics this whole field now borrows: **Position-Adjusted Word Count** (how much of your source appears in the answer, weighted by where it appears) and **Subjective Impression** (a model-judged relevance/influence score). Baseline visibility across sources was 19.3%.

### Exact tactic results (Table 1, position-adjusted word count vs 19.3% baseline)

| Tactic | Absolute | Relative gain |
|---|---|---|
| Quotation Addition (add relevant quotes from experts/sources) | 27.8% | ~+44% |
| Statistics Addition (replace vague claims with concrete numbers) | 25.9% | ~+34% |
| Fluency Optimization (cleaner, more readable prose) | 25.1% | ~+30% |
| Cite Sources (add citations/references to authoritative sources) | 24.9% | ~+29% |
| Technical Terms | 23.1% | ~+20% |
| Easy-to-Understand | 22.2% | ~+15% |
| Authoritative (confident, authoritative tone) | 21.8% | ~+13% |
| Unique Words | 20.7% | ~+7% |
| **Keyword Stuffing** | 17.8% | **~-8% (hurts)** |

Two findings matter more than the ranking itself:

**(a) Gains are domain-dependent (Table 2).** No single tactic wins everywhere. Winners by domain:
- Cite Sources -> Statement, Facts, **Law & Government**
- Statistics Addition -> Law & Government, Debate, Opinion
- Quotation Addition -> People & Society, Explanation, History
- Authoritative -> Debate, History, Science
- Fluency -> **Business, Science, Health**

Implication for local service pages: they are closest to the **Business / Facts / Statement** domains, where **Fluency, Cite Sources, and Statistics** are the highest-yield moves, and Authoritative tone alone is weak. This is the opposite of the "sound confident" advice most GEO blogs give.

**(b) The lift concentrates on lower-ranked sources (Table 3).** When all sources optimize at once, a rank-5 source gained **+115.1% (Cite Sources), +99.7% (Quotation), +97.9% (Statistics)**, while rank-1 sources *lost* 23-30% of their share. GEO is a leveler: a page that ranks #5-#12 but is structured for extraction can take citation share from the #1 that isn't. This is the mechanism behind doctrine Truth 2 (citation decoupled from top-10 rank).

**(c) Live Perplexity validation (Table 5):** Quotation +22% (position-adjusted), Statistics +37% (subjective impression). The lab result survived contact with a real engine.

Sources:
- Primary paper (full text): https://ar5iv.labs.arxiv.org/html/2311.09735 and PDF https://arxiv.org/pdf/2311.09735v1
- Plain-English breakdown (cross-checks the numbers): https://derivatex.agency/blog/princeton-geo-paper-plain-english/
- Independent summary of tactics: https://www.stackmatix.com/blog/generative-engine-optimization-paper
- What the research actually says (critical read): https://sunilpratapsingh.com/guides/geo/what-research-says-about-generative-engine-optimization

**Critical caveat (do not overclaim to clients):** the paper predates the current engines (GPT-4o/5, Gemini 2.x, live AI Mode) and tested a Bing-Chat proxy. The *direction* (stats + quotes + citations + fluency beat keyword stuffing, and the effect is domain-conditional) is robust and repeatedly re-observed; the exact percentages are not a 2026 promise. Treat the tactics as validated priors, the numbers as historical.

---

## 2. How each engine selects and cites LOCAL sources (per-engine mechanics)

The single most important 2026 finding for local: **the engines disagree wildly on what they cite, and Google increasingly cites itself.**

### Google AI Overviews / AI Mode
- AI Mode uses **query fan-out**: it decomposes "best emergency plumber in Phoenix" into many sub-queries and assembles the answer from several pieces of local evidence, not one ranking page. A multi-location or service-area business is assembled from fragments, so every service-in-city page is a potential citation surface (source: Cheers GEO Academy, Subscribe PR fan-out playbook).
- Local answers are grounded in the **same infrastructure as Maps and the Knowledge Graph**: GBP completeness, review volume/recency/language, NAP consistency decide who gets named (PinMeTo, Ditans, MapAtlas).
- **Google cites its own properties heavily for local.** SE Ranking (via Digital Applied) found citations to google.com rose **8.4x April-June 2026**, driven by Business Profile and Product Knowledge Panel subpaths; google.com citations outnumber the next six domains combined (YouTube, Facebook, Reddit, Amazon, Indeed, Zillow). Home services, restaurants, real estate, healthcare, travel are where self-citation concentrates (Travel = 53% of AI Mode answers cite Google). **Consequence: the GBP is infrastructure, not a listing; the website's citation opportunity is the specific-answer query the GBP card cannot fully answer** (pricing, process, edge cases, "how fast," "is X included"). Write for the questions the card can't.

Sources: https://www.digitalapplied.com/blog/google-cites-itself-ai-mode-gbp-product-schema-visibility-2026 , https://www.cheers.tech/geo-academy/what-is-query-fan-out-google-ai-mode , https://subscribepr.com/blog/how-to-rank-in-google-ai-mode/

### Perplexity
- Cites brands/sources at a far higher rate than ChatGPT: one 34,234-response study found a **46x gap** (ChatGPT 0.59% vs Perplexity 13.05% brand citation). Perplexity pulls from a **diverse third-party set** (review platforms, directories, industry press) and is the easiest engine to earn a local citation in. For local, SOCi's 2026 Local Visibility Index: 7.4% location visibility on Perplexity vs 1.2% on ChatGPT vs 35.9% in Google's local 3-pack.

### ChatGPT Search
- Stingy with citations, high bar. Reviews act as a **confidence threshold, not a gradient**: ChatGPT-recommended locations average **4.3 stars**; locations near 3.4 stars with review-response rates under 5% are effectively invisible. Corroboration across multiple trusted third-party sources is the price of entry.

### Gemini
- Grounded in Google Maps, so local factual accuracy is near-100% (vs ~68% reported for ChatGPT/Perplexity per the doctrine's Truth 4). Wins/loses on the GBP + Knowledge Graph layer, not page prose.

### The cross-engine takeaway
Single-channel strength is insufficient: fewer than half of brands that lead traditional local search appear in AI recommendations. The corroboration profile (third-party directories, reviews, consistent entity data) is where nearly all local businesses are weak, and it is mostly an ops/off-page job, not a page-copy job. **The page's controllable lever is the specific extractable answer; the citation depends on the entity being corroborated off-page.** Write the page assuming the entity work is a parallel ops track, and flag it when it's missing.

Sources: https://www.leapd.ai/blog/ai-visibility/how-chatgpt-google-ai-overviews-and-perplexity-source-information-in-2026 , https://www.soci.ai/blog/how-to-rank-in-chatgpt-perplexity-and-google-ai-overview/ , https://www.pleiadesconsultancy.com/blog/how-to-get-cited-by-perplexity-ai-2026 , https://www.demandlocal.com/blog/chatgpt-and-perplexity-citation-roi-statistics/

---

## 3. Entity SEO / LLMO for local: what has evidence, what is hype

**Has evidence - entity consistency and Knowledge Graph presence:**
- Wikidata is the **highest-leverage sameAs target** because it is a primary input to Google's Knowledge Graph; a Wikidata Q-number entry effectively guarantees a Knowledge Graph entity. `sameAs`, `knowsAbout`, and Organization schema pointing to authoritative external IDs (Wikidata, LinkedIn, Crunchbase) improve entity recognition; a fresh Organization + strong sameAs deploy shows in Knowledge Graph references in ~4-12 weeks (Digital Applied entity guide, Jottler, Ahrefs KG guide). This is the machine-readable backbone under doctrine Truth 4 (entity/NAP consistency).
- For local specifically: consistent NAP + business name + service list + hours across GBP, website schema, and directories is what lets the engines agree on who you are. Entity confidence, not backlinks, decides the local citation.

**Weak / hype - llms.txt:** The evidence is brutal and worth stating plainly so the system does NOT waste a feature on it.
- Adoption ~10% of sites (SE Ranking, 300k domains), but **AI crawlers overwhelmingly do not fetch /llms.txt** - GPTBot, ClaudeBot, PerplexityBot, OAI-SearchBot, Google-Extended crawl HTML directly.
- Google (Gary Illyes, July 2025) confirmed it does **not** support llms.txt and isn't planning to; John Mueller compared it to the discredited keywords meta tag. Anthropic/Perplexity have said they *may* read it when present; no engine's answer-surface citation is measurably improved by it today.
- **Recommendation: do NOT build an llms.txt generator as a citation lever.** If a client wants one it is a cheap, harmless nicety, not a ranking/citation feature. Building it into the doctrine as a "GEO win" would be a fabricated-benefit claim (violates the no-fabricated-success rule). Note it as "low-cost, unproven, optional" and move on.

Aleyda Solis's framing (via Learning AI Search, learningaisearch.com, and Search Engine Land's LLMO guide) is the sane one: LLMO is a **parallel discipline to SEO, not a replacement** - classic SEO indexes and ranks; LLMO earns the citation when the answer is generated. The winning move is running both, and the LLMO-specific work is structure (extractability) + entity (corroboration) + freshness, not a magic file.

Sources: https://www.digitalapplied.com/blog/entity-seo-knowledge-graph-optimization-guide-2026 , https://organikpi.com/blog/distribution/llms-txt-adoption-impact/ , https://okara.ai/blog/llms-txt-guide , https://searchengineland.com/guides/large-language-model-optimization-llmo , https://learningaisearch.com/ , https://ahrefs.com/blog/llm-optimization/

---

## 4. Practical writing moves that increase AI-citation for a local page

Synthesized from the GEO paper (Section 1), the per-engine mechanics (Section 2), and the doctrine's passage-block protocol. Ranked by evidence strength for the local/business domain:

1. **Statistic + source density.** Replace every vague claim with a concrete number and, where possible, a named source. "Drain cleaning in Phoenix runs $150-$350 depending on access" beats "affordable drain cleaning." Statistics Addition and Cite Sources are the paper's top movers in the Facts/Statement/Law domains that local pages resemble. A local business's statistics are its own operational data (job counts, response times, price ranges, warranty terms) - falsifiable, first-hand, exactly the first-hand marker doctrine Truth 1 rewards.
2. **Direct-answer-first passage blocks** (already doctrine Truth 3): one self-contained 100-300 word answer per H2, opening with a one-sentence answer, one verifiable claim per paragraph, closing on a citable fact. This is the retrieval boundary the engines extract.
3. **Fluency.** Clean, readable prose measurably lifts citation in the Business/Health domains (paper Table 2). This is not "sound authoritative" - authoritative tone alone was one of the *weakest* movers. Rhythm and clarity beat bravado.
4. **Real Q&A for extraction, not for the dead FAQ accordion** (doctrine Truth 7): answer the exact questions buyers ask, especially the ones the GBP card can't (pricing logic, process, timelines, "what's included"). Fan-out means each answered sub-question is a citation surface.
5. **Quotation of the operator/expert.** Quotation Addition was the #1 paper mover. For local, that is a real quote from the licensed operator in the SME interview ("In 1920s Highland Park homes we usually find the gas line predates code"). Doubles as a first-hand marker.
6. **Definitional clarity.** State plainly what the service is, where it's offered, who it's for. Entity disambiguation starts on the page.
7. **Freshness.** AI systems cite older content less in 2026; a visible last-updated with genuinely refreshed data/examples maintains citation eligibility (multiple 2026 analyses). Do not fake dates - update the substance.
8. **Do NOT keyword-stuff** - the only tactic that *reduced* citation in the paper, and it trips the doctrine's compliance rule B3.

---

## 5. How to measure share of answer manually (no API) - the missing operational method

Doctrine Truth 10 and Law 13 both name "share of answer" as the real reward, but the system has no method to measure it. This is the highest-priority build. A rigorous manual method, synthesized from the 2026 measurement literature (Nick Lafferty's metrics reference, Contently, GrackerAI):

### Core metrics (pick 3, keep them frozen)
- **Citation Share** = (answers citing your domain / all answers in the frozen prompt set) x 100
- **Share of Voice / mention rate** = (answers mentioning your brand / all answers) x 100 - looser, counts unlinked mentions
- **Presence rate per engine** = share, reported *per engine separately* (mandatory - identical pages showed 18% ChatGPT vs 0% Perplexity, or the reverse; blending engines produces fiction)
- Optional: **Co-citation rate** (who you get cited alongside - names your real AI competitors) and **inline-hyperlink share** (mention with clickable URL vs bare mention).

### Sampling discipline (the rules that make it repeatable)
- **Freeze the prompt set.** "Citation share is only comparable across periods if the prompt set is frozen. Change the prompts and you changed the denominator, and the trend line is fiction."
- **30-100 money prompts** for a single local business (SMB scale); 250-500 only for enterprise/multi-location. Structure them in three buckets: **discovery** ("best emergency plumber in [city]"), **comparison** ("[competitor] vs [client]" / "top 3 X in [city]"), **problem/use-case** ("water heater leaking who to call in [city]", "how much does X cost in [city]").
- **Repeated runs beat more prompts.** "A 50-prompt set run 10 times tells you more about stability than a 500-prompt set run once." AI answers are non-deterministic; run each prompt 3-5x (10x if feasible) and record the citation *frequency*, not a single yes/no. Fan-out uniqueness on ChatGPT was ~91% across runs - one run is noise.
- **Manual capture:** query each engine's consumer UI (ChatGPT, Perplexity, Gemini, Google AI Overview/AI Mode, Copilot) by hand or via saved screenshots; log per run whether the client domain was cited, mentioned, or absent, plus which competitors/domains were cited. No API needed and no ToS-risky scraping (respects the no-API constraint).
- **Report as a distribution, not a point.** Median plus a spread; overlapping weeks = "no measurable trend yet." Citation distributions are power-law, so small samples over-swing.

### The repeatable protocol (turn into a script + template)
1. Define the frozen prompt set (money queries) once per client; store in a CSV/JSON.
2. Each measurement cycle (monthly), run every prompt N times per engine, log results in a fixed schema (prompt, engine, run#, cited y/n, mentioned y/n, competitors_cited, notes, date).
3. A Python script reads the log and computes citation share, SoV, and presence per engine, with a simple bootstrap spread, and diffs against the prior cycle.
4. Output a one-page share-of-answer report: per-engine trend, biggest gap (which engine/query the client is absent from), and the recommended page fix (map the missing query back to a passage block to write/strengthen).

This closes the loop doctrine Truth 10 opens: the system writes for extraction, then *measures* whether extraction happened, then feeds the gap back into the next page brief.

Sources: https://nicklafferty.com/blog/ai-visibility-metrics-reference/ , https://contently.com/2026/03/10/how-to-track-ai-citation-rates/ , https://gracker.ai/blog/how-to-measure-ai-share-of-voice , https://www.ai-advisors.ai/blog/how-to-measure-ai-citation-share

---

## 6. Build map - recommendations by category

Priority order given the brief: (1) manual share-of-answer tracker, (2) GEO framework/laws, then the rest. Effort S/M/L.

### [Python scripts]
1. **`share-of-answer-tracker`** (PRIORITY 1). Reads a frozen prompt-set file + a manually-logged results CSV/JSON; computes citation share, share-of-voice, and presence rate *per engine*, with a bootstrap spread and a diff vs the prior cycle; emits a one-page markdown report naming the biggest per-engine/per-query gap and the page fix. Why #1: it is the only thing that makes Law 13 measurable, turns "share of answer" from a slogan into a managed metric, and creates the write -> measure -> fix loop no competitor content system has. No API, pure local file math (respects constraints). Source: Section 5 / Lafferty, Contently. Effort **M**.
2. **`prompt-set-builder`**. Generates the frozen money-query set (discovery/comparison/problem buckets) for a client from their services + cities + competitor list; outputs the CSV the tracker consumes and a copy-paste run sheet for manual querying. Why: removes the setup friction that kills manual measurement; enforces the "freeze the set" discipline. Effort **S**.
3. **`geo-page-linter`** (extends any existing passage/quality check). Scores a drafted page on the GEO-evidenced levers: statistic density, source/citation presence, direct-answer-first per H2, real-quote presence, keyword-stuffing flag (negative), freshness stamp. Outputs a per-lever score + fix list. Why: operationalizes Section 1's validated tactics at draft time. Effort **M**.

### [laws]
4. **Law: "Statistics + citations + operator quotes, domain-weighted."** New doctrine law (or extend Law 13): every local passage block carries at least one concrete statistic and, where a claim is contestable, a named source or a first-hand operator quote; keyword stuffing is banned as a *citation-negative* move, not just a spam risk. Weight the mix to the business/facts domain (fluency + stats + cite-sources highest; authoritative-tone lowest). Why: this is the single most evidence-backed content rule in the entire GEO literature (Princeton Table 1-2), and most GEO advice gets the tone-vs-substance tradeoff backwards. Source: arXiv 2311.09735 Tables 1-2. Effort **S** (write the law).
5. **Law: "Share of answer is a measured metric, not an aspiration."** Codify the frozen-prompt-set + per-engine + repeated-runs discipline as a hard law: no client engagement claims AI-search success without a share-of-answer baseline and a re-measure. Why: prevents fabricated-success claims about AI citation; enforces the loop. Source: Section 5. Effort **S**.

### [frameworks]
6. **The GEO Content Lever framework** - a one-pager mapping each of the 8 evidenced tactics to (a) its citation lift, (b) the query domain where it wins, (c) how it manifests for a local business, (d) the first-hand marker it doubles as. The writer's cheat sheet for Section 4. Why: turns the paper into a repeatable authoring pattern instead of vibes. Effort **S**.
7. **The Local AI-Citation Stack framework** - extends doctrine Truth 6 into a checklist that separates the two tracks: **page-controllable** (extractable specific answers, stats, quotes, schema) vs **ops-track** (GBP completeness, NAP corroboration, third-party directory/review presence, Wikidata/sameAs entity). Every page brief flags which ops-track items are missing so the citation isn't silently blocked off-page. Why: the #1 reason a well-written local page still isn't cited is an uncorroborated entity, and the system currently has no mechanism to surface that. Effort **S**.

### [skills]
8. **`geo-optimize` skill** - takes a drafted or existing local page and rewrites it against the GEO Content Lever framework (inject stats, add operator quotes from the SME interview, convert essays to direct-answer-first passages, add freshness), then runs the geo-page-linter. Why: packages the highest-yield writing moves into a repeatable action. Effort **M**.
9. **`share-of-answer` skill** - wraps the two scripts into a founder-facing workflow: build the prompt set, produce the manual run sheet, ingest results, generate the report, and translate the biggest gap into the next page brief. Why: makes the measurement loop a single command. Effort **M**.

### [agents]
10. **`entity-consistency-auditor` agent** (read-only) - given a business name + NAP + service list, checks the page's schema/NAP against a supplied set of directory/GBP facts and flags conflicts + missing sameAs/Wikidata targets, mapping to the ops-track. Why: entity corroboration is the top local-citation blocker and is auditable. Effort **M**. (No API: works from pasted/supplied listing data, not live directory scraping.)

### [MD knowledge files]
11. **`knowledge/geo/geo-research-primer.md`** - this file's Sections 1-4 as durable knowledge, so authors have the evidence base and the exact tactic figures on hand. Effort **S**.
12. **`knowledge/geo/llms-txt-verdict.md`** - a short "do not build this as a citation feature; here's the evidence" note, so the hype doesn't creep back in. Effort **S**.

### [examples]
13. **Before/after local passage example** - one service-section rewritten from generic prose to GEO-optimized (direct answer + stat + operator quote + source), annotated with which lever each edit pulls. Why: the fastest way to teach the pattern; doctrine already leans on concrete examples. Effort **S**.
14. **A filled share-of-answer report example** - a sample one-pager for a fictional local business showing per-engine share, the gap, and the resulting page fix. Effort **S**.

---

## 7. Honest limits

- The Princeton numbers are 2023-2024 on a Bing-Chat proxy. Direction is robust and re-observed; exact percentages are historical, not a 2026 guarantee. Never quote "40% lift" to a client as a promise.
- Per-engine local stats (SOCi index, the 46x citation gap, Google's 8.4x self-citation) are 2026 industry analysis, directional, and drift fast. Re-verify quarterly with the doctrine.
- The biggest local-citation lever (entity corroboration + GBP) is mostly *off* the page this system controls. The honest positioning: SEO-CONTENT-OS owns the extractable-answer half of the stack and *measures* the whole, and it must flag the ops-track half rather than pretend a page alone wins the citation.
- llms.txt: no measurable citation benefit today. Do not build it as a feature.

*Sources fetched live 2026-07-20 PKT. Primary academic figures from arXiv 2311.09735 (KDD 2024). Industry-analysis figures are directional; re-verify before quoting to a client.*
