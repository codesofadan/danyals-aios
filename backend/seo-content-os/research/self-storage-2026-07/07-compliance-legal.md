# 07 - US Self-Storage Compliance & Legal Spine

Territory dossier for a content-compliance overlay (self-storage vertical, US market).
Research run: 2026-07-23 PKT. Every claim below traces to a source fetched or searched this run; URLs are inline. Where a live government host (flsenate.gov, capitol.texas.gov, leginfo faces client) blocked or timed out, the statute text was read via an official mirror (Justia, public.law, CA leginfo billTextClient) and that mirror URL is the citation. Items that could not be pinned to a statute are labeled **pattern**, not fact.

> **How the writer should use this.** These are the ways self-storage marketing copy can cross from "aggressive" into "legally actionable or regulator-exposed." The compliance overlay converts them into gate rules (AUTO-FAIL = block the draft; REQUIRE = copy is missing a mandatory element; STATE-DEP = the rule's existence or threshold depends on the client's state, so the gate must read `brand.yaml` state before firing). The last section is the ready-to-encode rule list.

---

## 0. The two legal layers that govern self-storage copy

1. **Federal advertising law** - FTC Act Section 5 (unfair/deceptive acts or practices) plus specific FTC guides. This is national and applies to every facility's website, ads, and offers. Source: FTC Advertising FAQ's, "the two most important tools... a solid understanding of the FTC Act" and that ads must be truthful, non-deceptive, and backed by evidence ([ftc.gov/business-guidance/resources/advertising-faqs-guide-small-business](https://www.ftc.gov/business-guidance/resources/advertising-faqs-guide-small-business)). Every US state also has a "little FTC Act" (UDAP statute) that mirrors this, so a deceptive-pricing claim is actionable at both levels.

2. **State Self-Service Storage Facility Acts** - nearly every state has a dedicated statute governing the storage lien, the pre-sale notice chain, late fees, and (increasingly) rental-agreement disclosure. These vary materially by state. Confirmed this run: California (Bus. & Prof. Code ch. 10, ss. 21700-21716), Texas (Property Code ch. 59), Florida (Statutes ch. 83, **Part III**, ss. 83.801-83.809). **Correction to the brief:** Florida's self-service storage act is Part **III** of chapter 83, not Part IV ([law.justia.com/codes/florida/title-vi/chapter-83/part-iii/section-83-806](https://law.justia.com/codes/florida/title-vi/chapter-83/part-iii/section-83-806/)).

The overlay's job: copy about **auctions, lien sales, "we notify you before we sell," late fees, insurance/protection, climate control, free months, "$1 move-in," rate locks, security, and accessibility** is exactly where a real statute or a real FTC rule sits underneath the marketing claim.

---

## 1. State Self-Service Storage Facility Acts - lien sale, notice, advertising

The lien-sale process is the single most statute-governed thing a storage operator does, and copy that describes it (a) must not misstate the tenant's rights and (b) must not promise a process softer than the statute if the operator will actually follow the statute. Three verified state templates show how much the details move:

**California - Bus. & Prof. Code ss. 21700-21716.**
- Lien attaches to all personal property in the unit for unpaid rent/charges (s. 21702) ([law.onecle.com/california/business/division-8/chapter-10](https://law.onecle.com/california/business/division-8/chapter-10/index.html)).
- Notice of lien sale must tell the occupant their access is terminated, the current lien amount, that property will be sold after a date **not less than 14 days from mailing**, that they can stop the sale by paying in full, and that they can file a signed **declaration in opposition** by certified mail to force the operator into small-claims court instead of auction ([law.justia.com/codes/california/2009/bpc/21700-21716](https://law.justia.com/codes/california/2009/bpc/21700-21716.html)).
- Advertisement of sale: published **once a week for two consecutive weeks** in a newspaper of general circulation in the judicial district (s. 21707) (same source).

**Texas - Property Code ch. 59.**
- Notice of claim (s. 59.043) must contain an itemized account, the lessor's name/address/phone, a statement that contents were seized under the contractual landlord's lien, and a warning that if unpaid within **14 days** the property may be sold at public auction or towed; delivered in person, by verified mail, or by email **only if the rental agreement authorizes email** ([texas.public.law/statutes/tex._prop._code_section_59.043](https://texas.public.law/statutes/tex._prop._code_section_59.043)).
- Notice of sale (s. 59.044) must contain a general description of the property, a statement it is sold to satisfy a landlord's lien, the tenant's name, the facility address, and the time/place/terms of sale; **published once in each of two consecutive weeks** in a newspaper of general circulation in the county (or, if none, posted at the facility plus five conspicuous nearby locations) ([texas.public.law/statutes/tex._prop._code_section_59.044](https://texas.public.law/statutes/tex._prop._code_section_59.044)).
- Excess proceeds held for the tenant for **two years** ([law.justia.com/codes/texas/property-code/title-5/subtitle-b/chapter-59/subchapter-c/section-59-044](https://law.justia.com/codes/texas/property-code/title-5/subtitle-b/chapter-59/subchapter-c/section-59-044/)).

**Florida - Statutes ch. 83 Part III, s. 83.806.**
- Advertisement of sale published **once a week for two consecutive weeks** in a newspaper of general circulation; if none, posted at least **10 days** before sale in not fewer than **three conspicuous places** in the neighborhood.
- Online lien sales expressly allowed on a public website that customarily conducts personal-property auctions, and the operator needs no auctioneer license to post ([law.justia.com/codes/florida/title-vi/chapter-83/part-iii/section-83-806](https://law.justia.com/codes/florida/title-vi/chapter-83/part-iii/section-83-806/); 2024 text confirmed via [flsenate.gov/Laws/Statutes/2024/83.806](https://www.flsenate.gov/Laws/Statutes/2024/83.806) listing, host unreachable for full fetch this run).

**What this means for copy (STATE-DEP):** the notice window (14 days in CA and TX), the number of newspaper insertions, and the "declaration in opposition" right are statute-specific. Marketing copy that describes the auction/lien timeline ("we'll always give you 30 days," "we notify you three times," "you can't lose your unit without a court order") is a factual claim about a statutory process and is only safe if it matches that state's act. **Do not let generic copy state a specific notice period, number of notices, or tenant remedy unless it is pulled from the client's state statute.**

**Pattern (not yet statute-verified this run):** the near-universal existence of a state Self-Service Storage Facility Act is treated as an industry given; only CA, TX, FL were read to their text this run. The overlay should carry a per-state statute citation in `brand.yaml`, not a hardcoded national rule.

---

## 2. Late fees and lien fees

**California is the concrete example of a hard statutory cap** (Bus. & Prof. Code s. 21713.5): a late fee may be charged only if rent is unpaid **10 days** past the due date, must be stated in the rental agreement, and is capped at a "reasonable" schedule - **$10** if monthly rent is $60 or less; **$15** if rent is over $60 but under $100; **$20 or 15% of monthly rent, whichever is greater**, if rent is $100 or more. Only one late fee per missed payment ([law.justia.com/codes/california/code-bpc/division-8/chapter-10/section-21713-5](https://law.justia.com/codes/california/code-bpc/division-8/chapter-10/section-21713-5/)).

**Overlay implication (STATE-DEP):** copy that advertises or quotes a specific late fee, or says "low late fees" / "no hidden late fees," is a factual claim measured against the state cap. In California a "$25 late fee" advertised on a $90 unit would exceed the statutory $15 ceiling and is both a lease-drafting problem and a deceptive-advertising exposure. Other states set fees by "reasonableness" rather than a dollar grid, so the gate must not assume the California numbers nationally - flag any advertised late-fee figure for state review.

---

## 3. Tenant "protection plans" vs. tenant insurance - the "not insurance" trap

This is the highest-frequency legal-risk phrase in storage marketing, because operators sell an in-house **protection plan** (they self-indemnify for a monthly add-on) but the word "insurance" is regulated.

- **California - protection plans are NOT insurance.** *Heckart v. A-1 Self Storage, Inc.* (Cal. Supreme Court, 2018): unanimous ruling that a self-storage tenant-protection plan is not insurance subject to the Insurance Code, because the plan was "purely incidental" to the rental agreement and the facility indemnifies the tenant directly (the "principal object and purpose" test), not through a third-party carrier ([insideselfstorage.com/self-storage-profit-centers/california-supreme-court-rules-self-storage-tenant-protection-plans-aren-t-subject-to-insurance-code](https://www.insideselfstorage.com/self-storage-profit-centers/california-supreme-court-rules-self-storage-tenant-protection-plans-aren-t-subject-to-insurance-code)).
- **New Mexico - opposite result.** Under a broader statutory definition of "insurance" ("a contract whereby one undertakes to pay or indemnify another as to loss from certain specified contingencies or perils"), a court found the protection plan **was** insurance and **a fine was levied against the operator** ([insideselfstorage.com/tenant-insurance-protection/busting-5-misconceptions-about-self-storage-tenant-insurance](https://www.insideselfstorage.com/tenant-insurance-protection/busting-5-misconceptions-about-self-storage-tenant-insurance)).
- **Genuine tenant insurance** is a regulated product: it is sold under state insurance-department oversight and typically requires the operator to hold a license (often a limited-lines license) to sell it (same tenant-insurance source).

**Overlay implication (STATE-DEP, high severity):**
- If the client sells a **protection plan** (self-indemnity), copy must NOT call it "insurance," "coverage," "insured," "policy," or "premium." Industry-standard disclosure language: "The program is not an insurance policy... and the provider is not an insurance company" ([members.storelocal.com/blog/tenant-protection-vs-tenant-insurance](https://members.storelocal.com/blog/tenant-protection-vs-tenant-insurance) via search; corroborated by the ISS tenant-insurance article above). Calling a protection plan "insurance" is what triggered the New Mexico fine and is the exact regulated-term risk.
- If the client sells **true tenant insurance**, copy may say "insurance" only if the operator is actually licensed to sell it in that state.
- The gate cannot resolve which product the client sells from the copy alone - it must read a `brand.yaml` field ("tenant_protection_type: protection_plan | licensed_insurance") and enforce the vocabulary accordingly.

---

## 4. "Climate controlled" claims - no legal definition, real reliance liability

There is **no industry or legal standard** for "climate controlled." Facilities variously use it to mean air-conditioned only, temperature-only, or temperature **and** humidity controlled; commonly cited operating ranges are ~55-85 F with humidity managed to roughly 45-55%, but "these vary based on the facility" and "'climate-controlled' isn't a regulated term" ([storagepug.com/blog/climate-controlled-storage](https://www.storagepug.com/blog/climate-controlled-storage); [extraspace.com/blog/self-storage/understanding-the-different-types-of-climate-controlled-storage](https://www.extraspace.com/blog/self-storage/understanding-the-different-types-of-climate-controlled-storage/)).

**Why it is a liability, not just a semantics issue:** *DiSanto v. Safeco Insurance* (Ohio, 2006) - a facility advertised units as "climate-controlled" and "dry and safe"; after water damage the court found a genuine factual dispute over whether the tenant justifiably **relied** on those representations, and the case proceeded against the facility precisely because the terms were undefined in the lease and the ads ([insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements](https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements)).

**Overlay implication:** "climate controlled" is allowed only if the copy also states what is actually controlled. AUTO-FAIL a bare "climate controlled" that is paired with humidity-implying promises ("keeps your items dry," "prevents mold/mildew," "protects against moisture") unless `brand.yaml` confirms the facility actively controls **humidity**, not just temperature. If only temperature is controlled, require the honest term ("temperature controlled" / "heated and cooled") and forbid moisture/dryness promises.

---

## 5. Move-in specials: "first month free," "$1 move-in," "50% off"

**Governing authority is the FTC's Guide Concerning Use of the Word "Free," 16 CFR Part 251** (read this run via [law.cornell.edu/cfr/text/16/251.1](https://www.law.cornell.edu/cfr/text/16/251.1)), plus FTC Act Section 5 deception standard.

Core rules from 16 CFR 251.1:
- All **terms and conditions** of a "free"/"$1" offer must be disclosed "clearly and conspicuously **at the outset**... so as to leave no reasonable probability that the terms of the offer might be misunderstood," and **"in close conjunction with the offer"** - the guide specifically prohibits burying conditions in an asterisked footnote.
- "Free" is truthful only against a bona fide **regular price** - the price at which the item was "openly and actively sold" in that market for the most recent 30 days; you cannot inflate the regular price to fund the "free" month.
- Frequency limits in the guide: a "free" offer should not run more than **6 months in any 12-month period**, with at least a **30-day gap** between offers and no more than **3 such offers per year** in the same trade area.

**FTC deception standard generally** (Advertising FAQ's): objective claims must be truthful and substantiated; fine print does not cure a misleading headline ([ftc.gov/business-guidance/resources/advertising-faqs-guide-small-business](https://www.ftc.gov/business-guidance/resources/advertising-faqs-guide-small-business)).

**Junk-fees rule - scope check (do NOT over-cite):** the FTC "Rule on Unfair or Deceptive Fees" (16 CFR Part 464, effective **May 12, 2025**) requires all-in total-price disclosure, but its "Covered Good or Service" is defined to reach **only live-event tickets and short-term lodging** - it does **not** bind self-storage ([consumerfinancialserviceslawmonitor.com/2024/12/ftc-releases-final-junk-fee-rule-modified-to-target-live-event-tickets-and-short-term-lodging](https://www.consumerfinancialserviceslawmonitor.com/2024/12/ftc-releases-final-junk-fee-rule-modified-to-target-live-event-tickets-and-short-term-lodging/); [ftc.gov/news-events/news/press-releases/2025/05/ftc-rule-unfair-or-deceptive-fees-take-effect-may-12-2025](https://www.ftc.gov/news-events/news/press-releases/2025/05/ftc-rule-unfair-or-deceptive-fees-take-effect-may-12-2025)). The overlay should treat all-in pricing as directional best practice for storage, but ground any hard rule in Section 5 + the "Free" guide, not in Part 464.

**Overlay implication:** a "first month free" or "$1 first month" headline REQUIRES the conditions in-line (admin/setup fee amount, required insurance/protection purchase, required autopay, minimum stay, unit-size limits). AUTO-FAIL when the mandatory admin fee, required protection-plan purchase, or minimum-term is disclosed only via asterisk/footnote or omitted. "Free" is AUTO-FAIL if the "regular" rate it references is not a genuine 30-day price.

---

## 6. Rate increases (ECRI), auto-renewal, and month-to-month disclosure

Existing-customer rate increases (ECRI - "existing customer rate increase") are the industry's core margin lever and the fastest-rising area of state regulation and litigation.

**California SB 709 (2025) - NEW, effective Jan 1, 2026.** Adds **Bus. & Prof. Code s. 21715.2**. For rental agreements entered on/after Jan 1, 2026, the agreement must disclose **on the first page, in larger/visually emphasized type**: (1) the initial term and any renewal term; (2) whether the fee is promotional/discounted; (3) the duration of any promotional rate; (4) **whether the rental fee is subject to change and, if so, the maximum rental fee the owner could charge during the first 12 months**; (5) the steps to terminate and avoid future charges; and (6) owner contact info. Confirmed against the bill text via CA leginfo ([leginfo.legislature.ca.gov billTextClient SB709](https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202520260SB709)) and a legal explainer ([norcaladvocates.com/selfstoragelawblog/californias-new-self-storage-law-sb-709](https://www.norcaladvocates.com/selfstoragelawblog/californias-new-self-storage-law-sb-709-what-consumers-need-to-know-about-new-contract-requirements)).
- **Accuracy flag / correction:** SB 709 is a **disclosure** law. It does **NOT** cap rate increases. An earlier draft carried rent-control language that was removed; a first-pass search this run incorrectly reported a "5% + CPI or 10%" cap - that figure is California's **residential** rent cap and does **not** apply to storage. Verified no-cap in two sources ([norcaladvocates.com](https://www.norcaladvocates.com/selfstoragelawblog/californias-new-self-storage-law-sb-709-what-consumers-need-to-know-about-new-contract-requirements); [forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know](https://forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know/)).

**California AB 498 (2026) - email lien notices.** To send lien notices by email, the operator must show the occupant actually downloaded, printed, viewed, opened, or otherwise acknowledged the email; otherwise fall back to mailed notice ([forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know](https://forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know/)). Affects copy that promises "paperless/e-notifications."

**California AB 380 / price-gouging.** After a declared emergency, price increases are limited to no more than **10% for 180 days** following the declaration ([forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know](https://forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know/)). Directly relevant to post-disaster "storage after the fire/flood" campaigns - AUTO-FLAG any "special disaster rate" copy that raises price in an emergency zone.

**Auto-renewal / negative option:**
- **FTC "Click-to-Cancel" / Negative Option Rule was VACATED** by the Eighth Circuit on **July 8, 2025**, on procedural grounds, days before its compliance date; it is **not in force** as of this run ([sidley.com/en/insights/newsupdates/2025/07/us-ftc-click-to-cancel-rule-struck-down](https://www.sidley.com/en/insights/newsupdates/2025/07/us-ftc-click-to-cancel-rule-struck-down); [crowell.com/en/insights/client-alerts/eighth-circuit-cancels-click-to-cancel](https://www.crowell.com/en/insights/client-alerts/eighth-circuit-cancels-click-to-cancel)). **Do not cite it as binding.** ROSCA (Restore Online Shoppers' Confidence Act) still governs online negative-option sign-ups with lighter disclosure/consent/cancellation duties.
- **State Automatic Renewal Laws still apply.** California's ARL was tightened effective **July 1, 2025** (stricter consent, disclosure, and cancellation) and applies to auto-renewing/month-to-month billing ([cooley.com/news/insight/2025/2025-06-04-california-automatic-renewal-law-amendments-take-effect-on-july-1-2025](https://www.cooley.com/news/insight/2025/2025-06-04-california-automatic-renewal-law-amendments-take-effect-on-july-1-2025)). Storage month-to-month autopay is a recurring charge and copy touching "auto-billing / auto-renew" is exposed under state ARLs even though the federal rule fell.

**Overlay implication:**
- REQUIRE: copy that advertises a **promotional/introductory rate** ("$29 to start," "intro rate") must not imply the rate is permanent; if the client is CA and the agreement post-dates 2026-01-01, the promo/max-in-12-months disclosure is a first-page legal requirement (SB 709) and the marketing page should not contradict it.
- AUTO-FAIL: "rate locked," "price never goes up," "guaranteed rate for life," "no rate increases" unless the client contractually guarantees it - these are false for standard month-to-month agreements with ECRI.
- AUTO-FLAG: emergency/disaster-zone pricing copy (CA AB 380 and general state price-gouging law).

---

## 7. Security-claim honesty - the fastest way to void your own lease

Every storage lease contains a limitation-of-liability / "we are not responsible for loss" clause. **Overstated security marketing can void that clause.** Concrete case law read this run ([insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements](https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements)):

- ***Dilbeck v. Yates* (Georgia, 1992):** a manager told a prospective tenant "no one had ever broken into any of the units" when numerous break-ins had in fact occurred. The court **voided the facility's liability-limiting lease clause** for fraudulent misrepresentation and awarded the tenant the value of stolen property.
- ***DiSanto v. Safeco* (Ohio, 2006):** "climate-controlled" + "dry and safe" advertising survived summary judgment against the facility on justifiable-reliance grounds (also cited in section 4).
- **Legal principle:** "if an operator acts with deceit, the court can choose to invalidate his defenses contained in the lease." Security words carry an implied promise the operator then has to keep - and providing security that then fails is itself a liability path.
- **Recommended safe framing (from the same source):** replace "security," "safe and secure," "protected," "your belongings are safe" with **verifiable factual descriptors** - "perimeter fencing," "individually coded gate access," "fenced and lighted," "24-hour recorded cameras" (only if true and operational).
- **State overlay:** some states bar contracting away negligence liability entirely - e.g., in Minnesota a storage rental agreement "may not exempt an owner from liability for damages to an occupant's personal property caused by the owner's negligence" (search result, [insideselfstorage.com](https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements)).

**Overlay implication (high severity):** AUTO-FAIL absolute security/safety guarantees ("your belongings are 100% safe," "guaranteed secure," "theft-proof," "nothing ever gets stolen here," "fully protected"). Allow only factual, verifiable security features present in `brand.yaml`. Never let copy answer a hypothetical history claim ("we've never had a break-in") - that is the exact *Dilbeck* fraud fact pattern.

---

## 8. ADA / accessibility claims

Self-storage facilities are **places of public accommodation under ADA Title III** - the rental office and public areas must be accessible (post-1990 construction must have a wheelchair-accessible office), and the facility's **website** is increasingly treated as covered too ([insideselfstorage.com/legal-issues/everything-self-storage-operators-need-to-know-about-the-americans-with-disabilities-act](https://www.insideselfstorage.com/legal-issues/everything-self-storage-operators-need-to-know-about-the-americans-with-disabilities-act); [members.storelocal.com/blog/ada-guidelines-for-self-storage](https://members.storelocal.com/blog/ada-guidelines-for-self-storage)).

- **Website accessibility:** *Robles v. Domino's Pizza* (9th Cir., 2019) established that a business's website can be a covered public accommodation; the circuits are **split** on whether a website alone qualifies, so exposure is jurisdiction-dependent ([mcafeetaft.com/appeals-courts-split-on-whether-websites-are-places-of-public-accommodation-under-ada](https://www.mcafeetaft.com/appeals-courts-split-on-whether-websites-are-places-of-public-accommodation-under-ada/)). ADA Title III filings exceeded 11,000 in 2021 and website-accessibility suits are a large share ([accessibe.com/blog/knowledgebase/court-rules-websites-public-accommodations-under-ada](https://accessibe.com/blog/knowledgebase/court-rules-websites-public-accommodations-under-ada)).

**Overlay implication:** "ADA compliant," "fully accessible," "wheelchair accessible" are factual claims. AUTO-FAIL these unless `brand.yaml` verifies it (accessible office/path of travel, and - for a "fully accessible" site claim - the page itself meeting WCAG). Ground-floor "drive-up" units are not automatically ADA-accessible; do not conflate "easy access" marketing with an ADA-compliance claim. This is also a page-quality concern: the very page making an accessibility claim should itself be accessible.

---

## 9. AUTO-FAIL / REQUIRE rule candidates for the overlay

Each row: pattern -> disposition -> why -> authority. `STATE-DEP` = threshold/existence depends on client state; gate reads `brand.yaml.state`.

| # | Banned / required pattern | Disposition | Why | Authority URL |
|---|---|---|---|---|
| C1 | "insurance," "coverage," "insured," "policy," "premium" used for an in-house **protection plan** | AUTO-FAIL (STATE-DEP) | Calling a self-indemnity plan "insurance" is a regulated-term violation; produced a fine in NM | [insideselfstorage.com tenant-insurance](https://www.insideselfstorage.com/tenant-insurance-protection/busting-5-misconceptions-about-self-storage-tenant-insurance) ; [Heckart, Cal. 2018](https://www.insideselfstorage.com/self-storage-profit-centers/california-supreme-court-rules-self-storage-tenant-protection-plans-aren-t-subject-to-insurance-code) |
| C2 | Say "insurance" without the operator holding a license to sell insurance in that state | AUTO-FAIL (STATE-DEP) | Tenant insurance is a state-regulated, licensed product | [insideselfstorage.com tenant-insurance](https://www.insideselfstorage.com/tenant-insurance-protection/busting-5-misconceptions-about-self-storage-tenant-insurance) |
| C3 | "safe and secure," "your belongings are safe," "protected," "theft-proof," "100% secure," "guaranteed secure" | AUTO-FAIL | Absolute security promise; can void lease liability cap (fraud/misrep) | [Dilbeck v. Yates via ISS](https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements) |
| C4 | Any claim about break-in/theft/fire history ("we've never had a break-in") | AUTO-FAIL | Exact *Dilbeck* fraud fact pattern; must answer honestly, never market a clean history | [ISS misleading-statements](https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements) |
| C5 | Bare "climate controlled" paired with "dry," "moisture-free," "prevents mold/mildew" when facility controls temperature only | AUTO-FAIL unless `brand.yaml` confirms humidity control | No standard definition; reliance liability (*DiSanto*) | [ISS misleading-statements](https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements) ; [storagepug climate](https://www.storagepug.com/blog/climate-controlled-storage) |
| C6 | "First month free" / "$1 move-in" / "free" without in-line disclosure of admin fee, required protection/insurance purchase, autopay, or minimum term | AUTO-FAIL (conditions in footnote/asterisk or omitted) | 16 CFR 251.1 requires conditions "at the outset... in close conjunction," not in fine print | [law.cornell.edu 16 CFR 251.1](https://www.law.cornell.edu/cfr/text/16/251.1) |
| C7 | "Free"/discount measured against an inflated or non-bona-fide "regular price" | AUTO-FAIL | "Regular price" = openly sold prior 30 days | [law.cornell.edu 16 CFR 251.1](https://www.law.cornell.edu/cfr/text/16/251.1) |
| C8 | "Rate locked," "price never increases," "guaranteed rate for life," "no rate increases" on standard month-to-month | AUTO-FAIL unless contractually guaranteed in `brand.yaml` | False for ECRI month-to-month agreements; deceptive under FTC Act s.5 / state UDAP | [ftc.gov advertising FAQ](https://www.ftc.gov/business-guidance/resources/advertising-faqs-guide-small-business) |
| C9 | Promo/intro rate copy that implies permanence | REQUIRE promo-duration + "subject to change" note; hard-required first-page in CA post-2026-01-01 | CA SB 709 (Bus.&Prof. s.21715.2) mandates the disclosure | [leginfo SB709](https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202520260SB709) |
| C10 | Advertised late fee figure | AUTO-FLAG for state cap review; AUTO-FAIL in CA if it exceeds the s.21713.5 grid ($10/$15/$20-or-15%) | CA caps late fees by rent tier; other states use "reasonable" | [law.justia CA 21713.5](https://law.justia.com/codes/california/code-bpc/division-8/chapter-10/section-21713-5/) |
| C11 | Copy stating a specific lien/auction notice period, number of notices, or tenant remedy | AUTO-FLAG unless pulled from the client's state act | Notice window and remedies are statute-specific (14 days CA/TX; declaration-in-opposition CA) | [CA 21700-21716](https://law.justia.com/codes/california/2009/bpc/21700-21716.html) ; [TX 59.043](https://texas.public.law/statutes/tex._prop._code_section_59.043) ; [FL 83.806](https://law.justia.com/codes/florida/title-vi/chapter-83/part-iii/section-83-806/) |
| C12 | "ADA compliant," "fully accessible," "wheelchair accessible" | AUTO-FAIL unless verified in `brand.yaml` (office + path of travel; page meets WCAG for a site claim) | Title III public-accommodation + website-accessibility exposure | [ISS ADA](https://www.insideselfstorage.com/legal-issues/everything-self-storage-operators-need-to-know-about-the-americans-with-disabilities-act) ; [Robles split](https://www.mcafeetaft.com/appeals-courts-split-on-whether-websites-are-places-of-public-accommodation-under-ada/) |
| C13 | Emergency/disaster-zone "special storage rate" that raises price after a declared emergency | AUTO-FLAG (STATE-DEP) | Price-gouging caps (CA AB 380: max 10% for 180 days) | [forgebuildings 2026 laws](https://forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know/) |
| C14 | "Paperless / we email all notices" implying email lien notice is automatic | AUTO-FLAG (STATE-DEP) | CA AB 498 requires proof of actual receipt for email lien notice; TX requires the agreement to authorize email | [forgebuildings 2026 laws](https://forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know/) ; [TX 59.043](https://texas.public.law/statutes/tex._prop._code_section_59.043) |
| C15 | Do NOT cite the FTC "junk fees" rule (16 CFR 464) or "Click-to-Cancel" rule as binding on storage | GUARDRAIL for the writer | 464 covers only tickets/lodging; Click-to-Cancel was vacated 2025-07-08 | [FTC 464 scope](https://www.consumerfinancialserviceslawmonitor.com/2024/12/ftc-releases-final-junk-fee-rule-modified-to-target-live-event-tickets-and-short-term-lodging/) ; [Click-to-Cancel vacated](https://www.sidley.com/en/insights/newsupdates/2025/07/us-ftc-click-to-cancel-rule-struck-down) |

---

## 10. State-dependent items (the gate must branch on `brand.yaml.state`)

- Lien-sale notice window, number of notices, publication count, "declaration in opposition" right (section 1) - **per-state statute**.
- Late-fee cap: hard dollar grid in CA; "reasonable" standard elsewhere (section 2).
- Protection-plan vs. insurance classification: not-insurance in CA (*Heckart*), insurance in NM; licensing to sell true insurance (section 3).
- Rental-agreement first-page disclosures: CA SB 709 from 2026-01-01; other states adopting similar (section 6).
- Email lien notice validity: CA AB 498, TX authorization requirement (section 6).
- Price-gouging during emergencies: CA AB 380 and general state price-gouging law (section 6).
- Negligence-liability waiver enforceability: barred in MN; varies elsewhere (section 7).
- Website/ADA public-accommodation exposure: circuit split (section 8).

---

## 11. Sources (all fetched or searched 2026-07-23)

Statutes / primary:
- CA Bus. & Prof. Code ss.21700-21716: https://law.justia.com/codes/california/2009/bpc/21700-21716.html ; https://law.onecle.com/california/business/division-8/chapter-10/index.html
- CA Bus. & Prof. Code s.21713.5 (late fees): https://law.justia.com/codes/california/code-bpc/division-8/chapter-10/section-21713-5/
- CA SB 709 (adds s.21715.2): https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202520260SB709
- TX Property Code ch.59: https://texas.public.law/statutes/tex._prop._code_title_5_subtitle_b_chapter_59 ; s.59.043 https://texas.public.law/statutes/tex._prop._code_section_59.043 ; s.59.044 https://law.justia.com/codes/texas/property-code/title-5/subtitle-b/chapter-59/subchapter-c/section-59-044/
- FL Statutes ch.83 Part III s.83.806: https://law.justia.com/codes/florida/title-vi/chapter-83/part-iii/section-83-806/
- FTC "Free" guide, 16 CFR 251.1: https://www.law.cornell.edu/cfr/text/16/251.1
- FTC Rule on Unfair or Deceptive Fees (16 CFR 464) effective 2025-05-12: https://www.ftc.gov/news-events/news/press-releases/2025/05/ftc-rule-unfair-or-deceptive-fees-take-effect-may-12-2025

Secondary / case law / analysis:
- FTC Advertising FAQ's (Section 5 deception): https://www.ftc.gov/business-guidance/resources/advertising-faqs-guide-small-business
- Heckart v. A-1 Self Storage (Cal. 2018): https://www.insideselfstorage.com/self-storage-profit-centers/california-supreme-court-rules-self-storage-tenant-protection-plans-aren-t-subject-to-insurance-code
- Tenant protection vs. insurance, NM contrast: https://www.insideselfstorage.com/tenant-insurance-protection/busting-5-misconceptions-about-self-storage-tenant-insurance
- Dilbeck v. Yates + DiSanto v. Safeco (misleading advertising / voided lease defenses): https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements
- "Climate controlled" no-standard: https://www.storagepug.com/blog/climate-controlled-storage ; https://www.extraspace.com/blog/self-storage/understanding-the-different-types-of-climate-controlled-storage/
- CA SB 709 explainer (no rate cap): https://www.norcaladvocates.com/selfstoragelawblog/californias-new-self-storage-law-sb-709-what-consumers-need-to-know-about-new-contract-requirements ; https://forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know/
- FTC junk-fees rule scope (tickets/lodging only): https://www.consumerfinancialserviceslawmonitor.com/2024/12/ftc-releases-final-junk-fee-rule-modified-to-target-live-event-tickets-and-short-term-lodging/
- Click-to-Cancel vacated 2025-07-08: https://www.sidley.com/en/insights/newsupdates/2025/07/us-ftc-click-to-cancel-rule-struck-down ; https://www.crowell.com/en/insights/client-alerts/eighth-circuit-cancels-click-to-cancel
- CA ARL amendments 2025-07-01: https://www.cooley.com/news/insight/2025/2025-06-04-california-automatic-renewal-law-amendments-take-effect-on-july-1-2025
- ADA Title III + self-storage: https://www.insideselfstorage.com/legal-issues/everything-self-storage-operators-need-to-know-about-the-americans-with-disabilities-act ; https://members.storelocal.com/blog/ada-guidelines-for-self-storage
- Website/ADA circuit split (Robles): https://www.mcafeetaft.com/appeals-courts-split-on-whether-websites-are-places-of-public-accommodation-under-ada/

### Verification notes / limits
- flsenate.gov, statutes.capitol.texas.gov, and several Justia/BillTrack/Legiscan pages returned DNS failures, timeouts, or HTTP 403 during this run; the corresponding statutory text was read via the official-mirror URLs cited above (public.law, Cornell LII, CA leginfo billTextClient, Justia year-archived pages).
- The exact `$` figures and day counts above are taken from the cited mirror text; before shipping a client page that quotes a specific number, re-confirm against that client's current state statute (statutes are amended annually).
- "Nearly every state has a Self-Service Storage Facility Act" is treated as an industry pattern; only CA, TX, FL were read to their text this run.
