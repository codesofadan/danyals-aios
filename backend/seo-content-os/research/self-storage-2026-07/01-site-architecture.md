# Self-Storage Site Architecture & Page-Type Taxonomy (US)

Research dossier 01 of the self-storage knowledge base. Market: United States. Compiled 2026-07-23 (PKT).

Method: live fetches of real operator sites this run. Where a page returned HTTP 403 (Extra Space and its Life Storage brand run bot protection that blocks WebFetch), the URL pattern is confirmed from live search result listings and the anatomy is reconstructed from a peer operator, and every such point is labelled a pattern, not a fetched fact. Every claim below carries its source URL inline.

---

## 0. TL;DR for the content system

A US self-storage site is built from roughly **13 page types**. The commercial core is a **three-axis grid**: facility (where) x storage-type (what kind) x unit-size (how big). The money page is the intersection of an axis with geography, e.g. "10x10 storage units in Las Vegas" or "climate controlled storage in Dallas". The taxonomy below gives each type a real example URL, its non-thin content contract, and the silo it links into.

Single-facility operators collapse the whole geo hierarchy into the homepage. Multi-facility operators expand it into state > city > facility, then multiply it by storage-type and unit-size axes to generate their page inventory (this is where index-bloat and doorway risk live).

---

## 1. Master page-type taxonomy

| # | Page type | Job | Real example URL | Scale (who builds it) |
|---|---|---|---|---|
| 1 | Homepage | Entity anchor + primary conversion | https://www.mygarageselfstorage.com/ | All |
| 2 | Facility / store page | Rank + convert for one physical location; NAP + live inventory | https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/224.html | All (single-facility = homepage) |
| 3 | City hub / "storage in {city}" | Aggregate all facilities in a market | https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/ | Multi-facility |
| 4 | State hub | Roll up all cities in a state | https://www.cubesmart.com/texas-self-storage/ | Multi-facility |
| 5 | National unit-size guide page | Inform "how big is a 10x20" | https://www.cubesmart.com/storage-resources/size-guide/10x20-storage-unit/ | Larger operators |
| 6 | City-level unit-size page (money page) | Rank "10x10 storage units {city}" | https://www.publicstorage.com/self-storage-nv-las-vegas/10x10-storage-units | Big operators |
| 7 | National storage-type hub | Inform "what is climate controlled storage" | https://www.cubesmart.com/storage/climate-controlled-storage/ | Larger operators |
| 8 | City-level storage-type page (money page) | Rank "climate controlled storage {city}" | https://www.extraspace.com/storage/facilities/us/california/sacramento/id/climate-controlled-storage/ (pattern) | Big operators |
| 9 | Facility-level storage-type page (silo bridge) | "climate controlled storage at {this store}" | https://myplaceselfstorage.com/storage-locations/tx/dallas/6434-maple-ave/dallas-climate-controlled-storage/ | Some multi-facility |
| 10 | Audience / use-case page | Rank + convert student / military / business / wine storage | https://www.aceself-storage.com/college-student-storage/ | All sizes |
| 11 | Size guide / calculator asset (interactive tool) | Capture "what size do I need" | https://www.storage-mart.com/self-storage/unit-size-guide | All sizes |
| 12 | Cost guide asset | Rank "how much does a storage unit cost" | https://www.storage.com/blog/how-much-does-a-storage-unit-cost/ | Big operators + aggregators |
| 13 | Trust/utility: About, FAQ, Contact, Blog | E-E-A-T + support | https://www.cubesmart.com/about-us/frequently-asked-questions/ | All |

