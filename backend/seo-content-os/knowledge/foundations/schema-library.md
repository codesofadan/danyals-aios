# Schema Library (Local Pages)

The JSON-LD bundle every local page emits. This file is the copy-paste source of truth: real, valid schema.org types with placeholder values that resolve from `clients/<client>/brand.yaml`. Nothing here is a fake business. Every value is a `{{placeholder}}` the writer fills from the client profile or leaves out if the fact does not exist.

Governing law (doctrine Law 8 + Law 13): **schema is a machine-readable set of CLAIMS about a real entity.** It is not a ranking trick and not a detector dodge. You mark up only what is true and visible on the page. A schema value that contradicts the rendered page, or asserts a credential/review/price the business does not have, is a manual-action vector and a hard violation here. Schema earns two things when it is honest: rich-result eligibility (deterministic) and entity clarity that raises the odds of being the cited answer inside AI engines (probabilistic). It earns nothing when it is inflated.

Do not fabricate. If `brand.yaml` has no `geo.lat`, you omit `geo`; you do not invent coordinates. If there is no third-party review count, you omit `aggregateRating`; you never self-review. This is not optional.

---

## 1. What goes on which page (the mapping)

Every page emits one `<script type="application/ld+json">` with a single `@graph`. The graph always contains the canonical `LocalBusiness` node (by `@id` reference, defined in full only where noted) plus the page-specific nodes.

| Page type | Command | Primary node(s) | Also in graph |
|---|---|---|---|
| Homepage | `/write-homepage` | `LocalBusiness` (full definition, the canonical entity) | `WebSite`, `BreadcrumbList` (Home only, or omit), `FAQPage` if genuine Q&A |
| Service page | `/write-service-page` | `Service` (brand-wide, `areaServed` = whole coverage) | `LocalBusiness` (ref), `BreadcrumbList`, `FAQPage` if used |
| Service-in-city (money page) | `/write-service-city-page` | `Service` (`areaServed` = the one city) | `LocalBusiness` (ref), `BreadcrumbList`, `FAQPage` if used |
| Location / city page | `/write-location-page` | `LocalBusiness` (ref) + `Service`(s) offered there | `BreadcrumbList`, `FAQPage` if used. Use a `department`/branch node ONLY if a real second address exists |
| About / team page | `/write-about-page` | `LocalBusiness` (ref) + `Person` per real team member | `BreadcrumbList`, optional `AboutPage` `WebPage` node |
| Service-area page | `/write-service-area-page` | `LocalBusiness` (ref) with `areaServed` list | `Service`, `BreadcrumbList`, `FAQPage` if used |

Rules that fall out of the table:
- **`LocalBusiness` is defined in full exactly once** (the homepage) and referenced everywhere else by `@id`. Do not redeclare the full block on every page. Redeclaration fragments the entity (schema-audit C1).
- **`Person` nodes live on the about page** where the real bio is visible, and are referenced by `@id` from any page that uses that person as `author`.
- **`FAQPage` ships only when the page renders a genuine visible Q&A block** built from passage blocks (see section 6). No hidden FAQ markup, ever.
- **`Organization` vs `LocalBusiness`:** a `LocalBusiness` IS an `Organization` (subtype). For a single-location service business, the `LocalBusiness` node is the organization; do not add a separate `Organization`. Add a distinct `Organization` node only for a multi-location parent brand or when the site publisher is a different legal entity than the storefront (rare for local). Section 7 covers that case.

---

## 2. LocalBusiness and the industry subtypes

Google's own instruction: **use the most specific subtype that applies.** The subtype is not guessed here; it is read from `brand.yaml -> schema.local_business_type`. `/new-client` sets it. Fall back to the parent (`HomeAndConstructionBusiness` or bare `LocalBusiness`) only when no specific subtype exists.

### Subtype map (verified against schema.org type tree)

Home and trade services (children of `HomeAndConstructionBusiness`):

