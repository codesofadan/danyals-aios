# Local GBP Signals - Aligning On-Page Content with the Google Business Profile

This system writes web pages. It does not manage the client's Google Business Profile (GBP). But every page we write must **reinforce** the GBP, because for a local service business the GBP is the entity Google ranks in the map pack, and the website is the corroborating signal. When the site and the GBP tell the same story - same name, same address, same phone, same categories, same services, same cities, same reviews - Google's confidence in the entity rises and the pages rank. When they disagree, they cannot cite each other, relevance is diluted, and both surfaces lose.

The writer's job is one-directional: read the GBP facts (carried into `brand.yaml`), and make every page echo them. We never invent a category, a service, a city, or a review the GBP does not support. This file is the alignment spec.

**Doctrine Law 8 binding.** Alignment is a real-value signal, not a trick. We reinforce the GBP by making pages genuinely specific to the real business - its real categories, real service area, real reviews - not by keyword-matching for its own sake. Fabricating a review, a rating, or a service to "match" a GBP field is a trust violation and is forbidden (see the hard rules in CLAUDE.md and `nap-consistency.md`).

---

## 1. NAP consistency between the page and the GBP

NAP = Name, Address, Phone. It is the spine of entity resolution. The GBP's NAP is canonical; every page must present the identical NAP, and the on-page NAP must be in crawlable HTML text, not baked into an image or hidden behind JavaScript.

Full mechanics live in `nap-consistency.md`. The GBP-alignment essentials the writer enforces on every page:

- **Name.** Use the exact business name as it appears on the GBP and the real-world signage - no appended city or keyword ("Desert Door Pros", never "Desert Door Pros Garage Door Repair Tempe"). A keyword-stuffed name on the site does not help and it mirrors the top GBP suspension trigger; keep them identical and clean.
- **Address.** Match the GBP address field-for-field: same street, unit, city, ZIP. Abbreviation differences (St vs Street) are fine - Google normalizes those - but a different street number, unit, or ZIP is a real divergence and a flag. For a **service-area business (SAB)** whose GBP address is hidden, do not publish a storefront address the GBP hides; present the service area instead. The site's address model must match the GBP's address model.
- **Phone.** Use the GBP primary number as the visible, `tel:`-linked number on the page. If the client uses call-tracking (dynamic number insertion), the crawlable HTML must still serve the GBP primary number to Googlebot; a tracking number that replaces it in the source is a NAP mismatch.
- **Placement.** NAP in the footer site-wide (single location), and the relevant city NAP on each location / service-city page. The `LocalBusiness` JSON-LD `name`, `telephone`, and `PostalAddress` must equal the visible NAP and the GBP (schema that disagrees with the visible page or the GBP is a self-inflicted contradiction).

---

## 2. Category alignment - the site reinforces the GBP primary category

The GBP **primary category** is the single strongest relevance lever a local business controls, and it defines the head term the business is trying to win. The site's job is to reinforce it, not contradict or dilute it.

- **Primary category -> homepage + top service hub.** The homepage entity and the main service hub must plainly say what the GBP primary category says the business *is*. If the GBP primary is "Garage door supplier", the homepage H1, title, and opening copy must establish "garage door" as the core entity, and the primary service hub must match. A homepage that buries the primary category behind generic "home services" copy weakens the strongest signal the business has.
- **Secondary categories -> secondary service hubs / pages.** Each genuinely relevant GBP secondary category ("Garage door repair service") should have a corresponding service page or hub, so the site's architecture mirrors the GBP's category set. A secondary category with no page on the site is a missed relevance signal; a prominent site service with no GBP category behind it is a signal the GBP owner should add (flag it, do not fabricate it on the page).
- **One page, one dominant category topic.** Do not let a single page try to rank for the primary and three unrelated secondaries at once. Mirror the GBP's structure: one primary anchor, distinct pages for distinct categories.
- **Copy reinforces, it does not stuff.** Reinforcing the primary category means the page genuinely covers that service in depth with local specifics, not that the category string is repeated mechanically.

---

## 3. Service and service-area alignment - the site and GBP must match both ways

Google cross-checks the services and areas the business claims on the GBP against what the site says. Mismatches confuse relevance and can suppress both surfaces.

