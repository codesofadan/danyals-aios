# The Service-in-City Page: The Definitive 2026 Build Playbook

The money page. One service, one city. "Emergency plumber in Austin." "Invisalign in Scottsdale." "AC repair in Mesa." "Personal injury lawyer in Baltimore." This is the single highest-intent, highest-converting page a local service business owns, and it is also the single highest doorway-spam risk in the entire content system. Both facts are central. Treat them as one problem: the same lever that makes this page convert (nailing one exact query for one exact place) is the lever that, done lazily at scale, gets a whole site deindexed.

A builder handed this file plus one real business (name, real service, real target city, real crew, real reviews, real completed jobs, real photos) can produce a single service-in-city page that a top-0.1% local operator signs off on, and that survives Google's doorway and scaled-content-abuse policies by construction, with no further guidance.

Governing law: `knowledge/doctrine/seo-system-doctrine.md`, especially **Law 8** (optimize the reward function, not proxies: no detector-evasion, humanize via real facts and specificity). This page is humanized the correct way, by being made of local facts a competitor does not have. Read `knowledge/doctrine/google-compliance-spine.md` alongside it.

Every quantitative figure here is **directional** unless flagged PRIMARY. There is no live A/B test behind this document. Verify each number against its named source and your own analytics before you bank on it. No number appears here as a promise.

Style note for the builder: this playbook writes for a builder, not a reader. If a rule says "add local content," it has failed. It must say "add the named intersection this firm actually litigates accidents at, the local court's judge count, and one verdict amount from this county." Hold every rule to that bar.

---

## 1. Purpose and the ONE job

### 1.1 The one job

**Rank for, earn the AI citation for, and convert the visitor who searched one specific service in one specific place.** Not the whole city. Not the whole service line. The exact intersection of both: `[service] + [city]`.

That intersection is why this is usually the highest-converting page in a local site. The searcher who types "emergency plumber in Round Rock" or "dental implants in Plano" has already done two acts of qualification for you. They named the service (so intent is transactional, not informational), and they named the place (so they want a local provider, not a national listicle). There is almost no top-of-funnel drift left. Ruler Analytics 2026 (5M+ conversions, directional, verify) reports legal converts at 56.3% by phone and professional services at 52.6% by phone. For a service-in-city page catching a named-service-named-place query, the buyer is closer to the call than on any other page you build. A generic city page catches "plumber Austin" (broad); a service hub catches "drain cleaning" (place-agnostic); only the combo page catches "drain cleaning in Cedar Park" with full scent from query to headline to CTA.

### 1.2 Where it sits in the silo

The service-in-city page is a **child of two parents at once**, and that dual parentage is the whole architecture:

- **Parent 1: the service hub.** `/services/drain-cleaning/` describes the service brand-wide. The combo page `/services/drain-cleaning/cedar-park/` is its city-specific child. The hub links down to every city it serves; each city child links back up to the hub.
- **Tied to: the city.** The city location page `/locations/cedar-park/` (if one exists) covers the whole business in that town. The combo page links laterally to it and to sibling services in the same city.

Pick ONE canonical URL pattern and hold it site-wide (Section 10.1). The two live patterns are service-first (`/services/[service]/[city]/`) and city-first (`/locations/[city]/[service]/`). Roto-Rooter runs a real, live city-first hybrid: `rotorooter.com/houston/` is the city hub, and `rotorooter.com/houston/emergency-plumber/` and `rotorooter.com/houston/drain-cleaning/` are the service-in-city children (verified live 2026, rotorooter.com/houston/). Either pattern is defensible. Mixing them is not.

The internal-linking shape is hub-and-spoke on both axes: service hub to city children, city hub to service children, and contextual inline links between siblings inside the local body copy. Never orphan a combo page behind a JavaScript store-locator that renders no crawlable `<a href>`. Orphaning is the single most common real indexation failure for these pages.

### 1.3 Why it is also the highest-risk page

The reason this page converts (one service, one city, high scent) is exactly why it multiplies into a doorway hazard. A business with 8 services and 20 cities needs 8 x 20 = **160 of these pages**. The moment a builder generates 160 pages by swapping two tokens into one template, the site has manufactured a doorway network, and Google's scaled-content-abuse and doorway policies are written almost verbatim to catch it. Section 5 is the full rule set. Hold it as tightly as you hold the conversion rules. A page that converts brilliantly but is one of 160 find-and-replace clones does not get the chance to convert, because it does not get indexed.

---

## 2. Target intent and real query patterns

### 2.1 The query shapes

The combo page targets a family of near-identical high-intent queries. Build for all of them at once:

- **`[service] in [city]`** - "water heater repair in Tempe," "invisalign in Scottsdale." The canonical target. Explicit service, explicit place.
- **`[service] [city]`** (no preposition) - "roof replacement Frisco." Same intent, terser.
- **`[service] near me`** - resolves to the searcher's location; a combo page for the town they are standing in is what ranks. "Near me" is a place token Google fills in from geolocation, so a page strongly tied to that town catches it.
- **`emergency [service] [city]`** / **`[service] [city] open now`** - urgent variant, phone-dominant.
- **`[service] [neighborhood/suburb]`** - "AC repair West Lake Hills." The sub-city long tail. This is where a well-built combo page that names its neighborhoods wins queries the city page cannot.
- **`best [service] in [city]`** / **`[service] [city] cost`** - hybrid intent (see 2.3); these route into AI answers and comparison surfaces, not just the pack.

### 2.2 The emergency vs considered split (this reorders the page)

Two intent states use this page, and they demand different page orders. Decide which the target query is before writing a line.

- **URGENT** (emergency plumber, HVAC-down, lockout, emergency dental, water damage, towing): the buyer is in pain now. Phone is the primary CTA. The click-to-call leads the hero. The form can be suppressed or deferred below the fold. The trust bar leads with speed and availability ("we answer live, on-site same day"). Response-time promise is load-bearing.
- **CONSIDERED** (invisalign, kitchen remodel, roof replacement, solar, implants, med spa): the buyer is researching a planned purchase. A form, self-scheduling calendar, or "book a consult" leads. Financing, before/after galleries, and project portfolios move up the page. Reviews with project photos beat a bare star count. Price transparency and process detail matter more than raw speed.

The conversion *purpose* (become a lead) is single; the *CTA* is not. Offering both call and form is not a leak, it serves two intent states. What is a leak on a paid landing variant is a full 8-link global nav.

### 2.3 Intent mix governs which SERP surface you are fighting for

