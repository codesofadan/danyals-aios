# The Unit-Size Page: The Definitive Self-Storage Build Playbook

The storage-native money page. One unit size, one place. "10x10 storage units in Las Vegas." "5x10 storage Austin." "10x20 climate-controlled unit Dallas." This page type does not exist in any other vertical, and it is the single most important page a self-storage operator can own after the facility page itself, because "what size do I need / what fits in a 10x10" is the highest-intent question a renter asks (`research/self-storage-2026-07/05-voice-language.md`, the renter's question #1).

It is also, with the facility page, the highest doorway risk in the whole storage vertical: a business with 6 unit sizes across 8 cities can mint 48 near-identical "[size] storage units [city]" pages by swapping two tokens, and Google's scaled-content-abuse policy is written to catch exactly that. Public Storage's own programmatic "10x10 storage units near [city]" pages are a live, verified instance of the pattern (same skeleton scaling to Atlanta, LA, NY, Phoenix). Both facts are central. Treat them as one problem.

A builder handed this file plus one real facility (real unit sizes, real live or dated prices, real dimensions, real what-fits knowledge, real nearby inventory) can produce a unit-size page a top-0.1% storage operator signs off on, that survives the doorway policy by construction.

Governing law: `knowledge/doctrine/seo-system-doctrine.md` (Law 8: humanize with real facts, never detector-evasion) and `knowledge/doctrine/local-content-laws.md` (Law 15 information gain, Law 16 the experience moat, Law 20 no fabricated urgency). Read alongside `knowledge/verticals/self-storage.md` (the compliance overlay), the closest example teardowns in `knowledge/playbooks/examples/self-storage.md`, and `service-city-page.md` (the general money-page doorway discipline this specializes).

Every quantitative figure here is directional unless it comes from the client's `brand.yaml`. The dimensions and what-fits mappings are the industry-standard pattern (verified against CubeSmart and Public Storage size guides this build); re-verify the client's real prices and inventory at write time. No number ships from memory.

---

## 1. The dual-node split (read this before anything else)

**One unit size produces TWO different pages with two different intents, and confusing them loses both.** This is the defining architectural call of the storage vertical (`research/self-storage-2026-07/02-keyword-clusters.md`, cluster B).

| | Informational size guide | City-level unit-size money page (this playbook's primary) |
|---|---|---|
| Target query | `storage unit sizes`, `what fits in a 10x10`, `10x10 vs 10x15` | `10x10 storage units [city]`, `5x10 storage [city]` |
| Intent | informational | transactional-local |
| Node | ONE brand-wide asset | one per size per city the facility genuinely stocks that size |
| Localizes on | nothing (brand-wide) | city + size |
| Build command | `/write-local-asset` (size-guide asset) | `/write-unit-size-page` |
| The moat | dated first-party data + a real size diagram/calculator | REAL local inventory + price for that size at a real facility |
| Promotion gate | one hub, always | real inventory in that size (topical-map evidence gate) |

The money page fails two ways at once: answer a size-in-city query with only the national size guide (no local inventory, loses the transactional intent), or spin a size-in-city page with no real availability (a doorway). **The city-level unit-size page must carry genuine per-facility inventory or it is a doorway** (G3 / `duplication_gate.py` / overlay SS-DOORWAY). The two page types share the "what fits" content contract (Section 6) but only the money page carries local price and inventory.

This playbook is written for the **city-level unit-size money page**. Its "what fits" and dimensions sections double as the spec for the size-guide asset when `/write-local-asset` builds one; the difference is the money page adds the local inventory board and the guide adds original dated data (Section 8).

**Single-facility collapse rule.** If `brand.yaml.storage.operator_type == single_facility`, do NOT build separate unit-size pages at all. A one-location operator shows its unit sizes as a section on the homepage-as-facility-page (verified: packitup.us). Separate size pages for one facility are thin by construction (`research/self-storage-2026-07/01-site-architecture.md`, the collapse rule). The unit-size page is a multi-facility / big-footprint move.

---

## 2. Purpose and the ONE job

**Rank for, earn the AI-answer citation for, and convert the renter who searched one specific unit size in one specific place.** The renter who types "10x10 storage units in Las Vegas" has qualified themselves twice: they know the size they think they need (or they are checking), and they want it near them, now. The page has one job: confirm what actually fits that size, show that this facility has that size available at a real price near them, and get the rent-or-reserve.

**Where it sits in the silo** (`research/self-storage-2026-07/01-site-architecture.md`): the unit-size page is a facet that links back UP to the facility page (the hub every axis returns to) and the city hub, ACROSS to the adjacent sizes (10x10 links 10x15 and 5x10) and to the storage-type pages (a 10x10 comes in climate-controlled and drive-up), and to the informational size-guide asset. It is never orphaned behind a JavaScript store-locator.

---

## 3. Target intent and query patterns

The page targets a family of near-identical high-intent queries. Build for all at once:

- **`[size] storage units [city]`** - "10x10 storage units Las Vegas." The canonical target.
- **`[size] storage [city]`** / **`[size] unit [city]`** - terser variants.
- **`[size] storage near me`** - resolves to the searcher's location; a page strongly tied to that city catches it.
- **`[size] [storage-type] storage [city]`** - "10x20 climate-controlled unit Dallas" (the size axis crossed with the type axis; still one page if the facility stocks that combination).
- **`how much is a [size] storage unit [city]`** / **`[size] storage cost [city]`** - the price variant, answered by the live inventory board.
- **`what fits in a [size]`** - the informational tail; answered as a passage block on the money page AND owned by the size-guide asset.

Renters do not think in square feet, they think in rooms and truckloads (`05-voice-language.md`). "The size of a one-car garage" is a 10x20. "A studio apartment's worth" is a 5x10. The page must answer in their words, then anchor to the dimensions.

**The two mindsets split the CTA** (`04-conversion-cro.md`): an URGENT mover (truck already loaded) wants **Rent Online Now** + click-to-call; a PLANNED declutterer wants **Reserve free, no card, no obligation** (which honestly locks the daily-fluctuating web rate). Match the primary CTA to the dominant intent of the query, keep the other subordinate, keep click-to-call one tap away on mobile.

---

## 4. The 2026 SERP reality

- **The money query is owned by the local pack + national brands + directory aggregators**, not by other local facilities (`02-keyword-clusters.md`, section 1). Public Storage builds `/self-storage-tx-austin/10x10-storage-units`; SpareFoot builds `/Austin-TX-self-storage/10x10-storage-units.html`; StorageArea renders `?size=10x10`. The independent competes by out-specifying the directory (which is a thin price table) and out-localizing the brand page (which is generic). The win condition = brand-page structure + directory-grade live inventory + the one thing neither has: a dated first-party local detail.
- **There is NO self-storage pricing rich result in Google Search** (`03-schema-structured-data.md`). `Product`/`Offer` markup does not put your unit price in the SERP; a storage unit is a rental, not a purchasable retail SKU. Operators surface "from $X/mo" in the title tag and on-page copy, not via a schema price chip. Mark up units for entity/AI-answer understanding only, never as a rich-result lever.
- **AI answer engines increasingly answer "how much is a 10x10 in [city]"** by lifting a clean, marked-up price band + a direct-answer what-fits passage. This is where the passage-block discipline (Section 5) pays off even with zero classic rich result.

---

## 5. Section-by-section architecture

Build in this order. Each section states its must-contain, the local requirement, and a binary PASS test.

### 5.1 Hero
- **Must contain:** an H1 with the exact size AND the exact city ("10x10 Storage Units in Las Vegas, NV"); a one-line direct answer under it ("A 10x10 holds a one-bedroom apartment: bed, sofa, dresser, and about 100 boxes."); the primary CTA (Rent Online for urgent, Reserve free for planned); a from-price if `live_inventory` or a real dated rate; click-to-call tappable.
- **PASS:** H1 contains both the exact size and the exact city; a real from-price or an honest "check live availability" is above the fold; phone tappable on a 375px viewport.

### 5.2 The direct-answer "what fits" block (the money passage)
- **Must contain:** the size's real dimensions + derived area/volume ("10 ft x 10 ft, 100 sq ft, 800 cubic feet, 8-foot ceilings"); a physical-world equivalent ("about a one-bedroom apartment," "half a one-car garage"); a what-fits inventory grouped by room (bedroom / living room / kitchen / garage), real item lists not adjectives; a box-count estimate WITH the honesty hedge (Public Storage's real move: "144 boxes maximum, but 100 is more realistic"); a recommended truck size where relevant.
- **Local requirement:** lead with the direct answer sentence (an AI engine lifts it). Do NOT open with the banned non-answer "the size you need depends on how much you have" (overlay/voice Tier-3).
- **PASS:** dimensions + volume + a room-grouped what-fits list + an honesty-hedged box count, all present; the opening sentence answers the question standalone.

### 5.3 The live inventory board (the #1 conversion lever, the anti-doorway core)
- **Must contain:** this facility's (or these facilities') real available 10x10 units with real prices, dated, ideally PMS-fed. Where `live_inventory == false`, the honest current published web rate by size with a dated stamp, never invented. Online vs in-store price if both exist. Honest availability states, including "sold out / limited" (showing a sold-out unit is the anti-fabrication move that proves the board is real - Capitola does this).
- **Local requirement:** this is the section that makes the page NOT a doorway. Real, priced, addressed local inventory is the value a spun template cannot fake (overlay SS-DOORWAY, SS-CV3). For a city with multiple facilities, list the real facilities with addresses and per-facility rates (the Public Storage Dallas-climate model, done right).
- **PASS:** at least one real, dated, size-specific price tied to a real facility; no fabricated availability; page price equals checkout price.