| Business | `local_business_type` | schema.org page |
|---|---|---|
| Plumbing | `Plumber` | https://schema.org/Plumber |
| HVAC / heating + cooling | `HVACBusiness` | https://schema.org/HVACBusiness |
| Electrical | `Electrician` | https://schema.org/Electrician |
| Roofing | `RoofingContractor` | https://schema.org/RoofingContractor |
| General contractor / remodel | `GeneralContractor` | https://schema.org/GeneralContractor |
| Painting | `HousePainter` | https://schema.org/HousePainter |
| Locksmith | `Locksmith` | https://schema.org/Locksmith |
| Moving | `MovingCompany` | https://schema.org/MovingCompany |

Professional and medical:

| Business | `local_business_type` | schema.org page |
|---|---|---|
| Law firm / lawyer | `Attorney` (or `LegalService`) | https://schema.org/Attorney |
| Dentist | `Dentist` | https://schema.org/Dentist |
| Doctor / clinic | `Physician` or `MedicalClinic` | https://schema.org/Physician |
| Accounting | `AccountingService` | https://schema.org/AccountingService |
| Auto repair | `AutoRepair` | https://schema.org/AutoRepair |

No exact subtype (pest control, landscaping, cleaning, junk removal, tree service, pressure washing, garage doors, water damage restoration): use `HomeAndConstructionBusiness` if it is a trade, else bare `LocalBusiness`. Do NOT invent a type like `LandscapingBusiness` or `PestControlBusiness`; those are not in the vocabulary and a bad `@type` maps to no feature. Verify any subtype against its schema.org page before shipping.