Pure local-intent queries ("emergency plumber in Austin") are won in the local pack and localized organic. Hybrid and informational variants ("best invisalign in Scottsdale," "invisalign in Scottsdale cost") route the searcher into an AI Overview and comparison content first (Section 3). One combo page has to serve both: the pack-and-organic transactional query AND the hybrid research query. That is why the page carries both a fast local conversion path and self-contained, extractable answer passages.

---

## 3. The 2026 SERP and AI-answer reality

Live and cited. Re-verify at build time; these surfaces move quarterly.

### 3.1 For pure local-intent combo queries, the pack still rules and AI Overviews are rare

Whitespark's local AI Overviews study (PRIMARY-ish: 540 queries, 3 US cities - Houston, Phoenix, Denver - 6 industries including plumbers, personal injury lawyers, dentists, optometrists; published May 12, 2025; whitespark.ca/blog/case-study-the-prevalence-of-ai-overviews-in-local-search/) found:

- **Local-intent queries: AI Overview appears 15% of the time; the local pack appears 93% of the time.**
- **Informational-intent queries: AI Overview 92%; local pack 6%.**
- **Hybrid-intent queries: AI Overview 97%; local pack 17%.**

The relationship is inverse and driven by intent, not geography. A buyer typing a direct transactional local query wants phone numbers, hours, and directions now, which the 3-pack delivers perfectly, so a text summary is redundant and Google mostly suppresses it. This is the single most important 2026 fact for this page: **for the money query, the local pack (which is fed by the Google Business Profile, not the page) is still the dominant surface, and the combo page is one of three surfaces, not the sole one.**

### 3.2 For the hybrid variants, AI answers dominate and cite third parties more than the business

In the same study's Houston plumber dataset, of the AI citations shown, **60% pointed to third-party publishers** (Indeed, Reddit, Yelp) and only **40% cited individual local businesses**. So the "best [service] in [city]" and "[service] [city] cost" variants are being answered by an engine that prefers to cite directories and forums over the service business's own page. The combo page competes for that 40% by being maximally extractable and entity-clear, and the business competes for the rest through its presence on the third-party surfaces the engines pull from (Yelp, GBP, industry directories).

### 3.3 Spam policy now governs the AI surfaces too

As of a Google documentation update **published May 15, 2026**, every spam policy that governed blue-link results, including doorway pages and scaled content abuse, **now explicitly governs what appears inside AI Overviews and AI Mode** (ppc.land/google-spam-policies-now-officially-cover-ai-overviews-and-ai-mode-in-search/, verify against Search Central). Translation: a doorway combo page is not just excluded from the ten blue links, it is excluded from the AI answer too. There is no "the AI surface is a loophole" move. The uniqueness bar in Section 5 is the price of admission to every surface at once.

### 3.4 The three-surface truth for this page

For any service-in-city query the visibility is split across: (1) the **GBP profile** - the primary local-pack and primary AI-cited entity, largely controlled off-page; (2) the **AI answer surface** - which for hybrid queries prefers third-party citations; (3) **the combo page itself** - which wins localized organic, feeds the GBP its city-specific landing target, and is the only surface you fully control. Optimize the page as the controllable third of a three-part system, never as if it were the whole system. A system that only tracks blue-link rank for these queries is optimizing yesterday's surface (Doctrine Law 13).

---

## 4. Section-by-section architecture

Build in this order for URGENT intent; for CONSIDERED, move financing, gallery, and the booking calendar up to positions 4-7 and let the form or scheduler lead the hero. Each section states: must-contain, the named copy/CRO framework, the local-SEO requirement, the schema requirement, a real-example precedent, the anti-pattern, and a binary PASS test.

### 4.1 Hero

- **Must contain:** an H1 with the exact service AND exact city verbatim; a one-line problem-first subhead under 10 words; a tappable `tel:` number; the primary CTA (call for URGENT, form/scheduler for CONSIDERED); an authentic local hero image (this crew, this town), not stock.
- **Framework:** Message match / conversion scent (Unbounce). The H1 repeats the exact words the visitor searched: `[Service] + [City] + [Differentiator/Urgency]`, e.g. "Emergency Plumber in Round Rock, TX - On-Site Same Day." URGENT uses PAS (Problem-Agitate-Solution) compressed into the hero; CONSIDERED uses BAB (Before-After-Bridge) selling the after-state. Write at a 5th-to-7th-grade level.
- **Local-SEO requirement:** service and city both appear in the H1 verbatim. Lead the section with a self-contained answer sentence an AI engine can lift: "[Business] provides [service] in [City] and [named nearby areas], available [hours/response]."
- **Schema requirement:** none in the hero itself; the H1 text must match the `name`/`areaServed` values in the page's JSON-LD (Section 10).
- **Real precedent:** Roto-Rooter Houston leads with a location-and-service hero and a local number (713-472-5554), verified live (rotorooter.com/houston/). Its emergency-plumber child page carries the service-in-city intent explicitly.
- **Anti-pattern:** a brand-voice headline naming neither service nor city ("Comfort, Reimagined"); dynamic-keyword-insertion producing a wrong or awkward city string; the same templated H1 across 160 pages with no unique body beneath it.
- **PASS test:** H1 contains both the exact service and the exact city; phone and primary CTA are visible without scrolling on a 375px viewport.

### 4.2 Trust bar (directly below hero, above the fold)

- **Must contain:** at least 3 distinct trust signals: Google star rating **with review count and source**, license number as a literal lookup-able string, insured/bonded status, years in business, 1-2 relevant certification badges.
- **Framework:** Trust-before-benefit. Local buyers are trust-gated before benefit-gated; a stranger is deciding whether to let this business into their home or handle their injury claim.
- **Local-SEO requirement:** the license number is a public regulatory record, safe to print, and a hard E-E-A-T "who is responsible" signal. Print the license number and carrier name plus insured/bonded status. **Never print the insurance policy number or coverage limits** (fraud/impersonation vector).
- **Schema requirement:** license as no formal property; reflect years-in-business via `foundingDate` on the provider node if used, and the named responsible manager as a `Person` node (Section 10).
- **Real precedent:** Roto-Rooter Houston stacks a 4.9 rating with 1,647 reviews and names the local licensed manager (Ryan Throne, license M-43414) and manager Mike Krysa, verified live. That named, licensed, local human is the un-fakeable trust anchor.
- **Anti-pattern:** "fully licensed and insured" as a floating badge with no number; a "5.0" with no review count (reads manufactured); twelve logos diluting the two that matter (Google rating and state license).
- **PASS test:** at least 3 distinct trust signals sit above the fold, and at least one (license number or review count with source) is externally verifiable.

