# Topical Authority + Content-Optimization Tooling: Path to #1

Research territory: content-optimization tooling and topical-authority methodology for SEO-CONTENT-OS.
Author pass: expansion sprint 2026-07. All URLs fetched 2026-07-20 PKT.
Discipline: separate what actually moves rankings from vendor marketing. Every recommendation is offline-buildable (no external APIs), consistent with doctrine Law 8 (optimize the reward function, not detector-evasion proxies).

---

## 0. The one-sentence thesis

The commercial optimizers (Surfer, Clearscope, MarketMuse, Frase, Koala) all do the same core trick - reverse-engineer the terms and structure of the current top 10-30 SERP results and score your draft's coverage against that corpus - which means they can only ever help you **match the consensus**. Google's information-gain patent rewards the opposite: content that **diverges** from the consensus with net-new value. A local content system that already writes from real first-hand specifics (G1) is architecturally positioned to win the game the SaaS tools structurally cannot play. The build is therefore two-sided: (a) an offline **coverage** scorer that approximates what Surfer/Clearscope do from the SERP corpus, and (b) an offline **information-gain / divergence** scorer that measures net-new value - the second being the actual moat.

---

## 1. How the commercial optimizers actually score content

### 1.1 Surfer SEO

Surfer analyzes the top 10-20 ranking pages for a keyword and runs **TF-IDF** (term frequency-inverse document frequency) to surface terms that top pages share, then scores your draft 0-100 against benchmarks for word count, heading structure, NLP term coverage, image count, paragraph density, and entity coverage. In 2026 it splits into a separate SEO score and an AI Search score.
Source: https://www.aiocopilot.com/blog/surfer-seo-ai-content-optimization-2026 (fetched 2026-07-20); https://aiflowreview.com/surfer-seo-content-score-review/ (fetched 2026-07-20).

Critical read: the score is a **correlation-with-current-winners** proxy. It tells you where you diverge from the pattern Google currently rewards. That is useful as a floor (do not be conspicuously thin on obvious terms) and dangerous as a ceiling (it pushes every page toward the mean of what already ranks). Vendor-independent reviews concede the content score is "a proxy for keyword coverage, which is one input among many" and does not by itself decide rankings.
Source: https://getspike.ai/blog/clearscope-vs-marketmuse/ (fetched 2026-07-20).

### 1.2 Clearscope

Reverse-engineers the top ~30 search results, extracts a term list, and gives a live letter grade (F to A++) plus a readability grade. Same TF-IDF/term-frequency family as Surfer, positioned as the cleaner, faster in-draft grader.
Source: https://getspike.ai/blog/clearscope-vs-marketmuse/ (fetched 2026-07-20); https://www.eesel.ai/blog/marketmuse-vs-clearscope (fetched 2026-07-20).

### 1.3 MarketMuse

The genuine methodological outlier. MarketMuse builds a **topic model** from your existing content plus competitors' and scores drafts against topical authority and content-gap coverage. It positions itself as "proprietary AI topic modeling rather than traditional TF-IDF or correlation SEO," and its real strength is **planning a content cluster before you write** (inventory analysis, gap-finding), not just grading one page.
Source: https://getspike.ai/blog/clearscope-vs-marketmuse/ (fetched 2026-07-20); https://ustechautomations.com/resources/blog/marketmuse-vs-clearscope-2026 (fetched 2026-07-20).

Takeaway for us: MarketMuse validates that the higher-leverage layer is the **map** (cluster planning, gap analysis), not the single-page term grade. Our `cluster-graph-protocol.md` already reaches for this; it is under-tooled.

### 1.4 Frase

Extracts headings and subheadings from top-ranking pages, pulls questions from Google People Also Ask, Reddit, and Quora, scores the draft live against the ranking corpus, and returns a ranked "what to add next" list. The differentiated primitive here is **question harvesting from real discussion sources**, not just term coverage.
Source: https://www.frase.io/features/seo-content-optimization (fetched 2026-07-20); https://www.aiocopilot.com/blog/frase-ai-content-optimization-seo-2026 (fetched 2026-07-20).

### 1.5 Koala

A "proprietary algorithm" that analyzes top-ranking pages to identify key topics, entities, and semantic keywords associated with the primary keyword, then recommends heading structure and topic organization. Functionally the same SERP-derived term+entity+structure extraction, bundled into an AI writer.
Source: https://koala.sh/features/automatic-seo-optimization (fetched 2026-07-20); https://www.eesel.ai/blog/koala-writer-review-2026 (fetched 2026-07-20).

### 1.6 The replicable method behind "topical completeness"

