# Auto-Repair Example Library (real, live-verified 2026-07-20)

The teardown corpus for the auto-repair vertical. For each of the six page types: at least two real GOOD examples (live URL, why it wins, the gate/law it satisfies) and at least two real BAD or penalty-risk examples (live URL or a labeled real pattern, why it fails, the gate it trips).

Governing law: `knowledge/doctrine/seo-system-doctrine.md`, especially **Law 8** (humanize with real facts and specificity, never detector-evasion). Read alongside `knowledge/doctrine/google-compliance-spine.md` and the six page-type playbooks. Every quote below was pulled live on 2026-07-20 unless tagged `[search-summary, re-verify at build]` (surfaced via a live search-result summary but the page body was not individually fetched) or `[labeled real pattern]` (a real, widely-documented pattern described honestly, not a named victim). Re-verify perishable facts (warranty terms, staff names, offers, live URLs) at write time. No fact here is fabricated; where a page was not fetched in full it is tagged, per CLAUDE.md.

---

## The auto-reality gates this vertical is graded on

These are the auto-specific overlays on the standard doorway and E-E-A-T gates. Every example below is scored against them.

1. **ASE proof gate.** "ASE certified" is a claim; the moat is the externally verifiable version: a named technician with a stated ASE Master certification, or the shop in the ASE Blue Seal directory (ase.com/find-a-repair-shop) or AAA Approved list (aaa.com/autorepair). A floating ASE badge with no named human trips the E-E-A-T Experience gate the same way "licensed and insured" with no license number does on a plumber page.
2. **Warranty-specificity gate.** A real, stated warranty term is a trust anchor and a conversion mechanic: Christian Brothers' "3-year/36,000-mile," an AAA shop's "24-month/24,000-mile," Hillsboro Village's "4-year/48,000-mile (industry best)." "We stand behind our work" with no number is noise. Only publish terms the shop actually underwrites.
3. **The 3-D doorway multiplier (the sharpest auto risk).** Local law firms and plumbers multiply on TWO axes (service x city). Auto repair multiplies on THREE: **service x make/model x city.** Brakes/transmission/AC/oil (4) x Camry/Accord/F-150/Silverado/Civic (5) x 15 suburbs = 300 pages from one template. "Toyota Camry Transmission Repair in Round Rock," "Honda Accord Brake Service in Cedar Park," on and on. This is the vertical's defining scaled-content hazard and the reason Section 5 of the service-city playbook is stricter here than anywhere else.
4. **No-upsell trust gate.** The dominant fear in this vertical is being sold repairs the car does not need. The winning pages convert on it explicitly ("only what your car actually needs," itemized written estimate before work, digital inspection with photos). This is auto's equivalent of legal's "no fee until we win."
5. **Real-technician / real-shop proof gate.** Named techs, named owner, real bay and branded-truck photos, the diagnostic equipment shown. Stock photos of a smiling mechanic in a clean polo trip the same reverse-image tell a stock plumber crew does.
6. **Real review handling gate.** City-tagged named reviews in HTML, owner replies dated in the last 30-90 days. Do NOT wrap your own LocalBusiness/Service nodes in Review/AggregateRating JSON-LD (renders no stars since 2019; the pack stars come from GBP).

---

## 1. Homepage (entity anchor + primary conversion)

### GOOD

**G1. Master Team Automotive, West Melbourne FL - masterteamautomotive.com** (verified live)
Why it wins: the homepage is built on un-fakeable human proof. Founder **Kevin Christensen**, "GM- and Toyota-factory-trained technician" 1984-1998 who "earned his ASE Master Technician certification before opening the shop in 1998"; lead tech **Victor Pasztor**, "ASE Certified Master Automotive Technician with more than 20 years' experience"; co-owner Jeniene Christensen named. The no-upsell fear is answered on the entity page itself: **"Auto repair without the upsell"** and **"Only what your car actually needs."** Warranty is specific ("12 months or 12,000 miles, parts and labor"), reviews are quantified (5.0 from 1,090), and the service area is named (Space Coast, Melbourne, Palm Bay). Satisfies gates 1, 2, 4, 5, 6 and the E-E-A-T Experience bar on the homepage, not buried in an About page.
Gate/law: E-E-A-T Experience; ASE proof gate; no-upsell trust gate.

