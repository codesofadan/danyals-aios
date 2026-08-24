# The Service Page - Deep Playbook

**Artifact:** the SERVICE page. One page that ranks and converts for a single service across the whole brand, with no city in the target query. Examples: "roof replacement", "root canal", "AC installation", "water heater replacement", "slab leak repair", "personal injury" (as a law-firm practice-area page). It is the canonical, brand-wide explanation of one service and the topical hub every service-in-city page hangs off.

**Command:** `/write-service-page`. Load order per `CLAUDE.md`: doctrine -> google-compliance-spine -> foundations -> this playbook -> voice -> client `brand.yaml`.

**The one governing fact:** a service page has two jobs that pull in different directions, and it must win both at once. Job one is to be the topical-authority answer for the service (rank the head term, get cited in AI answers, feed link equity down to the money pages). Job two is to convert the visitor who is ready to buy that service now. A page that ranks but reads like an encyclopedia entry fails. A page that converts but is thin and undifferentiated never gets the traffic to convert. Every rule below serves resolving that tension.

**Reading contract.** Numbers in this playbook are directional priors for ranking a decision queue, not promises to quote a client. The obey-me facts are flagged inline with their primary source (the Whitespark AI-Overview study, Google's Search Quality Rater Guidelines dated 11 September 2025, Google's May 2026 FAQ deprecation note, schema.org type definitions). Every teardown URL in Sections 5 and 6 was fetched live during authoring; if a URL has since changed, re-verify before citing it to a client. No local fact (price, review count, credential, years, service radius) is ever invented; it comes from the client `brand.yaml`, the SME interview, or cited research. This is Law 8 territory: the page reads human because it is specific and true, not because it was laundered through a paraphraser. No detector-evasion, ever.

---

## 1. Purpose and the one job of a service page

### The one job

A service page exists to be the definitive brand-wide answer to a single question: "Do you do [service], and are you the one I should trust to do it?" It must satisfy the searcher who wants to understand the service (what it involves, what it costs, whether they need it) AND move the ready-to-buy searcher to a call or form. It is the page that owns the service as a concept for this business.

Concretely, a finished service page does five things:

1. **Ranks the head service term** ("roof replacement", "root canal") and the informational long-tail around it ("how long does a roof replacement take", "signs you need a new roof").
2. **Wins share of the AI answer** for that service by carrying self-contained, extractable, sourced passages an engine can lift.
3. **Converts** the commercial-intent visitor with proof, process clarity, pricing transparency, risk reversal, and a frictionless CTA.
4. **Acts as the silo hub**: it is the parent that every `[service] [city]` page links up to, and it distributes internal link equity and topical context down to those spokes.
5. **Establishes real E-E-A-T for the service**: the process specifics, credentials, and first-hand project detail that prove this business actually performs this work, not just names it.

### How it differs from a service-in-city page and a location page (the local silo)

This is the single most misunderstood distinction in local SEO, and getting it wrong causes cannibalization that suppresses both pages. The three page types answer three different questions:

| Page type | Answers | Target query | Primary axis |
|---|---|---|---|
| **Service page** (this artifact) | *What is this service and why us?* | `[service]` (brand-wide, no city, or the city where the business sits) | The service as a concept |
| **Service-in-city page** (the money page) | *Do you do this service in my city?* | `[service] [city]` | Service x place intersection |
| **Location page** | *What do you do in this city / at this branch?* | `[city] [company]` or `[services] [city]` | The place / branch |

