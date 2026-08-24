# Storage Topical Map + Keyword Cluster Library

The self-storage specialization of `knowledge/foundations/topical-map-protocol.md` (node selection) and `knowledge/foundations/keyword-research-method.md` (the query network). Load this whenever `brand.yaml.vertical == self-storage`, at PLAN time (inside `/build-topical-map` / `topical-map-architect`) and per node at RESEARCH time (inside `keyword-intent-researcher`). It does not replace those files; it supplies the storage-specific grid axes, the storage query-cluster library, the storage promotion-evidence rules, and the two structural rules unique to storage (the single-facility collapse and the axis-page doorway cap).

Built from `research/self-storage-2026-07/01-site-architecture.md` (the taxonomy and silo) and `02-keyword-clusters.md` (the query network). Every rule traces to a real page fetched that run; re-read the live SERP per node before writing.

If you remember one thing: **the storage grid is a three-axis product (facility x storage-type x unit-size, plus an audience axis) crossed with geography, and it is a CEILING, not a plan.** The map is the far smaller subset that survives real demand, a real first-party specific per node, and the collapse rule. A storage node ships as a page only when the facility has real inventory or a real operating fact that makes that page un-copyable. No inventory, no fact, no page.

---

## 1. The storage entity and central intent

- **Central entity:** the business crossed with self-storage, anchored to the GBP primary category ("Self-storage facility"). For a single-facility operator the central entity is that one building; for a multi-facility operator it is the brand, with each staffed facility a location sub-entity.
- **Source context:** how the operator makes money - month-to-month unit rentals, the admin fee, and the tenant protection plan (the margin engine). Storage revenue is occupancy x rate, driven online by live inventory + the local pack.
- **Central search intent:** local-transactional / ready-to-rent (a renter solving a life event - one of the 6 Ds: Death, Divorce, Dislocation, Downsizing, Decluttering, Distribution - who wants a nearby unit now), plus a large informational layer ("what fits in a 10x10," "how much does storage cost") that earns links and AI citations and feeds the money pages.
- **The facility page is the atom.** Every axis links back into it; it is the hub of the storage silo. The money pages (city x size, city x type) funnel to the facility page for the actual rental.

---

## 2. The storage candidate ceiling: the three-axis grid

The full storage page-space is the product of four axes crossed with geography. This is the ceiling of what COULD exist, never the plan.

| Axis | Members (from `brand.yaml.storage`) | Becomes a money page when crossed with |
|---|---|---|
| **Facility (where)** | each real staffed building (`locations[]`, or the single facility) | is itself the geo node |
| **Unit-size (how big)** | `storage.unit_sizes[]` - 5x5, 5x10, 10x10, 10x15, 10x20, 10x30 | a city ("10x10 storage units [city]") |
| **Storage-type (what kind)** | `storage.storage_types[]` - climate-controlled, drive-up, indoor, outdoor, vehicle/RV/boat/car, business, wine, document | a city ("climate controlled storage [city]") |
| **Audience (for whom)** | `storage.audiences[]` - student, military, business | a campus / base / city ("student storage near [University]") |

Plus the non-grid page types every site needs: homepage, city hub + state hub (multi-facility), the informational size-guide and cost-guide ASSETS, the service-area/cities-served page, About, FAQ, Contact.

**The grid is the ceiling; three filters reduce it (per `topical-map-protocol.md`):** the demand filter (a real autocomplete/PAA/ranking-competitor signal), the user-cluster merge (behaviorally-identical geographies/sizes collapse into one node), and the evidence gate (Section 5). What remains is the map.

---

## 3. The storage keyword cluster library (the grid's columns)

The canonical storage query network, from `02-keyword-clusters.md`. Each cluster maps to a dominant intent and the ONE page type it wants. This is the storage replacement for the generic modifier grid in `keyword-research-method.md` section 3; use it as the candidate-expansion source, then demand-filter and evidence-gate.