**G2. Christian Brothers Automotive - cbac.com** (verified live via child pages)
Why it wins as a network homepage/entity: a single, consistent trust spine repeated at scale without going thin - the "Nice Difference 3-year/36,000-mile warranty honored at any location," the "#1 in Customer Satisfaction in the J.D. Power 2025 Aftermarket Study for the sixth consecutive year" (an externally verifiable third-party award, the strongest kind of proof), and a real digital-vehicle-inspection process. The brand-authority caveat from the service-city playbook applies: a single-location shop copying this structure inherits none of CBAC's entity strength and must earn it with links, reviews, and GBP.
Gate/law: warranty-specificity gate; external-verifiability (J.D. Power award); Law 8 (proof, not adjectives).

### BAD

**B1. My Transmission & Auto Care Experts - mytransmissionexperts.com** (verified live, template leak visible)
Why it fails: the network's location pages carry a live **template leak** - the Houston page (store/37) reads "At My Transmission & Auto Care Experts **in Delaware**, it's our mission..." on a page headed "Houston Transmission Shop, 11729 Jones Road." A wrong-city token bleeding through is the literal fingerprint of variable-substitution-at-scale, the exact behavior Google's scaled-content-abuse policy names. No ASE, no named staff, no real reviews (placeholder "Happy Cars, Happy Clients" carousel with no quotes), a 36-manufacturer make list identical across locations.
Gate/law: scaled-content-abuse (developers.google.com/search/docs/essentials/spam-policies); strip-the-city test; ASE proof gate; real-review gate.

**B2. The generic-template auto homepage** `[labeled real pattern]`
The mass-produced pattern sold by low-end web shops and AI site builders (mobirise.com and peers advertise exactly this): a stock hero of a smiling mechanic, "Your trusted local auto repair shop," a floating "ASE Certified" badge with no named human, "fully licensed and insured," "competitive pricing, quality you can trust," no owner, no real bay photos, no warranty number. It reads human to no one and proves nothing. Every trust claim is an adjective, not a verifiable fact.
Gate/law: E-E-A-T Experience (fails); gate 1 (unnamed ASE); gate 5 (stock imagery); Law 8 (empty humanization).

---

## 2. Location / city page ("[auto repair] [city]")

### GOOD