### 4.3 The exact service, framed for this city

- **Must contain:** a tight description of THIS service as delivered in THIS city, benefit-led, with the specific local sub-services or variants that matter here placed first.
- **Framework:** Scannability plus specificity. Confirm "yes, we do your exact thing, here" without forcing a read. On an organic page, link laterally to sibling services in the same city and up to the service hub.
- **Local-SEO requirement:** one dedicated page per service-in-city is a rising factor. Whitespark's Local Search Ranking Factors survey (2023 edition, directional, verify current edition) found "dedicated page for each service" rose 186% and "internal links to the GBP landing page from other pages" entered the ranked factors at #24. This section is where the combo page earns its dedicated status, so it must describe the service specifically, not link out to a generic service hub and call it done.
- **Schema requirement:** a `Service` node with `serviceType` = the exact service, `provider` = the LocalBusiness node, and `areaServed` = the exact city (Section 10).
- **Real precedent:** Roto-Rooter's Houston children split by service (`/houston/emergency-plumber/`, `/houston/drain-cleaning/`), each describing that one service in that one city rather than one page listing all services.
- **Anti-pattern:** a 20-item equal-weight service mega-list (paralysis, diluted topical focus); stuffing every service-plus-city permutation into one page (thin and spammy); describing the service in city-agnostic boilerplate.
- **PASS test:** the service is described specifically and is internally linked up (hub) and lateral (siblings); the description is not identical to the brand-wide service hub.

### 4.4 The local-proof block (the un-templated core, the section that wins or loses everything)

- **Must contain (hard minimum, this is the Minimum Unique Local Substance bar, Section 5):** at least 3 named hyper-local geographic anchors this business actually serves (neighborhoods, suburbs, landmarks, highways, intersections - NOT the city name); at least 1 named local condition that changes how THIS service is delivered here (soil, water chemistry, climate/freeze-thaw, housing stock era, local code/permit rule, common local failure mode), causally tied to the service; at least 1 externally verifiable local proof (a named completed local job, a permit record, a dated geotagged photo, or a city-tagged review resolving to a real Google profile).
- **Framework:** E-E-A-T first-hand Experience at local altitude (Google added "Experience" to E-E-A-T in December 2022 specifically to reward has-actually-done-this proof). This is the hardest thing a spun template can fake and the section that decides the doorway question.
- **Local-SEO requirement:** this block must be a genuine majority of the page body on organic pages. The 2026 moat is not specificity alone (an LLM can now write convincing fake specifics across 40 towns in one pass); the moat is **external verifiability** - a permit a skeptic can look up, a review that resolves to a real profile, dated job photos.
- **Schema requirement:** none required, but this content is what the `areaServed` and any `Review` displayed (from a compliant source) describe; keep it in crawlable HTML, never locked in an image.
- **Real precedent (two, both verified live 2026):**
  - Roto-Rooter Houston names Aldine, Jersey Village, Hunters Creek, Spring Valley; explains the local mechanism ("local 'gumbo' clay soil expands and contracts with moisture changes, resulting in misaligned, cracked, or collapsed underground pipes"); names the city water sources (Lake Conroe, Lake Houston, Lake Livingston) and hard-water mineral load. Swap the city and every one of those sentences collapses.
  - Miller & Zois's Baltimore personal injury page (millerandzois.com/claims-by-maryland-jurisdictions/baltimore-personal-injury-lawyer/) names the Circuit Court for Baltimore City ("one of the largest in the state, with 33 judges"), a specific dangerous intersection (Gwynns Falls Parkway and Reisterstown Road, "46 accidents in a year"), named local hospitals tied to verdicts, and specific jurisdiction verdicts ("2024: $8,310,172 Verdict," "2021: $34,770,292 Verdict"). Verdicts by jurisdiction are the un-fakeable version of local proof for legal.
- **Anti-pattern:** "We proudly serve [City] and surrounding areas" with zero named streets, landmarks, permits, or operational detail; a "Common [Service] Issues" section that reads identically for any town.
- **PASS test:** passes the strip-the-city test (Section 5.3) and contains at least one externally verifiable local claim.

### 4.5 Real photos

- **Must contain:** photos of this crew, branded trucks, and completed local work; named technicians; the owner shown. Stock photography is prohibited.
- **Framework:** visual proof of Experience. Real local imagery is the fastest trust tell and the hardest thing a template competitor can fabricate.
- **Local-SEO requirement:** deliver as WebP/AVIF with responsive `srcset` and `fetchpriority="high"` on the LCP hero; lazy-load everything below the fold. Engineer around the weight; do not drop the photos.
- **Schema requirement:** reference the owner or named manager as a `Person` node so Experience is machine-readable; images can carry `ImageObject` where warranted.
- **Real precedent:** the harvested corpus (A.J. Alberts Plumbing "Locally Owned Since 1989," Thelen Mechanical owner/team video) and Roto-Rooter's named local managers.
- **Anti-pattern:** the Getty smiling call-center woman in a headset; the same stock crew photo across all 160 city pages (a reverse-image search is how a rater and a competitor both catch this).
- **PASS test:** at least one real, city-attributable image is present and no stock photography is used in the proof zone.

### 4.6 Reviews / testimonials (city-tagged, placed high)

- **Must contain (hard minimum):** 3 real named reviews, city-tagged, dated, placed high (right after the service or local-proof block, not in the footer). Repeat one compact proof element near the final CTA.
- **Framework:** proof consumed before the ask lowers perceived risk. Show the owner replying to recent reviews (last 30-90 days) to prove the business is currently operating and currently good.
- **Local-SEO requirement (gets this wrong constantly):** display reviews as on-page HTML. **Do NOT wrap your own LocalBusiness, Service, or Organization nodes in Review or AggregateRating JSON-LD to mint star snippets.** Since 2019 Google does not render review rich results when the entity controls the reviews it rates; self-marking your own reviews renders no stars and is wasted markup. The stars in the map pack come from GBP. Display-source compliance: do not scrape Google review text (Places API is capped and its terms restrict caching/republishing); use Google's own review widget, first-party testimonials collected with permission, or your own reviews via the Business Profile Performance API.
- **Schema requirement:** none on your own nodes for reviews (see above). This is the one place where the correct schema move is to add nothing.
- **Real precedent:** Roto-Rooter Houston shows a city-tagged named review ("Dee G., Houston, TX") alongside its live 4.9 / 1,647-review count.
- **Anti-pattern:** unattributed testimonials ("Great service! - J.D."); a hardcoded "5.0" graphic with no names or dates; a builder adding Review schema to these reviews and breaking the rule above.
- **PASS test:** 3+ reviews, city-tagged and dated, in HTML, high on the page; no self-serving Review/AggregateRating JSON-LD.

