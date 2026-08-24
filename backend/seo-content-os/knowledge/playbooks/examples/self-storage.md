# Self-Storage Example Library: Real Pages, Torn Down (live-verified 2026-07)

The reference corpus for every self-storage page this system writes. Seven page types. For each: real GOOD examples (live URL, what it does right, why it ranks or converts, which gate/law/overlay-rule it exemplifies) and real BAD or penalty-risk examples (live URL where verified, otherwise a clearly-labeled real pattern, what fails, which gate catches it).

Governing law: `knowledge/doctrine/seo-system-doctrine.md` (Law 8: humanize with real facts, never detector-evasion) and `knowledge/doctrine/local-content-laws.md` (Law 15 information gain, Law 16 the experience moat, Law 20 no fabricated urgency). Read alongside `knowledge/verticals/self-storage.md` (the SS-* compliance rules), the page-type playbooks (`unit-size-page.md`, and the facility/service-city/homepage/about/service-area/local-asset playbooks used with the storage overlay), and the master intelligence in `research/self-storage-2026-07/00-MASTER-self-storage-intelligence.md`.

Every page here was fetched live in the window shown (2026-07). Where a fetch was bot-blocked (Extra Space and its Life Storage brand return HTTP 403), 500'd, or 404'd, the entry says so and is labeled a pattern, not an invented page. No business, URL, price, or spec below is fabricated; each was read off the live page. Re-verify perishable specifics (prices, review counts, promos) at build time.

## The self-storage reality that governs all seven page types

Before the examples, the five facts that make self-storage different from a service trade. Every teardown below turns on one of them.

1. **Storage is a near-commodity, so proof of the specific physical place is the entire moat.** A 10x10 at Facility A holds the same boxes as a 10x10 at Facility B. When the product is undifferentiated, the only durable edge is the first E of E-E-A-T: proof of THIS place and THIS operating practice, which a SERP-remix tool structurally cannot produce. The governing test (Law 16, the paste test): if a sentence stays true when pasted onto the facility across town, it is asserted and it fails. "Clean, safe, secure storage" survives the paste and is dead. "Over 40 HD cameras recording continuously across entry points, hallways, and parking lots" (Big Tex, real) breaks on the paste and is proven.

2. **Live per-unit price + availability is the #1 conversion lever AND an Experience signal.** "Facilities with live inventory outperform those without." A real-time board proves a real, operated facility; "call for pricing" is structurally lower-converting and proves nothing. The winning storage page = national-brand page structure + directory-grade live inventory + the one thing neither competitor has: a dated first-party local detail.

3. **The security slogan is a legal liability, not decoration.** "Safe and secure" can void the facility's own liability-limiting lease clause as fraud (`Dilbeck v. Yates`, GA 1992). Every security claim must be a concrete spec (camera count, individual door alarms, per-tenant gate code, on-site manager) or it is cut (overlay SS-3). The winners print specs; the losers print adjectives.

4. **"Climate controlled" and "insurance" and "free" are regulated-word traps.** "Climate controlled" has no legal definition; pairing it with a moisture promise without real humidity control is reliance liability (`DiSanto v. Safeco`; SS-5). A self-indemnity "protection plan" may never be called "insurance" (`Heckart`; SS-1). "First month free" needs the admin fee disclosed in-line, not in a footnote (16 CFR 251.1; SS-6).

5. **The city-swap doorway is the defining penalty risk.** The three-axis grid (facility x size x type x geography) mints near-identical pages by swapping tokens. Google's scaled-content-abuse policy is written to catch it, and the pattern is live and verifiable in the wild (Storage King, Public Storage below). The defense: a real local inventory board + a unique local block + the strip-the-city test.

---

## 1. Facility / location page (single facility)

Job: rank + convert for one physical building - its NAP, its live unit board, its neighborhood. The bar: live per-size prices + a genuinely local description paragraph + real reviews. The trap: a NAP-and-unit-grid shell with zero unique editorial, or a description templated across every location.

