# Search Intent Taxonomy for Local Service Search

Every page this system writes serves exactly one primary search intent, expressed through one target query pattern, mapped to exactly one of the six page types. Mismatched intent is the single most common reason a well-written local page fails to rank or convert: a long educational essay where the searcher wanted a "call now" money page, or a thin templated city page where the searcher wanted the mechanics of the service.

Local service search has a different center of gravity than national or e-commerce search. The dominant surfaces are the **local pack (map pack)** and, increasingly, the **AI Overview**, not the ten blue links. A large share of commercial local queries carry proximity intent ("near me," "[service] [city]") and route to Google Business Profiles and money pages, not articles. This file keeps the classic informational / commercial / transactional spine but foregrounds the local intent layer that actually drives service-business demand, gives a free-signals decision procedure to classify any target query, and maps every intent to the exact page type that serves it.

---

## Layer 1: the local intent spine

Six intent classes cover essentially all local service demand. The first four are the local-specific layer; the last two are the classic spine, reframed for local.

| Code | Intent | What the searcher wants | Canonical query patterns |
|---|---|---|---|
| EMERGENCY | Urgent transactional | Someone to call and dispatch now | "emergency plumber Tempe," "24 hour AC repair near me," "burst pipe repair Chandler" |
| LOCAL-TRAN | Considered transactional | To hire a local provider for a planned job | "water heater installation Tempe," "electrician Mesa," "roof replacement Gilbert" |
| NEAR-ME | Proximity transactional | The closest credible provider, map-pack first | "plumber near me," "dentist near me open now," "HVAC near me" |
| LOCAL-COMM | Local commercial investigation | To compare providers, prices, or options before hiring | "best plumber in Tempe," "drain cleaning cost Tempe," "top rated roofers Gilbert," "AC repair vs replace" |
| LOCAL-INFO | Local / general informational | To understand the problem, often pre-hire | "why is my water heater leaking," "how long does a roof last in Arizona," "what does a slab leak sound like" |
| NAV | Navigational | A specific known business | "[brand name] Tempe," "[brand name] phone number," "[brand name] reviews" |

Two cross-cutting dimensions modify every class:

- **Local pack triggering.** Almost every EMERGENCY, LOCAL-TRAN, NEAR-ME, and most LOCAL-COMM queries trigger a map pack. That pack is won primarily by the Google Business Profile plus NAP consistency and reviews, but the landing page behind it (the money page) is what converts and what carries the on-page relevance that helps the pack ranking. LOCAL-INFO usually does not trigger a pack.
- **AI Overview triggering.** LOCAL-INFO and LOCAL-COMM ("[service] cost [city]," "best [service] in [city]," "how long does X last") increasingly trigger an AI Overview that draws from extractable passages. EMERGENCY, NEAR-ME, and NAV rarely do; those resolve straight to the pack or a brand result. This is why service, service-city, and location pages must be built as extractable passage blocks (see the passage-block foundation): the commercial-investigation and cost questions attached to them are exactly the ones AI Overviews answer.

---

## Layer 2: emergency vs considered (the urgency axis)

Urgency changes the page shape even inside the same service. It is the most consequential local distinction after the pack/no-pack split.

- **Emergency purchase.** No comparison shopping. The searcher wants a phone number, a "we answer 24/7," a response-time promise, and trust signals compressed above the fold. Long education below the fold is fine for the answer engines but the top of the page is a conversion sprint. Served by a service-city page (or a dedicated emergency variant of one) with the emergency angle led hard.
- **Considered purchase.** Planned installs, replacements, upgrades. The searcher researches, compares, checks price and credentials, may get multiple quotes. The page can and should educate: what the job involves, how the operator does it, what it costs, why this provider. Served by a service-city or service page with full expertise and proof depth.

A single service often spans both. "Emergency plumber Tempe" (EMERGENCY) and "water heater installation Tempe" (LOCAL-TRAN, considered) are different pages with different leads even though both are plumbing in Tempe. Do not collapse them into one page; do not write the considered page with an emergency lead or vice versa.

---

## Layer 3: reader stage

Where in the hire journey is the searcher? This sets voice posture, not usually page type.

| Code | Stage | State | Typical intent classes |
|---|---|---|---|
| PROBLEM | Just realized there is a problem | Diagnosing, worried | LOCAL-INFO, EMERGENCY |
| RESEARCH | Weighing options and providers | Comparing, pricing | LOCAL-COMM |
| READY | Ready to call/book | Wants to hire now | LOCAL-TRAN, NEAR-ME, EMERGENCY |
| KNOWS-YOU | Already knows the brand | Looking it up | NAV |

