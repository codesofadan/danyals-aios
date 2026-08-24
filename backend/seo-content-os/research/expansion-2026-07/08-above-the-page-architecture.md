# Above-the-Page Architecture: Topical Map, Client Profile, and the Full Scenario Set

Research territory: the pre-writing planning layer (topical map + client/entity profile) and the operator scenarios beyond writing one page (greenfield build, audit, improve, migrate). This is the Wave 3 blueprint: the one layer every prior wave deferred.

Method: a scaled expert panel. Six web-grounded research territories (Koray/topical-map methodology, local-SEO ranking reality, content briefs/process, entity-IR + data model, the operator use-case set, content audit/improve) + one live system-inventory pass, then two independent adversarial verifiers (source integrity, architecture naivety), then this synthesis. All external URLs fetched 2026-07-21/22 PKT. Every load-bearing claim traces to a source a researcher actually read this session; unverified claims are marked as such. Law 8 binding throughout (no detector-evasion; optimize the reward function, not a proxy).

Provenance discipline: this file separates what was verified against a primary source, what is practitioner-heuristic, and what could not be verified. Read the "Open uncertainties" section before treating any number here as settled.

---

## 0. The one-paragraph call

The system is mature below the page (11 playbooks, 19 offline scripts, the full G0-G13 gate stack, the lifecycle loop, measurement) and absent above it. There is no artifact that plans a client's whole content footprint before writing, no entry path for a greenfield build, an existing-site audit, or a structural gap-driven improvement, and `brand.yaml` is a per-page fact sheet rather than a site-level source of truth. The fix is not a new page-writer; it is a planning layer that sits on top of the existing one. The keystone of that layer is a **topical map**: a persisted, per-client artifact that selects which pages should exist, classifies each as core (converts) or outer (builds trust), and gates each node's promotion from a coverage-index line to a full page on real first-party evidence. Critically, the map is a **demand-and-evidence-filtered subset**, not the full service-by-city grid; the grid is demoted from the thing that generates the site to the ceiling the map filters down from. Everything else in this blueprint (greenfield, audit, improve, migrate) consumes that map plus an extended profile as its primary input.

**Strongest case against this build (stated honestly):** the system already writes excellent pages and its keyword-research method is already demand-grounded, so a new above-page layer risks over-engineering and the exact doorway-farm-at-scale failure mode it is meant to prevent; and Koray himself says no tool can measure topical authority, so an entity-attribute "coverage score" would be a category error. The internal audit (file 07) argues the highest-value remaining work is finishing per-vertical examples and gate enforcement, not a new layer. The rebuttal: the gap is real and specific (nothing runs the map once at site level; there is no greenfield/audit/improve entry; the profile is not a site source of truth), and the design below is shaped specifically to avoid those failure modes (grid demoted to a filtered ceiling, node default is an index line not a page, and no topical-authority scoring tool is built). Both can be true: build this layer, and finish examples/enforcement in parallel.

---

## 1. The verified use-case set (8 scenarios, with build-state)

Grounded in how operators actually structure engagements (Growth Rocket agency playbook; Animalz content-audit; Fact&Form / Contentoo audit-vs-strategy split; GoInflow consolidation case; Backlinko/SEJ multi-location; Clustermagic/Stackmatix cadence). The panel converged on eight top-level scenarios. Verifier and inventory then corrected what is actually missing.

| # | Scenario | Operator goal | Starts from | Build-state today |
|---|---|---|---|---|
| A | Onboarding / discovery | Build the operating profile before any content | Intake, GBP, citations, existing site | **Partial** - `/new-client` + `sme-interviewer` build `brand.yaml`; missing the entity/topical half |
| B | Write one page | Rank + convert one target query | Profile + one page-type + query | **Built** - 11 write commands, full pipeline |
| C | Greenfield full-site build | Stand up a whole content footprint | Profile + market/service list | **Gap** - no map, no page inventory, no batch orchestrator |
| D | Audit existing content | Diagnose what exists, produce a decision doc | Live site, GSC/GA, crawl | **Gap** - `/qa` audits one draft; `decay_monitor` audits performance, not coverage |
| E | Refresh / decay | Recover one declining ranking page | A decay signal on a known URL | **Built** - `/refresh` + `decay_monitor.py` + protocol |
| F | Improve / optimize footprint | Fix structural + gap-driven weakness across many pages | Audit findings, competitor gap | **Gap** - only per-page decay refresh exists |
| G | Migration / consolidation | Merge/retire overlapping or cannibalizing URLs | Audit-flagged duplicates, or a domain move | **Gap** - no redirect-map tooling |
| H | Ongoing production cadence | Compound authority over time | Existing map + cluster roadmap | **Partial** - per-page loop exists; no map-level coverage loop |

