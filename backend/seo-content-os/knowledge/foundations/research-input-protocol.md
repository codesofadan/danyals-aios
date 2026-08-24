# Research Input Protocol

This file resolves the single hardest constraint in the discovery layer: the prime rule says every keyword and every map node must trace to a real demand signal (an autocomplete suggestion, a People-Also-Ask question, a related search, a competitor page that ranks), but the tools cannot always fetch those signals. Live `google.com/search` autocomplete and PAA are JavaScript-gated and routinely blocked to an automated `WebFetch`. If the discovery step silently fails, an agent is one weak moment away from inventing demand to fill the map, which is the exact Law 8 violation the prime rule exists to prevent.

This protocol makes discovery honest under real tool constraints. It defines where demand signals come from, in reliability order; it defines the one unbendable rule when a signal cannot be obtained (the node stays a flagged candidate, never a fabrication); and it defines the operator-supplied research-input file that carries the browser-captured corpus the tools cannot fetch themselves.

It governs both discovery-running agents: `keyword-intent-researcher` (per page) and `topical-map-architect` (per client). Both read the research input; neither invents a signal.

---

## The problem, stated plainly

`keyword-research-method.md` teaches discovery as a human sitting in an incognito window reading autocomplete, the alphabet-soup pass, PAA, and related searches. That is the correct method. But an agent is not a human in a browser: its `WebSearch` returns result listings (which work), while `WebFetch` of a live Google SERP for the autocomplete dropdown or the PAA accordion usually returns a JS shell, not the data. So the richest demand signals (autocomplete, PAA) are the ones the agent is least able to fetch directly. The method assumed a capability the runtime does not reliably have. This protocol closes that gap instead of pretending it is not there.

---

## The demand-signal sources, in reliability order

Every node's `demand_trace` must cite at least one of these. Prefer the highest tier available.

**Tier A - Operator-supplied research input (the ground truth).** The operator (or a human browser session) captures the real SERP signals a browser sees and pastes them into `clients/<slug>/research-input.md` (format below). This is autocomplete dropdowns, the alphabet-soup pass, verbatim PAA, related searches, and the ranking-competitor URLs, captured from a logged-out browser in the target city. It is the most reliable signal because it is exactly what the human method produces, and it is immune to the JS-gating problem because a human captured it. When present, it is authoritative.

**Tier B - Agent `WebSearch` (works, use always).** The agent's `WebSearch` tool returns real result listings for a query. Use it to find the ranking competitor pages for each head query, to read the titles and snippets the SERP surfaces, and to surface related and "people also search for" terms that appear in the results. This is reliable and should always run, whether or not Tier A exists.

**Tier C - Agent `WebFetch` of specific non-Google URLs (works for most sites).** Once `WebSearch` names the ranking competitor URLs, `WebFetch` them directly. Competitor service/location pages, directory pages (Yelp, Angi listings), and GBP-adjacent pages are usually plain enough to read. Extract their service list, their city list, their nav, and what local specifics they carry. This is the competitor-architecture signal, and it is reliable because these are not the JS-gated Google SERP itself.

**Tier D - `brand.yaml` real capabilities (always available).** The business's real `services`, `service_areas`, `gbp.primary_category`, `gbp.secondary_categories`, `gbp.services`, and `brand_terms`. A node may be seeded from a real capability the business has, even before external demand is confirmed - but a capability alone is a candidate, not a confirmed node (see the rule below).

What the agent must NOT do: treat its own recall as a demand signal. "Businesses like this usually need an X page" is not a signal from any tier; it is model pattern-completion, which the prime rule forbids. A node's demand must trace to Tier A, B, C, or a real Tier D capability, never to memory.

---

## The unbendable rule: unverifiable demand becomes a flagged candidate, never a fabrication

For any candidate node:

- If its demand traces to a real signal (Tier A/B/C) OR it is a real Tier D capability with at least one supporting external signal, it is a genuine node and enters the map (its `status` then set by the evidence gate, per `topical-map-protocol.md`).
- If its demand cannot be verified from any tier (no operator input captured it, `WebSearch` surfaces nothing, no competitor targets it, and it is not a real `brand.yaml` capability), the node does **not** get invented. It becomes a **flagged candidate**: recorded in the output as "demand unverified - needs operator capture," and the operator is asked to run the browser capture (Tier A) for that seed. It never becomes a `status: page` node, and it is never written as if the demand were confirmed.

This is the discovery-layer form of the system's core discipline: under starvation, flag the gap, never fill it with an invention. A thin map that honestly says "I could not verify demand for these five candidates, capture them and re-run" is correct. A full map padded with unverified guesses is the failure.

---

## The research-input file

`clients/<slug>/research-input.md`, filled from `templates/research-input.md`. The operator captures the browser signals the agent cannot fetch and pastes them here. The agent reads it first, then supplements with Tier B/C. Structure:

- **Autocomplete** per seed service x top city (the dropdown, plus the alphabet-soup pass worth keeping).
- **People Also Ask**, verbatim, per head query (these become FAQ entries and passage-block leads too).
- **Related searches** from the foot of each SERP.
- **Ranking competitors** per head query: the URLs, and from each, the page type and the services/cities in its nav.
- **Map-pack GBP categories** the competitors chose.
- **Capture metadata**: the city the SERP was queried from and the date, so the freshness is known.

The file is optional in the sense that the pipeline does not hard-halt without it (Tier B/C still run), but any node whose demand would have come only from autocomplete/PAA (which the agent cannot fetch) stays a flagged candidate until the operator supplies this file. So for a real build, capturing it is how the map reaches full coverage rather than competitor-visible coverage only.

---

## How the two discovery agents use this

**`topical-map-architect`** (per client, at plan time): reads `research-input.md` first (Tier A), runs `WebSearch` for each head query (Tier B), `WebFetch`es the named competitors (Tier C), and reads `brand.yaml` capabilities (Tier D). Every candidate node's `demand_trace` cites its tier. Candidates with no verifiable demand are listed in the map's coverage-reality note as "demand unverified - capture and re-run," not promoted, not invented.

**`keyword-intent-researcher`** (per page, at write time): reads `research-input.md` for the page's query if present (Tier A), always runs `WebSearch` + competitor `WebFetch` (Tier B/C) for the live SERP read, and never fabricates a volume, a PAA question, or a SERP feature. Its existing "no invented numbers, no fabricated SERP features" discipline is the same rule; this protocol just names where the real signals come from when the live SERP cannot be fetched directly.

---

## Why this is not a workaround that weakens the method

The human method was always the ground truth; the tools only ever approximated it. This protocol makes that explicit: the operator's browser capture is Tier A precisely because the human sitting in the incognito window is the most reliable instrument, exactly as `keyword-research-method.md` describes. `WebSearch` and competitor `WebFetch` are real, working signals that cover most of the demand surface on their own. The only thing this protocol refuses to do is let the model paper over a fetch failure with a guess. That refusal is the whole point: the map's value is that every node is real, and a node built on unverifiable demand is not real, no matter how plausible it looks.