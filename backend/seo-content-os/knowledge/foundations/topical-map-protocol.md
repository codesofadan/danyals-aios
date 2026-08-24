# Topical Map Protocol

This file specifies how SEO-CONTENT-OS plans a client's whole content footprint before a single page is written. It owns **node selection**: which pages should exist for this business, in what priority, classified core or outer, each gated on real evidence before it becomes a page. It is the site-level source of truth that `/brief` and every `/write-*` command consume.

If you remember nothing else: the topical map is a **demand-and-evidence-filtered subset of the possible pages, not the full grid**. The service-by-geography grid is the ceiling of what could exist; the map is the smaller set that survives real demand, real local differentiation, and behavioral de-duplication. A node ships as a full page only when the client has first-party evidence that makes that page un-copyable. No evidence, no page.

This file owns the **plan** (what nodes exist and why). It does not own link topology (that is `cluster-graph-protocol.md`, which receives the surviving node list and wires it), keyword discovery mechanics (that is `keyword-research-method.md`, now a supplier of candidate variants for justified nodes), or the internal structure of a single page (that is `passage-block-protocol.md`). Where they overlap, reference them, do not restate them.

---

## Why this exists, and what it replaces

Before this file, node selection was implicit. `keyword-research-method.md` §0 specified "one keyword map per client... run this method once per client to build the map," but nothing ever ran it once at the site level, nothing persisted it, and no command or agent owned it. Node selection happened per page, inside `keyword-intent-researcher`, one query at a time. And the selection logic it taught was a **grid** (§3, "Local modifier expansion - the grid"): cross every service against every modifier against every city.

`cluster-graph-protocol.md` explicitly disclaims node selection: it organizes the nodes it is handed and does not choose them (it now names this protocol as the selector). Before this file existed, that left a hole: a grid-shaped selection method with no owner, no persisted artifact, and no evidence gate on which cells become pages. This protocol fills the hole. It elevates the keyword map into a topical map, gives it an owner (`/build-topical-map` and the `topical-map-architect` agent), persists it (`clients/<slug>/topical-map.md`), and puts an evidence gate on every node.

---

## Map mode: lite (default for small/local) vs full

The map has two modes, because a single-location dentist and a fifty-city HVAC franchise do not need the same apparatus. The mode is chosen first and recorded in the map header; it decides how much of this protocol applies.

- **`lite` (the default for local).** For a single-location business, or any site whose candidate page count is under roughly 25. This is most local clients. `lite` keeps the load-bearing discipline and drops the ceremony: it uses source context / central entity / central search intent, the core/outer split, the demand filter, the user-cluster merge, and the evidence gate, and it writes the minimal node fields only (`node_id`, `entity`, `section`, `page_type`, `target_query`, `query_network`, `intent`, `geography`, `parents`, `evidence`, `status`, `priority`, `info_gain_thesis`, `command`). It skips the EAV attribute-classing, the ontology/attribute-value layer, and the grid-ceiling arithmetic as a formal artifact. A `lite` map is a right-sized, evidence-gated page plan. It is not called a "topical map" in the full semantic sense, and it does not pretend to be.

- **`full`.** For a genuine multi-service x multi-city build (a large candidate ceiling, roughly 50+ distinct service-city combinations across many cities), where topical breadth is the actual competitive problem. `full` adds the complete apparatus: the EAV attribute-value layer, the query-network construction, contextual-bridge nodes, and the information-gain node path (a node created from a real client capability that has no existing search-demand signal). These are specified in the advanced sections and are out of scope for a `lite` map.

**Choosing the mode.** Default to `lite`. Escalate to `full` only when the business genuinely spans many services across many cities and the candidate ceiling is large. Never run `full` on a small local site (it is ceremony a top operator would cut); never run `lite` on a real large multi-city build (it under-plans the breadth). When in doubt, `lite` - a smaller, evidence-gated plan is always safer than a large one built on ceremony.

---

## The prime rule: the map is built from real discovery, never generated from memory

An agent may not propose a node from what a business "like this" usually needs. Every node traces to a live demand signal or a real client capability:

- a live demand signal: a Google autocomplete suggestion, a People-Also-Ask question, a related search, a competitor page that actually ranks, a GBP category or Services entry (the one part of GBP that measurably moves rankings; GBP posts move rankings zero, so they are never a map node).
- or a real capability in `brand.yaml`: a service the business actually performs, a city it actually serves.

This is not a stylistic preference. It is the same discipline the system already enforces for facts (a local specific must trace to `brand.yaml`, the SME interview, or cited research, never invention) applied to the map. The reason is external and load-bearing: an auto-generated topic list is not a topical map. "Asking a model for 20 types of X" produces the consensus of what already ranks, which is the mean the system is built to beat (see the information-gain principle in `local-content-laws.md`). The map must come from the real query network a real market produced, read off the live SERP the way `keyword-research-method.md` teaches, not from pattern-completion.

Corollary: do not score topical authority with a number. There is no "coverage %" or "completeness %" gate, ever, for the same reason there is no AI-detector gate (Law 8): it is a proxy, and mechanical map-completeness without first-hand value is a thin-content farm at scale. An entity-attribute checklist may be used as a **planning prompt** (candidate attributes to go research demand for), never as a pass/fail score. The map's quality is judged by whether each node clears the evidence gate, not by how many nodes it has.

---

## The primitives (the usable core of topical authority, hype stripped)

The map is organized by five primitives. They come from the semantic-SEO topical-authority tradition; only the defensible, operational core is kept.

1. **Source context.** What the business is and how it makes money. It decides which topics connect logically to this site and which do not. For a local service business it is: this trade, these services, this geography, this monetization (booked jobs, quotes, calls). Comes straight from the extended `brand.yaml` `entity` block.

2. **Central entity.** The one thing that appears in every section of the map: the business crossed with its primary service (anchored to the GBP primary category, which is the head-term anchor and a real ranking lever). Everything on the map ladders up to the central entity.

3. **Central search intent.** The intersection of source context and central entity. It is not chosen freely; it falls out of the first two. For a local service business it is almost always local-transactional / ready-to-hire (a searcher who wants a nearby provider to hire now).

4. **Core section vs outer section (a monetization split, not a topic split).** This is the load-bearing structural decision.
   - **Core nodes** sit nearest monetization. They convert. For a local business these are the money pages: service-in-city combos, service hubs, the homepage. They receive internal-link priority and they get built first.
   - **Outer nodes** exist to build the historical-data and trust that lets core nodes rank: local guides, cost data, neighborhood context, FAQ corpora, about/team, review assets. They are not primarily destinations; they fund the core. Internal links flow outer-to-core more than the reverse.
   Classifying every node core or outer is mandatory. It decides publishing order and link direction.

5. **The node as an entity-attribute pair (EAV).** Each node covers one entity and one attribute of it (the business, its "AC repair" service, in "Tempe"; or the business, its "financing" attribute, brand-wide). This is what makes coverage a real thing rather than a keyword pile. Attribute priority runs **unique > root > rare**: a genuinely unique attribute (a service or local condition this business owns that competitors lack) justifies its own page; a root attribute (a core service everyone has) earns a page only where demand and evidence support it; a rare attribute (a niche, low-demand angle) folds into an existing node as a section rather than spawning a URL.

---

## The grid is the ceiling, not the generator

The full service-by-geography product (every service crossed with every city and modifier) is the **candidate space**, the upper bound of what could exist. It is never the plan. Three filters turn the ceiling into the map, in order:

1. **Demand filter (already in `keyword-research-method.md`).** A cell survives only if a real searcher produced a signal for it: autocomplete, PAA, a ranking competitor page. "If nobody suggests it and no SERP exists, it is not demand." A city the business does not serve never gets a cell, no matter the apparent volume.

