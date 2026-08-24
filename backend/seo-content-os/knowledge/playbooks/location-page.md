# The City / Location Page: The SEO-CONTENT-OS Build Playbook

Leaf-artifact writing spec for `/write-location-page`. A writer handed this file plus one real client brand profile (real services, real city, real service-area facts, real reviews, real crew photos, real license) can produce a single city page that ranks in local organic, anchors the Google Business Profile (GBP), earns AI-answer citations, and converts, with zero further guidance and zero doorway-page risk.

This is the CITY page: the local hub for one real market. It ranks and converts for "[primary service] [city]", "[business type] [city]", and "[service] near me" for that city. It is the page the GBP for that location links to.

Sibling playbooks, do not confuse:
- `service-page.md` - one service, brand-wide, not city-bound.
- `service-city-page.md` - one service x one city, the granular money page (the spoke beneath this hub in a service-by-city matrix).
- `service-area-page.md` - coverage of a drive-to region with no branch, honest service-area-business (SAB) framing.

Every quantitative figure here is directional. There is no live A/B test behind this document. Each number carries a source and a verify flag. Re-open the primary before printing any figure to a client. No number appears here as a promise.

Style bar for this playbook: it writes for a writer, not a reader. If a rule says "add local content" it has failed. It must say "add 2 named neighborhoods this business actually books jobs in, 1 named local condition (soil, water, code, climate, housing stock), and 1 dated local job reference." Hold every line to that bar.

Governing law: `knowledge/doctrine/seo-system-doctrine.md`, Law 8. Google's policy is method-agnostic; it punishes scaled low-value publishing, not AI provenance. There is no detector-evasion, no humanizer chain, no "passes AI detection" gate anywhere in this playbook. A city page reads human because it is made of real local facts a competitor does not have, not because it was laundered through a paraphraser. If a client demands a bypass-detection feature, refuse it and cite Law 8.

---

## 1. Purpose: the one job, and when to build this page at all

### 1.1 The one job

A city page is one asset doing five jobs at once (the "One Page, Five Jobs" frame, Chris Shirlow via Backlinko, backlinko.com/location-pages, verified live 2026-07):

1. Rank in local organic for "[service] [city]" and "[business type] [city]".
2. Be the page the GBP for that location links to (the GBP-linked city landing page is a named ranking mover, Whitespark).
3. Earn AI-answer citations (Google AI Overviews and AI Mode, ChatGPT search, Perplexity).
4. Function as a paid-ad landing page when the client runs local PPC.
5. Convert the visitor into a booked lead (call, form, or self-scheduled slot).

The one job, compressed: be the single most useful, most obviously-local, most trustworthy destination for a person in this city who needs this service now. A page that ranks but reads like a spec sheet fails. A page that converts but is thin fails and risks a scaled-content penalty. World-class means all five jobs met, not the easy three.

### 1.2 The un-negotiable acceptance test

Two gates every finished city page must survive. They are referenced throughout this playbook.

**The strip-the-city test (the un-templated gate).** Strip the city name from every sentence. If a paragraph still reads fine for any town in the country, it is boilerplate and the page fails. The winning page fails-to-generalize on purpose: swap the city and its sentences collapse because they name real local soil, real neighborhoods, a real local licensed person, a real local job.

**The market-insider test (the differentiation gate).** At least one paragraph must contain a fact only someone actually working that specific market would know. Not "we serve [City]." A named local condition, a named neighborhood job, a named local licensed manager, a linkable permit record. Section 7 gives the repeatable sourcing method.

### 1.3 When to build a city page vs a service-area page vs a service-city page

This is a routing decision. Get it wrong and you either build a doorway page or you strand real local demand.

Build a **city page** (this playbook) when:
- The business has a genuine, provable operational anchor in that city: a staffed branch or storefront, OR a deep, dated, repeatable book of local jobs (not one job, a real footprint), OR a named local manager/crew who work that market.
- You can truthfully write the local-proof block (Section 4.4): named neighborhoods, a named local condition, a dated local job. If you cannot, do not build the page. That is the doorway line.
- The city is a real market for the client, not just a keyword on a list.

Build a **service-area page** (`service-area-page.md`) instead when:
- The client drives to a region but has no branch or staffed office there, and the honest framing is "we cover this region," not "we are based here."
- Local proof is thinner (some jobs, no local anchor). The service-area page is engineered to carry honest coverage without pretending to a presence that does not exist.

Build a **service-city page** (`service-city-page.md`) beneath this hub when:
- The client runs a service-by-city matrix and one specific service in one city has real standalone demand and real local proof (for example "trenchless sewer repair in Pflugerville" under the Pflugerville city hub). The city page is the hub; the service-city pages are spokes. Only build the spoke when you can write its local-proof block truthfully.

The hard rule that governs all three: **tie page creation to real service areas the business actually books jobs in, not to a keyword list.** One strong, locally substantiated page per real market beats fifty thin ones per zip you can name. If you cannot source the local-proof block truthfully for a town, there is no page for that town. (Doctrine Law 8; Google scaled-content-abuse policy, Section 6.)

### 1.4 The three-surface reality (do not treat the page as the whole game)

For local queries the page is one of three surfaces, not the sole one:
1. The **GBP profile** - the dominant controllable local-pack lever and the primary AI-cited local entity.
2. The **AI-answer surface** - AI Overviews / AI Mode, ChatGPT, Perplexity.
3. The **city page** itself.

The writer controls the page and the on-page entity signals (NAP, schema, extractable answers) that feed all three. Write the page so it strengthens the GBP entity (exact NAP match, sameAs bridge), not as if it competes with it.

---

## 2. Target intent and the real local query patterns this page must satisfy

A city page is a multi-intent page. It must satisfy several distinct real query shapes at once. Map the client's actual money queries to these before outlining.

**Query families the city page must serve:**

1. **Explicit service-plus-city** - "plumber pflugerville tx", "emergency electrician mesa az", "roof repair naperville". Highest commercial intent. The H1 and title must message-match this verbatim.
2. **"Near me" (implicit geo)** - "plumber near me", "emergency ac repair near me". Google resolves the geo from device location; the page ranks via the GBP entity plus city relevance. Sterling Sky's near-me research is the reference for what moves these (category, review velocity, review response, GBP-linked city page; re-open sterlingsky.ca before quoting specifics).
3. **Business-type-plus-city (non-branded)** - "24 hour plumber pflugerville", "licensed hvac pflugerville". Trust-and-availability qualifiers attached to city.
4. **Problem-plus-city (symptom search)** - "no hot water pflugerville", "sewer backup pflugerville", "ac not cooling mesa". Urgent, high-conversion, often under-served by competitors. The local-proof and FAQ blocks should answer the common local failure modes by name.
5. **Logistics / qualifier queries** - "plumber pflugerville open now", "emergency plumber pflugerville 24/7", "plumber pflugerville cost". Answered by hours, response-time commitment, and honest pricing signals.

