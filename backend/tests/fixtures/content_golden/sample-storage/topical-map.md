# Topical Map - Anchor Self Storage (sample-storage)

Built by /build-topical-map (topical-map-architect) per knowledge/foundations/topical-map-protocol.md
+ knowledge/foundations/storage-topical-map.md. DEMONSTRATION map for a two-facility self-storage
operator, built in `lite` mode. All specifics trace to clients/sample-storage/brand.yaml +
sme-answers.md; [SAMPLE] where a value stands in for a real one.

Rules enforced: every node traces to a real capability/demand; the storage grid (facility x unit-size x
storage-type x audience x geography) is the CEILING, not this list; every node defaults index-only and is
promoted only on real first-party evidence (real inventory / a real operating fact); no coverage %, no score.
The candidate ceiling for this client is 57 nodes (see `scripts/storage_cluster_seed.py --brand ...`); the
evidence gate below promotes 8 and holds the rest.

---

## Entity anchor (from brand.yaml `entity`)

- **Map mode:** lite (2 facilities, ~12 candidate money pages that survive the demand filter, under the 25-page full-mode threshold)
- **Central entity:** Anchor Self Storage self-storage (brand + GBP primary category "Self-storage facility")
- **Source context:** two-facility independent operator (Round Rock + Pflugerville, TX); revenue from month-to-month unit rentals, the admin fee, and the tenant protection plan
- **Central search intent:** LOCAL-TRAN - a renter solving a life event (a move, a downsize) who wants a nearby unit now, plus an informational layer (what fits / how much)
- **Primary GBP category (head-term anchor):** Self-storage facility
- **Real footprint (from brand.yaml):** facilities = 2 (Round Rock, Pflugerville); unit_sizes = 5; storage_types = 4; audiences = 2; service_areas = 5
- **Storage grid ceiling:** 57 candidate nodes (LITE mode - not built as a formal artifact; the map below is the evidence-gated subset)
- **operator_type:** multi_facility (NOT single_facility, so the collapse rule does not apply; the facility, size, and type axes each produce real pages where evidence supports them)
- **Date built (PKT):** 2026-07-23

Multi-facility note: two real staffed buildings, each its own NAP + GBP + on-site manager. Each earns a facility/location page (the un-copyable evidence is the real building + its own security stack + its dated photos). Three served cities have NO staffed facility (Hutto, Georgetown, Wells Branch); they are index-only coverage on the service-area page, never thin per-city doorway pages (the axis-page doorway cap).

---

## Node table

Status: `index-only` = acknowledged coverage, linked but no dedicated URL yet. `page` = promoted, evidence-backed, gets built.
Section: `core` = converts, built first, link priority. `outer` = builds trust, funds the core.

| node_id | entity / attribute | section | page_type | target_query | intent | geography | status | priority | command |
|---|---|---|---|---|---|---|---|---|---|
| homepage | Anchor Self Storage (entity anchor) | core | homepage | anchor self storage round rock | NAV / LOCAL-TRAN | brand-wide | page | 1 | /write-homepage |
| facility-round-rock | biz + Round Rock building | core | location | storage units round rock | LOCAL-TRAN | Round Rock | page | 2 | /write-location-page |
| facility-pflugerville | biz + Pflugerville building | core | location | storage units pflugerville | LOCAL-TRAN | Pflugerville | page | 3 | /write-location-page |
| climate-round-rock | biz + climate-controlled | core | service-city | climate controlled storage round rock | LOCAL-TRAN / COMM | Round Rock | page | 4 | /write-service-city-page |
| size-10x10-round-rock | biz + 10x10 | core | unit-size | 10x10 storage units round rock | LOCAL-TRAN | Round Rock | page | 5 | /write-unit-size-page |
| about-team | biz + CSSM manager | outer | about-team | anchor self storage owner / manager | LOCAL-COMM / NAV | brand-wide | page | 6 | /write-about-page |
| size-guide-asset | biz + what-fits guide | outer | local-asset | storage unit sizes / what fits in a 10x10 | INFORMATIONAL | brand-wide | page | 7 | /write-local-asset |
| service-area | biz + coverage | outer | service-area | self storage near [served towns] | LOCAL-TRAN | multi-city | page | 8 | /write-service-area-page |
| climate-pflugerville | biz + climate-controlled | core | service-city | climate controlled storage pflugerville | LOCAL-TRAN / COMM | Pflugerville | index-only | - | /write-service-city-page |
| size-10x10-pflugerville | biz + 10x10 | core | unit-size | 10x10 storage units pflugerville | LOCAL-TRAN | Pflugerville | index-only | - | /write-unit-size-page |
| vehicle-round-rock | biz + vehicle/RV/boat | core | service-city | rv storage round rock | LOCAL-TRAN | Round Rock | index-only | - | /write-service-city-page |
| student-storage | biz + student audience | core | service-page | student storage near [campus] | LOCAL-COMM (seasonal) | near a campus | index-only | - | /write-service-page |
| business-storage | biz + business audience | core | service-page | business storage round rock | LOCAL-COMM | brand-wide | index-only | - | /write-service-page |
| size-5x5..10x20 (x8) | biz + other sizes x city | core | unit-size | [size] storage units [city] | LOCAL-TRAN | per facility | index-only | - | /write-unit-size-page |
| facility-hutto/georgetown/wells-branch | biz + unserved city | core | (none) | storage units [city] | LOCAL-TRAN | no facility | index-only | - | (coverage line on service-area) |

