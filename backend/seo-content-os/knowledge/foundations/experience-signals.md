# Experience Signals - the provable-artifact catalog

This is the canonical catalog of **provable first-hand Experience markers** for a local service business. It operationalizes doctrine **Law 16** (Experience must be proven, not asserted) and is the reference that the `sme-interviewer` harvest, the `eeat-framework.md` Experience pillar, and `experience_gate.py` all resolve to. Where `eeat-framework.md` covers all four E-E-A-T pillars, this file is the deep layer on the first E only: for each marker type, exactly what artifact proves it, which `brand.yaml` field or SME question supplies it, and the deterministic **PASS test** that certifies it is real and not asserted.

## Why Experience is the whole moat

Experience is the first E of E-E-A-T and the one ranking-and-trust signal no competitor and no model can scrape, remix, or synthesize, because it lives only in the operator until someone extracts it. Every commercial AI content tool (Byword, Koala, Surfer, Jasper, Cuppa) sources from the SERP or the model's parametric memory, so none can manufacture it (research file 05). Our SME harvest is the only mechanism in the category that produces it on purpose. That is not a feature; it is the moat, and this catalog is how we keep it real.

Google's own guidance is explicit. From "Creating helpful, reliable, people-first content," the self-assessment question is verbatim:

> "Does your content clearly demonstrate first-hand expertise and a depth of knowledge (for example, expertise that comes from having actually used a product or service, or visiting a place)?"

and the framing to evaluate any page is **Who** created it, **How** it was produced, and **Why** it exists.
- Primary: https://developers.google.com/search/docs/fundamentals/creating-helpful-content