### 4.7 Process / how-it-works

- **Must contain:** a 3-4 step numbered sequence, icon plus one line each ("1. Call or book, 2. On-site local diagnosis, 3. Upfront flat quote, 4. Same-day fix"). Optionally "meet your tech" (name and photo of the assigned local pro).
- **Framework:** de-risk the action. Removes fear of surprise pricing, no-shows, and an unvetted stranger.
- **Local-SEO requirement:** none specific; keep it human-readable and scannable. Where a step is genuinely local ("we pull the [City] permit for you"), say so, and it doubles as local-proof.
- **Schema requirement:** optional `HowTo` is not recommended here (Google restricted HowTo rich results); keep it plain HTML.
- **Real precedent:** the ServiceTitan and Hook Agency corpora repeatedly show a simple 3-4 step "how it works" as a standard conversion block.
- **Anti-pattern:** a wall of prose describing the process; a 7-step sequence no one reads.
- **PASS test:** 3-4 scannable steps present.

### 4.8 Offer / coupon and financing (or explicit N/A)

- **Must contain:** a quantified offer in the CTA zone ("$55 off drain cleaning," "0% APR for 12 months via Synchrony," "same-day," "free local estimate"), or an explicit "N/A because [reason]" for verticals that do not use offers.
- **Framework:** specificity is credibility; a number is verifiable in the reader's head, an adjective is noise. The offer usually out-moves any headline tweak, so construct the offer before polishing copy. Only publish terms you actually underwrite.
- **Local-SEO requirement:** none. **Compliance gate:** published financing terms with a stated repayment period ("0% APR for 12 months") are triggering terms under Truth-in-Lending / Reg Z advertising rules and may require full financing-terms disclosure; verify with counsel before publishing financing specifics.
- **Schema requirement:** the `Offer`/`priceSpecification` can be nested under the `Service` node for completeness, but do not expect a price rich result for a custom-quote service; a genuine fixed-SKU productized offer (e.g. "$149 drain camera inspection") is the only case where a price is honestly markup-able, and price snippets increasingly require Merchant Center, not JSON-LD alone.
- **Real precedent:** Roto-Rooter Houston shows "$55 Off Any Plumbing or Drain Cleaning Service," verified live.
- **Anti-pattern:** "Competitive pricing, quality you can trust." Commits to nothing, converts nothing.
- **PASS test:** a quantified offer is present, or an explicit N-A with a reason.

### 4.9 Response / guarantee commitment

- **Must contain:** an explicit response-time commitment or workmanship guarantee, stated precisely and matched to the vertical's scar tissue ("On-site same day in [City] and [named areas]," "Lifetime workmanship guarantee," "No fee until we win," "No hidden cost guarantee").
- **Framework:** risk reversal is the highest-leverage conversion mechanic on a local page. Legal = "No fee until we win"; HVAC = "No hidden cost guarantee"; plumbing = "Free estimate, no service fee"; roofing = "Free inspection."
- **Local-SEO requirement:** none. **Operational gate:** audit the live answer-rate before promising "24/7" or "same-day." If after-hours calls hit voicemail, the promise converts the click and burns the lead. Tie the response promise to named areas where it is actually true ("same-day across Cedar Park and Round Rock"), which makes it both more credible and more local.
- **Schema requirement:** none.
- **Real precedent:** Roto-Rooter Houston commits to same-day and 24/7 availability; the harvested legal corpus ("No Fee Until We Win").
- **Anti-pattern:** "100% satisfaction guaranteed" with no duration or mechanism; a "60-minute response" the operation cannot answer after hours.
- **PASS test:** a precise, operationally-true response-time or guarantee commitment is present.

### 4.10 FAQ (city-specific)

- **Must contain (hard minimum):** 5 FAQs as natural question headers, **at least 2 locally specific**, answering real local logistics (response time to named areas, coverage, local permit/code requirements, local pricing band).
- **Framework:** objection kill. Each FAQ answers a real reason a local buyer hesitates, and each doubles as an extractable passage for the hybrid/AI-answer query (Section 3.2).
- **Local-SEO requirement:** ship `FAQPage` JSON-LD, but **expect no rich-result stars** (Google restricted FAQ rich results to authoritative government and health domains in August 2023). Build the FAQ for conversion and for passage-level AI-Overview citability (each answer a self-contained, liftable 1-2 sentences), not for SERP decoration.
- **Schema requirement:** `FAQPage` with each `Question`/`acceptedAnswer` mirroring the visible text exactly (Section 10).
- **Real precedent:** Roto-Rooter Houston carries 11 questions, verified live; the Pflugerville page (harvest) carries 13 location-specific FAQs.
- **Anti-pattern:** keyword/FAQ padding that says nothing to a human ("What is the best plumber in [City]? We are the best plumber in [City]."). RicketyRoo names this exact pattern as a spam tell (ricketyroo.com/blog/location-page-spam/).
- **PASS test:** 5+ FAQs, at least 2 genuinely city-specific, each answer a self-contained liftable passage.

### 4.11 Closing CTA, NAP, and map / service-area

- **Must contain:** a final CTA repeating call and form/scheduler; the canonical NAP block (name, address, phone) matching GBP exactly; hours; and an embedded map (lazy-loaded) or a named service-area coverage list.
- **Framework:** last-chance conversion for the scroller who read the whole page.
- **Local-SEO requirement:** NAP must be identical across visible text, JSON-LD, and GBP (suite formatting, "St" vs "Street," the exact number). **Storefront vs SAB:** storefront pages carry a real staffed walk-in address; service-area-business pages cover a drive-to region and must be transparent that there is no public office there. **Never invent or rent a street address (virtual mailbox, UPS box) to look more local** - it is both a GBP suspension trigger and a doorway signal. Call tracking done right: keep the true GBP-matched number as the static canonical NAP in HTML and JSON-LD; swap in a tracking number client-side via JS DNI only for paid channels, gated to exclude crawler user-agents so crawlers keep the static number.
- **Schema requirement:** the LocalBusiness `PostalAddress` and `telephone` here must equal the visible NAP and the GBP; add `hasMap` (a Google Maps URL, not a bare CID) and `geo` with the real coordinates (Section 10).
- **Real precedent:** Roto-Rooter's location pages present one coherent NAP set plus state/county licensing.
- **Anti-pattern:** a tracking number in the visible NAP/schema that never matches GBP; a JavaScript-only store-locator rendering no crawlable links (orphaned pages).
- **PASS test:** NAP is identical across page text, schema, and GBP; the address class matches the business type; no fabricated address.