### GOOD

**G1. CubeSmart, 4211 Bellaire Blvd, Houston TX** - `cubesmart.com/texas-self-storage/houston-self-storage/3764.html` (live, fetched 2026-07)
- What it does right: live, unit-level web pricing per size and attribute (5x5 climate/1st-floor $76.20/mo, 10x10 climate/elevator $115.80/mo, 10x20 climate/elevator $231.00/mo, wine 3'x3'x2.5' $17.00/mo), online price distinct from in-store. The local paragraph (~220 words) names real neighbors: Betsy's at Evelyn's Park, LA Fitness, Bellaire Town Square, Texas Medical Center, Rice University. 4.8 / 493 reviews (genuinely per-location, not a site-wide number).
- Why it wins: the Rice University / Texas Medical Center block breaks on the paste (Law 16 pass); the live board is the conversion lever (research 04). Live inventory + landmark specificity + real ratings on one page. The enterprise standard the money page must match.
- Gate/rule: G1 specificity, G3 anti-doorway (unique local block), the live-inventory conversion lever.

**G2. Capitola Self Storage** - `capitolaselfstorage.com/` (live; independent, homepage doubles as facility page)
- What it does right: the independent-operator model done right. Real held climate range "between 50 to 80 degrees fahrenheit," gate access "6am to 10pm Everyday" stated SEPARATELY from office hours (the access-vs-office distinction renters grieve over), live per-unit prices with honest availability ("limited availability," "sold out"). Showing a sold-out unit is the anti-fabrication move (Law 20) - it proves the board is real. On-page counters "5,420 Days Without a Security Breach," "4,366 Satisfied Customers," "15 Years in Business."
- Why it wins: an independent beats the chains not with budget but with un-fakeable operational facts. The dated breach counter is the storage equivalent of a contractor's license number - a checkable number a competitor cannot copy without lying.
- Gate/rule: Law 16 (dated first-party artifacts), SS-3 (security as counter/spec not adjective), SS-5 (real climate range), access-vs-office-hours honesty.

### BAD / penalty-risk

**B1. Same featured review + boilerplate opener across CubeSmart facilities** (observed pattern across the two Houston facility pages above)
- What fails: the same featured quote ("...Clean and secure, and very helpful and friendly service..." attributed to "Larry W.") and the same opener ("Welcome to CubeSmart Self Storage located at [address]...") appear verbatim across different facility URLs. Aggregate star counts differ per facility (real), but a hand-picked identical testimonial reused site-wide is not location Experience, and if it were ever wrapped in per-facility `Review` schema it would misrepresent a site-wide blurb as facility-specific (SS-SCHEMA1). (Caveat: read as rendered text, not JSON-LD; a content-duplication observation.)
- Gate/rule: G3 (soft doorway edge - duplicated editorial across location URLs); SS-SCHEMA1 (self-serving/misapplied review markup risk).

**B2. Pattern - the zero-editorial NAP-grid facility page** (clearly-labeled real pattern; the dominant independent-facility failure; live instance: Polk County, s5)
- What fails: address + hours + a unit-size table + a stock orange-door photo, and nothing that breaks on the paste. No live prices, no named manager, no security spec, no held climate range.
- Why: it is 100% commodity. The fix is not more words; it is the security-spec / climate-range / named-manager Experience block (`06-eeat-experience.md`).
- Gate/rule: G1 (no first-hand specific), Law 16 (asserted not shown).

---

## 2. Storage-type page ("[attribute] storage [city]", e.g. climate controlled / drive-up / RV)

Job: rank + convert for someone who has chosen an attribute and a city. The bar: live inventory for that attribute across the city PLUS real information gain about the attribute (the honest, unregulated-term angle). The trap: the city-swap doorway.

### GOOD

**G1. Public Storage, Climate Controlled Storage Units in Dallas TX** - `publicstorage.com/self-storage-tx-dallas/climate-controlled-storage-units` (live, fetched 2026-07)
- What it does right: genuine live inventory across 7 real Dallas facilities with full street addresses (2425 Canton St 75226; 2439 Swiss Ave 75204; 903 Slocum St 75207; and four more), per-unit rates $10-$301/mo, disclosed fees ("one-time $29 admin fee," "$1 First Month Rent Where Available"). The real, priced, addressed multi-facility board IS the value; aggregators cannot beat the operator's own real-time rates.
- Where it stops short (what the system must exceed): editorial is thin and generic ("Trusted nationwide since 1972"), no Dallas-specific climate reasoning, no facility's own held range. A great version adds the honesty lever (below).
- Gate/rule: the live-inventory conversion lever; SS-6 (fee disclosed with the "free" claim).

**G2. The information-gain bar, proven live** - Big Tex ("climate-controlled units maintain a stable temperature range of 58 F to 78 F," `bigtexstorage.com/storage-options/storage-units/10x10/`) and Capitola ("50 to 80 degrees fahrenheit... constant humidity")
- What it does right: stating your OWN setpoint and explaining that "climate controlled" is not an industry-standardized term is the exact information-gain move (Law 15) that separates a real climate page from a doorway (SS-5). Neither Storage King city page (below) does this.
- Gate/rule: Law 15 (information gain), SS-5 (honest climate claim with a real number).

### BAD / penalty-risk

**B1. Storage King USA: near-identical climate-controlled city pages (VERIFIED doorway pair)** - `storagekingusa.com/locations/texas/dallas/climate-controlled/` and `.../florida/tallahassee/climate-controlled/` (both live, fetched and compared 2026-07)
- What fails: same skeleton, same "recommended items" list, same closing CTA ("Reserve Your [City] Climate-Controlled Storage Unit"), both "from $62.00/month," and the SAME city-agnostic body sentence on both: "Several common household items are sensitive to extreme temperatures and can sustain damages from prolonged exposure." The only unique tokens are the city name and a landmark or two.
- Why it is the canonical BAD storage-type example: a real, indexed, scaled template where the differentiator is a find-and-replace on the city. Exactly the pattern Google's scaled-content-abuse policy targets.
- Gate/rule: G3 / `duplication_gate.py` (doorway), Law 15 (zero information gain), Law 16 (nothing breaks on the paste except the city noun), overlay SS-DOORWAY.

**B2. Pattern - the aggregator listicle occupying the query** (clearly-labeled real pattern)
- What it is: RentCafe ("30 Best..."), StorageCafe ("Top 20..."), Storage.com city hubs rank above operators via aggregated inventory + review volume. The lesson for an operator is not to imitate the listicle but to out-specify it: the aggregator cannot publish your held temperature range, your camera count, or your named manager.
- Gate/rule: the moat is first-hand facility Experience the directory lacks.

---

## 3. Unit-size page ("10x10 storage units [city]")

Job: rank + convert for "will my stuff fit / what does it cost." The bar: correct dimensions + a concrete what-fits list + live local price + real nearby inventory + internal consistency. The trap: commodity what-fits copy identical across every operator, and self-contradicting capacity numbers. Full spec in `unit-size-page.md`.

### GOOD

**G1. Stop & Stor, 10x10 sizing guide** - `stopandstor.com/storage-solutions/size-guide/10x10` (live, NYC operator)
- What it does right: couples the generic size education to REAL local priced inventory (West Brighton/Port Richmond ~$189/mo first month free; Co-op City small unit $56), a genuine building feature ("exclusive Drive-Thru Building at the Bronx location"), and a truthful risk-reversal: "prices are held steady for an entire year in writing" (a real Law-20 guarantee that also satisfies SS-8, because it is contractually true). Family-owned since 1980.
- Why it wins: a size page becomes non-commodity when it carries the operator's real prices, a real building feature, and a real written guarantee. The size math is table-stakes; the local inventory and the price-lock are the moat.
- Gate/rule: Law 16, SS-8 (a rate guarantee only where contractually true), the live-inventory lever.

**G2. Public Storage, 10x10 size guide** - `publicstorage.com/size-guide/10x10-storage-unit/` (live; the brand-wide ASSET flavor)
- What it does right: intellectually honest capacity math instead of hype - "144 medium boxes maximum; 100 boxes is more realistic," 800 cu ft, what-fits organized by room (Bedroom/Living/Kitchen/Business/Garage). The "more realistic" hedge is a small but real information-gain signal most competitors skip (they quote only the maximum).
- Where it stops short: no size diagram/calculator, no first-hand operator detail (a brand-wide asset, not a facility page). Add an original visual to make it link-worthy.
- Gate/rule: Law 15 (honesty hedge = information gain); the model for the size-guide asset built via `/write-local-asset`.

### BAD / penalty-risk

**B1. Public Storage, programmatic "10x10 storage units near [City]" (VERIFIED doorway)** - `publicstorage.com/self-storage-ga-atlanta/10x10-storage-units` (live; the same skeleton scales to San Antonio, LA, NY, Phoenix)
- What fails: H1 swaps city + facility grid, keeps everything else static ("Find Storage Near You," "Trusted nationwide since 1972," "$1 first month"). <5% Atlanta-specific editorial; ~2,500-3,000 words that are almost all repeated unit-card boilerplate. It survives partly on real inventory but the editorial adds no information gain.
- Why: word count without information gain is the doorway signature (G3, Law 15). Even a national brand's programmatic size pages are a doorway pattern.
- Gate/rule: G3 / SS-DOORWAY, Law 15.

**B2. Big Tex 10x10 blog: internal capacity contradiction (VERIFIED accuracy defect)** - `bigtexstorage.com/about/blog/how-big-is-a-10x10-storage-unit/` (live)
- What fails: the body says a 10x10 fits "150 to 200 medium-sized moving boxes," its own FAQ says "up to 80." A page that contradicts itself on the one number the reader came for fails the accuracy bar (G1) and undercuts the Experience it claims. (The same operator's product page, s3-adjacent, is tighter - long blog explainers are where uncaught capacity claims accumulate.)
- Gate/rule: G1 accuracy; every capacity number must be internally consistent and tied to a stated packing assumption.

---

## 4. Homepage

Job: entity anchor + primary conversion. The bar: instant find-a-facility, one real proof cluster (counters, credentials, real reviews), a specific value proposition. The trap: "peace of mind" wallpaper with no facts. Full spec in the homepage playbook + storage overlay.

### GOOD

**G1. Capitola Self Storage** - `capitolaselfstorage.com/` (live; independent) - see 1.G2. A wall of provable first-party facts (breach counter, 50-80 F range, individually alarmed units, gate 6am-10pm separate from office hours, live board with honest sold-out states, 12 named 5-star reviews, NAP). The independent-homepage model: beat the chains with un-fakeable operational facts, not budget.

**G2. CubeSmart homepage** - `cubesmart.com/` (live; enterprise)
- What it does right: conversion-first architecture - a persistent "Enter Zip, City or State -> Find Storage" search in header, hero, and footer (correct for a 1,000+ facility brand where the user's first job is "find my city"); concrete amenity language ("24-hour Video Recording," "Drive-Up and Climate-Controlled Units," "Extended Access Hours"); an explicit 5x5-through-10x30 size taxonomy that feeds internal linking.
- Where it leans generic: "peace of mind," "premium affordable," "highest service rating in the industry" (unquantified). The search UX carries it; for an enterprise that is acceptable, for an independent it would be a miss.
- Gate/rule: conversion-first (research 04); the generic copy is the SS-3 / voice-blocklist warning even a giant trips.

### BAD / penalty-risk

**B1. StorageMart homepage** - `storage-mart.com/` (live) - the stranded-moat mistake
- What underdelivers: mood copy - "Self storage is more than just a place to store your belongings... peace of mind is easier to find" - with one quoted review and badge logos, no years-in-business, no facility count, no live proof cluster on the homepage. The irony: StorageMart owns one of the industry's strongest About pages (s5, G1, the Burnam legacy) yet strands all that Experience one click away and fronts the homepage with generic aspiration.
- Gate/rule: G2 (proof exists in the org but not where conversion happens), voice-blocklist ("peace of mind," "more than just storage").

**B2. Polk County Storage homepage** - `polkcountystorage.com/` (live) - the thin independent
- What fails: ~350 words total; a family-heritage CLAIM ("passed down to us through many generations... serving the community since 1985") with no named people, no owner photo, no dated milestone, no unit prices, no security/climate specifics, no reviews, no schema. Real facts exist (address, seasonal gate hours), which keeps it honest, but the heritage story is asserted, not shown.
- Gate/rule: G2 / Law 16 ("family-owned since X" worthless without specifics). The independent baseline the system is built to beat.

---

## 5. About / team page (the E-E-A-T surface)

Job: convert trust; carry Person/Organization entity signals. The bar: named humans with dated, checkable histories and credentials, photos, a specific origin story. The trap: "family owned, we care" with no human named and no artifact shown.

### GOOD

**G1. StorageMart, About Us** - `storage-mart.com/about-us` (live)
- What it does right: a dated, named, checkable origin story ("In 1974, while on vacation with his family in Texas, Gordon saw the self storage industry for the first time..."); founders Gordon and Mickey Burnam, first location on Rangeline Street, Columbia MO; "four generations of Burnams." Named executives with VERIFIABLE third-party credentials: Cris Burnam (EY Entrepreneur of the Year, BBB Torch Award), Mike Burnam (Self-Storage Hall of Fame, SSA board); three executive headshots; concrete milestones ($3B+ Manhattan Mini Storage acquisition, 2021).
- Why it wins: every E-E-A-T lever at once - real people, dated events, external credentials (the strongest kind, third-party-verifiable).
- Gate/rule: G2, Law 16.

**G2. Advantage Storage, About Us** - `advantagestorage.net/about-us/` (live, Sherman TX operator)
- What it does right: an entire named leadership roster with dated, specific bios rather than titles - founder Rick Jones (1996, "35 years of industry experience"); "Cory Horne graduated with a business degree from North Carolina State University in 2000... joined in 2012"; credentials cited (MBA, CFA). ~2,100 words of genuine narrative.
- Where it stops short: no photos of the named individuals (a real gap - original headshots are a first-party Experience artifact and support Person schema). Fixing that makes it best-in-class.
- Gate/rule: G2 (named, dated, credentialed); the missing headshots are the improvement the system adds.

### BAD / penalty-risk

**B1. A Family Storage, About Us** - `afamilystorage.com/company-pages/about-us-.../` (live, Tucson AZ)
- What underdelivers: claims scale ("largest locally and privately owned storage company in Tucson," 19 locations, since 1998) and community ties but names NOT A SINGLE PERSON, shows no owner/staff photo, quotes no review, carries no schema, and leans on unprovable comparatives ("we're not just bigger... we're better!"). The genuine local detail it has (40+ named service areas) shows the raw material exists; it just never puts a person or a proof on the page.
- Gate/rule: G2 (E-E-A-T without a named human), Law 16 ("we're better" survives the paste onto any competitor).

**B2. Polk County Storage** (see 4.B2) - doubles as a failed About surface: a multi-generational family business since 1985 that never names a generation, a founder, or a year beyond "1985," and shows no photo. The most valuable, un-fakeable asset an independent has (the actual family) is claimed but never shown. A prime `sme-interviewer` target.

---

## 6. Cities-served / service-area page

Job: communicate coverage without spawning doorway pages. The bar: real, granular local geography (towns, counties, landmarks, distances) tied to genuine operating knowledge, or a clean facility directory. The trap: a wall of city links each fronting a near-identical thin page.

### GOOD

**G1. Storage City, service area** - `storagecity.biz/` (live, Smith Mountain Lake / Franklin County VA)
- What it does right: granular, real, checkable local geography instead of a city-list dump - "Since 1997, customers throughout Franklin County, Pittsylvania County, Rocky Mount, Glade Hill, Moneta, Penhook, Union Hall, Hardy, and Smith Mountain Lake have trusted Storage City," two real facilities with addresses, plus a local resources block demonstrating market knowledge. The named small towns break on the paste.
- Gap: no unit prices on this page; the coverage story is strong but should bridge to live inventory.
- Gate/rule: G3 (real local knowledge, not a metro-list), Law 16.

**G2. CubeSmart, Houston-area directory** - `cubesmart.com/texas-self-storage/houston-self-storage/` (live) - GOOD-with-a-warning
- What it does right: a genuine facility directory - 49 real facilities with addresses, per-facility ratings (4.4-4.9) and distances, named suburbs. As a directory-style service-area page it is legitimate: the value is real, priced, rated inventory, not spun editorial.
- The warning: the editorial wrapper is generic ("peace of mind"). A directory of REAL facilities is fine; a directory of thin per-city DOORWAY pages is not - which is the distinction B1 fails.
- Gate/rule: G3 (a real facility directory passes; the generic wrapper is the SS-3/voice warning).

### BAD / penalty-risk

**B1. The near-identical per-city landing page, proven live** - `storagekingusa.com` Dallas + Tallahassee (see 2.B1). When a service-area hub links out to 20-40 of these, the hub becomes a doorway index. The system's answer (`topical-map-protocol.md`): a city gets its own page only on real first-party evidence; otherwise it is an index-only entry, not a thin page.
- Gate/rule: G3 / SS-DOORWAY.

**B2. Pattern - the city-link carpet with duplicated per-city copy** (clearly-labeled real pattern): a paragraph of boilerplate ("Proudly serving [City] with clean, secure, affordable storage") repeated under 30 city headers, each linking to a page that is the same boilerplate with the city swapped. The discriminator: does each place carry a unique, checkable local fact (a real distance, landmark, facility), or only a swapped noun? If the latter, doorway.
- Gate/rule: G3 / SS-DOORWAY; the topical-map evidence gate.

---

## 7. Size-guide / cost-guide asset (the linkable asset)

Job: earn links and AI-answer citations with genuinely useful, sourced data. The bar: original or clearly-sourced data, dated, with real numbers and methodology. The trap: uncited round-number ranges rehashed from everyone else. Built via `/write-local-asset`.

### GOOD

**G1. Storage.com, Self-Storage Pricing Guide** - `storage.com/blog/how-much-does-a-storage-unit-cost/` (live)
- What it does right: proprietary, dated, methodologically-stated data - the single biggest citation-earning signal. National averages labeled "Based on Storage.com internal transaction data, January-June 2026... across 150+ U.S. markets": 5x5 $35.58, 10x10 $81.70, 10x20 $131.82, 20x20 $230.25; climate control "15% to 30% more"; indoor access "up to 50% more." External corroboration cited (RentCafe April 2026).
- Why it wins: precise non-round numbers ($81.70, not "~$80"), a named dataset, a date, a market count - exactly what an AI answer engine and a journalist cite. It manufactures information gain (Law 15) instead of restating it.
- Gate/rule: Law 15, GEO citability (`geo_page_linter.py`).

**G2. Public Storage 10x10 size guide** (see 3.G2) - as a size-guide asset it clears the bar with honest capacity math and a bridge to live prices; it would become link-worthy with an original size-comparison visual or calculator, which it lacks.

### BAD / penalty-risk

**B1. Public Storage, cost guide blog (big brand, thin + uncited)** - `publicstorage.com/blog/.../how-much-does-a-storage-unit-cost-a-complete-guide.html` (live)
- What fails, despite the brand: ~600-700 words of round-number, unsourced ranges (10x10 "$90-$130," climate "+$10-$30") with, in the fetched text, no research source, survey, or dataset cited. Set side by side with G1 (same topic), Storage.com's precise dated sourced data is vastly more citable. It proves brand authority does not substitute for information gain.
- Gate/rule: Law 15 (an asset that only restates the consensus in rounder numbers earns no links and no AI citations).

**B2. Pattern - the aggregated-consensus round-number guide** (clearly-labeled real pattern): dozens of "how much does storage cost" pages (Move.org, RecNation, and others) recycle the same ~$35/$65/$90/$140 ladder without a dated first-party dataset. Legal, but zero information gain and near-zero citation odds. The system's cost-guide asset must ship the client's own market data or a clearly-sourced original cut, or it should not ship (Law 15, Law 18).

---

## The one insight to carry into every self-storage page

**Pair a live per-size price with a concrete security spec (or a dated first-party counter), and you win the two games storage is played on at once.** The live price is the #1 conversion lever and proof the facility is really operating; a spun template cannot produce it. The security spec ("24 recorded cameras, individually alarmed units, a per-tenant gate code logged on entry and exit") is the concrete proof that satisfies the trust gate, stays out of the `Dilbeck` liability that "safe and secure" walks into, and breaks on the paste (only this facility has those cameras). The winners (CubeSmart's live board + Rice-University block, Capitola's breach counter + 50-80 F range, Stop & Stor's local prices + written price-lock, Storage.com's dated 150-market dataset) lead with both a real number and a real place; every penalty-risk page above omits one or both - it prints "peace of mind" with no facts, lists cities with no inventory, or claims "family owned" and never shows a face. The live price and the physical-place spec are not decoration. They are the moat, because a spun template can fake neither the rate that must equal checkout nor the cameras that resolve to a real gate.

---

## Sources (fetched live this session, 2026-07; full teardown detail in research/self-storage-2026-07/08-example-teardowns.md)

- CubeSmart facility + directory + homepage: cubesmart.com/texas-self-storage/houston-self-storage/3764.html , /4305.html , /houston-self-storage/ , cubesmart.com/
- Capitola Self Storage: capitolaselfstorage.com/
- Public Storage: /self-storage-tx-dallas/climate-controlled-storage-units , /self-storage-ga-atlanta/10x10-storage-units , /size-guide/10x10-storage-unit/ , /blog/.../how-much-does-a-storage-unit-cost...
- Storage King USA (verified doorway pair): storagekingusa.com/locations/texas/dallas/climate-controlled/ , /florida/tallahassee/climate-controlled/
- Stop & Stor: stopandstor.com/storage-solutions/size-guide/10x10
- Big Tex Storage: bigtexstorage.com/storage-options/storage-units/10x10/ (product) , /about/blog/how-big-is-a-10x10-storage-unit/ (blog contradiction)
- StorageMart: storage-mart.com/ , /about-us
- Advantage Storage: advantagestorage.net/about-us/
- A Family Storage: afamilystorage.com/company-pages/about-us-...
- Polk County Storage: polkcountystorage.com/
- Storage City: storagecity.biz/
- Storage.com cost guide: storage.com/blog/how-much-does-a-storage-unit-cost/
- Blocked/errored this run (labeled patterns, never torn down): extraspace.com (403), sparefoot.com (403), thelockup.com (403), storagestar.com (500), alansfactoryoutlet.com (403), uhaul.com 10x10 (ECONNRESET).

All prices/counts directional; re-verify at build time. Fetches that were blocked were labeled patterns, not reconstructed from memory.
