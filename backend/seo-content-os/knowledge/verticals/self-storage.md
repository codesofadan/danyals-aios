# Vertical Compliance Overlay - Self-Storage

**What this is.** A compliance overlay the `compliance-auditor` applies ON TOP of the base gate stack (`knowledge/quality-gates/gates.md`) and the compliance spine (`knowledge/doctrine/google-compliance-spine.md`) whenever `brand.yaml.vertical == self-storage`. It does not replace any base gate. It adds the self-storage consumer-protection, lien-law, honest-security, honest-pricing, and honest-schema auto-fails to G2, G10, G11, G12, and G13. It is built from `research/self-storage-2026-07/` (dossiers 03, 04, 06, 07 and the master); re-verify the perishable statute/rule specifics against that research and the client's current state statute before a close claim.

**Why this overlay is mandatory even though self-storage is NOT YMYL.** Self-storage is a low-stakes retail rental, not a your-money-or-your-life trade, so `trade_is_ymyl` stays `false` and the heightened C5-spine health machinery does not fire. But storage has its own dense compliance surface that the base gates do not know about, and it is where storage copy actually gets sued or fined:

1. **The lien is the most statute-governed thing an operator does.** Every state has a Self-Service Storage Facility Act governing the auction, the pre-sale notice chain, and late fees, and the numbers move by state (14-day notice in CA/TX, "declaration in opposition" right in CA). Copy that describes the process is a factual claim about a statute.
2. **The protection plan is a regulated-word trap.** Operators sell an in-house self-indemnity "protection plan" and calling it "insurance" is a regulated-term violation that produced a real fine in New Mexico (`Heckart v. A-1 Self Storage`, Cal. 2018, ruled the plan is *not* insurance).
3. **Overstated security voids the lease.** `Dilbeck v. Yates` (GA 1992): an absolute security claim can void the facility's own liability-limiting lease clause as fraud. "Safe and secure" is not a slogan here, it is a liability.
4. **"Climate controlled" has no legal definition.** `DiSanto v. Safeco` (OH 2006): "climate-controlled" + "dry and safe" advertising survived summary judgment against the facility on reliance grounds.
5. **"First month free" is an FTC-governed offer.** 16 CFR 251.1 requires the conditions (admin fee, required protection, autopay, minimum term) "at the outset... in close conjunction with the offer," not in an asterisked footnote.

So while storage is E-E-A-T-light versus legal/medical, its lien/insurance/security/pricing machinery is heavy and concrete. This overlay makes storage's trust currency (real security specs, a real held climate range, honest fees, an honest lien timeline, a real protection-plan disclosure) provable by construction, and it stops the five ways storage copy crosses from "aggressive" into "regulator-exposed."

**Jurisdiction warning.** The Self-Service Storage Facility Act, the late-fee cap, the protection-plan-vs-insurance classification, the rate-disclosure duty, and the price-gouging rule are all STATE-LEVEL and vary widely. Statute text was verified this build for CALIFORNIA (Bus. & Prof. Code 21700-21716), TEXAS (Property Code ch. 59), and FLORIDA (Statutes ch. 83 Part III). Every state-dependent rule below is tagged **STATE-DEP**: the gate reads `brand.yaml.nap.state_region` (and `brand.yaml.storage.lien_statute`) and, where the client's state was not verified this build, flags the item for live confirmation against that state's statute rather than silently passing. Never apply the California numbers nationally.

---

## Trigger and inputs

