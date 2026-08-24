# E-E-A-T Framework for Local Service Businesses

Google's December 2025 Helpful Content / Core Update pushed E-E-A-T (Experience, Expertise, Authoritativeness, Trust) scoring beyond YMYL into all competitive queries. Local service queries are competitive queries. A plumber's "emergency plumber Tempe" page is now scored on the same four pillars a health site is, and Trust is the load-bearing pillar (Google states verbatim that of the four, "trust is most important").

This file translates the four pillars into the concrete on-page markers a local service page must carry, where each marker is pulled from, and the minimum count per page type. It is method-agnostic per Doctrine Law 8: Google punishes scaled low-value content, not AI provenance. AI-detector score has ~zero correlation with rankings. So this framework never launders text through a humanizer or chases a detector score. It wins the only way that survives a core update: by putting real, verifiable, business-specific facts on the page that a competitor cannot copy because they do not have them.

The 2026 pillar priority order is **Experience > Expertise > Authoritativeness > Trust in weight of the differentiating signal, with Trust as the dominant gate.** Experience is the hardest signal for a scaled content operation to fabricate, which is exactly why it now carries the most differentiating weight. Trust is the one that, if failed, caps the page regardless of the other three.

---

## The one contrast that governs every pillar: claimed vs shown

Every pillar has a dead version (claimed) and a live version (shown). The dead version is a generic adjective. The live version is a specific, checkable fact that only this business, in this city, could put on the page.

| Pillar | Claimed (dead, banned) | Shown (live, required) |
|---|---|---|
| Experience | "We have years of experience with water heaters." | "We replaced 214 water heaters across Tempe and Chandler in 2025; the most common failure we see in Tempe's hard-water zip codes (85281, 85282) is anode-rod corrosion inside 6 years." |
| Expertise | "Our expert electricians handle any job." | "Panel upgrades in homes built before 1990 in Mesa usually mean replacing a 100-amp Zinsco or Federal Pacific panel, both flagged as fire risks by insurers, with a 200-amp service; permit pulled through the City of Mesa, inspection scheduled inside 5 business days." |
| Authoritativeness | "We are the #1 trusted electrician in Mesa." | "Licensed by the Arizona ROC, license ROC-######, Class CR-11 Electrical. Member, Arizona Chapter IEC. 5.0 across 187 Google reviews. Featured on the City of Mesa approved-contractor list." |
| Trust | "Trusted by thousands. 100% satisfaction guaranteed." | "Licensed, bonded ($X surety), and insured ($2M general liability, certificate available on request). Upfront flat-rate pricing, quoted before work starts. 10-year workmanship warranty on panel installs. Owner: Jane Doe, reachable at the number below." |

The rule: **if a competitor in the next city could paste your sentence onto their own page without it becoming false, it is a claimed sentence and it is worthless.** Every marker below is a fact that would become false on a competitor's page. That is the test.

Nothing on this table is invented at write time. Each fact is pulled from `clients/<client>/brand.yaml` or surfaced by the SME interview. If a fact is not in the profile and the operator cannot confirm it, it does not go on the page. A fabricated local specific (a made-up license number, an invented review count, a fictional completed job) is the single fastest path to a trust penalty and, for a licensed trade, a real-world liability. Never fabricate to hit a minimum count. If the facts are not there, the fix is a better SME interview, not a better adjective.

---

## Pillar 1: Experience (highest differentiating weight)

**What it means for a local service business:** proof that this specific crew has physically done this specific work, in this specific service area, many times. Not competence in the abstract. Jobs completed, on real streets, with real outcomes.

**What it does NOT mean:** "family-owned since 1998," "years of combined experience," "we pride ourselves on quality." Those are claimed, not shown, and in 2026 they carry zero signal.

### On-page marker types that prove Experience

1. **Completed-job reference with a location.** A real project tied to a neighborhood, subdivision, or zip: "Repiped a 1970s slab-foundation home in the Warner Ranch neighborhood of Chandler last spring." Pulled from the SME interview (recent jobs) or `brand.yaml: projects[]`.
2. **Before/after with original photos.** The crew's own photos of a real job, not stock. Caption with the location and the problem solved. Original media is the cleanest experience signal because it is hard to fake at scale. Pulled from `brand.yaml: media` or requested in the SME interview.
3. **Local failure-pattern observation.** A pattern only someone who works this territory would know: "In Tempe's older 85281 homes we see galvanized supply lines corroding at the 40-to-50-year mark; in the newer Chandler builds it is almost always a failed pressure-reducing valve instead." Pulled from the SME interview.
4. **Volume/count over a stated window.** "214 water heater replacements across the East Valley in 2025." Real number, real window. Pulled from `brand.yaml: stats` or the SME interview.
5. **Local-condition specificity.** Climate, soil, water, code quirks the operator handles daily: "Phoenix hard water (17+ grains) means Tempe tankless units need descaling every 12 months, not the 24 the manual claims." Pulled from the SME interview.
6. **First-person job anecdote from the owner or a named tech.** "Got a call at 11pm from a homeowner off Baseline Road with sewage backing up into a downstairs bathroom; the cleanout was buried under a patio addition the previous owner poured over it." Pulled from the SME interview, ideally verbatim.