### 5.4 Is this the right size? (up/down cross-links)
- **Must contain:** a "too small / too big?" decision block linking to the adjacent sizes (10x10 links up to 10x15 and down to 5x10), each with its one-line what-fits, so the renter self-corrects instead of bouncing.
- **PASS:** contextual links to the adjacent smaller and larger size pages with descriptive anchors.

### 5.5 This size in this facility's real conditions (storage-type + local specifics)
- **Must contain:** whether this size comes climate-controlled / drive-up / indoor here, at what real held range (overlay SS-5); one genuinely local fact for the city (a neighborhood the facility serves, why this size is in demand locally - college move-out near a named campus, an apartment-heavy district), from the SME.
- **Local requirement:** this is where the strip-the-city test is won. One sentence that breaks when pasted onto the facility across town.
- **PASS:** at least one externally-verifiable or first-party local specific that this page alone carries.

### 5.6 Trust + security (mechanism, not reassurance)
- **Must contain:** the concrete security spec from `storage.security_features[]` (camera count, individual door alarms, gated per-tenant code, on-site manager), NOT "safe and secure" (overlay SS-3); real reviews as on-page HTML (never self-serving review schema, SS-SCHEMA1); a dated first-party facility photo where available.
- **PASS:** every security claim carries a spec; no banned absolute-security phrase; reviews in HTML, no self-serving Review/AggregateRating markup.