Self-storage: use **`SelfStorage`** (a real `LocalBusiness` subtype, https://schema.org/SelfStorage), not bare `LocalBusiness`. It defines no properties of its own; storage-specific facts use inherited properties plus `amenityFeature`. See the dedicated self-storage schema section below for the facility node, the unit `Offer` bundle, and the storage do-not-emit list.

### The canonical LocalBusiness node (full definition, homepage)

```json
{
  "@context": "https://schema.org",
  "@type": "{{local_business_type}}",
  "@id": "https://{{domain}}/#localbusiness",
  "name": "{{business_name}}",
  "legalName": "{{legal_name}}",
  "url": "https://{{domain}}/",
  "image": "https://{{domain}}/{{storefront_or_team_photo}}",
  "logo": "https://{{domain}}/{{logo_path}}",
  "telephone": "{{phone_e164}}",
  "priceRange": "{{price_range}}",
  "description": "{{one_sentence_entity_description}}",
  "foundingDate": "{{founded_year}}",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "{{street}}",
    "addressLocality": "{{city}}",
    "addressRegion": "{{state}}",
    "postalCode": "{{postal_code}}",
    "addressCountry": "{{country}}"
  },
  "geo": {
    "@type": "GeoCoordinates",
    "latitude": "{{lat}}",
    "longitude": "{{lng}}"
  },
  "hasMap": "{{gbp_map_url}}",
  "openingHoursSpecification": [
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"],
      "opens": "08:00",
      "closes": "18:00"
    },
    {
      "@type": "OpeningHoursSpecification",
      "dayOfWeek": "Saturday",
      "opens": "09:00",
      "closes": "14:00"
    }
  ],
  "areaServed": [
    { "@type": "City", "name": "{{primary_city}}" },
    { "@type": "City", "name": "{{service_area_2}}" }
  ],
  "sameAs": [
    "{{gbp_profile_url}}",
    "{{facebook_url}}",
    "{{yelp_url}}",
    "{{bbb_url}}",
    "{{linkedin_url}}"
  ]
}
```

Field rules:
- `@type` is the subtype string from `brand.yaml`. One value, not an array, unless you genuinely need two (e.g. `["Dentist", "MedicalBusiness"]` is redundant since Dentist inherits; keep it single).
- `telephone` uses E.164 (`+14805551234`). The visible NAP phone can be formatted for humans; the schema value should be dialable and match GBP.
- `priceRange` is a coarse band (`"$$"` or a real range like `"$150-$500"`), pulled from `brand.yaml`. Omit if unknown; do not guess.
- `openingHoursSpecification` uses the object form (24h `HH:MM`). `brand.yaml` stores compact strings like `"Mo-Fr 08:00-18:00"`; the writer converts to the object form above. For a 24/7 emergency line add `{ "@type": "OpeningHoursSpecification", "dayOfWeek": ["Monday", ... "Sunday"], "opens": "00:00", "closes": "23:59" }` only if the business truly answers 24/7.
- `areaServed` lists real `City` (or `AdministrativeArea`) nodes from `service_areas`. Do not inflate coverage; a city listed here that has no genuine service is a doorway signal.
- `sameAs` carries authoritative, resolving profile URLs: Google Business Profile, Facebook, Yelp, BBB, LinkedIn, industry directories (Angi, HomeAdvisor). Each must return 200 and describe THIS business. A dead or wrong-entity `sameAs` harms disambiguation; drop it. Presence-count is not the goal; correctness is.
- **`aggregateRating`:** add ONLY from genuine third-party reviews with a visible source and count on the page, and never self-authored. If in doubt, omit. This is the single most common local manual-action cause.

### The reference form (every non-homepage page)

Other pages do not redeclare the block. They reference it:

```json
{ "@type": "{{local_business_type}}", "@id": "https://{{domain}}/#localbusiness" }
```

and any node needing the business as provider/publisher points at `https://{{domain}}/#localbusiness`.

---

## 3. Service schema (service page and money page)

`Service` is the primary node on the service page and the service-in-city money page. It links to the business via `provider` and scopes coverage via `areaServed`. `serviceType` names the service in words the query uses.

Brand-wide service page (`areaServed` = whole coverage footprint):

```json
{
  "@context": "https://schema.org",
  "@type": "Service",
  "@id": "https://{{domain}}/services/{{service_slug}}/#service",
  "name": "{{service_name}}",
  "serviceType": "{{service_type}}",
  "description": "{{what_the_service_is_and_who_it_is_for}}",
  "provider": { "@id": "https://{{domain}}/#localbusiness" },
  "areaServed": [
    { "@type": "City", "name": "{{primary_city}}" },
    { "@type": "City", "name": "{{service_area_2}}" },
    { "@type": "City", "name": "{{service_area_3}}" }
  ],
  "url": "https://{{domain}}/services/{{service_slug}}/",
  "offers": {
    "@type": "Offer",
    "priceCurrency": "{{currency}}",
    "priceSpecification": {
      "@type": "PriceSpecification",
      "price": "{{price_or_from_price}}",
      "priceCurrency": "{{currency}}"
    },
    "availability": "https://schema.org/InStock"
  },
  "hasOfferCatalog": {
    "@type": "OfferCatalog",
    "name": "{{service_name}} options",
    "itemListElement": [
      { "@type": "Offer", "itemOffered": { "@type": "Service", "name": "{{sub_service_1}}" } },
      { "@type": "Offer", "itemOffered": { "@type": "Service", "name": "{{sub_service_2}}" } }
    ]
  }
}
```

Money page (service-in-city). Same node, `areaServed` narrowed to the one city, `name` and `@id` carry the city:

```json
{
  "@context": "https://schema.org",
  "@type": "Service",
  "@id": "https://{{domain}}/{{service_slug}}-{{city_slug}}/#service",
  "name": "{{service_name}} in {{city}}, {{state}}",
  "serviceType": "{{service_type}}",
  "description": "{{service_in_this_city_specifics}}",
  "provider": { "@id": "https://{{domain}}/#localbusiness" },
  "areaServed": { "@type": "City", "name": "{{city}}" },
  "url": "https://{{domain}}/{{service_slug}}-{{city_slug}}/"
}
```

Rules:
- `provider` is always an `@id` reference to the canonical business node, never an inlined duplicate business.
- `offers`/`price` only when a real price or "from" price is visible on the page. Omit otherwise; do not fabricate. `price` is a number as a string (`"149"`), `priceCurrency` is ISO 4217 (`"USD"`).
- `serviceType` is the query-shaped label (`"Emergency AC repair"`), which helps topical clustering. `name` is the human title.
- Do not mark up two `Service` nodes with the same `@id` across the service page and the money page; the money page uses the city-qualified `@id`.

---

## 4. BreadcrumbList (matches the local silo)

Breadcrumbs mirror the actual URL silo and nav. High ROI, low effort, supported rich result. Chain must match the real path.

Service-in-city money page silo `Home > Services > {{Service}} > {{Service}} in {{City}}`:

```json
{
  "@context": "https://schema.org",
  "@type": "BreadcrumbList",
  "@id": "https://{{domain}}/{{service_slug}}-{{city_slug}}/#breadcrumb",
  "itemListElement": [
    { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://{{domain}}/" },
    { "@type": "ListItem", "position": 2, "name": "Services", "item": "https://{{domain}}/services/" },
    { "@type": "ListItem", "position": 3, "name": "{{service_name}}", "item": "https://{{domain}}/services/{{service_slug}}/" },
    { "@type": "ListItem", "position": 4, "name": "{{service_name}} in {{city}}", "item": "https://{{domain}}/{{service_slug}}-{{city_slug}}/" }
  ]
}
```

Silo per page type:
- Homepage: no breadcrumb (or a single Home item).
- Service page: `Home > Services > {{Service}}`.
- Location page: `Home > Locations > {{City}}` (or `Home > Service Areas > {{City}}`).
- Service-in-city: `Home > Services > {{Service}} > {{Service}} in {{City}}`.
- About: `Home > About`.
- Service-area: `Home > Service Areas` (hub) then each city page hangs under it.

The last `ListItem` is the current page and still carries its `item` URL. Positions are sequential from 1. The chain must be the true click path, not a keyword-stuffed invented one.

---

## 5. FAQPage (built from the page's passage blocks)

Ship `FAQPage` only when the page renders a real, visible Q&A block. The questions are the extractable passage-block questions from the page (see `passage-block-protocol.md`): each H2/H3 phrased as a real customer question, each answer the 40-90 word direct-answer lead that already sits on the page. The schema mirrors visible content verbatim; it does not add hidden Q&A.

```json
{
  "@context": "https://schema.org",
  "@type": "FAQPage",
  "@id": "https://{{domain}}/{{page_slug}}/#faq",
  "mainEntity": [
    {
      "@type": "Question",
      "name": "{{visible_question_1}}",
      "acceptedAnswer": { "@type": "Answer", "text": "{{visible_answer_1_40_to_90_words}}" }
    },
    {
      "@type": "Question",
      "name": "{{visible_question_2}}",
      "acceptedAnswer": { "@type": "Answer", "text": "{{visible_answer_2}}" }
    },
    {
      "@type": "Question",
      "name": "{{visible_question_3}}",
      "acceptedAnswer": { "@type": "Answer", "text": "{{visible_answer_3}}" }
    }
  ]
}
```

Rules:
- Minimum 3 genuine pairs. A 1-2 pair FAQ is decorative and reads as schema-stuffing.
- Every question and answer must appear in the rendered DOM, word for word. Hidden FAQ markup violates Google policy and risks a manual action.
- FAQ rich results are largely gone from the SERP (direction: retired for most sites; verify the current state at Search Central before promising a rich result to a client). Keep the markup because AI answer engines still extract clean Q&A pairs for citation. That is the reason it earns its place here, not a blue-link enhancement.
- Answers 40-90 words. Below that they fall out of the citation band; above it retrieval models truncate.

---

## 6. Organization and Person (E-E-A-T for about and author)

For a single-location local business you usually do NOT add a separate `Organization`; the `LocalBusiness` node is the org. Add `Organization` only for a multi-location parent or a distinct publisher entity:

```json
{
  "@context": "https://schema.org",
  "@type": "Organization",
  "@id": "https://{{domain}}/#organization",
  "name": "{{parent_brand_name}}",
  "url": "https://{{domain}}/",
  "logo": { "@type": "ImageObject", "url": "https://{{domain}}/{{logo_path}}" },
  "sameAs": ["{{linkedin_url}}", "{{facebook_url}}"]
}
```

`Person` is the E-E-A-T surface: real team members with real bios, defined on the about page where the bio is visible. `worksFor` references the business node; a page using this person as an author references the Person by `@id`.

```json
{
  "@context": "https://schema.org",
  "@type": "Person",
  "@id": "https://{{domain}}/about/#person-{{person_slug}}",
  "name": "{{person_full_name}}",
  "jobTitle": "{{person_role}}",
  "worksFor": { "@id": "https://{{domain}}/#localbusiness" },
  "image": "https://{{domain}}/{{headshot_path}}",
  "description": "{{bio_with_specifics_years_and_a_real_detail}}",
  "knowsAbout": ["{{specialty_1}}", "{{specialty_2}}"],
  "hasCredential": {
    "@type": "EducationalOccupationalCredential",
    "credentialCategory": "license",
    "name": "{{license_name}}",
    "identifier": "{{license_number_if_public}}"
  },
  "sameAs": ["{{linkedin_url}}", "{{trade_registry_or_directory_url}}"]
}
```

Rules:
- Only real people with a visible bio on the page. No invented staff, no stock-photo personas.
- `worksFor` is an `@id` reference to `#localbusiness`, not an inlined business.
- `hasCredential` only for a credential the business actually holds; include the license number only if it is public (trade license, bar number). Never fabricate a number.
- `knowsAbout` lists the person's genuine specialties, not the whole industry. It should align with what they actually did.
- When a service or location page names a technician/author, add `"author": { "@id": "https://{{domain}}/about/#person-{{person_slug}}" }` on that page's primary node and let the full Person definition stay on the about page.

---

## 7. The @id and @graph linking pattern

Everything ships as one `@graph` per page. Entities reference each other by stable `@id`; nothing important is inlined twice.

Canonical `@id`s (absolute, fragment-based, reused byte-identically site-wide):

| Entity | `@id` | Defined in full on | Referenced from |
|---|---|---|---|
| The business | `https://{{domain}}/#localbusiness` | homepage | every page |
| The website | `https://{{domain}}/#website` | homepage | homepage |
| A service | `https://{{domain}}/services/{{service_slug}}/#service` | its service page | money pages, location pages |
| A team member | `https://{{domain}}/about/#person-{{slug}}` | about page | any page they author |
| A page's breadcrumb | `{{page_url}}#breadcrumb` | that page | that page |
| A page's FAQ | `{{page_url}}#faq` | that page | that page |

Linking directions (the load-bearing edges):
- `Service.provider` -> `#localbusiness`
- `Person.worksFor` -> `#localbusiness`
- page primary node `.author` -> `#person-{{slug}}`
- `LocalBusiness.sameAs` -> external profiles (never `@id`; external URLs go in `sameAs`, internal identity goes in `@id`)

The `@id` is your identity, `sameAs` is your external corroboration. Never put an external URL in `@id`, never put an internal fragment in `sameAs`. Reuse the same `@id` for the same entity on every page so Google and AI retrieval reconcile it into one node instead of many weak mentions.

A page graph looks like:

```json
{
  "@context": "https://schema.org",
  "@graph": [
    { "...Service (primary)..." },
    { "@type": "{{local_business_type}}", "@id": "https://{{domain}}/#localbusiness" },
    { "...BreadcrumbList..." },
    { "...FAQPage if used..." }
  ]
}
```

---

## 8. Worked example: plumber in Tempe, Arizona (money page, full @graph)

Placeholder business, illustrating a filled money page for `/write-service-city-page`, target query "emergency drain cleaning Tempe AZ". Every value here would come from `brand.yaml`; shown filled so the shape is concrete. This is a template illustration, not a claim about a real company.

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Service",
      "@id": "https://{{domain}}/drain-cleaning-tempe/#service",
      "name": "Emergency Drain Cleaning in Tempe, AZ",
      "serviceType": "Emergency drain cleaning",
      "description": "Same-day drain and sewer clearing for Tempe homes and rentals, including hydro-jetting for root-blocked lines common in older Maple-Ash neighborhood pipes.",
      "provider": { "@id": "https://{{domain}}/#localbusiness" },
      "areaServed": { "@type": "City", "name": "Tempe" },
      "url": "https://{{domain}}/drain-cleaning-tempe/",
      "offers": {
        "@type": "Offer",
        "priceCurrency": "USD",
        "priceSpecification": {
          "@type": "PriceSpecification",
          "price": "89",
          "priceCurrency": "USD"
        },
        "availability": "https://schema.org/InStock"
      }
    },
    {
      "@type": "Plumber",
      "@id": "https://{{domain}}/#localbusiness",
      "name": "{{business_name}}",
      "url": "https://{{domain}}/",
      "telephone": "+14805550142",
      "priceRange": "$$",
      "image": "https://{{domain}}/img/team-truck.jpg",
      "address": {
        "@type": "PostalAddress",
        "streetAddress": "1420 W Broadway Rd",
        "addressLocality": "Tempe",
        "addressRegion": "AZ",
        "postalCode": "85282",
        "addressCountry": "US"
      },
      "geo": { "@type": "GeoCoordinates", "latitude": "33.4072", "longitude": "-111.9663" },
      "openingHoursSpecification": [
        {
          "@type": "OpeningHoursSpecification",
          "dayOfWeek": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
          "opens": "00:00",
          "closes": "23:59"
        }
      ],
      "areaServed": [
        { "@type": "City", "name": "Tempe" },
        { "@type": "City", "name": "Mesa" },
        { "@type": "City", "name": "Chandler" }
      ],
      "sameAs": [
        "https://www.google.com/maps/place/?q=place_id:{{gbp_place_id}}",
        "https://www.facebook.com/{{fb_handle}}",
        "https://www.yelp.com/biz/{{yelp_slug}}"
      ]
    },
    {
      "@type": "BreadcrumbList",
      "@id": "https://{{domain}}/drain-cleaning-tempe/#breadcrumb",
      "itemListElement": [
        { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://{{domain}}/" },
        { "@type": "ListItem", "position": 2, "name": "Services", "item": "https://{{domain}}/services/" },
        { "@type": "ListItem", "position": 3, "name": "Drain Cleaning", "item": "https://{{domain}}/services/drain-cleaning/" },
        { "@type": "ListItem", "position": 4, "name": "Drain Cleaning in Tempe", "item": "https://{{domain}}/drain-cleaning-tempe/" }
      ]
    },
    {
      "@type": "FAQPage",
      "@id": "https://{{domain}}/drain-cleaning-tempe/#faq",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "How fast can you reach a clogged drain in Tempe?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "For most Tempe addresses inside the 202 loop we arrive within 60 to 90 minutes of the call, day or night. Crews stage out of our Broadway Road shop, so South Tempe and the ASU-area rentals are usually the fastest, often under an hour off-peak."
          }
        },
        {
          "@type": "Question",
          "name": "What does emergency drain cleaning cost in Tempe?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "A standard cabled drain clearing starts at $89. Hydro-jetting a root-blocked main line, which is common in the older Maple-Ash and Mitchell Park lines, runs more because it needs a camera inspection first. We quote the full price on site before any work starts, with no after-hours surcharge."
          }
        },
        {
          "@type": "Question",
          "name": "Do you fix the root cause or just clear the clog?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "We run a camera after clearing so you see what caused it. Tempe has a lot of 1960s and 1970s cast-iron and clay laterals that crack and let roots in. If that is the cause, we show you the footage and give a repair or lining option, so the same drain does not back up again next season."
          }
        }
      ]
    }
  ]
}
```

Note the money page references `#localbusiness` but does NOT redeclare hours/address from scratch as a second entity; the block above is shown filled only because a money page may be the first crawled page and Google should still see the full business. In production, the homepage holds the full definition and this page can carry either the full block or the `@id` reference; keep it consistent site-wide and never emit two different definitions of the same `@id`.