Distinctness verdict (verified): B (write one page) is the atomic **leaf** every other scenario bottoms out into, not itself an engagement type. Competitor-gap expansion and net-new cluster launch are **inputs to H**, not separate pipelines (every source shows them terminating in ordinary page production). E vs F is analytically real (E = decay-triggered, single URL, in place; F = gap-triggered, multi-page, structural) but is **not universally named** as two SOPs by small agencies - so build them as two modes that can share machinery, not two heavy separate products. Audit (D) is sometimes standalone, sometimes nested in onboarding - so it must be callable standalone.

**The real remaining scenario work is C, D, F, G, and the map-level piece of H.** None is usefully buildable until the map + profile layer (below) lands, because all four consume it as primary input. This corrects the founder's framing that "everything above the page" is one undifferentiated gap: two of the eight scenarios (B, E) are done and one (A) is half done.

---

## 2. The core architectural decision: the map is a filtered subset, not the grid

This is the single most consequential decision in the build, and it resolves a genuine tension the panel surfaced.

**The tension (verified as real, not a misunderstanding).** The local-reality territory and the existing system both treat the service-by-city combo page as "the money page," and `keyword-research-method.md` §3 literally builds "the grid" by crossing every service against every modifier against every city. Koray's method says local scaling should be organized by **user clusters** (behavioral similarity), with **fewer** pages as a win condition, and calls naive grid-stamping a doorway risk. Verifier 1 confirmed this is reconcilable on one axis and not on another:

- **Reconcilable on doorway risk.** Google's actual doorway-abuse policy (fetched verbatim from Search Central) condemns only pages that are "substantially similar" and funnel to one real destination, not city pages per se. A grid of genuinely unique, evidence-selected city pages is defensible, and `duplication_gate.py` (G3, Jaccard >= 0.70 fail) plus the 60-70%-unique-per-page bar already enforce that floor.
- **Not reconcilable on "is the full grid the right base unit."** Koray's claim is stronger than "make each page unique"; it says the base unit of local scaling should not be the full Cartesian product at all. The system has only one architecture (grid + per-page uniqueness gate).

**The resolution.** Demote the grid. The full service-by-city product becomes the **candidate ceiling**, and the topical map is the **demand-and-evidence-filtered subset** that survives. This is not a new claim bolted on; it is the node-selection responsibility that `cluster-graph-protocol.md` **explicitly disclaims** (lines 181-185: "Which cities and services are worth a node at all... is a keyword-and-demand question, owned by `keyword-research-method.md`... The graph organizes the nodes that research says should exist; it does not choose them"). So:

- The topical map **owns node selection.** It replaces the selection logic currently implicit in `keyword-research-method.md` §3's grid.
- `cluster-graph-protocol.md` is unchanged in topology. It receives the surviving node list and wires the hub-and-spoke graph. No conflict; a clean seam that already exists.
- `keyword-research-method.md` is **demoted in scope**: from "the method that decides which nodes exist" to "one input channel that supplies candidate keyword variants for a node the map has already justified." Without this edit, the two files silently disagree about node selection and whichever agent runs first wins by accident.

Note the important nuance verifier 2 caught: the existing keyword method is **already demand-disciplined** ("if nobody suggests it and no SERP exists, it is not demand"; "a city the business does not serve does not get a row"). So the grid it builds is not a naive stamp. What it lacks is (a) the entity/attribute and core-outer layer that makes it a *topical* map rather than a *keyword* map, (b) a persisted artifact, (c) an owner that runs it once at site level, and (d) an explicit user-cluster merge step so behaviorally-identical geographies collapse instead of each spawning a page.

**Robustness check.** The demotion conclusion does **not** depend on Koray's unverified "millions to under 100k pages" case study (verifier 1 could not find it after four searches; likely paywalled course content). It stands independently on verified ground: Sterling Sky's evidence-driven location selection ("don't create pages for areas you do not serve"; smaller cities often outperform metros) and Google's own doorway policy. Build the conclusion on those; cite the Koray case study only as directional.