- **Trigger:** `brand.yaml.vertical == self-storage`.
- **Required `brand.yaml.storage` fields:** `operator_type`, `unit_sizes[]`, `storage_types[]`, `live_inventory` (bool), `access_hours`, `office_hours`, `gate_access_24h` (bool), `climate_control` (`offered`, `temp_range_f`, `humidity_control`), `security_features[]` (`feature`, `spec`, `source`), `break_in_free_since`, `move_in_special` (`offer`, `admin_fee`, `required_add_ons`, `end_date`), `admin_fee`, `deposit_required`, `month_to_month`, `tenant_protection_type` (`protection_plan | licensed_insurance | none`), `insurance_license` (`number`, `state`), `rate_guarantee`, `advertised_late_fee`, `lien_statute`, `ada_verified`, `manager`. Plus `brand.yaml.nap.state_region` (the state the overlay branches on) and the generic `eeat.media[]`, `eeat.reviews[]`, `eeat.differentiators[]`.
- **Fail-closed rule.** If a page states a security spec, a climate range, a move-in special, a fee, a rate guarantee, a lien/auction timeline, an insurance/protection term, an accessibility claim, or a live unit count, and the backing `storage.*` field is empty, the overlay fails closed and routes to `sme-interviewer`. Never invent a camera count, a held temperature, a license number, an admin fee, or a break-in-free streak. An empty field is a missing-evidence flag, not a blank to fill (Law 16, G10; `research/self-storage-2026-07/06-eeat-experience.md`).

---

## Extra requirements per page type