---

## 8b. Self-storage schema (SelfStorage facility + unit Offer + AggregateOffer)

For `brand.yaml.vertical == self-storage`, the canonical business node is `SelfStorage`. It defines no properties of its own, so there is no `unitSize`, `climateControlled`, or `gateHours` property; storage facts use `amenityFeature`, the two hour clocks, and unit `Offer`s. Full rationale: `research/self-storage-2026-07/03-schema-structured-data.md`.

### The facility node (SelfStorage)

The canonical entity for a single-facility homepage (homepage IS the facility page) and for each location page of a multi-facility brand. Same field rules as the `LocalBusiness` node in section 2, plus:

```json
{
  "@context": "https://schema.org",
  "@type": "SelfStorage",
  "@id": "https://{{domain}}/#localbusiness",
  "name": "{{business_name}}",
  "url": "https://{{domain}}/",
  "image": "https://{{domain}}/{{dated_facility_photo}}",
  "telephone": "{{phone_e164}}",
  "priceRange": "{{price_band_matching_visible_copy}}",
  "currenciesAccepted": "USD",
  "paymentAccepted": "Credit Card, Debit Card, ACH",
  "address": { "@type": "PostalAddress", "streetAddress": "{{street}}", "addressLocality": "{{city}}", "addressRegion": "{{state}}", "postalCode": "{{postal_code}}", "addressCountry": "{{country}}" },
  "geo": { "@type": "GeoCoordinates", "latitude": "{{lat}}", "longitude": "{{lng}}" },
  "hasMap": "{{gbp_map_url}}",
  "areaServed": [ { "@type": "City", "name": "{{primary_city}}" }, { "@type": "Place", "name": "{{served_zip}}" } ],
  "openingHoursSpecification": [
    { "@type": "OpeningHoursSpecification", "name": "Office hours", "dayOfWeek": ["Monday","Tuesday","Wednesday","Thursday","Friday"], "opens": "09:00", "closes": "18:00" }
  ],
  "amenityFeature": [
    { "@type": "LocationFeatureSpecification", "name": "Climate-controlled units", "value": true },
    { "@type": "LocationFeatureSpecification", "name": "Drive-up access", "value": true },
    { "@type": "LocationFeatureSpecification", "name": "24-hour gate access", "value": {{gate_access_24h_bool}} },
    { "@type": "LocationFeatureSpecification", "name": "Video surveillance", "value": true },
    { "@type": "LocationFeatureSpecification", "name": "Individually alarmed units", "value": {{door_alarm_bool}} }
  ],
  "sameAs": [ "{{gbp_profile_url}}", "{{yelp_url}}", "{{facebook_url}}" ]
}
```

