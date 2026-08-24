# Outline Templates Per Page Type

A starter skeleton for each of the six local page types this system writes. The
outline step copies the matching skeleton into `output/<client>/<page-slug>/`
and fills each section from the brief, the page-type playbook, live research,
and the SME interview.

Every H2 is a **passage block**: a self-contained, extractable answer of roughly
120-220 words that leads with a direct answer, carries one idea per paragraph,
and closes on something citable. That is what gets pulled into local packs and
AI Overviews. Word budgets below are starting points; the page-type playbook in
`knowledge/playbooks/` is the authority when they differ.

Hard rule for all types: no doorway pattern. Location, service-in-city, and
service-area pages must each carry unique, genuinely local value. If two city
pages could swap their city name and still read fine, they are doorway pages and
they do not ship.

Rhythm applies everywhere: vary sentence length, one job per page, real facts
over filler, brand voice on top of universal humanization.

---

## 1. Location / city page  (`/write-location-page`)

**Query shape:** "[service] [city]" or "[trade] in [city]".
**Core job:** rank + convert for the city, prove the business genuinely serves it.
**Target length:** 900-1,500 words.

```
H1: [Primary service] in [City], [State]  -  [specific local angle, not generic]

OPENING (80-140 words, single block, not counted as a passage block)
- Direct hook: a real fact about serving THIS city that a generic page cannot fake.
- Name the searcher's situation and the one action this page wants.
- Speakable selector covers H1 + this first paragraph.

H2 #1: [Service] in [City]: the short answer  (passage block)
- One-paragraph direct answer: who you are, what you do in this city, response reality.
- One expertise marker (license number, years serving this city).

H2 #2: Why [City] homes/businesses need [service]  (passage block)
- The local conditions that drive demand (climate, housing stock, soil, codes).
- Specific, local, cited or SME-sourced. This is the anti-doorway section.

H2 #3: Areas of [City] we serve  (passage block + honest list)
- Real neighborhoods / districts / ZIPs actually covered. No inflated radius.
- One experience marker (a real job in a named area, anonymized as needed).

H2 #4: What [service] costs in [City]  (passage block)
- Honest local price ranges, cited. Trust section; often the most-read.
- What changes the price here specifically.

H2 #5: Why [neighbors in City] choose [Brand]  (passage block)
- Real differentiators + real proof (review count + platform, guarantee).
- One experience marker.

H2 #6: Common questions about [service] in [City]  (FAQ, 4-6 Q&A)
- Pulled from PAA + SME. FAQPage schema if 3+ pairs.

CLOSING (50-90 words)
- One concrete next step (call / book), phone + service promise. No summary filler.

[NAP block  -  byte-identical to brand.yaml / GBP; run nap_checker.py]
[Internal links: money service-in-city page, related services, homepage]
[Schema: LocalBusiness subtype + BreadcrumbList + FAQPage]
```

---

## 2. Service page  (`/write-service-page`)

**Query shape:** "[service]" brand-wide, not city-locked.
**Core job:** rank + convert for one service across the whole service area.
**Target length:** 1,000-1,700 words.

```
H1: [Service]  -  [what outcome the customer actually gets]

OPENING (80-140 words)
- Direct hook: the outcome, not the feature. Who this is for.
- The one conversion action.

H2 #1: What [service] includes  (passage block)
- Plain-language scope: what is and is not part of the job.
- One expertise marker (method, standard, certification).

H2 #2: When you need [service] (and when you do not)  (passage block)
- Honest signals it is time; honest signals it can wait. Trust builder.
- Specifics over abstractions.

H2 #3: How our [service] process works  (passage block, may be a short ordered list)
- Step-by-step of the real process. What the customer experiences at each step.
- One experience marker.

H2 #4: What [service] costs  (passage block)
- Honest range + the variables that move it. Cited where possible.

H2 #5: Why choose [Brand] for [service]  (passage block)
- Real, specific differentiators + proof. Not "quality service."
- Credentials with numbers, guarantee, review proof.

H2 #6: Common questions about [service]  (FAQ, 4-6 Q&A)
- PAA + SME. FAQPage schema if 3+ pairs.

CLOSING (50-90 words)
- One next step + the primary conversion path.

[Internal links: matching service-in-city pages, related services, about page]
[Schema: Service (+ provider LocalBusiness) + BreadcrumbList + FAQPage]
```