---

## 3. The pre-writing infrastructure (item one)

### 3.1 The topical map

**What it is.** A persisted, per-client artifact (`clients/<slug>/topical-map.md` or `.yaml`) that is the site-level source of truth for which pages should exist, in what priority, wired to what. It supersedes and absorbs the on-paper keyword-map spec in `keyword-research-method.md` §0.

**Construction discipline (the non-negotiable rule).** The map is built from **real discovery**, never from model pattern-completion. Koray's own disclaimer, verified: "Do not believe auto-generated topical maps... asking ChatGPT for 20 types of X won't give you a topical map." The existing keyword method already models the right discipline (eight real discovery channels, live SERP as tiebreaker). The map construction inherits that exact discipline as an explicit, named rule: **an agent may not propose a node from memory; every node traces to a live demand signal (autocomplete, PAA, related search, a competitor page that ranks, GBP categories/services) or a real client capability in `brand.yaml`.** This is the same trap the system already avoids for facts (G1/G10) and must now avoid for the map.

**The primitives (Koray's usable core, hype stripped).**
- **Central entity + source context + central search intent.** Source context = what the business is and how it monetizes; central entity = the one thing appearing in every section (for local: the business + its primary GBP-category service); central search intent falls out of the first two, it is not chosen freely. These are the map's root and they come straight from the extended profile (3.2).
- **Core vs outer is a monetization split, not a topic split** (verified, holisticseo.digital). Core nodes sit near monetization and convert (the money pages); outer nodes build the historical-data/trust that lets core nodes rank. Internal links flow outer-to-core more than the reverse.
- **EAV (entity-attribute-value) is the atomic node unit.** A node covers one entity-attribute pair; this is what makes coverage countable. Attribute priority is unique > root > rare (a genuinely unique attribute justifies its own page; a rare one folds into an existing page as a section).
- **User-cluster merge (the local adaptation).** Before the grid is finalized, geographies with overlapping searcher behavior collapse into one node rather than each spawning a page. This is the mechanism that turns the ceiling into a smaller, real map.

**How the map drives everything downstream.**
- **Page inventory** = the surviving node list. One page per node that clears the demand filter and the evidence gate; attributes without demand fold into an existing node as a section.
- **Publishing order** = core nodes first (they carry monetization and receive link priority), then outer nodes to build trust around them. Within core, sequence by the existing Win-now / Winnable-with-depth / Hard-defer read from `keyword-research-method.md` §5 and Aleyda's Impact-vs-Difficulty prioritization.
- **Internal-link graph** = handed to `cluster-graph-protocol.md` unchanged; contextual bridges are links justified by a shared attribute, not link-for-link's-sake.

**The anti-doorway design at the map level (the biggest new risk).** Once a persisted map enumerates N nodes, there is gravity to treat "ship all N" as success - which is the scaled-content-abuse dynamic applied for the first time at a level with no gate watching it. The design fix, mirroring the existing service-area "booked-jobs test + local-proof test":
- Every node's **default state is a low-commitment coverage-index line**, not a page.
- Promotion to a full page is an **explicit, evidence-gated step** keyed to real fields in `brand.yaml` / SME answers (a real local price band, a permit/code fact, a job done there, a condition specific to that place). No evidence, no promotion; the node stays an index line or routes to the service-area page.
- Never the reverse (propose the full grid, hope the write-time gate saves you).

### 3.2 The client / entity profile (extend, do not rebuild)

`brand.yaml` already carries identity, NAP+geo, schema subtype/hours/sameAs, services, service_areas, rich E-E-A-T arrays (credentials/team/proof/media/reviews + per-vertical credential arrays), vertical routing, a 6-field voice block, guardrails, and a compounding case_log. Verifier 2 confirmed this is a genuine per-page fact sheet and should be extended, not replaced. The precise additions, ordered by leverage:

1. **An `entity` block** - the disambiguation layer Google actually keys on and the map's root: `central_entity`, `source_context` (what it is + how it monetizes), `canonical_description` (one to two factual sentences, not ad copy), `same_as` as a relationship registry (kept in sync with the schema block's emission list), optional `kgmid` / `parent_org` / `memberships`.
2. **A `competitive_set`** - the real local competitors, each with `url`, `strength` (what they genuinely do well, not strawmanned), and `gap_we_fill` (the specific fact/depth they lack). This drives information-gain decisions and is entirely absent today (only `banned_competitor_mentions` exists).
3. **Lighter enrichments** - `people[]` as sub-entities (mostly already present in `eeat.team`; add author/reviewer credit and a `worksFor_verified` flag) and a `dated_results[]` array split out from the looser `eeat.proof[]` to feed Law 19.

