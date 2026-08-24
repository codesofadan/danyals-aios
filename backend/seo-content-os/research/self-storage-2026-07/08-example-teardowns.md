# Self-Storage Page Teardowns: The Example-Library Seed (US)

Research run: 2026-07-23 PKT. Territory 08 of the self-storage knowledge base.
Purpose: real, live self-storage pages torn down GOOD vs BAD, grouped by the seven page types the system writes, so this file can seed `knowledge/playbooks/examples/self-storage.md` (the vertical teardown file the DRAFT and HUMANIZE stages load).

**IRON LAW honored.** Every page below was fetched this run. Where a fetch was blocked, 500'd, or 404'd, it is listed in the sourcing note and is NEVER presented as a teardown; the few pattern-level entries are explicitly labeled `[PATTERN]` and carry no invented facts. Every price, heading, and spec quoted is from the page as retrieved. The fetcher converts HTML to markdown and strips JSON-LD, so any schema claim is labeled as inference, not inspection.

Cross-refs: gates in `knowledge/quality-gates/gates.md`; the six content laws in `knowledge/doctrine/local-content-laws.md`; schema verdicts in `03-schema-structured-data.md`; CRO patterns in `04-conversion-cro.md`; Experience markers in `06-eeat-experience.md`.

## Sourcing note: what fetched and what did not

- **Fetched clean and torn down:** publicstorage.com, cubesmart.com (homepage + 3 facility/directory pages), storage-mart.com (homepage + about), storagekingusa.com (2 city pages), capitolaselfstorage.com, bigtexstorage.com (blog + product page), stopandstor.com, storage.com (cost guide), afamilystorage.com, polkcountystorage.com, advantagestorage.net, storagecity.biz, myplaceselfstorage.com.
- **Blocked / errored this run (never torn down below):** `extraspace.com` (HTTP 403, both the 10x10 unit page and the cost guide), `sparefoot.com` (403), `thelockup.com` (403), `storagestar.com` (500), `alansfactoryoutlet.com` (403), `astoragedepot.com` (404), `uhaul.com` 10x10 guide (ECONNRESET). Consistent with `06-eeat-experience.md`: Extra Space blocks automated fetches. Anything about these is `[PATTERN]`, not a teardown.

---

## The scoring rubric (how each teardown is judged)

Every teardown scores the page on the levers that actually move storage rankings and conversions, drawn from the sibling research:

1. **Live, unit-level price + availability** (the #1 storage conversion lever, `04-conversion-cro.md` s1.1). Specific dollar rate per size, dated, ideally PMS-fed. Generic "call for pricing" or "affordable units" is a fail.
2. **Provable local specificity** (Law 16, gate G1). Does a sentence break when pasted onto the facility across town? Real addresses, real neighborhood landmarks, real held temperature range, real security specs.
3. **Information gain** (Law 15, gate G1 `information_gain_scorer.py`). Does the page add something the top 10 results do not already say?
4. **No doorway / no near-duplicate** (gate G3 `duplication_gate.py`). City-swap templates fail.
5. **E-E-A-T Experience proof** (Law 16, gate G2). Named people, dated first-party artifacts, credentials.
6. **Truthful conversion + honest schema** (Law 20, gate G13; `03-schema-structured-data.md`). No fabricated urgency/availability, no self-serving review stars.

---

# 1. Facility / location page (single facility)

The money-adjacent page: one physical building, its NAP, its live unit board, its neighborhood. The bar: live per-size prices + a genuinely local description paragraph + real reviews. The trap: a NAP-and-unit-grid shell with zero unique editorial, or a description paragraph templated across every location.

## GOOD

### G-1a. CubeSmart, 4211 Bellaire Blvd, Houston TX
`https://www.cubesmart.com/texas-self-storage/houston-self-storage/3764.html`
- **What it does right:** Live, unit-level web pricing pulled from inventory, per size and per attribute: 5x5 climate/1st-floor **$76.20/mo**, 10x10 climate/elevator **$115.80/mo**, 10x20 climate/elevator **$231.00/mo**, and a genuine specialty unit (wine storage 3'x3'x2.5' **$17.00/mo**). Online price shown distinct from in-store price. Real ratings surface: **4.8 stars / 493 reviews**.
- **The local paragraph is provable:** "Conveniently located just south of West Loop S" with named neighbors: **Betsy's at Evelyn's Park, LA Fitness, Bellaire Town Square, Texas Medical Center, Rice University**. ~220 words of location-specific editorial. That paragraph breaks on the paste (Law 16 pass) because a facility in another city cannot claim Rice University proximity.
- **Principle exemplified:** live inventory (lever 1) + real landmark specificity (lever 2) + real ratings (lever 5) on one page. This is the enterprise standard the money page must beat or match.

### G-1b. CubeSmart, 4717 Strack Rd, Houston TX
`https://www.cubesmart.com/texas-self-storage/houston-self-storage/4305.html`
- **What it does right:** Full live price table (5x10 climate **$38/mo** online vs $76 in-store, 10x20 climate **$157.50/mo**, 22ft outdoor parking **$39/mo**), and a description anchored to real local geography: "just off Cypress Creek Parkway, near Champions Forest Drive," neighbors **Perry's Steakhouse & Grille, Pappasito's Cantina, Lifetime Fitness, Houston Northwest Medical Center, Meyer Park**. Rating **4.4 / 191**.
- **Why it still passes despite templating:** the middle localized block carries real, checkable proximity facts. The differing star counts across the two facilities (4.8/493 vs 4.4/191) indicate the aggregate rating is genuinely per-location, not a single site-wide number stamped everywhere.

### G-1c. Capitola Self Storage (independent, homepage doubles as facility page)
`https://capitolaselfstorage.com/` (fuller teardown under Homepage, s4)
- Included here because it is the independent-operator model of a facility page done right: real held climate range "**between 50 to 80 degrees fahrenheit**," gate access "**6am to 10pm Everyday**" stated separately from office hours, and live per-unit prices with honest availability states (5x9 $165/mo, 5x5 $110/mo "limited availability," 5x5 1st-floor $132/mo "sold out"). Showing a unit as sold-out is the anti-fabrication move (Law 20): it proves the board is real.

## BAD / penalty-risk

### B-1a. Same featured review + boilerplate opener across CubeSmart facilities `[OBSERVED PATTERN]`
- Across the two different CubeSmart Houston facility pages fetched above, the **same featured customer quote appeared verbatim** ("The CubeSmart experience has been very positive. Clean and secure, and very helpful and friendly service..." attributed to "Larry W."), and both opened with the same templated shell ("Welcome to CubeSmart Self Storage located at [address]...").
- **Why it is a risk:** duplicated editorial/review content reused across many location URLs is the soft edge of the doorway problem (gate G3). The aggregate star counts differ by facility (real), but a hand-picked identical testimonial reused site-wide is not location Experience; if that same quote were ever wrapped in per-facility `Review` schema it would misrepresent a site-wide blurb as facility-specific (see `03-schema-structured-data.md` on self-serving/misapplied review markup). *Caveat: I read rendered text, not JSON-LD; this is a content-duplication observation, not a confirmed schema violation.*
- **Lesson for the system:** every facility page needs its own reviews and its own opening sentence, not a stamped shell + a mascot testimonial.

### B-1b. MyPlace Self-Storage, Dallas facility page `[PATTERN, could not verify body]`
`https://myplaceselfstorage.com/storage-locations/tx/dallas/6434-maple-ave/dallas-climate-controlled-storage/`
- WebFetch retrieved **only navigation chrome and the footer phone number (1-877-700-0155)**; no H1, no body copy, no unit board came back. The most likely cause is client-side rendering where the crawlable HTML is near-empty.
- **Why it is a risk (labeled):** a facility page whose substance exists only after JavaScript executes is an indexability and thin-to-crawler risk (see `01-site-architecture.md` territory on rendering). I am NOT asserting the page is thin for human users; I could not retrieve its rendered content. It is logged as a "verify server-rendered HTML" cautionary pattern.

### B-1c. Zero-editorial NAP-grid facility page `[PATTERN]`
- The dominant failure mode for independent facility pages: address + hours + a unit-size table + a stock orange-door photo, and nothing that breaks on the paste. Polk County Storage (s5 below, ~350 words, no prices, no named people) is the live independent instance. The fix is not more words; it is the security-spec / climate-range / named-manager Experience block from `06-eeat-experience.md`.

---

# 2. Storage-type page (e.g. "climate controlled storage [city]")

Intent: someone who has decided on an attribute (climate, drive-up, 24-hr, RV) and a city. The bar: live inventory for that attribute across the city's facilities PLUS real information gain about the attribute (the honest, unregulated-term angle). The trap: the city-swap doorway.

## GOOD

### G-2a. Public Storage, Climate Controlled Storage Units in Dallas TX
`https://www.publicstorage.com/self-storage-tx-dallas/climate-controlled-storage-units`
- **What it does right:** genuine live inventory across **7 real Dallas facilities with full street addresses** (2425 Canton St 75226; 2439 Swiss Ave 75204; 1611 Chestnut St 75226; 903 Slocum St 75207; 2320 N Central Expy 75204; 207 Avery St 75208; 2420 N Haskell Ave 75204) with per-unit rates spanning **$10/mo to $301/mo** and disclosed fees ("one-time $29 admin fee," "$1 First Month Rent Where Available"). That real, priced, addressed inventory is the reason it earns the query (lever 1).
- **Principle exemplified:** for a storage-type-in-city page, the live multi-facility board IS the value. Aggregators cannot beat the operator's own real-time rates.
- **Where it stops short (the system must exceed it):** editorial is thin and generic ("Trusted nationwide since 1972"), no Dallas-specific climate reasoning. A truly great version adds the operator's own held range and the unregulated-term honesty lever (below).

### G-2b. The information-gain bar for this page type, proven live
- Big Tex publishes its actual held range, "**climate-controlled units maintain a stable temperature range of 58 F to 78 F**" (`https://www.bigtexstorage.com/storage-options/storage-units/10x10/`); Capitola publishes "**50 to 80 degrees fahrenheit... constant humidity**" (`https://capitolaselfstorage.com/`). Per `06-eeat-experience.md` (Marker 3), stating your *own* setpoint and explaining that "climate controlled" is not an industry-standardized term is the exact information-gain move (Law 15) that separates a real climate page from a doorway. Neither of the Storage King city pages below does this.

## BAD / penalty-risk

### B-2a & B-2b. Storage King USA: near-identical climate-controlled city pages (VERIFIED doorway pair)
`https://www.storagekingusa.com/locations/texas/dallas/climate-controlled/` and `https://www.storagekingusa.com/locations/florida/tallahassee/climate-controlled/`
- **The doorway proof (two live URLs, fetched and compared):**
  - Dallas H2: "**Do I Need a Climate-Controlled Unit in Dallas?**" / intro leads on "Dallas faces heat most of the year."
  - Tallahassee H2: "**Why Do I Need Climate-Controlled Storage in Tallahassee, FL?**" / intro leads on "Protect your belongings from the blazing Florida sun."
  - **Same generic body sentence on both**, city-agnostic: "Several common household items are sensitive to extreme temperatures and can sustain damages from prolonged exposure."
  - Same structural skeleton, same "recommended items" list (electronics, leather furniture, books), same closing CTA ("Reserve Your [City] Climate-Controlled Storage Unit"). Both start "from $62.00/month."
- **What fails:** gate G3 (`duplication_gate.py`) doorway/near-duplicate; Law 15 (zero information gain, no real per-city climate data, humidity numbers, or local specifics); Law 16 (nothing breaks on the paste except the swapped city noun). The only unique tokens are the city name and a landmark or two ("Florida State University," "Lake Jackson").
- **Why it is the canonical BAD storage-type example:** it is a real, indexed, scaled template where the differentiator is a find-and-replace on the city. This is exactly the pattern Google's scaled-content-abuse policy targets.

### B-2c. Aggregator listicle occupying the query `[PATTERN]`
- Queries like "climate controlled storage units Dallas" surface RentCafe ("30 Best..."), StorageCafe ("Top 20..."), and Storage.com city hubs above the operators. These rank via aggregated inventory + review volume, not first-hand facility Experience. For an operator, the lesson is not to imitate the listicle but to out-specify it: the aggregator cannot publish your held temperature range, your camera count, or your named manager.

---

# 3. Unit-size page (e.g. "10x10 storage units")

Intent: "will my stuff fit / what does it cost." The bar: correct dimensions + a concrete what-fits list + live price + a link to real nearby inventory + internal consistency. The trap: commodity what-fits copy that is identical across every operator, and self-contradicting capacity numbers.

## GOOD

### G-3a. Stop & Stor, 10x10 Storage Unit Sizing Guide (NYC operator)
`https://www.stopandstor.com/storage-solutions/size-guide/10x10`
- **What it does right:** couples the generic size education to **real, local, priced inventory and first-party proof**: specific facility rates (West Brighton/Port Richmond ~**$189/mo** first month free; Queens Village/Bellerose ~**$276/mo**; Co-op City small unit **$56**), a genuine differentiator ("exclusive **Drive-Thru Building** at the Bronx location"), and a real trust mechanism: "**prices are held steady for an entire year in writing**" (a truthful risk-reversal, Law 20 / gate G13). Family-owned since **1980**, NYC five-boroughs. ~1,800-2,000 words, 10-pair FAQ.
- **Principle exemplified:** a size page becomes non-commodity when it carries the operator's real prices, a real building feature, and a real guarantee. The size math is table-stakes; the local inventory and the written price-lock are the moat.

### G-3b. Big Tex Storage, 10x10 unit product page (Houston operator)
`https://www.bigtexstorage.com/storage-options/storage-units/10x10/`
- **What it does right:** operator-owned page (not a blog) with a question-led H2 stack primed for AI extraction ("How Big," "How Much," "Can a King-Size Bed Fit," "How do I find a 10x10 near me"), the real held climate spec (**58 F to 78 F**), on-site managers, door alarms, and links to **six named Houston facilities** (Museum District 4503 Montrose Blvd; Heights 730 E 11th; Garden Oaks 3480 Ella Blvd; Montrose-Richmond 1810 Richmond; River Oaks 3202 Weslayan; Uptown-Tanglewood 4944 Woodway). Truthful CTA: "no deposits or hidden fees."
- **Where it stops short:** pricing is generic ("competitive pricing," reservation offsite) rather than live per-facility. Add the live rate and it is fully compliant.

### G-3c. Public Storage, 10x10 size guide (brand-wide reference)
`https://www.publicstorage.com/size-guide/10x10-storage-unit/10x10-storage-unit.html`
- **What it does right:** intellectually honest capacity math instead of hype: "~144 medium boxes maximum; **100 boxes is more realistic**," 800 cu ft, what-fits organized by room (Bedroom/Living/Kitchen/Business/Garage), FAQ structure, and a "See Unit Prices Near Me" bridge to live inventory. The "more realistic" hedge is a small but real information-gain signal (most competitors quote only the maximum).
- **Where it stops short:** no size-comparison visual, diagram, or calculator; no first-hand operator detail (it is a brand-wide asset, not a facility page).

## BAD / penalty-risk

### B-3a. Public Storage, programmatic "10x10 storage units near [City]" (VERIFIED doorway)
`https://www.publicstorage.com/self-storage-ga-atlanta/10x10-storage-units`
- **What fails:** H1 "10x10 Storage Units Near You in **Atlanta, GA**" on a template that swaps city + facility grid and keeps everything else static ("Find Storage Near You," "Trusted nationwide since 1972," "$1 first month"). <5% Atlanta-specific editorial; the same skeleton demonstrably scales to San Antonio, Los Angeles, New York, Phoenix (all live at the same URL pattern, surfaced this run). High doorway risk (gate G3). It survives partly on real inventory (facility #2 at 647 Donald Lee Hollowell Pkwy lists a 10x10 at **$128/mo**), but the editorial layer adds no information gain.
- **The tell:** the page is 2,500-3,000 words yet almost all of it is repeated unit-card boilerplate. Word count without information gain is the doorway signature.

### B-3b. Big Tex 10x10 blog: internal capacity contradiction (VERIFIED accuracy defect)
`https://www.bigtexstorage.com/about/blog/how-big-is-a-10x10-storage-unit/`
- **What fails:** the ~3,200-word body says a 10x10 fits "**150 to 200 medium-sized moving boxes**," while its own FAQ on the same page says "**up to 80 medium-sized boxes**." A page that contradicts itself on the one number the reader came for fails the accuracy bar behind gate G1 / Law 15 and undercuts the very Experience it is trying to claim. (Note the discipline gap: the same operator's *product* page, G-3b, is tighter.)
- **Lesson:** long blog explainers are where uncaught, un-sourced capacity claims accumulate. Every capacity number must be internally consistent and, ideally, tied to a stated packing assumption.

### B-3c. Commodity what-fits copy `[PATTERN]`
- The near-universal 10x10 boilerplate ("about the size of half a one-car garage," "holds a 1-2 bedroom apartment") appears almost verbatim across Extra Space, SpareFoot, The Lock Up, Storage Star, and My Golden Storage (all surfaced this run; several 403'd on fetch, so this is pattern-level, not a teardown of any one URL). It is not penalizable on its own, but a size page that is *only* this copy has zero information gain and no reason to outrank the incumbents. The differentiator must be live local price + a first-party detail (as G-3a does).

---

# 4. Homepage

Job: entity anchor + primary conversion. The bar: instant find-a-facility, one real proof cluster (counters, credentials, real reviews), and a specific value proposition. The trap: "peace of mind" wallpaper with no facts.

## GOOD

### G-4a. Capitola Self Storage (independent, Santa Cruz County)
`https://capitolaselfstorage.com/`
- **What it does right:** the homepage is a wall of provable first-party facts, exactly the Experience moat (Law 16, `06-eeat-experience.md`): on-page live counters "**5,420 Days Without a Security Breach**," "**4,366 Satisfied Customers**," "**15 Years in Business**"; real held climate range (50-80 F); security specifics ("24/7 digital video surveillance," "Each unit is individually alarmed"); gate access (6am-10pm) stated separately from office hours; live unit prices with honest availability ("limited availability," "sold out"); NAP (809 Bay Ave Suite H, Capitola CA 95010; (831) 465-0600); and 12 named 5-star reviews.
- **Principle exemplified:** an independent beats the chains on the homepage not with budget but with un-fakeable operational facts. The dated breach counter is the storage equivalent of a contractor's license number: a checkable number a competitor cannot copy without lying.

### G-4b. CubeSmart homepage (enterprise)
`https://www.cubesmart.com/`
- **What it does right:** conversion-first architecture: a persistent "Enter Zip, City or State -> Find Storage" search in header, hero, and footer; concrete amenity language ("24-hour Video Recording," "Drive-Up and Climate-Controlled Units," "Extended Access Hours"); explicit size taxonomy (5x5 through 10x30) that feeds internal linking; and a "not sure what size?" bridge. The search-first pattern is correct for a 1,000+ facility brand where the user's real first job is "find my city."
- **Where it leans generic:** "peace of mind," "premium affordable," "highest service rating in the industry" (unquantified). The search UX carries the page; the copy is forgettable. For an enterprise this is acceptable; for an independent it would be a miss.

## BAD / penalty-risk

### B-4a. StorageMart homepage (generic-value wallpaper)
`https://www.storage-mart.com/`
- **What underdelivers:** the homepage leans on mood copy, "Self storage is more than just a place to store your belongings... peace of mind is easier to find," "Self Storage to Support All Life's Transitions," with a single quoted Google review (Joe J.) and badge logos (Trustpilot, McAfee, EY Entrepreneur of the Year). No years-in-business, no facility count, no live proof cluster on the homepage itself.
- **The irony worth flagging:** StorageMart owns one of the strongest About pages in the industry (s5, G-5a, the Burnam family legacy) yet strands all of that Experience one click away and fronts the homepage with generic aspiration. This is a real, common mistake: the proof exists in the org but is not surfaced where conversion happens. Not a penalty, but a wasted moat.

### B-4b. Polk County Storage homepage (thin independent)
`https://www.polkcountystorage.com/`
- **What fails:** ~350 words total; a family-heritage *claim* ("family-owned-and-operated business has been passed down to us through many generations... serving the community since 1985") with **no named people, no owner photo, no dated milestone, no unit prices, no security or climate specifics, no reviews, no schema**. Real operational facts do exist (address 590 Hoffman Rd, Independence OR 97351; seasonal gate hours), which keeps it honest, but the heritage story is asserted, not shown (Law 16 fail, gate G2). This is the independent-operator baseline the system is built to beat.

---

# 5. About / team page (the E-E-A-T surface)

Job: convert trust; carry Person/Organization entity signals. The bar: named humans with dated, checkable histories and credentials, photos, and a specific origin story. The trap: "family owned, we care" with no human named and no artifact shown.

## GOOD

### G-5a. StorageMart, About Us
`https://www.storage-mart.com/about-us`
- **What it does right:** a dated, named, checkable origin story: "**In 1974, while on vacation with his family in Texas, Gordon saw the self storage industry for the first time...**"; founders **Gordon and Mickey Burnam**; first location on Rangeline Street, Columbia MO; "four generations of Burnams" in the company; founder's 2017 passing noted. Named executives with **verifiable third-party credentials**: Cris Burnam (CEO, Ernst & Young Entrepreneur of the Year, BBB Torch Award), Mike Burnam (President, **Self-Storage Hall of Fame**, SSA board), Ryan McKenzie (CFO); three executive headshots. Concrete milestones ($3B+ Manhattan Mini Storage acquisition, 2021).
- **Principle exemplified:** every E-E-A-T lever at once (Law 16, gate G2): real people (Experience + Authoritativeness), dated events (checkable), external credentials (Trust). Hall-of-Fame and EY awards are third-party-verifiable, the strongest kind.

### G-5b. Advantage Storage, About Us (Sherman TX operator)
`https://www.advantagestorage.net/about-us/`
- **What it does right:** an entire named leadership roster with **dated, specific bios** rather than titles: founder **Rick Jones** (1996, "35 years of industry experience"); "Cory Horne graduated with a business degree from North Carolina State University in **2000**," progressed through Mobile Mini and Optivest before joining in **2012**; Davis Deadman "grew a **$50 million rural community bank into a $600 million** urban commercial bank"; credentials cited (MBA, CFA, CGMA). ~2,100 words of genuine narrative.
- **Where it stops short:** no photos of the named individuals (a real gap, since original headshots are a first-party Experience artifact per `06-eeat-experience.md` Marker 1 and support Person schema, `03`). Fixing that would make it best-in-class.

## BAD / penalty-risk

### B-5a. A Family Storage, About Us (Tucson AZ)
`https://www.afamilystorage.com/company-pages/about-us-a-family-storage-in-tucson-and-green-valley-az/`
- **What underdelivers:** claims scale ("largest locally and privately owned storage company in Tucson," 19 locations, since 1998) and community ties ("partner with local schools, charitable organizations and sports teams") but names **not a single person**, shows **no owner or staff photo**, quotes **no review**, carries **no schema**, and leans on unprovable comparatives: "we're not just bigger than other storage companies, **we're better!**" and "we understand your unique needs."
- **What fails:** gate G2 (E-E-A-T without a named human or artifact) and Law 16 (the "we're better" line is pure assertion; it survives the paste onto any competitor). The genuine local detail it does have (40+ named neighborhood service areas, Bluetooth entry) shows the raw material for a good page exists; it just never puts a person or a proof on the page.

### B-5b. Polk County Storage (see B-4b)
- Doubles as a failed About surface: a multi-generational family business since 1985 that never names a generation, a founder, or a year beyond "1985," and shows no photo. The single most valuable, un-fakeable asset an independent has (the actual family) is claimed but never shown. Prime `sme-interviewer` target.

---

# 6. Cities-served / service-area page

Job: communicate coverage without spawning doorway pages. The bar: real, granular local geography (towns, counties, landmarks, distances) tied to genuine operating knowledge, or a clean facility directory. The trap: a wall of city links each fronting a near-identical thin page (classic doorway).

## GOOD

### G-6a. Storage City, service area (Smith Mountain Lake / Franklin County VA)
`https://www.storagecity.biz/`
- **What it does right:** granular, real, checkable local geography rather than a city-list dump: "Since **1997**, customers throughout **Franklin County, Pittsylvania County, Rocky Mount, Glade Hill, Moneta, Penhook, Union Hall, Hardy, and Smith Mountain Lake** have trusted Storage City," two real facilities with addresses (Penhook 3465 Smith Mountain Rd; Glade Hill 7770 Old Franklin Turnpike; (540) 576-1113), and a local resources/blog block ("contractors throughout Franklin County," SML guides) that demonstrates market knowledge.
- **Principle exemplified:** a service-area page earns its keep by proving real local knowledge (specific small towns most competitors omit, lake-community context), not by listing 40 metros it barely touches. The named small towns break on the paste (Law 16 pass).
- **Gap:** no unit prices on this page; the coverage story is strong but should bridge to live inventory.

### G-6b. CubeSmart, Houston-area directory
`https://www.cubesmart.com/texas-self-storage/houston-self-storage/`
- **What it does right (mostly):** a genuine facility directory, **49 real facilities** with addresses, per-facility ratings (4.4-4.9) and distances, plus named suburbs (Pearland, Humble, Sugar Land, Missouri City). As a directory-style service-area page it is legitimate: the value is real, priced, rated inventory, not spun editorial.
- **Why it is GOOD-with-a-warning:** the editorial wrapper is generic ("Whether you're relocating an office or stashing items away...," "peace of mind"). Moderate doorway risk (gate G3) sits in the templated promotional layer; the real facility grid is what saves it. Contrast with B-6a: a directory of real facilities is fine; a directory of thin per-city *doorway* pages is not.

## BAD / penalty-risk

### B-6a. The near-identical per-city landing page, proven live
`storagekingusa.com` Dallas + Tallahassee (URLs in s2)
- The service-area failure mode in the flesh: a family of "[attribute] storage in [city]" pages that share one skeleton and one city-agnostic paragraph, differing only by the city noun and a landmark. When a service-area hub links out to 20-40 of these, the hub becomes a doorway index. Gate G3 / scaled-content-abuse. The system's answer (`knowledge/foundations/topical-map-protocol.md`): a city gets its own page only on real first-party evidence; otherwise it is an index-only entry, not a thin page.

### B-6b. The city-link carpet with duplicated per-city copy `[PATTERN]`
- The classic bad "Areas We Serve" page: a paragraph of boilerplate ("Proudly serving [City] and surrounding areas with clean, secure, affordable storage") repeated under 30 city headers, each linking to a page that is the same boilerplate with the city swapped. No fetched single URL is quoted here because the specific instance varies, but the mechanism is the same one verified in B-6a. The discriminator: does each "served" place carry a *unique, checkable* local fact (a real distance, a real landmark, a real facility), or only a swapped noun? If the latter, it is a doorway.

---

# 7. Size-guide / cost-guide asset (the linkable asset)

Job: earn links and AI-answer citations with genuinely useful, sourced data. The bar: original or clearly-sourced data, dated, with real numbers and methodology. The trap: uncited round-number ranges rehashed from everyone else (no information gain, no citation-worthiness), or off-topic content from a non-storage site.

## GOOD

### G-7a. Storage.com, Self-Storage Pricing Guide
`https://www.storage.com/blog/how-much-does-a-storage-unit-cost/`
- **What it does right:** **proprietary, dated, methodologically-stated data** - the single biggest citation-earning signal. National averages labeled "**Based on Storage.com internal transaction data, January-June 2026**... derived from city-level pricing data across **150+ U.S. markets**": 5x5 **$35.58**, 5x10 **$51.77**, 10x10 **$81.70**, 10x15 **$110.17**, 10x20 **$131.82**, 15x20 **$194.60**, 20x20 **$230.25**. Real premiums with numbers: climate control "**15% to 30% more**"; indoor access "up to **50% more**." External corroboration cited (RentCafe April 2026 rent-per-sqft comparison).
- **Principle exemplified:** this is a citable asset (GEO, `03`/geo research). Precise non-round numbers ($81.70, not "~$80"), a named dataset, a date, and a market count are exactly what an AI answer engine and a journalist will cite. It manufactures information gain (Law 15) instead of restating it.

### G-7b. Public Storage, 10x10 size guide (see G-3c)
`https://www.publicstorage.com/size-guide/10x10-storage-unit/10x10-storage-unit.html`
- As a size-guide asset it clears the bar with honest capacity math ("100 boxes is more realistic" vs the 144 maximum), room-by-room what-fits, and a bridge to live prices. It would become link-worthy with an original size-comparison visual or calculator, which it currently lacks.

## BAD / penalty-risk

### B-7a. Public Storage, cost guide blog (big brand, thin + uncited)
`https://www.publicstorage.com/blog/public-storage/how-much-does-a-storage-unit-cost-a-complete-guide.html`
- **What fails, despite the brand:** ~600-700 words of **round-number, unsourced ranges** (5x5 "$40-$60," 10x10 "$90-$130," large "$140-$220," climate "+$10-$30") with, in the fetched text, **no research source, survey, or dataset cited** and clichE opener ("Just like real estate, location drives pricing"). It names NYC and San Francisco as expensive but attaches no actual figures to them.
- **Why it is the instructive BAD:** it proves brand authority does not substitute for information gain. Set side by side with G-7a (same topic), Storage.com's precise, dated, sourced data is vastly more citable than Public Storage's vague ranges. An asset that only restates the consensus in rounder numbers earns no links and no AI citations (Law 15 fail). *Caveat: absence of a citation in the converted text is not absolute proof none exists in the raw page; the round-number ranges and generic framing are the independent tells.*

### B-7b. Off-topic retailer publishing a storage cost guide `[PATTERN, fetch blocked]`
`alansfactoryoutlet.com/blog/storage-unit-costs/` (HTTP 403 this run)
- Surfaced ranking for "storage unit cost 2026," but the domain's core business is sheds and carports, not self-storage. I could not fetch it (403), so this is labeled a pattern, not a teardown: a non-storage retailer ranking a storage-cost article is a topical-authority mismatch, the kind of thin, off-entity content the Dec 2025 helpful-content emphasis and E-E-A-T-for-all-queries stance disfavor. For an operator, it is also a reminder that generic cost content is a commoditized battlefield; the winning move is first-party data (G-7a), not another aggregated ranges post.

### B-7c. Aggregated-consensus round-number guide `[PATTERN]`
- The broad pattern behind B-7a: dozens of "how much does storage cost" pages (Move.org, RecNation, Storage Star, and others surfaced this run) recycle the same ~$35/$65/$90/$140 ladder without a dated first-party dataset. Legal, but zero information gain and near-zero citation odds. The system's cost-guide asset must ship the client's own market data or a clearly-sourced original cut, or it should not ship (Law 15, Law 18 enrolled-not-shipped).

---

## Appendix: the seven-type GOOD/BAD matrix (quick index)

| Page type | GOOD (live URLs) | BAD / risk |
|---|---|---|
| Facility / location | CubeSmart 3764 + 4305 (live price + local paragraph); Capitola | Site-wide identical review/opener across CubeSmart facilities; MyPlace body not server-rendered `[pattern]`; NAP-grid shells |
| Storage-type ([attr] [city]) | Public Storage Dallas climate (live 7-facility board); Big Tex/Capitola held-range info gain | Storage King Dallas vs Tallahassee near-identical doorway (verified pair); aggregator listicles `[pattern]` |
| Unit-size (10x10) | Stop & Stor (local price + written price-lock); Big Tex product page; Public Storage size guide (honest capacity) | Public Storage "10x10 near [city]" programmatic doorway; Big Tex blog 150-200 vs 80 box contradiction; commodity what-fits `[pattern]` |
| Homepage | Capitola (breach counter + live board); CubeSmart (search-first) | StorageMart (peace-of-mind wallpaper, proof stranded on About); Polk County (thin heritage claim) |
| About / team | StorageMart (Burnam legacy, named execs, credentials); Advantage (dated named bios) | A Family Storage (no named human, "we're better"); Polk County (unshown family claim) |
| Cities-served / service-area | Storage City (granular real VA towns since 1997); CubeSmart Houston directory (49 real facilities) | Storage King per-city doorway pair; city-link carpet with duplicated copy `[pattern]` |
| Size/cost guide asset | Storage.com (proprietary dated 150-market data); Public Storage 10x10 size guide | Public Storage cost blog (uncited round numbers); off-topic retailer `[pattern, 403]`; aggregated-consensus guides `[pattern]` |

## The five rules this teardown set proves (for the playbook example file)

1. **Live per-size price beats every adjective.** Every GOOD example carries real dollar rates or a real board; the doorways carry "from $62/mo" and stop.
2. **One paragraph that breaks on the paste saves the page.** CubeSmart's Rice-University/Texas-Medical-Center block is the difference between a facility page and a doorway; Storage King's city-swap paragraph is the doorway itself.
3. **Name a human, show an artifact.** StorageMart/Advantage name people with dated, credentialed histories; A Family Storage and Polk County assert "family" and never show one.
4. **A dated first-party number is the whole moat.** Capitola's "5,420 days without a breach" and Storage.com's "$81.70, Jan-Jun 2026, 150+ markets" are un-fakeable and citation-worthy; "peace of mind" and "$90-$130" are neither.
5. **Word count is not information gain.** The 3,000-word Public Storage city page and the 3,200-word Big Tex blog are longer than the pages that beat them and add less; length without a new, sourced fact is the doorway/thin signature (gate G3, Law 15).