Every tool above reduces to a four-step pipeline that is fully replicable offline given the page text of the top results:

1. Collect the top N ranking documents for the query (N = 10-30).
2. Build a term/entity/n-gram frequency profile across the corpus (TF-IDF: `IDF(t) = 1 + log(n / (DF(t) + 1))`, `TF-IDF(t,d) = TF(t,d) * IDF(t)`).
3. Extract structure: headings, subheadings, and questions (PAA / Reddit / Quora surfaced as H2/H3 candidates).
4. Score the draft as coverage-of-corpus and emit the ranked missing-terms / missing-questions / missing-subtopics gap list.

The math and the manual corpus method are public and simple. High-TF-IDF terms are also a decent cheap proxy for the salient **entities** of a topic.
Source: https://ipullrank.com/ultimate-guide-to-tf-idf-content-optimization (fetched 2026-07-20); https://www.digitaleer.com/seo-tools/tf-idf-calculator/ (fetched 2026-07-20); https://workspacein.com/tools/tf-idf-calculator (fetched 2026-07-20).

**No-API constraint, honestly stated.** Steps 2-4 are pure offline Python (`scikit-learn` TfidfVectorizer or a hand-rolled counter, both stdlib-adjacent). The only step that needs the outside world is step 1 - obtaining the competitor page text. We do not scrape at write-time and we hold no search API. So the correct design is: the operator (or Claude Code during the SME/brief phase) pastes 5-15 competitor URLs' body text or the SERP People-Also-Ask questions into a corpus file, and the scorer runs fully offline against that pasted corpus. This keeps us API-free and keeps the human in the loop where our real specificity advantage lives. Coverage scoring becomes an **optional brief-time input**, never an auto-fail gate (matching down our G-stack philosophy: coverage is a floor signal, not the reward function).

---

## 2. Information gain: the real moat

### 2.1 What the patent actually says

Google's "Contextual estimation of link information gain" patent (filed 2018, published/granted 2022) defines an information-gain score as a measure of **new, additional information a document contains above and beyond what a searcher has already seen** on that topic across other results. It is computed by comparing a document against the corpus of documents for the topic and can be fed through a machine-learning model. The patent gives the concept, not a step-by-step formula.
Source: https://searchengineland.com/what-is-information-gain-seo-why-it-matters-429763 (fetched 2026-07-20); https://www.semrush.com/blog/information-gain/ (fetched 2026-07-20); https://contadu.com/information-gain-score-what-googles-patent-means-for-your-content-strategy-2/ (fetched 2026-07-20).

Key line worth internalizing: a 1,500-word page with a unique data study, expert analysis, and high information gain will consistently outrank a 4,000-word rehashed listicle that offers zero net-new information, all else equal.
Source: https://searchengineland.com/what-is-information-gain-seo-why-it-matters-429763 (fetched 2026-07-20).

### 2.2 The offline scoring insight (this is the build)

Digitaloft's operator writeup gives the single most important, directly-implementable tactic for a Claude-Code system:

> Generate the LLM-consensus version of the topic, then compare your draft against it and keep only what an LLM "could never come up with" - opinions, first-hand insights, quotes, proprietary data, real specifics. Ensure the unique elements outweigh the consensus portions.

Source: https://digitaloft.co.uk/information-gain-in-seo/ (fetched 2026-07-20).

This is enormous for us: **Claude Code is itself the consensus-generation engine.** We can, fully offline, (1) generate the bland consensus answer for the page's core queries, (2) diff the draft against it, and (3) score the residual - the sentences carrying specifics, numbers, named local facts, first-hand judgment, and claims absent from the consensus. That residual **is** an approximation of information gain. No API, no detector, no evasion - it measures the exact thing Google's patent rewards and the exact thing our G1 specificity gate already demands. It converts our differentiator from a qualitative gate into a **scored, trackable number**.

### 2.3 What concretely adds information gain (the checklist to encode)

From the SearchEngineLand and Digitaloft operator guidance (both fetched 2026-07-20):
- First-party / proprietary data: custom studies, surveys, internal metrics competitors cannot replicate.
- Subject-matter-expert insight and direct quotes (our SME interview already captures this - it is under-exploited).
- Cross-departmental intelligence: sales objection patterns, customer-service inquiry trends, real client pain points.
- Customer voice: reviews, testimonials, real jobs done, named neighborhoods/streets/conditions.
- Named local specifics: permits, codes, climate, seasonal patterns, regional pricing - the local page's natural information-gain surface.
- A meaningful divergence from the AI-generated consensus.
Sources: https://searchengineland.com/what-is-information-gain-seo-why-it-matters-429763 ; https://digitaloft.co.uk/information-gain-in-seo/ ; https://www.ibeamconsulting.com/blog/seo-and-information-gain/ (all fetched 2026-07-20).