**Intent axis that reorders the page (decide before writing):**

- **URGENT** verticals (plumbing leak, HVAC-down, lockout, towing, emergency dental, injury law): the phone is the primary CTA. The call button leads; the form can be deferred below the fold. Trust bar emphasizes speed and real availability. Phone carries a large share of conversions for these buyers (Ruler Analytics 2026, 5M+ conversions, reported legal ~56% and professional services ~53% of conversions by phone; share-of-channel, not proof call-first lifts total conversions; verify).
- **CONSIDERED** verticals (kitchen remodel, implants, med spa, solar, roofing replacement): a form or self-scheduling calendar leads. Financing, portfolio and before/after project photos, and a design-consult booking move up the page. Reviews with project photos beat a bare star count.

The single conversion purpose (become a lead) is not a single CTA. Call and form serve two intent states (urgent-now vs considered-later). Offering both is not a leak. A full global nav on a paid version of the page is.

---

## 3. The 2026 SERP and AI-answer reality for local queries (live research)

This is the ground truth the page is written into. All figures below were surfaced 2026-07; re-open each primary before quoting to a client.

### 3.1 AI Overviews are now dominant on informational and hybrid local queries, thin on pure-local

Whitespark manually analyzed 540 queries across Houston, Phoenix and Denver, six industries (plumbers, lawyers, dentists, optometrists, clinics, real estate), classifying each query as local, informational, or hybrid (whitespark.ca/blog/case-study-the-prevalence-of-ai-overviews-in-local-search/, read 2026-07):

| Intent | AI Overview shown | Local pack shown |
|---|---|---|
| Local (e.g. "plumber near me") | 15% | 93% |
| Informational (e.g. "how much does drain cleaning cost") | 92% | 6% |
| Hybrid (e.g. "best emergency plumber pflugerville") | 97% | 17% |

Average AI-Overview prevalence across all query types was 68% (range 57-80% by industry). The operational read: the local pack still dominates the pure "[service] [city]" and "near me" queries (93%), so GBP plus a GBP-linked city page still wins those. But the informational and hybrid queries around the service (cost, how-to, "best") are now answered by AI, and that is where the page earns citations rather than clicks.

### 3.2 AI answers cite third-party publishers more than business sites, and they cut clicks

In Whitespark's plumber dataset, AI Overviews cited 23 total sources: 60% third-party publishers (Yelp, Reddit, Thumbtack, Indeed) and 40% individual businesses. When an AI Overview appears, Whitespark cites an average 34.5% CTR reduction (Ahrefs research). Backlinko's own 30-query, three-platform citation experiment (backlinko.com/location-pages, read 2026-07) found the same skew by engine: Google AI Mode cited Yelp (32%) and Reddit (30%) most; ChatGPT favored editorial "best of" lists (22%); Perplexity cited direct business websites most (73%).

The three implications for how this page is written:
1. **Perplexity rewards the direct site** (73% business-site citations), so the extractable-passage work on this page pays off most there. Write each section to lead with a self-contained, liftable 1-2 sentence answer.
2. **Google AI Mode and ChatGPT reward being present in the third-party corpus** (Yelp, Reddit, "best of" roundups). That is a GBP/reputation and digital-PR job, not a page-copy job, but the writer should note it in the client's sources file as a gap the page alone cannot close.
3. **The GBP is the primary AI-cited local entity.** Keep NAP identical across page, schema, and GBP so the entity is unambiguous (doctrine Law 13).

### 3.3 Proximity gates inclusion, not rank, inside AI answers

Search-surfaced 2026 commentary (onpurposemedia.com, localfalcon.com, verify) reports that proximity has some influence on whether a business is included in an AI Overview but little influence on ranking position once included, which differs from the classic local pack where proximity dominates. Treat this as directional. The controllable levers it names for AI inclusion are entity authority, structured data, GBP completeness, and passage-level content clarity. Those are exactly what Sections 4 and 10 build.

### 3.4 What this means for the writer

- Write the pure "[service] [city]" and "near me" surface to win the **local pack**: exact-match H1/title, GBP-linked, NAP-consistent, review-rich, real local proof.
- Write the informational and hybrid surface (cost, common problems, "best", how-long) as **extractable passage blocks and FAQs** so the page is citable when the answer engine renders. Do not expect a blue-link click for these; expect a citation.
- Do not oversell the page as the whole solution. The GBP and third-party reputation carry the AI-citation game; the page carries the local-pack and the on-site conversion.

---

## 4. Section-by-section page architecture

The default block order below is a defensible convention, not a proven law (there is no cited A/B test behind the exact sequence). Ship it as the default; for CONSIDERED verticals move financing, gallery, and the booking calendar up (typically positions 4-7); for URGENT verticals suppress the above-fold form and let the call button carry the hero.

For each section: **Must-contain / Framework / Local-SEO / Schema / Precedent / Anti-pattern / PASS test.**

### 4.1 Hero

**Must-contain:** location-first H1 (exact service or business-type + exact city verbatim), a one-line problem-first subhead under 10 words, a tappable `tel:` phone number, the primary CTA (call for URGENT, form/scheduler for CONSIDERED), and an authentic local hero image (real crew/truck/local job, never stock).

**Framework:** Message match (conversion scent). The H1 repeats the words the visitor typed or clicked: `[Service or business type] + [City] + [Differentiator or Urgency]`. For URGENT use PAS (Problem, Agitate, Solution) compressed into the hero. For CONSIDERED use BAB (Before-After-Bridge) selling the after-state. Write at a 5th-to-7th-grade reading level (Unbounce Conversion Benchmark data reports lower reading levels convert better; directional, verify).

**Local-SEO:** the H1 must contain the service (or business type) and the exact city verbatim. Lead the section with one self-contained answer sentence an AI Overview can lift: "[Business] provides [service] in [City] and [named areas], available [hours/response]." This is the passage-block move: extractable answer at the top of the section.

**Schema:** the hero content is described by the page-level `LocalBusiness` (most specific subtype) node; `name`, `telephone`, `url`, `areaServed` set here must mirror the visible hero text exactly.

**Precedent:** Roto-Rooter Pflugerville (rotorooter.com/pflugervilletx/, verified live 2026-07) leads with a location-first H1 - "Trusted Pflugerville Plumber for Drains, Water Heaters & Water Cleanup" - phone 512-371-3615, dual CTA ("Schedule Online" / call), and 24/7 availability above the fold. (Note: this H1 differs from the version the MARKETING-OS exemplar quoted; live pages change, always re-open at build time.)