The Quality Rater Guidelines (the 182-page manual Google's human raters use, September 11 2025 revision) elevate this first-hand Experience to the most differentiating signal: raters are told to reward original photos, first-party data, and specific dated results, and to mark "purely AI-generated content without human review and unique value" as Lowest quality. The classification is about value and provenance-of-effort, not about whether a machine touched the text.
- Primary: https://guidelines.raterhub.com/searchqualityevaluatorguidelines.pdf (canonical PDF; Experience characterizations corroborated via secondary summaries, not a full-PDF read this session)
- Secondary summaries: https://theguidex.com/google-quality-rater-guidelines-summary/ ; https://www.seroundtable.com/google-search-quality-raters-guidelines-update-40092.html

## The provability principle (claimed vs proven)

Law 16 in one line: **every falsifiable Experience claim resolves to a dated, externally checkable first-party artifact, or it is cut.** An Experience claim has two states:

- **Asserted (dead, banned):** a generic adjective a competitor in the next city could paste onto their page without it becoming false. "Family-owned since 1998." "Years of experience." "Trusted by thousands."
- **Proven (live, required):** a specific fact backed by an artifact that would become false on a competitor's page. "214 water-heater replacements across the East Valley in 2025, invoices on file." "ROC-######, Class CR-11." "Before/after photo of the Dobson Ranch panel swap, March 2026."

The governing test for every marker below: **if the sentence stays true when pasted on a competitor's site, it is asserted, and it fails.** This is the same test G1 (first-hand specificity) applies at the section level and G10 (source resolution, no fabricated facts) applies at the fact level. This catalog is what makes both gates enforceable rather than vibes.

## How this ties to the gates

- **G1 - First-hand specificity (auto-fail).** A marker that is genuinely first-hand and locally specific is what G1 scans for. A page whose Experience markers survive the find-and-replace test (re-point to any city or competitor and it breaks) passes G1 on this axis. Markers 1, 6, and 7 below are the primary G1 carriers.
- **G10 - Source resolution, no fabricated facts (auto-fail).** Every marker here is falsifiable, so every marker must trace to a real artifact (`brand.yaml`, a tagged SME answer, or cited live research) recorded in `sources.md`. An Experience claim with no proving artifact is treated as fabricated and fails G10. Markers 4 and 5 (numbers and credentials) are the primary G10 carriers because they are the most tempting to round-number-invent.
- The provable-artifact requirement is what lets a future `scripts/experience_gate.py` mechanically certify a draft: named author present, at least one dated specific, at least one SME-tagged fact in `sources.md`, and no numeric or credential claim without a recorded source. That script does not exist yet; this catalog is its specification.

---

## The seven marker types

Each marker: **what it is**, **how it proves Experience** (tied to the QRG / helpful-content guidance), the **source** (`brand.yaml` field plus the SME harvest question that produces it), and the **PASS test** (what a gate checks to certify it real).

Source note: the current `clients/_template/brand.yaml` stores the free-text Experience assets under `eeat.credentials`, `eeat.team`, `eeat.proof`, and `eeat.differentiators` (plus `client.founded_year`, `service_areas`, `schema.price_range`, and `schema.same_as`), and it now also carries structured Experience arrays: `eeat.media` (`{url, caption, geotag, date}` - original job photos with a capture date), `eeat.reviews` (`{platform, count, rating, profile_url}`), and the vertical credential arrays (`eeat.attorneys` with `bar_number`, `eeat.providers` with `license_number`, `eeat.license_bond_insurance` with `license_number`, and `eeat.warranties`). Map each marker to those real fields first. Only artifact types with no structured home yet (for example an invoice-backed job count tied to its record) remain **proposed**, and those are labeled as such; do not assume a proposed field exists until the template is extended.

### 1. Original photos of real jobs

**What it is.** The crew's own photographs of a real job this business did: a finished install, the crew on site, a tricky repair mid-fix, the truck at a recognizable local spot. Captioned with the real location and the problem solved. Never stock, never AI-generated, never a manufacturer's product shot.

**How it proves Experience.** Original media is the single cleanest Experience artifact the QRG rewards, because it is the hardest thing for a scaled or SERP-remix operation to fake at volume - it requires having physically been on the job. It is the most direct possible answer to Google's "actually used a product or service, or visiting a place." A geotagged original photo answers Who, How, and Why in one asset.

**Source.**
- `brand.yaml`: `eeat.proof` (free-text today); **proposed** structured field `eeat.media[]` as `{ref, caption, city, job_type, date, geotag}`.
- SME question (harvest category 3): "What real photos do you already have on your phone for this kind of work - a finished job, the crew on site, a tricky repair, the truck at a recognizable local spot? List what exists; we place them and caption them with the real job." Geotag to `nap.geo` where the phone kept location.

**PASS test.** Every image reference on the page resolves to a real first-party asset listed in `sources.md` with a caption tying it to a real job and location. Any image that is stock, generic, or unattributed fails (it is not Experience). Alt text and caption name the real place/job, not a keyword string (a keyword-stuffed alt also trips G5). No original asset = this marker is absent, not "close enough."

### 2. Dated results and case data

**What it is.** A specific job with a date, a situation, an action, and an outcome: "Repiped a 1970s slab-foundation home in Warner Ranch, Chandler, March 2026; replaced the corroded manifold, $340, before/after on file." Before/after outcomes with real numbers where they exist.

**How it proves Experience.** The QRG's most-rewarded Experience signal is specific, dated proof that you did the thing. A dated result is the difference between "we do great work" (asserted) and a checkable event with a time, a place, and a number (proven). It also carries information gain (Law 15): the date, price, and situation are net-new facts absent from the SERP consensus.

**Source.**
- `brand.yaml`: `eeat.proof` (free-text); **proposed** `eeat.projects[]` as `{city, neighborhood, job_type, situation, outcome, date, asset_ref}`.
- SME question (harvest category 1): "Tell me about a job in <city> in the last few months where the result was clearly better after you left than before. What was the situation, what did you do, and what was the outcome - roughly when, and is there a photo?"

**PASS test.** At least one dated result per money page (per the `eeat-framework.md` minimums; three local for service-city and location pages). Each carries a date, a real location, and an outcome. A result with no date, or a "recent project" with no place, fails (it reads as a template). The date and any figure trace to the SME answer or a record in `sources.md` (G10); a rounded or unsourced number is a fabrication risk.

### 3. Named team with real bios

**What it is.** A real person who would actually show up to the job: name, role, years on the tools, one true human detail (a certification, where they grew up, the thing customers always say). On the about page, a bio and photo corroborated by Person schema and, where it exists, a `sameAs` (LinkedIn, license lookup).

**How it proves Experience.** The QRG rewards clear authorship and real people over a faceless "the team." A named human with a checkable detail answers Who directly and gives the answer engines and raters a real entity to trust. A named owner with a licensing date a reader could verify outranks an anonymous brand on trust.

**Source.**
- `brand.yaml`: `eeat.team[]` as `{name, role, years, one_detail}`; `schema.same_as` for the person's authoritative profile.
- SME question (harvest category 2): "Who would actually show up to this job, and what is one true thing about them - years on the tools, a certification, where they grew up, the thing customers always say about them?"

**PASS test.** Money pages name at least one real person with a role and one specific human detail; the about page carries the full team with bios and Person schema whose fields match the visible page (G11 NAP/entity consistency). "Our team of experts" with no name fails. A named person whose credential is claimed on the page must have that credential recorded in `eeat.credentials` (G10), or the credential is cut and the name stays.

### 4. License, permit, and bond numbers

**What it is.** The verifiable regulatory artifacts: state contractor license number and class, trade certifications, bond amount, insurance limits, permit paths through the named local authority. "Arizona ROC-######, Class CR-11. Bonded. $2M general liability, certificate on request. Permit pulled through the City of Mesa online portal."

**How it proves Experience.** These turn "licensed and insured" (asserted) into claims a third party issued and a reader can check on the registrar's site (proven). For a licensed trade the number is also a real-world liability if false, which is exactly why a real one is such a strong trust and authority signal. The permit-path detail additionally proves first-hand local Experience: only someone who has pulled permits here knows the actual process.

**Source.**
- `brand.yaml`: `eeat.credentials[]` (credential type + number + issuing authority).
- SME question (harvest category 4): "What license, permit, bond, or certification do you carry for this work, and what are the numbers if they are public? Anything the guy down the road does not have?"

**PASS test.** Every licensed-trade claim on the page carries a real number tied to its issuing authority in `eeat.credentials` and, where public, is verifiable on the registrar (G10, G12 regulated-trade check). "Fully licensed and insured" with no number is asserted and fails on money pages. A permit-process claim names the real local authority; a generic "we handle all permits" does not count. Never invent or placeholder a license number to pass a count - that is the single fastest path to a trust penalty and a compliance-spine violation.

### 5. Invoice-backed counts and real reviews

**What it is.** Every falsifiable count on the page - jobs completed over a window, years in business, review count and rating - resolves to a real record: invoices, the business's books, or the live Google Business Profile. "214 water heaters in 2025." "5.0 across 187 Google reviews." Real quoted reviews carry a first name and, ideally, the job type and neighborhood, matching what is publicly visible on the GBP.

**How it proves Experience.** A count you could defend from invoices is proven volume of first-hand work; a round-number guess ("thousands of happy customers") is asserted and carries zero signal. A real review with attribution is customer-voice Experience that the QRG rewards and answer engines corroborate as an off-page consensus signal (research file 05). The count is the authority; "highly rated" is noise, "5.0 across 187 Google reviews" is a fact.

**Source.**
- `brand.yaml`: `eeat.proof` for counts and review figures; `client.founded_year` for years in business; **proposed** `eeat.reviews[]` as `{quote, first_name, job_type, city, platform}` and `eeat.stats[]` as `{claim, count, window, record}`.
- SME question (harvest category 5): "Roughly how many <job type> have you actually done, over how many years, and how many reviews are out there - the numbers you could back up from your invoices or your Google profile, not a guess?"

**PASS test.** Every number on the page (count, years, rating, review count) traces to `brand.yaml` or a tagged SME answer or the live GBP recorded in `sources.md` (G10). A count with no backing record fails. Years-in-business is consistent with `founded_year`, the license record, and the GBP. Every quoted review is real, attributable to what is publicly visible, and respects the `guardrails.review_pii_rule` (never publish a full name or identifying detail without consent). A fabricated review or an invented count is an auto-fail under G10 and Law 20 (no fabricated proof).

### 6. Street-level local detail

**What it is.** The anti-doorway fact: proof this crew physically works here, in named places, under named local conditions. Neighborhoods and streets they get called to most, and the reason (housing stock, soil, hard water, a local permitting or pricing quirk), plus the real local price shape. "The 1980s slab foundations off Gattis School Road get the same pinhole copper leak every spring; a repipe here runs $X, more if the slab routing is buried under an addition."

**How it proves Experience.** This is the strongest G1 carrier and the direct answer to the QRG's "visiting a place." A local failure-pattern observation is knowledge only someone who works this territory holds; it is precisely what makes a service-city page impossible to templatize across cities, which is what separates a genuine local page from a doorway page (banned by Hard Line and Google's spam policy). It is also pure information gain (Law 15): named streets and local conditions are net-new facts absent from the national consensus.