The two storage rules that break a naive port from a trade page:
- **Two clocks, never conflated.** `openingHoursSpecification` = OFFICE / leasing hours ONLY. Express gate/access hours (6am-10pm, or 24-hour) via `amenityFeature` ("24-hour gate access", value from `storage.gate_access_24h`), NEVER as `opens:00:00 / closes:23:59` on the office spec (that tells a caller the office is open all night). State BOTH clocks in the visible copy. (Overlay SS-SCHEMA2.)
- **`amenityFeature` uses `LocationFeatureSpecification`** (`name` + boolean `value`). Mark `value:false` honestly for a feature the facility lacks; every marked amenity must be true and appear on the page (`amenityFeature`/`priceRange` contradicting visible copy is misleading markup).
- **NO `aggregateRating`/`review` on the `SelfStorage` node** (the self-serving wall; SS-SCHEMA1). `SelfStorage` is a `LocalBusiness`/`Organization` subtype, so `schema_validator.py`'s D3 check fires on it. Reviews live on the visible page and the GBP, never in self-node schema.

### The unit-type node (Product + Offer + UnitPriceSpecification) - unit-size / storage-type money pages

Emit ONLY where a real, current price is on the page (`storage.live_inventory == true`, or a dated static rate that matches the visible copy):

```json
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "10x10 Climate-Controlled Storage Unit - {{facility}}",
  "description": "100 sq ft climate-controlled ground-floor unit.",
  "image": "https://{{domain}}/{{unit_photo}}",
  "offers": {
    "@type": "Offer",
    "priceCurrency": "USD",
    "availability": "https://schema.org/InStock",
    "businessFunction": "http://purl.org/goodrelations/v1#LeaseOut",
    "url": "https://{{domain}}/{{city}}/10x10-storage-units",
    "priceSpecification": {
      "@type": "UnitPriceSpecification",
      "price": "{{real_monthly_rate}}",
      "priceCurrency": "USD",
      "unitCode": "MON",
      "billingDuration": 1,
      "billingIncrement": 1
    }
  }
}
```