---

## 3. Service-in-city page (the money page)  (`/write-service-city-page`)

**Query shape:** one service x one city, highest commercial intent.
**Core job:** win the exact "[service] [city]" money query and convert.
**Target length:** 900-1,500 words. This is where specificity matters most.

```
H1: [Service] in [City], [State]  -  [sharp local + outcome angle]

OPENING (80-130 words)
- Direct hook tying the exact service to the exact city with a real specific.
- Immediate conversion cue (call / quote), plus response reality for this city.

H2 #1: The short answer  (passage block, may run 60-120 words)
- "For [service] in [City], here is what to expect / what it costs / how fast."
- The paragraph AI Overviews and local packs preferentially cite.

H2 #2: [Service] challenges specific to [City]  (passage block)
- The genuinely local dimension: codes, permits, climate, common failure modes.
- The single strongest anti-doorway section. Real, cited or SME.

H2 #3: How we deliver [service] in [City]  (passage block)
- The process localized: crews, response radius to this city, local supply.
- One experience marker (a real local job, anonymized).

H2 #4: [Service] pricing in [City]  (passage block)
- Honest local numbers + variables. Cited.

H2 #5: Proof from [City] customers  (passage block)
- Real reviews / results tied to this city (respect PII rules). Guarantee.

H2 #6: Common questions about [service] in [City]  (FAQ, 4-6 Q&A)
- Localized questions. FAQPage schema.

CLOSING (50-90 words)
- Single concrete action + phone + local promise.

[NAP block; run nap_checker.py]
[Internal links: parent city page, parent service page, related services in city]
[Schema: Service + LocalBusiness subtype + BreadcrumbList + FAQPage]
```

---

## 4. Homepage  (`/write-homepage`)

**Query shape:** brand + primary "[service] [primary city]"; entity anchor.
**Core job:** establish the business entity and drive the primary conversion.
**Target length:** 700-1,300 words (plus conversion furniture).

```
H1: [Brand]  -  [primary service] in [primary city / metro]

HERO (40-90 words)
- One-line value proposition + the primary action (call / quote / book).
- Immediate trust cue (years, license, review count).

H2 #1: What [Brand] does  (passage block)
- Plain summary of the core services and who is served.
- One expertise marker.

H2 #2: Services we provide  (passage block + linked list)
- Short, scannable list of core services, each linking to its service page.
- One line of substance per service, not a bare list.

H2 #3: Areas we serve  (passage block + linked list)
- The real service area, each key city linking to its location page. No inflation.

H2 #4: Why [primary city] chooses [Brand]  (passage block)
- The 3-4 real differentiators + hard proof (reviews, guarantee, credentials).
- One experience marker.

H2 #5: How to get started  (passage block)
- The simple next-step process. Reduce friction to the conversion.

H2 #6: Common questions  (FAQ, 3-5 Q&A)
- Broad top-of-funnel questions. FAQPage schema if 3+.

CLOSING (40-80 words)
- Restate the primary action + phone. Confident, short.

[NAP block; run nap_checker.py]
[Internal links: all core service pages, top location pages, about page]
[Schema: Organization + LocalBusiness subtype + BreadcrumbList + FAQPage]
```

---

## 5. About / team page  (`/write-about-page`)

**Query shape:** brand + trust research ("[brand] reviews", "who owns").
**Core job:** the E-E-A-T and trust surface. Make the humans and history real.
**Target length:** 700-1,300 words.

