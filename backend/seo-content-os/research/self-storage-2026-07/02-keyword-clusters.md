# Self-Storage Local-SEO Keyword & Search-Intent Network (US, 2026)

Research territory: THE SELF-STORAGE QUERY NETWORK + INTENT CLASSIFICATION + PAGE-TYPE MAPPING.
Purpose: give SEO-CONTENT-OS the storage-vertical cluster map so every page is briefed against a real query cluster with a known dominant intent and the exact page type that cluster wants.
Market: United States. All sources fetched live 2026-07-23 PKT via WebSearch/WebFetch. Prices and counts are dated directory/aggregator figures read this run, not invented; treat any single price as a directional market snapshot for that city on that date. Where a big-brand page blocked WebFetch (403), the URL pattern is still evidence and is labeled as such.

---

## 0. Executive read (the money map)

The storage query network splits cleanly into two economies, and the system must brief them differently.

1. **The transactional-local economy (the money).** Queries that name a place or a filter and imply "I want to rent now": `storage units [city]`, `storage near me`, `10x10 storage [city]`, `climate controlled storage [city]`, `RV storage near me`, `cheap storage [city]`, `24 hour storage [city]`. Dominant intent is transactional-local. These want a **facility page** or a **facet/landing page** (a size, type, or feature slice of the facility). The SERP is owned by (a) the Google local pack, (b) national brands (Public Storage, Extra Space, CubeSmart, U-Haul, Life Storage), and (c) directory aggregators (SpareFoot, Storage.com, FindStorageFast, RentCafe, USSelfStorage, StorageArea, Yelp). A single local operator's realistic leverage is the local pack plus hyper-specific facet pages the directories render thinly and the brands render generically.

2. **The informational/asset economy (the moat and the links).** Queries that ask a question: `what fits in a 10x10`, `how much does a storage unit cost`, `climate controlled vs drive up`, `what not to store in a storage unit`, `pods vs storage unit`, `how to bid on a storage auction`. Dominant intent is informational. These want an **asset page** (size guide, cost guide, comparison, checklist). They rarely convert directly but they earn links, win AI-answer citations, and feed the internal graph that lifts the money pages.

**The structural trap the system must encode:** the biggest page-type decision in this vertical is the unit-size split. `storage unit sizes` / `what fits in a 10x10` is informational and wants ONE brand-wide asset. `10x10 storage units [city]` is transactional-local and wants a size-facet page under the city - Public Storage, SpareFoot, and StorageArea all build these as distinct localized URLs (evidence in section 3). A system that answers a size query with only a national size guide, or that spins a size-in-city page with no real local availability, both lose. The facet page must carry genuine per-facility inventory or it is a doorway (Law 3 / `duplication_gate.py`).

**Honest constraint:** most head-term "near me" real estate is the local pack plus directories plus brands. Content's leverage here is Relevance (the facet and type pages) and the informational moat, not out-muscling Public Storage on the raw `storage units [city]` head term.

---

## 1. SERP composition reality (who actually ranks - brief against this, not against a clean SERP)

For the money queries, the operator is not competing with other local facilities first. They are competing with:

- **National brand facility pages** with city and facet URLs baked in: Public Storage `publicstorage.com/self-storage-ny-new-york`, `.../self-storage/drive-up-storage`, `.../self-storage/24-hour-storage` (https://www.publicstorage.com/self-storage , https://www.publicstorage.com/self-storage/drive-up-storage , https://www.publicstorage.com/self-storage/24-hour-storage); Extra Space `extraspace.com/self-storage/business-storage/`, `.../vehicle-storage/rv-storage/`, `.../cheap-storage-units/` (https://www.extraspace.com/self-storage/business-storage/ , https://www.extraspace.com/self-storage/vehicle-storage/rv-storage/ , https://www.extraspace.com/self-storage/cheap-storage-units/); CubeSmart `cubesmart.com/storage/business-storage/`, `/storage/wine-storage/`, `/size-guide/` (https://www.cubesmart.com/storage/business-storage/ , https://www.cubesmart.com/storage/wine-storage/ , https://www.cubesmart.com/size-guide/).
- **Directory aggregators** that generate a page for every city x facet combination: SpareFoot `sparefoot.com/Denver-CO-self-storage.html`, `.../Denver-CO-self-storage/24-hour-access.html`, `.../drive-up-storage-units.html`, `.../storage-lockers.html`, `.../Austin-TX-self-storage/10x10-storage-units.html`, `sparefoot.com/portable-storage/denver-co.html` (https://www.sparefoot.com/Denver-CO-self-storage.html ). FindStorageFast `findstoragefast.com/co/denver-storage-units` (https://www.findstoragefast.com/co/denver-storage-units ). RentCafe `rentcafe.com/storage-units/us/tx/austin/` and `rentcafe.com/climate-controlled-storage-units/us/tx/austin/` (https://www.rentcafe.com/storage-units/us/tx/austin/ ). StorageArea renders live facet params: `storagearea.com/austin-tx-self-storage.html?size=10x10&climate=y&driveup=y` (https://www.storagearea.com/austin-tx-self-storage.html ). Yelp lists too (https://www.yelp.com/ ).
- **The Google local pack + Google Maps**, driven by GBP + proximity + reviews (outside content's direct control; see the local-authorities dossier).

Implication for the system: every storage money page must out-specific the directory listing (which is thin, price-table-only) and out-local the brand page (which is generic and national). The winning page = brand-page structure + directory-grade live inventory + the one thing neither has: dated first-party local proof (Law 16).

---

## 2. The cluster map (each cluster: representative queries -> dominant intent -> page type it wants)

### Cluster A - Head / "near me" / "[type] storage [city]"
Representative queries: `storage units near me`, `self storage [city]`, `storage units [city]`, `cheap self storage [city]`, `storage near me`, `self storage units near me`.
Dominant intent: **transactional-local.**
Page type it wants: **facility page** (the city/location page for the operator's site), competing in the local pack.
Evidence: directory city pages exist for exactly these terms and lead with a live price ("198 Cheap Self-Storage Units in Denver, CO (From $10)", SpareFoot; "Storage units in Denver start at $14.00/month, popular 10x10 units averaging $113.28/month", FindStorageFast, July 2026). Sources: https://www.sparefoot.com/Denver-CO-self-storage.html , https://www.findstoragefast.com/co/denver-storage-units
Notes: this is the hardest cluster to win as an independent (pack + brands + directories). Brief the facility page to convert the pack click, not to out-rank Public Storage organically.

### Cluster B - Unit-size queries (THE SPLIT - two page types from one size)
B1 transactional-local: `10x10 storage unit [city]`, `5x10 storage [city]`, `10x20 storage units [city]`, `10x30 storage [city]`.
  Intent: **transactional-local.** Page type: **size-facet page** (size slice under the city). Evidence: Public Storage builds one URL per size per city - `publicstorage.com/self-storage-tx-austin/10x10-storage-units`, `.../10x15-storage-units`, `.../10x30-storage-units`; SpareFoot `sparefoot.com/Austin-TX-self-storage/10x10-storage-units.html`; StorageArea `?size=10x10`. Austin 10x10 averaged $102.92/mo, cheapest $39 (StorageArea/directory data, 2026-06-24). Sources: https://www.publicstorage.com/self-storage-tx-austin/10x10-storage-units , https://www.sparefoot.com/Austin-TX-self-storage/10x10-storage-units.html , https://www.storagearea.com/austin-tx-self-storage.html
B2 informational: `storage unit sizes`, `storage size guide`, `what fits in a 10x10`, `10x10 vs 10x15`, `what fits in a 5x10`.
  Intent: **informational.** Page type: **asset page** (one brand-wide size guide + per-size explainer sections / comparison sub-pages). Evidence: every major brand runs a single size-guide hub - SpareFoot `/storage-unit-size-guide.html`, Extra Space `/self-storage/storage-unit-size-guide/`, CubeSmart `/size-guide/`, and dedicated comparison URLs like Extra Space `/storage-unit-size-guide/10x10-vs-10x15-storage-units/`. Standard size facts read this run: 5x5 = 25 sq ft (small closet); 5x10 = 50 sq ft (studio/1-bed); 10x10 = 100 sq ft (~1-bedroom, "most popular"); 10x15 = 150 sq ft (2-bed, 1,200 cu ft); 10x20 = 200 sq ft (3-bed home / vehicle); 10x30 = large (car/small boat). Sources: https://www.sparefoot.com/storage-unit-size-guide.html , https://www.cubesmart.com/size-guide/ , https://www.extraspace.com/self-storage/storage-unit-size-guide/10x10-vs-10x15-storage-units/ , https://self-storage.modernstorage.com/size-guide
Notes: this split is the single most important architectural call in the vertical (see section 0). The size-in-city facet must carry real availability; the size guide is the link/citation asset.

### Cluster C - Storage-type queries (climate, drive-up, indoor/outdoor)
Representative queries: `climate controlled storage [city]`, `drive up storage near me`, `indoor storage units`, `outdoor storage units`, `climate controlled vs drive up`, `storage lockers [city]`.
Dominant intent: **commercial + transactional-local** (the modifier is a buying filter). The comparison variants (`climate controlled vs drive up`, `indoor vs outdoor`) are **informational.**
Page type it wants: **storage-type page** (a type slice: climate-controlled, drive-up, indoor, outdoor), plus type-in-city facets; comparison variants -> **asset page.**
Evidence: brands and directories build type facets - Public Storage `/self-storage/drive-up-storage`; SpareFoot `/Denver-CO-self-storage/drive-up-storage-units.html`, `/storage-lockers.html`; USSelfStorage `usselfstorage.com/ca/self-storage-los-angeles/drive-up-access`; RentCafe `climate-controlled-storage-units/us/tx/austin/`. Climate control adds a ~20-30% price premium (Extra Space pricing guide); Austin 10x10 climate-controlled ~$163/mo vs $102.92 standard (directory, 2026). Comparison intent is served by dedicated explainers (6Storage climate-vs-drive-up; Extra Space indoor-vs-outdoor FAQ). Sources: https://www.publicstorage.com/self-storage/drive-up-storage , https://www.6storage.com/climate-controlled-vs-drive-up/ , https://www.extraspace.com/self-storage/faq/how-to-choose-between-indoor-and-outdoor-storage/ , https://usselfstorage.com/ca/self-storage-los-angeles/drive-up-access , https://www.rentcafe.com/climate-controlled-storage-units/us/tx/austin/

### Cluster D - Vehicle storage (RV / boat / car / motorcycle / trailer)
Representative queries: `RV storage near me`, `boat storage [city]`, `car storage near me`, `covered RV storage`, `enclosed vehicle storage`, `motorcycle storage`, `trailer/camper storage`.
Dominant intent: **transactional-local** (informational tail: `how much does RV storage cost`).
Page type it wants: **storage-type page (vehicle family)** - usually a vehicle-storage hub plus per-vehicle pages (RV, boat, car, motorcycle), each with covered/uncovered/enclosed options.
Evidence: this is the most consistently productized type. Extra Space `/self-storage/vehicle-storage/rv-storage/`; StoragePRO `/storage-types/rv-vehicle-and-boat-storage/`; Storage King USA `/rv-boat-and-vehicle-storage/`; U-Haul `/Storage/Vehicle-Storage/`; Storage.com splits it fully: `/car-storage/`, `/rv-storage/`, `/boat-storage/`, `/motorcycle-storage/` (confirmed via WebFetch of storage.com nav). Pricing tiers read this run: outdoor RV $50-$150/mo, covered $75-$250, indoor/enclosed $150-$500 depending on length (HomeGuide/Extra Space). Sources: https://www.extraspace.com/self-storage/vehicle-storage/rv-storage/ , https://www.storagepro.com/storage-types/rv-vehicle-and-boat-storage/ , https://homeguide.com/costs/rv-storage-cost , https://www.uhaul.com/Storage/Vehicle-Storage/ , https://www.storage.com/blog/types-of-business-storage/
Notes: covered / uncovered / enclosed is a sub-facet inside vehicle storage, not a separate cluster - encode as an attribute, not a page each, unless the facility has real inventory in all three.

### Cluster E - Specialty / commercial-good storage (business, wine, document/records)
Representative queries: `business storage near me`, `commercial storage`, `inventory storage for small business`, `document storage [city]`, `records storage`, `wine storage near me`, `temperature controlled wine storage`.
Dominant intent: **commercial + transactional-local** (B2B buyers; often higher LTV).
Page type it wants: **audience/use-case page** (business storage) and **specialty-type page** (wine, document) - a type or audience slice, sometimes both (business storage that is also climate-controlled).
Evidence: dedicated hubs exist - Extra Space `/self-storage/business-storage/`; CubeSmart `/storage/business-storage/` and `/storage/wine-storage/`; Storage.com `/business-storage/` plus a "Secure Document and File Storage" type; Prime Storage `/business-inventory/`. Wine storage ideal conditions cited: 52-64 F, 60-70% humidity, UV-protected (SpareFoot/CubeSmart). Business storage sold on month-to-month vs warehouse-lease economics. Sources: https://www.extraspace.com/self-storage/business-storage/ , https://www.cubesmart.com/storage/wine-storage/ , https://www.sparefoot.com/wine-storage.html , https://www.storage.com/blog/types-of-business-storage/
Notes: document/records and wine are the two specialty types worth a page ONLY where the facility genuinely offers the controlled conditions; otherwise fold into climate-controlled. Business storage is broadly applicable and worth a standing page in most markets.

### Cluster F - Audience storage (student, military)
Representative queries: `student storage near [university]`, `college summer storage`, `dorm storage`, `military storage`, `storage military discount`, `PCS / deployment storage`, `storage near [base]`.
Dominant intent: **commercial + transactional-local**, strongly seasonal (student = spring move-out / summer) and event-driven (military = PCS/deployment).
Page type it wants: **audience page** (student-storage, military-storage), ideally localized to the campus or base.
Evidence: universal audience products - Extra Space `/self-storage/storage-tips/student-storage/` and `/military-storage/`; StoragePRO `/storage-types/military-storage-units/`; Storage.com `/college-student-storage/`; SpareFoot `/military-storage.html`. Student self-storage near campus runs ~$50-$150/mo; military discounts are the hook (StoragePRO 10% active + veterans; Storage King USA 5%; EZ Storage 10%/mo). Sources: https://www.storagescholars.com/blog/college-summer-storage , https://www.extraspace.com/self-storage/storage-tips/student-storage/ , https://www.storagepro.com/storage-types/military-storage-units/ , https://www.storagekingusa.com/military-discount/ , https://www.sparefoot.com/military-storage.html
Notes: audience pages localize on the anchor institution (`student storage near [University]`, `storage near [Base]`), not just the city - a distinct and defensible facet an independent near a campus/base can own before the brands do.

### Cluster G - Price / deal queries
Representative queries: `cheap storage units near me`, `affordable storage [city]`, `first month free storage`, `1 month free storage near me`, `storage deals / specials`, `$1 storage unit`, `storage unit prices`.
Dominant intent: **SPLIT.** `cheap/affordable/first-month-free storage [city]` = **transactional-local**; `storage unit prices` / `how much does storage cost` = **informational.**
Page type it wants: **deal/facility page** (a cheap-storage or specials facet of the facility page) for the transactional half; **asset page** (cost guide) for the informational half.
Evidence: brands run a dedicated cheap-storage facet - Extra Space `/self-storage/cheap-storage-units/`; SpareFoot `/storage-deals.html`; U-Haul "one month free" hub with "no admin fees or deposits, rate fixed 12 months." Directory deal data: FindStorageFast units "from $8/mo, popular 10x10 avg $75, lowest $33" (2026-07-16). Cost-guide asset intent is huge and separate: Alan's Factory Outlet, Extra Space blog, Public Storage 2026 price guide, SpareFoot "average by size + state." Market cost facts read this run: most units $60-$300/mo; small (5x5/5x10) $35-$60; 10x10 drive-up ~$100-$160; 10x20 ~$150-$284; $0.97-$1.40 per sq ft. Sources: https://www.extraspace.com/self-storage/cheap-storage-units/ , https://www.sparefoot.com/storage-deals.html , https://alansfactoryoutlet.com/blog/storage-unit-costs/ , https://www.extraspace.com/blog/self-storage/how-much-do-storage-units-cost/ , https://www.findstoragefast.com/co/colorado-springs-storage-units
Notes: Law 20 (no fabricated urgency) and the review/promo rules bite hardest here. "First month free" copy must match the actual, currently-live offer at that facility or it is a false local specific.

### Cluster H - Access / feature queries
Representative queries: `24 hour storage near me`, `24/7 access storage`, `drive up storage`, `ground floor storage unit`, `month to month storage`, `gated storage`, `storage with elevator`, `storage lockers`.
Dominant intent: **transactional-local** (feature is the buying filter).
Page type it wants: **feature-facet page** - most often merged as sections/attributes of the facility or type page, promoted to its own page only where search volume + real inventory justify it (24-hour, drive-up, storage lockers all have standalone facets in the wild).
Evidence: Public Storage `/self-storage/24-hour-storage`; SpareFoot `/Denver-CO-self-storage/24-hour-access.html` and `/storage-lockers.html`; USSelfStorage `/drive-up-access`. Standard feature vocabulary read this run: unique gate code + logged entries, perimeter cameras, illuminated aisles, month-to-month leases, ground-level drive-up. Sources: https://www.publicstorage.com/self-storage/24-hour-storage , https://www.sparefoot.com/Denver-CO-self-storage/24-hour-access.html , https://usselfstorage.com/ca/self-storage-los-angeles/drive-up-access
Notes: "month to month" and "ground floor" are almost always attributes, not pages. "24 hour access" and "drive up" cross the threshold to their own facet page in enough markets to treat as promotable nodes (gate on real inventory via the topical-map lint).

### Cluster I - Informational / asset queries (the link + AI-citation layer)
Representative queries: `storage unit size guide`, `how much does a storage unit cost`, `what not to store in a storage unit` (prohibited items), `how to pack a storage unit`, `climate controlled vs drive up`, `indoor vs outdoor storage`, `pods vs storage unit`, `moving and storage`, `portable storage containers`, `how to bid on a storage auction`, `storage insurance`, `how do storage auctions work`.
Dominant intent: **informational** (a commercial tail on the comparison and moving queries where a decision is imminent).
Page type it wants: **asset page** (size guide, cost guide, prohibited-items checklist, comparison, neighborhood/moving guide) - the `/write-local-asset` and FAQ surfaces.
Evidence: mature question-content ecosystem - prohibited-items lists (SelfStorage.com, Move.org: no hazardous/flammable, perishables, firearms, living things, strongly scented items, high-value valuables); pods-vs-storage comparisons (PODS, moveBuddha, RecNation) with cost framing ($1,000-$7,000 for containers on long moves vs lower monthly self-storage); storage-auction how-to (StorageTreasures, "750,000+ auctions/year"). Sources: https://www.selfstorage.com/blog/what-can-you-not-store-in-a-storage-unit/ , https://www.move.org/self-storage-tips-dos-donts/ , https://www.pods.com/blog/pods-vs-storage-unit , https://www.movebuddha.com/blog/self-storage-vs-moving-container/ , https://www.storagetreasures.com/
Notes: these are the pages that earn the AI-answer citation and the links, and they are where information-gain (Law 15) is easiest to win with dated first-party data (this facility's real prices, this city's real demand curve). Also the natural home for FAQ-schema passage blocks.

### Cluster J - Brand / navigational
Representative queries: `Public Storage`, `Extra Space Storage`, `CubeSmart login / pay bill`, `U-Haul storage`, `Life Storage`, `[brand] [city]`, `[brand] near me`, `[brand] account`.
Dominant intent: **navigational** (the user already picked a brand).
Page type it wants: for the operator, only their **own brand + homepage / login / pay** surface; competitor brand terms are not a content target beyond honest comparison assets.
Evidence: heavy account/utility intent - CubeSmart `/login/`, U-Haul "how to pay your storage unit rent," brand-comparison content ("Public Storage competitors"). Sources: https://www.cubesmart.com/login/ , https://www.uhaul.com/Tips/Storage/How-To-Pay-Your-Storage-Unit-Rent-26930/
Notes: the only defensible play against competitor-brand navigational queries is a truthful "[operator] vs [brand]" or "alternatives" comparison asset (commercial intent), never a doorway. For the operator's own brand, ensure the homepage owns `[brand] [city]` and the account/pay path is crawlable.

---

## 3. URL-pattern evidence table (real ranking URLs -> the page type each cluster wants)

Every URL below was returned as a ranking result this run. The pattern proves how the market has already resolved the intent-to-page-type mapping. (Big-brand pages 403 on WebFetch; the URL string itself is the evidence.)

| Cluster | Real ranking URL pattern | Implied page type |
|---|---|---|
| Head / city | `sparefoot.com/Denver-CO-self-storage.html` ; `findstoragefast.com/co/denver-storage-units` | facility / city page |
| Size-in-city | `publicstorage.com/self-storage-tx-austin/10x10-storage-units` ; `sparefoot.com/Austin-TX-self-storage/10x10-storage-units.html` | size-facet page |
| Size guide | `cubesmart.com/size-guide/` ; `extraspace.com/self-storage/storage-unit-size-guide/10x10-vs-10x15-storage-units/` | asset (size guide) |
| Type - drive-up | `publicstorage.com/self-storage/drive-up-storage` ; `usselfstorage.com/ca/self-storage-los-angeles/drive-up-access` | storage-type / feature facet |
| Type - climate | `rentcafe.com/climate-controlled-storage-units/us/tx/austin/` | storage-type-in-city facet |
| Vehicle | `extraspace.com/self-storage/vehicle-storage/rv-storage/` ; `storage.com/boat-storage/` ; `storage.com/motorcycle-storage/` | storage-type (vehicle) page |
| Business | `extraspace.com/self-storage/business-storage/` ; `cubesmart.com/storage/business-storage/` | audience / use-case page |
| Wine / document | `cubesmart.com/storage/wine-storage/` ; Storage.com "Secure Document and File Storage" | specialty-type page |
| Student | `extraspace.com/self-storage/storage-tips/student-storage/` ; `storage.com/college-student-storage/` | audience page |
| Military | `storagepro.com/storage-types/military-storage-units/` ; `storagekingusa.com/military-discount/` | audience page |
| Cheap / deals | `extraspace.com/self-storage/cheap-storage-units/` ; `sparefoot.com/storage-deals.html` | deal / facility facet |
| 24-hour / feature | `publicstorage.com/self-storage/24-hour-storage` ; `sparefoot.com/Denver-CO-self-storage/24-hour-access.html` | feature facet |
| Cost guide | `alansfactoryoutlet.com/blog/storage-unit-costs/` ; `publicstorage.com/blog/.../the-complete-guide-to-storage-unit-prices-in-2026.html` | asset (cost guide) |
| Prohibited items | `selfstorage.com/blog/what-can-you-not-store-in-a-storage-unit/` | asset / FAQ |
| Pods vs storage | `pods.com/blog/pods-vs-storage-unit` ; `movebuddha.com/blog/self-storage-vs-moving-container/` | asset (comparison) |
| Storage auction | `storagetreasures.com/auctions/fl/miami` | asset / navigational (3rd-party platform) |

---

## 4. Intent classification summary (system-ready)

| Cluster | Dominant intent | Page type (system term) | Localizes on | Promote-to-page gate |
|---|---|---|---|---|
| A. Head / near-me / [type] [city] | transactional-local | facility (location page) | city | always (core node) |
| B1. Size-in-city (10x10 [city]) | transactional-local | unit-size facet | city + size | real inventory in that size |
| B2. Size guide / what-fits | informational | asset | none (brand-wide) | one hub, always |
| C. Type: climate / drive-up / indoor / outdoor | commercial + transactional-local | storage-type page | city (facet) | real inventory of that type |
| C-alt. Type comparisons | informational | asset | none | one per comparison, as needed |
| D. Vehicle: RV/boat/car/motorcycle | transactional-local | storage-type (vehicle) | city + vehicle | real vehicle inventory |
| E. Business / wine / document | commercial + transactional-local | audience + specialty-type | city | business: usually; wine/doc: only if truly offered |
| F. Student / military | commercial + transactional-local (seasonal/event) | audience page | campus / base | near a real anchor institution |
| G1. Cheap / first-month-free [city] | transactional-local | deal/facility facet | city | a live, real offer (Law 20) |
| G2. Storage prices / how much | informational | asset (cost guide) | none (or city cost guide) | one hub, always |
| H. 24hr / drive-up / ground-floor / month-to-month | transactional-local | feature facet or attribute | city | attribute by default; page only for 24hr/drive-up w/ inventory |
| I. Prohibited items / packing / pods-vs / moving / auctions | informational | asset / FAQ | none (or city moving guide) | as the asset calendar allows |
| J. Brand / login / pay / [brand] [city] | navigational | own homepage/account only | brand | own brand only; competitor = comparison asset |

---

## 5. What the system must encode (hand-off to topical-map + playbooks)

1. **The unit-size dual node.** Ship one brand-wide size-guide asset (B2) AND size facet nodes per city (B1), and never let the facet exist without real per-facility availability. This is the vertical's defining architecture decision and the sharpest doorway risk.
2. **A storage-type node family, not one "types" page.** Climate-controlled, drive-up, indoor, outdoor, plus the vehicle family (RV/boat/car/motorcycle) - each a promotable node gated on real inventory. Covered/uncovered/enclosed are attributes inside vehicle storage.
3. **Audience nodes that localize on the anchor institution.** Student-near-[university] and military-near-[base] are the independent operator's most defensible facets; brief them to the campus/base, not just the city, and lead with the seasonal/event trigger.
4. **The price cluster's two-page rule.** A cost-guide asset (informational, link/citation magnet) is separate from the cheap-storage / first-month-free facet (transactional), and the promo facet must mirror a currently-live real offer (Law 20, no fabricated urgency).
5. **Feature queries default to attributes.** Only 24-hour access and drive-up reliably earn their own facet page; everything else (month-to-month, ground floor, gated, elevator) is a schema/attribute and an on-page section.
6. **The asset layer carries the moat.** Size guide, cost guide, prohibited-items checklist, pods-vs-storage, and storage-auction explainers are where first-party dated data wins information-gain and AI citations. Route these through `/write-local-asset` and the FAQ surface with passage-block + FAQ schema.
7. **Brief every money page against the real SERP:** local pack + national brand facet page + directory listing. The win condition is brand-page structure + directory-grade live inventory + dated first-party local proof - the one thing neither competitor has.

---

## 6. Open questions / limits of this run

- **Volume, not just structure.** This maps clusters and intent from live SERPs and ranking URLs; it does not carry keyword *volumes* (no keyword API, per system constraint). Relative importance is inferred from how universally the big players have productized each cluster (a strong but indirect proxy). A per-market volume pass would sharpen node prioritization.
- **Autocomplete/PAA captured indirectly.** Google autocomplete and People-Also-Ask were inferred from ranking titles, "vs" pages, and directory facet URLs rather than scraped from the SERP widget (no direct SERP-widget access this run). The comparison and "what fits / how much" clusters are the clearest PAA signals.
- **Prices are dated snapshots.** Every dollar figure here is a real directory/brand figure with a date attached; none should be republished as a current local price without re-verification at write time for the specific city/facility (Law: no fabricated local specifics).
- **Seasonality quantified only qualitatively.** Student (spring/summer) and military (PCS/deployment) seasonality is documented as pattern, not as a demand curve. A calendar overlay would improve refresh timing (Laws 18-19).
- **Local pack mechanics are out of scope here.** How to actually win the pack (GBP, proximity, reviews) lives in the local-authorities dossier; this file is the query/intent/page-type layer only.