---

## Per-node detail (promoted nodes)

### homepage
- **Section / command:** core - `/write-homepage`
- **Target query:** anchor self storage round rock (+ "self storage round rock" as the entity's primary category query)
- **Query network:** anchor self storage, anchor storage round rock/pflugerville, self storage round rock, storage units near me
- **Intent:** NAV / LOCAL-TRAN
- **Demand trace:** brand_terms + GBP primary category "Self-storage facility" + "self storage round rock" head query
- **Evidence (promotion gate):** two real staffed facilities; live PMS pricing; named CSSM manager (Dana Reyes); 28 recorded cameras; 1,240+ days break-in-free (since 2021-03-14); climate held 55-80F with dehumidification
- **Info-gain thesis:** an independent whose homepage is a wall of provable facts (live prices, a dated break-in-free counter, a named on-site CSSM), where the national brands run generic copy
- **Status:** page - **Priority:** 1

### facility-round-rock
- **Section / command:** core - `/write-location-page`
- **Target query:** storage units round rock
- **Intent:** LOCAL-TRAN
- **Evidence:** real staffed building at 2100 N Mays St, Round Rock 78664; own GBP + phone (512) 555-0148; on-site manager Dana Reyes (CSSM); dated gate/keypad + climate-hallway photos (2026-06); live per-size inventory; a unique local block (near N Mays St / I-35 corridor, Round Rock)
- **Info-gain thesis:** the N Mays Street building with its own manager, its own camera count, and its own live board - not a national grid cell
- **Status:** page - **Priority:** 2

### facility-pflugerville
- **Section / command:** core - `/write-location-page`
- **Target query:** storage units pflugerville
- **Evidence:** real staffed building at 18601 FM 685, Pflugerville 78660; own GBP + phone (512) 555-0172; live per-size inventory; its own local block (FM 685 / Pflugerville). Must be substantially different from the Round Rock page (duplication_gate.py across the two facility pages).
- **Info-gain thesis:** the FM 685 building; its own hours, manager coverage, and local access notes
- **Status:** page - **Priority:** 3

### climate-round-rock
- (This is the money page built end-to-end as the demo package in output/sample-storage/.)
- **Section / command:** core - `/write-service-city-page` (storage-type x city)
- **Target query:** climate controlled storage round rock
- **Intent:** LOCAL-TRAN / COMM
- **Evidence:** real climate inventory at the Round Rock building; the facility's OWN held range (55-80F) with dehumidification (humidity_control true, so the honest moisture lever is available, SS-5); live price for climate units; the honesty lever ("climate controlled" is unregulated, here is what we actually control)
- **Info-gain thesis:** the operator's real 55-80F + dehumidification spec and the unregulated-term honesty, where the Storage King-style doorway pages restate a national definition
- **Status:** page - **Priority:** 4

### size-10x10-round-rock
- **Section / command:** core - `/write-unit-size-page`
- **Target query:** 10x10 storage units round rock
- **Intent:** LOCAL-TRAN
- **Evidence:** real available 10x10 inventory + live price at the Round Rock building; the honest what-fits (a one-bedroom apartment, ~100 boxes); a local reason 10x10 is in demand (apartment turnover along the I-35 corridor); climate + drive-up 10x10 both offered
- **Info-gain thesis:** the real Round Rock 10x10 rate + an honest capacity, vs the programmatic "10x10 near [city]" doorway
- **Status:** page - **Priority:** 5

### about-team
- **Section / command:** outer - `/write-about-page`
- **Evidence:** Dana Reyes, CSSM (certified 2023-09), 6 years, runs the daily aisle walk and weekly thermostat check; family-owned since 2011; Texas Self Storage Association member. A named, credentialed human + a dated history (the StorageMart/Advantage model, not the A Family Storage "we're better" fail).
- **Info-gain thesis:** the named CSSM manager and the real founding story competitors do not put a face on
- **Status:** page - **Priority:** 6

### size-guide-asset
- **Section / command:** outer - `/write-local-asset` (the ONE informational size-guide asset)
- **Target query:** storage unit sizes / what fits in a 10x10
- **Evidence:** the operator's own what-fits knowledge (what actually fits each size, learned at the counter) + a real size diagram; bridges to the live per-city size money pages
- **Info-gain thesis:** an honest what-fits guide (the realistic box count, not the brochure maximum) tied to live local inventory
- **Status:** page - **Priority:** 7

### service-area
- **Section / command:** outer - `/write-service-area-page`
- **Evidence:** the two real facilities as a directory + honest coverage of Hutto, Georgetown, Wells Branch (drive-to, no staffed office there). Real granular local geography, not a city-link carpet.
- **Info-gain thesis:** honest coverage anchored to two real buildings, with the unserved towns acknowledged as coverage, not spun into thin pages
- **Status:** page - **Priority:** 8

---

## Held at index-only (SME homework / evidence gate, in priority order to promote)

- **climate-pflugerville, size-10x10-pflugerville** - real demand, but the Pflugerville building's live climate inventory + a Pflugerville-specific local reason must be confirmed before these promote (else they near-duplicate the Round Rock money pages; duplication_gate.py). Promote when the Pflugerville-specific specifics are documented.
- **vehicle-round-rock** - vehicle/RV/boat storage is offered, but real vehicle-space inventory (covered vs uncovered) and the dimensions must be confirmed; covered/uncovered is an attribute, not a page each.
- **student-storage** - waiting on the anchor institution: the nearest campus (Texas State Round Rock / ACC) and audience-specific pricing + a seasonal (spring move-out) scenario. Localize on the campus, not just the city.
- **business-storage** - waiting on real business-inventory customers and a concrete B2B scenario.
- **the other 8 size-in-city nodes (5x5, 5x10, 10x15, 10x20 x each facility)** - promote only where that size has real available inventory AND a first-party local reason; otherwise they stay index-only (the size grid is the sharpest doorway risk).
- **facility-hutto / georgetown / wells-branch** - NO staffed facility; they stay coverage lines on the service-area page. Promoting a facility page for a city with no building would be the doorway pattern the gate exists to prevent.

---

## Coverage reality (not a score)

- **Promoted (pages):** 8 nodes - homepage, the two real facilities, one climate money page + one 10x10 money page (Round Rock, where inventory and a local reason are documented), the about/CSSM page, the size-guide asset, and the service-area page. Each carries a first-party specific competitors cannot copy (the named CSSM manager, the dated break-in-free counter, the real 55-80F climate spec, the live per-size prices, the real buildings).
- **Held (index-only, awaiting evidence):** ~49 candidate nodes from the 57-node ceiling. Most are size-in-city and type-in-city cells whose real inventory + local reason are not yet documented, plus three unserved cities. This is the point: the grid is huge, the map is small and evidence-gated.
- **Next evidence step:** the SME interview should surface (1) the Pflugerville building's live climate/10x10 inventory + a Pflugerville-specific local reason, (2) the nearest campus + seasonal student pricing, (3) real vehicle-space dimensions and covered/uncovered inventory, (4) which other sizes have genuine available inventory. Supplying any promotes the corresponding node.
- **Levers this plan does NOT move:** proximity, GBP configuration (the two facilities' categories/services), and review velocity/recency - these dominate the local pack for storage but are not on-page content. Reviews -> `/write-review-requests` + `/write-review-responses`; GBP + proximity are operator work per facility. The map moves roughly a fifth of what decides local visibility; it says so rather than hiding the other four-fifths.