```
H1: About [Brand]  -  [the one true thing that sets the business apart]

OPENING (80-140 words)
- The real origin in one tight paragraph. A specific, not a slogan.
- No "family-owned since 1998" without the specifics that prove it.

H2 #1: Our story  (passage block)
- Founding, why the business exists, a real turning point. SME-sourced specifics.
- One experience marker.

H2 #2: Meet the team  (passage block, one short profile per key person)
- Real names, roles, years, one specific credential or detail each (from brand.yaml).
- Each key person can carry Person schema. Respect PII rules.

H2 #3: Our credentials and standards  (passage block)
- Licenses with numbers, certifications, insurance, memberships, safety standards.
- Expertise markers, verifiable.

H2 #4: How we work / what to expect  (passage block)
- The values made concrete through how the work actually gets done.
- One experience marker.

H2 #5: Proof and guarantees  (passage block)
- Review counts + platforms, awards, the guarantee in plain terms. Honest.

H2 #6: Common questions about [Brand]  (FAQ, 3-5 Q&A)
- Ownership, coverage, licensing, "are you insured" style questions.

CLOSING (50-90 words)
- Warm, specific invitation to the primary action. Phone.

[NAP block; run nap_checker.py]
[Internal links: services, top location pages, homepage]
[Schema: Organization + Person (per team member) + LocalBusiness + BreadcrumbList]
```

---

## 6. Service-area page  (`/write-service-area-page`)

**Query shape:** "[service] near me" / broad coverage across a region.
**Core job:** communicate coverage without spawning doorway near-duplicates.
**Target length:** 800-1,400 words.

```
H1: [Service] across [Region / Metro]  -  our full service area

OPENING (80-140 words)
- Direct statement of the real coverage footprint and how response works across it.
- The one conversion action.

H2 #1: Where we work  (passage block + honest structured list)
- The real cities / counties / ZIPs served, grouped sensibly. No inflated radius.
- Each major city links to its own location page (this page is the hub, not a
  replacement for them).

H2 #2: How coverage actually works  (passage block)
- Response times / travel by zone, dispatch reality, any surcharge honesty.
- One experience marker. This is the anti-doorway substance.

H2 #3: [Service] considerations across [Region]  (passage block)
- What varies across the area (codes by municipality, terrain, climate zones).
- Real, cited or SME. Gives the page genuine per-region value.

H2 #4: What service across [Region] costs  (passage block)
- Honest ranges and what shifts them by area. Cited.

H2 #5: Why [Region] chooses [Brand]  (passage block)
- Real differentiators + proof that hold across the whole area.

H2 #6: Common questions about our service area  (FAQ, 4-6 Q&A)
- "Do you cover [X]", "is there a travel fee", "how fast in [Y]".

CLOSING (50-90 words)
- One next step + phone + coverage promise.

[NAP block; run nap_checker.py]
[Internal links: every child location page, core service pages, homepage]
[Schema: LocalBusiness subtype with areaServed + BreadcrumbList + FAQPage]
```

---

## Filling and validation workflow

1. Read the brief (`00_brief.md`) and confirm the page type.
2. Copy the matching skeleton into the outline file.
3. Fill each H2 with brief-specific, SME-sourced, and researched local specifics.
   Every claim traces to a real source (Law: no fabricated local facts).
4. Confirm each H2 is a true passage block (direct-answer lead, one idea per
   paragraph, citable closer) and sits inside its word band.
5. Confirm the anti-doorway section is genuinely unique for this exact page.
6. Draft, humanize, then run the GATE scripts:
   `schema_validator.py`, `nap_checker.py`, `readability_scorer.py`,
   `compliance_lint.py`, `keyword_density.py`. Fix and re-run, max 2 retries.

If the page type does not match one of these six, it is out of scope for this
system (see CLAUDE.md "Not for"). Do not improvise a national/blog structure.