---

## Intent to page-type mapping

This is the routing table the writer uses. Each intent class has a primary page type that serves it and, often, a secondary.

| Intent class | Primary page type | Command | Secondary | Why |
|---|---|---|---|---|
| EMERGENCY | Service-in-city combo (emergency angle led) | `/write-service-city-page` | Location page | Money page for "[urgent service] [city]"; converts the pack click. |
| LOCAL-TRAN | Service-in-city combo | `/write-service-city-page` | Service page | The core money page: one service x one city, built to rank + convert. |
| NEAR-ME | Location / city page + strong GBP | `/write-location-page` | Service-city | "Near me" resolves by proximity to the GBP; the city page carries the on-page local relevance. |
| LOCAL-COMM | Service-in-city combo (with cost/comparison depth) | `/write-service-city-page` | Service page | "[service] cost [city]," "best [service] [city]" want price, options, proof, all on the money page; feeds the AI Overview. |
| LOCAL-INFO | Service page (with the informational section) or homepage FAQ | `/write-service-page` | Service-city | General "how/why/what" is served inside the service or service-city page's education block, not a separate blog (this system does not write blogs). |
| NAV | Homepage / about page | `/write-homepage`, `/write-about-page` | - | Brand queries resolve to the entity anchor and the trust surface. |
| Coverage ("do you serve [area]") | Service-area page | `/write-service-area-page` | Location pages | Proves genuine coverage across the service area without doorway spam. |

Notes that keep the system honest:

- **The service-in-city combo page is the money page and the default target for commercial local demand.** EMERGENCY, LOCAL-TRAN, and LOCAL-COMM all route to it. It carries the heaviest local E-E-A-T load (see the E-E-A-T foundation) because it must prove this business genuinely serves this city.
- **Location pages serve NEAR-ME and city-level demand,** but only if they carry unique, locally-specific value. A location page that is a templated near-duplicate of another city with the name swapped is a doorway page, a spam-policy violation. If there is nothing true and unique to say about a city, do not make the page.
- **Service-area pages prove coverage, not per-city depth.** They answer "do you come out to [area]" without spinning up a thin page per suburb. When a suburb deserves real depth (real jobs, real local conditions), it graduates to its own location or service-city page.
- **This system writes no blogs.** Pure LOCAL-INFO that has no commercial pull ("history of copper piping") is out of scope; point to BLOG-OS. LOCAL-INFO that is pre-hire ("why is my water heater leaking," "how long does a roof last in Arizona") lives as the educational passage block inside the relevant service or service-city page, where it earns the AI Overview citation and warms the reader toward the call.

---

## The decision procedure: classifying a target query from free signals

No paid tools required. Everything here is readable from a live Google search, the visible SERP, autocomplete, People-Also-Ask, and the competitors' own pages. Ahrefs / Semrush / DataForSEO are optional aids for volume and difficulty only; the classification does not depend on them.

**Step 1: Read the query aloud. What is the searcher trying to do?**
- Do they want someone to come out and fix something? Transactional (EMERGENCY / LOCAL-TRAN / NEAR-ME).
- Are they comparing or pricing? LOCAL-COMM.
- Are they trying to understand a problem? LOCAL-INFO.
- Are they looking for a specific business by name? NAV.

**Step 2: Check for urgency words.** "emergency," "24 hour," "now," "burst," "no [heat/AC/water]," "same day" => EMERGENCY. Lead the page with the phone number and response promise.

**Step 3: Run the live SERP and read its shape.** This is the strongest signal. Search the query in an incognito window set to the target city and read:
- **Is there a local pack (map of 3 businesses)?** Yes => transactional/commercial local intent; the target is a money page (service-city or location), and the GBP matters as much as the page. No pack => likely informational; served by the education block, not a standalone thin page.
- **What do the organic results look like?** Are they **service pages / location pages from local providers** (transactional, build a money page), or **articles and guides** (informational, build the education block), or a **mix with a listicle** like "10 best plumbers in [city]" (LOCAL-COMM, build the money page with comparison-grade proof and cost depth)?
- **Is there an AI Overview?** If yes, note the exact passages it quotes and which pages it cites; build extractable passages that answer the same question better with real local facts. AI Overviews cluster on LOCAL-INFO and LOCAL-COMM ("cost," "how long," "best," "vs").
- **Are there shopping/service ads or "message"/"call" buttons in the pack?** Strong transactional signal.

