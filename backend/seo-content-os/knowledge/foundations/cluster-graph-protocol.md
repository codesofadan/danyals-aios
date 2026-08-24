# Cluster Graph Protocol

This file specifies how SEO-CONTENT-OS structures a local service site as a topical graph: what the nodes are, how they parent and child each other, and which nodes link to which. Cluster discipline is one of the highest-leverage moves the system makes. A local site with a clean hub-and-spoke graph reads to Google and to AI answer engines as an authoritative entity for its services in its geography; a pile of disconnected pages reads as noise.

If you remember nothing else: the canonical local silo is **homepage -> service hubs -> service-in-city spokes (the money pages) -> city/location pages -> service-area pages**, every money page links up to both its service hub and its city page, and no node is a templated near-duplicate of another.

This file owns the **graph and topology**: node types, parent/child structure, and which nodes link to which. It does not own anchor-text wording or link-equity flow mechanics; those live in `internal-linking.md`. It does not own node SELECTION either: the set of nodes it wires is the promoted `status: page` set chosen upstream by `topical-map-protocol.md`. Where the files overlap, reference them, do not restate them.

---

## The node types

A local service site in SEO-CONTENT-OS has six node types, one per page type. Their roles in the graph:

1. **Homepage.** The single root and the primary entity anchor. It names the business, the core services, and the geography served. It links down into every service hub and into the top city/location pages. Everything in the graph ladders up to here.

2. **Service hub (service page).** One per core service the business offers (AC repair, furnace repair, installation). The broadest page on that one service, brand-wide, not tied to a single city. It is the parent of every service-in-city spoke for that service. It links down to all of its city spokes and up to the homepage.

3. **Service-in-city spoke (the money page).** One service crossed with one city. This is the page built to rank and convert for "[service] [city]" ("AC repair Tempe"), and it is where the commercial intent and the revenue live. Each spoke has two parents: its service hub (what) and its city/location page (where). It must link up to both.

4. **City / location page.** One per city the business actively serves. It is the geographic hub for that city: it links to every service the business offers in that city (that is, to each service-in-city spoke scoped to that city) and up to the homepage. It carries genuinely local content about operating in that specific city.

5. **Service-area page.** Covers the broader footprint: the full list of cities, towns, and neighborhoods served, often organized by region. It links to the city/location pages and, where relevant, directly to money pages. It is the coverage map, not a stack of thin duplicate city pages.

6. **About page.** The trust and E-E-A-T node. It is not part of the commercial hub-and-spoke flow, but it is linked from the homepage and referenced from money pages where credentials matter (license, insurance, years in business). It feeds entity clarity for answer engines rather than topical-commercial ranking.

---

## Parent and child relationships

The graph has two intersecting axes: a **service axis** (what the business does) and a **geography axis** (where it does it). The money page is the cell where a service row meets a city column.

```
                         homepage (root, entity anchor)
                        /         |          \
         service hub A     service hub B      service hub C
        (AC repair)       (furnace repair)   (installation)
              |                  |                  |
   ...each hub links DOWN to all its city spokes...
              |                  |                  |
        [AC repair Tempe] [furnace repair Tempe] [installation Tempe]
              \______________ | ________________/
                              |
                    city / location page: Tempe
                    (links to every service offered in Tempe)
                              |
                    service-area page (Tempe, Mesa, Chandler...)
```

Read it two ways:
- **Down the service axis:** homepage -> service hub -> its city spokes.
- **Down the geography axis:** homepage -> service-area page -> city/location page -> that city's service spokes.

Every money page sits at the intersection and therefore has a parent on each axis: the service hub above it (service axis) and the city page beside/above it (geography axis).

---

## The internal-linking rules between node types

These are the edges the graph requires. Anchor-text wording and equity-flow reasoning are in `internal-linking.md`; here we specify only which edges must exist.

1. **Service hub links down to all of its city spokes.** The AC repair hub links to AC repair Tempe, AC repair Mesa, AC repair Chandler. This is what makes the hub a real hub and distributes authority to the money pages.

2. **Every spoke links up to its service hub.** AC repair Tempe links up to the AC repair service page. Bidirectional with rule 1. A money page that is linked down-to but never links back reads as an orphan to retrieval models.