| Page type | Self-storage-specific requirement added on top of the base playbook |
|---|---|
| Homepage / single-facility facility page | Real NAP + `access_hours` AND `office_hours` shown as two distinct clocks; security stack as concrete specs (SS-3), not "safe and secure"; a real held climate range where climate is offered (SS-5); the named manager (Experience marker 6); at least one dated first-party facility photo or a real dated proof counter; a truthful primary CTA (SS-CV). No absolute-security or "peace of mind" wallpaper. |
| Facility / location page (multi-facility) | Everything the homepage needs, per THIS building, from its `locations[]` entry: this building's own access/office hours, its own security spec, its own manager, its own unique "About This Facility" local block naming real nearby roads/landmarks (the doorway-defeating block). Live per-size price where `live_inventory`. |
| Unit-size page (`5x5`-`10x30`, city facet) | Real dimensions + derived sq ft/cu ft, a what-fits list in rooms-and-boxes, and REAL local inventory/price for that size at a real facility (SS-DOORWAY). A size-in-city facet with no real availability is a doorway (G3). Internally consistent capacity numbers (no "150-200 boxes" in the body and "80" in the FAQ). |
| Storage-type page (climate / drive-up / vehicle / business, city facet) | The honest definition with a number (climate control = the facility's REAL held range), the unregulated-term honesty lever (SS-5), and real local inventory of that type. No city-swap template body (the `storagekingusa.com` Dallas-vs-Tallahassee doorway pattern is the canonical fail). |
| About / team page | The named owner/manager with a dated, checkable history; the CSSM or state storage-insurance license where held; real founding year. No unshown "family owned since [year]" (the Polk County / A Family Storage fail). |
| Service-area / cities-served page | Real coverage only, granular real towns/landmarks, or a real facility directory. No city-link carpet fronting near-identical thin pages (SS-DOORWAY, G3). |
| Cost-guide / size-guide asset | Real, dated, sourced numbers (the client's own market data or a clearly-sourced original cut), never a recycled round-number range. Law 15 / Law 18. |
| Move-in-special / deal facet | The offer, the admin fee, and every still-payable item disclosed in-line (SS-6). A live, real offer with a real end date only (SS-CV, Law 20). |

Any page stating a security spec, a climate range, a fee, a promo, a rate claim, a lien/auction fact, an insurance/protection term, or an accessibility claim is a proof-bearing page: every such element must trace to `brand.yaml.storage` or the SME answers.

---

## Auto-fail additions (this overlay's new rules)

Each rule cites its base gate and its real authority. **AF** = auto-fail (blocks publish). **REQ** = a mandatory element is missing (block until added). **FLAG** = log in the report and hold for operator/state confirmation. STATE-DEP rules branch on `brand.yaml.nap.state_region`.

### Insurance and the protection-plan word trap (extends G12, G10)

**SS-1 - "Insurance" for a self-indemnity protection plan. AF (STATE-DEP).**
If `storage.tenant_protection_type == protection_plan`, the words "insurance," "insured," "coverage," "policy," or "premium" may NOT describe that plan. A self-indemnity protection plan is not insurance (`Heckart v. A-1 Self Storage`, Cal. 2018); calling it insurance is the exact regulated-term violation that drew a fine in New Mexico. Required framing: "protection plan," and where the client uses the industry disclosure, "the program is not an insurance policy and the provider is not an insurance company."
*Authority:* G12; `Heckart` (Cal. 2018); NM fine. https://www.insideselfstorage.com/self-storage-profit-centers/california-supreme-court-rules-self-storage-tenant-protection-plans-aren-t-subject-to-insurance-code

**SS-2 - "Insurance" without a license to sell it. AF (STATE-DEP).**
The word "insurance" is permitted only if `storage.tenant_protection_type == licensed_insurance` AND `storage.insurance_license.number` is present for the client's state. Tenant insurance is a state-regulated licensed product. A bare "we offer insurance" with no license backing fails as an unverifiable regulated claim (G10).
*Authority:* G10; G12; state insurance licensing (CA Ins. Code 1758.75 is the storage-agent-license archetype). https://www.insurance.ca.gov/0200-industry/0050-renew-license/0200-requirements/self-service-storage/

### Security-claim honesty (extends G12, G2, spine C-truthfulness)

**SS-3 - Absolute or unbacked security claims. AF.**
Banned patterns: "safe and secure," "your belongings are safe," "your stuff is protected," "100% secure," "guaranteed secure," "theft-proof," "totally safe," "completely secure," and the bare "secure storage" with no mechanism. An absolute security promise can void the facility's own liability-limiting lease clause as fraud (`Dilbeck v. Yates`, GA 1992). The only permitted security copy is the concrete, verifiable spec from `storage.security_features[]`: "24 recorded HD cameras," "individually alarmed units," "gated keypad with a per-tenant code logged on entry and exit," "perimeter fencing," "motion-activated LED lighting," "on-site resident manager." This is the mechanism-not-reassurance rule (`research/self-storage-2026-07/05-voice-language.md`): every security claim carries a spec or it is cut.
*Authority:* G12; G2; `Dilbeck v. Yates` (GA 1992, voided the lease liability cap for a false security representation); FTC truthful-claims standard. https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements

**SS-4 - Break-in / theft / fire history claims. AF.**
No claim about the facility's incident history unless it is a real, dated, tracked record in `storage.break_in_free_since` (rendered as an honest counter, e.g. "1,840 days without a break-in as of [date]"). Never write "we've never had a break-in," "nothing has ever been stolen here," or "no fires, ever." An unbacked clean-history claim is the exact `Dilbeck` fraud fact pattern (the manager told a tenant "no one had ever broken in" when break-ins had occurred; the court voided the lease defense). A real dated counter is Experience proof (marker 2); an asserted clean history is fraud exposure.
*Authority:* G12; G10; `Dilbeck v. Yates`. Same source as SS-3.

### Climate-controlled honesty (extends G10, G12)

**SS-5 - Bare "climate controlled" + moisture/dryness promise. AF unless humidity control is confirmed.**
"Climate controlled" has no legal or industry-standard definition. A page may pair "climate controlled" with "dry," "moisture-free," "prevents mold/mildew," "protects against moisture/humidity," or "keeps your items dry" ONLY if `storage.climate_control.humidity_control == true`. If the facility controls temperature only (`humidity_control: false`), require the honest term ("temperature controlled," "heated and cooled") and forbid the moisture/dryness promise. Any "climate controlled" claim must also state the real held range from `storage.climate_control.temp_range_f`; a bare feature-word with no number is thin (G1) and the honesty lever (stating your own range + that the term is unregulated) is a genuine information-gain win (Law 15). Reliance on an undefined "climate-controlled / dry and safe" claim kept a facility in court (`DiSanto v. Safeco`, OH 2006).
*Authority:* G10; G12; `DiSanto v. Safeco` (OH 2006); "climate controlled" is not a regulated term. https://www.storagepug.com/blog/climate-controlled-storage

### Move-in-special / "free" disclosure (extends G13, G12; FTC 16 CFR 251.1)

**SS-6 - "First month free" / "$1 move-in" / "50% off" without in-line conditions. AF.**
Any "free," "$1," or discount headline REQUIRES the still-payable conditions disclosed in-copy, in close conjunction with the offer, NOT in an asterisked footnote: the one-time admin fee (`storage.admin_fee`), any required protection-plan/insurance purchase, required autopay, and any minimum term. Never imply "$0 due at move-in" when an admin fee or required protection plan applies. 16 CFR 251.1 requires all terms "clearly and conspicuously at the outset... so as to leave no reasonable probability that the terms of the offer might be misunderstood." Conditions-in-footnote or omitted = AF.
*Authority:* G13; G12; FTC Guide Concerning Use of the Word "Free," 16 CFR 251.1. https://www.law.cornell.edu/cfr/text/16/251.1

**SS-7 - "Free"/discount against an inflated regular price. AF.**
A "free month" or "X% off" is truthful only against a bona-fide regular price (the rate openly and actively charged in the prior 30 days). Do not measure "free" against an inflated "regular rate" the facility does not actually charge. The saved/regular figure must trace to `brand.yaml`.
*Authority:* G12; 16 CFR 251.1 (regular price = openly sold prior 30 days). Same source as SS-6.

### Rate / ECRI honesty (extends G12, G13)

**SS-8 - "Rate locked" / "price never increases" on month-to-month. AF unless contractually guaranteed.**
"Rate locked," "price never goes up," "guaranteed rate for life," "no rate increases," and "your rate is fixed" are false for a standard month-to-month agreement subject to existing-customer rate increases (ECRI). Permit such a claim ONLY if `storage.rate_guarantee` states a real contractual guarantee, and then only in its exact terms (e.g. "no rate increase for your first 12 months, in writing"). A web/introductory rate may never be presented as permanent (in-place rates run 30-50% above web rates via ECRI).
*Authority:* G12; G13; FTC Act s.5 / state UDAP; ECRI reality. https://www.radiusplus.com/latest/what-in-the-self-storage-web-rates-is-going-on/

**SS-9 - Promotional/intro rate implying permanence. REQ (STATE-DEP).**
Copy advertising a promotional or introductory rate ("$29 to start," "intro rate") must not imply the rate is permanent; state the promo duration and that the rate is subject to change. For a California client with an agreement on/after 2026-01-01, the promo-duration and maximum-fee-in-first-12-months disclosure is a first-page legal requirement (SB 709, adds Bus. & Prof. s.21715.2, a disclosure law - it does NOT cap rates), and the marketing page must not contradict it.
*Authority:* G12; CA SB 709. https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202520260SB709

### Late fee, lien, and auction (extends G10, G12)

**SS-10 - Advertised late fee above the state cap. FLAG, and AF in CA if over the grid.**
Any late-fee figure in copy is a factual claim measured against the state cap. In California (Bus. & Prof. s.21713.5) the cap is a hard grid: $10 if monthly rent is $60 or less; $15 if rent is $60-100; the greater of $20 or 15% if rent is $100 or more, and only after rent is 10 days late. A "$25 late fee" advertised on a $90 CA unit exceeds the $15 ceiling = AF. Other states use a "reasonable" standard; FLAG any advertised late fee for state confirmation and never apply the CA numbers nationally.
*Authority:* G12; CA Bus. & Prof. s.21713.5. https://law.justia.com/codes/california/code-bpc/division-8/chapter-10/section-21713-5/

**SS-11 - A lien/auction timeline not from the client's state statute. FLAG (AF if it misstates the statute).**
Copy that states a specific lien/auction notice period, a number of notices, a publication schedule, or a tenant remedy ("we always give you 30 days," "we notify you three times," "you can't lose your unit without a court order") is a factual claim about the state Self-Service Storage Facility Act. It must trace to `storage.lien_statute` for the client's state and match it (14-day notice window in CA and TX; the "declaration in opposition" right and once-a-week-for-two-weeks publication in CA; two consecutive weekly insertions in TX and FL). Generic lien-timeline copy not pulled from the client's state act = FLAG; copy that softens or misstates the statutory process = AF (G10 fabricated legal fact).
*Authority:* G10; G12; state SSFA acts. CA https://law.justia.com/codes/california/2009/bpc/21700-21716.html ; TX https://texas.public.law/statutes/tex._prop._code_section_59.043 ; FL https://law.justia.com/codes/florida/title-vi/chapter-83/part-iii/section-83-806/

### Accessibility, emergency pricing, e-notice (extends G12)

**SS-12 - Unverified accessibility claims. AF unless verified.**
"ADA compliant," "fully accessible," "wheelchair accessible" are factual claims. Permit ONLY if `storage.ada_verified == true` (accessible office + path of travel; and, for a "fully accessible site" claim, the page itself meets WCAG). Do not conflate a ground-floor "drive-up" unit with ADA accessibility. Storage facilities are ADA Title III public accommodations and website-accessibility exposure is real (`Robles v. Domino's`, 9th Cir. 2019, circuit split).
*Authority:* G12; ADA Title III; `Robles v. Domino's`. https://www.mcafeetaft.com/appeals-courts-split-on-whether-websites-are-places-of-public-accommodation-under-ada/

**SS-13 - Emergency/disaster-zone "special rate" that raises price. FLAG (STATE-DEP).**
Post-disaster "storage after the fire/flood" campaigns that raise price in a declared-emergency zone hit state price-gouging caps (CA AB 380: no more than 10% for 180 days after a declaration). FLAG any emergency-zone special-rate copy for state confirmation.
*Authority:* G12; CA AB 380 / state price-gouging law. https://forgebuildings.com/new-2026-laws-every-self-storage-operator-should-know/

**SS-14 - "Paperless / we email all notices" implying automatic email lien notice. FLAG (STATE-DEP).**
Copy implying lien notices are sent by email automatically is state-exposed: CA AB 498 requires proof the occupant actually received/opened the email or the operator falls back to mail; TX requires the rental agreement to authorize email notice. FLAG "we email all your notices" / "paperless notifications" for state confirmation.
*Authority:* G12; CA AB 498; TX Prop. Code 59.043. Same forgebuildings source; TX https://texas.public.law/statutes/tex._prop._code_section_59.043

**SS-15 - Do NOT cite the FTC junk-fees rule or Click-to-Cancel as binding on storage. WRITER GUARDRAIL.**
The FTC "Rule on Unfair or Deceptive Fees" (16 CFR 464) covers only live-event tickets and short-term lodging, not storage. The FTC "Click-to-Cancel" / Negative Option Rule was vacated by the 8th Circuit on 2025-07-08 and is not in force. Do not cite either as binding on a storage page. Ground any fee-disclosure or cancellation rule in FTC Act s.5, the "Free" guide, and applicable state Automatic Renewal Laws (CA ARL, tightened 2025-07-01) instead. All-in pricing is directional best practice for storage, not a Part-464 mandate.
*Authority:* writer guardrail; 16 CFR 464 scope; Click-to-Cancel vacated. https://www.sidley.com/en/insights/newsupdates/2025/07/us-ftc-click-to-cancel-rule-struck-down

### Conversion truthfulness (extends G13, Law 20)

**SS-CV1 - Scarcity claim without a live PMS basis. AF.**
"Only N units left," "selling fast," "N units remaining," "almost gone" are permitted ONLY if `storage.live_inventory == true` and N is fed from real-time inventory. No hard-coded unit counts. The FTC's own illegal-scarcity example is "Only two left in stock" shown "when stock is plentiful." A real live "2 left at this price" is truthful and material; a hard-coded one is a dark pattern.
*Authority:* G13; Law 20; FTC "Bringing Dark Patterns to Light" (2022). https://www.ftc.gov/news-events/news/press-releases/2022/09/ftc-report-shows-rise-sophisticated-dark-patterns-designed-trick-trap-consumers

**SS-CV2 - Countdown timer that resets. AF.**
A countdown timer is permitted only if it targets a real, fixed, server-enforced end datetime that does not reset per visit or per session. Ban per-session and auto-resetting "sale ends in HH:MM:SS" timers outright (FTC fake-countdown dark pattern). A stated promo end date must be the real `storage.move_in_special.end_date`, never a rolling "ends soon" / "today only" that is not literally true.
*Authority:* G13; Law 20; FTC dark-patterns report. Same source as SS-CV1.

**SS-CV3 - Web rate presented as locked/permanent, or a checkout price that differs from the page. AF.**
A web/introductory rate is never presented as a locked or permanent price (see SS-8). The price and promo shown on the page must equal the price at checkout; a "$0 first month" that becomes "$50 at checkout" is both a conversion killer and a truthfulness failure. The one primary CTA must match page intent (rent-online for urgent, reserve-free for planned) with click-to-call always one tap away on mobile; reservation copy must stay honest (a free, no-card, no-obligation hold, not a confirmed rental).
*Authority:* G13; Law 20. https://www.storagepug.com/blog/reducing-friction-online-rentals

### Schema honesty (extends G11)

**SS-SCHEMA1 - Self-serving review stars on the facility/brand node. AF.**
No `aggregateRating` or `review` on the `SelfStorage`/`Organization` node about the facility's own reviews. Since 2019 Google does not render stars when the entity controls the reviews about itself, and marking them up risks a misleading-markup manual action. `SelfStorage` is a `LocalBusiness`/`Organization` subtype, squarely inside the wall. Reviews live on the visible page and in the GBP, never in self-node schema. (This is `schema_validator.py`'s existing D3 check; it fires on `SelfStorage` because `SelfStorage` is in the LocalBusiness set.)
*Authority:* G11; Google review-snippet doc (self-serving rule). https://developers.google.com/search/docs/appearance/structured-data/review-snippet

**SS-SCHEMA2 - Fabricated availability, mislabeled rental, or 24h-gate-as-office-hours. AF.**
`Product`/`Offer` unit markup is permitted only when a real, current price is on the page and `storage.live_inventory == true` (or a dated static rate that matches the visible copy); `availability` must reflect true inventory and the `Offer` must carry `businessFunction: LeaseOut` (a rental, not a sale). Office hours map to `openingHoursSpecification`; 24-hour gate access is expressed via `amenityFeature` ("24-hour gate access", value from `storage.gate_access_24h`), NEVER as `opens:00:00 / closes:23:59` on the office spec. `amenityFeature` and `priceRange` must not contradict visible copy; `areaServed` must match the real service-area copy (no inflated city list).
*Authority:* G11; Google structured-data policies + merchant-listing doc. https://developers.google.com/search/docs/appearance/structured-data/sd-policies

### The storage doorway line (extends G3)

**SS-DOORWAY - Axis page without a real local specific. AF.**
A facility, city-level unit-size, city-level storage-type, or per-city service-area page must carry a real first-party specific that page alone owns: this facility's real address + unique local block (named nearby roads/landmarks), real live inventory/price for this size/type at a real facility, this building's real security spec or held climate range. The canonical fail is the verified live doorway pair `storagekingusa.com/locations/texas/dallas/climate-controlled/` vs `.../florida/tallahassee/climate-controlled/`: one skeleton, one city-agnostic sentence ("Several common household items are sensitive to extreme temperatures..."), differing only by the swapped city noun. Run `scripts/duplication_gate.py` across sibling facility/size/type pages; a pair at or above threshold, or a page that survives the strip-the-city paste test, fails. For a single-facility client, do not generate separate size/type/audience pages at all - they collapse into the one facility page (`storage.operator_type == single_facility`).
*Authority:* G3; Google doorway + scaled-content-abuse policy. https://developers.google.com/search/docs/essentials/spam-policies

---

## How `compliance-auditor` enforces this overlay

Add to the GATE stage when `vertical == self-storage`:

1. **Load the overlay;** read `brand.yaml.storage.*`, `nap.state_region`, and `eeat.*`. Set `state = nap.state_region`. If `state` is one of the build-verified states (CA/TX/FL), apply its specific numbers; otherwise, for every STATE-DEP rule, FLAG for live statute confirmation and do not silently pass.
2. **SS-1/SS-2 insurance check:** grep "insurance / insured / coverage / policy / premium." If `tenant_protection_type == protection_plan`, any hit describing the plan = AF. If `licensed_insurance`, require `insurance_license.number`; missing = AF. Deterministic scan lives in `scripts/storage_lint.py` (run with `--protection-type` or `--brand`).
3. **SS-3/SS-4 security scan:** banned-pattern scan for "safe and secure / your belongings are safe / protected / theft-proof / 100% secure / guaranteed secure / secure storage (bare) / never had a break-in / nothing stolen." Any hit = AF unless it is a concrete spec from `security_features[]` or a dated counter from `break_in_free_since`. Run `scripts/storage_lint.py`.
4. **SS-5 climate check:** for every "climate controlled" + moisture/dryness pairing, require `climate_control.humidity_control == true`; else AF and route to the honest term. Require a real held range on any climate claim.
5. **SS-6/SS-7 "free" check:** for every "free / $1 / % off" headline, confirm the admin fee + required add-ons are disclosed in-line (not footnote) and the regular price is bona-fide. Run `scripts/storage_lint.py`. Missing/footnoted = AF.
6. **SS-8/SS-9 rate check:** grep "rate locked / price never / guaranteed rate / no rate increase / fixed rate"; permit only against a real `rate_guarantee`. For CA post-2026 promo copy, confirm the SB 709 disclosure is not contradicted.
7. **SS-10 late-fee check:** if a late fee appears, compare to the state cap (CA grid hard-checked; else FLAG).
8. **SS-11 lien check:** any lien/auction timeline must trace to `storage.lien_statute`; generic = FLAG, statute-softening = AF.
9. **SS-12/SS-13/SS-14 checks:** accessibility claim requires `ada_verified`; emergency-zone rate copy = FLAG; "paperless notices" = FLAG.
10. **SS-CV1/2/3 conversion checks:** run `scripts/conversion_linter.py` + `scripts/storage_lint.py` for hard-coded scarcity, resetting timers, and page-vs-checkout price consistency; permit scarcity only if `live_inventory == true`.
11. **SS-SCHEMA1/2 checks:** run `scripts/schema_validator.py` (D3 self-review fires on `SelfStorage`; plus the storage checks) - no self-serving review, `LeaseOut` on unit Offers, gate-access as `amenityFeature` not office hours, `availability` backed by real inventory.
12. **SS-DOORWAY check:** run `scripts/duplication_gate.py` across sibling axis pages; apply the strip-the-city paste test; single-facility clients get no separate axis pages.
13. **Record each SS rule** in a "Vertical overlay: self-storage" section of `compliance-report.md`, AF/REQ/FLAG with evidence, and note every STATE-DEP item whose state was not verified live.

Any SS **AF** blocks publish exactly like a base AF gate. The `conversion-optimizer` runs the SS-CV checks at CONVERT (one step upstream) and `compliance-auditor` re-confirms them.

---

## The sharpest rule for this vertical

**SS-3: no "safe and secure" without the mechanism, because in storage the security slogan is a legal liability, not just a weak trust signal.** "Clean, safe and secure" is the single most-repeated line in self-storage copy and the one that reads as template AI slop to a human, pattern-matches to the exact facilities that got renters robbed, AND can void the facility's own liability-limiting lease clause as fraud (`Dilbeck v. Yates`). The overlay converts it into a claim that must resolve to a real spec in `storage.security_features[]`: "24 recorded HD cameras, individually alarmed units, a per-tenant gate code logged on entry and exit, an on-site manager who cuts the lights at 10pm." This is the storage lane's equivalent of the plumber's license number and the lawyer's results disclaimer: the concrete, checkable proof that converts a slogan into a trust asset and out of a lawsuit. It is also the whole moat (Law 16): only this facility can truthfully write the specific version, because only this facility has those cameras.

---

## Sources (verified this build 2026-07-23 PKT; re-verify quarterly and against the client's state statute)

- `Heckart v. A-1 Self Storage` (Cal. 2018, protection plan is not insurance): https://www.insideselfstorage.com/self-storage-profit-centers/california-supreme-court-rules-self-storage-tenant-protection-plans-aren-t-subject-to-insurance-code
- `Dilbeck v. Yates` (GA 1992) + `DiSanto v. Safeco` (OH 2006), advertising that voided lease defenses: https://www.insideselfstorage.com/legal-issues/self-storage-facility-advertising-avoiding-the-liability-caused-by-misleading-statements
- FTC "Free" guide, 16 CFR 251.1: https://www.law.cornell.edu/cfr/text/16/251.1
- FTC dark-patterns report "Bringing Dark Patterns to Light" (2022): https://www.ftc.gov/news-events/news/press-releases/2022/09/ftc-report-shows-rise-sophisticated-dark-patterns-designed-trick-trap-consumers
- CA Bus. & Prof. Code 21700-21716 (lien/auction) + 21713.5 (late-fee cap): https://law.justia.com/codes/california/2009/bpc/21700-21716.html ; https://law.justia.com/codes/california/code-bpc/division-8/chapter-10/section-21713-5/
- TX Property Code ch. 59 (lien): https://texas.public.law/statutes/tex._prop._code_section_59.043
- FL Statutes ch. 83 Part III s.83.806 (lien sale): https://law.justia.com/codes/florida/title-vi/chapter-83/part-iii/section-83-806/
- CA SB 709 (rate-disclosure, no cap): https://leginfo.legislature.ca.gov/faces/billTextClient.xhtml?bill_id=202520260SB709
- CA storage-agent insurance license (Ins. Code 1758.75): https://www.insurance.ca.gov/0200-industry/0050-renew-license/0200-requirements/self-service-storage/
- Google review-snippet self-serving rule + SD policies: https://developers.google.com/search/docs/appearance/structured-data/review-snippet ; https://developers.google.com/search/docs/appearance/structured-data/sd-policies
- Google doorway + scaled-content-abuse policy: https://developers.google.com/search/docs/essentials/spam-policies
- Internal: `research/self-storage-2026-07/` (dossiers 03 schema, 04 conversion, 05 voice, 06 E-E-A-T, 07 compliance, 08 teardowns, 00 master); `knowledge/quality-gates/gates.md` (G2, G3, G10, G11, G12, G13); `knowledge/doctrine/local-content-laws.md` (Law 16, Law 20); `knowledge/verticals/home-services.md` (the overlay-format template).

*The Self-Service Storage Facility Act, late-fee cap, protection-plan classification, rate-disclosure duty, and price-gouging rule are state-level and vary widely; CA/TX/FL were read to statute this build, the rest are the industry pattern. State-dependent items are flagged inline. Confirm the client's state statute live before publishing any close-to-the-line lien, late-fee, insurance, or rate claim.*