2. **User-cluster merge (the local adaptation), operationalized.** Before finalizing, geographies (and services) with overlapping searcher behavior collapse into one node instead of each spawning a page. The test is concrete, the same SERP-overlap test `keyword-research-method.md` §6 uses for keyword clustering: **two geographies merge when their head-query SERPs (the top ~10 organic plus the local pack) share roughly 30-40% or more of the same ranking URLs AND carry the same dominant intent.** If "AC repair Tempe" and "AC repair West Tempe" draw largely the same ranking pages and the same map pack, they are one node, one page, not two near-duplicates. Borderline tie-break: merge if a real searcher in one geo would be equally served by the other's page (same neighborhoods, same operator coverage, no distinct local specific); keep separate only if each carries its own un-copyable specific (a different staffed office, a different code jurisdiction, a genuinely different local condition). This is the mechanism that makes the map smaller than the grid on purpose. Fewer, genuinely distinct pages beat more near-identical ones; the local evidence (evidence-driven location selection, "don't build pages for areas you don't serve," smaller markets often out-convert metros) and Google's own doorway policy point the same way.

3. **Evidence gate (the anti-doorway line, see below).** A surviving, merged cell becomes a full-page node only if the client has first-party evidence to make it un-copyable. Otherwise it stays a coverage-index line or routes to the service-area page.

What remains after the three filters is the map: usually far fewer nodes than the grid's cell count, each with a real reason to exist.

---

## The anti-doorway design at the map level

The single biggest new risk this protocol introduces is its own existence. Once a persisted map enumerates N nodes, there is gravity to treat "ship all N" as the success metric. A checklist begs completion, and completing a page checklist with thin pages is exactly the scaled-content-abuse pattern Google's spam policy and the doctrine's Law 8 forbid, now at a level where no per-page gate is watching. The per-page gates (`duplication_gate.py`, the outline anti-doorway check) catch template duplication after a page is drafted; they do not stop the map from proposing more full pages than the client has evidence for.

The design that prevents it:

- **Every node's default state is a low-commitment coverage-index line, not a page.** A node is born as one row in the map with a status of `index-only`.
- **Promotion to a full page is an explicit, evidence-gated step**, keyed to real fields in `brand.yaml` or the SME answers, mirroring the service-area page's existing "booked-jobs test + local-proof test." A node earns promotion to `page` only when it has at least one un-copyable local specific that page alone would carry: a real local price band, a permit or code fact for that jurisdiction, a job actually done there, a condition specific to that place, a named local proof. Facts come from `brand.yaml` or research, never invented.
- **Never the reverse.** Do not enumerate the full grid as pages and hope the write-time gate saves you. An empty coverage-index line is better than a doorway page; a doorway page is a domain-wide spam-policy liability.
- **If there is nothing locally true to say yet**, the node stays `index-only` (a linked entry on the service-area page) until real content exists. The grid is the ceiling of what could exist, not a mandate to stamp out all of it on day one.

### What counts as promotion evidence, by vertical

The promotion examples above (a local price band, a permit or code fact, a job done there) are home-services-shaped. The evidence gate is vertical-aware: what makes a page un-copyable differs by trade, and for a regulated vertical the usual proof may be forbidden. Promotion evidence by vertical:

- **Home services** (plumbing, HVAC, roofing, electrical): a real local price band, a permit or code fact for that jurisdiction, a documented job done in that city, a local condition (hard water, clay soil, storm season), a license or bond number.
- **Medical / dental** (YMYL): a named credentialed provider tied to the page, a procedure specific the practice actually does (technique, equipment, an in-house team), an office-level fact (a real staffed location, on-site imaging), dated outcome counts. NOT a patient testimonial or before/after unless a HIPAA consent is on file (`brand.yaml.eeat.consents`) - for a dental client with no consents, the evidence is credentials + procedure + office facts, never a patient photo.
- **Legal** (YMYL): a real case result or settlement (bar-advertising-rules aware, with the required disclaimer), an attorney's bar admission and practice-area depth, a jurisdiction-specific procedural fact.
- **Financial** (YMYL): a credentialed advisor (CFP/CPA with a CRD), a real fee or rate figure with its as-of date and source, a regulatory registration, the required disclosures.
- **Self-storage** (not YMYL, but its own dense evidence surface): real available inventory + a real price for that size/type at a real facility, this facility's own held climate range or concrete security spec, a real staffed building with its own NAP/GBP, a named campus/base for an audience page, or original dated market data for an asset. The full per-page-type promotion-evidence table, the storage grid axes, the query-cluster library, and the two structural rules (the single-facility collapse - a one-location operator gets ONE facility page, never separate axis pages - and the axis-page doorway cap) live in `knowledge/foundations/storage-topical-map.md`. Load it whenever `brand.yaml.vertical == self-storage`.