The experience marker is not decoration. It is what makes the page impossible to templatize across cities, which is exactly what separates a genuine service-city page from a doorway page (banned by the doctrine and by Google's spam policy).

### Worked example (licensed electrician, Mesa AZ)

> Weak (claimed): "With years of experience serving Mesa homeowners, we handle all your electrical needs."
>
> Strong (shown): "Roughly a third of the panel jobs we run in Mesa are Federal Pacific Stab-Lok or Zinsco panels in homes built between 1965 and 1985, mostly in the Dobson Ranch and Alta Mesa areas. Both brands are on the insurers' known-hazard list. Last month we swapped a 100-amp FPE panel in a Dobson Ranch ranch house for a 200-amp Square D QO, pulled the permit through Mesa's online portal, and passed inspection on the first visit. Before/after below."

Experience signal: real brands (FPE, Zinsco, Square D QO), real neighborhoods (Dobson Ranch, Alta Mesa), real build-year window, real permit path (Mesa portal), real recent job with photos.

---

## Pillar 2: Expertise

**What it means for a local service business:** demonstrable, technical knowledge of how the work actually gets done, at a depth only a licensed practitioner would have. Named parts, real code, real diagnostic logic, real tradeoffs.

**What it does NOT mean:** a generic explanation of the service copied from any competitor's site or an AI's default answer. "We fix leaks fast" is not expertise.

### On-page marker types that prove Expertise

1. **Named part, brand, or spec.** Not "a new panel," but "a 200-amp Square D QO panel." Not "a good water heater," but "a Bradford White 50-gallon with a 6-year tank warranty." Pulled from the SME interview.
2. **Code, permit, or licensing citation.** The actual local authority and requirement: "Permit required through the City of Tempe; NEC 210.12 requires AFCI protection on the branch circuits we replace." Pulled from the SME interview / live research on the local building department.
3. **Diagnostic or decision logic.** How the operator decides between options: "If the drain clears with a cable but backs up again inside a week, the next step is a camera inspection, not another cabling; repeat cabling on a bellied line is money wasted." Pulled from the SME interview.
4. **Real threshold, dimension, or measurement.** "Water pressure above 80 psi voids most fixture warranties; Tempe's municipal supply runs 65 to 85 psi depending on elevation, which is why we install a PRV on most jobs east of Rural Road." Pulled from the SME interview.
5. **Correctly used trade vocabulary.** Terms that signal fluency: PRV, anode rod, AFCI, cleanout, slab leak, load calculation, ROC class. Used correctly, not stuffed.
6. **Tradeoff stated honestly.** "Tankless saves space and runs endless hot water but costs more upfront and needs annual descaling in our hard water; for a family of two in a small condo the payback rarely justifies it." Pulled from the SME interview.

Expertise markers do the ranking and citation work. An AI answer engine cites the page that explains the mechanism, not the page that asserts the outcome.

### Worked example (licensed electrician, Mesa AZ)

> Weak (claimed): "We install high-quality panels that keep your home safe."
>
> Strong (shown): "A 200-amp service is the right call for most Mesa homes adding a heat pump, an EV charger (a Level 2 charger pulls 40 to 48 amps continuous), or a casita. We run a load calculation to NEC Article 220 before quoting; if the existing 100-amp service is already above 80% load, the upgrade is not optional, it is code. Panels we standardize on: Square D QO and Eaton BR, both with readily stocked breakers so a future repair is not a special order."

Expertise signal: real amperage math, real EV-charger draw, real NEC article, real named panels with a stated reason.

---

## Pillar 3: Authoritativeness

**What it means for a local service business:** external, verifiable recognition that this business is a legitimate, licensed, established operator in this market. Not self-claimed superlatives, but credentials a third party issued and a reader can check.

**What it does NOT mean:** "the #1 plumber in town," "the most trusted name in HVAC." Self-awarded titles are banned by the doctrine (no unverifiable superlatives) and read as noise by the models.

### On-page marker types that prove Authoritativeness

1. **License number with issuing authority.** "Arizona ROC ####### (Class CR-11)." Verifiable on the state registrar's site. Pulled from `brand.yaml: license`.
2. **Certifications and manufacturer credentials.** "NATE-certified technicians," "Bradford White authorized installer," "EPA 608 certified." Pulled from `brand.yaml: certifications[]`.
3. **Trade-association membership.** IEC, PHCC, ACCA, state or county contractor associations. Pulled from `brand.yaml: associations[]`.
4. **Google review count and rating, stated as a number.** "5.0 across 187 Google reviews" beats "highly rated." The count is the authority; pull the live number from the Google Business Profile at write time and record it in `brand.yaml: reviews`.
5. **Years in business tied to a foundable date.** "Serving the East Valley since 2009" is only authoritative if the date is real and consistent with the license record and GBP. Pulled from `brand.yaml: founded`.
6. **Awards, media, or civic recognition (real only).** "On the City of Mesa approved-contractor list," "Best of the East Valley 2024 (Tribune readers' poll)." Pulled from `brand.yaml: awards[]`. If it cannot be linked or verified, it does not go on the page.
7. **Named owner or lead tech as an entity.** A real person with a name, role, and (on the about page) a bio and photo, corroborated by Person schema and, where it exists, a LinkedIn or license-lookup `sameAs`. An operator with a real named human outranks a faceless "the team" for trust.

### Worked example (licensed electrician, Mesa AZ)

> Weak (claimed): "Mesa's most trusted and highest-rated electrician, number one for a reason."
>
> Strong (shown): "Licensed by the Arizona Registrar of Contractors, ROC-###### (Class CR-11, Residential Electrical), bonded and insured. Independent Electrical Contractors (IEC) Arizona chapter member. 5.0 across 187 verified Google reviews. Owner Jane Doe has held an Arizona electrical license since 2011."

Authoritativeness signal: checkable license number and class, named association, real review count, named owner with a licensing date a reader could verify at the registrar.

---

## Pillar 4: Trust (the dominant, load-bearing pillar)

**What it means for a local service business:** the reader and the search engine both have concrete reasons to believe the business is real, reachable, accountable, and will not cheat them. Trust is the gate. A page can be rich in the other three pillars and still be capped if it fails trust.

**What it does NOT mean:** trust badges, "100% satisfaction guaranteed," stock "trusted by thousands" banners, an SSL padlock. Decorative trust signals are dead.

### On-page marker types that prove Trust

1. **Consistent, complete NAP.** Exact business name, real physical or service-area address, local phone. Must match the Google Business Profile and every citation character for character (see the NAP-consistency foundation). Inconsistent NAP is a direct trust downgrade. Pulled from `brand.yaml: nap`.
2. **License, bonding, and insurance stated together.** "Licensed (ROC-######), bonded, and insured ($2M general liability; certificate on request)." Pulled from `brand.yaml: license`, `bond`, `insurance`.
3. **Transparent, real pricing posture.** Flat-rate or "quoted before work starts, no surprise charges," with real numbers where the operator will commit to them. No "starting at $X" bait. Pulled from the SME interview.
4. **Honest limitation or scope boundary.** "We do not do commercial three-phase work; for that we refer you to [partner]." Recommending against yourself where honest is a strong trust signal. Pulled from the SME interview.
5. **Real guarantee/warranty with terms.** "10-year workmanship warranty on panel installs; manufacturer warranty on parts." Specific, not "satisfaction guaranteed." Pulled from `brand.yaml: warranty`.
6. **Genuine reviews with attribution.** Real quoted Google reviews with the reviewer's first name and, ideally, the job type and neighborhood, matching what is publicly visible on the GBP. Never fabricated. Pulled from `brand.yaml: reviews` / live GBP.
7. **Reachability and accountability.** Named owner, a real phone answered by a human, service hours, response-time commitment for emergencies. Pulled from `brand.yaml`.
8. **Schema corroboration.** LocalBusiness (correct subtype), Person (owner/author on the about page), and review/aggregateRating markup that matches the visible on-page facts exactly. Schema is hygiene, not a ranking lever on its own, but a mismatch between schema and visible content is a trust flag. See the schema-library foundation.

### Worked example (licensed electrician, Mesa AZ)

> Weak (claimed): "100% satisfaction guaranteed. Trusted by thousands of happy customers!"
>
> Strong (shown): "Flat-rate pricing quoted in writing before we start, so the number you approve is the number you pay. Licensed (ROC-######), bonded, and insured; certificate of insurance available on request. 10-year workmanship warranty on every panel install. We do residential only; if you need commercial three-phase, we will point you to a licensed commercial shop rather than take a job outside our lane. Call Jane or the crew at (480) ###-#### 7am to 6pm, Monday to Saturday."

Trust signal: pricing transparency, license/bond/insurance, specific warranty, honest scope boundary, named human, real hours and number.

---

## Minimum marker counts per page type

The about page carries the heaviest E-E-A-T load in the system: it is the trust surface the whole site leans on and the page QRG raters and answer engines check to answer "who made this." Service-city (the money page) and location pages need the heaviest **local** proof, because their whole job is to prove this business genuinely serves this city. Homepage anchors the entity and must carry the headline credentials. Service and service-area pages carry a lighter but still mandatory load.

Counts are minimums, not targets. More real markers is always better; the ceiling is only the supply of true facts.

| Page type | Experience | Expertise | Authoritativeness | Trust | Notes |
|---|---|---|---|---|---|
| About page | 3 | 2 | 4 | 4 | Heaviest load. Owner/team bios + photos, founding story with real dates, full credential stack, Person schema. |
| Service-city combo (money page) | 3 local | 3 | 2 (1 local) | 3 | Heaviest **local** proof: completed jobs in that city, local failure patterns, local code/permit path, city-specific reviews. |
| Location / city page | 3 local | 2 | 2 (1 local) | 3 | Local jobs, neighborhoods served, local conditions; not a templated near-duplicate of another city. |
| Service page (brand-wide) | 2 | 3 | 2 | 3 | Expertise-led: the mechanics of the service; experience across the whole service area. |
| Homepage | 2 | 1 | 3 | 4 | Entity anchor: headline credentials, review count, NAP, license, named owner, primary trust posture. |
| Service-area page | 2 | 1 | 2 | 3 | Real coverage proof (jobs across the named areas), not a doorway list of city names. |

Reading the table: a service-city page needs at least 3 experience markers that are specific to that city (a job in that city, a local failure pattern, a local condition), at least 3 expertise markers, at least 2 authoritativeness markers of which at least 1 is local (a city-specific review or a local-authority recognition), and at least 3 trust markers.

If a page cannot hit its minimums from real facts, it is not ready to publish. Escalate to a deeper SME interview or, for a location/service-area page with genuinely no unique local substance, question whether that page should exist at all (a page with nothing true and unique to say about a city is a doorway page; do not manufacture one).

---

## Where every marker comes from (source map)

No marker is invented at the keyboard. Each traces to a field in `brand.yaml` or an answer from the SME interview or live research. This is the anti-fabrication contract.

| Marker type | Primary source | Fallback |
|---|---|---|
| Completed jobs, neighborhoods, addresses | SME interview | `brand.yaml: projects[]` |
| Before/after and original photos | `brand.yaml: media` | SME interview request |
| Local failure patterns, conditions | SME interview | (none - do not invent) |
| Volume/counts over a window | `brand.yaml: stats` | SME interview |
| Named parts, brands, specs | SME interview | `brand.yaml: standard_equipment` |
| Code / permit / licensing detail | SME interview + live research on the local building dept | (verify, do not guess) |
| License number and class | `brand.yaml: license` | verify on state registrar |
| Certifications, associations, awards | `brand.yaml: certifications[]`, `associations[]`, `awards[]` | SME interview |
| Google review count, rating, quotes | live GBP at write time | `brand.yaml: reviews` |
| Years in business / founding date | `brand.yaml: founded` | verify against license + GBP |
| NAP | `brand.yaml: nap` | GBP (must match) |
| Bond / insurance | `brand.yaml: bond`, `insurance` | SME interview |
| Pricing posture, guarantee, warranty | SME interview | `brand.yaml: warranty`, `pricing` |
| Owner / tech names, roles, bios | `brand.yaml: team[]` | SME interview |
| Honest limitations / scope boundaries | SME interview | (none) |

If a field is empty in `brand.yaml` and the SME interview did not fill it, the marker does not exist yet. Write around it or go get the fact. Never fill the gap with a plausible-sounding invention.

---

## The E-E-A-T pass (run at the GATE stage)

Before any page passes the quality gate:

1. Count Experience markers against the page-type minimum; at least one should be verbatim or near-verbatim from the SME interview.
2. Count Expertise markers against the minimum.
3. Count Authoritativeness markers; confirm at least the required local ones on location and service-city pages.
4. Count Trust markers; confirm NAP matches the GBP exactly and license/insurance are present.
5. Scan for claimed-not-shown language: any generic superlative, "years of experience," "trusted by thousands," "#1," "satisfaction guaranteed," or any sentence that would remain true if pasted on a competitor's page. Each one is a fail; rewrite it into a shown marker or cut it.
6. Confirm every specific fact traces to `brand.yaml` or the SME interview or cited live research. Any fact with no source is a fabrication risk; remove it or source it.

A failed count returns a specific error naming the missing marker type and the section that needs it. Regenerate that section against real facts; do not paper over a missing fact with a better adjective. Max two retries, then flag for the operator to supply the missing fact.

That is the bar: every pillar shown, never claimed, every specific true and sourced, counts met from real substance the competitor down the road does not have.