That is an additive change to `/new-client` and the template, not a rebuild.

### 3.3 The research and planning between profile and map

Largely already present and strong; the gap is that it runs per-page, not once at site level. Reuse:
- **Keyword + intent clustering** from `keyword-research-method.md` (SERP-overlap clustering; the six local intent classes; the live-SERP tiebreaker). Elevate it to run once, at site level, writing the persisted map.
- **The brief synthesis** (from the briefs territory): coverage floor + POV/information-gain thesis. Every node's eventual brief carries both a SERP-consensus shape (the floor) and a one-sentence thesis line naming the first-hand fact this page adds beyond consensus (the ceiling). Coverage-only briefs produce copycat content; POV-only briefs rank for nothing. The map records the thesis line per node so it is decided at plan time, not rediscovered per page.
- **Opportunity prioritization**: Aleyda's Impact-vs-Difficulty, layered with the Quality-Cliff test (invest heavy POV only where the topic's quality bar is high).

---

## 4. Audit + improve (scenarios D and F)

**The reuse insight (verified):** gap detection = the topical map's should-exist set minus the live-and-adequate pages (MarketMuse framing). The map supplies what should exist; the profile supplies the quality bar (what counts as "thin" or "generic" for this specific business, set by its real facts and proof inventory). So audit and improve are not new infrastructure; they are the map + profile pointed at an existing site.

**What to measure per page** (synthesized, all practitioner-sourced): GSC impressions/clicks/position/CTR; organic sessions (12-month window) and total pageviews across channels; how many other site URLs also rank for the same query (the cannibalization signal); conversions judged against the page's *intended* job; referring domains; word depth / last-updated / duplicate title-meta-H1 overlap; index status.

**Detection methods:** thin (low words relative to the intent's real requirement, "a clue not a verdict," plus Google's people-first questions as the qualitative override); doorway/near-duplicate (content-similarity + same query intent + funnel behavior); cannibalization (multiple URLs ranking top-100 for one query, or tracked-keyword URL-switching); gap (map minus live-and-adequate); decay (traffic trend over a rolling 12-month window, after isolating seasonality and index causes; min content age ~3-6 months before judging).

**The decision framework (multi-metric AND-logic, not a single threshold):** keep / improve / consolidate(merge, 301 the losers) / prune(delete or noindex) / redirect. Prune only when low on *every* axis at once (traffic AND pageviews AND conversions AND backlinks); redirect if it holds backlinks; noindex if it must stay live for non-search reasons. Stage removals in batches with a 1-3 week monitoring gap.