**Anti-pattern:** a brand-voice headline naming neither service nor city ("Comfort, Reimagined"). Dynamic-keyword-insertion producing an awkward or wrong city string. On the indexed page, a duplicate-templated H1 shared across 200 city pages with no unique body.

**PASS test:** H1 contains both the service (or business type) and the exact city verbatim; phone and primary CTA are visible without scrolling on a 375px viewport.

### 4.2 Trust bar (immediately below hero, above fold)

**Must-contain:** at least 3 distinct trust signals: Google star rating **with review count and source**, license number as a literal lookup-able string, insured/bonded status, years in business, and 1-2 relevant certification badges.

**Framework:** Trust-before-benefit. Local buyers are trust-gated before they are benefit-gated; the first-scroll decision hinges on whether the business looks legitimate and licensed (the top objection for a stranger inviting a tradesperson into the home). Compact logos, not a wall of twelve.

**Local-SEO:** the license number is a public regulatory record, safe to print, and a hard E-E-A-T "who is responsible" signal (Google Creating Helpful Content). Print the license number and carrier/board name plus insured-and-bonded status. **Never print the insurance policy number or coverage limits** (impersonation and claims-fraud vector).

**Schema:** if a named licensed person is shown, mark them as a `Person` node cross-referenced from the `LocalBusiness`. Do NOT wrap your own reviews in `Review`/`AggregateRating` markup here (Section 4.6 explains why).

**Precedent:** Roto-Rooter Pflugerville (verified live) stacks "Rated 4.8 on Google", "fully licensed and insured", "since 1935", BBB A rating, IICRC, and names the responsible licensed plumber as a literal string, "Jose Luis Rodriguez M-38038, Regulated by the Texas Board of Plumbing Examiners", plus the local manager (Ryan Rupp). That license string is the model: verifiable, specific, un-fakeable.

**Anti-pattern:** "Fully licensed and insured" as a floating badge with no number. A "5.0" with no review count (reads manufactured). Expired or unverifiable badges. Twelve logos diluting the two that matter (Google rating and license).

**PASS test:** at least 3 distinct trust signals above the fold, including a literal license/registration string and a rating with its review count.

### 4.3 Services offered in this city

**Must-contain:** a scannable grid or bulleted list; the exact service the query/ad promised placed first and visually emphasized; each item benefit-led, not a feature paragraph.

**Framework:** Scannability decides consumption. Confirm "yes, we do your specific thing in your city" without forcing reading.

**Local-SEO:** each service item deep-links to its dedicated service page or, where the matrix exists, its service-city spoke (`service-city-page.md`). "Dedicated page for each service" was the single largest riser in the Whitespark Local Search Ranking Factors survey (+186%, 2023 edition; whitespark.ca/local-search-ranking-factors, verify), and "internal links to the GBP landing page from other pages" entered at #24. Interlink both ways: the brand service page links down to the cities served; this city page links out to the relevant service pages.

**Schema:** each offered service can be expressed as a `Service` node with `areaServed` set to this city and `provider` referencing the `LocalBusiness` `@id`. Keep the list of `Service` nodes to the services genuinely offered here.

**Precedent:** Roto-Rooter Pflugerville lists the specific drain, water-heater, and water-cleanup services for the location rather than a generic national menu.

**Anti-pattern:** a 20-item equal-weight mega-list (paralysis, diluted topical focus). Dense paragraphs no one scans. Every service-plus-city permutation stuffed into this one page (thin and spammy; that is what the service-city spokes are for).

**PASS test:** the promised service appears first and visually emphasized; each item internally links to a real service or service-city page.

### 4.4 Local proof block (the un-templated core, this is the page)

**Must-contain (hard minimum):** 2 named neighborhoods, landmarks, or streets this business actually works in; 1 named local condition (soil, water hardness, water table, climate/freeze-thaw, permit rule, or a common failure mode in the local housing stock); and 1 dated job reference tied to this city ("180+ water-heater installs across Pflugerville over 4 years", or a completed job on a named street).

**Framework:** E-E-A-T first-hand Experience at local altitude. This is the single hardest thing a spun template can fake, the block that wins or loses the strip-the-city test, and it must be a genuine majority of the page body.

**Local-SEO:** this block is the safe/risky/spammy separator (RicketyRoo, ricketyroo.com/blog/location-page-spam, verify): a visible local footprint is what divides a real city page from a doorway page. The 2026 moat is not specificity alone (an LLM can now write convincing fake specifics across 40 towns in one pass); the moat is **external verifiability** - a permit record a skeptic can look up, a dated geotagged job photo, a review that resolves to a real Google profile, a named local licensed person.

**Schema:** none specific; keep it human-readable. If a dated job or project has a page, it can be referenced, but do not invent structured claims here.

**Precedent:** Roto-Rooter Pflugerville (verified live) names Falcon Pointe, Highland Park, Blackhawk, Springbrook and Windermere neighborhoods, Lake Pflugerville and the SH-130 corridor, and names real local mechanisms verbatim: "expansive clay soils shift dramatically during Central Texas drought and rain cycles", "hard water minerals from Pflugerville's municipal supply", "mature live oak and pecan trees" with "aggressive root systems". Swap the city out of any of those sentences and they collapse. That is the target. Backlinko's guide cites Wade Paint Co's Sullivan's Island page addressing that barrier island's "historic preservation requirements" as the same move in a different vertical (referenced by Backlinko, verify live before citing to a client).

**Anti-pattern:** "We proudly serve [City] and surrounding areas" with zero named streets, landmarks, permits, or operational detail. A generic "Common Heating System Issues" section that applies identically to any city (the near-miss failure, Section 6).

**PASS test:** passes the strip-the-city test AND the market-insider test. Minimum 2 named local places + 1 named local condition + 1 dated local job, and at least one of them is externally verifiable.

### 4.5 Real photos

**Must-contain:** photos of this crew, branded trucks, and completed local work. Name technicians. Show the owner or manager. Stock photography is prohibited.

**Framework:** Google added the first "E" (Experience) to E-E-A-T in December 2022 to reward has-actually-done-this proof; stock imagery signals the opposite. Real local imagery is the fastest visual trust tell and the hardest thing a template competitor can fabricate.

**Local-SEO:** reference the owner or named manager as a `Person` entity in structured data so Experience is machine-readable.

**Schema:** `Person` for the owner/manager, referenced from the `LocalBusiness`. Image assets described in the page but delivered by the client's front end (WebP/AVIF, responsive, LCP hero prioritized) - this is a handoff note to the build side, not the writer's emit.

**Precedent:** the exemplar corpus cites A.J. Alberts Plumbing ("Locally Owned Plumbing Experts Since 1989", real team imagery) and Thelen Mechanical (owner/team intro video); re-open live before citing to a client.

**Anti-pattern:** the stock smiling call-center headset photo. Instant template flag.