### 5.7 FAQ (size-specific + local)
- **Must contain:** 4-6 FAQs, at least 2 local (does this facility have 10x10s available now, what does a 10x10 cost here, is it climate-controlled, drive-up or interior), each a self-contained liftable passage. Capacity numbers internally consistent (no "150-200 boxes" in the body and "80" in the FAQ - the Big Tex blog contradiction is a verified accuracy fail).
- **PASS:** 4+ FAQs, 2+ genuinely local, no internal capacity contradiction, FAQPage schema mirroring the visible text (no rich result expected, kept for AI extraction).

### 5.8 Move-in special + closing CTA
- **Must contain:** the real, live move-in special with the admin fee and every still-payable item disclosed in-line (overlay SS-6, never "$0 at move-in" when an admin fee applies); a closing CTA repeating the primary action after the proof and FAQ; NAP byte-identical to `brand.yaml`; a persistent sticky mobile CTA.
- **PASS:** offer conditions disclosed in-copy (not footnote); a CTA after the FAQ; NAP identical to brand.yaml; no fabricated urgency (SS-CV1/2).

---

## 6. The non-thin content contract (the pass test, union of CubeSmart + Public Storage)

A unit-size page may not publish unless it carries ALL of:

1. **Exact dimensions + derived area/volume** ("10x10x8 = 800 cu ft; 100 sq ft").
2. **A physical-world equivalent** ("one-bedroom apartment," "half a one-car garage").
3. **A room-grouped what-fits inventory** with real item lists, not adjectives.
4. **A box-count estimate with an honesty hedge** (the maximum AND the realistic count).
5. **Real local price/inventory for this size** at a real facility (the money-page requirement; the guide flavor substitutes original dated data).
6. **Up/down cross-links to the adjacent sizes.**
7. **A recommended truck size** where the size warrants it, and/or a size visual/photo.
8. **At least one first-party local specific** that this page alone carries (the strip-the-city survivor).

Miss any of 1-6 and it is thin; miss 5 or 8 and it is a doorway. A page that is ONLY the generic what-fits copy (items 1-4, 6-7) is the commodity boilerplate that appears verbatim across every operator (`08-example-teardowns.md`, B-3c) - legal, but zero information gain and no reason to outrank the incumbents.