**Source.**
- `brand.yaml`: `service_areas[]` (real areas only, no inflation), `schema.price_range`; the failure-pattern and condition detail lands in body copy sourced from the SME answer.
- SME question (harvest category 6): "Which neighborhoods or streets in <city> do you get called to most for <problem>, and why there - the housing stock, the soil, the water, the local permitting or pricing quirk? What does a normal <job> run here, and what pushes it up?"

**PASS test.** Location, service-area, and service-city pages carry named neighborhoods, at least one local condition behind a named pattern, and a real price shape, all traced to the SME answer. The find-and-replace test is the gate: if swapping the city name and a few tokens would make the page fit the next city over, it fails G1 and G3 (doorway). A page with no street-level substance about this specific city should not be published (question whether it should exist at all), never padded with a generic "we serve the greater metro area."

### 7. Operator judgment and failure-mode observation

**What it is.** First-hand judgment only someone who has done the work hundreds of times has: the mistake other outfits in this city make that this operator has learned to avoid, the diagnostic decision logic, the honest tradeoff, the real reason a customer picks them over the cheaper quote (in the customer's words).

**How it proves Experience.** This is the border between Experience and Expertise, and it is the highest-value content because an answer engine cites the page that explains the mechanism and the judgment, not the page that asserts the outcome. Judgment usually carries real frustration or a real tradeoff, which reads unmistakably human and cannot be generated from the consensus. It is the differentiator in the customer's own voice, not a slogan.

**Source.**
- `brand.yaml`: `eeat.differentiators[]`.
- SME question (harvest category 7): "What is the mistake you see other <trade> outfits in <city> make on this that you have learned to avoid - and when a customer picks you over the cheaper quote, what do they say is the actual reason?"

**PASS test.** Each money page carries at least one piece of real operator judgment or a named failure mode traced to the SME answer, phrased as a specific decision or tradeoff rather than a value statement. "We care about quality" fails; "repeat cabling on a bellied line is money wasted, the next step is a camera inspection" passes. A differentiator that a competitor could also claim word-for-word is asserted and fails the provability principle.

---

## The harvest ledger (marker to field to gate)

| Marker | brand.yaml field (proposed in italics) | Primary SME category | Gate/law |
|---|---|---|---|
| 1. Original photos | `eeat.proof` / *`eeat.media[]`* + sources.md refs | 3 Original-photo checklist | Law 16, G1 |
| 2. Dated results / case data | `eeat.proof` / *`eeat.projects[]`* | 1 Dated results | G1, Law 16 |
| 3. Named team + bios | `eeat.team[]`, `schema.same_as` | 2 Named team | G2, Law 16 |
| 4. License / permit / bond | `eeat.credentials[]` | 4 Credential numbers | G10, G12, Law 16 |
| 5. Invoice-backed counts / reviews | `eeat.proof`, `founded_year` / *`eeat.reviews[]`*, *`eeat.stats[]`* | 5 Invoice-backed counts | G10, Law 16, Law 20 |
| 6. Street-level local detail | `service_areas`, `schema.price_range`, body | 6 Street-level specifics | G1, G3 (anti-doorway), Law 16 |
| 7. Operator judgment / failure mode | `eeat.differentiators[]` | 7 Operator judgment | G2, Law 16 |

## The anti-fabrication contract

No marker is invented at the keyboard. If a field is empty in `brand.yaml` and the SME interview did not fill it, the marker does not exist yet: write around it or go get the fact. The fix for a thin page is never a better adjective; it is a deeper SME harvest or a note to the operator that the page cannot make a claim it has no artifact to prove (Law 16, G10). Fabricating a local specific - a made-up license number, an invented review count, a fictional completed job - is the fastest path to a trust penalty and, for a licensed trade, a real-world liability. Under starvation (thin proof manifest), the correct behavior is a missing-evidence flag, never an invented stat.

This is the moat maintained: fewer, deeper, artifact-backed, certified pages built from facts the competitor down the road does not have, which is exactly the axis on which the entire commercial field (SERP-remix and parametric) structurally cannot compete.

Numbers and QRG characterizations here reflect the September 2025 QRG and the sources fetched 2026-07-20 PKT. Re-verify quarterly.