**PASS test:** the brief explicitly requires real crew/truck/local-job photos and prohibits stock; the named owner/manager is a `Person` in schema.

### 4.6 Reviews / testimonials (city-tagged, placed high)

**Must-contain (hard minimum):** 3 real named reviews, city-tagged, with dates, placed high on the page (right after services or the local-proof block), not in the footer. Repeat one compact proof element near the final CTA.

**Framework:** proof consumed before the ask lowers perceived risk. Most visitors never reach the footer; the visitor who needed reassurance has already bounced if proof is buried. Show the owner replying to recent reviews (last 30-90 days) to prove the business is currently operating and currently good.

**Local-SEO / schema (critical, builders get this wrong constantly):** display reviews as on-page HTML. **Do NOT wrap your own `LocalBusiness`, `Service`, or `Product` nodes in `Review` or `AggregateRating` JSON-LD to mint star snippets.** Since 2019 Google will not render review rich results when the entity controls the reviews it is rating; the `LocalBusiness` structured-data doc restricts review/aggregateRating to sites capturing reviews about *other* businesses. Self-marking your own reviews renders no stars and is wasted markup (not a documented penalty trigger, but it earns nothing). The stars in the map pack come from GBP, not from your JSON-LD. **Display-source compliance:** do not scrape Google review text. The Places API is capped at 5 reviews per place and its terms restrict caching/republishing. Use Google's own review widget, first-party testimonials collected with permission, or your own reviews via the Business Profile Performance API (you own those, so they are not capped).

**Precedent:** Roto-Rooter Pflugerville shows named, city-tagged reviews on-page (4 displayed) and a live 4.8 Google rating rather than a hardcoded graphic.

**Anti-pattern:** unattributed testimonials ("Great service! - J.D."). Stock-photo faces. A hardcoded "5.0" graphic with no names, dates, or replies. Adding `Review` schema to your own reviews and breaking the rule above.

**PASS test:** 3+ real named reviews, city-tagged, dated, placed above the footer; zero self-serving `Review`/`AggregateRating` markup on the business's own nodes.

### 4.7 Process / how-it-works

**Must-contain:** a 3-4 step numbered sequence, icon plus one line each ("1) Call or book, 2) On-site diagnosis, 3) Upfront flat quote, 4) Same-day fix"). Optionally "meet your tech" (name plus photo of the assigned pro).

**Framework:** de-risk the action. Removes fear of the unknown: surprise pricing, no-shows, an unvetted stranger in the home.

**Local-SEO / schema:** none specific; keep it human-readable and scannable. Optionally `HowTo` is available but not required and earns no local benefit; skip unless it genuinely helps the reader.

**Precedent:** the ServiceTitan and Hook Agency corpora repeatedly show a simple 3-4 step "how it works" as a standard conversion block; verify live before citing.

**Anti-pattern:** a wall of prose describing the process. A 7-step sequence no one reads.

**PASS test:** 3-4 numbered steps, one line each, scannable.

### 4.8 Offer / coupon + financing

**Must-contain:** a quantified offer in the CTA zone ("$55 off drain cleaning", "0% APR for 12 months via Synchrony", "same-day", "30-minute response"), or an explicit "N/A because [reason]" for verticals that do not use offers.

**Framework:** specificity is credibility. A number is verifiable in the reader's head; an adjective is noise. The offer usually out-moves any headline tweak, so construct the offer before polishing copy. Only publish terms the client actually underwrites.

**Local-SEO / schema:** none. **Compliance gate:** published financing terms with a stated repayment period ("0% APR for 12 months") are triggering terms under Truth-in-Lending / Reg Z advertising rules and may require full financing-terms disclosure. Flag for the client's counsel before publishing financing specifics; do not invent terms.

**Precedent:** Roto-Rooter Pflugerville (verified live) shows a "$55 Off Any Plumbing or Drain Cleaning Service" coupon and Synchrony Bank financing.

**Anti-pattern:** "Competitive pricing, quality you can trust." Commits to nothing, converts nothing.

**PASS test:** a quantified offer is present, or an explicit N/A with a stated reason.

### 4.9 Response / guarantee commitment

**Must-contain:** an explicit response-time commitment or workmanship guarantee, stated precisely ("On-site in 60 minutes", "Lifetime workmanship guarantee", "No hidden cost guarantee", "No fee until we win").

**Framework:** risk reversal is the highest-leverage conversion mechanic on a local page. Match the guarantee to the vertical's specific scar tissue: legal "No fee until we win", HVAC "No hidden cost guarantee", plumbing "Free estimate, no service fee", roofing "Free inspection".

**Local-SEO / schema:** none. **Operational gate:** confirm the client's live answer-rate before writing "24/7" or "same-day". If after-hours calls hit voicemail, the promise converts the click and burns the lead. Do not write a response promise the operation cannot keep.

**Precedent:** the exemplar corpus cites Marr Law "No Fee Until We Win", Big Wave HVAC "No Hidden Cost Guarantee"; verify live. The near-miss page (Section 6) has no response-time or warranty specificity, which is precisely why a competitor with a response promise beats it.

**Anti-pattern:** "100% satisfaction guaranteed" with no duration or mechanism. Legally meaningless, trust-neutral.

**PASS test:** an explicit, specific response-time or workmanship guarantee is present and the operation can keep it.

### 4.10 FAQ (city-specific, AI-citable)

**Must-contain (hard minimum):** 5 FAQs written as natural question headers, at least 2 locally specific, answering real local logistics (response time, coverage area, permit requirements, local pricing range, common local failure mode).

**Framework:** objection kill. Each FAQ answers a real reason a local buyer hesitates. Write each answer as a self-contained, liftable 1-2 sentences so an AI Overview or Perplexity can cite it (Section 3: Perplexity cites direct sites 73% of the time).

**Local-SEO / schema:** ship `FAQPage` JSON-LD, but **expect no rich-result stars** - Google restricted FAQ rich results to authoritative government and health domains for most queries in August 2023. Build the FAQ for conversion and for passage-level AI citability, not for SERP decoration. The JSON-LD is cheap and aids parsing.

**Precedent:** Roto-Rooter Pflugerville (verified live) carries 13 location-specific FAQs covering slab leaks, tree-root intrusion, hard-water damage, local building codes, and seasonal prep - each answerable only for that market.

**Anti-pattern:** keyword/FAQ padding that says nothing to a human ("What is the best plumber in [City]? We are the best plumber in [City]."). RicketyRoo names this exact pattern as a spam tell.

**PASS test:** 5+ FAQs, at least 2 genuinely city-specific, each answer self-contained and liftable; `FAQPage` JSON-LD present and mirroring the visible text.

### 4.11 Closing CTA + NAP + map / service-area

**Must-contain:** a final CTA repeating call and form/scheduler; the canonical NAP block (name, address, phone) matching GBP exactly; hours; and an embedded map (footer zone) or a named service-area coverage list.