| Cluster | Representative queries | Dominant intent | Page type it wants | Localizes on | Promote-to-page gate |
|---|---|---|---|---|---|
| **A. Head / near-me / [type] [city]** | storage units near me, self storage [city], storage units [city], cheap storage [city] | transactional-local | **facility / location page** | city | always (core node) |
| **B1. Size-in-city** | 10x10 storage units [city], 5x10 storage [city], 10x20 storage [city] | transactional-local | **unit-size page** (money) | city + size | real inventory in that size |
| **B2. Size guide / what-fits** | storage unit sizes, what fits in a 10x10, 10x10 vs 10x15 | informational | **size-guide asset** | brand-wide | one hub, always |
| **C. Type: climate / drive-up / indoor / outdoor** | climate controlled storage [city], drive up storage near me, indoor storage units | commercial + transactional-local | **storage-type page** (money) | city (facet) | real inventory of that type |
| **C-alt. Type comparisons** | climate controlled vs drive up, indoor vs outdoor | informational | **comparison asset** | none | one per comparison, as needed |
| **D. Vehicle: RV / boat / car / motorcycle** | RV storage near me, boat storage [city], covered RV storage, enclosed vehicle storage | transactional-local | **storage-type (vehicle) page** | city + vehicle | real vehicle inventory (covered/uncovered/enclosed is an attribute, not a page each) |
| **E. Specialty: business / wine / document** | business storage near me, commercial storage, document storage [city], wine storage | commercial + transactional-local | **audience (business) + specialty-type page** | city | business: usually; wine/doc: only if truly offered |
| **F. Audience: student / military** | student storage near [University], college summer storage, military storage, PCS/deployment storage | commercial + transactional-local (seasonal/event) | **audience page** | campus / base | near a real anchor institution |
| **G1. Cheap / first-month-free [city]** | cheap storage units near me, first month free storage [city], $1 storage unit | transactional-local | **deal / facility facet** | city | a live, real offer (Law 20 / SS-6) |
| **G2. Storage prices / how much** | how much does a storage unit cost, storage unit prices | informational | **cost-guide asset** | none | one hub, always |
| **H. Access / feature** | 24 hour storage near me, drive up storage, month to month storage, ground floor unit | transactional-local | **feature facet or attribute** | city | attribute by default; page only for 24hr / drive-up with real inventory |
| **I. Informational / asset** | what not to store in a storage unit, how to pack a storage unit, pods vs storage unit, how do storage auctions work | informational | **asset / FAQ** | none | as the asset calendar allows |
| **J. Brand / navigational** | [brand], [brand] [city], [brand] login / pay bill | navigational | **own homepage / account only** | brand | own brand only; competitor brand = honest comparison asset, never a doorway |

**The three storage rules the cluster library encodes** (`02-keyword-clusters.md` section 5):
1. **The unit-size dual node (Cluster B).** One brand-wide size-guide asset (B2) AND per-city size-facet money pages (B1); never let the facet exist without real per-facility availability. This is the sharpest doorway risk in the vertical.
2. **A storage-type node FAMILY, not one "types" page (Clusters C, D, E).** Climate-controlled, drive-up, indoor, outdoor, plus the vehicle family, each a node gated on real inventory. Covered/uncovered/enclosed and month-to-month/ground-floor are attributes, not pages.
3. **Audience nodes localize on the anchor institution (Cluster F).** Student-near-[university] and military-near-[base] are an independent's most defensible facets; brief them to the campus/base, not just the city, and lead with the seasonal/event trigger.

---

## 4. The two page types most often confused (storage edition)

- **Unit-size page vs size-guide asset.** The size-guide asset (B2) is informational, brand-wide, and earns links/citations - built by `/write-local-asset`. The unit-size page (B1) is a transactional per-city money page with real local inventory - built by `/write-unit-size-page`. Same "what fits" content, different node and different command. See `unit-size-page.md` section 1.
- **Cost-guide asset vs cheap-storage facet.** The cost-guide (G2) is informational (needs original dated data) - `/write-local-asset`. The cheap-storage / first-month-free facet (G1) is transactional and must mirror a real live offer (SS-6, Law 20) - it is a facet of the facility/city page, not its own thin page.

---

## 5. Promotion evidence by storage page type (the evidence gate, specialized)

This is the storage row for the `topical-map-protocol.md` "promotion evidence by vertical" table. Every node defaults to `index-only`; promote to `page` only when the facility has the un-copyable specific that page alone carries:

| Node (page type) | Promotion evidence (the un-copyable first-party specific) |
|---|---|
| Facility / location page | a real staffed building with its own NAP + GBP, its own live/dated unit board, and a unique "About This Facility" local block naming real nearby roads/landmarks |
| City hub (multi-facility) | 2+ real facilities in the city AND unique city prose (population, named neighborhoods, local use-cases) |
| Unit-size page (city x size) | real available inventory + a real price for that size at a real facility in that city, plus one first-party local reason that size is in demand there |
| Storage-type page (city x type) | real inventory of that type in that city AND the facility's own held spec (real climate range, real drive-up/indoor mix) - not a restated national definition |
| Audience page (student / military / business) | a real anchor institution nearby (named campus/base) or real business-inventory customers, audience-specific pricing, and 2-3 concrete scenarios |
| Size-guide / cost-guide asset | original, dated, sourced data (the operator's own market/rate data or a clearly-sourced original cut) - never a recycled round-number range |
| Service-area / cities-served page | real granular coverage (named small towns/landmarks) or a real facility directory - not a city-link carpet |

A node whose only available "evidence" is a restated definition, a generic what-fits paragraph, or a swapped city noun stays `index-only`. That is not a page; it is a doorway waiting to be caught (SS-DOORWAY, G3).

---

## 6. The two structural rules unique to storage

### 6a. The single-facility collapse rule

If `brand.yaml.storage.operator_type == single_facility`, the ENTIRE geo/axis hierarchy collapses into the homepage. The homepage IS the facility page; unit sizes and storage types are shown as SECTIONS on that page, never as separate indexable pages (verified: packitup.us). Do NOT generate separate unit-size, storage-type, city, or audience pages for a one-location client - each would be thin by construction and a doorway cohort of one skeleton. A single-facility map is: homepage-as-facility (core), About, FAQ, Contact, and at most one informational asset (a size guide) if the operator has a real reason to own it. That is the whole map.

### 6b. The axis-page doorway cap (multi-facility)

The multi-facility grid is where index-bloat lives. Guard it the same way the protocol caps index-only city lists:
- **Tie every axis page to real inventory, not a keyword slot.** A size-in-city or type-in-city page exists only where that facility genuinely stocks that size/type in that city.
- **Merge behaviorally-identical nodes.** If "10x10 storage [city]" and "10x10 storage [adjacent suburb]" draw the same SERP and the same facilities, they are one node, one page.
- **Cap the index-only coverage list.** A service-area or city hub renders at most a human-scannable set (~15-25) of index-only facet links, grouped; beyond that, excess nodes stay in the map but are linked nowhere until they earn promotion (a coverage list that grows unbounded is itself the thin-content pattern one level up).
- **Run `scripts/duplication_gate.py` across the axis cohort** (all the size pages, all the type-in-city pages) before publishing; a near-duplicate pair fails.

---

## 7. Page-type to command mapping (storage)

The storage extension of `keyword-research-method.md` section 9. Node selection is gated by the evidence gate above, not by this mapping alone.

| Cluster shape | Page type | Command |
|---|---|---|
| Head / near-me / [type] [city]; the facility in a city | facility / location page | `/write-location-page` (with the self-storage overlay) |
| One service/type across the brand ("climate controlled storage") | storage-type page (brand-wide service) | `/write-service-page` |
| One type in one city ("climate controlled storage [city]") | storage-type money page | `/write-service-city-page` |
| One size in one city ("10x10 storage units [city]") | **unit-size page** | `/write-unit-size-page` |
| Audience in a place ("student storage near [University]") | audience page | `/write-service-page` or `/write-service-city-page` (localized to the anchor) |
| Coverage across served areas / cities served | service-area page | `/write-service-area-page` |
| Head term + brand + primary category (entity anchor) | homepage | `/write-homepage` |
| Owner/manager, credentials, "[brand] reviews" | about page | `/write-about-page` |
| Size guide, cost guide, prohibited-items, pods-vs, neighborhood guide | linkable asset | `/write-local-asset` |
| Real customer questions as extractable answers | FAQ page | `/write-faq-page` |

Single-facility clients use only `/write-homepage` (+ optional `/write-about-page`, `/write-faq-page`, `/write-local-asset`); the axis commands are for multi-facility / large-footprint operators.

---

## 8. How the architect and the researcher use this

- **`topical-map-architect` (PLAN):** after loading `brand.yaml`, if `vertical == self-storage`, read this file. Build the candidate ceiling from the four axes x `service_areas` (optionally seeded by `scripts/storage_cluster_seed.py`, which expands `storage.unit_sizes` x `storage.storage_types` x `storage.audiences` x `service_areas` into the candidate list - a CANDIDATE generator, never the map). Apply the demand filter, the user-cluster merge, and the storage evidence gate (Section 5). Apply the collapse rule (6a) first: a single-facility client gets the collapsed map, full stop. Classify core (facility, unit-size, storage-type, audience money pages, homepage) vs outer (assets, About, FAQ, service-area). Write `clients/<slug>/topical-map.md`.
- **`keyword-intent-researcher` (RESEARCH, per node):** use the cluster library (Section 3) to classify the node's intent and confirm the page type, then read the live SERP for the node (local pack + national brand facet + directory listing) and extract what the ranking pages conspicuously lack (real per-facility inventory + a first-party local detail - the win condition).

---

## 9. The four storage traps (do not do these)

1. **Do not build the full grid as pages.** Facility x size x type x audience x geography is a huge ceiling; most cells stay `index-only`. The map's existence is the doorway risk; the evidence gate is the whole defense.
2. **Do not spin axis pages for a single-facility client.** The collapse rule (6a) is absolute. One facility, one deep page.
3. **Do not let a size-in-city or type-in-city page ship without real inventory.** The Storage King Dallas-vs-Tallahassee doorway pair and the Public Storage programmatic "10x10 near [city]" pages are the live proof of what this prevents.
4. **Do not score the map.** No coverage %, no "topical authority" number (topical-map-protocol trap #2 / Law 8). Map quality is the evidence gate, not the node count.

---

## Sources

- Internal research: `research/self-storage-2026-07/01-site-architecture.md` (taxonomy, silo, collapse rule, non-thin contracts), `02-keyword-clusters.md` (the full cluster map, intent, page-type mapping), `08-example-teardowns.md` (the doorway proofs).
- System: `knowledge/foundations/topical-map-protocol.md` (the node-selection spec this specializes), `knowledge/foundations/keyword-research-method.md` (the discovery engine), `knowledge/foundations/cluster-graph-protocol.md` (the link topology that wires the promoted nodes), `knowledge/playbooks/unit-size-page.md` (the dual-node split), `knowledge/verticals/self-storage.md` (SS-DOORWAY and the overlay), `scripts/storage_cluster_seed.py` (the candidate generator).

Re-read the live SERP per node before writing; storage prices, inventory, and SERP shape move constantly.