---

## 7. The doorway problem (the storage size grid)

**The arithmetic:** 6 sizes x 8 cities = 48 unit-size pages. Generating 48 by injecting two variables into one template is the exact behavior the scaled-content-abuse policy names, and Public Storage's own programmatic "10x10 near [city]" pages demonstrate it live (same skeleton at Atlanta/LA/NY/Phoenix, <5% city-specific editorial, ~3,000 words of repeated unit-card boilerplate - word count without information gain is the doorway signature).

**The rules that keep the grid alive:**
1. **Tie page creation to real inventory, not a keyword list.** A size-in-city page exists only where the facility genuinely stocks that size in that city (the topical-map evidence gate). No inventory, no page - the node stays index-only.
2. **The strip-the-city / strip-the-facility test.** Remove the city name and the facility's real inventory board. If the remaining body reads complete for any facility in any city, it FAILS. The winner fails-to-generalize on purpose: the real 10x10 rate at THIS address, the named local campus that drives 10x10 demand, the facility's real held climate range.
3. **`duplication_gate.py` across siblings.** Run it across the size pages (10x10 Vegas vs 10x10 Reno vs 5x10 Vegas). A pair at/above threshold is a doorway; inject the real per-facility inventory and local specifics or consolidate.
4. **Single-facility collapse** (Section 1): one facility gets zero separate size pages.

---

## 8. Best-in-class teardowns (real, live-verified 2026-07; full set in the example library)

**WINNER - Stop & Stor, 10x10 sizing guide** (`stopandstor.com/storage-solutions/size-guide/10x10`). Couples the generic size education to REAL local priced inventory (West Brighton ~$189/mo first month free; Co-op City small unit $56), a genuine building feature ("exclusive Drive-Thru Building at the Bronx location"), and a truthful risk-reversal: "prices are held steady for an entire year in writing" (a real Law-20 guarantee, not a hollow badge). Family-owned since 1980. This is the model: the size math is table-stakes; the local inventory + the written price-lock are the moat.

**WINNER - Public Storage 10x10 size guide** (`publicstorage.com/size-guide/10x10-storage-unit/`). The honesty-hedged capacity math ("144 boxes maximum; 100 is more realistic," 800 cu ft, room-by-room what-fits) is a small but real information-gain signal most competitors skip. The model for the size-guide ASSET flavor (add an original size diagram/calculator to make it link-worthy).

**LOSER - Public Storage programmatic "10x10 near [city]"** (`publicstorage.com/self-storage-ga-atlanta/10x10-storage-units`). H1 swaps city + facility grid, keeps everything else static; the same skeleton scales to San Antonio, LA, NY, Phoenix live. It survives partly on real inventory but the editorial adds no information gain. The verified doorway.

**LOSER - Big Tex 10x10 blog internal contradiction** (`bigtexstorage.com/about/blog/how-big-is-a-10x10-storage-unit/`). The body says "150 to 200 boxes," its own FAQ says "up to 80." A page that contradicts itself on the one number the reader came for fails the accuracy bar (G1). Every capacity number must be internally consistent and tied to a stated packing assumption.

---

## 9. Schema (see `knowledge/foundations/schema-library.md`, section 8b, for the full bundle)

- **`Product` + `Offer` + `UnitPriceSpecification`** for the unit, ONLY when a real current price is on the page: `businessFunction: http://purl.org/goodrelations/v1#LeaseOut` (a rental, not a sale), `price` / `priceCurrency: USD` / `unitCode: MON` / `billingDuration: 1`, `availability` reflecting TRUE inventory (`InStock`/`SoldOut`/`LimitedAvailability`). For a multi-unit range use `AggregateOffer` (`lowPrice`/`highPrice`/`offerCount`) matching the on-page table.
- **`BreadcrumbList`** on every unit-size page (Home > City > [Size] Storage Units) - the one reliably-rendered storage rich result.
- **`FAQPage`** mirroring the visible FAQ - kept for AI extraction, no SERP dropdown (deprecated 2026-05-07).
- **NEVER** `aggregateRating`/`review` on the facility node (SS-SCHEMA1). Expect NO pricing rich result (Section 4). Validate with `scripts/schema_validator.py`.

---

## 10. Meta formulas