3. **Every spoke also links up to its city / location page.** AC repair Tempe links to the Tempe location page. This is the second parent edge, on the geography axis. Every money page carries both up-links: to its service and to its city.

4. **City / location page links to every service offered in that city.** The Tempe page links to AC repair Tempe, furnace repair Tempe, installation Tempe. This makes the city page the geographic hub and lets a Tempe visitor reach any service from one place.

5. **Sibling spokes link laterally where genuinely relevant.** AC repair Tempe links to furnace repair Tempe (same city, adjacent need) and, more weakly, to AC repair Mesa (same service, neighboring city) only where a real reader would want that path. Link where it genuinely helps a customer, never to hit a quota. Do not cross-link every spoke to every other; that dilutes the signal and reads as a link farm.

6. **Service-area page links down to the city / location pages** and up-links from each city page point back to the service-area page, so the coverage map is navigable in both directions.

7. **Homepage links down to the service hubs and to the top city pages.** It is the root; it should reach the primary branches in one hop.

8. **No orphan money pages, ever.** Every service-in-city spoke must have both up-links (service hub and city page) live before it ships. A money page with no inbound path from a hub is invisible to both users and retrieval systems. This is the graph's hardest gate.

---

## The anti-doorway rule (doctrine hard line)

Every spoke and every location node must carry unique, genuinely local value. This is a hard line from the doctrine (Part III, hard line 4 on destructive/spam patterns) and from CLAUDE.md's "No doorway pages" rule, and it is where most local SEO builds fail.

The failure mode: generate one template, then mass-produce "AC repair Tempe / AC repair Mesa / AC repair Chandler / AC repair Gilbert..." pages that are byte-for-byte identical except the city name swapped in. Google's spam policy names this exactly - scaled, templated, thin location pages are doorway pages, and the doctrine's Law 8 reframes the point: the penalty is for scaled low-value content, not for the method used to make it. A hundred near-duplicate city pages is scaled low-value content whether a human or a model typed it.

The rule this system enforces instead:

- A city spoke ships only when it carries locally true specifics that page alone has: a real local price band, a permit or code fact for that jurisdiction, response times to that city's neighborhoods, a job actually done there, a condition specific to that place (hard water, clay soil, coastal salt, a local climate driver). Facts come from `brand.yaml` or research, never invented.
- If there is nothing locally true to say about a city yet, that city does not get a full spoke. It gets a linked entry on the service-area page until real local content exists. An empty page is better than a doorway page; a doorway page is a spam-policy liability across the whole domain.
- Two city pages for the same service must differ in substance, not just in the city token. The passage blocks on each (see `passage-block-protocol.md`) must answer that city's version of the question with that city's real facts.

The graph is what makes non-doorway scale possible: the hub-and-spoke structure gives each money page a legitimate reason to exist (a distinct service-city intent with distinct local facts), rather than a template stamped N times.

---

## Worked example: HVAC company, 3 cities, 3 services

A small HVAC business serves **Tempe, Mesa, and Chandler** and offers **AC repair, furnace repair, and installation**. That is a 3x3 grid, so nine money pages plus the hubs and geo nodes.

### The full node graph

```
Homepage
|
+-- Service hubs (service pages)
|     +-- AC repair              [hub]
|     +-- Furnace repair         [hub]
|     +-- Installation           [hub]
|
+-- Service-in-city spokes (money pages, 3x3 = 9)
|     +-- AC repair Tempe        Furnace repair Tempe      Installation Tempe
|     +-- AC repair Mesa         Furnace repair Mesa       Installation Mesa
|     +-- AC repair Chandler     Furnace repair Chandler   Installation Chandler
|
+-- City / location pages
|     +-- Tempe        [geo hub]
|     +-- Mesa         [geo hub]
|     +-- Chandler     [geo hub]
|
+-- Service-area page  (Tempe, Mesa, Chandler, + towns/neighborhoods served)
|
+-- About page  (license, insurance, years, technicians - trust node)
```

### The link edges

Service-axis down-links (rule 1), one hub to its three city spokes:

```
AC repair (hub)        -> AC repair Tempe, AC repair Mesa, AC repair Chandler
Furnace repair (hub)   -> Furnace repair Tempe, Furnace repair Mesa, Furnace repair Chandler
Installation (hub)     -> Installation Tempe, Installation Mesa, Installation Chandler
```

