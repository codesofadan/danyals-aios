# Self-Storage Conversion & CRO Reality (US)

Research run: 2026-07-23 PKT. Market: United States.
Scope: how storage facilities actually convert online, the working conversion-element set, the primary-CTA reality (reserve vs rent-online vs call), and the truthfulness rules a conversion/compliance gate must enforce. Every fact below traces to a source read this run; recommendations and unverified live examples are labeled as patterns, not facts.

Sourcing note on the big REITs: Extra Space Storage and Public Storage FAQ pages return HTTP 403 to automated fetches. Public Storage's public deals page and CubeSmart's terms/FAQ pages fetched cleanly and carry the load-bearing exact numbers. Extra Space specifics are corroborated via third-party listings and the industry press, and are labeled as such.

---

## 1. The conversion-element set that actually works for storage

Storage is a near-commodity local purchase bought under one of two mindsets (see section 4). The elements below are the ones the industry itself builds and A/B tests. Ordered by conversion leverage.

### 1.1 Real-time price + availability on the page (the non-negotiable)
The single biggest lever is showing live, unit-level price and availability, pulled from the PMS, on the location page. Modern Storage Media's teardown of high-converting sites lists "Real-Time Pricing and Availability" as component #2 and states plainly: "Facilities with live inventory outperform those without" and recommends "transparent pricing with no hidden fees" plus size/type/amenity filters ([modernstoragemedia.com](https://www.modernstoragemedia.com/msm-exclusives/captivate-customers-5-components-of-high-converting-websites)). Storable frames the same point as intent-matching: "Most customers shopping for storage online intend to reserve and pay online without making a phone call" ([storable.com](https://www.storable.com/resources/self-storage-conversion-rate-optimization-strategies/)).

Implication for our pages: a location or service-city page that lists sizes and "call for price" is structurally lower-converting than one that surfaces the actual per-size web rate and unit count. Where the client feeds live inventory, show it; where they do not, show the honest current published web rate with a dated stamp, never an invented one.

### 1.2 A visible move-in special
Promotions are the near-universal hook. The real, current offer shapes across the three largest operators:

- **Public Storage:** "$1 First Month Rent", "50% off first month rent", and "2nd month free" (pay first, get second free), all "on select units", each tagged "LIMITED TIME OFFER" ([publicstorage.com/storage-solutions/storage-deals](https://www.publicstorage.com/storage-solutions/storage-deals)).
- **CubeSmart:** "First Month Rent Free", "First Month Half Off", and "Two Months Rent Free" (the two-month deal requires a minimum six-month agreement, second month applied to the final month) ([cubesmart.com/deals/terms](https://www.cubesmart.com/deals/terms/)).
- **U-Haul:** "One Month Free" self-storage, positioned to movers (free month commonly bundled with a truck/equipment rental) ([uhaul.com](https://www.uhaul.com/Tips/Storage/One-Month-Free-Storage-AT-U-Haul-Self-Storage-Locations-16119/)).

The critical compliance detail is what "free" excludes. CubeSmart's exact terms: the rent promotions "apply to rental payments due and do not apply to taxes, insurance/protection plan fees, administrative fees, or other fees" ([cubesmart.com/deals/terms](https://www.cubesmart.com/deals/terms/)). Any page we write that says "first month free" must not imply "$0 at move-in", because the admin fee and required protection plan are still due.

### 1.3 Transparent fee disclosure (admin fee, no deposit, month-to-month)
Storage carries a one-time **administrative / admin fee** on top of rent. Public Storage discloses it in fine print: "Other restrictions, taxes, and fees, including a **$29 administrative fee**, apply" ([publicstorage.com/storage-solutions/storage-deals](https://www.publicstorage.com/storage-solutions/storage-deals)). CubeSmart defines it functionally: "a one-time fee that covers your lease processing, account setup, gate access code creation, and the convenience fee for your first payment" ([cubesmart.com FAQ](https://www.cubesmart.com/storage-resources/frequently-asked-questions/)). A $29 one-time admin fee also appears on an Extra Space facility listing ([sparefoot.com listing](https://www.sparefoot.com/Gaithersburg-MD-self-storage/Extra-Space-Storage-3034-Gaithersburg-Diamond-Ave-229796.html)); treat the exact number as facility-specific, not a universal, until confirmed in the client's brand.yaml.

Two friction-killers the category leans on hard, both genuine trust signals:
- **No deposit** and **month-to-month**. CubeSmart: "Yes. We offer month to month leases for your convenience" ([cubesmart.com FAQ](https://www.cubesmart.com/storage-resources/frequently-asked-questions/)). Public Storage: "All Rentals Month to Month" ([publicstorage.com/storage-solutions/storage-deals](https://www.publicstorage.com/storage-solutions/storage-deals)).
- These are conversion assets precisely because they reduce perceived commitment. Surface them near the CTA.

### 1.4 The tenant protection plan / insurance line item (the margin engine, and a disclosure trap)
Coverage on stored goods is effectively **mandatory** at the two chains that state it plainly. CubeSmart: "you are responsible for the items you store... and insurance for those items is required"; a customer using their own homeowner/renter policy must present "a copy of the declarations page... at the time of rental" ([cubesmart.com FAQ](https://www.cubesmart.com/storage-resources/frequently-asked-questions/)). Extra Space: "you must have an active insurance policy that covers the items you store", with its Customer Protection Plan (CPP) offered as the default path ([extraspace.com search summary](https://www.extraspace.com/self-storage/faq/); FAQ page itself 403s to automated fetch).

Why operators push their own plan over "bring your own policy": it is a high-margin ancillary. Inside Self Storage reports operators may retain "50% to 60%" of collected tenant *insurance* premiums but "70% to 80%" on a tenant *protection* plan, because protection plans are billed as additional rent and are not rate-filed with a state insurance department, so the operator sets the price ([insideselfstorage.com](https://www.insideselfstorage.com/tenant-insurance-protection/peace-of-mind-plus-profit-how-tenant-insurance-and-tenant-protection-plans-bolster-the-self-storage-bottom-line)). Other industry figures cited this run: margins "up to 90 percent" and "$3-$6 per unit per month in pure profit" ([insideselfstorage.com tenant-protection advantages](https://www.insideselfstorage.com/tenant-insurance-protection/the-advantages-of-implementing-a-self-storage-tenant-protection-program)); a real price point of "$5,000 of coverage for $16 a month" (Inland Devon Self Storage, via the same peace-of-mind-plus-profit piece).

CRO consequence: forcing the protection-plan choice *inside* the checkout is a known conversion killer. StoragePug's fix: "Make insurance selection optional. Next, set it up to auto-enroll the new tenant after a set time, let's say 14 days" ([storagepug.com](https://www.storagepug.com/blog/reducing-friction-online-rentals)). For our copy: we can name the protection plan and its benefit truthfully, but we must never present it as free, never bury it, and never imply the "free month" covers it.

### 1.5 Trust signals near the decision
Reviews, security iconography (gates, cameras, lighting, alarms), real facility photos/video, and click-to-call/chat. Storable calls reviews "some of the most commonly used forms of demonstrating social proof and some of the most effective" ([storable.com](https://www.storable.com/resources/self-storage-conversion-rate-optimization-strategies/)). Modern Storage Media's component #5 is "High-Credibility Trust Signals" and notes "Many renters will happily pay more for a facility they perceive to be higher grade" ([modernstoragemedia.com](https://www.modernstoragemedia.com/msm-exclusives/captivate-customers-5-components-of-high-converting-websites)). This is the E-E-A-T surface expressed as CRO.

### 1.6 Mobile-first, e-commerce-style checkout
The category benchmarks itself against Amazon/Airbnb: minimal steps, autofill, progress indicators (Steps 1-3), familiar payment fields, instant SMS + email confirmation. "When the rental process is optimized, abandoned checkouts fall dramatically" ([modernstoragemedia.com](https://www.modernstoragemedia.com/msm-exclusives/captivate-customers-5-components-of-high-converting-websites)).

---

## 2. Primary-CTA reality: reserve vs rent-online vs call

There are three distinct conversion actions, and they are not interchangeable. Definitions from StoragePug ([storagepug.com/blog/reservations-vs-rentals](https://www.storagepug.com/blog/reservations-vs-rentals)):

| Action | What happens | Money / card | Commitment |
|---|---|---|---|
| **Reserve** | Holds a unit before move-in | None. "no charge to reserve a space and no obligation" (Public Storage) | Lead only. "a lead could back out and never rent" |
| **Rent online** | Inputs info, pays, e-signs lease; unit is theirs now | Full first payment + admin fee (+ protection) | Contract. Rental begins immediately (CubeSmart SmartRental: "your rental begins as soon as you complete the process") |
| **Call / in-person** | Manager completes it | At office | Contract |

Sources: reserve/no-card/no-obligation ([publicstorage.com/storage-solutions/storage-deals](https://www.publicstorage.com/storage-solutions/storage-deals)); SmartRental immediacy ([cubesmart.com/smartrental](https://www.cubesmart.com/smartrental/) via [cubesmart.com FAQ](https://www.cubesmart.com/storage-resources/frequently-asked-questions/)); Extra Space online path branded "Rapid Rental" ([extraspace.com/rapid-rental](https://www.extraspace.com/rapid-rental/), page 403s to fetch but confirmed via search).

### The conversion numbers (the reason CTA choice matters)
- **Reservation -> rental** converts roughly **40% to 80%** depending on the site; "the best operators convert around 50-60% of reservations into rentals" ([storagepug.com/blog/reservations-vs-rentals](https://www.storagepug.com/blog/reservations-vs-rentals)). So a reservation is worth, at best, ~0.5-0.6 of a rental.
- **Online-rental completion** (people who start the online rent flow and finish) averages **~31%** across "tens of thousands of rentals" per StoragePug, meaning "nearly 70% of users abandon the checkout process" ([storagepug.com/blog/reducing-friction-online-rentals](https://www.storagepug.com/blog/reducing-friction-online-rentals)).
- **Call -> sale** averages **~35%** ([storagepug.com/blog/reservations-vs-rentals](https://www.storagepug.com/blog/reservations-vs-rentals)).
- E-commerce baseline for context: storage sites are measured against a general US e-commerce conversion of "around 2.5% to 3%" ([storable.com](https://www.storable.com/resources/self-storage-conversion-rate-optimization-strategies/)).

### The operator debate, honestly
There is no single "right" CTA. StoragePug: "this decision is entirely up to you and what's best for your facility and market." Rent-online captures revenue immediately and fits the "most customers intend to reserve and pay online" reality, but forfeits tenant screening. Reserve is lower-friction and useful for lease-up and for vetting, but keeps the customer "in limbo... a lead could back out" ([storagepug.com/blog/reducing-friction-online-rentals](https://www.storagepug.com/blog/reducing-friction-online-rentals)). Note the industry still A/B tests even the micro-copy: Storable cites testing "Reserve Now" vs "Reserve Today" ([storable.com](https://www.storable.com/resources/self-storage-conversion-rate-optimization-strategies/)).

### Real primary-CTA button copy seen this run
- Public Storage: "Find Storage" / "Find Storage Deals Near You" (search-first), then reserve ([publicstorage.com/storage-solutions/storage-deals](https://www.publicstorage.com/storage-solutions/storage-deals)).
- Modern Storage Media's recommended pairing: "View Units" and "Rent Now" ([modernstoragemedia.com](https://www.modernstoragemedia.com/msm-exclusives/captivate-customers-5-components-of-high-converting-websites)).
- CubeSmart: "SmartRental" (contact-free online rental) ([cubesmart.com/smartrental](https://www.cubesmart.com/smartrental/)).

### How intent splits the CTA (the operator move)
Storage demand is driven by the "5 Ds / 6 Ds": Death, Divorce, Dislocation, Downsizing, Decluttering, and now Distribution ([storagecafe.com](https://www.storagecafe.com/blog/the-6-ds-of-self-storage-where-demand-is-strongest-across-the-us/)). Those collapse into two buying mindsets the industry names explicitly: customers who are "stressed and urgently needing storage due to an unexpected life event" vs those "planning ahead and weighing options" ([cubixassetmanagement.com](https://cubixassetmanagement.com/blog/drive-self-storage-demand-guide/)). This is the CTA fork:

- **URGENT move (relocation, eviction, disaster, a truck already loaded):** the dominant CTA should be **Rent Online Now** (unit secured today, e-sign, immediate gate code) with **click-to-call** as the co-primary for people who want a human to confirm access hours or truck clearance. Reservation is a downgrade here; it adds a step and a follow-up gap when the customer needs certainty today. StoragePug's canonical failure case is exactly this: a customer who cannot book the date she needs "is most likely going to go to a competitor" ([storagepug.com/blog/reducing-friction-online-rentals](https://www.storagepug.com/blog/reducing-friction-online-rentals)).
- **PLANNED declutter / downsizing / seasonal (weeks of lead time, comparison shopping):** **Reserve free, no card, no obligation** is the right lead CTA. It locks the web rate and the promo while the person is still deciding, and it converts at 40-80% on follow-up. The reservation's real product benefit is a genuine one to state: it "guarantees the prices on our website" while quoted rates fluctuate daily ([cubesmart.com FAQ](https://www.cubesmart.com/storage-resources/frequently-asked-questions/); Public Storage "Reservation required to guarantee price"). Rent-online stays visible as the secondary for the ready-to-commit.

Practical rule for our pages: lead with one primary CTA matched to the page's dominant intent, keep the other two present but subordinate, and always keep **click-to-call** one tap away on mobile (it is the safety valve for both mindsets and the highest-converting single action at ~35%).

---

## 3. Truthful vs fabricated urgency/scarcity (the line the gate must police)

This is the territory where the category's own marketing advice runs straight at Law 20 (no fabricated urgency). The industry openly recommends urgency; some of what it recommends is legitimate, some is a dark pattern. The distinction is not "urgency yes/no", it is **whether the specific claim is true right now and verifiable**.

### TRUTHFUL (allowed): the claim maps to a real, current state
- **Live-inventory scarcity from the PMS.** "Only X units left" is legitimate *only when it reflects real-time PMS availability*. Modern Storage Media lists "Only X units left!" as a feature of real-time-availability sites, explicitly tied to "real-time PMS integration" ([modernstoragemedia.com](https://www.modernstoragemedia.com/msm-exclusives/captivate-customers-5-components-of-high-converting-websites)). If the system truly shows 2 of that size remaining, showing "2 left" is true scarcity, and it is genuinely material: "If only one or two units remain, waiting may mean the price or promotion changes before you rent" ([radiusplus.com](https://www.radiusplus.com/latest/what-in-the-self-storage-web-rates-is-going-on/)).
- **A promotion with a real, enforced end date.** A "LIMITED TIME OFFER" is fine when the date is real and the offer actually ends then (Public Storage tags its deals this way, with "Subject to availability" and "new customers only") ([publicstorage.com/storage-solutions/storage-deals](https://www.publicstorage.com/storage-solutions/storage-deals)).
- **Rate-lock framing.** "Reserve to lock today's web rate" is true because storage web rates genuinely "change daily based on supply and demand" ([cubesmart.com FAQ](https://www.cubesmart.com/storage-resources/frequently-asked-questions/)).
- **Size-substitution honesty.** Popular sizes (5x10, 10x10, 10x20 climate-controlled) really do sell out locally; stating that a size is limited *when the live count says so* is truthful.

### FABRICATED (forbidden): the claim is manufactured, resetting, or unverifiable
- **A resetting / per-session countdown timer** that implies a deadline that never actually arrives. The FTC's "Bringing Dark Patterns to Light" report (2022) names fake countdown timers as a deceptive design under Section 5 of the FTC Act; a "perpetually resetting 'sale' timer" is the textbook non-compliant case, while a "real deadline, enforced server-side" is the compliant one ([growthsuite.net summary](https://www.growthsuite.net/questions/what-ftc-rules-apply-to-timers); FTC report via [ftc.gov press release](https://www.ftc.gov/news-events/news/press-releases/2022/09/ftc-report-shows-rise-sophisticated-dark-patterns-designed-trick-trap-consumers)).
- **Hard-coded "only 1 left" that is not wired to inventory.** The FTC's own example of an illegal scarcity claim is "Only two left in stock, order now" shown "when stock is plentiful" ([growthsuite.net summary](https://www.growthsuite.net/questions/what-ftc-rules-apply-to-timers); corroborated by dark-pattern enforcement coverage at [reedsmith.com](https://www.reedsmith.com/articles/dark-patterns-lead-to-enforcement-spotlight-key-compliance-steps-for-businesses/) and [journals.library.columbia.edu](https://journals.library.columbia.edu/index.php/stlr/blog/view/593)).
- **"Web rate" bait that the operator has no intention of honoring.** A related but distinct trap: advertising an artificially low web rate as if it is the enduring price, then applying an aggressive existing-customer rate increase (ECRI) weeks later. Radius+ reports "in-store rates and in-place rates can now surpass web rates by 30-50%" and warns the teaser web rate can hide "regular aggressive rate increases after an initial hidden promotional period" ([radiusplus.com](https://www.radiusplus.com/latest/what-in-the-self-storage-web-rates-is-going-on/)). This is legal in most states but is a trust penalty and a truthfulness problem for our copy: we do not present a web rate as a locked or permanent rate. If the client raises rates on a schedule, the honest move is the counter-position some operators now advertise, e.g. "your rate will not increase for at least one full year" ([radiusplus.com](https://www.radiusplus.com/latest/what-in-the-self-storage-web-rates-is-going-on/)) - and we only write that if it is contractually true.

The legal test the FTC applies is the **reasonable-consumer standard**, and it treats urgency as **material**: "False urgency is a material misrepresentation" ([growthsuite.net summary](https://www.growthsuite.net/questions/what-ftc-rules-apply-to-timers)). So the bar is not "would a savvy shopper see through it"; it is "would an average mover believe it and act."

---

## 4. Rules a conversion/compliance gate must enforce (storage overlay)

Concrete, checkable rules for the CONVERT stage (G13) and the compliance auditor. Each maps to a source above.

1. **No urgency claim without a live, verifiable basis.** "Only N left", "selling fast", "N units remaining" are permitted only if N is fed from real inventory (SME/brand.yaml must assert the page pulls live PMS data). No hard-coded unit counts. (FTC scarcity rule; Law 20.)
2. **No countdown timer unless it targets a real, fixed end datetime that is enforced and does not reset per visit/session.** Ban per-session or auto-resetting timers outright. (FTC countdown rule.)
3. **A promo end date, if stated, must be a real date** carried from brand.yaml, not a rolling "ends soon" with no date, and not "today only" unless it is literally true and enforced.
4. **"Free" / "$1" / "50% off" must disclose the still-payable fees in-copy:** the one-time admin fee and the required tenant protection plan / insurance are not waived by a rent promo. Mirror CubeSmart's exclusion language. Never imply "$0 due at move-in" when an admin fee applies. (CubeSmart terms.)
5. **Admin fee, deposit status, and month-to-month must be stated truthfully and specifically.** If the client charges a $XX admin fee, name it; if there is no deposit, say so; do not hide fees to inflate the "free" hook. (Public Storage $29 disclosure pattern.)
6. **Protection plan / insurance disclosed as a real cost and, where applicable, as required** - never framed as free, never omitted from the true move-in total. If we cite its price or margin, it comes from brand.yaml, not invented. (CubeSmart/Extra Space requirement; ISS margin data is context only, not for customer-facing copy.)
7. **Web rate is never presented as a locked or permanent rate.** No "this price forever" language. A rate-lock or no-increase promise ships only if the client's contract actually guarantees it. (Radius+ ECRI reality.)
8. **Reservation copy must stay honest about what a reservation is:** a free, no-card, no-obligation hold, not a confirmed rental. Do not imply the unit is "yours" or "guaranteed" beyond the rate/promo lock the operator actually offers. (StoragePug reserve vs rental.)
9. **One primary CTA matched to page intent** (rent-online for urgent, reserve-free for planned), with click-to-call always present on mobile. No CTA that forces a phone call when the customer's intent is self-serve. (G13 one-real-CTA + intent split.)
10. **No fee reveal at checkout that contradicts the page.** The price and promo shown on the page must equal the price at checkout; a "$0 first month" that becomes "$50 at checkout" is both a conversion killer and a truthfulness failure ([storagepug.com/blog/reducing-friction-online-rentals](https://www.storagepug.com/blog/reducing-friction-online-rentals)).

---

## 5. Open questions / gaps to close with the operator (SME)

- Does this client's site actually surface **live PMS inventory**, or static "call for availability"? Determines whether any scarcity claim is permissible at all.
- Exact **admin fee** amount, **deposit** policy, and whether **month-to-month** is truly no-minimum. (Public Storage $29 is their number, not a default.)
- Is the **protection plan required**, what does it cost the tenant, and what coverage tiers? Needed to write an honest move-in total.
- Real **current promotion** and its **real end date / unit eligibility**, sourced to brand.yaml, so urgency copy is truthful.
- Does the client run **ECRIs** (existing-customer rate increases), and on what cadence? Governs whether any "locked rate" or "no increase" claim can ship.
- Primary CTA the client's PMS supports: full **online rental (rent + e-sign + pay)** vs **reserve-only**. Some smaller operators only offer reserve; that caps the CTA choice.

---

## Source list (read this run)

- Public Storage, Storage Deals (offers, $29 admin fee, LIMITED TIME OFFER, reserve no-obligation, month-to-month): https://www.publicstorage.com/storage-solutions/storage-deals
- CubeSmart, Deals Terms & Conditions (free-month exclusions, 30-day rate-change notice, new-customers-only): https://www.cubesmart.com/deals/terms/
- CubeSmart, FAQs (admin fee definition, insurance required, month-to-month, daily-changing prices, reservation guarantees website price): https://www.cubesmart.com/storage-resources/frequently-asked-questions/
- CubeSmart, SmartRental (contact-free online rental, rental begins immediately): https://www.cubesmart.com/smartrental/
- StoragePug, Reservations vs. Rentals (definitions, 40-80% and 50-60% reservation->rental, ~35% call->sale): https://www.storagepug.com/blog/reservations-vs-rentals
- StoragePug, Reducing Friction in Online Rentals (~31% completion / ~70% abandon, insurance auto-enroll at 14 days, price-consistency, advance-date booking): https://www.storagepug.com/blog/reducing-friction-online-rentals
- Storable, Self-Storage CRO Strategies (intent to rent online, review social proof, Reserve Now vs Reserve Today A/B, 2.5-3% e-comm baseline): https://www.storable.com/resources/self-storage-conversion-rate-optimization-strategies/
- Modern Storage Media, 5 Components of High-Converting Websites (real-time pricing, "Only X units left" tied to PMS, View Units/Rent Now, trust signals): https://www.modernstoragemedia.com/msm-exclusives/captivate-customers-5-components-of-high-converting-websites
- Inside Self Storage, Peace of Mind Plus Profit (tenant insurance 50-60% vs protection plan 70-80% retention, $16/mo for $5k example): https://www.insideselfstorage.com/tenant-insurance-protection/peace-of-mind-plus-profit-how-tenant-insurance-and-tenant-protection-plans-bolster-the-self-storage-bottom-line
- Inside Self Storage, Advantages of a Tenant-Protection Program (up to 90% margin, $3-6/unit/month): https://www.insideselfstorage.com/tenant-insurance-protection/the-advantages-of-implementing-a-self-storage-tenant-protection-program
- Radius+, "What in the Self-Storage web rates is going on?" (web rate vs in-place rate 30-50% gap, ECRI, no-increase-for-a-year counter-position): https://www.radiusplus.com/latest/what-in-the-self-storage-web-rates-is-going-on/
- StorageCafe, The 6 Ds of Self-Storage Demand (Death, Divorce, Dislocation, Downsizing, Decluttering, Distribution): https://www.storagecafe.com/blog/the-6-ds-of-self-storage-where-demand-is-strongest-across-the-us/
- Cubix Asset Management, Drive Self-Storage Demand (urgent vs planning customer mindset): https://cubixassetmanagement.com/blog/drive-self-storage-demand-guide/
- GrowthSuite summary of FTC timer rules (Section 5, resetting timer vs server-side deadline, "false urgency is material"): https://www.growthsuite.net/questions/what-ftc-rules-apply-to-timers
- FTC press release, dark-patterns report "Bringing Dark Patterns to Light" (2022): https://www.ftc.gov/news-events/news/press-releases/2022/09/ftc-report-shows-rise-sophisticated-dark-patterns-designed-trick-trap-consumers
- Reed Smith, dark-patterns enforcement (false scarcity examples): https://www.reedsmith.com/articles/dark-patterns-lead-to-enforcement-spotlight-key-compliance-steps-for-businesses/
- U-Haul, One Month Free Self-Storage (mover-bundled free month): https://www.uhaul.com/Tips/Storage/One-Month-Free-Storage-AT-U-Haul-Self-Storage-Locations-16119/
- SpareFoot facility listing corroborating a $29 admin fee at an Extra Space location: https://www.sparefoot.com/Gaithersburg-MD-self-storage/Extra-Space-Storage-3034-Gaithersburg-Diamond-Ave-229796.html

Fetch failures noted: Extra Space Storage FAQ pages (fees, Rapid Rental, protection plan) returned HTTP 403 to automated fetch; their specifics above are corroborated via search summaries and third-party listings, and are labeled accordingly rather than quoted as exact facility numbers.