### 4.12 Persistent sticky mobile CTA bar

- **Must contain:** a sticky bar for the whole mobile scroll, with a call button and a "Get a quote / Book" anchor; thumb-first tap targets (WCAG 2.2: 24x24 CSS px minimum, 44x44 recommended); visible focus states.
- **Framework:** the visitor who decides on screen 4 should never scroll back to the hero to act.
- **PASS test:** sticky bar present the whole scroll, tap targets meet the minimum, does not cover content.

---

## 5. THE SCALE PROBLEM (the doorway rule set)

This is the section that keeps the site alive. Read it as binding, not advisory.

### 5.1 The arithmetic that creates the hazard

A business with 8 services x 20 cities needs **160 combo pages**. Generating 160 pages by injecting two variables into one template is the exact behavior Google's spam policies name. From the live policy (developers.google.com/search/docs/essentials/spam-policies, verified 2026):

- **Doorway abuse** is "when sites or pages are created to rank for specific, similar search queries." Named examples include "having multiple domain names or pages targeted at specific regions or cities that funnel users to one page" and "creating substantially similar pages that are closer to search results than a clearly defined, browseable hierarchy."
- **Scaled content abuse** is "when many pages are generated for the primary purpose of manipulating search rankings and not helping users." Named examples include "using generative AI tools or other similar tools to generate many pages without adding value for users" and "creating many pages where the content makes little or no sense to a reader but contains search keywords."

The March 2024 core-plus-spam update gave scaled-content-abuse real enforcement teeth (SpamBrain), and scaled content abuse was reported as Google's top March 2026 enforcement priority, with mass-templated sites seeing 50-80% traffic drops (digitalapplied.com, secondary/reported, verify). The doorway policy has been enforced with manual actions and algorithmic updates since the 2015 Doorway Update.

### 5.2 The rule: usefulness and uniqueness, not page count

Volume is not the trigger; **usefulness is**. Google's own framing is behavioral: can the user finish the job on this page (local phone, local booking, local proof, local team), or are they funneled to a generic central destination? A site with 50 thin city pages can be penalized while a site with 10,000 genuinely useful ones is untouched. The doorway line is "intermediate vs destination," not a number.

So the governing rule for the 160-page problem is not "make fewer pages." It is: **tie page creation to real service areas the business actually books jobs in, not to a keyword list.** If you cannot write the local-proof block (4.4) truthfully for a town, do not make the page for that town. One strong, locally-substantiated page per provable service area beats twenty find-and-replace clones, and it is the only version that survives.

### 5.3 The hard doorway test (run on every combo page before it ships)

**The strip-the-city test (the kill trigger).** Strip the city name AND the 3 named local anchors from the page. Read what remains. If the body still makes complete, correct sense for any other town in the country, the page is boilerplate and it FAILS. It must not ship. A winner fails-to-generalize on purpose: Roto-Rooter Houston's "gumbo clay soil" and "Lake Conroe / Lake Houston / Lake Livingston" sentences collapse the moment you swap the city; that collapse is the target. Miller & Zois Baltimore's "Circuit Court for Baltimore City, 33 judges" and "$34,770,292 verdict" collapse identically.

**The external-verifiability test (the 2026 differentiation gate).** At least one local claim on the page must resolve to a record outside the business's own control that a skeptic or an answer engine could independently confirm: a lookup-able permit, a review that resolves to a real Google profile, a named public courthouse, a public water-authority fact, a licensed manager's license number. Specificity alone is no longer the moat, because an LLM can fake convincing specifics across 40 towns in one pass. Verifiability is the moat.

### 5.4 The Minimum Unique Local Substance bar (the per-page floor)

**A service-in-city page may not publish unless it carries, for THIS service in THIS city, ALL of the following:**

1. **At least 3 named hyper-local geographic anchors** the business actually services (neighborhoods, suburbs, landmarks, highways, or intersections). The city name does not count toward the three.
2. **At least 1 named local condition** that changes how THIS service is delivered here (soil, water chemistry, climate/freeze-thaw, housing stock era, local code/permit rule, common local failure mode), stated with a causal link to the service.
3. **At least 1 externally verifiable local proof** (a named completed local job or job count, a permit/record a skeptic can look up, a dated geotagged photo, or a city-tagged review that resolves to a real Google profile).
4. **At least 2 city-specific FAQ answers** addressing real local logistics (response time to named areas, local permit/code, local pricing band, local dispatch).
5. **A real local conversion path that terminates on-page** (local or DNI-to-canonical phone, on-page booking or form) plus a real address for storefronts or an honest service-area statement for SABs. No fabricated or rented address.

**And a proportional floor:** a genuine majority of the body (target roughly 50%+, treated as a working heuristic, never a safe harbor, because Google publishes no percentage) must be city-specific and non-transferable. The real test remains 5.3: could a competitor regenerate this page by swapping the city token? If yes, it fails regardless of the percentage.

Any page that cannot meet all five items truthfully is not a page. It is a signal to either gather the real local substance (call the crew, pull the permit, cite the real job) or not build the page for that town yet.

### 5.5 The doorway smoke detector (post-publish monitoring)

Watch Google Search Console index coverage across the combo-page cohort. "Crawled - currently not indexed" and "Discovered - currently not indexed" spreading across a set of service-in-city pages is the concrete, monitorable signal that Google is treating them as scaled content. This is a better early warning than any bounce or dwell heuristic (which has no safe threshold). If it spreads, consolidate the thin pages into fewer, genuinely substantiated ones before it becomes a site-wide signal.

### 5.6 The sourcing engine for real local substance (how to fill the bar without fabricating)

1. **Call the crew.** Ask the techs who actually work that town: what breaks most here, what is the housing stock, the recurring local failure mode. That yields the named local condition.
2. **Pull the local physical reality.** Soil, water hardness, water table, climate/freeze-thaw, tree species causing root intrusion, coastal salt, local water authority and its sources. Verifiable, un-fakeable.
3. **Pull the local regulatory reality.** Permit rules, licensing body, a linkable permit record, for legal the county court and its procedures. Municipal permit data is inconsistent and often has no API; do this per-market by hand.
4. **Cite a named local job or result.** "180+ installs in Scottsdale over 4 years," a completed job on a named street, a verdict from this county, a review resolving to a real profile. Pull from your own completed-job records, your own reviews via the Business Profile API, and dated geotagged photos.