For every vertical the rule is the same: promotion evidence is a real, checkable, first-party specific this page alone carries, drawn from `brand.yaml` or the SME answers, never invented, and never a proof type the vertical's compliance overlay forbids. A node whose only available evidence is a forbidden proof type (a dental before/after with no consent) stays `index-only` until a permitted specific exists.

---

## Information gain and the index-only set: two resolutions

**Information gain is a thesis carried by a demand-backed node, not a demand-less node of its own.** The prime rule admits only nodes with real demand; the map exists to add net-new value beyond the SERP consensus. These are not in tension, because information gain does not need its own page. A page targets a query people actually search (the demand) AND wins it by carrying the first-hand fact no competitor has (the info-gain thesis). So a genuinely unique, un-copyable capability that nobody searches for (a `brand.yaml` differentiator with no autocomplete / PAA / competitor signal) does not become a standalone page - it becomes the `info_gain_thesis` of the closest demand-backed node, a section inside that node, or, if it is substantial and trust-building, an outer asset (an about-page detail, an FAQ answer, a linkable-asset angle). The map never spawns a page for an attribute with no demand, and never discards a real differentiator: it routes the differentiator into the demand-backed node that can carry it. That is how the map contains its information gain without violating the prime rule.

**The index-only set has a named consumer and a cap.** An `index-only` node is not a floating placeholder; it is rendered as a linked entry on the node's natural parent - the service-area page for a city node, the service hub for a service node. The link acknowledges the coverage and passes a little context without spending a full URL. But a coverage list is itself scaled-low-value content if it grows unbounded: a service-area page carrying 200 index-only city links is the same thin-content pattern the evidence gate exists to prevent, one level up. So cap it: a single parent page renders at most a human-scannable set of index-only entries (roughly 15-25, grouped by region); beyond that, the excess index-only nodes stay in the map (the record of what could exist) but are linked nowhere until they earn promotion. The cap keeps the deferral honest - index-only is a smaller, real coverage acknowledgment, not a dumping ground that recreates the doorway problem as a link farm.

---

## How the map drives everything downstream

- **Page inventory** = the set of nodes with status `page`. One page per promoted node. Nodes at `index-only` are coverage the site acknowledges but does not yet spend a URL on.
- **Publishing order** = core nodes first (they carry monetization and receive link priority), then outer nodes to build trust around them. Within core, sequence by the Win-now / Winnable-with-depth / Hard-defer read from `keyword-research-method.md` §5, layered with an Impact-vs-Difficulty pass (high impact, low difficulty first). The homepage and the primary service hubs anchor the entity and come first regardless.
- **Internal-link graph** = the promoted node list is handed to `cluster-graph-protocol.md` unchanged. The map records each node's core/outer class and its contextual bridges (links justified by a shared attribute or shared local context), and the graph enforces the hub-and-spoke topology and the no-orphan rule. The map chooses the nodes; the graph wires them.
- **Per-page briefs** = each promoted node carries its information-gain thesis (the one first-hand fact this page adds beyond the SERP consensus) into `/brief`, so the differentiation is decided at plan time, not rediscovered per page.

---

## The levers the map does not move (and where they go)

The map plans on-page content, which is roughly a fifth of what decides local visibility. It does not move - and must not pretend to move - the levers that dominate the local pack: proximity (fixed by the searcher and the address), the Google Business Profile configuration (category, services, completeness), and review volume, recency, and text. A map that presents itself as the whole local strategy is a misrepresentation. So the map is explicit about its scope:

- **Proximity and GBP configuration** are operator/GBP work, not content. The map reinforces the GBP category and services on-site (the central entity anchors to the GBP primary category; service nodes mirror the GBP service list), it does not claim to move the pack by content alone.
- **Reviews** (a heavy local factor: volume, recency, and the text Google reads to understand the business) are produced by `/write-review-requests` and `/write-review-responses`, not the map.
- **The plan names what it does not move.** Every map's coverage-reality note carries a one-line "levers this plan does not move" entry - proximity, GBP config, review velocity - routing each to its real owner. Review velocity often outranks building the next marginal page; the map says so rather than hiding 80% of the ranking model behind a page list.

---

## The map data model

Persisted at `clients/<slug>/topical-map.md` (human-readable table plus the per-node detail). One row per node. Fields:

| Field | Meaning |
|---|---|
| `node_id` | stable id, kebab-case (e.g. `ac-repair-tempe`) |
| `entity` | the business + the service/attribute this node covers |
| `attribute` | the attribute covered, and its class: `unique` / `root` / `rare` |
| `section` | `core` (converts) or `outer` (builds trust) |
| `page_type` | one of the system's page types, or `section` if it folds into another node |
| `target_query` | the primary head query, read off the live SERP |
| `query_network` | the secondary queries / PAA / variants this node also answers |
| `intent` | the local intent class (from `search-intent-taxonomy.md`) |
| `geography` | city / neighborhood / brand-wide; and `user_cluster` if merged with others |
| `parents` | the service hub and/or city node it links up to (for the graph) |
| `contextual_bridges` | sibling nodes it links to, and the shared attribute justifying each |
| `evidence` | the first-party specifics that justify a full page (from `brand.yaml` / SME); the promotion gate reads this |
| `status` | `index-only` (default) or `page` (promoted, has evidence) |
| `priority` | publish-order rank (core-first, then Win-now, then Impact-vs-Difficulty) |
| `info_gain_thesis` | one sentence: the net-new fact this page adds beyond the SERP consensus |
| `command` | the `/write-*` command that will build it when promoted |
| `build_state` | `planned` / `briefed` / `drafted` / `published` |

The map is re-read (and the live SERP re-checked for a node) before each write, so pages are built against the SERP as it is today, not as it was when the map was first made.

---

## The four traps (do not do these)

1. **Do not auto-generate the map with a model.** Every node traces to a live demand signal or a real capability. A model-proposed topic list is the consensus, which is what the system beats, not builds toward.
2. **Do not score topical authority with a script.** No coverage-%, no completeness-%, no attribute-matrix gate. The entity-attribute checklist is a planning prompt only. Map quality is the evidence gate, not the node count.
3. **Do not treat the information-gain patent as a ranking law.** The defensible basis for covering a topic well is Google's helpful-content self-assessment (does the content provide substantial, complete value versus other results), not a document-sequence redundancy patent Google has never confirmed uses in core ranking. See `local-content-laws.md` (Law 15), which states coverage is a floor and a warning, never the reward.
4. **Do not propose the full grid as pages and hope the gate saves you.** Node default is `index-only`; promotion is evidence-gated. The map's existence is the new doorway risk, and no per-page gate watches the map.

---

## What this protocol does not cover

- **Link topology, anchor text, equity flow.** Owned by `cluster-graph-protocol.md` and `internal-linking.md`. The map hands them the promoted node list.
- **Keyword discovery mechanics.** Owned by `keyword-research-method.md`, now scoped as a supplier of candidate keyword variants and the live-SERP read for a justified node, not the node selector.
- **The internal structure of a single page.** Owned by `passage-block-protocol.md`.
- **The client facts the map is built from.** Owned by `clients/<slug>/brand.yaml` (specifically the `entity`, `services`, `service_areas`, and `competitive_set` fields).
- **Auditing an existing site against the map.** The audit scenario (a future build, not yet shipped) will read the map as the should-exist set and diff it against the live-and-adequate pages. This protocol only produces the should-exist set; the diff, and its owning command/agent, are backlog (see `research/expansion-2026-07/08-above-the-page-architecture.md`, scenario D). Do not assume an audit protocol exists today.

The map is the plan. It decides which pages deserve to exist and forbids stamping out pages the client cannot make un-copyable. Build the map first, evidence-gate every node, hand the promoted set to the graph, and no page is ever a doorway and no page is ever stranded.