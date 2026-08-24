# Schema.org & Structured Data for Self-Storage (US)

Research run: 2026-07-23 PKT. Territory 03 of the self-storage knowledge base.
Every claim below traces to a source I fetched this run. Where a source was blocked, truncated, or a figure is unverified, it is labeled a *pattern* or flagged, not stated as fact.

---

## 0. Bottom line up front

- **`schema.org/SelfStorage` exists.** It is a real subtype of `LocalBusiness`. Use it directly on the facility/location pages. It adds **no properties of its own** - it is a semantic label that inherits everything from `LocalBusiness` > `Organization`/`Place` > `Thing`. ([schema.org/SelfStorage](https://schema.org/SelfStorage))
- **The facility entity is the safe, high-value markup.** NAP + `geo` + `openingHoursSpecification` + `amenityFeature` + `areaServed` + `image` + `sameAs`. This is legitimate, matches visible content, and feeds the Google knowledge panel and Maps.
- **Unit pricing markup (`Product`/`Offer`/`AggregateOffer`/`UnitPriceSpecification`) is legitimate to *describe* a rentable unit, but it earns Google NO pricing/availability rich result for storage** - merchant-listing rich results require a purchasable retail product with checkout, which a rental unit is not. Marking `availability` you cannot back with real, current, on-page inventory is a quality-guideline violation and a fabrication risk (system Law: no fabricated local specifics).
- **Do NOT mark up self-serving review stars.** Since 2019 Google does not show `review`/`aggregateRating` stars when the entity controls the reviews about itself. `LocalBusiness`/`Organization` self-reviews are explicitly ineligible. This is the single most common self-storage schema mistake.
- **FAQ rich results are dead.** Google deprecated FAQ rich results on 2026-05-07 (after restricting them to government/health sites in Aug 2023). `FAQPage` markup is still valid and worth keeping for AI/answer-engine extraction, but it will not produce a SERP dropdown. Do not promise the client an FAQ rich result.
- **`BreadcrumbList` is the other reliably-rendered rich result** for storage sites and should be on every deep page.

---

## 1. Does `SelfStorage` exist? Type, hierarchy, properties

**Verified at [schema.org/SelfStorage](https://schema.org/SelfStorage).** Yes, it exists.

**Description (exact):** "A self-storage facility."

**Full hierarchy (two inheritance paths, because `LocalBusiness` is both an Organization and a Place):**

```
Thing > Organization > LocalBusiness > SelfStorage
Thing > Place        > LocalBusiness > SelfStorage
```

**Specific properties defined on `SelfStorage` itself: none.** `SelfStorage` is a leaf label. All usable properties are inherited. This matters operationally: there is no storage-specific `unitSize`, `climateControlled`, or `gateHours` property in schema.org. Those facts are expressed with generic properties (`amenityFeature`, `openingHoursSpecification`, free-text `description`), not a bespoke vocabulary.

> Usage note: schema.org's own usage banner reports `SelfStorage` in use on a low band of domains (the fetch reported a "1K-10K domains" band). Treat the exact count as an unverified schema.org telemetry figure, not a hard stat - the load-bearing fact is only that the type is real and adoptable.

**Key inherited properties relevant to a storage facility** (all valid on `SelfStorage`):

| Property | Inherited from | Storage use |
|---|---|---|
| `name` | Thing | Facility/brand name (NAP) |
| `address` (`PostalAddress`) | Organization/Place | Street, city, region, postal, country (NAP) |
| `telephone` | Organization/Place | Local phone (NAP) |
| `geo` (`GeoCoordinates`) | Place | Lat/long of the gate |
| `hasMap` | Place | Google Maps URL |
| `openingHoursSpecification` (`OpeningHoursSpecification`) | Place | Office/leasing hours (see access-hours nuance §3) |
| `openingHours` (text shorthand) | LocalBusiness | Legacy text form; prefer the Specification |
| `priceRange` | LocalBusiness | "$" to "$$$" tier, or "$25-$300/mo" text |
| `amenityFeature` (`LocationFeatureSpecification`) | Place | Climate control, 24hr access, drive-up, video surveillance, etc. |
| `currenciesAccepted` / `paymentAccepted` | LocalBusiness | "USD" / "Credit Card, ACH" |
| `areaServed` | Organization (via contactPoint/Service) | Cities/ZIPs the facility serves |
| `image` | Thing | Real dated facility photos |
| `url` | Thing | Canonical page URL |
| `sameAs` | Thing | GBP, Yelp, Facebook, industry-directory profiles |
| `aggregateRating` / `review` | Organization/Place | **DO NOT USE self-serving - see §5** |

Sources: [schema.org/SelfStorage](https://schema.org/SelfStorage), [schema.org/LocalBusiness](https://schema.org/LocalBusiness), [schema.org/amenityFeature](https://schema.org/amenityFeature).

---

## 2. What Google recommends for the business entity (LocalBusiness doc)

From [Google's LocalBusiness structured-data doc](https://developers.google.com/search/docs/appearance/structured-data/local-business):

- Google says use "**the most specific `LocalBusiness` sub-type possible.**" For storage, that specific subtype is `SelfStorage`. Use it, not bare `LocalBusiness`.
- **Required:** `name`, `address` (`PostalAddress`).
- **Recommended:** `geo` (`GeoCoordinates`), `telephone`, `url`, `openingHoursSpecification`, `priceRange`, `department`, plus (with a caveat) `aggregateRating` and `review`.
- **Rich result:** LocalBusiness data feeds the Google **knowledge panel** in Search and Maps ("Search results may display a prominent Google knowledge panel with details about a business"). Note: the local pack / map pack ranking itself is driven by the **Google Business Profile, not page schema** - schema supports the knowledge panel and entity understanding, it does not win the 3-pack. (Confirmed by practitioner pattern: map-pack placement comes from GBP proximity, profile completeness, and reviews, not markup. Source: [Cubby local-SEO playbook](https://www.cubbystorage.com/blog/local-seo-for-self-storage-the-complete-map-pack-playbook), pattern-level.)
- **The review caveat, verbatim from the LocalBusiness doc:** the `review`/`aggregateRating` properties are "only recommended for sites that capture reviews about **other** local businesses." That is the self-serving line, restated in §5.

---

## 3. Recommended JSON-LD per page type (exact property names)

### 3a. Facility / location / homepage page -> `SelfStorage`

The anchor entity. One per physical facility, on that facility's location page (and referenced from the homepage for a single-location brand).

```json
{
  "@context": "https://schema.org",
  "@type": "SelfStorage",
  "@id": "https://example.com/locations/austin-south#facility",
  "name": "Example Storage - South Austin",
  "url": "https://example.com/locations/austin-south",
  "image": "https://example.com/img/austin-south-gate-2026-06.jpg",
  "telephone": "+1-512-555-0142",
  "priceRange": "$29-$249/mo",
  "currenciesAccepted": "USD",
  "paymentAccepted": "Credit Card, Debit Card, ACH",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "1234 S Congress Ave",
    "addressLocality": "Austin",
    "addressRegion": "TX",
    "postalCode": "78704",
    "addressCountry": "US"
  },
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": 30.2450,
    "longitude": -97.7500
  },
  "hasMap": "https://www.google.com/maps/place/?q=place_id:XXXX",
  "areaServed": [
    { "@type": "City", "name": "Austin" },
    { "@type": "Place", "name": "78704" },
    { "@type": "Place", "name": "78745" }
  ],
  "openingHoursSpecification": [
    {
      "@type": "OpeningHoursSpecification",
      "name": "Office hours",
      "dayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday"],
      "opens": "09:00",
      "closes": "18:00"
    },
    {
      "@type": "OpeningHoursSpecification",
      "name": "Office hours",
      "dayOfWeek": "Saturday",
      "opens": "09:00",
      "closes": "14:00"
    }
  ],
  "amenityFeature": [
    { "@type": "LocationFeatureSpecification", "name": "Climate-controlled units", "value": true },
    { "@type": "LocationFeatureSpecification", "name": "Drive-up access", "value": true },
    { "@type": "LocationFeatureSpecification", "name": "24-hour gate access", "value": true },
    { "@type": "LocationFeatureSpecification", "name": "Video surveillance", "value": true },
    { "@type": "LocationFeatureSpecification", "name": "Individually alarmed units", "value": false }
  ],
  "sameAs": [
    "https://www.google.com/maps/place/?q=place_id:XXXX",
    "https://www.yelp.com/biz/example-storage-austin",
    "https://www.facebook.com/examplestorage"
  ]
}
```

**Property notes (all verified):**
- `amenityFeature` expects `LocationFeatureSpecification`, which uses `name` + a boolean `value` (and optional `hoursAvailable`). Marking a feature `false` is valid and honest - do it rather than omitting, if the on-page content addresses it. ([schema.org/amenityFeature](https://schema.org/amenityFeature))
- **Access-hours nuance:** storage has two distinct clocks - *office/leasing hours* and *gate/access hours*. `openingHoursSpecification` most cleanly maps to office hours. Do not encode 24/7 gate access as `opens:00:00 closes:23:59` on the office spec (misleads a caller). Express gate access via an `amenityFeature` ("24-hour gate access", `value:true`) with optional `hoursAvailable`, and state both clocks in visible page copy. This is a real trust point in the vertical.
- `priceRange` is free text; keep it consistent with the visible price band on the page.
- `areaServed` accepts `City`/`Place`/`GeoCircle` - use the real cities/ZIPs, matching the page's service-area copy, not an inflated list (doorway risk).

### 3b. Unit-type page -> `Product` + `Offer` / `UnitPriceSpecification` (legitimate, but no rich result - read §4 first)

For a page dedicated to one unit type (e.g. "10x10 climate-controlled unit"), where a **real, current** price is shown on the page:

```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "10x10 Climate-Controlled Storage Unit - South Austin",
  "description": "100 sq ft climate-controlled unit, drive-up-adjacent, ground floor.",
  "image": "https://example.com/img/10x10-climate-austin-south.jpg",
  "offers": {
    "@type": "Offer",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock",
    "businessFunction": "http://purl.org/goodrelations/v1#LeaseOut",
    "url": "https://example.com/locations/austin-south/units/10x10-climate",
    "priceSpecification": {
      "@type": "UnitPriceSpecification",
      "price": "129.00",
      "priceCurrency": "USD",
      "unitCode": "MON",
      "billingDuration": 1,
      "billingIncrement": 1
    }
  }
}
```

**Why this shape:**
- `businessFunction` = GoodRelations `LeaseOut` correctly signals a **rental, not a sale**. A storage unit is leased, not bought; omitting this and using a bare `Offer` mislabels the transaction. ([schema.org/Offer](https://schema.org/Offer) inherits `businessFunction`.)
- `UnitPriceSpecification` carries `price`, `priceCurrency`, `unitCode`, `unitText`, `referenceQuantity`, `billingIncrement`, `billingDuration`. For "$129 per month," `unitCode:"MON"` (UN/CEFACT month code) + `billingDuration:1` expresses the monthly rate. ([schema.org/UnitPriceSpecification](https://schema.org/UnitPriceSpecification))
- `availability` uses the enum `https://schema.org/InStock` / `SoldOut` / `LimitedAvailability`.

### 3c. Facility with a price *range* across unit sizes -> `AggregateOffer`

When one page summarizes many unit sizes (e.g. a "unit sizes & prices" table), an `AggregateOffer` is the honest summary object:

```json
{
  "@type": "AggregateOffer",
  "priceCurrency": "USD",
  "lowPrice": "29.00",
  "highPrice": "249.00",
  "offerCount": "14",
  "availability": "https://schema.org/InStock"
}
```

`AggregateOffer` properties: `lowPrice`, `highPrice`, `offerCount`, `priceCurrency`, `offers`. Parent is `Offer`, so it inherits `availability`, `priceSpecification`, `businessFunction`, etc. Values must equal the price band actually printed on the page. ([schema.org/AggregateOffer](https://schema.org/AggregateOffer))

### 3d. FAQ page -> `FAQPage` (valid markup, NO rich result - see §6)

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "mainEntity": [{
    "@type": "Question",
    "name": "How much notice do I need to give before moving out?",
    "acceptedAnswer": {
      "@type": "Answer",
      "text": "At our South Austin facility we ask for 10 days written notice; there is no long-term contract and no move-out fee."
    }
  }]
}
```

Keep it for answer-engine/LLM extraction and correctness, but do not expect a SERP dropdown (§6).

### 3e. Every deep page -> `BreadcrumbList` (reliably rendered)

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com" },
    { "@type": "ListItem", "position": 2, "name": "Austin Storage", "item": "https://example.com/locations/austin" },
    { "@type": "ListItem", "position": 3, "name": "South Austin", "item": "https://example.com/locations/austin-south" }
  ]
}
```

Required: `itemListElement` -> `ListItem` with `position`, `name`, `item`. Eligible for the breadcrumb-trail rich result on desktop in all regions/languages. ([Google breadcrumb doc](https://developers.google.com/search/docs/appearance/structured-data/breadcrumb))

### 3f. Recommended per-page-type schema matrix

| Page type | Primary type(s) | Also emit | Notes |
|---|---|---|---|
| Homepage (single location) | `SelfStorage` | `BreadcrumbList`, `WebSite` | Anchor entity + `@id` |
| Homepage (multi-location brand) | `Organization` (brand) | `BreadcrumbList`, `WebSite` | Each facility is `SelfStorage` on its own page, linked via `sameAs`/`department` |
| Location / facility page | `SelfStorage` | `BreadcrumbList` | The NAP+geo+amenity anchor |
| Service page (e.g. "climate-controlled storage") | `Service` or `WebPage` | `BreadcrumbList` | Optional; describe, don't force `Product` |
| Unit-type page (real live price) | `Product` + `Offer`/`UnitPriceSpecification` | `BreadcrumbList` | §4 caveats apply; no rich result |
| Unit-sizes/pricing page (range) | `SelfStorage` + `AggregateOffer` | `BreadcrumbList` | Range must match on-page table |
| FAQ page | `FAQPage` | `BreadcrumbList` | No rich result (§6); keep for AI |
| Local asset / cost guide | `Article` + `BreadcrumbList` | `Dataset` if a real study | Author E-E-A-T |

---

## 4. Unit pricing/availability: legitimate vs risky

**The core reality:** Google's `Product`/merchant-listing rich results (the price + availability + review chips in Search/Images/Shopping) are built for **purchasable retail products**. Per [Google's merchant-listing doc](https://developers.google.com/search/docs/appearance/structured-data/merchant-listing): "**Only pages where a shopper can purchase a product are eligible for merchant listing experiences.**" A self-storage unit is a **rental/lease of a service space**, not a retail SKU a shopper checks out and buys on the page. Practical consequences:

- **Legitimate:** using `Product` + `Offer` + `UnitPriceSpecification` (with `businessFunction: LeaseOut`) as an *honest description* of a rentable unit, when the price and availability shown in the markup exactly match the visible, current on-page content. This aids entity/price understanding and AI answer engines even without a Google rich result.
- **Risky / do not do:**
  1. **Fabricated or stale `availability`.** Setting `availability: InStock` when you have no real, current inventory signal on the page. Google's quality guidelines require "up-to-date information" and forbid marking up content "not visible to readers of the page." Fabricated availability is exactly the local-specific fabrication this system refuses. ([Google SD policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies))
  2. **Prices in markup that differ from the page.** The price in `UnitPriceSpecification` must equal the printed price. Storage prices move constantly (dynamic revenue management); if the page shows "starting at $99" the markup cannot say "$129."
  3. **Expecting a pricing rich result.** There is **no confirmed self-storage pricing rich result in Google Search.** Do not tell a client that `Product` markup will put their unit price in the SERP. (Practitioner pattern: some operators instead put "starting at $X" in the *title tag* precisely because the SERP won't render it from schema. Source: [Cubby playbook](https://www.cubbystorage.com/blog/local-seo-for-self-storage-the-complete-map-pack-playbook), pattern-level.)
- **Verdict:** mark up units with `Product`/`Offer` only when a real, current price is on the page and inventory is genuinely reflected; treat it as entity/AEO signal, not a rich-result lever. When in doubt, describe pricing in visible copy + `priceRange`/`AggregateOffer` on the facility, and skip per-unit `Offer`.

Sources: [Google merchant-listing doc](https://developers.google.com/search/docs/appearance/structured-data/merchant-listing), [Google Product intro](https://developers.google.com/search/docs/appearance/structured-data/product), [Google SD policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies), [schema.org/Offer](https://schema.org/Offer), [schema.org/UnitPriceSpecification](https://schema.org/UnitPriceSpecification).

---

## 5. Reviews & aggregateRating: the self-serving wall (the #1 mistake)

**Since September 2019, Google does not show review stars for an entity that controls the reviews about itself.** The current, authoritative statement is in [Google's review-snippet doc](https://developers.google.com/search/docs/appearance/structured-data/review-snippet):

> "If the entity that's being reviewed controls the reviews about itself, their pages that use `LocalBusiness` or any other type of `Organization` structured data are ineligible for the star review feature. For example, a review about entity A is placed on the website of entity A, either directly in their structured data or through an embedded third-party widget."

Restated in the [LocalBusiness doc](https://developers.google.com/search/docs/appearance/structured-data/local-business): `review`/`aggregateRating` are "only recommended for sites that capture reviews about **other** local businesses." Background: [Google's 2019 blog "Making Review Rich Results more helpful"](https://developers.google.com/search/blog/2019/09/making-review-rich-results-more-helpful) (blog body did not load this run; the current doc quote above is the operative rule). The 2019 change explicitly named `LocalBusiness`, `Organization`, and their subtypes as no longer eligible for self-serving review stars, and swept in reviews embedded via third-party widgets, not just hand-coded testimonials. (Corroborating pattern: [BrightLocal review-schema guide](https://www.brightlocal.com/learn/review-schema/).)

**What this means for a self-storage facility (`SelfStorage` is an `Organization`/`LocalBusiness` subtype - it is squarely inside the wall):**

- **Do NOT** put `aggregateRating` / `review` on your `SelfStorage` (or brand `Organization`) markup pointing at reviews of *your own* facility. It will not render stars, and marking up review content that isn't on the page (or piping in a Google/widget rating) risks a "misleading/irrelevant markup" quality violation. ([SD policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies): "Don't mark up irrelevant or misleading content, such as fake reviews.")
- **Where storage star ratings *do* legitimately appear:** in the **Google Business Profile / map pack / knowledge panel**, sourced from Google's own review corpus - not from your page schema. Reviews are a real ranking and CTR lever, but through GBP, not `aggregateRating` markup. ([Cubby playbook](https://www.cubbystorage.com/blog/local-seo-for-self-storage-the-complete-map-pack-playbook), pattern-level.)
- **The narrow legitimate exception:** review markup is allowed when the site reviews *other* businesses (a storage-comparison/directory reviewing many facilities), or on a genuine `Product` page reviewing that product. Neither describes a facility reviewing itself.

**Verdict for this system:** `review`/`aggregateRating` on facility/brand pages is on the permanent do-not-emit list. Drive reviews through GBP instead.

---

## 6. FAQ & other rich results that are gone or never existed

- **`FAQPage` rich results are deprecated.** Google announced deprecation on **2026-05-07**; FAQ Q&A dropdowns no longer appear in Search. This followed the **August 2023** restriction that had already limited them to "well-known, authoritative government and health websites." The `FAQPage` type remains valid schema and can stay on pages (Google says unused structured data does not harm Search), and it still helps AI/answer engines extract Q&A - but it produces **no SERP feature**. Do not sell it as a rich result. Sources: [Search Engine Journal: Google Drops FAQ Rich Results](https://www.searchenginejournal.com/google-drops-faq-rich-results-from-search/574429/), [The HOTH](https://www.thehoth.com/blog/google-faq-rich-results-deprecated/). (One WebFetch also reported a phased end to Search Console/Rich Results Test support through mid-2026; treat the exact secondary dates as reported-not-verified, the load-bearing fact is: no FAQ dropdown as of May 2026.)
- **HowTo rich results** were similarly deprecated earlier (2023) - not relevant to storage but worth knowing if a "how to pack a unit" page is considered: no rich result.
- **Breadcrumb** remains a live, rendered rich result (§3e) - the one to rely on for deep storage pages.

---

## 7. What Google actually renders for storage queries (SERP reality)

For queries like "storage units near me" / "storage units in [city]":

- **The dominant surface is the local pack / map pack** - three GBP listings with name, star rating, review count, address, call/directions buttons, above the organic results. Placement is driven by the **Google Business Profile** (proximity, profile completeness/activity, review count/rating/recency), **not** by page schema. Pattern estimate cited in the vertical: the map pack drives a large majority (one source says 70%+) of storage conversions - treat the exact percent as an unverified industry claim. Source: [Cubby local-SEO playbook](https://www.cubbystorage.com/blog/local-seo-for-self-storage-the-complete-map-pack-playbook), [MarketApts guide](https://www.marketapts.com/blog/local-seo-guide-self-storage/) (pattern-level).
- **Knowledge panel** for a branded facility search - fed by GBP + `SelfStorage`/`Organization` entity signals (name, address, phone, hours, `sameAs`). This is where clean facility schema pays off.
- **No self-storage pricing/availability rich result exists in Google Search.** Price does not render from `Offer`/`AggregateOffer` for storage. Operators surface price via GBP attributes, title tags ("from $X/mo"), and on-page copy - not schema-driven SERP chips.
- **AI/answer surfaces (AI Overviews, ChatGPT, Perplexity, Gemini)** increasingly answer "how much is a 10x10 in [city]" style questions. Clean, visible, marked-up facts (price band in copy + `AggregateOffer`, amenities in `amenityFeature`, Q&A in `FAQPage`) improve extraction odds even with zero classic rich result. This is where the "keep FAQPage anyway" value lives.

---

## 8. What NOT to mark up (the do-not-emit list)

Grounded in [Google's structured-data policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies):

1. **Self-serving `review` / `aggregateRating` on the facility or brand.** Ineligible since 2019; risks a misleading-markup violation. Reviews live in GBP. (§5)
2. **Fabricated or stale `availability` / unit prices.** Markup must be "visible to readers of the page" and "up-to-date." Availability you cannot back with real inventory, or a price that differs from the page, is a fabrication and a quality violation. (§4)
3. **`FAQPage` sold as a rich result.** Fine to keep for AI extraction; never promise a SERP dropdown. (§6)
4. **Inflated `areaServed`** listing cities you do not genuinely serve - feeds the doorway-page problem, and mismatches page content.
5. **`priceRange` / amenity claims that contradict visible copy.** Every marked-up fact must appear on the page and be true (climate control marked `true` when the facility has none = misleading markup).
6. **Bare `Offer` without `businessFunction: LeaseOut`** mislabels a rental as a sale.

**Enforcement stakes (verbatim):** a structured-data manual action means "a page loses eligibility for appearance as a rich result." Violations "can prevent syntactically correct structured data from being displayed as a rich result... or possibly cause it to be marked as spam." ([SD policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies))

---

## 9. Sources (fetched this run, 2026-07-23)

schema.org (primary vocabulary):
- [schema.org/SelfStorage](https://schema.org/SelfStorage) - type exists, hierarchy, no own properties, "A self-storage facility."
- [schema.org/LocalBusiness](https://schema.org/LocalBusiness), [schema.org/amenityFeature](https://schema.org/amenityFeature) - `LocationFeatureSpecification` (name + boolean value + hoursAvailable)
- [schema.org/Offer](https://schema.org/Offer), [schema.org/AggregateOffer](https://schema.org/AggregateOffer) - lowPrice/highPrice/offerCount; inherited availability, businessFunction, priceSpecification
- [schema.org/UnitPriceSpecification](https://schema.org/UnitPriceSpecification) - price, priceCurrency, unitCode, unitText, referenceQuantity, billingIncrement, billingDuration

Google Search Central (rendering rules & policy):
- [LocalBusiness structured data](https://developers.google.com/search/docs/appearance/structured-data/local-business) - most-specific subtype, required/recommended props, knowledge panel, review caveat
- [Review snippet structured data](https://developers.google.com/search/docs/appearance/structured-data/review-snippet) - the self-serving-review rule (exact quote in §5)
- [Making Review Rich Results more helpful (2019 blog)](https://developers.google.com/search/blog/2019/09/making-review-rich-results-more-helpful) - origin of the 2019 change (blog body did not load; current doc is authoritative)
- [Merchant listing structured data](https://developers.google.com/search/docs/appearance/structured-data/merchant-listing) - "Only pages where a shopper can purchase a product are eligible"
- [Product structured data intro](https://developers.google.com/search/docs/appearance/structured-data/product)
- [Breadcrumb structured data](https://developers.google.com/search/docs/appearance/structured-data/breadcrumb) - itemListElement/ListItem/position/name/item; live rich result
- [Structured data general/quality policies](https://developers.google.com/search/docs/appearance/structured-data/sd-policies) - visibility, up-to-date, no misleading markup, manual-action stakes

FAQ deprecation (secondary, corroborated):
- [Search Engine Journal - Google Drops FAQ Rich Results](https://www.searchenginejournal.com/google-drops-faq-rich-results-from-search/574429/)
- [The HOTH - FAQ rich results deprecated](https://www.thehoth.com/blog/google-faq-rich-results-deprecated/)

Vertical/practitioner patterns (labeled pattern-level, not primary):
- [Cubby - Local SEO for Self-Storage (map pack playbook)](https://www.cubbystorage.com/blog/local-seo-for-self-storage-the-complete-map-pack-playbook)
- [MarketApts - Local SEO guide for self-storage](https://www.marketapts.com/blog/local-seo-guide-self-storage/)
- [BrightLocal - Can local businesses use review schema?](https://www.brightlocal.com/learn/review-schema/)

---

## 10. Open questions / to verify at write time

- Exact current `SelfStorage` domain-usage band on schema.org (reported "1K-10K", unverified telemetry).
- Whether Google has quietly added any storage-specific price surface in AI Overviews (no evidence found; recheck at write time).
- The 2019 blog body (fetch returned only the archive shell this run) - the operative rule is captured from the live review-snippet doc, so this is completeness-only.
- Secondary FAQ-deprecation sub-dates (Search Console/API sunset) reported by one fetch - not load-bearing, verify if a client asks.