Never fabricate any of these. A fabricated local specific is both a doorway signal and the fastest path to a trust penalty (CLAUDE.md hard rule). If the operator does not have it, the SME interview surfaces it or the page waits.

---

## 6. Best-in-class teardowns (real, live-verified 2026)

**WINNER 1 - Roto-Rooter, Houston (service-in-city hybrid).** `rotorooter.com/houston/` is the city hub; `rotorooter.com/houston/emergency-plumber/` and `rotorooter.com/houston/drain-cleaning/` are the true service-in-city children (verified live 2026). Why it wins: location-and-service hero with a local number (713-472-5554); a trust stack (4.9 rating, 1,647 reviews) with a named local licensed manager (Ryan Throne, M-43414) and manager Mike Krysa; genuinely local proof that fails the strip-the-city test (named neighborhoods Aldine, Jersey Village, Hunters Creek, Spring Valley; the "gumbo clay soil" pipe-failure mechanism; city water sources Lake Conroe / Lake Houston / Lake Livingston and hard-water mineral load); a city-tagged named review ("Dee G., Houston, TX"); 11 FAQs; a quantified offer ("$55 Off"); same-day and 24/7 commitments. All five jobs covered. **Authority caveat:** Roto-Rooter also ranks on national brand link authority and entity strength; a single-location operator who copies the structure inherits none of that and must earn the benefit through links, reviews, and GBP. The structure is necessary, not sufficient.

**WINNER 2 - Miller & Zois, Baltimore personal injury (`millerandzois.com/claims-by-maryland-jurisdictions/baltimore-personal-injury-lawyer/`, verified live 2026).** The un-fakeable version of local proof for a YMYL legal service. It names the Circuit Court for Baltimore City ("one of the largest in the state, with 33 judges") and comments on its specific procedures and facilities; names a specific dangerous intersection (Gwynns Falls Parkway and Reisterstown Road, "46 accidents in a year"); ties verdicts to named local hospitals; and lists specific jurisdiction verdicts ("2024: $8,310,172 Verdict," "2021: $34,770,292 Verdict"). Verdicts-by-jurisdiction and courthouse-specific procedure are the legal equivalent of "gumbo clay soil": they collapse the moment you change the city, and they resolve to public records. The URL is a clean jurisdiction subfolder. This is the model for any considered/YMYL combo page: substitute the physical local mechanism with the local regulatory-and-results mechanism.

**WINNER 3 (companion, from the harvest, re-verify at build) - Roto-Rooter Pflugerville** (`rotorooter.com/pflugervilletx/`). Names Falcon Pointe, Highland Park, Blackhawk; the expansive-clay / live-oak-and-pecan-root-intrusion mechanism; Lake Pflugerville and the SH-130 corridor; a named local licensed manager; 13 location-specific FAQs. Proof that the roughly 50/50 local-to-brand split is real and un-spinnable across a network (Houston, Baltimore, New York versions each carry different, town-true mechanisms).