- **Services.** Every service listed on the GBP (its "Services" section) should have a corresponding page or clearly-covered section on the site, and every service the site sells should be a real service the business performs (and ideally listed on the GBP). The GBP services and the site's service pages are two views of one truth; keep them the same set. Use the GBP's customer-language service names as the on-page service names where natural.
- **Service area / cities.** The cities and areas on the GBP (its service-area list for an SAB, or its single city for a storefront) must match the site's location pages, service-city pages, and service-area page. Do not build a `[service] [city]` page for a city the GBP does not serve - that is a false-relevance and doorway-page risk with nothing to corroborate it. Conversely, a GBP service area with no supporting page on the site is an alignment gap worth closing.
- **Address model decides the page type.** A staffed storefront city gets a location page; a covered-but-unstaffed area on an SAB's GBP routes to the service-area page (or service-city combo pages), never to thin per-city storefront pages. The GBP's address-and-service-area model in `brand.yaml` dictates which of the six page types applies (see `keyword-research-method.md` step 7).

---

## 4. Review signals - surface real reviews, never fabricate

Reviews are among the highest-leverage local ranking and conversion signals, and they live on the GBP. On-page content reinforces them by surfacing the *real* review corpus, in a way Google and the reader can both verify.

- **Surface real reviews and themes.** Pull genuine review language and recurring themes from the client's actual GBP reviews (via `brand.yaml` or the SME interview) and reflect them on-page - the specific outcomes customers praise ("same-day", "explained the broken spring", "cleaned up after"), the neighborhoods they mention, the services they name. This makes the page specific and locally credible and echoes the GBP reputation. Never invent a quote, a reviewer, a rating, or a count.
- **Rating and count must be true and current.** If the page states a star rating or review count, it must match the live GBP at publish time and be genuinely displayed, not asserted. A number that disagrees with the GBP is both a trust problem and a schema-eligibility problem.
- **Review schema alignment.** `Review` / `AggregateRating` markup may only reflect reviews genuinely displayed on that page, and self-serving `AggregateRating` on your own `LocalBusiness`/`Organization` is ineligible for star rich results - so the failure mode to avoid is marking up reviews that are not on the page. Align schema to what is actually shown, which should in turn align to the GBP. When in doubt, display real testimonials on the page and mark up only those.
- **Do not scrape-and-paste.** Reflect themes and real, permissioned testimonials; do not lift the entire GBP review feed verbatim onto the page. The goal is corroboration and specificity, not duplication.

---

## 5. The local ranking triad, and where on-page content moves it

Google ranks local results on three factors: **Proximity, Relevance, Prominence.** The writer cannot touch one of them and moves the other two through content.

- **Proximity** - how close the business is to the searcher. **Fixed by the searcher's location and the business address.** No page can change it. The honest consequence: where a business is physically far from the searcher and content cannot close the gap, the real lever is a closer location or a correct GBP service area, not more copy. Content does not fake proximity; it maximizes the return on the proximity the business has.
- **Relevance** - how well the business matches the query. **On-page content is a primary lever here.** Content moves relevance by: reinforcing the GBP primary category (section 2), covering the specific service in the specific city with genuine local detail (service-in-city money pages), matching the GBP's services and service-area set (section 3), and keeping NAP and entity data consistent so Google can confidently connect the page to the GBP entity. Service + city specificity is the relevance engine, and it is exactly what the six page types are built to produce.
- **Prominence** - how well-known and trusted the business is. **On-page content contributes here too**, through: depth and genuine expertise (real E-E-A-T, see `eeat-framework.md`), surfacing real reviews and ratings (section 4), consistent entity signals that let third-party mentions and citations resolve to the same business (`sameAs` schema linking the site to the GBP and canonical profiles), and earning internal and external links to substantive pages. Prominence is built over time; content is the substance that makes the business worth citing and linking.

So the writer's leverage is Relevance and Prominence. Every page-type playbook is, at root, a method for moving those two while respecting the fixed Proximity the business has.

---

## 6. GBP-alignment checklist (run before any page ships)

Confirm each item against the client's GBP facts in `brand.yaml`:

- [ ] **Name** on the page and in schema exactly matches the GBP name, no appended keywords or city.
- [ ] **Address** matches the GBP field-for-field (normalization-tolerant); SAB address handling matches the GBP's (hidden stays hidden).
- [ ] **Phone** on the page and in `tel:` and schema is the GBP primary; any call-tracking still serves the GBP primary to crawlers.
- [ ] NAP is in **crawlable HTML text**, not an image or JS-only block.
- [ ] The page's dominant topic **reinforces the GBP primary category** (homepage and top service hub especially).
- [ ] Every relevant **GBP secondary category** has a corresponding page/hub; no orphaned prominent service lacks a GBP category (flag to owner if so).
- [ ] Services on the page are a subset of / consistent with the **GBP services list**; no invented services.
- [ ] The city/area targeted by the page is in the **GBP service area / matches the GBP address model**; no page for an unserved city.
- [ ] The correct **page type** was chosen for the address model (storefront -> location page; SAB coverage -> service-area page).
- [ ] Any **review content, rating, or count** is real, current, and matches the live GBP; nothing fabricated.
- [ ] **Review/rating schema** reflects only reviews genuinely displayed on the page and is eligibility-correct.
- [ ] `LocalBusiness` schema `name`/`address`/`telephone` equal the visible NAP and the GBP; `sameAs` links the GBP and canonical profiles.
- [ ] Page adds **genuine local specificity** (neighborhoods, landmarks, local detail) that reinforces relevance and prominence, not stuffed category strings.

Any unchecked box is a GBP-alignment gap; fix it or, where it requires a GBP edit the writer cannot make, flag it for the operator. Do not fabricate a page fact to force alignment.

---

## 7. Worked example: a dentist in Gilbert, AZ

`brand.yaml` (from the GBP): name "Val Vista Family Dental", storefront on E Williams Field Rd, Gilbert AZ; `gbp.primary_category`: "Dental clinic"; `gbp.secondary_categories`: "Cosmetic dentist", "Emergency dental service", "Pediatric dentist"; `gbp.services`: dental exam, teeth cleaning, dental implants, teeth whitening, emergency dentistry, kids dentistry; service area: Gilbert (staffed storefront), plus nearby Chandler and Queen Creek; live GBP rating 4.8 across 210 reviews, themes: "gentle", "great with kids", "same-day emergency", "explained the implant options".

**Homepage** (`/write-homepage`). Anchors the entity on the primary category: H1 and copy establish "Val Vista Family Dental - a Gilbert dental clinic", reinforcing "Dental clinic" as the core entity. NAP in the footer matches the GBP exactly, `tel:` on the GBP primary number, `LocalBusiness` (subtype `Dentist`) schema equal to the visible NAP with `sameAs` to the GBP and social profiles. Surfaces the real 4.8/210 reputation and two genuine testimonials themed on what reviews actually praise. Links out to the service hubs that mirror the primary and secondary categories.

**Service pages** (`/write-service-page`). One hub per GBP category/service: a "Dental implants" page (reinforcing the "Cosmetic dentist" secondary and the implants service), a "Emergency dentist" page (reinforcing "Emergency dental service", surfacing the "same-day emergency" review theme), a "Kids / pediatric dentistry" page (reinforcing "Pediatric dentist" and the "great with kids" theme). Each covers one service in depth in the practice's real voice; services match the GBP services list one-to-one; no service appears that the GBP does not list.

**Location / service-city pages** (`/write-location-page` for Gilbert, `/write-service-city-page` for the Chandler and Queen Creek service-city combos). Gilbert is the staffed storefront -> a location page targeting "dentist Gilbert" across the services, NAP matching the GBP, genuine local detail (Williams Field Rd area, Val Vista neighborhood, local landmarks). Chandler and Queen Creek are covered-but-unstaffed areas in the GBP service area -> service-in-city combo pages ("emergency dentist Chandler", "dental implants Queen Creek"), each corroborated by the GBP service area, none published for a city the GBP does not serve. Every one reinforces the "Dental clinic" primary category, matches NAP and services to the GBP, and surfaces real, current reviews - so the site and the GBP tell Google one consistent story, and relevance and prominence both rise on the proximity the practice actually has.