- **`businessFunction: http://purl.org/goodrelations/v1#LeaseOut`** - a storage unit is leased, not sold. A bare `Offer` without `LeaseOut` mislabels the transaction; `schema_validator.py` flags a monthly `UnitPriceSpecification` Offer that omits it (SS-SCHEMA2).
- `UnitPriceSpecification` with `unitCode: "MON"` expresses the monthly rate. `availability` uses the enum `InStock`/`SoldOut`/`LimitedAvailability`, reflecting TRUE inventory - never fabricated or stale (SS-SCHEMA2, Law 20).
- **There is NO self-storage pricing rich result in Google Search** (a rental is not a purchasable retail SKU). This is an entity/AI-answer signal, not a SERP price chip; surface the price in the title tag and on-page copy, and never promise a client a schema-driven price chip.

### The price-range node (AggregateOffer) - a facility or size page summarizing many units

```json
{ "@type": "AggregateOffer", "priceCurrency": "USD", "lowPrice": "29.00", "highPrice": "249.00", "offerCount": "14", "availability": "https://schema.org/InStock" }
```

Values must equal the price band actually printed on the page.

### Storage do-not-emit list (extends section 2's aggregateRating rule)

1. Self-serving `review`/`aggregateRating` on the `SelfStorage`/brand node (SS-SCHEMA1; ineligible since 2019, a manual-action vector).
2. Fabricated or stale `availability`, or a price in markup that differs from the page.
3. A bare `Offer` without `businessFunction: LeaseOut` on a unit (SS-SCHEMA2).
4. 24-hour gate access encoded as an office `openingHoursSpecification` instead of an `amenityFeature`.
5. Inflated `areaServed`, or `amenityFeature`/`priceRange` that contradicts visible copy.
6. `FAQPage` promised as a rich result (deprecated 2026-05-07; keep it for AI extraction only).

