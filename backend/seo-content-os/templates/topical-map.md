# Topical Map - <brand_name> (<slug>)

The site-level source of truth for which pages this client should have. Built once by
`/build-topical-map` (the `topical-map-architect` agent) per
`knowledge/foundations/topical-map-protocol.md`, then re-read before every `/brief`
and `/write-*` command. Save the filled map to `clients/<slug>/topical-map.md`.

Rules this artifact enforces (do not violate when filling it):
- Every node traces to a live demand signal (autocomplete / PAA / related search /
  ranking competitor / GBP category or Services) or a real capability in `brand.yaml`.
  No node is proposed from memory.
- The grid (every service x every city) is the CEILING, not this list. This list is the
  filtered subset that survived demand + user-cluster merge + the evidence gate.
- Every node defaults to `status: index-only`. It is promoted to `status: page` ONLY
  when the `evidence` column names a real first-party specific that makes that page
  un-copyable. No evidence, no page.
- No coverage %, no completeness score. Map quality is the evidence gate, not node count.

---

## Entity anchor (from brand.yaml `entity`)

- **Map mode:** <lite | full>  (lite = small/single-location; the default. full = large multi-service x multi-city. See topical-map-protocol.md "Map mode".)
- **Central entity:** <business + primary service>
- **Source context:** <what it is + how it monetizes>
- **Central search intent:** <falls out of the two above; usually local-transactional / ready-to-hire>
- **Primary GBP category (head-term anchor):** <gbp.primary_category>
- **Real footprint (from brand.yaml):** services = <n>, service_areas = <n>, locations = <n if multi-location>
- **Grid ceiling:** <services x modifiers x cities = N candidate cells> (FULL mode only; for reference. LITE maps may omit this line.)
- **Date built (PKT):** <YYYY-MM-DD>

---

## Node table

Status legend: `index-only` = acknowledged coverage, linked on the service-area/hub page, no dedicated URL yet. `page` = promoted, has evidence, gets built.
Section legend: `core` = money page, converts, built first, receives link priority. `outer` = builds trust/historical data, funds the core.

| node_id | entity / attribute (class) | section | page_type | target_query | intent | geography (user_cluster) | status | priority | command |
|---|---|---|---|---|---|---|---|---|---|
| <ac-repair-tempe> | <business + AC repair> (root) | core | service-in-city | <ac repair tempe> | LOCAL-TRAN | Tempe (cluster: E-valley) | page | 1 | /write-service-city-page |
| <furnace-repair-chandler> | <business + furnace repair> (root) | core | service-in-city | <furnace repair chandler> | LOCAL-TRAN | Chandler | index-only | - | /write-service-city-page |
| ... | | | | | | | | | |

---

## Per-node detail

Repeat this block for every node in the table. The `evidence` and `info_gain_thesis`
lines are the promotion gate: a node cannot be `status: page` without both filled from
real facts.

### <node_id>

- **Entity / attribute:** <the business + the service/attribute> - class: <unique | root | rare>
- **Section:** <core | outer>  (core = converts; outer = builds trust)
- **Page type + command:** <service-in-city> - `/write-service-city-page`
- **Target query:** <primary head query, read off the live SERP>
- **Query network:** <secondary queries / PAA / variants this node also answers>
- **Intent:** <EMERGENCY | LOCAL-TRAN | NEAR-ME | LOCAL-COMM | LOCAL-INFO | NAV>  (the six local classes from search-intent-taxonomy.md)
- **Geography / user cluster:** <city or brand-wide; name the cluster if merged with behaviorally-identical geos>
- **Demand trace (why this node exists):** <the live signal: "autocomplete + 2 ranking competitor city pages + GBP Services entry">
- **Parents (for the link graph):** <service hub node, city node>
- **Contextual bridges:** <sibling node - shared attribute justifying the link>
- **Evidence (the promotion gate):** <the un-copyable first-party specific from brand.yaml/SME: a real local price band, a permit/code fact, a job done here, a local condition. If empty, this node stays index-only.>
- **Info-gain thesis:** <one sentence: the net-new fact this page adds beyond the SERP consensus>
- **Status:** <index-only | page>  (page only if evidence + thesis are real)
- **Priority:** <publish-order rank; core-first, then Win-now, then Impact-vs-Difficulty>
- **Build state:** <planned | briefed | drafted | published>

---

## Publishing plan (derived from the table)

Ordered list of the `status: page` nodes, core-first, in build order. This is the
input to a greenfield batch build and to `/brief`.

1. <homepage - entity anchor>
2. <primary service hub>
3. <highest-Win-now money page>
4. ...

**Nodes held at index-only (and why):** <list nodes that lack evidence yet, with the one specific each is waiting on. These are the SME's homework and the service-area page's linked entries.>

---

## Coverage reality (not a score)

A plain-language note, not a percentage: how much of the real winnable footprint the
promoted set covers today, what is deliberately held back for lack of evidence, and what
the next evidence-gathering step is. This replaces any "topical authority %" number,
which the protocol forbids.

- **Promoted (pages):** <n> nodes
- **Held (index-only, awaiting evidence):** <n> nodes - waiting on: <the specific facts>
- **Next evidence step:** <the SME questions or research that would promote the highest-priority held nodes>
- **Levers this plan does NOT move:** proximity, GBP configuration (category/services), and review velocity/recency dominate the local pack but are not on-page content. Reviews -> `/write-review-requests` + `/write-review-responses`; GBP + proximity are operator work. (Review velocity often outranks building the next marginal page.)