- **Title:** `[Size] Storage Units in [City], [ST] | From $[X]/mo | [Brand]` (keep under ~60 chars; the from-price in the title is how storage surfaces price the SERP will not render from schema).
- **Description:** `[Size] units ([sq ft], holds [real equivalent]) in [City]. [Live/real price + move-in special with its real condition]. [Reserve/Rent CTA + phone].` Under ~155 chars, no fabricated urgency.
- **H1:** exact size + exact city, matching the schema `name`/`areaServed`.

---

## 11. Finished-page checklist (binary; every NO blocks publish)

**Dual-node + doorway gate:**
- [ ] This is a city-level money page (not the brand-wide guide); the guide, if built, is a separate `/write-local-asset` node.
- [ ] `storage.operator_type != single_facility` (single-facility clients build NO separate size pages).
- [ ] Real local inventory/price for this size at a real facility is on the page (not "call for pricing").
- [ ] Strip the city + the inventory board: does the body still read complete for any facility anywhere? (YES = doorway = FAIL.)
- [ ] `duplication_gate.py` clean against sibling size/city pages.
- [ ] At least one first-party local specific this page alone carries.

**Non-thin content contract (all present):**
- [ ] Exact dimensions + sq ft + cu ft.
- [ ] Physical-world equivalent.
- [ ] Room-grouped what-fits inventory (real items).
- [ ] Box-count with the honesty hedge; capacity numbers internally consistent across body and FAQ.
- [ ] Up/down adjacent-size cross-links.
- [ ] Truck size and/or a size visual.

**Conversion + compliance:**
- [ ] H1 = exact size + exact city; from-price or honest availability above the fold.
- [ ] One primary CTA matched to intent (Rent-online urgent / Reserve-free planned); click-to-call one tap away.
- [ ] Move-in special conditions (admin fee, required add-ons) disclosed in-line, not footnote (SS-6).
- [ ] No hard-coded scarcity or resetting countdown; no "rate locked" unless real (SS-CV1/2, SS-8).
- [ ] Security claims carry a spec, not "safe and secure" (SS-3); no clean-history claim (SS-4).
- [ ] Climate claim states the real held range; no moisture promise without humidity control (SS-5).
- [ ] Reviews in HTML; no self-serving review schema (SS-SCHEMA1).

**Local-SEO + technical:**
- [ ] URL is a flat subfolder on the main domain; one pattern site-wide; not a subdomain-per-size/city.
- [ ] Internally linked up (facility, city hub), across (adjacent sizes, storage types, size-guide asset); not orphaned behind JS.
- [ ] NAP identical across page, schema, GBP.
- [ ] Schema: `SelfStorage` (facility) + `Product`/`AggregateOffer` (only with real price) + `BreadcrumbList` + `FAQPage`; validates; no pricing-rich-result promise.
- [ ] No detector-evasion, no humanizer chain (Law 8).
- [ ] Universal humanization + client brand voice both applied; no storage cliches (`knowledge/voice/vocabulary-blocklist.md` self-storage set + `knowledge/voice/self-storage-voice.md`).

A page missing any box is an unfinished draft. The output contract (CLAUDE.md) applies: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`, all five present, every gate marked pass with evidence.

---

## Sources

- Internal research: `research/self-storage-2026-07/01-site-architecture.md` (page taxonomy, the collapse rule, non-thin contracts), `02-keyword-clusters.md` (the dual-node split), `03-schema-structured-data.md` (Product/Offer/LeaseOut, no pricing rich result), `04-conversion-cro.md` (CTA split, truthful urgency), `05-voice-language.md` (renter's size question, mechanism rule), `08-example-teardowns.md` (Stop & Stor, Public Storage, Big Tex).
- Real pages verified this build: Stop & Stor 10x10 (`stopandstor.com/storage-solutions/size-guide/10x10`); Public Storage 10x10 guide + Vegas money page (`publicstorage.com/size-guide/10x10-storage-unit/`, `/self-storage-nv-las-vegas/10x10-storage-units`); CubeSmart 10x20 guide (`cubesmart.com/storage-resources/size-guide/10x20-storage-unit/`); Big Tex 10x10 (product page vs blog contradiction).
- System: `knowledge/verticals/self-storage.md` (overlay SS-* rules), `knowledge/playbooks/service-city-page.md` (the general money-page doorway discipline), `knowledge/playbooks/examples/self-storage.md` (the teardown corpus), `knowledge/foundations/schema-library.md` (the SelfStorage bundle), `knowledge/doctrine/local-content-laws.md` (Laws 15, 16, 20).

Directional figures; re-verify the client's real prices, dimensions, and inventory at write time. No local specific ships from memory.