Anchors for the table: Public Storage size-guide + city unit-size URLs from [publicstorage.com search listing](https://www.publicstorage.com/self-storage-nv-las-vegas/10x10-storage-units); Extra Space facility + city storage-type URLs from [extraspace.com search listing](https://www.extraspace.com/storage/facilities/us/missouri/st_louis/4042/); CubeSmart URLs verified by fetch below.

---

## 2. Each page type in detail

### 2.1 Facility / store page (the atom of the whole site)

Fetched: CubeSmart San Antonio, https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/224.html

H1: "CubeSmart Self Storage of San Antonio". H2/H3 blocks in order:
- Office Hours / Access Hours ("Daily: 6:00 AM-10:00 PM")
- Services at This Facility / Store Amenities (Handcarts/Dollies, Online Payments, Month-to-Month Leases, Delivery Acceptance, Climate Control, Drive-up access, 24-hour video surveillance)
- Moving and Storage Deals
- About This Facility (unique local content: names nearby St Luke's Baptist / Methodist / University Hospital, Lowe's, Sprouts, Six Flags, The Alamo)
- Select Your Storage Unit Below -> Small / Medium / Large Storage Units, each unit with online price, in-store price, and promo (e.g. 5x5 at $31.80/mo online; 10x20 at $119.25/mo)
- Reviews for this address
- Self storage FAQs

NAP block: "9238 I-10, San Antonio, TX 78230", separate new-customer vs current-customer phone numbers.

Non-thin contract for a facility page:
1. Full NAP + office hours + gate/access hours (distinct fields).
2. Live unit inventory with real prices, grouped by size class, online vs in-store price shown.
3. Amenities list specific to that building.
4. A genuinely local "About This Facility" paragraph naming nearby landmarks/roads (this is the doorway-defeating unique-value block).
5. Facility-specific reviews.
6. FAQ.
7. Internal links out to unit-size guides, storage-type pages, nearby facilities, the city hub and state hub (full list in section 5).

Source: fetch of https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/224.html

Extra Space facility URL pattern (403 on fetch, confirmed from search listing): `extraspace.com/storage/facilities/us/{state}/{city}/{facility-id}/`, e.g. https://www.extraspace.com/storage/facilities/us/missouri/st_louis/4042/ and `/us/missouri/st_louis/3874/`. Life Storage stores are being rebranded onto this same tree (rebrand began Aug 2024). Source: [extraspace.com / lifestorage.com search listing](https://www.extraspace.com/life-storage/).

U-Haul facility URL pattern: `uhaul.com/Locations/Self-Storage-near-{City}-{State}-{ZIP}/{FacilityID}/`, e.g. https://www.uhaul.com/Locations/Self-Storage-near-Kansas-City-KS-66102/734024/. Source: [uhaul.com search listing](https://www.uhaul.com/Locations/Self-Storage-near-Kansas-City-KS-66102/734024/).

### 2.2 City hub / "storage in {city}" page

Fetched: https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/

H1: "Find Self Storage in San Antonio, TX". Blocks:
- "14 storage facilities near San Antonio, TX" (list + map toggle, facility cards with star rating 4.1-5.0, distance, starting price, promo, pagination)
- City-specific intro paragraph (cites San Antonio ~1.5M population, names downtown, Lackland, Converse, southern suburbs, River access, climate concerns)
- Small / Medium / Large / Vehicle unit-size sections (lockers, 5x5, 5x10; 10x10, 10x15; 10x20, 10x30; vehicle)
- Self storage FAQs
- "Find Storage Facilities Near You" + "Featured Cities"

Non-thin contract: a city hub must carry city-unique prose (population, neighborhoods, local use-cases), the live facility list with map, and the size/type cross-links. Without the unique city block it is a doorway. Source: fetch of https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/

State hub sits one level up at `/texas-self-storage/` and rolls up cities (same source, breadcrumb + internal link).

### 2.3 National unit-size guide page

Fetched two, cross-referenced.

CubeSmart, https://www.cubesmart.com/storage-resources/size-guide/10x20-storage-unit/. H1 "10'x20' Storage Units". H2 order:
1. How big is a 10x20 storage unit? (10ft x 20ft x 8ft; 1600 cubic feet; "similar floor space to a one-car garage"; 22-foot moving truck)
2. What does a 10x20 look like?
3. What can I fit in a 10x20? (king bedroom sets, appliances, sectional couches, dining sets, exercise equipment, small-medium vehicles, motorcycles, boxes)
4. How do I find a 10x20 near me?
5. How much does a 10x20 cost?
6. Other available large storage unit sizes (H3: 10x30)
7. Why choose CubeSmart?
8. Storage tips and guides

Public Storage, https://www.publicstorage.com/size-guide/10x10-storage-unit/10x10-storage-unit.html. H1 "10x10 Storage Unit FAQ". H2: Sizes & Types; Items; Prices; Other Storage Unit Sizes; Explore Other Resources. Hard specifics present: "10 feet wide and 10 feet long, totaling 100 square feet", 8-foot ceilings, "800 cubic feet"; "about the size of a large shed or half the size of a one-stall garage"; "items from up to three rooms"; box-count math ("144 boxes... 100 boxes is more realistic"); item lists organized by room (bedroom, living room, kitchen, business, garage). Sources: fetches of the two URLs above.

### 2.4 City-level unit-size page (a money page)

Fetched: https://www.publicstorage.com/self-storage-nv-las-vegas/10x10-storage-units

H1: "10x10 Storage Units Near You in Las Vegas, NV". Breadcrumb Home > Locations > United States > Nevada > Las Vegas > 10x10 Storage Units. Body = 7 real facilities with photos, addresses, distance, starting prices ($20-$58/mo on featured units), one-time $29 admin fee, per-facility unit options (5x5, 8x10, 10x10, 10x14, 10x15, 15x10), promos ("$1 First Month Rent Where Available", "First month 50% off"). "Not sure what size you need?" cross-link to the Size Guide. No dedicated FAQ.

Read: this page type is the intersection of the unit-size axis and the city geo node. It ranks for "[size] storage units [city]" and converts by listing local inventory. Source: fetch of the URL above.

### 2.5 National storage-type hub page

Fetched: https://www.cubesmart.com/storage/climate-controlled-storage/. H1 "Climate Controlled Storage Units". H2/H3:
- Do I Need a Climate Controlled Storage Unit?
- Benefits of Climate Controlled Storage
- Climate Controlled Storage Unit Types (H3: Climate Controlled / Air-Cooled or Evaporative / Heated)
- Common Climate Controlled Storage Unit Sizes (H3: 5x5, 5x10, 10x20)
- Climate Controlled Storage Tips (H3: Preparing / Packing / Moving)
- Climate Controlled Storage FAQs (H3 Q&A)
- Find Storage Facilities Near You (city links)

Hard specifics: definition "maintain a temperature... between 55 and 80 degrees Fahrenheit"; three system types explained; sensitive-item list (cameras, vinyl records, musical instruments, wood furniture, electronics). Internal links to city pages (Bronx, Brooklyn, Houston, LA, Phoenix), unit sizes, and sibling types (business, RV). Source: fetch of the URL above.

Big-operator storage-type URL vocabularies seen in the wild:
- Public Storage: `/self-storage/drive-up-storage`, `/business-storage`, `/business-storage/vehicle`, `/business-storage/faqs`. Source: [publicstorage.com search listing](https://www.publicstorage.com/business-storage).
- Storage Star: `/storage-type/business-storage`. Source: [storagestar.com listing](https://www.storagestar.com/storage-type/business-storage).
- Security Public Storage: `/storage-types` index. Source: [securitypublicstorage.com listing](https://www.securitypublicstorage.com/storage-types).
- Extra Space storage-type taxonomy: self, 24-hour, business, vehicle & RV, boat, climate controlled, drive-up, indoor. Source: [publicstorage.com storage-type listing](https://www.publicstorage.com/) and Extra Space feature listings.

### 2.6 City-level storage-type page (a money page)

Pattern (Extra Space fetch 403; URL confirmed from search listing): `extraspace.com/storage/facilities/us/{state}/{city}/id/climate-controlled-storage/`, e.g. https://www.extraspace.com/storage/facilities/us/california/sacramento/id/climate-controlled-storage/ and `/us/new_york/new_york/id/climate-controlled-storage/`. Note "(from $19)" / "(from $26)" price teasers in the title tags. This is the storage-type axis crossed with the city geo node. Source: [extraspace.com search listing](https://www.extraspace.com/storage/facilities/us/california/sacramento/id/climate-controlled-storage/).

### 2.7 Facility-level storage-type page (the silo bridge)

Fetched (partial - single H1 title page): https://myplaceselfstorage.com/storage-locations/tx/dallas/6434-maple-ave/dallas-climate-controlled-storage/. URL silo = `storage-locations / {state} / {city} / {street-address} / {city}-{storage-type}-storage/`. It is a hybrid: the climate-controlled view of one specific store, bridging the store's main page and the national climate-controlled hub. This is the tightest silo form and the one most prone to thin-content risk if it only re-states the type definition. Source: fetch of the URL above.

### 2.8 Audience / use-case page

Fetched: https://www.aceself-storage.com/college-student-storage/ (independent, ~6 locations). H1 "College Student Storage". H2 blocks: Storage Units for College Students in San Diego; Deals on Student Storage Units; Why Choose Ace; Newest Facility; Check Available Units; Reviews; College Student Storage FAQ; Self Storage Near You; Storage Locations; Other Types of Self Storage. Audience specifics: move-in specials ("5x5: $15 | 5x10: $29 | 10x10: $39"), summer storage, semester flexibility, dorm/apartment furniture, month-to-month. Their "Special Offers" menu is an audience hub: Military, Business, College Student, Summer, Short Term, Moving Boxes. Source: fetch of the URL above.

Big-operator audience pages: Extra Space military storage at `/self-storage/storage-tips/military-storage/` (403 on fetch; URL from search); student/military/business framed inside `/self-storage/`. Source: [extraspace.com search listing](https://www.extraspace.com/self-storage/storage-tips/military-storage/). Public Storage business storage at `/business-storage` with `/business-storage/faqs`. Source: [publicstorage.com listing](https://www.publicstorage.com/business-storage).

Non-thin contract for an audience page: audience-specific pricing/discount, 2-3 concrete scenarios (deployment/PCS move, summer break, business inventory), what-to-store list for that audience, and an FAQ answering that audience's actual objections. A generic "we have storage for students" block is thin.

### 2.9 Size guide / calculator asset (interactive tool)

Fetched: https://www.storage-mart.com/self-storage/unit-size-guide. H1 "Self Storage Calculator". Interactive item-picker with category tabs (Appliances, Automotive, Bedroom, Boxes & Totes, Electronics, Home Goods, Kitchen, Living Room, Musical Instruments, Office, Outdoor, Sporting) and increment/decrement item counters that drive a visual unit diagram. Below the tool, six size-class cards (Closet <6ft, 5-50 sq ft; Small up to 80; Medium 81-150; Large 151-300; XL 301+; Parking 18-38ft) with sample contents. Source: fetch of the URL above.

The tool market is real and worth naming: Extra Space "AI Smart Size Finder" (photo-to-inventory) at https://www.extraspace.com/self-storage/ai-smart-size-finder/; Storage Sense calculator https://www.storagesense.com/storage-calculator/; Modern Storage https://www.modernstorage.com/self-storage-calculator; and Calcumate, a third-party 3D size-guide widget vendor https://calcumate.co/en/. Source: [calculator search listing](https://www.extraspace.com/self-storage/ai-smart-size-finder/).

### 2.10 Cost guide asset

Fetched: https://www.storage.com/blog/how-much-does-a-storage-unit-cost/. H1 "Self-Storage Pricing Guide: How Much Does It Cost To Rent A Storage Unit?". H2: Pricing by Size and Market; Location; Climate Control; Structure Type; Security; Rental Agreement; Is Self-Storage Worth the Cost. Contains a price-by-size x market-tier table and hard numbers (see section 6). Source: fetch of the URL above.

### 2.11 Trust / utility pages

FAQ hub at `/about-us/frequently-asked-questions/`, Contact at `/about-us/contact-us/` (CubeSmart, from facility-page footer links). About pages are E-E-A-T surfaces. These are present on operators of every size. Source: fetch of https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/224.html footer.

---

## 3. Single-facility vs multi-facility architecture

Fetched a genuine single-location operator: Pack-It-Up Self Storage, one facility in Kings Mountain, NC, https://packitup.us/.

Single-facility collapse (verified):
- The homepage IS the facility page. NAP inline ("115 Bethlehem Rd, Kings Mountain, NC 28086", (704) 349-7926), office hours, gate hours ("6 AM - 10 PM") all on the homepage.
- Unit sizes are shown as a section on the homepage (5x10, 10x10, 10x15, 10x20 with "typical fits"), NOT as separate indexable pages.
- No state/city hub, no separate storage-type pages, no size-guide page. Storage-type and audience needs (business/vehicle) are handled as feature boxes on the one page.
- Sections are: hero, gallery, unit-size table, specials, 3-step move-in (Storable-powered), why-choose-us, FAQ (5 Q&A), contact form, footer.
Source: fetch of https://packitup.us/.

Multi-facility expansion:
- The geo hierarchy exists as real pages: state hub > city hub > facility page. CubeSmart shows all three (`/texas-self-storage/` > `/san-antonio-self-storage/` > `/224.html`). Source: CubeSmart fetches above.
- Mid-size independents run the same shape with a flatter URL. My Garage Self Storage (~19 TX locations) uses `mygarageselfstorage.com/storage-units/{state}/{city}/{facility-name}`, e.g. `/storage-units/texas/belton/i-35`, with a nav of Find Storage / Storage Types (Business, Climate Controlled, Personal, Vehicle) / Resources (FAQ, Smart Units, Protection Plans, Size Guide) / About / Contact. Homepage does NOT double as a facility page here. Source: fetch of https://www.mygarageselfstorage.com/.
- Ace Self Storage (~6 locations) proves independents also build the storage-type and audience axes (50+ storage-type variants, a "Special Offers" audience hub). Source: fetch of https://www.aceself-storage.com/college-student-storage/.

Rule of thumb for the content system:
- 1 location: build ONE deep page (the homepage-as-facility) plus optional About/FAQ/Contact. Do not spin up separate size or type pages - there is nothing local to differentiate them and they become thin.
- 2-15 locations: build facility pages + a light city hub if 2+ stores share a city; add storage-type and audience pages only where the operator genuinely offers and can prove that type/serves that audience.
- 15+ / big operator: full state > city > facility geo tree, multiplied by unit-size and storage-type axes at the city level. This is where doorway/duplication defenses (unique local block per facility, unique city prose per hub) become mandatory.

---

## 4. Exact non-thin content contracts (the two hardest page types)

### 4.1 Unit-size page must contain (union of CubeSmart + Public Storage specs)

1. Exact dimensions in feet AND derived area/volume: "10 x 20 x 8 ft = 1600 cubic feet" (CubeSmart) / "100 square feet ... 800 cubic feet" (Public Storage).
2. A physical-world equivalent: "one-car garage", "large shed", "half a one-stall garage".
3. A recommended moving-truck size: "22-foot moving truck" (CubeSmart 10x20).
4. A concrete what-fits inventory, ideally grouped by room (bedroom / living room / kitchen / business / garage) - not adjectives, actual item lists.
5. A box-count estimate with an honesty hedge ("144 boxes... 100 is more realistic" - Public Storage).
6. Price context (a "how much does it cost" block) and a "find one near me" locator CTA.
7. Up/down cross-links to the adjacent sizes (10x20 links 10x15 and 10x30).
8. A visual: photo or video of the actual size (CubeSmart embeds video per size).

Sources: https://www.cubesmart.com/storage-resources/size-guide/10x20-storage-unit/ ; https://www.publicstorage.com/size-guide/10x10-storage-unit/10x10-storage-unit.html

### 4.2 Storage-type page must contain (CubeSmart climate-controlled spec)

1. A precise definition with a number: climate control = "maintain a temperature... between 55 and 80 degrees Fahrenheit".
2. A "do I need this?" decision block (long-term storage, extreme local climate, humidity-sensitive items).
3. The sub-types of the type (climate-controlled vs air-cooled/evaporative vs heated).
4. A specific sensitive-item list (cameras, vinyl, instruments, wood furniture, electronics).
5. Common sizes this type comes in (cross-link to unit-size pages).
6. Preparation/packing/moving tips.
7. A cost note relative to standard (see section 6: ~10-30% premium).
8. Type-specific FAQ.
9. Links to city-level instances of this type and to sibling types.

Source: https://www.cubesmart.com/storage/climate-controlled-storage/

---

## 5. Internal-linking / silo model

Observed linking out of a single facility page (CubeSmart San Antonio 224.html):
- UP the geo silo: city hub (`/san-antonio-self-storage/`) and state hub (`/texas-self-storage/`).
- SIDEWAYS to nearby facilities (New Braunfels, Schertz, Live Oak).
- ACROSS to the unit-size axis: national size-guide pages (5x5, 10x10, 10x30 at `/storage-resources/size-guide/...`).
- ACROSS to the storage-type axis: national type hubs (climate-controlled, vehicle, boat at `/storage/{type}-storage/`).
- To utility: Size Guide, FAQs, Contact.
Source: fetch of https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/224.html

The three-axis silo model that emerges:

```
                 STATE HUB  (/texas-self-storage/)
                     |
                 CITY HUB  (/san-antonio-self-storage/)  <-- unique city prose + facility list
                   / | \
   facility A   facility B (/224.html)   facility C   <-- unique local block each
                    /   |   \
      unit-size axis  type axis  audience axis
      (national guides) (nat hub -> city page -> facility-type page)  (student/military/business)
```

- The unit-size axis is mostly informational at the national level (`/size-guide/10x10...`) but becomes a money page when crossed with a city (`/self-storage-nv-las-vegas/10x10-storage-units`, Public Storage).
- The storage-type axis has three depths: national hub -> city-level type page -> facility-level type page (MyPlace `/storage-locations/tx/dallas/{address}/dallas-climate-controlled-storage/`). Each deeper node must add local specificity or it is a doorway.
- Facility pages are the hub every axis links back into; the money pages (city x size, city x type) funnel to facility pages for the actual rental.

Silo discipline that keeps this penalty-proof: every facility page carries a genuinely unique "About This Facility" block naming local roads/landmarks; every city hub carries unique city prose (population, neighborhoods, local use-cases); the type/size pages differentiate by real local inventory and price, not restated definitions.

---

## 6. Key numbers harvested (each with source, for the cost-guide + calculator page types)

- US national average, 10x10 unit, 2026: **$81.70/mo**; all-units current average ~$89.09/mo (May 2026). Source: [storage.com pricing guide](https://www.storage.com/blog/how-much-does-a-storage-unit-cost/) and [extraspace cost guide listing](https://www.extraspace.com/blog/self-storage/how-much-do-storage-units-cost/).
- Price-by-size national averages: 5x5 ~$35.58; 10x10 ~$81.70; 20x20 ~$230.25. Source: [storage.com pricing guide](https://www.storage.com/blog/how-much-does-a-storage-unit-cost/).
- SpareFoot range framing: 5x5 ~$40-60/mo; 10x20 ~$140-250/mo; 10x30 averages ~$316. Source: [sparefoot cost guide listing](https://www.sparefoot.com/blog/how-much-does-a-storage-unit-cost).
- Location swing: same 10x10 ~$219 in Los Angeles vs ~$80 in Houston. Source: [sparefoot / storage.com listings](https://www.storage.com/blog/how-much-does-a-storage-unit-cost/).
- Climate-controlled premium: ~15-30% over standard (storage.com says 15-30%; Extra Space/Yelp framing 10-20%). Source: [storage.com pricing guide](https://www.storage.com/blog/how-much-does-a-storage-unit-cost/) and [extraspace climate rates listing](https://www.extraspace.com/blog/self-storage/your-guide-to-climate-controlled-storage-rates/).
- Indoor-access units can cost up to ~50% more than drive-up outdoor. Source: [storage.com pricing guide](https://www.storage.com/blog/how-much-does-a-storage-unit-cost/).
- Unit dimensions/volume: 10x10 = 100 sq ft / 800 cu ft; 10x20 = 200 sq ft / 1600 cu ft, "one-car garage". Source: [cubesmart 10x20](https://www.cubesmart.com/storage-resources/size-guide/10x20-storage-unit/) and [publicstorage 10x10](https://www.publicstorage.com/size-guide/10x10-storage-unit/10x10-storage-unit.html).
- Climate-control definition: temperature maintained 55-80 F. Source: [cubesmart climate-controlled](https://www.cubesmart.com/storage/climate-controlled-storage/).

Note: these are national-aggregate figures for reference and for the cost-guide page type only. Per the system's iron law, any client page must use the client's own real prices from brand.yaml/SME, never these averages.

---

## 7. URL pattern cheat-sheet (real, per operator)

| Operator | Facility | City hub | Unit-size (money) | Storage-type | Size guide |
|---|---|---|---|---|---|
| Public Storage | (within city path) | `/self-storage-{st}-{city}/` | `/self-storage-{st}-{city}/10x10-storage-units` | `/self-storage/drive-up-storage`, `/business-storage`, `/business-storage/vehicle` | `/size-guide/10x10-storage-unit/10x10-storage-unit.html` |
| Extra Space (+Life Storage) | `/storage/facilities/us/{state}/{city}/{id}/` | (facilities index) | (n/a - size handled in guide) | `/storage/facilities/us/{state}/{city}/id/climate-controlled-storage/`; audience `/self-storage/storage-tips/military-storage/` | `/self-storage/storage-unit-size-guide/` |
| CubeSmart | `/{state}-self-storage/{city}-self-storage/{id}.html` | `/{state}-self-storage/{city}-self-storage/` | (via size guide) | `/storage/climate-controlled-storage/`, `/storage/vehicle-storage/`, `/storage/boat-storage/` | `/storage-resources/size-guide/10x20-storage-unit/` |
| U-Haul | `/Locations/Self-Storage-near-{City}-{ST}-{ZIP}/{id}/` | `/Storage/{City}-{ST}/Results/` | (via size guide) | `/Storage/Climate-Controlled-Storage/` | `/Storage/Self-Storage-Unit-Size-Guide/` |
| MyPlace (multi-facility indie) | `/storage-locations/{st}/{city}/{address}/` | `/storage-locations/{st}/{city}/` | (n/a) | facility-level: `/storage-locations/{st}/{city}/{address}/{city}-climate-controlled-storage/` | site size guide |
| My Garage (mid indie) | `/storage-units/{state}/{city}/{facility-name}` | `/storage-units/{state}/{city}/` | (n/a) | `/` Storage Types nav: Business/Climate/Personal/Vehicle | `/` Resources: Size Guide |
| Ace (small indie) | location pages | per-location | size guides 5x5-10x30 | 50+ type pages + audience hub | site size guide |
| Pack-It-Up (single) | homepage IS facility | n/a | inline on homepage | inline feature boxes | none |

Anchors: [Public Storage](https://www.publicstorage.com/self-storage-nv-las-vegas/10x10-storage-units), [Extra Space](https://www.extraspace.com/storage/facilities/us/missouri/st_louis/4042/), [CubeSmart](https://www.cubesmart.com/texas-self-storage/san-antonio-self-storage/224.html), [U-Haul](https://www.uhaul.com/Locations/Self-Storage-near-Kansas-City-KS-66102/734024/), [MyPlace](https://myplaceselfstorage.com/storage-locations/tx/dallas/6434-maple-ave/dallas-climate-controlled-storage/), [My Garage](https://www.mygarageselfstorage.com/), [Ace](https://www.aceself-storage.com/college-student-storage/), [Pack-It-Up](https://packitup.us/).

---

## 8. What to encode into the content system

1. Model the page inventory as **facility x storage-type x unit-size x audience**, gated by real first-party evidence per node (matches the existing topical-map evidence gate).
2. Treat **city x unit-size** and **city x storage-type** as the money pages; each must list real local inventory/price and unique local prose, never a restated national definition.
3. Ship the two hard content contracts (section 4) as playbook pass-tests for unit-size and storage-type pages.
4. Collapse to a single homepage-as-facility page for one-location clients; do not generate axis pages that would be thin.
5. Enforce the silo (section 5): facility page is the hub; every axis links back to it; every geo node carries a unique local block.
6. Size-guide/calculator and cost-guide are the two linkable assets worth building for links + AI citation.

---

## 9. Open questions / gaps for later dossiers

- Extra Space, Life Storage, and the Extra Space military/audience pages block WebFetch (403). Their exact H2 anatomy is inferred from peers; a later pass should capture them via a rendering fetch or cache.
- National Storage Affiliates operates a consumer brand (nsastorage.com, "1000+ facilities in 42 states") but I did not fetch a facility page this run; NSA's brand-vs-regional-brand structure is unmapped. Source: [nsastorage.com search listing](https://www.nsastorage.com/).
- Schema.org markup per page type (SelfStorage / Place / Product / FAQPage) is out of scope here - belongs in a schema dossier.
- Neighborhood-level pages (below city) exist at big operators but were not isolated this run; worth confirming whether they are indexable or JS-filtered views.
- Whether facility-level storage-type pages (MyPlace pattern) actually rank or are index-bloat is an open measurement question.
