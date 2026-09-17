# Local SEO 2026 playbook - operational version

Loaded by: D1 (GBP), D2 (Citations + NAP), D3 (Reviews), D4 (Local Pack + Geo).
Sources: D:\AIOS\context\strategy\local-seo-ai-os-complete-blueprint.md; D:\AIOS\context\strategy\citation-backlink-automation-reality-2026.md; Andrew Shotland and Joy Hawkins commentary on 2025-2026 algorithm changes.

## What changed in 2025-2026 (relative weights for the local pack)

Approximate weights synthesized from public commentary and Local Search Ranking Factors surveys (May 2026):

- GBP signals (categories, completeness, posts, photos): ~28%
- Reviews (count, recency, velocity, owner response, sentiment): ~22%
- On-site signals (LocalBusiness schema, geo content, NAP, internal links): ~16%
- Citations (presence + NAP consistency on tier-1 and aggregators): **~13% (up from ~6% in 2024)**
- Links (referring domains, local relevance, niche relevance): ~10% (down from ~14%)
- User behavior (CTR, dwell, return visits): ~6%
- Personalization (user proximity, history): residual; not actionable

Citations rose because AI-search citation ecosystems (Otterly, Profound, AthenaHQ data) confirmed AI engines weight directory consensus heavily when ranking businesses in answer overviews.

## The 12 pillars (consolidated from AIOS strategy file)

1. **GBP optimization** - the single highest-leverage asset
2. **Citations** - tier-1 + aggregators + industry
3. **Reviews** - count, recency, velocity, owner response
4. **NAP consistency** - on-site footer + every citation + GBP must match
5. **LocalBusiness schema** - on the home page minimum, on every location page if multi-location
6. **Geo-targeted content** - city + neighborhood pages; non-boilerplate
7. **Local backlinks** - chambers of commerce, local press, local business associations
8. **Service area definition** - explicit on GBP, on site, in schema
9. **On-page UX** - mobile, page speed, clear CTAs
10. **Technical hygiene** - sitemap, indexability, redirects, hreflang if multi-language
11. **AI search citability** - llms.txt, structured answers, schema, semantic HTML
12. **Reputation management** - review responses, sentiment monitoring, brand SERP audit

## GBP rules of thumb

- Primary category must match the dominant service. "General Contractor" for a plumbing business is critical.
- Up to 9 secondary categories; use them all, relevantly.
- Photos: target 10 across exterior + interior + team + work. Geo-tagged where possible.
- Posts: weekly cadence in 2026 is baseline; stale > 30 days = minor finding.
- Q&A: owner-posted FAQs at the top; respond to customer questions within 48 hours.
- Hours: every weekday + special hours for known holidays.
- Service area: bounded service area (radius or list of cities) defined explicitly.

## Citation tier-1 (for service businesses)

GBP, Apple Business Connect, Bing Places, Yelp, Facebook Page, Foursquare. Missing any tier-1 = critical.

## Citation aggregators (downstream feed for 50+ directories each)

Foursquare, Localeze (Neustar/Data Axle), Acxiom. Missing any = major.

## Industry-specific citations to add per niche

- Plumbers: Angi, HomeAdvisor, Thumbtack, BBB
- Dentists: Healthgrades, Zocdoc, Vitals
- Lawyers: Avvo, FindLaw, Justia, Lawyers.com
- Restaurants: OpenTable, TripAdvisor, Zomato
- Auto: Cars.com, AutoTrader, Edmunds
- Home services: Houzz (contractors, designers), Porch

## Review acquisition baseline

- 25+ Google reviews to be competitive in mid-sized markets
- 4.0+ rating to avoid suppression
- 2-4 new reviews per month for "healthy velocity"
- Owner responses on > 80% of reviews, every negative one responded to
- Avoid review buying or filtering - reputation manipulation is detectable and penalized

## NAP exactness

The variants below count as inconsistent in Google's matcher:
- "Suite 100" vs "Ste. 100" vs "#100"
- "+92 300 123 4567" vs "+923001234567" vs "(0300) 123-4567"
- "St" vs "Street"
- Old phone numbers still listed in legacy directories

When the audit detects variants, recommend ONE canonical NAP and a worklist of directories to update.

## Local pack geo-grid coverage targets

- Center + 1-mile ring: top-3 in > 80% of probes
- 3-mile ring: top-3 in > 60%
- 5-mile ring: top-10 in > 60%
- Beyond service area: not relevant; do not flag

## How D4 uses this when generating findings

D4 reads the geo-grid probe data and names the dead zones. "Top-3 at center and 1-mile, drops to top-10 at 3-mile NE and SE, not ranked beyond 5 miles. Competitor X (DA 38, 287 reviews) dominates East-side coverage."