The pattern across all three: a genuine majority of the body is city-specific and externally verifiable, the conversion path terminates on-page, and the named responsible human (licensed manager, or the firm's attorneys) is present. That is what a compliant, converting combo page looks like.

---

## 7. Worst teardowns (real, reported doorway patterns and why they get penalized)

I will not fabricate a named victim network. What follows are the real reported patterns and documented penalty case studies; where a case is from a secondary SEO source, it is flagged.

**Pattern A - the suburb-swap HVAC network.** A regional HVAC company built hundreds of pages, one per suburb it served, each with similar copy and a swapped location. After the March 2024 core update, over 80% of those doorway pages lost rankings and the site saw a reported 63% organic traffic drop in 30 days (reported case study, upnorthmedia.co / manningmarketing.com class of sources, secondary, verify). Why it fell: the city name was the only variable, so every page failed the strip-the-city test simultaneously, and SpamBrain reads a cohort of near-duplicates as scaled content.

**Pattern B - the 42,000-page manual action.** A site received a manual action for doorway pages roughly 4 months after building them; traffic dropped a reported 96% and recovery took 8 months and required deleting 42,000 pages (reported case study, secondary, verify). Recovery only began after consolidating the pages into fewer, genuinely location-specific pages with unique content and per-area reviews. The lesson the source draws is exact: "if your only unique element is a city name, you are creating doorway pages."

**Pattern C - the subdomain-per-city network.** `austin.yoursite.com`, `dallas.yoursite.com`, each a thin clone funneling to one central form. This matches Google's named doorway example ("multiple domain names or pages targeted at specific regions or cities that funnel users to one page") almost verbatim. It is a structural doorway signal independent of content quality. Use flat subfolders on one domain instead (Section 10.1).

**Pattern D - the AI-spun combo network.** Using generative AI to produce 160 service-in-city pages in one pass, each convincingly specific but none externally verifiable and none tied to a real booked job. This is the 2026 version and the one this playbook exists to prevent. It fails the external-verifiability test (5.3) even when it passes a naive strip-the-city read, and it is the exact "using generative AI tools to generate many pages without adding value" example in the live scaled-content-abuse policy.

The common failure in all four: pages were created for a keyword list, not for real service areas the business books jobs in. That inversion (Section 5.2) is the root cause every time.

---

## 8. Google-compliance notes

- **Doorway policy (live).** The test is intermediate-vs-destination and usefulness, not page count. Every combo page must let the user finish the job on-page (local phone, booking, proof, team). Source: developers.google.com/search/docs/essentials/spam-policies.
- **Scaled-content-abuse policy (live).** Many pages generated primarily to manipulate rankings, including AI-generated pages "without adding value" and template-with-variable-substitution at scale, are the named violations. The Minimum Unique Local Substance bar (5.4) is the compliance control. Source: same policy page; enforcement context March 2024 and March 2026 (secondary, verify).
- **AI surfaces are in scope (May 15, 2026 update).** Doorway and scaled-content policies now govern AI Overviews and AI Mode explicitly. There is no AI-surface loophole. Source: ppc.land, verify against Search Central.
- **Local accuracy / NAP integrity.** NAP identical across page, schema, and GBP; real address for storefronts, honest service-area statement for SABs; never a fabricated or rented address (GBP suspension + doorway signal). Do not self-mark your own reviews with Review/AggregateRating schema (renders nothing since 2019).
- **YMYL.** Legal, medical, dental, and financial combo pages are YMYL: trust is the dominant E-E-A-T aspect ("Of these aspects, trust is most important," Google's Creating Helpful Content). Name the credentialed responsible human (attorney, licensed contractor, DDS), cite verifiable credentials and real results, and never overstate outcomes. A verdict page must be accurate and current; a medical page must not promise results. The external-verifiability bar is stricter here, not looser.
- **Financing / consent / review-substantiation.** Reg Z trigger-term disclosure on published financing; TCPA express-consent language next to every form submit; FTC substantiation for any "5.0 from 100+" claim. Verify with counsel per vertical and state.

This page ships **no detector-evasion and no humanizer chain, ever** (Doctrine Law 8, and CLAUDE.md hard line). It reads human because it is made of real, verifiable, local facts, not because it was laundered through a paraphraser. If a client asks for a "passes AI detection" gate, refuse it and cite Law 8.

---

## 9. Voice and humanization notes

- **Humanize with specificity, not with a paraphraser.** The single fastest way to make a combo page read human is to fill 4.4 with facts only someone who works that town has. "Gumbo clay soil cracks the underground pipe" reads human because it is true and specific; "we provide top-quality plumbing solutions" reads like a machine because it is empty.
- **Kill the AI tells.** Apply `knowledge/voice/`: no "in today's fast-paced world," no "look no further," no "nestled in the heart of [City]," no triads-of-three-adjectives filler, no "whether you need X, Y, or Z" list padding. Vary sentence rhythm; let some sentences run short.
- **Write at 5th-to-7th-grade level.** A local buyer in a burst-pipe panic is not reading an essay. Short paragraphs, plain words, one idea per sentence where it earns it.
- **Match the emotional register to intent.** URGENT copy is calm and fast (the buyer supplies the panic; you supply the fix). CONSIDERED copy sells the after-state and reduces risk. Wrong engine for the intent is a real failure: agitation on an elective cosmetic page repels aspiration buyers.
- **Per-client brand voice always on.** Layer the client's `brand.yaml` voice (tone, reading level, banned phrases) over the universal humanization. Never ship in a generic voice.
- **Do not disclose "AI-assisted content."** Google does not require it and grants no ranking credit; on a local trust page the label cuts against the human-accountability signal you are building. The real requirement is authentic, named, credentialed human authorship, surfaced by the SME interview.

---

## 10. Meta formulas and JSON-LD

### 10.1 URL pattern (pick one, hold site-wide)

- Service-first: `/services/[service-slug]/[city-slug]/` (e.g. `/services/drain-cleaning/cedar-park/`).
- City-first: `/locations/[city-slug]/[service-slug]/` (e.g. `/locations/cedar-park/drain-cleaning/`) - Roto-Rooter's live pattern (`/houston/emergency-plumber/`).
- Flat subfolders on the main domain, two clicks or fewer from home. **Never subdomain-per-city** (matches the doorway-network shape almost verbatim).

### 10.2 Meta title formulas

- URGENT: `Emergency [Service] in [City], [ST] | [Same-Day / 24-7] | [Brand]` (keep under ~60 chars / pixel-width; expect Google rewrites).
- CONSIDERED: `[Service] in [City], [ST] | [Differentiator] | [Brand]` (e.g. "Invisalign in Scottsdale, AZ | Free 3D Scan | [Brand]").
- Cost/hybrid variant target inside body and FAQ, not the title.

### 10.3 Meta description formula

`[Outcome-first benefit] for [City] and [named nearby areas]. [Trust signal: rating/license/years]. [Response/offer]. [CTA + local phone].` Under ~155 chars. Example: "Same-day drain cleaning across Cedar Park, Round Rock and Leander. Licensed, 4.9 stars, $55 off. Call [number] or book online."

### 10.4 The JSON-LD graph (LocalBusiness + Service + areaServed + BreadcrumbList + FAQPage)

One coherent `@graph`. Use the most specific LocalBusiness subtype (`Plumber`, `HVACBusiness`, `Dentist`, `Attorney`). NAP must mirror the visible page and GBP exactly. Do NOT add self-serving `Review`/`aggregateRating` to your own nodes. Validate with Google's Rich Results Test before shipping.

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Plumber",
      "@id": "https://example.com/#business",
      "name": "Example Plumbing Co.",
      "url": "https://example.com/locations/cedar-park/drain-cleaning/",
      "telephone": "+1-512-555-0100",
      "priceRange": "$$",
      "foundingDate": "2009",
      "image": "https://example.com/img/cedar-park-crew.jpg",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "123 Real Staffed St",
        "addressLocality": "Cedar Park",
        "addressRegion": "TX",
        "postalCode": "78613",
        "addressCountry": "US"
      },
      "geo": {
        "@type": "GeoCoordinates",
        "latitude": 30.5052,
        "longitude": -97.8203
      },
      "hasMap": "https://www.google.com/maps/place/?q=place_id:REAL_PLACE_ID",
      "areaServed": [
        { "@type": "City", "name": "Cedar Park" },
        { "@type": "City", "name": "Round Rock" },
        { "@type": "City", "name": "Leander" }
      ],
      "openingHoursSpecification": [
        {
          "@type": "OpeningHoursSpecification",
          "dayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"],
          "opens": "00:00",
          "closes": "23:59"
        }
      ],
      "sameAs": [
        "https://www.google.com/maps/place/?q=place_id:REAL_PLACE_ID",
        "https://www.facebook.com/exampleplumbing",
        "https://www.yelp.com/biz/example-plumbing-cedar-park"
      ],
      "employee": {
        "@type": "Person",
        "name": "Real Named Manager",
        "jobTitle": "Licensed Master Plumber",
        "identifier": "TX Master Plumber M-00000"
      }
    },
    {
      "@type": "Service",
      "@id": "https://example.com/locations/cedar-park/drain-cleaning/#service",
      "serviceType": "Drain Cleaning",
      "provider": { "@id": "https://example.com/#business" },
      "areaServed": { "@type": "City", "name": "Cedar Park" },
      "offers": {
        "@type": "Offer",
        "description": "$55 off any drain cleaning service",
        "priceCurrency": "USD"
      }
    },
    {
      "@type": "BreadcrumbList",
      "itemListElement": [
        { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com/" },
        { "@type": "ListItem", "position": 2, "name": "Drain Cleaning", "item": "https://example.com/services/drain-cleaning/" },
        { "@type": "ListItem", "position": 3, "name": "Cedar Park", "item": "https://example.com/locations/cedar-park/drain-cleaning/" }
      ]
    },
    {
      "@type": "FAQPage",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "How fast can you reach Cedar Park for an emergency drain backup?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "We dispatch same-day across Cedar Park, Round Rock and Leander, typically on-site within [X hours] for emergency drain backups."
          }
        },
        {
          "@type": "Question",
          "name": "Do I need a permit for a sewer line replacement in Cedar Park?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "Sewer line work in Cedar Park requires a plumbing permit from the city; we pull the permit and schedule the required inspection as part of the job."
          }
        }
      ]
    }
  ]
}
```

Every value must mirror visible page text and GBP. Placeholder values (REAL_PLACE_ID, coordinates, license, hours) get replaced with the client's real facts from `brand.yaml`; never ship placeholders. Validate with `scripts/schema_validator.py` and Google's Rich Results Test.

---

## 11. Finished-page checklist (including the doorway pass test)

Binary. Every line must pass before the page ships.

**Doorway / uniqueness gate (any NO here = do not publish):**
- [ ] Strip the city name and the 3 named local anchors: does the remaining body still read complete and correct for any other town? (If YES = doorway = FAIL.)
- [ ] Is the city name (plus a keyword) the ONLY thing that varies vs another combo page? (If YES = FAIL.)
- [ ] At least 1 local claim resolves to an externally verifiable record (permit, real Google-profile review, public court, water authority, license number)? (If NO = FAIL.)
- [ ] Is a genuine majority of the body city-specific and non-transferable? (If NO = FAIL.)
- [ ] Was this page created for a real service area the business books jobs in, not for a keyword-list slot? (If NO = FAIL.)

**Minimum Unique Local Substance bar (all five required):**
- [ ] 3+ named hyper-local anchors (neighborhoods/landmarks/highways/intersections), city name not counted.
- [ ] 1+ named local condition causally tied to the service.
- [ ] 1+ externally verifiable local proof.
- [ ] 2+ city-specific FAQ answers.
- [ ] On-page conversion path terminates locally; real address (storefront) or honest SAB statement; no fabricated/rented address.

**Conversion + structure:**
- [ ] H1 contains exact service AND exact city; phone + primary CTA above the fold on 375px.
- [ ] 3+ trust signals above the fold (rating+count+source, license number, insured).
- [ ] Reviews: 3+ city-tagged, dated, in HTML, high on page; NO self-serving Review/AggregateRating schema.
- [ ] Real local photos, no stock in the proof zone.
- [ ] Response-time or guarantee commitment present and operationally true.
- [ ] Quantified offer present or explicit N-A with reason.
- [ ] Sticky mobile CTA bar; tap targets meet WCAG minimum.
- [ ] Intent (URGENT vs CONSIDERED) correctly reorders the page and the primary CTA.

**Local-SEO + technical:**
- [ ] URL is a flat subfolder on the main domain; one pattern held site-wide; not a subdomain-per-city.
- [ ] Page is internally linked (up to service hub, lateral to city siblings); not orphaned behind JS.
- [ ] NAP identical across page text, JSON-LD, and GBP.
- [ ] JSON-LD: LocalBusiness subtype + Service (with areaServed) + BreadcrumbList + FAQPage; validates in Rich Results Test; mirrors visible content.
- [ ] Meta title and description follow the formulas and include service + city.
- [ ] Core Web Vitals pass at p75 mobile field data (LCP <= 2.5s, INP <= 200ms, CLS < 0.1); hero has fetchpriority, below-fold lazy-loaded.
- [ ] AI-answer crawlers allowed (verify current OAI-SearchBot, ChatGPT-User, PerplexityBot, Perplexity-User, ClaudeBot strings against each provider's list); each section leads with a self-contained extractable answer.

**Compliance + voice:**
- [ ] No fabricated local facts; every local specific traces to client profile, SME interview, or a cited source.
- [ ] YMYL pages name the credentialed responsible human; no overstated outcomes.
- [ ] Reg Z (financing), TCPA (form consent), FTC (review substantiation) satisfied where applicable.
- [ ] No detector-evasion, no humanizer chain, no "passes AI detection" gate (Doctrine Law 8).
- [ ] Universal humanization + client brand voice both applied; no AI tells.
- [ ] Post-publish: GSC index-coverage watch scheduled across the combo-page cohort (doorway smoke detector).

A page missing any box is an unfinished draft, not a page. The output contract (CLAUDE.md) still applies: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`, all five present, every gate marked pass with evidence.