Every spoke's two up-links (rules 2 and 3), shown for the Tempe column:

```
AC repair Tempe        -> AC repair (hub)  AND  Tempe (city page)
Furnace repair Tempe   -> Furnace repair (hub)  AND  Tempe (city page)
Installation Tempe     -> Installation (hub)  AND  Tempe (city page)
```

City page down-links to every service in that city (rule 4):

```
Tempe (city page)      -> AC repair Tempe, Furnace repair Tempe, Installation Tempe
Mesa (city page)       -> AC repair Mesa, Furnace repair Mesa, Installation Mesa
Chandler (city page)   -> AC repair Chandler, Furnace repair Chandler, Installation Chandler
```

Lateral edges, only where a real customer path exists (rule 5):

```
AC repair Tempe        <-> Furnace repair Tempe     (same city, a homeowner with one HVAC problem often has the other)
Installation Tempe     <-> AC repair Tempe          (a failing repair converts to an install decision)
AC repair Tempe        -> AC repair Mesa            (weak, same-service neighbor city; include only if genuinely useful)
```

Not every pair. There are 36 possible spoke pairs in a 3x3 grid; only a handful carry a real reader journey. Same-city cross-service links are the strongest (a Tempe homeowner reads AC repair, may need furnace or install in Tempe). Same-service cross-city links are weak and mostly unnecessary; a Tempe searcher rarely wants the Mesa page. Link the strong ones, skip the rest.

Geography-axis edges:

```
Service-area page      -> Tempe, Mesa, Chandler (city pages)
Tempe / Mesa / Chandler city pages -> Service-area page (up-link)
Homepage               -> AC repair, Furnace repair, Installation (hubs)  AND  Tempe, Mesa, Chandler (top city pages)  AND  About
```

### Why this survives the anti-doorway gate

The nine money pages are not templates. AC repair Tempe carries Tempe's summer-peak AC-season lead times and the local code trigger for a condenser replacement; AC repair Chandler carries Chandler's own permit fee and a note on the hard-water effect on coil life there; Installation Mesa carries Mesa's rebate program for high-efficiency units if one exists. Each is a distinct service-city intent answered with that cell's real local facts, pulled from `brand.yaml` and research. If the business genuinely has nothing local to say about, say, furnace repair in Chandler yet (furnaces are rare there, few jobs done), that page waits and Chandler furnace repair is a linked line on the service-area page until real content exists. The grid is the ceiling of what could exist, not a mandate to stamp out all nine on day one.

---

## Orphan rejection

Before any money page ships, confirm it has both up-links live: to its service hub and to its city/location page, and that the service hub links back down to it. A spoke that fails either check is an orphan and does not ship until the edges exist. In practice this means a new money page is never published alone; publishing "AC repair Gilbert" requires that the AC repair hub gains a link to it and a Gilbert city page exists (or is created in the same batch) to parent it on the geography axis. No orphan money pages is the graph's non-negotiable gate.

---

## What this protocol does not cover

- **Anchor-text wording and rotation, and link-equity flow.** Owned by `internal-linking.md`. This file says which edges exist; that file says what the link text reads and how authority moves along the edges.
- **The internal structure of a single page** (the answer blocks inside it). Owned by `passage-block-protocol.md`.
- **Which cities and services are worth a node at all.** Node SELECTION is owned by `topical-map-protocol.md` (built by `/build-topical-map`): the graph wires the promoted `status: page` nodes the topical map hands it, already filtered from the grid by real demand, the user-cluster merge, and the evidence gate. `keyword-research-method.md` supplies the discovery that feeds that selection. The graph organizes the nodes the map promotes; it does not choose them, and it never wires an `index-only` node (those live only as linked entries on the service-area/hub page until they earn promotion).
- **NAP and entity consistency across the graph.** Owned by `nap-consistency.md` and `local-gbp-signals.md`.

The graph is the skeleton. It decides what links to what and forbids orphans and doorways. The passage blocks are the muscle on each node; the internal-linking file is the wiring detail; the playbooks decide which bones exist. Build the skeleton first, then no page is ever stranded and no page is ever a duplicate.