Plain-language rule, corroborated by 2026 practitioner consensus: **service pages answer what you do; location pages answer where you do it; service-in-city pages answer the intersection.** ([Search Engine Land 90-day plan](https://searchengineland.com/local-seo-sprints-a-90-day-plan-for-service-businesses-in-2026-469059), [Emarketed](https://emarketed.com/seo/local-seo-2026-service-business-rankings/))

The relationship in the silo:

```
Homepage (entity anchor)
├── Service page: "Roof Replacement"        <- THIS ARTIFACT (hub)
│     ├── Roof Replacement in [City A]        (money page / spoke)
│     ├── Roof Replacement in [City B]        (money page / spoke)
│     └── Roof Replacement in [City C]        (money page / spoke)
├── Service page: "Roof Repair"
│     └── ...city spokes...
└── Location page: "[City A] Office"           (parallel axis: covers all services in City A)
```

The service page is the **deepest, most complete treatment of the service anywhere on the site**. The city spokes inherit its structure but localize (local proof, local pricing reality, local FAQs, service-radius facts, city-specific project photos). The location page is a different axis entirely: it is organized around a place and lists the services offered there, linking across to each service page.

**Cannibalization is the failure mode.** If the service page and a service-in-city page both try to rank for "roof replacement Austin", one suppresses the other ([MarketMyMarket](https://www.marketmymarket.com/building-effective-content-silos-for-local-seo/)). The discipline: the service page targets the un-cityed head term and the informational cluster; the city spokes own `[service] [city]`; the service page never optimizes for a specific city in its title, H1, or anchor targets. Internal anchors from the service page to its spokes use the city-qualified anchor ("Roof replacement in Round Rock"), never the bare head term, so the anchors reinforce the right page (this is the internal-link/anchor conflict check from the on-page audit spec).

**Edge case - the single-location business.** A business with one location and one service area collapses the service page and the service-in-city page into one, because "roof replacement" and "roof replacement [home city]" resolve to the same intent for that business. In that case, build one page, target the head term plus the primary city, and do not spin up thin near-duplicate city pages you cannot differentiate (that is doorway-page territory, a spam-policy violation per the doctrine and `CLAUDE.md`). Build additional city pages only when the business genuinely serves and can prove work in those additional cities.

---

## 2. Target intent and real query patterns

A service page must serve the full intent spread for one service, from someone who does not yet know they need it to someone with a quote request open in another tab. Take "roof replacement" as the worked example. The queries cluster into three bands:

**Informational (top of funnel, the searcher is diagnosing):**
- "signs you need a new roof"
- "how long does a roof replacement take"
- "roof replacement vs roof repair"
- "how long does a roof last"
- "what happens during a roof replacement"

**Commercial investigation (comparing, the searcher is choosing a provider):**
- "how much does a roof replacement cost" (the money question, and a hybrid: informational phrasing, commercial intent)
- "best roof replacement company"
- "roof replacement near me"
- "[brand] roof replacement reviews"
- "roof replacement financing"

**Transactional (ready to act):**
- "roof replacement quote"
- "free roof inspection"
- "roof replacement estimate near me"

The service page cannot be a pure blog post (it would not convert) or a pure landing page (it would not rank the informational cluster or feed the silo). It resolves the spread by **leading with the conversion answer and layering the informational depth beneath it** (BLUF for the aware buyer up top, the diagnostic and educational passages below for the researcher and the AI engines). This is the inverted-pyramid discipline from the content-drafting golden spec: the answer to the page's implied question sits in the first 100 words; the depth that satisfies the researcher and earns citations follows.

**Intent-SERP match is a P0 gate.** Before writing, confirm the page format matches what Google actually ranks for the target head term. For most `[service]` head terms in home services, law, and dental, the ranking set is a mix of service pages and cost guides, with a local pack and, increasingly, an AI Overview above them. If the SERP for your head term is dominated by cost-calculator content, the page must carry a genuine pricing section or it will not match intent. A service page shipped against a comparison-intent SERP ("roof repair vs replacement") is neither ranked nor cited.

**Keyword mechanics** (from the on-page audit spec, 2026-current, not 2021 density rules): the head service term is load-bearing in the title, H1, and first passage for commercial/transactional intent. Do not chase a keyword-density number. Cover the entity set the top-ranking pages share (materials, process, timeline, warranty, cost factors, permits) as a coverage floor, then go deeper than the median on the one thing you can own (the SME's real process, real local project detail). Length is an output of covering the intent completely, never a target.

---

## 3. The 2026 SERP and AI-answer reality for service queries

This is the environment the page ships into. It has changed materially, and a service page written to a 2021 model loses.

**AI Overviews now dominate the informational and hybrid bands of service search.** The Whitespark study (540 queries, 3 US cities, 6 local verticals including plumbers, personal-injury lawyers, dentists; manually collected, published 2026) found AI Overviews appeared in an average of **68%** of local-business queries, ranging 57-80% by vertical. Broken out by intent, the split is stark ([Whitespark](https://whitespark.ca/blog/case-study-the-prevalence-of-ai-overviews-in-local-search/)):

| Intent | AI Overview shown | Local pack shown |
|---|---|---|
| Local-intent ("primary care clinic Phoenix") | 15% | 93% |
| Informational ("how long does an eye exam take") | 92% | 6% |
| Hybrid ("cost of hiring a personal injury lawyer") | 97% | 17% |

Read that against the service page's job. The **informational and hybrid queries the service page targets are exactly the queries where the AI Overview appears 92-97% of the time.** The cost question, the "how long does it take" question, the "do I need this" question - an AI answer sits above the organic results for almost all of them. The local pack, by contrast, dominates the bare local-intent query and is largely absent from the informational cluster; there is no correlation between the two surfaces.

Three consequences for how the page is built:

1. **Being the cited source in the AI answer is now a first-class outcome, not a bonus** (doctrine Law 13). The page must carry self-contained, question-headed, sourced passages that an engine can lift verbatim: the direct cost answer, the process-timeline answer, the "do I need replacement or repair" answer. If the AI Overview answers the cost question by citing a competitor, the click and the trust go to the competitor.

2. **Zero-click is the default for the informational band, so the page must earn the click it does get.** The passages that win citations must also leave a reason to click through: the generic answer up top, the specific-to-this-business depth (real process, real local pricing reality, real project proof) that the AI answer cannot synthesize below it. The move is to answer the commodity question AND hold the un-summarizable specifics only this business has.

3. **AI packs are narrower than local packs.** Where an AI Overview carries a local element, it typically surfaces 1-2 businesses rather than the local pack's three, and strips the call button ([On Purpose Media](https://onpurposemedia.com/ai-overview-local-packs-impacting-visibility/)). Visibility is scarcer and more winner-take-all, which raises the bar on entity clarity (consistent NAP, clear brand mention, structured facts) so the engine associates the answer with this business.

**AI-crawler access is a precondition.** A page blocked from the search/answer fetchers cannot be cited. Confirm the page is reachable and server-rendered for the fetchers that decide citability - Googlebot (serves AI Overviews and AI Mode), OAI-SearchBot and ChatGPT-User, PerplexityBot and Perplexity-User, Claude-SearchBot and Claude-User. Blocking the training crawlers (GPTBot, ClaudeBot, Google-Extended, CCBot) is a separate IP-policy call that does not govern citation; the common and costly error is opening the training crawlers while the search fetchers are blocked.

**What has NOT changed:** the local pack still dominates bare local intent, and organic rank still gates AI citation (you generally must be in the ranking candidate pool to be lifted into the answer). Classic ranking is the entry gate; extractability is the selection layer on top. The page needs both.

---

## 4. Section-by-section architecture

Build in this order. Each block states what it must contain, the named framework it is built to, its local-SEO requirement, its schema requirement, a real-example precedent (live URLs torn down in Section 5), the anti-pattern, and a binary PASS test the draft must clear.

The governing sequence for the page as a whole is **belief-sequencing** (Joanna Wiebe, Copyhackers): each block earns the reader's belief before the next asks for more. Overlaid on it is the **PAS/PASTOR** spine (Problem - Agitate - Solution, extended by Ray Edwards to Problem - Amplify - Story - Testimony - Offer - Response) for the problem-to-proof middle. The page opens with the answer for the ready buyer, then walks the researcher through problem -> service -> proof -> price -> objections -> risk reversal -> close.

### 4.1 Hero + promise

- **Must contain:** one outcome-anchored H1 naming the service in the buyer's words; a one-line subhead that reduces risk or names what makes this provider different; one primary CTA action (call or quote), visible without scrolling on mobile; one first authority signal in the fold (aggregate rating with real count, years in business, licensed/insured/certified, or a warranty figure). The head service term appears in the H1.
- **Framework:** Copyhackers 5-element hero; the Rule of One (one reader, one dominant idea, one action). The headline is the service outcome, not a category label: "Get a roof that lasts 30 years, installed in a day" beats "Roof Replacement Services."
- **Local-SEO requirement:** the head service term in H1 and title; the business name and primary market present for entity clarity. Do not city-stuff the H1 (that is the city spoke's job); the head term is un-cityed or carries only the home market.
- **Schema requirement:** the fold's rating claim must be backed by `AggregateRating` inside the `Service` or `LocalBusiness` node, and the number on the page must equal the number in the markup (mismatch is a trust and structured-data-spam risk).
- **Precedent:** local service pages that lead with a picturable outcome plus a rating-and-count trust bar in the fold (Section 5 teardowns). Principle illustration from the broader corpus: Shopify's five-word outcome headline shows clarity beats length; Calm's "Try for free" shows the fold ask can be a low-friction first yes.
- **Anti-pattern:** a hero image with no message; a category-label H1 ("Professional Roofing Services"); two co-equal primary buttons splitting intent ("Call" and "Learn more" at equal weight); an unquantified claim ("the area's best roofers"); the licensed/insured/rating signal buried below the fold.
- **PASS test:** a first-time reader can state, in five seconds, what service this is, who it is for, one reason to trust it, and the single next action. If any of the four is missing or ambiguous, FAIL.

### 4.2 The problem / symptoms

- **Must contain:** the problem or symptoms in the buyer's own words, so the researcher who does not yet know they need the service recognizes themselves; the specific real-world signs, costs, and consequences of leaving it unaddressed. For "roof replacement": the water stains, the granules in the gutter, the daylight in the attic, the failed real-estate inspection, the escalating repair bills. Written as an extractable answer to "how do I know I need [service]".
- **Framework:** PAS (Problem-Agitate-Solution). Name the problem in mined customer language, then agitate by listing the concrete operational and financial costs before any pitch. Voice-of-customer mining supplies this language: pull the buyer's exact words from reviews and support calls, not a swipe file.
- **Local-SEO requirement:** this block is a citation magnet for the informational band ("signs you need a new roof") where the AI Overview shows 92% of the time. Make each symptom a self-contained, liftable statement. Where the problem has a local dimension (hail season in Texas, ice dams in the Northeast, hard-water scale on water heaters in a known hard-water metro), name the local specific - this is coverage the AI answer cannot synthesize generically and a city spoke can inherit and localize.
- **Schema requirement:** none mandatory; if this section is structured as Q&A ("How do I know I need a roof replacement?"), it may sit under the page's `FAQPage` node, with the honest caveat in 4.6.
- **Precedent:** Section 5 teardowns that open with a symptoms/diagnostic block before pitching. PAS as a structural spine is a widely-used default, not a proven-lift winner (the only lift evidence is DTC and does not transfer); use it because it sequences belief, and test it.
- **Anti-pattern:** jumping from hero straight to "why choose us" with no problem articulation (loses the researcher and the informational traffic); agitation written in the company's words ("your roof may be compromised") instead of the buyer's ("you keep finding little rocks in your gutters"); manufactured fear with no substantiable cost.
- **PASS test:** a searcher who typed "signs I need [service]" finds a self-contained answer they could paste as a standalone quote, in the buyer's language, with at least one specific/local detail. If the section is generic-anyone-could-write, FAIL.

### 4.3 The service explained: process and what is included

- **Must contain:** the actual process, step by step, in the sequence the business performs it (inspection -> quote -> permit -> tear-off -> deck inspection -> underlayment -> install -> cleanup -> final inspection); exactly what is included (and what is not); materials/options; timeline; what the customer needs to do. This is the E-E-A-T core: process specificity is the proof that this business actually does this work.
- **Framework:** the two-part mechanism (Stefan Georgi, RMBC), adapted for services: first the *mechanism of the problem* (why the cheap fix failed before - "most leaks come back because the flashing was never replaced, only the shingles"), then the *mechanism of the solution* (why this process uniquely prevents that). This is the belief bridge that turns a commodity service into a differentiated one.
- **Local-SEO requirement:** this is the deepest, most complete process description on the site - the city spokes inherit and localize it. Cover the shared entity set the top pages carry (materials, permits, timeline, warranty, disposal) as a floor, then go deeper than the median on the SME's real process. Include real specifics the SME interview surfaces (the exact underlayment brand, the deck-replacement policy, the permit handling) that no competitor can copy because they do not have them.
- **Schema requirement:** the `Service` node carries `serviceType`, `provider`, and a `hasOfferCatalog` enumerating the sub-services/steps as an `OfferCatalog` of named `Offer`/`Service` items. Note: `Service` schema is not eligible for a dedicated Google rich result; it aids entity understanding and disambiguation, per Google's supported-features list. Use it for what it does, do not promise a rich card.
- **Precedent:** Section 5 teardowns that show a numbered process with real inclusions and a named material spec. Principle: feature-listing with no causal story is the anti-pattern the two-part mechanism fixes.
- **Anti-pattern:** a bullet list of deliverables with no causal story for why the process produces a better outcome; vague stages ("we do a thorough job"); hiding what is not included so the quote surprises later; a process block identical to the one on every other service page (no service-specific substance).
- **PASS test:** a reader finishes this section able to describe, in their own words, what will physically happen and what they are paying for, including at least one specific detail (named material, exact step, explicit inclusion/exclusion) that proves first-hand expertise. If it reads as could-apply-to-any-provider, FAIL.

### 4.4 Why us / proof

- **Must contain:** proof distributed next to the claims it supports, not pooled in one wall: real named reviews with specifics (not "J.D., satisfied customer"), verifiable ratings with counts and a link to the source profile, named credentials and licenses, real project detail (photos of this crew's actual work, before/after, the specific neighborhood or project type), and the named humans who will do the work. For services, the credentials of the people delivering the work are part of the product.
- **Framework:** Bencivenga distributed proof; Cialdini (Authority carried by external verification, Social Proof, Liking/Unity via shared local context). Lead with third-party-verifiable proof (Google/BBB/Angi profile links, named case metrics) because self-hosted anonymous quotes have lost trust weight in the deepfake era.
- **Local-SEO requirement:** proof is where local specificity compounds. Name the real neighborhoods, the real project types, the local awards or chamber membership, the local licensing body. This is the un-copyable E-E-A-T layer and the strongest entity-consistency signal. Housecall Pro's homeowner survey found 72% would pay up to 10% more for a contractor with a stronger service reputation ([via Superpath](https://superpath.com/blog/four-potential-reasons-why-your-hvac-website-conversions-are-down-in-2026/)); reputation proof is a conversion lever, not decoration.
- **Schema requirement:** `Review` and `AggregateRating` on the `Service`/`LocalBusiness` node, honest and matching on-page counts; `sameAs` links to the real review profiles for entity reconciliation. Never mark up reviews the business did not receive - Google's review-snippet policy and the FTC's rules on fake endorsements both bite here.
- **Precedent:** Section 5 teardowns with named-customer reviews carrying project specifics and linked third-party profiles. Principle: logo soup and anonymous quotes are the failure; verifiable, attributable, specific proof is the moat.
- **Anti-pattern:** stock-photo team headshots; anonymous testimonials; unverifiable star widgets; "trusted by thousands" with no number; awards with no issuer; a review a skeptic cannot check.
- **PASS test:** every trust claim in this section is externally verifiable (a real profile, a real license number, a real named person, a real project) and at least one proof point is specific to this local market. An unverifiable or generic-only proof block FAILs.

### 4.5 Pricing transparency

- **Must contain:** real pricing guidance - a "starting from" anchor, a typical range, the factors that move the price, and financing options if offered. It does not require a fixed on-page price (most custom service work has none), but "contact us for pricing" as the entire pricing answer is the anti-pattern.
- **Framework:** Hormozi value stack used as structure (itemize what is included so perceived value exceeds the ask), plus price-anchoring. For services with no fixed price, substitute a value stack plus a "starting from" or "typical range" anchor and the honest cost drivers.
- **Local-SEO requirement:** "how much does [service] cost" is a hybrid query where the AI Overview appears ~97% of the time. A real, sourced pricing passage is the single highest-value citation and click-earning block on the page. Provide the range and the local cost drivers (local permit fees, local labor reality) as a self-contained answer. Qualifying the lead with a "starting at" figure filters tire-kickers ([improveit360](https://www.improveit360.com/blog/homeowner-behavior-shifts-2026/), [BeKindLocal](https://bekindlocal.com/the-high-converting-checklist-for-home-service-landing-pages-in-2026/)). Transparency is a 2026 conversion driver: homeowners now expect visible pricing and timelines, and trust converts better than any discount.
- **Schema requirement:** if a genuine fixed or "starting from" price exists, a nested `Offer` on the `Service` node with `priceSpecification` (or `PriceRange` on the `LocalBusiness`) is legitimate for completeness; do not expect a price rich result from it, and do not fabricate a price to populate markup. For custom-quote work, use `Offer` with `priceSpecification` omitted or a `PriceRange`, not an invented number.
- **Precedent:** Section 5 teardowns that publish a real range or a "starting at" figure with cost drivers. The FTC "junk fee" rule (effective May 2025) makes hidden mandatory fees a compliance risk, not just a trust risk.
- **Anti-pattern:** "contact us for a custom quote" as the entire pricing content; a single lump figure with no itemization or drivers; a price the business cannot honor; padding the section to seem transparent while saying nothing.
- **PASS test:** a reader leaves with a real sense of what this will cost them and why the number moves, sourced to the client `brand.yaml` or the SME, never invented. If the page dodges price entirely, FAIL.

### 4.6 FAQs (with FAQ schema)

- **Must contain:** the real buying objections and questions in the order a buyer raises them - price justification, "will this work for my situation", timeline, warranty, what happens after I book, licensing/insurance, financing, cleanup/disruption. Each answer is a self-contained, question-headed, citable passage carrying one checkable fact.
- **Framework:** objection-handling as friction-and-anxiety reduction. Author each answer to the paste-this-sentence-alone test: it must answer its question fully with no dependence on a prior paragraph.
- **Local-SEO requirement:** the FAQ is the densest concentration of extractable, question-shaped passages on the page - exactly the format AI engines lift. Map the questions to the real "People Also Ask" and to what the SME actually gets asked. Localize where it matters (permit questions, local warranty terms, service-radius questions).
- **Schema requirement - and the critical 2026 correction:** include a `FAQPage` node in the JSON-LD, but understand what it does now. **Google fully deprecated FAQ rich results as of 7 May 2026** ([Google's own FAQ doc note, reported widely](https://www.thehoth.com/blog/google-faq-rich-results-deprecated/)); the Aug 2023 restriction to government/health sites was the prior step. FAQPage markup earns **no rich result** on a commercial service page. Google still parses it, and it is a marginal machine-parsing aid, but the active ingredient is the on-page Q&A content, not the markup - AI engines lift clean Q&A whether or not the schema is present, and Google states no special schema is required for AI Overviews or AI Mode. So: ship the FAQPage node for completeness and parsing, label it internally as "no rich result, marginal parsing aid", and never sell it to a client as a rich-result or AI-citation win. The value is the content.
- **Precedent:** Section 5 teardowns whose FAQ answers real price/fit/risk objections rather than logistics. Anti-precedent: an FAQ of office-hours trivia that dodges the questions that actually block the sale.
- **Anti-pattern:** no FAQ; an FAQ that answers only logistics and avoids price, risk, and fit; answers that need prior context to parse (fail the standalone test); marking up FAQPage and telling the client it will produce a rich snippet (false in 2026).
- **PASS test:** the FAQ answers the real price/fit/timeline/risk objections, each answer passes the paste-alone test, and the FAQPage JSON-LD validates. If the FAQ dodges the hard objections or the schema is sold as a rich-result win, FAIL.

### 4.7 Risk reversal / guarantee

- **Must contain:** a named, exact-terms guarantee placed at the point of ask - workmanship warranty (with years), manufacturer warranty, satisfaction guarantee, "no mess left behind", free re-inspection, or "no-obligation quote". State the terms plainly. Pair it with the cost-of-inaction frame (the leak that becomes a deck replacement, the small cavity that becomes a root canal) using costs the business can substantiate.
- **Framework:** anxiety reduction - a guarantee shifts perceived risk from buyer to seller and removes a stated objection. Do not justify it with a fabricated loss-aversion coefficient; the mechanism needs no number.
- **Local-SEO requirement:** name the real warranty terms from `brand.yaml`; local licensing and bonding are part of the risk-reversal story ("licensed, bonded, and insured in [state]" with the real license number). A workmanship-warranty figure is also an entity/trust fact worth stating consistently across the site.
- **Schema requirement:** if the warranty is an offer term, it may be noted in the `Offer` (`warranty` via `WarrantyPromise`); optional, no rich result expected.
- **Precedent:** Section 5 teardowns that place a specific warranty ("10-year workmanship warranty") at the CTA. Principle: no risk reversal on a high-ticket service is a conversion leak; a guarantee so hedged it reads as a trap is worse than none.
- **Anti-pattern:** no guarantee on a high-ticket service; a vague "satisfaction guaranteed" with no terms; an inaction cost the business cannot substantiate; fine-print that contradicts the headline promise.
- **PASS test:** the page states a specific, real, honorable guarantee with its terms, placed at or near the CTA. A missing or unsubstantiated-terms guarantee FAILs.

### 4.8 The CTA

- **Must contain:** a single primary action worded as a first-person outcome ("Get my free roof inspection", "Book my consultation"), repeated 2-4 times down the page (after the hero, after proof, after the FAQ), in one reserved color; a phone number that is click-to-call on mobile and matches the NAP exactly; a form whose field count matches ticket size (more qualifying fields on high-ticket work, optimizing for cost-per-closed-deal, not raw submits). Any secondary action (e.g. "see our work") is demoted to a text link.
- **Framework:** attention conservation and the Rule of One (one destination, repeated); Commitment/Consistency (a low-friction first yes - "check my availability", "get my free inspection" - before the full ask); Reciprocity (a free inspection or audit is a gift that obligates). Multiple buttons are fine only if every one fires the same action.
- **Local-SEO requirement:** the phone number and business name at every CTA must be NAP-consistent with the Google Business Profile and every other page - inconsistency erodes the entity signal that AI packs and the local pack rely on. Click-to-call is non-negotiable on mobile for local service intent.
- **Schema requirement:** the CTA phone number appears in `telephone` on the `LocalBusiness` node; `contactPoint` optional. `availableChannel`/`ServiceChannel` can express the booking path.
- **Precedent:** Section 5 teardowns with a repeated single-action CTA and a click-to-call number in a sticky header. Principle: two or three co-equal primary CTAs in the hero split intent; a generic "Submit" verb underperforms a first-person outcome verb (contrast and hierarchy matter; the specific color does not).
- **Anti-pattern:** competing primary CTAs ("Call" + "Email" + "Chat" at equal weight); a generic "Submit"/"Send"; a 9-field form on a simple service; a phone number that differs from the GBP; no mobile click-to-call.
- **PASS test:** there is exactly one primary action, repeated, first-person, with a NAP-consistent click-to-call number, and the form length is justified by ticket size. Competing CTAs or NAP mismatch FAIL.

---

## 5. Best-in-class teardowns

Three real, live service pages (fetched and verified 2026-07-20 PKT). Each is torn down for the one transferable lesson, not to be copied wholesale. Re-verify a URL before quoting it to a client; live pages change.

### 5.1 Morgan & Morgan - Personal Injury (law, YMYL)
`https://www.forthepeople.com/practice-areas/personal-injury-lawsuits/`
- **Headline + fee model:** "We fight for people injured by negligence." Subline "The Fee is Free unless you win." The pricing model (contingency) is made the headline promise instead of being buried, which removes the single biggest objection on a YMYL money query.
- **Proof layer, the reason it wins:** $35B recovered, 700,000+ clients, 1,100+ attorneys, 100k+ 5-star reviews, and a library of specific verdicts ($644.7M Orlando slip-and-fall, $35M 2024, $20.04M 2022, $11M Phoenix 2025). This is earned litigation history rendered as numbers, not adjectives.
- **Depth:** "8 Steps to Take After an Injury" resource, a "what is my case worth" video, and a 50+ case-type breakdown that earns topical relevance honestly.
- **Transferable lesson:** the proof is uncopyable because it is theirs. A competitor cannot paste "$35B recovered." That is exactly the E-E-A-T surface this system builds from the SME interview: real, specific, verifiable numbers, not "trusted and experienced."

### 5.2 Benjamin Franklin Plumbing - Water Heater Installation (plumbing)
`https://www.benjaminfranklinplumbing.com/services/water-heaters/water-heater-installation/`
- **Proof:** 4.81 Google rating across 120,582 reviews, Forbes "Top Ranked Plumbing Company of 2024," and a punitive operational guarantee: "If There's Any Delay, It's You We Pay" ($5/minute up to $300). A guarantee that costs the business money when it fails is a credibility signal a hollow "satisfaction guaranteed" badge can never be.
- **Explanation depth:** every water-heater type (gas / electric / tankless / solar / high-efficiency) with pros and cons, the replacement warning signs (pooling water, rising bills, slow heating, pilot issues), and a stated install time (~3 hours).
- **Pricing:** no dollar figure, but the cost drivers are itemized (unit size, install difficulty, materials, labor, permits). Transparent about the variables even without a number, which is the honest move when a real number depends on a site visit.
- **Transferable lesson:** you can be pricing-transparent without publishing a price, by naming the drivers. The service playbook's pricing section uses exactly this when a fixed number is not truthful.

### 5.3 A1 Garage Door - Garage Door Repair
`https://a1garage.com/garage-door-repair/`
- **Technical specificity as expertise:** component cycle ratings (80,000-100,000 cycles), and a symptom-to-fix map across six components (spring / cable / roller / panel / track / drum). This is a genuine diagnostic tool, not filler, and it signals real product knowledge a generic "durable parts" page cannot fake.
- **Proof + partial pricing:** named-customer testimonials praising specific technicians, four third-party trust badges (Google / Angi / BBB / Nextdoor), a lifetime install warranty, a named $29.95 tune-up and a $400-off promo.
- **Transferable lesson:** engineering detail (real numbers, real component names) is both the ranking asset and the humanization asset at once. It reads expert because it is expert.

**What the three share:** every winning page leads with checkable specifics (a dollar figure, a review count, a cycle rating, a named guarantee) and explains the service as a real process. None of them read like AI, and none used a paraphraser to get there. They read human because they are made of true, specific facts, which is the whole Law 8 thesis in practice.

## 6. Worst / penalty-risk teardowns

Three real, live pages (verified 2026-07-20 PKT) that lose both the ranking and the conversion. These are public commercial pages torn down analytically to teach the failure pattern, not to disparage a business.

### 6.1 Telleria, Telleria & Levy - Personal Injury (law)
`https://www.tellerialevy.com/personal-injury`
- **The failure:** "Injured due to someone's negligence," "aggressive legal representation," "Let's fight for you," on ~400-500 words with no settlement figures, no testimonials, no fee structure, no FAQ, no case-type depth. Just two addresses and a phone number.
- **Why it loses:** on the same query as Morgan & Morgan it has zero proof layer and no informational depth to earn topical relevance. It is a template any PI firm could paste in, which is precisely the thin-content signal the helpful-content system demotes.

### 6.2 Buffalo Lawn & Pest Services - Pest Control
`https://www.buffalolawns.com/pest-control`
- **The failure:** "your trusted partner in the battle against insect invaders," "cutting-edge techniques," one-line boilerplate per service, no pricing, no process detail, no FAQ, and no seasonal or neighborhood-level pest specificity despite claiming local-climate relevance.
- **Why it loses:** the only real specific is a 45-years / family-owned claim. Everything else is indistinguishable from a pest-control template. It claims local relevance and proves none, which is the exact gap this system's local-substance rules close.

### 6.3 Garage Door Expert (Virginia) - Garage Door Repair
`https://www.garagedoorexpert.net/featured-services/garage-door-repair.php`
- **The failure:** ~1,200-1,400 words padded with repeated navigation and CTAs, not substance. "Skilled technicians equipped to handle a wide range of issues," four testimonials with no ratings/dates/verification, no pricing, no FAQ, no process, and no response-time guarantee despite a "Fast" headline.
- **Why it loses:** put side by side with A1 Garage Door on the identical service, it has none of A1's symptom-to-fix mapping, cycle-rating specificity, or verifiable badges. Length without substance does not rank; word count is not depth.

**The pattern across all three:** proof-free positioning. Confident adjectives ("aggressive," "trusted," "skilled") standing in for checkable facts. Every one would be caught by this system's first-hand-specificity gate and its keyword-vs-substance check before it shipped. The fix is never "add more words," it is "add true, specific, verifiable facts," which only the SME interview can supply.

## 7. E-E-A-T for services: proving real expertise

For a service page, E-E-A-T is not a content-marketing garnish; it is the difference between a page that reads as a real operator and a page that reads as a lead-gen shell. Per Google's Search Quality Rater Guidelines (dated 11 September 2025, active in 2026), Trust is the load-bearing member, and the December 2025 guidance extended the elevated E-E-A-T bar toward all competitive queries, not only YMYL (treat the "all queries" framing as strong practitioner inference, not verbatim Google policy). The service page is where a local business earns it. Concretely:

**Experience (the first E) is shown, not claimed.** The proof of first-hand experience is specificity only an operator who has done the work can produce: the exact failure mode they see most ("nine out of ten leaks we open up were never actually the shingle, it was the flashing"), the real step-count of their process, the material brands they actually install and why, the disposal and permit reality, the before/after of a real local job. The SME interview is the mechanism that surfaces this. "Family-owned since 1998" is worthless without the specifics that prove it. Original photos of this crew's real work outweigh any amount of first-person phrasing, because AI can fake the prose and cannot fake the job.

**Expertise is the named human and the credential.** Name the licensed operator, the master plumber, the board-certified dentist, the attorney with the bar number. Link the credential to a real, verifiable issuer. On the service page, the person who will do the work is part of the product; put a real face and a real name on it. Author/reviewer entity resolution matters: the named person on the page should resolve to a real, consistent identity (schema `Person` with `sameAs`, matching the visible byline).

**Authoritativeness is topical consistency.** The business should be a recognizable source for this service - the service page reinforced by the city spokes, consistent NAP, review profiles, and structured facts that let Google and the AI engines reconcile the entity. A roofer's service page that suddenly talks about gutters, solar, and windows with equal thinness dilutes the authority signal; depth on the owned service beats breadth.

**Trust is the sum: accurate claims, real proof, transparent pricing, honest guarantee, verifiable identity, clean NAP.** Every fabricated local specific (an invented review count, a borrowed stock photo, a warranty the business does not honor) is a fast path to a trust penalty and, for the regulated verticals, a legal one.

**The SME interview prompts that surface real E-E-A-T** (feed these into `/brief` for any service page): What is the most common thing customers get wrong about this service? Walk me through exactly what happens, step by step, on a real job. What do you include that competitors skip, and what do cheap providers cut? Tell me about a specific recent local job - the address type, the problem, what you found, how you fixed it. What is your actual warranty and has it ever been claimed? What licenses/certifications do you hold and who issues them? What does this really cost and what moves the number?

---

## 8. Google-compliance notes specific to service pages

The service page inherits every rule in `google-compliance-spine.md`; the ones that bite hardest for this artifact:

**YMYL escalation.** Where the service touches health (dental, medical, cosmetic procedures), legal (personal injury, family, criminal, immigration), financial (tax, lending, bankruptcy), or home-safety (electrical, gas, roofing, structural, mold, foundation), the page is YMYL and Google applies a much higher page-quality bar (Quality Rater Guidelines, Sept 2025). Practical consequences:
- Author/reviewer credentials must be real, named, and displayed (the "Medically reviewed by Dr. X, DDS" pattern; the attorney's bar number and jurisdiction).
- No contrarian claims against established consensus; differentiate with real experience and data, never by contradicting medical/legal/safety consensus.
- Double-verify every factual claim against an independent, human-authored authoritative source. A fabricated statistic on a YMYL service page is a reputational and potentially legal event.
- Claims are substantiated and non-deceptive; guarantees state real terms.

**No doorway pages.** The service page and its city spokes must each carry unique, genuinely useful, locally-specific value. Templated near-duplicate service pages (same body, service name swapped) or thin city clones (same body, city swapped) are a scaled-content / doorway-page spam-policy violation. The test: strip the service or city name; if the page is indistinguishable from the sibling, it is a doorway.

**Scaled-content-abuse.** Publishing volume beyond genuine editorial review is the site-level intent proxy Google acts on. A service page must be substantive per page, not one of forty thin near-identical pages. Value-per-page over volume (Law 8).

**Structured-data honesty.** Mark up only what is true on the page. `AggregateRating`/`Review` markup must reflect real reviews with on-page counts that match; fake or unearned review markup violates Google's policy and FTC endorsement rules. `Service` schema earns no rich result and must not be sold as one. FAQPage earns no rich result as of May 2026 and must not be sold as one.

**FTC and advertising law.** The "junk fee" rule (effective May 2025) makes hidden mandatory fees a violation - pricing claims must be honest and complete. Testimonials must be real and from real customers; fake reviews carry civil-penalty exposure. For the regulated verticals, state-specific advertising rules apply (bar-association rules for law firms, dental/medical advertising boards); flag for the client and do not draft claims that need a compliance review you cannot perform.

**AI-content disclosure.** Google does not penalize AI assistance per se (Law 8); it penalizes unhelpful, manipulative, or unverified content. Disclose AI involvement where a reader's trust turns on authorship (a first-person "I inspected" claim must be true), and never fabricate first-hand experience markers. The page must read human because it is substantive and specific, not because it was run through a humanizer - detector-evasion is a hard line, refused on sight.

---

## 9. Voice and humanization notes

The universal humanization layer (`knowledge/voice/`) and the client `brand.yaml` voice both apply. Service-page-specific craft:

- **Write in the operator's voice, not a marketing agency's.** A roofer, a dentist, and a personal-injury attorney do not talk alike. The service page should sound like the person who does the work explaining it to a neighbor: short paragraphs, contractions, plain words for the hard parts, the occasional specific aside only an insider would know. Voice-of-customer mining supplies the buyer's words; the SME interview supplies the operator's.
- **Kill the AI tells.** No "in today's fast-paced world", no "when it comes to [service]", no "look no further", no "nestled in the heart of", no hedge-stacking ("might potentially help ensure"), no listicle padding, no boilerplate transitions ("Furthermore," "Moreover,"). These are the sameness signal both readers and Google punish.
- **Vary sentence rhythm.** One idea per sentence where it earns the emphasis; mix a short punch against a longer explanatory line. Robotic uniform cadence is the tell.
- **Specificity is the humanizer.** The line that proves a human wrote it is the one carrying a fact an AI could not invent: the real material brand, the real neighborhood, the real number of steps, the real thing customers always get wrong. Every section should carry at least one such specific. This is Law 8 in practice: humanize via truth and detail, never via paraphrase laundering.
- **No em dash** (U+2014); the Write hook blocks it. Use hyphens or rewrite.
- **Blind-review test:** a competent editor reading the draft cold cannot flag any passage as machine-generated boilerplate, and a domain insider cannot find a place where the writer clearly did not understand the service. If either fails, revise with the specific gap, not a generic rewrite.

---

## 10. Meta formulas and JSON-LD

### Meta title formulas (pick by intent and market; keep to ~50-60 characters, front-load the service term)

- `[Service] in [Primary Market] | [Brand]` - default for a single-market business.
- `[Service] - [Differentiator/Outcome] | [Brand]` - e.g. "Roof Replacement - 30-Yr Warranty | Apex Roofing".
- `[Service]: [Cost/Timeline Hook] | [Brand]` - when the SERP rewards the cost angle, e.g. "Root Canal: Same-Day, Painless | Elm Dental".
- Head-term-first for entity clarity; the brand is a suffix behind a delimiter (hyphen or pipe), omitted if it costs the character budget on a non-brand query.

### Meta description formula (~150 characters, front-load value; Google shows it ~37% of the time, so write for the case it keeps)

`[Outcome/what you get]. [Proof or differentiator - rating, warranty, years]. [Risk-free CTA].`
Example: "New roof installed in a day, backed by a 10-year workmanship warranty. 4.9 stars, 600+ local jobs. Book your free inspection."

Do not keyword-stuff; write click-driving, honest framing. The description is not a ranking factor and is frequently rewritten; its job is the click on the impressions where it shows.

### JSON-LD (Service + Offer + FAQPage + BreadcrumbList, with LocalBusiness as provider)

Validate with `scripts/schema_validator.py`. All values come from `brand.yaml`; never invent a rating, count, price, or review. `Service` and `FAQPage` earn no rich result in 2026 - they are for entity understanding and parsing only.

```json
[
  {
    "@context": "https://schema.org",
    "@type": "Service",
    "@id": "https://{{domain}}/{{service-slug}}/#service",
    "serviceType": "{{Service name, e.g. Roof Replacement}}",
    "name": "{{Service name}} in {{Primary Market}}",
    "description": "{{One-sentence factual summary of the service}}",
    "provider": {
      "@type": "{{LocalBusiness subtype, e.g. RoofingContractor}}",
      "@id": "https://{{domain}}/#localbusiness",
      "name": "{{Brand}}",
      "telephone": "{{NAP phone}}",
      "priceRange": "{{$$ or real range}}",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "{{street}}",
        "addressLocality": "{{city}}",
        "addressRegion": "{{state}}",
        "postalCode": "{{zip}}",
        "addressCountry": "US"
      },
      "aggregateRating": {
        "@type": "AggregateRating",
        "ratingValue": "{{real rating, matches on-page}}",
        "reviewCount": "{{real count, matches on-page}}"
      },
      "sameAs": ["{{Google Business Profile URL}}", "{{BBB/Angi profile}}"]
    },
    "areaServed": [
      {"@type": "City", "name": "{{City A}}"},
      {"@type": "City", "name": "{{City B}}"}
    ],
    "hasOfferCatalog": {
      "@type": "OfferCatalog",
      "name": "{{Service}} options",
      "itemListElement": [
        {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "{{Sub-service 1}}"}},
        {"@type": "Offer", "itemOffered": {"@type": "Service", "name": "{{Sub-service 2}}"}}
      ]
    },
    "offers": {
      "@type": "Offer",
      "priceSpecification": {
        "@type": "PriceSpecification",
        "priceCurrency": "USD",
        "minPrice": "{{real starting-from figure, or omit for custom quote}}"
      },
      "availability": "https://schema.org/InStock"
    }
  },
  {
    "@context": "https://schema.org",
    "@type": "FAQPage",
    "@id": "https://{{domain}}/{{service-slug}}/#faq",
    "mainEntity": [
      {
        "@type": "Question",
        "name": "{{Real question 1, e.g. How much does a roof replacement cost?}}",
        "acceptedAnswer": {"@type": "Answer", "text": "{{Self-contained, sourced answer}}"}
      },
      {
        "@type": "Question",
        "name": "{{Real question 2}}",
        "acceptedAnswer": {"@type": "Answer", "text": "{{Self-contained answer}}"}
      }
    ]
  },
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [
      {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://{{domain}}/"},
      {"@type": "ListItem", "position": 2, "name": "Services", "item": "https://{{domain}}/services/"},
      {"@type": "ListItem", "position": 3, "name": "{{Service name}}", "item": "https://{{domain}}/{{service-slug}}/"}
    ]
  }
]
```

Notes: the `provider` `@id` should match the `LocalBusiness` node used site-wide so the entity reconciles. `FAQPage` is included for parsing completeness only (no rich result post-May-2026). Omit the `offers`/`priceSpecification` `minPrice` rather than invent one for custom-quote work. `BreadcrumbList` is the one node here still eligible for a rich result and reinforces the silo hierarchy.

---

## 11. Finished-page checklist

A page is not done until every line passes. Binary; a fail returns a specific error and re-runs (max 2 retries, then human queue).

**Intent + structure**
- [ ] Target head service term declared; page format matches the live SERP for it (intent-SERP match verdict on file).
- [ ] The head term is un-cityed (or home-market only); no city-spoke cannibalization; internal anchors to spokes use city-qualified anchor text.
- [ ] The answer to the page's implied question sits in the first 100 words (BLUF for the ready buyer); informational depth follows.
- [ ] Every H2 is a self-contained, extractable answer; no block over ~4 sentences.

**The eight blocks (Section 4)**
- [ ] Hero passes the five-second test (service, who, one trust reason, one action; fold trust signal present).
- [ ] Problem/symptoms block in the buyer's words, with at least one specific/local detail, extractable.
- [ ] Service explained with a real step-by-step process and explicit inclusions, carrying at least one first-hand-expertise specific.
- [ ] Why-us/proof block: every claim externally verifiable, at least one local-specific proof, real named reviews.
- [ ] Pricing transparency: a real range/"starting from" + cost drivers, sourced not invented; no bare "contact us".
- [ ] FAQ answers the real price/fit/timeline/risk objections; each answer passes the paste-alone test.
- [ ] Risk reversal: a specific, real, honorable guarantee with terms, at the CTA.
- [ ] CTA: one primary first-person action, repeated, NAP-consistent click-to-call, form length justified by ticket size.

**E-E-A-T + compliance**
- [ ] First-hand experience shown via SME specifics; named human + verifiable credential; NAP consistent site-wide.
- [ ] YMYL controls applied where the service is medical/legal/financial/home-safety (credentialed author/reviewer, consensus-aligned, double-verified facts).
- [ ] No doorway/near-duplicate; strip-the-name test passes.
- [ ] Zero fabricated local facts; every external fact cited in `sources.md`; every SME fact tagged.

**AI + technical**
- [ ] Server-rendered; search/answer fetchers (Googlebot, OAI-SearchBot, PerplexityBot, Claude-SearchBot and their -User agents) not blocked.
- [ ] Self-contained sourced passages for the cost answer, the process/timeline answer, and the do-I-need-it answer (the high-AI-Overview queries).
- [ ] Meta title (~50-60 chars, head-term front-loaded) and description (~150 chars, value-first) written.
- [ ] JSON-LD (Service + Offer + FAQPage + BreadcrumbList + LocalBusiness provider) validates; every rating/count/price matches the page or is omitted; FAQPage/Service not sold as rich results.

**Voice**
- [ ] No em dash; no AI tells; varied rhythm; operator voice, not agency voice.
- [ ] Blind-review test passes: no passage flags as machine boilerplate; no passage reveals the writer did not understand the service.

**Output contract (per `CLAUDE.md`)**
- [ ] `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md` all emitted; every gate marked pass with evidence.