**Framework:** last-chance conversion for the scroller who read the whole page.

**Local-SEO / schema:** NAP must be identical across visible text, JSON-LD, and GBP (suite formatting, "St" vs "Street", the exact number). **Storefront vs SAB:** a storefront/branch city page carries a real staffed walk-in address; a service-area city page covers a drive-to region and must be transparent that there is no public office there (and belongs in `service-area-page.md` if there is no anchor at all). **Never invent or rent a street address (virtual mailbox, UPS box) to look more local** - that is both a GBP-suspension trigger and a doorway signal. If the client runs call-tracking DNI, keep the true GBP-matched number as the static canonical NAP in the HTML and JSON-LD and swap the tracking number client-side only for paid channels with crawler user-agents excluded (a build-side note, not the writer's emit).

**Precedent:** Roto-Rooter Pflugerville shows one coherent NAP set, 24/7 hours, and a service-area presentation; verify live.

**Anti-pattern:** a tracking number in the visible NAP and schema that never matches GBP. A JavaScript-only store-locator that renders no crawlable `<a href>`, orphaning the page.

**PASS test:** one canonical NAP, identical across visible text, JSON-LD, and GBP; storefront-vs-SAB framing is honest; no fabricated address.

### 4.12 Sticky mobile CTA bar and internal links (indexed page)

**Must-contain:** a sticky mobile bar for the whole scroll with a call button and a "Get a quote / Book" anchor (thumb-first, WCAG 2.2 tap targets, minimum 24x24 CSS px, 44x44 recommended). On the indexed page: internal links out to the parent service pages, sibling city pages, and a crawlable `/locations/` hub.

**Framework:** the visitor who decides on screen 4 should never have to scroll back to act. Internal links are how a new city page inherits authority and gets crawled and indexed fast.

**Local-SEO / schema:** hub-and-spoke - a crawlable `/locations/` directory links to every city page; each city page links back to the hub and to its service pages; service pages link down to the cities served. Never orphan a city page. Point local backlinks at the city page, not the homepage.

**Anti-pattern:** a sticky bar that covers content or has sub-minimum tap targets. A city page reachable only via a JS store-locator with no crawlable link.

**PASS test:** sticky mobile CTA present the whole scroll; the page is linked from a crawlable hub and links out to its service pages.

### Default skeleton (starting order; A/B per vertical)

1. Hero (message-matched H1 + subhead + local hero shot + primary CTA + click-to-call)
2. Trust bar (rating + count, license #, insured, certs, years)
3. Services in this city (promised service first, internally linked)
4. First proof block (3+ city-tagged attributed reviews, high on page)
5. Local proof block (named neighborhoods + local condition + dated job)
6. Real photos (crew, trucks, local jobs)
7. Process / how-it-works (3-4 steps)
8. Offer/coupon + financing (or N/A)
9. Response/guarantee commitment
10. Second CTA + short quote form or scheduler (with consent line)
11. FAQ (5+, at least 2 city-specific, FAQPage JSON-LD)
12. NAP block + hours + embedded map (footer zone)
13. Sticky mobile CTA bar (whole scroll)
14. Internal links to parent service, sibling cities, related services

For CONSIDERED verticals move financing, gallery/portfolio, and the booking calendar up (typically positions 4-7). For URGENT verticals suppress the above-fold form and let the call button carry the hero. Add a real-time booking / instant-quote scheduler as a first-class path alongside call and form for scheduled (non-emergency) verticals; "call or fill a form" is a 2019 frame.

---

## 5. Best-in-class teardowns (real, live, verified 2026-07)

### WINNER - Roto-Rooter, Pflugerville TX

`https://www.rotorooter.com/pflugervilletx/` (fetched and verified live 2026-07-20).

Why it wins, checked against the five jobs:
- **Location-first H1**: "Trusted Pflugerville Plumber for Drains, Water Heaters & Water Cleanup" - service and city verbatim.
- **Trust stack above the fold**: "Rated 4.8 on Google", "fully licensed and insured", "since 1935", BBB A, IICRC, plus a literal responsible-licensee string ("Jose Luis Rodriguez M-38038, Regulated by the Texas Board of Plumbing Examiners") and a named local manager (Ryan Rupp).
- **A genuine majority of local content**: named neighborhoods (Falcon Pointe, Highland Park, Blackhawk, Springbrook, Windermere), named local geography (Lake Pflugerville, the SH-130 corridor), and named local mechanisms ("expansive clay soils shift dramatically during Central Texas drought and rain cycles", "hard water minerals from Pflugerville's municipal supply", "mature live oak and pecan trees" with "aggressive root systems"). Strip the city and these sentences collapse.
- **Converts**: phone 512-371-3615 tappable, dual CTA (Schedule Online / Call), $55-off coupon, Synchrony financing, 24/7, named city-tagged reviews.
- **AI-citable**: 13 location-specific FAQs answering local logistics as liftable passages.

**Authority caveat (state this to every client).** Roto-Rooter also ranks on national brand link authority and entity strength. A single-location operator who copies this structure inherits none of that and must earn the structure's benefit through links, reviews, and GBP. The structure is necessary, not sufficient.

### NEAR-MISS turned lesson - Bill Joplin's, heating repair, Plano TX

`https://www.joplins.net/service-areas/plano-tx/heating-repair-in-plano-tx/` (fetched and verified live 2026-07-20).

A legitimate 1978 business, but the exact failure this playbook prevents. The H1 "Expert Heating Repair Services in Plano, TX" is correct, but the opening paragraph immediately lists "McKinney, Allen, Melissa, Prosper, Fairview, Lucas, Plano, and Princeton, TX", diluting Plano in the first breath. The body ("Common Heating System Issues", "Why Choose Us") is generic and applies identically to any city; the only physical local anchor is the office address, which is in McKinney, not Plano. No neighborhood, no named local condition, no response-time commitment, no warranty specificity. It is a compliant, honest page that will lose to a competitor with named neighborhoods and a response-time promise. It is the strip-the-city fail exemplar: swap "Plano" for "McKinney" and the page is unchanged.

### Calibration corpus (referenced by primary sources; verify live before citing to a client)

Backlinko's location-page guide (backlinko.com/location-pages, read 2026-07) cites Wade Paint Co's Sullivan's Island page (barrier-island "historic preservation requirements" as the un-templated local hook), plus Merit Dental (Sandusky), Sila (HVAC, Philadelphia service area), Infinity Roofer (Denver), and Assembly Squad Remodeling (Chicago). The MARKETING-OS exemplar additionally references A.J. Alberts Plumbing, Big Wave HVAC "No Hidden Cost Guarantee", and Best Choice Roofing "$119/Month, 0% Financing For 12 Months". These are named for direction; open each live before quoting it in a client deliverable, because live pages change (as Roto-Rooter's own H1 did between the exemplar and this playbook).

---

## 6. Worst / penalty-risk teardowns (the #1 risk for this page type)

The location page is the single most penalty-prone page type in local SEO because the templated near-duplicate across cities is the textbook doorway pattern. Treat this section as the most important in the playbook.

### 6.1 The doorway pattern, in Google's own words

Google's spam-policy doc (developers.google.com/search/docs/essentials/spam-policies, read 2026-07) defines **doorway abuse** verbatim as sites or pages "created to rank for specific, similar search queries. They lead users to intermediate pages that are not as useful as the final destination," and lists as an example "Having multiple domain names or pages targeted at specific regions or cities that funnel users to one page" and "Creating substantially similar pages that are closer to search results than a clearly defined, browseable hierarchy."

The same doc defines **scaled content abuse** as "many pages are generated for the primary purpose of manipulating search rankings and not helping users," judged by the **primary-purpose test**: content violates the policy when generated mainly to game rankings rather than serve users, including AI-tool output and stitched content "without added value."

The trigger is behavioral, not volume. Can the user finish the job on this page (local phone, local booking, local proof, local team), or are they funneled to a generic central form? A site with 50 thin city pages can be penalized while a site with 10,000 genuinely useful pages is untouched.

### 6.2 The real-world damage

Search-surfaced 2026 case reporting (digitalapplied.com, verify): after the March 2024 core update, over 80% of one HVAC company's doorway pages lost rankings, a 63% organic-traffic drop in 30 days; template-generated location pages that differed only in city name saw 30-60% traffic loss. The March-2024 core-plus-spam update broadened the old spammy-auto-generated-content policy into scaled-content-abuse with real enforcement teeth. As of 2026-07 Google has announced no new spam policy on this; the 2024 guidance governs. Re-open the primary before quoting the case numbers, which are directional.

### 6.3 The specific patterns that get penalized, and how this playbook avoids each

| Penalty-risk pattern | Why Google punishes it | How this playbook prevents it |
|---|---|---|
| City-swap boilerplate (city name is the only variable across pages) | Scaled content abuse: substantially similar pages, primary purpose to rank | Section 4.4 local-proof block must be a majority of the body and must pass the strip-the-city test; Section 7 anti-doorway rules |
| "We serve [City] and surrounding areas" with no named local anything | Doorway signal: no destination value, funnels to a central form | Hard minimum of 2 named places + 1 named condition + 1 dated job, or no page |
| Pages built from a spreadsheet/keyword list, one per zip | Primary-purpose test failed: pages exist to rank, not to serve | Section 1.3: tie page creation to real booked markets, not keywords |
| Subdomain-per-city or domain-per-city network | Matches Google's named doorway example almost verbatim ("multiple domain names ... targeted at specific regions or cities") | Flat subfolder structure only (`/locations/city/`), never subdomain-per-city |
| Mass pages the operator cannot truthfully write a local-proof block for | Thin/scaled content with no added value | If you cannot source Section 4.4 truthfully, there is no page |
| FAQ/body keyword padding | Scaled low-value content; named as a spam tell | Section 4.10: every FAQ answers a real local objection, self-contained |
| Orphaned pages reachable only via JS locator | "Closer to search results than a browseable hierarchy" | Section 4.12 hub-and-spoke, crawlable links required |

### 6.4 The doorway smoke detector (monitor after publish)

Watch Google Search Console index coverage across the city-page cohort. "Crawled - currently not indexed" and "Discovered - currently not indexed" spreading across a set of city pages is the concrete, monitorable signal that Google is treating them as scaled content. This is a better early warning than any bounce/dwell heuristic, which has no safe threshold.

---

## 7. The anti-doorway rule: making each city page carry genuinely unique local value

This is the heart of the page type. Three sharp rules, then the sourcing method.

### 7.1 The three anti-doorway rules (the sharpest lines in this playbook)

1. **The strip-the-city rule.** Delete the city name from every sentence. Every paragraph that still reads fine for any town in the country is boilerplate and must be rewritten or cut. A genuine majority of the body must fail-to-generalize. This is the single binary test that separates a real city page from a doorway page.

2. **The verifiability rule (the 2026 moat).** Specificity is no longer enough, because an LLM can fake convincing local specifics across 40 towns in one pass. Every headline local claim must resolve to a record a skeptic or an answer engine can independently confirm: a lookup-able license/permit number, a dated geotagged job photo, a named neighborhood job, a review that resolves to a real Google profile, a named local licensed person. If a claim cannot be externally verified, it is decoration, not proof.

3. **The truthful-source rule (the build-vs-skip gate).** If you cannot write the local-proof block (Section 4.4) truthfully from real client facts - real neighborhoods worked, a real local condition, a real dated job - do not build the page. Tie page existence to real booked markets, never to a keyword list. The absence of truthful local proof is not a copywriting problem to paper over; it is the signal that this should be a service-area page or no page at all.

### 7.2 The repeatable market-insider sourcing method (the un-templated engine)

Run this in the RESEARCH step of the pipeline, via the SME interview plus live research, before drafting a word:

1. **Ask the crew who work that town.** What breaks most here, what is the housing stock, what is the recurring local failure mode. Yields the named local condition.
2. **Pull the local physical reality.** Soil type, water hardness, water table, climate/freeze-thaw, tree species causing root intrusion, coastal salt - facts a competitor cannot fake convincingly and a skeptic can verify. Live research grounds these (municipal water reports, USDA soil surveys, local extension offices).
3. **Pull the local regulatory reality.** Permit rules, licensing bodies, a linkable permit record. Municipal permit data is inconsistent and often has no API; do this per-market by hand as a best-effort source.
4. **Cite a named local job.** A completed job on a named street, "N installs in [City] over M years", a review that resolves to a real Google profile. Pull from the client's own completed-job records and reviews (Business Profile API for their own reviews), crew field notes, and dated geotagged photos.

Never fabricate any of these (CLAUDE.md hard rule: no fabricated local facts). A fabricated local specific is the fastest path to a trust penalty and a violation of the doctrine. When a fact is only available from the operator, surface it as an SME-interview question rather than inventing it.

### 7.3 The uniqueness floor (working heuristic, not a safe harbor)

A practitioner rule of thumb (SEJ) is roughly half brand/service boilerplate, half unique local substance. Treat that ~50% as a working heuristic, never a safe harbor - there is no Google-published percentage. The real test remains behavioral: could a competitor regenerate this page by find-and-replacing the city token? If yes, it fails, at any percentage.

---

## 8. Google-compliance notes specific to location pages

Every item here is on the `google-compliance-spine.md` spine as it applies to this page type. All are pass/fail.

1. **Doorway and scaled-content compliance** (Section 6): a genuine majority of unique, verifiable local substance; page tied to a real booked market; flat subfolder URL; no subdomain-per-city.
2. **NAP integrity**: identical name, address, phone across visible text, JSON-LD, and GBP. Mismatched schema is worse than none. Never invent or rent an address to look local (GBP-suspension + doorway signal).
3. **Storefront vs SAB honesty**: a storefront city page shows a real staffed walk-in address; a service-area presentation is transparent about no public office. Sterling Sky's near-me research reports hiding your address correlates negatively with SAB pack ranking (sterlingsky.ca, verify), so do not hide it and do not fake it; compensate for a proximity handicap with reviews, review velocity, and review response.
4. **Reviews**: display as HTML; no self-serving `Review`/`AggregateRating` markup on the business's own nodes (renders nothing since 2019). No scraping Google review text (Places API capped at 5, ToS-restricted); use owned reviews via the Business Profile API or first-party testimonials with permission.
5. **FAQ**: `FAQPage` JSON-LD is fine, but expect no rich-result stars (restricted to gov/health since Aug 2023). Build for conversion and AI citability.
6. **Financing / offers**: published financing terms with a repayment period are Reg Z triggering terms; flag for the client's counsel before publishing. Only publish offers the client underwrites.
7. **Lead-form consent**: capturing a US phone number to call or text back is governed by TCPA and the 2024-25 FCC consent rulemaking; express-consent disclosure next to the submit button, plus a honeypot. (Review copy relies on the FTC 2024 fake-review rule: any "5.0 from 100+" style proof must be substantiated.)
8. **Schema truthfulness**: schema mirrors visible text and GBP exactly; do not invent geo precision or claims; validate every template with Google's Rich Results Test before shipping. Schema is a pass/fail eligibility gate, not a scored ranking factor.
9. **AI-crawler access** (handoff note to the build side): allow the answer-engine crawlers so the page can be cited - OpenAI OAI-SearchBot and ChatGPT-User, PerplexityBot and Perplexity-User, Anthropic ClaudeBot and its search/user agent. GPTBot is OpenAI's training crawler and does not gate ChatGPT search citations. Verify the exact current user-agent strings against each provider's published list before shipping; they change. Add an `llms.txt`.
10. **No "AI-assisted content" disclosure.** Google does not require it and grants no ranking credit; on a local trust page an AI-assist label cuts against the human-accountability signal you are building. Disclose AI only where a specific non-SEO regulation demands it. The real requirement is authentic, named, credentialed human authorship - which the SME interview and named licensee provide.

---

## 9. Voice and humanization notes for the city page

Governed by `knowledge/voice/` (universal humanization) plus the client's `brand.yaml` voice. Law 8 method: humanize via specificity and real facts, never via paraphrase laundering.

- **Specificity is the humanizer.** The named clay soil, the named neighborhood, the named licensed plumber, the dated job - these are what make the page read human, because they are things only a real local operator would write. A page reads AI-generated when it is generic, not when a tool wrote it. Fix genericness with facts, not with a thesaurus pass.
- **Write to one worried person in that city**, at a 5th-to-7th-grade reading level. The reader has water on the floor or a dead furnace; match that register. Short sentences carry urgency. Vary rhythm so it does not thrum like template output.
- **The client's own voice, not sales-brochure gloss.** Pull the tone from the client's real writing (the brand voice profile). Contractions, plain words, the operator's actual phrasing. Roto-Rooter reads corporate; a family plumber should not. Never ship in a generic voice.
- **Kill the AI tells** (per the voice blocklist): "nestled in the heart of", "when it comes to", "look no further", "we understand that", "in today's fast-paced world", "rest assured". These are template flags and they read as filler to a human too.
- **Every claim carries its proof inline.** "Licensed" is weak; "Texas Board of Plumbing Examiners license M-38038" is human, specific, and verifiable at once. Experience is shown with the specifics only this business has, not asserted.
- **No fabrication, ever.** If a specific is not in the brand profile or the research, it becomes an SME-interview question, not an invention. A single fabricated local fact fails the page and violates the doctrine.

---

## 10. Meta title, meta description, and the JSON-LD block

### 10.1 Meta title formulas

Keep under ~60 characters where possible; front-load service and city. Pick by intent:

- **Primary**: `[Service or Business Type] in [City], [ST] | [Brand]`
  - "Emergency Plumber in Pflugerville, TX | Roto-Rooter"
- **Urgency/availability qualifier**: `[Service] [City] | 24/7 [Benefit] | [Brand]`
  - "Plumber Pflugerville | 24/7 Same-Day Service | [Brand]"
- **Trust qualifier**: `[Service] in [City] | Licensed & Insured | [Brand]`
- **Considered vertical**: `[Service] in [City] | [Offer or Guarantee] | [Brand]`
  - "Roof Replacement in [City] | Free Inspection | [Brand]"

Rules: exact city and service verbatim (message match). One brand token at the end. No keyword stuffing two cities into one title. Do not promise availability the operation cannot keep.

### 10.2 Meta description formulas

150-160 characters. Lead with the local hook, name the differentiator, end with a CTA. Not a ranking factor, but it drives CTR and is often the snippet an AI answer surfaces.

- **URGENT**: "[Service] in [City], [ST]. [Response promise], [licensed/insured], [rating] on Google. Call [phone] for same-day service."
  - "Emergency plumber in Pflugerville, TX. On-site fast, licensed and insured, 4.8 on Google. Call 512-371-3615 for same-day service."
- **CONSIDERED**: "[Service] for [City] homeowners. [Proof/years], [offer/guarantee]. [Free-consult CTA]."
  - "Roof replacement for [City] homeowners. GAF-certified, 0% financing for 12 months. Book a free inspection today."

Rules: exact city + service; one quantified proof (rating, years, or offer); one clear CTA. No fabricated numbers.

### 10.3 The JSON-LD block (LocalBusiness + Service + BreadcrumbList)

Emit to `schema.json`. Use the most specific `LocalBusiness` subtype (`Plumber`, `Electrician`, `HVACBusiness`, `Dentist`, `RoofingContractor`, or a type array for multi-service). NAP and hours must mirror the visible page and GBP exactly. `sameAs` bridges to the verified GBP and citations. Do NOT add `Review`/`AggregateRating` about the business's own reviews. Do not invent geo precision. Validate with Google's Rich Results Test before shipping.

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Plumber",
      "@id": "https://example.com/locations/pflugerville-tx/#business",
      "name": "Example Plumbing Co.",
      "url": "https://example.com/locations/pflugerville-tx/",
      "telephone": "+1-512-555-0100",
      "priceRange": "$$",
      "image": "https://example.com/img/pflugerville-crew.jpg",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "123 Real Staffed Street",
        "addressLocality": "Pflugerville",
        "addressRegion": "TX",
        "postalCode": "78660",
        "addressCountry": "US"
      },
      "geo": {
        "@type": "GeoCoordinates",
        "latitude": 30.4394,
        "longitude": -97.6200
      },
      "areaServed": [
        { "@type": "City", "name": "Pflugerville" },
        { "@type": "City", "name": "Round Rock" }
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
        "https://www.google.com/maps/place/?q=place_id:REAL_GBP_PLACE_ID",
        "https://www.facebook.com/exampleplumbing"
      ],
      "employee": { "@id": "https://example.com/locations/pflugerville-tx/#manager" }
    },
    {
      "@type": "Person",
      "@id": "https://example.com/locations/pflugerville-tx/#manager",
      "name": "First Last",
      "jobTitle": "Licensed Master Plumber",
      "identifier": "TX Board of Plumbing Examiners M-00000",
      "worksFor": { "@id": "https://example.com/locations/pflugerville-tx/#business" }
    },
    {
      "@type": "Service",
      "@id": "https://example.com/locations/pflugerville-tx/#service",
      "serviceType": "Emergency Plumbing",
      "provider": { "@id": "https://example.com/locations/pflugerville-tx/#business" },
      "areaServed": { "@type": "City", "name": "Pflugerville" }
    },
    {
      "@type": "BreadcrumbList",
      "itemListElement": [
        { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com/" },
        { "@type": "ListItem", "position": 2, "name": "Locations", "item": "https://example.com/locations/" },
        { "@type": "ListItem", "position": 3, "name": "Pflugerville, TX", "item": "https://example.com/locations/pflugerville-tx/" }
      ]
    },
    {
      "@type": "FAQPage",
      "@id": "https://example.com/locations/pflugerville-tx/#faq",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "Do you handle slab leaks in Pflugerville's clay-soil neighborhoods?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "Yes. Expansive clay soil around Falcon Pointe and Blackhawk shifts with Central Texas drought and rain cycles, which is a leading cause of slab leaks here, and we locate and repair them same-day."
          }
        }
      ]
    }
  ]
}
```

Notes: keep one `LocalBusiness` (subtype) node per page; cross-reference nodes with `@id`; the `FAQPage` `mainEntity` must mirror the visible FAQ text verbatim; add `Service` nodes only for services genuinely offered in this city; `sameAs` must point to the real, verified GBP. Run `scripts/schema_validator.py` and Google's Rich Results Test before the page is marked done.

---

## 11. Finished-page checklist (consolidated pass tests)

A city page is done only when every box is checked. Any single failure returns a specific error to fix and re-run (max 2 retries per the pipeline, then human queue). This is the compliance-report.md contract for `/write-location-page`.

**The two gates (both binary):**
- [ ] Passes the strip-the-city test: a genuine majority of the body fails-to-generalize; delete the city and those sentences collapse.
- [ ] Passes the market-insider test: at least one paragraph holds a fact only a real local operator would know, and it is externally verifiable.

**Section pass tests:**
- [ ] Hero H1 contains service (or business type) + exact city verbatim; phone + primary CTA visible on a 375px viewport.
- [ ] Trust bar: 3+ distinct signals above the fold, including a literal license/registration string and a rating with review count.
- [ ] Services block: promised service first; each item internally linked to a real service or service-city page.
- [ ] Local proof block: 2+ named local places + 1 named local condition + 1 dated local job; at least one externally verifiable.
- [ ] Real photos required and stock prohibited in the brief; named owner/manager is a `Person` in schema.
- [ ] Reviews: 3+ real, named, city-tagged, dated, above the footer; zero self-serving Review/AggregateRating markup.
- [ ] Process: 3-4 scannable numbered steps.
- [ ] Offer: quantified offer present, or explicit N/A with a reason.
- [ ] Guarantee: specific response-time or workmanship commitment the operation can keep.
- [ ] FAQ: 5+, at least 2 city-specific, each answer self-contained and liftable; FAQPage JSON-LD mirrors visible text.
- [ ] Closing: one canonical NAP identical across page, JSON-LD, and GBP; storefront-vs-SAB framing honest; no fabricated address.
- [ ] Sticky mobile CTA present whole scroll; page linked from a crawlable hub and links out.

**Compliance gates (any YES here = do not publish):**
- [ ] Is the city name the only variable versus another page? (city-swap boilerplate = FAIL)
- [ ] Does the FAQ or body pad keywords while saying nothing to a human? (FAIL)
- [ ] Is the page orphaned from crawlable navigation? (FAIL)
- [ ] No real address (storefront) or honest service-area statement (SAB), no local team, no local context? (FAIL)
- [ ] Does the page exist only to rank, with no genuine on-page conversion path? (FAIL)
- [ ] Fabricated or rented street address to look local? (FAIL)
- [ ] Schema NAP disagrees with visible NAP or GBP? (FAIL)
- [ ] Self-serving Review/AggregateRating markup present? (FAIL)
- [ ] Financing terms published without Reg Z disclosure sign-off? (FAIL)
- [ ] Lead form missing TCPA consent language? (FAIL)
- [ ] Any fabricated local fact, price, credential, or review? (FAIL - hard doctrine violation)

**Meta + schema:**
- [ ] Meta title: service + exact city verbatim, under ~60 chars, one brand token.
- [ ] Meta description: 150-160 chars, local hook + one quantified proof + one CTA, no fabricated number.
- [ ] JSON-LD: most-specific LocalBusiness subtype + Service + BreadcrumbList + FAQPage, NAP mirrors page and GBP, sameAs to real GBP, validated by schema_validator.py and Rich Results Test.

**Output contract (the five files must all exist):**
- [ ] page.md, schema.json, internal-links.md, compliance-report.md, sources.md - every external fact cited, every SME fact tagged.

**Post-publish monitor (hand to the client / GBP owner):**
- [ ] Watch GSC index coverage across the city-page cohort; "Crawled/Discovered - currently not indexed" spreading is the doorway smoke detector.

---

## Method note (honest)

This playbook is built on the MARKETING-OS location-page exemplar (the depth bar and structural base) plus live research verified 2026-07: the Roto-Rooter Pflugerville winner and Bill Joplin's Plano near-miss (both fetched live), the Whitespark AI-Overviews-in-local-search study, the Backlinko location-page guide and its AI-citation experiment, and Google's own spam-policy documentation quoted verbatim. Two Roto-Rooter companion URLs the exemplar cited (Baltimore, New York) returned 404 at build time and were dropped rather than cited stale - a live demonstration of the "re-open every page before quoting" rule. All figures are directional and carry a source and a verify flag; there is no live A/B test behind this document. Every local specific in a real deliverable must come from the client profile, the SME interview, or cited research, never invented (CLAUDE.md hard rule; doctrine Law 8).