Page-type schema matrix (storage): homepage/facility -> `SelfStorage` + `BreadcrumbList`; unit-size / storage-type money page -> `SelfStorage` (ref) + `Product`/`Offer` (real price only) OR `AggregateOffer` + `BreadcrumbList` + `FAQPage`; size/cost-guide asset -> `Article` + `BreadcrumbList`. Validate with `scripts/schema_validator.py` (recognizes `SelfStorage` and the `LeaseOut` check).

---

## 9. Validation (mandatory before ship)

Three gates, all must pass. A page with unvalidated schema is not done.

1. **`scripts/schema_validator.py`** (local, deterministic). Parses the `@graph`, confirms strict JSON, confirms every `@type` resolves to a real schema.org type, confirms every `@id` reference resolves inside the graph (no dangling refs), confirms dates are ISO 8601, confirms URLs are absolute, and flags fabricated-looking values (empty `{{placeholders}}` left unfilled, self-review patterns). This is the fast gate; run it on every draft.
2. **Google Rich Results Test** (https://search.google.com/test/rich-results) - the eligibility oracle for supported features. A green result confirms syntax and required fields; it does NOT confirm content parity, so passing it is necessary, not sufficient.
3. **schema.org validator** (https://validator.schema.org/) - vocabulary conformance, catches invented properties and wrong value types the Rich Results Test may let slide.

Content-parity check (human/LLM, not a validator): every schema value must match what the rendered page shows. Price in schema equals price on page. Hours in schema equal hours on page. Review count in schema equals the visible, third-party-sourced count. A mismatch here is the top manual-action cause and no tool flags it. This is a hard gate in the compliance report.

Deprecation hygiene: do not build `HowTo` for a rich result (removed 2023). Do not promise the FAQ rich result. Verify any subtype and any feature against the live Google search gallery (https://developers.google.com/search/docs/appearance/structured-data/search-gallery) before claiming an enhancement, because the supported set drifts.

---

## Sources (read this session; re-verify quarterly, the supported set drifts)

- schema.org LocalBusiness: https://schema.org/LocalBusiness
- schema.org Service: https://schema.org/Service
- schema.org Person: https://schema.org/Person
- schema.org PostalAddress: https://schema.org/PostalAddress
- schema.org GeoCoordinates: https://schema.org/GeoCoordinates
- schema.org OpeningHoursSpecification: https://schema.org/OpeningHoursSpecification
- schema.org BreadcrumbList: https://schema.org/BreadcrumbList
- schema.org FAQPage: https://schema.org/FAQPage
- Google local business structured data: https://developers.google.com/search/docs/appearance/structured-data/local-business
- Google breadcrumb structured data: https://developers.google.com/search/docs/appearance/structured-data/breadcrumb
- Google FAQ structured data: https://developers.google.com/search/docs/appearance/structured-data/faqpage
- Google search gallery (supported types): https://developers.google.com/search/docs/appearance/structured-data/search-gallery
- Google Rich Results Test: https://search.google.com/test/rich-results
- schema.org validator: https://validator.schema.org/
