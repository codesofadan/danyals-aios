# HVAC Example Library: Real Pages, Real Penalties, Per Page Type

The HVAC vertical, worked example by example. For each of the six page types this system writes, this file gives real GOOD pages (what wins and the gate/law it satisfies) and real BAD or penalty-risk pages (what fails and the gate it trips). It is the companion to the six playbooks in `../`. Read the page-type playbook for the spec; read this for the live proof.

Governing law: `knowledge/doctrine/seo-system-doctrine.md`, especially **Law 8** (humanize with real, verifiable local facts, never with detector-evasion). The service-in-city depth bar is `../service-city-page.md`; hold every HVAC page to its strip-the-city test and its Minimum Unique Local Substance bar.

## The HVAC reality that shapes every page

HVAC is not a generic trade. The page is written differently because the buyer's world is:

- **Two opposite emergencies, seasonally.** AC-down in a 115F Phoenix June and a furnace-down in a minus-20F Minnesota January are the same page mechanic (URGENT, phone-first, response-time-load-bearing) with opposite physics. A national template that says "comfort all year" in a market that has one real season is a tell.
- **Real technical specifics a buyer now checks.** SEER2 (the 2023 cooling-efficiency standard that replaced SEER), AFUE (furnace fuel efficiency, e.g. 96% AFUE), tonnage / Manual J load sizing (1 ton = 12,000 BTU; a 3-ton unit ~ 1,500-2,000 sqft depending on climate and insulation), and the **R-410A to R-454B refrigerant transition** (the AIM Act restricted manufacture of new R-410A residential equipment from Jan 1, 2025; R-454B is an A2L mildly-flammable refrigerant, GWP 466 vs R-410A's 2,088, and needs leak-detection-equipped coils). A service page still selling "R-410A systems" and pre-SEER2 numbers in 2026 reads stale to both the buyer and the engine.
- **Financing, maintenance plans, and climate-driven local failure modes** are the conversion levers: 0% APR install financing, membership "clubs" (priority scheduling, discounted tune-ups), and the local mechanism (desert dust clogging condenser coils, Gulf humidity and salt-air corrosion, freeze-thaw furnace short-cycling, monsoon load) that proves this business actually works this town.

## How to read the verification tags

Every example carries a tag for how its quotes were sourced at research time (July 2026). Re-verify perishable facts at build time.

- **[VERIFIED-LIVE]** quote pulled from the live page via direct fetch.
- **[INDEXED]** page is live but bot-blocks automated fetch (403); quote surfaced through Google's index. Real, but re-confirm in a browser at build.
- **[LABELED PATTERN]** a real, documented pattern or structural shape (with a cited case study where one exists), NOT a fabricated named business. Used where the honest move is to describe the real failure mode rather than invent a specific URL. This follows the CLAUDE.md rule: cite real live URLs or label the pattern, never fabricate a specific.

Note: Roto-Rooter Houston (the plumbing exemplar in `../service-city-page.md`) is **plumbing only**; it carries no HVAC content (verified). Do not cite it as an HVAC example. The HVAC anchors below are their own businesses.

---

## 1. LOCATION PAGE (city page: the whole HVAC business in one town)

Job: rank and convert for "HVAC / AC / heating [city]" and cover the business in that one town.

### GOOD

**G1. Discount AC & Refrigeration, Phoenix** [VERIFIED-LIVE]
`discountacr.com/services-areas/ac-repair-near-me-in-phoenix/`
The model single-operator HVAC location page. Real, non-transferable Phoenix substance, verbatim: "Phoenix summers regularly push past 115F from June through September"; "Summer dust storms clog outdoor condenser coils, forcing the system to overheat and shut down"; "In extreme heat, a unit low on refrigerant or with a failing compressor simply can't keep up past 110F"; the local utility angle "spiking APS and SRP bills"; named neighborhoods Arcadia, Ahwatukee, Paradise Valley, Camelback East, Desert Ridge, Maryvale, South Mountain; and "License No. ROC 361623" repeated on-page.
Why it wins: passes the **strip-the-city test** hard (the dust-storm-on-condenser-coil and 110F-refrigerant mechanisms collapse the instant you swap Phoenix for a temperate city) and passes the **external-verifiability gate** (the ROC number resolves at the Arizona Registrar of Contractors; APS/SRP are real utilities). Satisfies the **Minimum Unique Local Substance bar**: 3+ named anchors, a named local condition (desert heat + monsoon dust) causally tied to the failure, and a verifiable proof (license number).

**G2. Goettl, Phoenix and Las Vegas** [INDEXED]
City hub `goettl.com/location/phoenix-arizona/` with `/location/phoenix-arizona/air-conditioning/`; sibling `goettl.com/location/las-vegas-nevada/`.
Clean city-first URL architecture and real operational scale, surfaced via index: "89 fully stocked trucks operating in and around Phoenix"; desert framing "scorching summers and surprisingly cool winters"; "Trusted Since 1939"; the branded "RIGHT WAY Guarantee"; 24/7 emergency. The Las Vegas page's own title enumerates ten real submarkets: Henderson, North Las Vegas, Summerlin, Spring Valley, Paradise, Enterprise, Sunrise Manor, Whitney, Boulder City, Blue Diamond.
Why it wins: named submarkets + desert-heat entity framing + a verifiable operational fact (truck count, founding year) + a flat city-first subfolder pattern held site-wide. **Authority caveat:** Goettl also ranks on national brand strength; a single-location operator inherits the structure, not the authority, and must earn the rest through reviews, links, and GBP. Structure is necessary, not sufficient. (WebFetch is bot-blocked 403; re-confirm quotes in a browser at build.)

### BAD

**B1. The suburb-swap HVAC doorway network** [LABELED PATTERN, documented case]
Reported case study: `upnorthmedia.co/blog/doorway-pages-seo`.
A regional HVAC company built hundreds of pages, one per suburb it served, each near-identical with the city token swapped. After the March 2024 core-plus-spam update, over 80% of those pages lost rankings and the site saw a reported 63% organic traffic drop in 30 days; recovery required consolidating into fewer genuinely location-specific pages with per-area reviews.
Why it fails: the city name was the only variable, so every page failed the **strip-the-city test** simultaneously, and SpamBrain reads a cohort of near-duplicates as **scaled content abuse** (developers.google.com/search/docs/essentials/spam-policies). Trips the doorway + scaled-content gate.

**B2. The AI-generated phantom-address HVAC site** [LABELED PATTERN, documented case]
Reported case: `achrnews.com/articles/166082` (ACHR News, Orlando, Jan 2026).
A wave of AI-generated "HVAC contractor" sites flooded Orlando search with local-area-code phone numbers, dozens of fabricated reviews, fake BBB A+ claims, and **phantom addresses that resolve to vacant plazas or the middle of a neighborhood**. A real operator (Smart Home Air & Heat, owner Chris Elsis, reportedly ~$150k/mo) saw his phone stop ringing in January 2026 and laid off five staff.
Why it fails: fabricated addresses and fabricated reviews trip the **NAP-integrity / no-fabricated-or-rented-address gate** (a GBP suspension trigger and doorway signal) and the **scaled-content-abuse** policy. This is the 2026 face of the doorway problem: convincing specifics, zero external verifiability.

---

## 2. SERVICE PAGE (brand-wide single service, place-agnostic by design)

Job: rank and convert for one service ("AC repair," "furnace installation," "duct cleaning," "maintenance plan") across the whole business.

### GOOD

**G1. Parker & Sons, Cooling / AC** [INDEXED + VERIFIED-LIVE]
`parkerandsons.com/cooling` and `/cooling/ac-repair`.
Real technical specificity a buyer can act on: efficiency tiers stated as "up to 22 SEER" (deluxe), "15-17 SEER" (premium), and "14 SEER" (standard); install financing framed as "$69 - $99/month net investment" ("as low as ... $2 - $3/day"); the "Parker Family Plan" maintenance membership; "Since 1974 Parker & Sons has served the greater Phoenix metropolitan area"; "More than 15,000" Google reviews; live license strings ROC152654, ROC152656, ROC233298, ROC258885, ROC300696; 24/7 with "No Extra Charge for Nights, Weekends, or Holidays."
Why it wins: a brand-wide service page that carries numbers (SEER tiers, monthly financing), a membership offer, and verifiable license and review proof, not adjectives. Satisfies the service-page depth bar and E-E-A-T Expertise/Trust.
**The 2026 gap to close:** the page states SEER, not SEER2, and names no R-454B transition. A top-0.1% 2026 service page would state SEER2 and address the refrigerant change (see G2's absence and B2 below).

**G2. Sila, A/C Maintenance & Repair** [VERIFIED-LIVE]
`philadelphia.sila.com/hvac-services/cooling/maintenance-repair/` (H1 "Expert A/C Maintenance & Repair in Philadelphia").
Concrete, extractable process instead of "we fix ACs": the tune-up is itemized verbatim as "Cleaning coils, checking refrigerant levels, lubricating moving parts, testing electrical connections, inspecting the condensate drain, and calibrating the thermostat"; a "Comfort Club" membership; upfront-price promise "Never pay more than your original quote"; same-day and 24/7.
Why it wins: the itemized checklist is a self-contained, AI-extractable answer passage and a real de-risking signal. **Structural caveat (teachable):** Sila publishes this on a per-city subdomain (`philadelphia.sila.com`, `boston.sila.com`, `nyct.sila.com`), so it functions as a service-in-city page, and subdomain-per-city is the exact doorway-network shape the compliance spine flags. Good content, risky structure: on a single domain this is a clean service page; the subdomain farm is the part not to copy.

### BAD

**B1. The adjective-wall service page** [LABELED PATTERN]
The common "We repair all makes and models of air conditioners. Fast, friendly, affordable service. Call today!" service page. Names no SEER2, no AFUE, no tonnage/Manual J sizing, no refrigerant, no process, no financing terms, no membership detail. Place-agnostic AND substance-agnostic.
Why it fails: nothing on it is verifiable in the reader's head and nothing is extractable for an AI answer; it reads machine-generated because it is empty. Trips the service-page depth bar and the AI-tell voice gate (Law 8: substance, not laundering).

**B2. The refrigerant-blind, stale-spec service page** [LABELED PATTERN, grounded in the AIM Act]
An install or replacement service page in 2026 still selling "new R-410A systems" and quoting pre-SEER2 efficiency, after the Jan 1, 2025 restriction on manufacturing new R-410A residential equipment and the SEER2 standard. Also seen: promising exact tonnage ("we install 3-ton units") with no Manual J load reference.
Why it fails: factually stale on a high-dollar purchase erodes the **Expertise and Trust** legs of E-E-A-T and risks misinforming the buyer; the correct 2026 page states SEER2, addresses the R-454B/A2L transition, and sizes by Manual J load, not by square-foot rule of thumb. Trips the no-stale-facts / expertise gate.

---

## 3. SERVICE-IN-CITY (the money page: one service x one city)

Job: rank, earn the AI citation for, and convert "[service] in [city]." Highest intent and highest doorway risk on the site.

### GOOD

**G1. O'Boys Plumbing, Heating & Air, Furnace Repair in Minnetonka, MN** [VERIFIED-LIVE]
`calloboys.com/area/minnetonka-mn-furnace-repair/` (title "Furnace Repair in Minnetonka, MN").
Winter-emergency combo page, done right. Verbatim local substance: named neighborhoods "Ridgedale and Williston"; a named local job "A Williston Neighborhood Call That Couldn't Wait"; the housing-stock mechanism "Homes in Minnetonka that were built in the 1970s and 1980s are at the age where heat exchanger integrity should be verified" (carbon-monoxide risk); the microclimate "Winter temperatures here can feel genuinely harsh, especially overnight ... when wind comes off Lake Minnetonka"; 24/7 with a technician arriving "within the hour" in the case study.
Why it wins: passes the **strip-the-city test** (the Lake Minnetonka wind and the 1970s-80s heat-exchanger point collapse if you swap the city) and the **Minimum Unique Local Substance bar** (3+ anchors, a local condition tied to the service, a named local job as proof, plus local logistics). The furnace/CO angle is the winter equivalent of desert-dust-on-condenser-coils.

**G2. C&M Heating and Air, Furnace Repair in Ramsey, MN** [VERIFIED-LIVE]
`candmheatingandair.com/blog/furnace-repair-ramsey-mn-trusted-local-experts-for-north-metro-winters`.
Every local sentence is un-spinnable, verbatim: "familiar with the common split-entry and rambler layouts found in neighborhoods near the Rum River"; "Sub-zero temperatures force furnaces to run longer cycles, which accelerates wear on blowers, sensors, and igniters"; "Heavy snow accumulation is another local factor; it often blocks high-efficiency intake and exhaust vents"; "furnaces in the North Metro have a service life of 15 to 20 years"; "Since 1984 ... 40 years of local experience"; 24/7 across "Ramsey and the surrounding Anoka County area."
Why it wins: textbook strip-the-city collapse (split-entry/rambler stock near the Rum River, snow blocking high-efficiency intake/exhaust vents) plus a verifiable tenure. **Minor structural note:** it lives on a `/blog/` URL, not a clean `/services/furnace-repair/ramsey/` subfolder; the substance is combo-page grade, the URL slot is not ideal.

**G3 (companion). Goettl, AC Repair in Phoenix** [INDEXED]
`goettl.com/location/phoenix-arizona/ac-repair/`.
The summer/desert mirror of G1/G2: a clean city-first combo URL for one service in one city, desert-heat and monsoon-dust load, valley-wide truck dispatch. Same architecture as the location example, resolved to one service. (Bot-blocked fetch; re-confirm in browser.)

### BAD

**B1. The AI-spun 160-page combo network** [LABELED PATTERN, live policy]
8 services x 20 cities = 160 pages generated in one AI pass, each convincingly specific but none tied to a booked job, a permit, or a verifiable record. This is the exact "using generative AI tools ... to generate many pages without adding value" example in the live scaled-content-abuse policy (developers.google.com/search/docs/essentials/spam-policies), and as of the May 15, 2026 update those policies govern AI Overviews and AI Mode too.
Why it fails: it may pass a naive strip-the-city read (the specifics look local) but fails the **external-verifiability gate** (nothing resolves to a record outside the business's control) and was built for a keyword list, not a real service area the business books jobs in.

**B2. The subdomain-per-city combo farm** [LABELED PATTERN, real shape]
`phoenix.brand.com/ac-repair/`, `mesa.brand.com/ac-repair/`, `tempe.brand.com/ac-repair/`, each a thin clone funneling to one central form. (Sila's legitimate operation uses the subdomain-per-city shape; the shape, not Sila, is the lesson.)
Why it fails: it matches Google's named doorway example, "multiple domain names or pages targeted at specific regions or cities that funnel users to one page," almost verbatim. It is a structural doorway signal independent of content quality. Fix: flat subfolders on one domain, one URL pattern held site-wide.

---

## 4. HOMEPAGE (local HVAC entity anchor + primary conversion)

Job: establish the business as the local HVAC entity and drive the primary conversion.

### GOOD

**G1. Central Minnesota Heating and Cooling, Minneapolis** [VERIFIED-LIVE]
`centralminnesotaheatingandcooling.com`.
The dual-season HVAC entity done right. Verbatim: "Minneapolis homeowners' first call for same-day heating and cooling since 2009"; NATE-Certified; same-day service; the seasonal framing "deep-winter cold snaps knock out furnaces, summer heat waves push AC"; hyper-local coverage "Every Minneapolis ZIP 55401-55455" with Uptown, North Loop, Northeast, and Linden Hills named; a 1-year warranty.
Why it wins: local entity clarity (city + service + since-year in the hero), the credential (NATE), and the two-emergencies-one-market framing that is uniquely HVAC. Satisfies the homepage entity-anchor and E-E-A-T requirements.

**G2. Parker & Sons, Phoenix (strong body, one flagged weakness)** [VERIFIED-LIVE]
`parkerandsons.com`.
A dense, verifiable trust stack: "More than 15,000" Google reviews; established 1974; five live ROC license numbers; the Parker Family Plan membership; "Voted #1 by Consumers 14 Years in a Row!"; 24/7 with "No Extra Charge for Nights, Weekends, or Holidays"; "Service in Minutes, Not Days."
Why it wins as a homepage body: the proof density is exactly what an HVAC entity anchor needs. **The one weakness, called out honestly:** the H1 is "We're Not Your Average Joe!" which names neither the city nor the service. Parker survives it on brand equity; a single-location operator copying that H1 forfeits the local-entity signal. See B1.

### BAD

**B1. The entity-weak brand-voice hero** [VERIFIED-LIVE instance: Parker's H1]
An H1 like "We're Not Your Average Joe!" (or "Comfort, Reimagined") that names neither the city nor the HVAC service.
Why it fails for anyone without national brand equity: it breaks message-match / conversion scent and hands Google no local-entity signal in the most weighted on-page element. The fix is the G1 shape: "[Heating and Cooling] in [City] since [year]." Trips the homepage message-match / local-entity gate.

**B2. The generic "trusted local experts" homepage** [LABELED PATTERN]
"Your Trusted Local HVAC Experts. Licensed and Insured. Call Today!" with no city in the H1, a "5 stars" graphic with no count or source, "licensed and insured" with no number, and a stock hero of a smiling technician.
Why it fails: E-E-A-T claimed, not shown; no verifiable trust signal; no local entity. Trips the trust-signal + local-entity + real-imagery gates.

---

## 5. ABOUT / TEAM (the E-E-A-T and trust surface)

Job: prove Experience, Expertise, Authoritativeness, and Trust with named, credentialed, verifiable humans. HVAC is YMYL-adjacent (gas, combustion, carbon monoxide, refrigerant), so Trust is the dominant leg.

### GOOD

**G1. Hobaica Services, Phoenix** [VERIFIED-LIVE + INDEXED]
`hobaica.com/about-us/`.
Textbook shown-not-claimed E-E-A-T. The multi-generational family story with real dates: "Founded in 1952" by Paul Hobaica; two sons, Louis and Paul J., purchased the business in 1990; brother Mike joined in 2001; grown to "nearly 50" experts [INDEXED]. Verifiable credentials [VERIFIED-LIVE]: Arizona license C-39 ROC084870 (plus L-79 ROC084877, L-49 ROC084876, KB-2 ROC264735, K-77 ROC265390), ACCA member, BBB Accredited, Heat Pump Master Technician; plus NATE, National Comfort Institute, and Building Performance Institute certifications [INDEXED]. Founder's creed: "Treat others as you would want to be treated."
Why it wins: named humans + real dates + externally verifiable ROC license numbers + real trade certifications = Experience, Expertise, and Trust all shown and all checkable. Satisfies the **external-verifiability gate** on the about page, which most competitors skip.

**G2. The multi-generational heritage about page** [LABELED PATTERN, anchored to a verified claim]
Anchor: Standard Heating & Air Conditioning, Minneapolis, has "helped Minneapolis-St. Paul homeowners for nearly a century" [INDEXED; homepage bot-blocks fetch]. The winning pattern this heritage supports: a founding date and story, the named current leadership and their tenure, the count of NATE-certified and EPA 608-certified technicians, and local-community proof (chamber, sponsorships).
Why it wins: near-century local tenure is un-fakeable Experience; the pattern converts it into E-E-A-T by naming the people and credentials behind it rather than resting on the year alone. (Verify the extended specifics in a browser at build; only the century claim is index-confirmed here.)

### BAD

**B1. The no-humans about page** [LABELED PATTERN]
"Family owned and operated. Fully licensed and insured. Committed to quality and customer satisfaction." Zero named people, no founder, no dates, a stock team photo.
Why it fails: the section that exists to prove Experience names no one accountable. On a YMYL-adjacent trade (gas and CO risk), an anonymous about page is a trust failure. Trips the E-E-A-T Experience gate.

**B2. The claimed-credential-without-proof about page** [LABELED PATTERN, echoes the ACHR scam tell]
"NATE-certified technicians, licensed and insured, BBB A+," with no license number, no named certified techs, no EPA 608 evidence. The ACHR Orlando scam sites (see 1.B2) even displayed fake "A+ ratings and Better Business Bureau accreditation," which is precisely why claimed-but-unverifiable credentials now read as a scam signal.
Why it fails: trips the **external-verifiability + Trust gate**. The fix is Hobaica's move: print the actual license number and name the certified people.

---

## 6. SERVICE-AREA (coverage without doorway spam)

Job: communicate the region served, honestly and specifically, without manufacturing a doorway network.

### GOOD

**G1. Sila service-area page** [VERIFIED-LIVE / INDEXED]
`philadelphia.sila.com/about-us/service-area/`.
Names real submarkets instead of "and surrounding areas": South Philadelphia, Fishtown, Rittenhouse Square, West Philadelphia (the Boston region page names North Shore, South Shore, Metrowest).
Why it wins as coverage naming: named neighborhoods and submarkets give the page real local anchors. **Structural caveat (same as 2.G2):** it sits on a per-city subdomain; the neighborhood naming is the part to copy, the subdomain farm is not.

**G2. The honest-ZIP service-area block** [LABELED PATTERN, anchored to a verified instance]
Anchor: Central MN Heating's coverage names "Every Minneapolis ZIP 55401-55455" plus named west-metro suburbs (Edina, St. Louis Park, Hopkins, Minnetonka, Plymouth, Maple Grove, Eden Prairie) tied to a same-day promise [VERIFIED-LIVE for the ZIP framing; re-confirm the suburb list at build]. The winning pattern: list the real ZIPs and towns the business actually books, state honestly whether each is a drive-to service area (no staffed office there), and tie coverage to the operational promise (same-day where it is true).
Why it wins: real named anchors + honest service-area-business framing = coverage without doorway spam. Satisfies Minimum Unique Local Substance and NAP integrity.

### BAD

**B1. The "and all surrounding areas" empty coverage page** [LABELED PATTERN]
"We proudly serve [City] and all surrounding areas!" with zero named towns, no coverage nuance, no honest drive-to statement, no per-area detail.
Why it fails: no named anchors, nothing extractable, nothing local. Filler that trips the Minimum Unique Local Substance bar (3+ named anchors required).

**B2. The coverage-inflation / rented-address service-area page** [LABELED PATTERN, echoes ACHR Orlando]
Claiming a physical office or presence in towns where the business has no staffed address, propping the claim on a virtual mailbox, a UPS box, or a phantom plaza address to look local, exactly the fabricated-address behavior in the ACHR Orlando case (1.B2).
Why it fails: trips the **NAP-integrity / no-fabricated-or-rented-address gate** (a GBP suspension trigger) and the doorway signal. A service-area business must be transparent that it drives to a region and holds no public office there.

---

## Counts and the sharpest HVAC insight

- Page types covered: 6 (location, service, service-in-city, homepage, about/team, service-area).
- GOOD examples: 13. BAD / penalty-risk examples: 12. Every page type has at least 2 of each.
- Verified live or index-confirmed businesses used as anchors: Discount AC & Refrigeration (Phoenix), Goettl (Phoenix / Las Vegas), Parker & Sons (Phoenix), Sila (Philadelphia), O'Boys (Minnetonka), C&M Heating and Air (Ramsey), Central MN Heating and Cooling (Minneapolis), Hobaica (Phoenix), Standard Heating (Minneapolis). Documented penalty/scam cases: upnorthmedia.co doorway case, ACHR News Orlando AI-scam-sites case.

**Sharpest HVAC-specific insight:** in HVAC the strip-the-city test is won or lost on **the climate-driven physical failure mechanism**, and that mechanism is opposite by season and market. Phoenix wins with "dust storms clog the condenser coil and a low-refrigerant compressor can't keep up past 110F" (Discount ACR); Minnetonka wins with "1970s-80s heat exchangers and wind off Lake Minnetonka" and "sub-zero cycles wear the blower, sensors, and igniters, snow blocks the high-efficiency intake/exhaust vents" (O'Boys, C&M). Both are un-spinnable because they are physics tied to a named place. The doorway-page competitor, by contrast, writes "comfort all year in [City]" in a one-season market, and the 2026 AI-spun version fakes convincing local specifics that resolve to no record. So the HVAC moat is the same as the doctrine's: pair the real local failure mechanism (which collapses on city-swap) with an externally verifiable proof (an ROC/license number, a real utility like APS/SRP, a named local job, a checkable NATE/EPA credential). Specificity plus verifiability, never one without the other.

## Sources (opened this session)

- Discount AC & Refrigeration, Phoenix (verified live): discountacr.com/services-areas/ac-repair-near-me-in-phoenix/
- Goettl Phoenix / Las Vegas (index-confirmed, fetch bot-blocked): goettl.com/location/phoenix-arizona/ , /location/phoenix-arizona/ac-repair/ , goettl.com/location/las-vegas-nevada/
- Parker & Sons, Phoenix (verified live + indexed): parkerandsons.com/ , /cooling , /cooling/ac-repair
- Sila, Philadelphia (verified live): philadelphia.sila.com/hvac-services/cooling/maintenance-repair/ , /about-us/service-area/
- O'Boys, Minnetonka furnace repair (verified live): calloboys.com/area/minnetonka-mn-furnace-repair/
- C&M Heating and Air, Ramsey furnace repair (verified live): candmheatingandair.com/blog/furnace-repair-ramsey-mn-trusted-local-experts-for-north-metro-winters
- Central MN Heating and Cooling (verified live): centralminnesotaheatingandcooling.com
- Hobaica Services, Phoenix (verified live + indexed): hobaica.com/about-us/
- Standard Heating, Minneapolis (index-confirmed century claim): standardheating.com
- HVAC suburb-swap doorway case (documented, secondary, verify): upnorthmedia.co/blog/doorway-pages-seo
- AI-generated HVAC scam sites, Orlando (documented, ACHR News, Jan 2026): achrnews.com/articles/166082
- Google Search spam policies (doorway + scaled content abuse): developers.google.com/search/docs/essentials/spam-policies
- R-454B / AIM Act / SEER2 technical context (industry, verify at build): AIM Act Jan 1 2025 R-410A manufacturing restriction; R-454B A2L, GWP 466 vs R-410A 2,088

All quotes captured July 2026. Re-verify perishable facts (live URLs, license numbers, review counts, refrigerant-transition dates, AI-crawler policy) at build time. No live A/B test behind this document; win/fail rationales map to the gates in `../service-city-page.md` and `knowledge/doctrine/`.