**The improve playbook:** close the information-gain gap vs current top pages; close coverage gaps the query demands (new subtopics from PAA, not padding); freshness with a real delta (never a bumped timestamp - this is the system's own Law 19, independently corroborated); add internal links from high-authority pages; re-match intent if it has drifted.

---

## 5. The four traps (what NOT to build)

Each of these is a way the build could quietly betray its own doctrine. All four were flagged by the verifiers.

1. **Do not auto-generate the map with the LLM.** The map must come from real discovery channels, not model pattern-completion. Koray says this explicitly and the system already enforces the equivalent for facts. Named rule in the protocol.
2. **Do not score topical authority with a script.** Do not revive the proposed `entity_attribute_matrix.py` as a coverage-percentage or completeness-percentage *gate*. Koray: no tool can measure topical authority. The entity-attribute matrix may exist only as a **planning reference** (a per-vertical checklist of candidate attributes to research demand for), never as a pass/fail number. The system already has one over-mechanization instance (see trap 3); do not add a second at the map altitude.
3. **Do not treat the information-gain patent as ranking law.** Verifier 1 fetched the patent (US11354342B2): it is a document-**sequence** redundancy scorer for dialogue/assistant sessions, and Google has never confirmed core-ranking use. The system's own `local-content-laws.md` Law 15 and the `information_gain_scorer.py` docstring currently assert the stronger claim as settled fact. This needs correction (Section 7). The firmer basis for "cover the topic completely" is Google's helpful-content self-assessment, which is documented.
4. **Do not propose the full grid and hope the write-time gate saves you.** Node default is an index line; promotion is evidence-gated. The map's own existence is the new doorway-farm risk, and no per-page gate watches the map.

---

## 6. Build roadmap

Sequenced by dependency, per verifier 2. Item one is steps 1-3.

**Item one - the pre-writing layer (build now):**
1. **Resolve node-selection in doctrine.** New `knowledge/foundations/topical-map-protocol.md`: the construction methodology, the primitives, the grid demotion, the real-discovery rule, the core/outer split, the EAV node unit, the user-cluster merge, and the node-default-is-an-index-line anti-doorway design. Demote `keyword-research-method.md` §3 with an explicit pointer.
2. **Extend the profile.** Additive edit to `clients/_template/brand.yaml` and `/new-client`: the `entity` block and `competitive_set` (and lighter people/dated_results enrichments).
3. **Give the map an owner and an artifact.** New `templates/topical-map.md` (the persisted per-client artifact schema), new `/build-topical-map` command, new `topical-map-architect` agent that runs the method once per client and writes the artifact. Add a map-node reference field to `templates/content-brief.md` so every write ties to a map node.

**Item two onward (after item one, in order):**
4. **Greenfield build (C):** `/build-site-plan` (or fold into the map command) producing the prioritized page inventory, then a batch orchestrator that runs the write pipeline per node in publish order. Ensure the persistent link graph is maintained across the batch (see the honest wiring note in Section 8).
5. **Audit (D):** `/audit-content` - inventory a live site (operator-supplied crawl/URL list + GSC CSV, no scraping API), score each page against the map (gap) and the profile (quality bar), emit the keep/improve/consolidate/prune/redirect decision doc. New `content_audit.py` for the deterministic detections (cannibalization from rank data, thin from word depth, near-duplicate from the existing shingle logic in `duplication_gate.py`).
6. **Improve (F):** `/improve-content` - consume the audit's decision doc, drive the multi-page improvement in priority order, reusing the write pipeline and `/refresh` machinery.
7. **Migrate/consolidate (G):** `/consolidate-content` - the merge + 301 redirect-map workflow, the one scenario with genuinely unique tooling (URL-level redirect mapping).
8. **Map-level cadence (H):** extend measurement with a map-coverage loop (of the N nodes the map says should exist, how many are live / passing gates / ranking) - the one measurement signal absent today.

---

## 7. Doctrine corrections surfaced (propose, do not silently change)

These change shipped doctrine, so they are proposals for the founder's go, not unilateral edits.

1. **Law 15 (information gain) overstates the patent.** `knowledge/doctrine/local-content-laws.md` and the `information_gain_scorer.py` docstring assert the patent "rewards what a page adds beyond the SERP consensus" as fact. Proposed reword: state the patent as "inspired by, not confirmed as, a Google production ranking mechanism (US11354342B2 scores document-sequence redundancy in assistant sessions; Google has not confirmed core-ranking use)," and cite Google's helpful-content self-assessment as the primary justification, with the patent as directional support only. The scorer stays useful as an internal divergence check; only its stated justification changes. Keep it a warning-tier signal, not the sole reward (which Law 15's own text already says).
2. **`keyword-research-method.md` scope demotion** (Section 2). Add a pointer at §0 and §3 that node selection is now owned by `topical-map-protocol.md`, and this method supplies candidate keyword variants for justified nodes. Non-breaking; a scope clarification.

---

## 8. What survived verification, and open uncertainties

Confirmed against primary sources this session: GBP posts move rankings zero and the GBP Services field does move rankings (Sterling Sky, direct); schema markup does not rank (Mueller, on record); Google's doorway-abuse and scaled-content-abuse definitions (Search Central, verbatim); Koray's auto-generated-map and no-tool-measures-TA disclaimers (his Medium post); topical-authority-is-necessary-not-sufficient (Jason Barnard via Search Engine Land, correctly attributed as independent, not Koray); the information-gain patent's true narrow scope (US11354342B2, direct).