---

## Sources (opened this session)

- Google Search spam policies (doorway abuse + scaled content abuse, exact policy text): developers.google.com/search/docs/essentials/spam-policies
- Google spam policies now cover AI Overviews and AI Mode (May 15, 2026): ppc.land/google-spam-policies-now-officially-cover-ai-overviews-and-ai-mode-in-search/
- RicketyRoo, location-page spam / doorway line: ricketyroo.com/blog/location-page-spam/
- Whitespark, prevalence of AI Overviews in local search (540 queries, 3 cities, 6 industries, May 12, 2025): whitespark.ca/blog/case-study-the-prevalence-of-ai-overviews-in-local-search/
- Roto-Rooter Houston (live winner teardown): rotorooter.com/houston/ and /houston/emergency-plumber/, /houston/drain-cleaning/
- Miller & Zois Baltimore personal injury (live winner teardown): millerandzois.com/claims-by-maryland-jurisdictions/baltimore-personal-injury-lawyer/
- Roto-Rooter Pflugerville (companion, re-verify at build): rotorooter.com/pflugervilletx/
- Scaled-content-abuse March 2024 / March 2026 enforcement context (secondary, verify): digitalapplied.com/blog/scaled-content-abuse-google-march-update-ai-pages-decimated
- Doorway penalty case studies (secondary, verify): upnorthmedia.co/blog/doorway-pages-seo, manningmarketing.com/articles/what-are-doorwaygateway-pages/
- Whitespark Local Search Ranking Factors (dedicated-page-per-service, GBP-linked page factors; verify current edition): whitespark.ca/local-search-ranking-factors

Harvested from (internal): D:\MARKETING-OS\research\playbooks\local-service-location-page-playbook.md, service-offer-landing-page-playbook.md, D:\MARKETING-OS\research\golden-specs\seo-local-gbp-audit-2026.md, PLAYBOOK-REGISTRY.md.

All figures directional unless flagged. No live A/B test behind this document. Re-verify perishable facts (AI-crawler user-agent strings, AI-Overview prevalence, enforcement dates, Whitespark edition) at build time.