Note the near-perfect overlap with local first-hand specificity. For a **local** system this is the highest-ROI content lever in existence, because the local operator literally possesses proprietary facts (this crew, these trucks, these streets, this permit office) that no national competitor and no LLM consensus can hold.

---

## 3. Topical-authority methodology: real vs guru hype

### 3.1 Koray Tugberk Gubur - the usable core

Core formula: **Topical Authority = Topical Coverage + Historical Data.** A site must cover all semantic variations and subtopics of a niche while building a reliability history.
Source: https://opportunityandauthority.com/2025/07/04/koray-tugberk-gubur-seo-through-semantics-topical-authority-opportunity-authority/ (fetched 2026-07-20); https://medium.com/@ktgubur/3-suggestions-about-topical-authority-1cd73963a9cb (fetched 2026-07-20).

Actionable primitives (from the Koray-based semantic glossary, fetched 2026-07-20 at https://rokonz.com/resources/semantic-seo-glossary):
- **Central entity** - the entity appearing in every sub-section of the network (for local: the business + its primary service).
- **Source context** - the site's purpose and monetization model; decides which topics connect logically.
- **Central search intent** - intersection of source context and central entity; appears across the whole map.
- **Topical map** - source context + central entity + central search intent, split into **core sections** (main attributes) and **outer sections** (minor attributes that build trust).
- **Query network** - every word distribution / angle / definition users use for the term.
- **Contextual bridge** - connections between nodes via aligned, consistent information (with or without hyperlinks).
- **Node / attribute** - each document is a node; each entity has attributes with prominence and popularity relative to source context.
- **Macro vs micro semantics** - site-wide signaling (n-grams, headings, question formats) vs word-by-word answer responsiveness.
- **Information responsiveness** - satisfying all query interpretations, not just being topically relevant.
- **Cost of retrieval** - clearer, better-organized semantic structure = cheaper for the engine to process and extract.

Honest verdict: strip the jargon and Koray's method is a rigorous, defensible discipline for **entity-attribute completeness and query-network coverage**. It is the strongest available articulation of "cover the whole topic, not a few keywords." The hype tax is the vocabulary and the implication that mechanical map completeness alone ranks you - it does not without the first-hand value layer. Used as the **planning skeleton** feeding our cluster graph, it is real and worth encoding. The "historical data" half (age, trust, consistent output over time) is not something a content system manufactures; it accrues.

### 3.2 Why this is winnable for local (the good news)

Topical authority is more achievable for a local business than a national one because the topical surface area is narrow: a contractor in Austin must out-cover three metro competitors, not HGTV. That is a winnable game with a focused map of roughly 25-40 pages, filtered through two lenses at once - **topical relevance and local intent** (subject: methods, materials, certifications; market: local codes, climate, incentives). Google treats the business as an **entity with attributes** (name, description, services, industry) and relationships (service categories, locations, client brands); making those explicit in content helps the engine form an accurate picture.
Source: https://topicalmap.ai/blog/auto/topical-map-strategy-for-local-seo-service-pages (fetched 2026-07-20); https://floyi.com/blog/topical-authority-local-seo/ (fetched 2026-07-20).

This maps directly onto our 6 page types. The missing piece is an **entity-attribute coverage matrix** per vertical (roofer, dentist, HVAC...) that says: these are the attributes and sub-topics a complete local entity in this trade must cover across its map. That is a knowledge asset we can build once and reuse per client.

---

## 4. World-class content brief: what the top level contains

Two schools, and the best briefs fuse them:

**SEO-coverage school (Clearscope / Frase / Aleyda Solis).** Target keyword + intent, term/entity coverage targets derived from the SERP, competing pages, headings/questions to answer (PAA, Reddit, Quora), title/meta/H1, word-count band, internal-link targets. Aleyda's optimization worksheets establish the base: primary keywords to rank for, title, meta description, H1s, and the brief itself.
Source: https://www.aleydasolis.com/en/search-engine-optimization/international-seo-keyword-content-optimization-worksheet-free-template/ (fetched 2026-07-20); https://www.frase.io/serp-analyzer (fetched 2026-07-20).

**Point-of-view school (Ryan Law / Animalz).** The brief opens with the **core argument / key insight** - the non-obvious takeaway - before any outline. A mandatory "What We Believe / Our Unique Angle" section forces a POV. Explicit **content-gap analysis**: what competitors say and how this piece fills a gap, corrects a misconception, or takes a contrarian view. Keywords support the argument rather than dictate it.
Source: https://beomniscient.com/blog/ryan-law-content-greatness/ (fetched 2026-07-20); https://www.animalz.co/blog/quality-content (fetched 2026-07-20).

**The synthesis our brief must encode.** A top-0.1% brief for a local page carries both: SERP-derived coverage floor (terms, entities, questions, structure) **and** a mandated information-gain spine (the specific first-hand facts, the local angle, the proof this page holds that the consensus does not). Our `/brief` command exists; the research says it should be upgraded so that no brief is complete without (a) a corpus-derived gap list and (b) a named information-gain thesis per page. The second is the one the SaaS tools never force, and it is the one that wins.

---

## 5. Adversarial read: where the hype misleads

- **Content score is a floor, not a ranking cause.** Chasing a 100 Surfer score pushes toward the SERP mean and can strip the very divergence that earns information gain. Encode coverage as a warning-tier floor, never an auto-fail, and never let it override G1/G3. This is doctrine Law 8 restated: term coverage is a proxy; information gain is closer to the reward.
- **Topical maps do not rank you by themselves.** Mechanical entity-attribute completeness without first-hand value is a thin-content farm at scale. The map is the skeleton; specificity is the muscle.
- **"Historical data" is not buildable by a writer.** Do not sell map completeness as instant authority.
- **Entity extraction via TF-IDF is cheap-and-decent, not semantic truth.** High-TF-IDF terms approximate salient entities; they are not a knowledge graph. Good enough for a gap list, not for claims of "entity optimization."

---

## 6. What we should build (mapped, prioritized, effort-tagged)

Priority order below is by leverage toward #1. Items 1 and 2 are the flagship.

### [Python scripts]

**1. `information_gain_scorer.py` - FLAGSHIP. (Effort: M)**
What: takes the draft plus a Claude-Code-generated consensus baseline for the page's core queries, and scores the residual - the share of sentences/claims carrying net-new value (numbers, named local facts, first-hand judgment, SME quotes, proprietary specifics) absent from the consensus. Emits an information-gain ratio and flags rehash sections. Deterministic parts (specific-fact density, number density, named-entity/local-token density) run in Python; the consensus text is generated by the agent and passed in as a file, keeping it offline and API-free.
Why #1: it scores the exact thing Google's patent rewards and the exact thing our G1 differentiator asserts, converting a qualitative gate into a tracked number. No competitor tool does this; the SaaS optimizers structurally cannot.
Evidence: https://digitaloft.co.uk/information-gain-in-seo/ ; https://searchengineland.com/what-is-information-gain-seo-why-it-matters-429763 (both 2026-07-20).

**2. `coverage_scorer.py` - offline Surfer/Clearscope approximation. (Effort: M)**
What: given a pasted corpus of competitor body text (5-15 docs) in a client corpus file, compute TF-IDF term/entity/n-gram profile, extract heading and question candidates, then score the draft's coverage and emit a ranked missing-terms / missing-questions / missing-subtopics gap list. Pure offline Python; corpus is human-supplied at brief time (no scraping, no API).
Why: matches the commercial optimizers' core function as a brief-time floor signal, so we never ship conspicuously thin on obvious terms - without importing their push-to-the-mean failure mode (it feeds the brief, it is not an auto-fail gate).
Evidence: https://ipullrank.com/ultimate-guide-to-tf-idf-content-optimization ; https://www.digitaleer.com/seo-tools/tf-idf-calculator/ ; https://www.frase.io/features/seo-content-optimization (all 2026-07-20).

**3. `entity_attribute_matrix.py` - local entity-coverage checker. (Effort: S)**
What: loads a per-vertical entity-attribute reference (see MD asset below) and checks whether a client's page set / map covers the required attributes and sub-topics for that trade + market. Emits the coverage matrix and the specific missing nodes.
Why: operationalizes Koray's entity-attribute completeness and the local-topical-map thesis into a checkable artifact; feeds cluster planning.
Evidence: https://rokonz.com/resources/semantic-seo-glossary ; https://topicalmap.ai/blog/auto/topical-map-strategy-for-local-seo-service-pages (both 2026-07-20).

### [Skills]

**4. `content-completeness` skill. (Effort: S)**
What: a `.claude/skills/` skill (the folder is currently empty) that orchestrates scripts 1+2+3 at brief and QA time and interprets their output into concrete "add this" instructions, keeping coverage subordinate to information gain per Law 8.
Why: turns three scripts into one routed capability the writer/QA agents invoke without the operator remembering each script. The skills folder being empty is a gap; this is the first inhabitant.
Evidence: system inventory (skills folder empty, 2026-07-20 local read).

### [Agents]

**5. `information-gain-auditor` agent (or fold into `critical-editor`). (Effort: S)**
What: runs the consensus-diff, names the rehashed sections, and demands the specific first-hand fact each thin section is missing - routing back to the SME interview when the source material is genuinely thin (never inventing, per G10).
Why: makes information gain an enforced editorial pass, not a hope. Reuses the existing critical-editor pattern.
Evidence: https://digitaloft.co.uk/information-gain-in-seo/ (2026-07-20); local `.claude/agents/critical-editor.md`.

### [MD knowledge files]

**6. `knowledge/foundations/information-gain-protocol.md`. (Effort: S)**
The patent, the consensus-diff method, the "what adds gain" checklist, and how it scores. Cited to the SearchEngineLand/Digitaloft/Semrush sources above.

**7. `knowledge/foundations/topical-completeness-and-coverage.md`. (Effort: M)**
How the commercial optimizers score (Surfer/Clearscope/MarketMuse/Frase/Koala), the replicable TF-IDF pipeline, the honest floor-not-ceiling framing, and how our offline scorers approximate it.

**8. `knowledge/foundations/local-entity-attribute-matrices.md` (+ per-vertical data). (Effort: L)**
The reusable house asset: for each target trade, the entity attributes and sub-topics a complete local entity must cover across its map. This is the MarketMuse-grade planning layer, built once, reused per client. Highest long-run leverage of the MD items.
Evidence: https://floyi.com/blog/topical-authority-local-seo/ ; https://topicalmap.ai/blog/auto/topical-map-strategy-for-local-seo-service-pages (both 2026-07-20).

**9. Upgrade `knowledge/foundations/keyword-research-method.md` and the `cluster-graph-protocol.md`** with Koray's query-network and central-entity/central-search-intent primitives as the map-planning skeleton. (Effort: M)
Evidence: https://rokonz.com/resources/semantic-seo-glossary (2026-07-20).

### [Laws to add to doctrine]

**10. Proposed Law 15 (or Part I principle): Information gain over coverage. (Effort: S)**
"A page earns its rank by what it adds beyond the SERP consensus, not by how completely it matches it. Coverage scoring is a floor and a warning; information gain is the tracked reward. Never let a term-coverage target strip a first-hand specific." This is a direct, provable extension of Law 8 (optimize the reward function, not proxies) and Hard Line 5 (no detector-evasion), grounded in the information-gain patent rather than guru opinion.
Evidence: https://searchengineland.com/what-is-information-gain-seo-why-it-matters-429763 (2026-07-20); doctrine Law 8 / Hard Line 5 (local read).

### [Frameworks]

**11. The two-sided brief upgrade for `/brief`. (Effort: M)**
Every brief carries (a) SERP-derived coverage floor (terms, entities, questions, structure from coverage_scorer) AND (b) a mandated **information-gain thesis** - the named first-hand facts, local angle, and proof this page holds that the consensus lacks (Animalz "What We Believe" adapted to local). No brief is complete without both halves.
Evidence: https://beomniscient.com/blog/ryan-law-content-greatness/ ; https://www.aleydasolis.com/en/search-engine-optimization/international-seo-keyword-content-optimization-worksheet-free-template/ ; https://www.animalz.co/blog/quality-content (all 2026-07-20).

**12. Consensus-diff writing loop. (Effort: S)**
Formalize as method: generate consensus, write, diff, keep-the-divergence. Encoded in the information-gain protocol and run by the auditor agent.
Evidence: https://digitaloft.co.uk/information-gain-in-seo/ (2026-07-20).

### [Examples]

**13. One worked information-gain teardown per page type. (Effort: M)**
A rehash draft vs a high-gain rewrite for a location page and a service page, with the scorer output shown, so the standard is concrete not abstract. Follows the doctrine's per-artifact-depth bar.

### [Quality gates]

**14. Add a warning-tier coverage gate and elevate information gain inside G1/G3. (Effort: S)**
Coverage becomes a logged warning (never auto-fail); information-gain ratio becomes a scored sub-check of the existing G1 specificity gate. Keeps the gate stack honest to Law 8.

---

## 7. Bottom line

The commercial tools sell coverage; coverage is table stakes and a mean-reversion trap. The defensible, patent-aligned, offline-buildable moat is **information gain**, and a local content system built on real first-hand specifics is the one system type that can score and win it. Build the information-gain scorer first, the offline coverage approximation second, and the reusable local entity-attribute matrices third. Everything else is knowledge and enforcement scaffolding around those three.