**Step 4: Read autocomplete and People-Also-Ask.** Type the query into Google and read the autocomplete suggestions and the PAA box. These reveal the real sub-intents and the exact question phrasings to answer on the page (PAA questions often become the page's FAQ verbatim, lightly rewritten). "[service] [city]" autocompleting to "...cost," "...reviews," "...near me," "...emergency" tells you which variant pages the demand supports.

**Step 5: Confirm the page type against the mapping table.** Match the resolved intent to its primary page type. If the SERP for a supposed "location page" target is entirely national articles with no local pack, the query is informational and the location page is the wrong target; re-scope.

**Step 6: Halt-and-rescope check.** If the live SERP shows the target is purely informational with no commercial or local pull (national guides, no pack, no local providers ranking), this system is the wrong tool; the piece belongs in BLOG-OS or as an education block inside an existing money page, not a standalone page here.

---

## Worked example: three plumbing queries in Tempe, three different pages

Same trade, same city, three distinct intents. Reading each from free signals:

**"emergency plumber Tempe"**
- Intent: EMERGENCY (urgent transactional). Urgency word present.
- Live SERP: local pack at the top with "call" buttons, organic results are local plumbers' emergency/service pages, no AI Overview. Autocomplete offers "...24 hour," "...near me."
- Page type: service-in-city combo, emergency angle led. `/write-service-city-page`.
- Shape: phone number and "we answer 24/7, tech dispatched fast" above the fold, response-time promise, license/bond/insurance and review count compressed high, then the education block below for the answer engines.

**"how much does drain cleaning cost in Tempe"**
- Intent: LOCAL-COMM (commercial investigation, cost). "How much" + "cost" + city.
- Live SERP: likely an AI Overview quoting price ranges, organic mix of local service pages and a couple of guide-style "cost of drain cleaning" pages, pack may or may not show. Autocomplete offers "...average cost," "...vs hydro jetting." PAA: "why is drain cleaning so expensive," "cabling vs hydro jetting."
- Page type: service-in-city combo (drain cleaning x Tempe) with a real cost section, or the cost/FAQ block inside the plumbing service-city page. `/write-service-city-page`.
- Shape: an extractable, honest price range with the real local factors that move it (line length, cabling vs hydro jet, camera inspection), built to win the AI Overview citation, plus the trust and conversion path. Real numbers the operator will stand behind, pulled from the SME interview; never invented.

**"water heater installation Tempe"**
- Intent: LOCAL-TRAN (considered transactional). Planned install, no urgency word.
- Live SERP: local pack, organic dominated by local plumbers' water-heater service/location pages, possibly an AI Overview for "how long does installation take." Autocomplete: "...cost," "...tankless," "...same day."
- Page type: service-in-city combo (water heater installation x Tempe). `/write-service-city-page`.
- Shape: full considered-purchase page: what the install involves, tank vs tankless tradeoffs in Tempe's hard water, named equipment and warranties, permit/code path, real completed local jobs, price posture, credentials, then the call to action. Heavier education than the emergency page, because this searcher is researching, not panicking.

Three queries, one trade, one city, three pages, each classified from the live SERP and each mapped to its correct type. That is the discipline: the page is engineered for the intent the SERP proves exists, not the page the writer felt like writing.

---

## Intent mismatches to watch for

- **Writing a long education page for a transactional or emergency query.** The searcher wanted a number to call; they got an essay. High bounce, no calls. The pack and the money pages win.
- **Writing a thin templated city page for a query the SERP shows wants depth.** The location page has nothing true and unique about the city; it is a doorway page and ranks against no one.
- **Collapsing emergency and considered into one page.** The emergency searcher scrolls past your install guide; the considered searcher is put off by the panic lead. Split them.
- **Building a standalone page for pure informational demand.** No pack, no commercial pull, national guides ranking: this belongs in a blog or as an education block, not a page in this system. Re-scope.
- **Ignoring the AI Overview on cost/comparison queries.** The searcher gets their answer from the Overview and never clicks. If you are not the cited passage, you are invisible for that query. Build the extractable, honest, locally-specific answer.

Intent classification is gate one. Get it wrong and no amount of craft in the draft rescues the page. Classify from the live SERP, map to the page type, then write.