**G1. Christian Brothers Automotive West Road - cbac.com/west-road/** (verified live)
Why it wins: passes the strip-the-city test decisively. H1 "Auto Repairs in Houston, TX." Named hyper-local anchors: **Jersey Village, Cypress, Katy, Highway 290, Beltway 8, Sam Houston Tollway, I-10.** Named local condition causally tied to the service: **"Houston's intense heat and humidity"** and the stress of **"constant stop-and-go traffic on Beltway 8"** (heat and stop-and-go are real drivers of battery, AC, and brake wear - the mechanism is true). Real address (9130 West Road, 77064), local phone (713) 893-1845, named owners **Jeremy & Paula Robertson**, quantified offers ("$20 OFF oil changes," tiered "$50 off $500 / $125 off $1,000," free state inspection), the 3yr/36k warranty. Strip Houston and the Beltway-8 and Jersey-Village sentences collapse - that collapse is the target.
Gate/law: strip-the-city test (passes); Minimum Unique Local Substance bar (3+ anchors, named condition, real address, offer); warranty gate.

**G2. Auto Centric - autocentricrepair.com** (verified live)
Why it wins as an honest single-location page: real staffed address ("5355 Plainfield Ave NE, Grand Rapids MI 49525"), a genuine tenure claim ("serving Grand Rapids drivers since 1978"), and no fabricated multi-city footprint. It does not pretend to be in ten towns it is not. The honest limitation is the win: one real location, transparently stated. (Weakness to fix at build: thin on named neighborhoods and a local condition - it clears the honesty and NAP gates but only partially clears the Minimum Unique Local Substance bar.)
Gate/law: NAP integrity; no fabricated/rented address; honest single-location model beats a fake network.

### BAD

**B1. AAMCO franchise center page - aamco.com/Auto-Repair-Center/NC/Greensboro/W-Gate-City-Blvd** (verified live)
Why it fails: a franchise template with the address slotted in and nothing local beneath it. H1 "AAMCO of Greensboro, NC," real address and phone, but **no named staff, no ASE credentials, no customer reviews, zero Greensboro-specific content** - "no community references, generic service descriptions." Strip "Greensboro" and the body is correct for any AAMCO in the country. The page title implies brake service that the body does not detail. This is intermediate-not-destination: it exists to catch "transmission repair Greensboro," not to let a Greensboro driver finish the job with local proof.
Gate/law: strip-the-city test (fails); doorway intermediate-vs-destination test; ASE proof gate; real-technician gate.

**B2. The scaled-chain city hub** `[labeled real pattern]`
Firestone Complete Auto Care runs 1,700+ locations off state/city hub URLs (e.g. firestonecompleteautocare.com/pennsylvania/philadelphia/). The risk pattern (which any chain or aggressive independent can fall into): a city URL that is a store-locator list plus the same service boilerplate as every other city, with no Philadelphia neighborhoods, roads, or conditions - a page that varies only by the city token and the pin on the map. A big brand can survive on entity authority; an independent copying the shape gets read as scaled content. The multiplication risk compounds with gate-3 (service x make/model x city).
Gate/law: scaled-content-abuse; strip-the-city test; doorway smoke detector (watch "Crawled - currently not indexed" across the cohort).

---

## 3. Service page ("brake repair," "transmission repair," brand-wide)

### GOOD

**G1. Christian Brothers Automotive brakes - cbac.com/our-services/brakes/** (verified live)
Why it wins: symptom-led and genuinely useful, not a keyword slab. It teaches the buyer their own problem - **"soft" pedal, grinding or squealing, shaking, vibrations, dashboard warning lights**, plus an **ABS-light troubleshooting FAQ**. It shows the actual process (a five-step sequence: schedule, diagnose/inspect, digital inspection report with photos, review/approve, complete) and de-risks the no-upsell fear with the **complimentary Digital Vehicle Inspection (DVI) with photos.** The 3yr/36k nationwide warranty is stated. This is the depth a brakes page needs: what the work is, how you know you need it, what happens, what it is guaranteed by.
Gate/law: search-intent depth (informational + transactional served); no-upsell trust gate (DVI with photos); warranty gate.

**G2. Master Team Automotive service depth - masterteamautomotive.com** service set (verified live)
Why it wins: each core service (brakes, AC, diagnostics, transmission, cooling, electrical, suspension) is tied back to the named ASE Master technicians who perform it and to the "only what your car actually needs" promise, so the service page carries the Experience signal instead of floating free of any human. A brand-wide service page still passes E-E-A-T because the responsible, credentialed human is attached to the service.
Gate/law: E-E-A-T Experience on the service page; ASE proof gate; no-upsell gate.

### BAD

**B1. The "any make and model" one-liner service page** `[labeled real pattern, seen live]`
The dominant thin pattern (CBAC's brakes page itself notes technicians "can perform brake repairs on **any make and model**" - fine as a line, fatal as the whole page). The failure version: a "Brake Repair" page whose entire body is "We offer brake repair for all makes and models. Our ASE certified technicians provide quality brake service at competitive prices. Call today!" No symptoms, no process, no warranty number, no cost band, no named tech. It answers no question a real driver has and earns no AI-answer citation because there is no extractable passage.
Gate/law: thin-content / helpful-content (fails); search-intent depth (fails); Law 8 (empty).

**B2. The make/model service-page farm** `[labeled real pattern, seen live]`
Transmission specialists commonly spin a near-identical page per manufacturer ("Toyota Transmission Repair," "Honda Transmission Repair," "Ford Transmission Repair" ...), each swapping only the brand name over identical body copy. Legitimate ONLY when each page carries real make-specific substance (e.g. Toyota's known throttle-position-sensor / shift-solenoid issues on 1990-2007 Camrys, the A340E / U660E units, the actual failure modes). Without that, a 36-brand set is 36 doorways. This is axis two of the 3-D multiplier and the most common auto-specific scaled-content trap.
Gate/law: scaled-content-abuse; strip-the-token test (swap the make - does anything change?); external-verifiability gate.

---

## 4. Service-in-city combo ("brake repair in [city]," the money page + highest doorway risk)

### GOOD

**G1. Christian Brothers Automotive West Road as service-in-city hub - cbac.com/west-road/** (verified live)
Why it wins: it fuses one location with named services and true local substance, exactly the compliant combo pattern. Houston + brakes/AC/batteries/diagnostics/transmission, each tied to the Houston reality (heat-and-humidity load on batteries and AC, Beltway-8 stop-and-go on brakes), the named owners, the local offers, the 3yr/36k warranty, and a real address. It could split into `/west-road/brake-repair/` children the way Roto-Rooter splits `/houston/emergency-plumber/`, and each child would inherit real local proof rather than a swapped token.
Gate/law: Minimum Unique Local Substance bar (all five items); strip-the-city test (passes); message-match scent (service + city + local mechanism).

**G2. The single-service single-suburb page done right** `[labeled real pattern, model built from verified inputs]`
The winning shape, e.g. "Brake Repair in Cedar Park, TX": names 3+ real anchors (Whitestone Blvd, 183A toll, Twin Creeks), one real local condition (heavy 183A stop-and-go accelerates pad wear; Texas heat cooks brake fluid), one externally verifiable proof (a city-tagged 5-star review resolving to the real Google profile, or a named ASE Master tech with a lookup-able certification), 2+ city-specific FAQs (response time to named suburbs, local inspection/registration rule), a local conversion path, the warranty number. Build these ONLY for suburbs the shop actually books jobs in.
Gate/law: service-city playbook Sections 4-5 in full; 3-D multiplier discipline (gate 3).

### BAD

**B1. My Transmission Experts store pages - mytransmissionexperts.com/store/37/ (Houston), /store/39/ (Montgomery)** (verified live)
Why it fails as a combo: the "Delaware" leak on the Houston page proves the store pages are one template with a city token, and the 36-manufacturer make list is identical across Houston, Katy, and Montgomery. It targets "[city] transmission shop" without the local substance to survive the strip-the-city test, and with no named tech, no ASE, no real reviews.
Gate/law: scaled-content-abuse; strip-the-city test (fails); the template-leak smoking gun.

**B2. The AI-spun make x service x city network** `[labeled real pattern - the 2026 hazard]`
Using generative AI to mint "[Make] [Model] [Service] in [City]" at scale - "Honda Accord Transmission Repair in Frisco," "Ford F-150 Brake Service in Plano," hundreds of convincingly specific pages, none tied to a real booked job, none externally verifiable. This is the exact "using generative AI tools to generate many pages without adding value" example in the live scaled-content-abuse policy, and it fails the external-verifiability gate even when it passes a naive strip-the-city read. Auto's 3-D multiplier makes this the single most tempting and most dangerous move in the vertical.
Gate/law: scaled-content-abuse (AI-pages clause); external-verifiability test (5.3); May-15-2026 rule that spam policy now governs AI Overviews too.

---

## 5. About / team page (the E-E-A-T and trust surface)

### GOOD

**G1. Hillsboro Village Auto Service - hillsborovillageautoservice.com/about-us/** (verified live)
Why it wins: the un-fakeable version of ASE proof. Named responsible human with a specific credential - **Service Manager Brent Ferguson, "an ASE Master Certified Technician in Nashville with over 30 years of experience,"** at the shop 30+ years. Owners named (Crystal and Eric Iseldyke), store manager named (Jennifer Hood, 18+ years), **AAA approved** (an external, verifiable trust signal), a stated **"4-year/48,000-mile warranty (industry best),"** annual continuing education, and a retention proof point ("many customers... for over 30 years"). This is Experience shown with specifics, not "family owned since [year]" floating alone.
Gate/law: E-E-A-T Experience + Expertise; ASE proof gate (named + credentialed); external-verifiability (AAA, ASE Master); warranty gate.

**G2. Master Team Automotive about section - masterteamautomotive.com** (verified live)
Why it wins: two real founder bios with dates and factory pedigree (Kevin Christensen, GM/Toyota factory-trained 1984-1998, ASE Master before opening in 1998; Jeniene from the medical field), lead tech Victor Pasztor named with his ASE Master credential and 20+ years. The story proves the expertise instead of asserting it, and it carries the no-upsell ethos into the origin story.
Gate/law: E-E-A-T Experience; ASE proof gate; authentic named authorship.

### BAD

**B1. The nameless "family owned, ASE certified" about page** `[labeled real pattern]`
The commodity About page: "Family owned and operated. Our ASE certified technicians have years of combined experience. We treat every customer like family and stand behind our work." Not one named human, not one dated fact, not one lookup-able credential, a stock team photo. "Years of combined experience" is the tell - it hides that no single person's credential is stated. Worthless as E-E-A-T because nothing is verifiable and no one is accountable.
Gate/law: E-E-A-T Experience (fails - no named responsible human); ASE proof gate (fails); Law 8.

**B2. AAMCO / franchise "about" with no local humans - aamco.com center pages** (verified live pattern)
The franchise location pages carry "AAMCO Centers are independently owned and operated" but name no owner, no technician, no ASE credential on the page. The independent operator who actually owns that bay is invisible, so the page has an entity but no accountable human - the opposite of what a YMYL-adjacent trust page needs.
Gate/law: E-E-A-T (no named human); real-technician gate.

---

## 6. Service-area page (coverage without doorway spam)

### GOOD

**G1. Auto Centric - autocentricrepair.com** (verified live)
Why it wins: honest coverage. One real staffed address in Grand Rapids, "your neighborhood car and truck experts in Grand Rapids MI since 1978," with adjacent communities (Comstock Park, Rockford) named as accessible rather than faked into separate location pages. It does not invent a presence it lacks. (Build note: strengthen with drive-time transparency and one local condition per named area to fully clear the bar - it clears honesty and NAP but is light on per-area substance.)
Gate/law: honest SAB statement; NAP integrity; no fabricated/rented address.

**G2. The real-suburb coverage page done right** `[labeled real pattern, model built from verified inputs]`
The winning shape for a mobile or drive-radius shop: a service-area page that names each real suburb it dispatches to with a genuine reason it is there (a fleet account in that industrial park, a named road it runs daily), an honest "we are a service-area business, no public walk-in counter" line where true, and a coverage map - never a rented UPS-box address to look more local. Multi-location groups like Kennedy Transmission (7 real Minnesota shops since 1962) have the raw material to do this; the discipline is one genuinely differentiated page per real shop, not one template x seven cities.
Gate/law: doorway intermediate-vs-destination; no fabricated address (GBP suspension + doorway signal); per-page uniqueness.

### BAD

**B1. Kennedy Transmission location structure - kennedytransmission.com** (verified live, template-heavy)
Why it is at risk: seven genuine Minnesota locations, but the site is **"template-heavy rather than location-specific"** - unified messaging repeated across Apple Valley, Bloomington, Plymouth, Shakopee, Minneapolis, Forest Lake, and Waite Park with "no individual staff profiles or ASE certifications, no specific warranty details, no unique content per location." Real shops with real bays undermined by templated pages: the business is legitimate, the pages are thin, and thin pages on a real network still get read as scaled content. Fix by writing each location its real staff, reviews, hours, and local conditions.
Gate/law: scaled-content-abuse risk on a real business; doorway smoke detector; per-location uniqueness bar.

**B2. The city-swap "Areas We Serve" list** `[labeled real pattern, RicketyRoo-flagged]`
The classic doorway: an "Areas We Serve" page (or a page each) that "swaps city names across boilerplate copy" - "Serving [City] and surrounding areas with quality ASE auto repair" x 40 towns, "packed with keywords and FAQs but says nothing useful to a real person in that locale," often orphaned with no internal links. RicketyRoo names this exact pattern as spam (ricketyroo.com/blog/location-page-spam/): "swapping city names across boilerplate copy is duplication, not localization." The auto twist: it usually also faults on gate 3, multiplying the swap by services and makes.
Gate/law: doorway abuse (developers.google.com/search/docs/essentials/spam-policies); strip-the-city test; orphan-page check.

---

## Sources (opened this session, 2026-07-20)

Verified-live pages (fetched in full):
- Christian Brothers Automotive, West Road Houston: cbac.com/west-road/
- Christian Brothers Automotive, brakes service: cbac.com/our-services/brakes/
- Master Team Automotive, West Melbourne FL: masterteamautomotive.com
- Hillsboro Village Auto Service, About Us (Nashville): hillsborovillageautoservice.com/about-us/
- Auto Centric, Grand Rapids MI: autocentricrepair.com (areas-we-serve redirected to main)
- My Transmission & Auto Care Experts, Houston store: mytransmissionexperts.com/store/37/ (Delaware template leak)
- AAMCO Greensboro NC, W Gate City Blvd: aamco.com/Auto-Repair-Center/NC/Greensboro/W-Gate-City-Blvd
- Kennedy Transmission (7 MN locations): kennedytransmission.com
- RicketyRoo, location-page spam patterns: ricketyroo.com/blog/location-page-spam/

Search-summary sources (surfaced live, page body not individually fetched - re-verify at build):
- ASE Blue Seal repair-shop directory: ase.com/find-a-repair-shop
- AAA Approved Auto Repair (24/24 warranty, ASE requirement): aaa.com/autorepair
- Firestone Complete Auto Care city hubs (scaled-chain pattern): firestonecompleteautocare.com/pennsylvania/philadelphia/ (403 on fetch; pattern described, not quoted)
- Auto Service Experts (San Antonio), Midtown Automotive (Tulsa), Circle D Transmission (Houston, Toyota make pages): named via live search, re-verify
- Toyota Camry transmission known issues (throttle-position sensor, shift solenoid, A340E/U660E), make-specific substance benchmark: parts/repair sources via live search

Policy anchors (per the service-city playbook, re-verify at build):
- Google spam policies (doorway + scaled content abuse): developers.google.com/search/docs/essentials/spam-policies
- Spam policy now governs AI Overviews / AI Mode (May 15, 2026): ppc.land coverage, verify against Search Central

All figures directional. No live A/B test behind this document. Re-verify perishable facts (warranty terms, staff names, offers, live URLs, ASE/AAA listing status) at write time. No local fact fabricated; unfetched pages are tagged.