Open uncertainties (do not build as if these are settled):
- **Koray's "millions to under 100k pages via user-clusters" local case study is unverified** (four searches, no URL; likely paywalled). The grid-demotion decision does not depend on it - it stands on Sterling Sky + Google's doorway policy - so treat the case study as directional only.
- **The "~25-40 pages" local-map size is the system's own assumption**, not found in any source. Do not encode it as a target; let real demand + evidence determine map size.
- **Ranking-factor weights** (GBP 32% / reviews 20% / on-page 19% etc.) are practitioner-survey synthesis (BrightLocal of the gated Whitespark LSRF), directional, not Google-confirmed. The "NAP 40% more likely" figure and any "% of location pages that rank" ratio are unverified; do not cite as fact.
- **Numeric audit thresholds** (20% YoY decay, <300-500 words thin, <100 clicks/6mo review) are practitioner heuristics, not Google policy. Encode as configurable defaults, clearly labeled.
- **Wiring notes (verified against the command files, correcting SYSTEM-MAP.md):** `conversion-optimizer` **is** wired into the write commands (G13, confirmed in `write-service-city-page.md`) - the "orphaned" claim was stale. `link-architect` (the persistent `link_graph.json` owner) is **not** explicitly invoked by the write commands; per-page internal links are handled by `schema-linking-finisher` writing `internal-links.md`. For a greenfield batch build (scenario C) this matters: the persistent graph must be maintained across the batch, or money pages can ship without their up-links registered in the graph. Resolve during the C build.

---

## 9. Key sources (fetched 2026-07-21/22 PKT)

- Koray / topical authority (primary): https://www.holisticseo.digital/theoretical-seo/topical-authority/ ; https://www.holisticseo.digital/seo-research-study/topical-map ; https://www.holisticseo.digital/seo-research-study/entity-attribute-value ; disclaimer: https://medium.com/@ktgubur/3-suggestions-about-topical-authority-1cd73963a9cb
- Topical authority not sufficient (independent): https://searchengineland.com/why-topical-authority-isnt-enough-for-ai-search-474250
- Local reality (Sterling Sky): https://www.sterlingsky.ca/do-google-posts-impact-ranking/ ; https://www.sterlingsky.ca/services-in-google-business-profile-impact-ranking/ ; https://www.sterlingsky.ca/how-to-create-unique-and-helpful-service-area-pages-for-local-businesses/ ; https://www.sterlingsky.ca/pick-locations-for-service-area-pages/
- Local weights (secondary synthesis): https://www.brightlocal.com/learn/google-local-algorithm-and-ranking-factors/ ; Whitespark: https://whitespark.ca/blog/7-local-search-ranking-factors-that-may-challenge-your-current-thinking/
- Briefs/process: https://ahrefs.com/blog/content-briefs ; https://www.clearscope.io/blog/SEO-content-brief ; https://www.animalz.co/blog/information-gain ; https://www.animalz.co/blog/the-quality-cliff ; https://www.aleydasolis.com/en/search-engine-optimization/how-to-winning-seo-website-audit-growth/
- Entity/IR + Google docs: https://developers.google.com/search/docs/appearance/structured-data/local-business ; https://developers.google.com/search/docs/fundamentals/creating-helpful-content ; https://developers.google.com/search/blog/2022/12/google-raters-guidelines-e-e-a-t ; Mueller schema: https://www.searchenginejournal.com/google-confirms-that-structured-data-wont-make-a-site-rank-better/544433/ ; patent: https://patents.google.com/patent/US11354342B2/en
- Use-case set: https://www.growth-rocket.com/blog/the-agency-playbook-for-sustainable-local-seo-operations/ ; https://www.animalz.co/blog/content-audit ; https://factandform.com/seo-audit-vs-content-audit-differences/ ; https://backlinko.com/multi-location-seo
- Audit/improve: https://developers.google.com/search/docs/essentials/spam-policies ; https://www.goinflow.com/blog/content-pruning-case-study/ ; https://ahrefs.com/blog/content-decay/ ; https://www.mediapost.com/publications/article/388152/google-warns-against-content-pruning-as-cnet-del.html ; https://blog.marketmuse.com/content-gap-analysis-the-marketmuse-guide/

Evidence-class reminder: Sterling Sky controlled tests are the strongest class; Whitespark/Local SEO Guide are correlation + expert survey; BrightLocal is consumer survey; Koray primary pages are method exposition; agency posts are best-practice consensus. Weights and thresholds are directional until primary tables are re-pulled.
