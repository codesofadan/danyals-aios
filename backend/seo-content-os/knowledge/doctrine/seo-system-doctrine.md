# SEO System Doctrine - Global Build Standard

v1.1 - 2026-07-17 PKT. Portable: copy this file into any Xegents SEO workspace (or @-import it from that workspace's CLAUDE.md). It governs how every SEO system is built, improved, and modified. It is self-contained; no other file is required to apply it. Companion: `seo-system-spine.md` holds the canonical data contracts (Law 14) that let multiple systems share one brain - pull it in when building interop, not required for a single system.

Origin: distilled from the adversarial teardown of a competitor's claimed "superbrain" system (Actual SEO Media, Houston, July 2026), 7 territories of primary-source research, 10 independently verified claims, and our own build history across SEO-AUDIT-OS, MARKETING-OS, and BLOG-OS. Full evidence: `D:\AIOS\data\research\jamin-system-teardown-2026-07-17.md`.

Authority order: founder > this doctrine > local workspace convenience. When a local pattern conflicts with a law here, surface the conflict; do not silently follow either.

---

## Part I - Mindset

These are the thinking rules. Every architecture law in Part II is downstream of these.

**1. Puffery is market research.**
When an operator brags about capabilities that fail physics, do not dismiss the claim - decode it. A false claim that closes deals is a purchase order from the market: it tells you exactly what buyers want to be true. "8,000 pages audited in 3 minutes" is a lie about crawling and a truth about demand for instant re-audits. Extract the demand signal, discard the fabrication, and engineer the version that is true. Every competitor's exaggeration is a free product spec.

**2. Build the claim a technical buyer cannot break.**
The engineering target for any capability is the strongest sentence about it that survives hostile scrutiny. "First full crawl under 30 minutes, every re-audit under 3" beats "any site in 3 minutes" because it closes the same deal and cannot be dismantled on a call. Before building, write the sales sentence; then build until the sentence is literally true; then stop. This converts marketing honesty from a constraint into a design method.

**3. Physics first, always.**
Before building or claiming anything, run it against the three hard budgets: crawl physics (pages/second against real WAFs and politeness norms), token economics ($/1M at current official prices), and API pricing (what the data actually costs). Any design or claim that fails these budgets is dead regardless of how good it sounds. This is also the fastest way to evaluate anyone else's system: their numbers either survive arithmetic or they do not.

**4. Direction from anyone, specifications from no one.**
Take ambition, framing, and feature direction from competitors, braggarts, papers, and products. Never take implementation specs from them. The competitor who inspired this doctrine pointed at real things (structural audits, execution, guardrails, cost routing) while his implementations of them were naive or fake. Steal the pointing finger, re-derive the build from primary sources and our own physics.

**5. The gap between demo and production is where trust lives.**
Anyone can demo. The questions that separate real systems: does it run on sites you do not control, does it survive cancellation, does it measure its own impact, can it roll back, what happens when it is wrong. Build for those questions. Ask those questions of everyone else.

**6. Limitless does not mean reckless.**
Think without a ceiling on capability; think with a hard floor on safety. The ambition is a system that runs an agency's delivery end to end. The floor is that no change ships unmeasured, ungated, or unrecoverable. Both at once, always. The operator who retrofits guardrails after breaking client sites has told you his engineering culture; ours ships the guardrail in the same commit as the capability.

---

## Part II - Architecture laws

Fourteen laws. Each has a test. When building or modifying any SEO system, every law either HOLDS, PARTIALLY HOLDS, or IS VIOLATED for that system - there is no not-applicable.

### Law 1 - The loop is the product; the report is the funnel.
Audits are commoditized: free open source (claude-seo, 11.6k stars) and $99-599/mo SaaS produce credible audits. Never spend differentiation budget on audit depth. The sellable product is the closed loop: detect -> decide -> execute -> verify -> report impact -> re-detect. Any system whose terminal output is a document is an unfinished system.
**Test:** trace the system's main flow. If it ends at a PDF/markdown deliverable with no executable path, VIOLATED.

### Law 2 - Write access is the product boundary.
A system's real power equals the write surfaces it controls: WP REST/WP-CLI, git PRs, redirect managers, CMS APIs, DNS, CDN. Everything else is commentary. Design capabilities around owned, persistent, server-side changes that live in the client's infrastructure and survive the engagement ending. Never a rented JS overlay (the incumbent SaaS model: changes invisible to AI crawlers, 5-10% breakage, vanish on cancellation).
**Test:** for each fix class the system recommends, name the write surface that applies it. No surface = commentary, not capability.

### Law 3 - Decouple collection from analysis; the cache is the speed.
Crawl once into a persistent per-client store (raw HTML, extracted text, link graph, API pulls, keyed by URL hash, incremental via ETag/If-Modified-Since). Analyze and re-report from the store. Fresh full crawls are polite and slow; regeneration is instant. This is how the demo feels magical without lying, and how the marginal cost of the tenth deliverable approaches zero.
**Test:** re-running any report twice must not re-fetch unchanged pages. If it does, VIOLATED.

### Law 4 - Judgment is versioned code.
The durable moat is codified decision logic: per-issue-class rule catalogs (orphan page: kill / fill / merge / rewrite / link / restructure) as transparent, git-diffable YAML or markdown, with LLM judgment invoked only at semantic leaves ("do these two pages target the same intent?"). Every decision emits a rationale a human reads in ten seconds: action, target, evidence, confidence, risk tier. An honest 300-500 auditable rules beats a claimed 1,500 invisible ones, in engineering and in sales demos. Per-client rule overlays make the system non-transferable to a competitor - sell that explicitly: "your judgment, encoded, owned by you."
**Test:** pick any automated decision and ask "why?"; the system must answer from its rule catalog with evidence, not from a model's vibes.

### Law 5 - Guardrails ship before capabilities.
Hard-coded risk tiers, never LLM-reclassified: Tier A auto-apply after dry-run diff (metas, schema, alts, canonicals, added internal links); Tier B batch human approval (rewrites, merges, low-stakes redirects); Tier C explicit sign-off with migration protocol (URL changes, deletions, template changes). Pages with authoritative backlinks are never auto-deleted, by hard rule. Every batch: staging first, visual regression, snapshot, one-command rollback, and a change budget capping pages modified per site per week so one bad rule cannot nuke a site. Failed items hold in a queue for targeted retry or human escalation - they never ship.
**Test:** simulate a malicious or wrong decision at each tier; the blast radius must be bounded by structure, not by model goodwill.

### Law 6 - Measure or you are guessing.
Published A/B data (SearchPilot): ~75% of SEO changes are inconclusive, 7-8% measurably negative. Therefore unmeasured "optimization at scale" silently harms a meaningful fraction of everything it touches. Every deployed change cohort gets a GSC watch (28 days), statistical drop alerts, and an auto-proposed rollback. Verified before/after impact per change is also the retention product: it converts one-off projects into systems clients keep paying for.
**Test:** for any past change the system made, it must be able to show what happened next. If it cannot, VIOLATED.

### Law 7 - Route models like money.
Strong model plans, synthesizes, and faces the client (~20% of tokens); cheap tier executes bulk work (~80%): extraction, classification, per-page analysis, first drafts - via Haiku/Sonnet-class or open-weight official APIs (DeepSeek/GLM/Qwen at $0.14-1.40 per 1M). Prompt-cache every stable prefix (reads ~0.1x; verify cache_read_input_tokens is nonzero, hunt silent invalidators). Batch everything non-interactive (50% off). Never spend LLM tokens on what a deterministic API returns (crawls, PageSpeed, structured lookups) - that is the single largest avoidable sink. Track $/deliverable and $/client/month; publish the receipts. High AI spend is a waste signal, not a capability signal - a competitor bragging $1,200-1,500/day is confessing he has no routing.
**Test:** the system can state its cost per deliverable from logs, and >60% of its bulk tokens run below the flagship tier.

### Law 8 - Optimize the reward function, not proxies.
Google's policy is method-agnostic: it punishes scaled low-value publishing, not AI provenance. AI-share vs ranking correlation across 600k pages: 0.011 - zero. AI detectors are all sub-80% accurate and one paraphrase defeats them. Therefore: no detector-evasion loops, no humanizer chains, no "passes AI detection" gates or marketing. Optimize what actually moves outcomes: retrieval-grounded drafting, fact-check against primary sources, voice fidelity to the client's own writing, human SME input points (the E-E-A-T surface no fully-hands-off pipeline has), value-per-page over volume. Blind multi-pass self-refinement degrades quality (self-bias); refine only with external feedback - a failing gate's specific error report, injected, max 2 retries, then human queue.
**Test:** list the metrics any pipeline optimizes toward. Every one must have a demonstrated causal link to rankings, conversions, or client trust. Proxy metrics are VIOLATED.

### Law 9 - Few strong models beat many weak ones.
Ensemble returns plateau at 6-10 curated models; mixing many diverse models underperforms sampling one strong model (Self-MoA). A "21-AI brain" is ~20x cost for negative quality delta. The correct pattern: a 2-4 model council at judgment gates only (chairman + cheap independent critics, anonymized cross-review), single strong model everywhere else. This is also a true marketing line - "multi-model adversarial review" - backed by published evidence.
**Test:** count models per query path. More than 4 on any path requires written justification against the plateau evidence.

### Law 10 - The brain is files that compound.
Knowledge lives as structured markdown/YAML in the workspace - playbooks, rule catalogs, golden specs, per-client case files - retrieved by agentic search (Anthropic dropped vector RAG from Claude Code because agentic search won). Add hybrid contextual RAG only when a specific corpus outgrows grep (a crawled 8k-page site qualifies; a playbook library does not). The compounding rule: every run appends structured outcomes to the client case file - what was found, what was fixed, what happened, client quirks - so the system is smarter on every engagement than the last. A brain that does not compound is a cache.
**Test:** diff a client case file before and after a run. No growth = no compounding = VIOLATED.

### Law 11 - Every capability terminates in a paid, verified action.
The strongest commercial pattern observed anywhere in this research: see the gap -> see the recommended work -> approve/pay -> automated guardrailed fulfillment -> verified impact report. Wire every capability into that loop. The audit is the upsell artifact; the button is the business; the impact report is the retention. A capability that cannot be bought, triggered, and verified by a client is an internal tool, not a product.
**Test:** for each capability, name the click that buys it and the report that proves it worked.

### Law 12 - Name your assets; count honestly.
"Superbrain" closed attention because named, demoable assets sell - the lesson survives even though his was vapor. Every system needs a name, a 3-minute demo narrative, and one signature number. But every number we publish must be real and survivable: count real API integrations, not plugins; publish the rule count and show any ten rules on request; quote crawl times we actually hit. When a competitor cites a giant number, the counter is always: "show me any ten of them."
**Test:** every quantitative claim in the system's README or sales material traces to something a prospect could verify live.

### Law 13 - Optimize for the answer, not only the link.
The surface is shifting from ten blue links to being the cited source inside AI answer engines (Google AI Overviews, ChatGPT, Perplexity, Claude). Rankings are a lagging, shrinking slice of visibility. Every system treats "share of answer" as a first-class outcome alongside rankings: extractable passage blocks, schema as machine-readable claims, entity clarity and consistency (sameAs, NAP, structured facts), `llms.txt`, and being present in the corpora and retrieval paths these engines actually pull from. Measure it - sample the money queries across engines and record whether the client is named, cited, or absent - because what is not measured is not being optimized (Law 6). A system that only tracks Google positions is optimizing yesterday's surface.
**Test:** the system can report, for the client's top queries, presence and citation share across at least two AI answer engines. If it only knows blue-link rank, PARTIAL at best.

### Law 14 - One canonical spine, or the systems rot.
Multiple SEO systems that each invent their own data shapes cannot share a crawl cache, a judgment corpus, or measured outcomes - they drift into divergent copies (the documented failure across this operator's workspaces). Every system reads and writes the canonical contracts: the crawl-store record, the Finding, the ActionPlan, the change/outcome ledger, the rule-catalog format, the client case-file (defined in `seo-system-spine.md`). A system may extend a contract; it may not fork one. This is what lets the advanced systems on other machines pool into one compounding brain (Law 10) instead of five brains that disagree. Interop is not a feature added later; it is the schema chosen first.
**Test:** take one Finding produced by system A; system B must be able to consume it without translation. If each system has its own private format for the same concept, VIOLATED.

---

## Part III - Hard lines

Non-negotiable across every workspace, every machine, every client, regardless of who suggests otherwise:

1. **No gray-market model access.** No proxy routers, key pools, farmed free tiers, region-arbitrage accounts, or marketplace keys. It is the stolen-key supply chain (LLMjacking), it routes client data through unknown operators, and it breaches every data-security clause we sign. Official open-weight APIs cost cents; there is nothing to gain.
2. **No automated tiered link building or PBN participation.** Spam-policy violation, penalty surface, liability to sell. White-hat internal linking and link reclamation only.
3. **No JS-pixel injection as an execution layer.** It is the documented incumbent failure mode and the exact opposite of our ownership wedge.
4. **No hands-off destructive actions.** Deletions, merges, mass redirects, URL migrations always carry a human gate. Most URL-changing migrations lose traffic; "hands-off restructure" is recklessness marketed as capability.
5. **No detector-evasion as a product.** See Law 8. If a prospect demands the checkbox, it is a one-day commodity integration priced as such, never a moat, never a headline.
6. **No unverifiable superlatives in our own material.** "Nobody has this" is a claim we tear down in competitors; it never appears in our copy.

---

## Part IV - Doctrine audit protocol

When this file is present in a workspace and the task is to build, improve, or modify an SEO system:

1. **Score:** walk Laws 1-14 against the system as it actually is (read the code, not the README - READMEs lie about maturity). Mark each HOLDS / PARTIAL / VIOLATED with one line of evidence (file:line where possible).
2. **Rank:** order violations by leverage using this default: Law 1/2 gaps (no execution loop) > Law 5/6 gaps (unsafe or unmeasured execution) > Law 3 gaps (no cache) > Law 13 gaps (blind to AI answer engines) > Law 7 gaps (cost) > Law 14 gaps (no shared spine, if more than one system exists) > the rest. A system with a beautiful audit and no execution path ranks below a crude system that safely applies fixes.
3. **Plan:** produce the upgrade plan as concrete build items with write surfaces, tools, and week-scale estimates. Reuse before rebuild: check the ecosystem (open source, existing workspace modules, sister workspaces) before writing new code - the audit layer especially must absorb, not rebuild.
4. **Verify claims:** any capability the upgraded system will advertise gets the Part I treatment - write the sales sentence, confirm it survives physics and a hostile buyer, adjust either the build or the sentence until it does.
5. **Compound:** append the audit result and what was built to the workspace's case file / build log, so the next session starts from evidence.

---

## Part V - Frontier bets

The laws are the floor. This is the ceiling. These are the moves that would put our systems somewhere the market is not - each is a real, buildable bet, not a fantasy, but each is unproven and harder than the laws. Treat them as the R&D backlog: the doctrine says "be excellent," this says "be somewhere no one else is." Pursue them when a system already holds the core laws; a system that fails Law 2 has no business attempting bet 2.

**Bet 1 - Outcome-first auditing (audit backward from the winner).**
Stop auditing sites against a 339-point checklist - that is the commoditized product. Audit against the specific entities ranking and being cited for the client's money queries: reconstruct what the winners have that the client lacks (entity coverage, schema claims, internal-link centrality, content depth, freshness, citation share) and make *that delta* the audit. This turns "here are your 3,724 issues" into "here are the 11 things standing between you and the money," which is a different and better product. Hard part: reliably modeling "what the winner has" from crawl + SERP + answer-engine data. Payoff: the audit becomes competitor-relative and un-genericizable.

**Bet 2 - The site digital twin.**
Maintain a true staging mirror and run every change against it before production, with predictive impact scoring, so the system becomes a closed control loop: propose -> simulate on twin -> measure proxy signals -> promote to production only what improved. The SaaS incumbents cannot do this because they rent JS pixels and never hold the real site. We insist on write/hosting access (Law 2), which makes the twin possible. Hard part: making twin signals predictive of production. Payoff: changes that are tested before they touch a client, not after.

**Bet 3 - The causal fix ledger (the real moat).**
Because every change cohort is measured (Law 6), accumulate a proprietary causal dataset: this fix class, in this vertical, at this site size, produces this expected ranking/traffic/citation delta. Feed those measured outcomes back as confidence weights on the rule catalog (Law 4), so the judgment engine is *trained by reality*, not by opinion. After N engagements the system knows, with evidence nobody else has, which fixes actually move the needle where. This is a data moat that compounds and cannot be bought or scraped - it is the honest, defensible version of the competitor's "1,500 rules" fantasy.

**Bet 4 - Adversarial self-red-team before ship.**
Before any change deploys, a red-team agent attacks it: can this trip scaled-content-abuse, degrade E-E-A-T, create cannibalization, or get penalized. Ship only what survives its own attack. This operationalizes "adversarially verify" (our research method) as a product guardrail, and it is the structural opposite of the operator who shipped unsafe and retrofitted guardrails after breaking client sites.

**Bet 5 - Entity and knowledge-graph engineering.**
Treat the client as an *entity to be established* in the machines' world models (Google Knowledge Graph, Wikidata, the LLMs' internal representations), not just a site to rank. Engineer entity consistency and structured claims, seed the authoritative sources these systems ingest, and measure whether the models "know" the entity correctly and completely. This is upstream of both rankings and citations and is where durable AI-era visibility is won.

**Bet 6 - Real crawl-budget engineering from server logs.**
Most tools guess how bots crawl. With server access (Law 2), ingest real logs and see exactly how Googlebot, GPTBot, ClaudeBot, and PerplexityBot actually traverse the site - then engineer crawl budget, bot access, and render paths against ground truth. Only possible for a system that holds the write/hosting boundary; invisible to every rented-pixel competitor.

**Bet 7 - The cross-client meta-brain (privacy-scoped).**
The judgment corpus and causal ledger (bets 3, Law 10) learn across every engagement, scrubbed of client-private data per the founder rule, so vertical-level patterns compound: the tenth roofing client benefits from the measured outcomes of the first nine. Each client owns their instance; the anonymized pattern layer is the house asset. This is the only "brain" claim in this document that would actually be true - and it is a learning loop, not a server.

Rule for this part: a frontier bet graduates into a law only after it has shipped, been measured on a real client, and survived the physics and hostile-buyer tests (Part I). Ambition earns its place by proof, not by ambition.

---

Numbers in this doctrine (prices, benchmark figures, plateau counts) were verified July 2026. They drift. Re-verify before quoting externally; re-verify all of them quarterly. The laws are stable; the constants are not; the frontier bets are hypotheses until proven.
