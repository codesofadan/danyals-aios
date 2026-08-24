# Keyword Research Method (Free + Manual, No Paid APIs)

The repeatable procedure this system runs before any page is outlined. It turns a client's services, cities, and Google Business Profile categories into an intent-tagged, clustered keyword map, then maps each cluster to one of the six page types. It uses only the free, public web. No paid API is ever called.

**Doctrine Law 8 binding.** This method optimizes for real local demand and page-to-searcher fit, not for a volume count or a difficulty score sold by a tool vendor. Every keyword we keep must trace to a live signal a real searcher produced (an autocomplete suggestion, a People-Also-Ask question, a competitor page that already ranks) and must map to a page that genuinely answers it. We never harvest for breadth, never build a page to chase a string no page can honestly satisfy.

**Why manual and free.** Paid keyword tools (Ahrefs, Semrush, DataForSEO and the rest) model volume and difficulty from clickstream panels that drift from reality, cost money, and lock the method behind an account. For a single-location or small-multi-location service business the entire winnable keyword universe is small enough to build by hand from the SERP itself, which is the ground truth those tools are trying to estimate. You may glance at a free-tier tool as an optional cross-check (see 2.9), but the method must fully work with nothing but a browser, and no step here depends on one.

---

## 0. What this produces

**Scope note (read first).** Since the topical-map layer landed, node selection - deciding which pages the site should have - is owned by `topical-map-protocol.md` and executed by `/build-topical-map`. This method is now the **discovery and live-SERP engine** that feeds it: it supplies the candidate keyword variants, the intent classification, and the manual competition read for nodes the map is evaluating. The grid in §3 is the ceiling the map filters down from, not the generator of the site. Run this method inside `topical-map-architect` at site level to build the map once, and again per node (re-reading the live SERP) before each `/write-*` command.

One artifact per client, stored alongside the brand profile: a keyword map with six columns per row - `keyword | source channel | local intent tag | manual competition read | cluster | target page type`. Every row is falsifiable: it names where the keyword came from, what a real SERP for it looks like, and which single page will own it. This keyword map is absorbed into `clients/<slug>/topical-map.md` (each cluster becomes a node), and the topical map is the input to `/brief` and every `/write-*` command.

The pipeline, in order:

1. **Seed** - pull the service + geo + category spine from `brand.yaml`, then expand it across eight free discovery channels.
2. **Modifier grid** - cross the seed services against the local modifier set to generate the keyword universe.
3. **Intent** - tag every keyword with one of six local intent classes, verified against the live SERP.
4. **Manual competition read** - judge winnability by inspecting the live SERP, not a paid difficulty score.
5. **Cluster** - group keywords into page-sized units (one cluster equals one page).
6. **Map** - assign each cluster to exactly one of the six page types.

---

## 1. Ground truth: start from `brand.yaml`

Before touching Google, read the client's `brand.yaml`. It is the authoritative seed spine and it prevents inventing demand the business does not serve:

- **`services`** - every service the business actually performs. Each becomes a seed root.
- **`service_areas`** - every city, suburb, and neighborhood served (this is the field name in `brand.yaml`; there is no separate `cities` field). These become the geo modifiers. `primary_city` is the anchor and must itself appear in `service_areas`. Never generate a `[service] [city]` keyword for a city not in this list; that is how doorway pages and false-relevance signals get built.
- **`gbp.primary_category`** - the single Google Business Profile primary category. This is the head-term anchor: the site's service hubs and the homepage must reinforce it (see `local-gbp-signals.md`). The primary category is usually your single most important seed.
- **`gbp.secondary_categories`** - each maps to a secondary service hub and its own seed cluster.
- **`gbp.services`** - the service items listed on the GBP itself. These are pre-vetted seeds in the customer's own language; they must have matching pages on the site.
- **`brand_terms`** - business name, common misspellings, owner name, phone. These seed the navigational cluster.

If `brand.yaml` is thin (a new client), run `/new-client` first, or interview the operator for the service and city list before expanding. A thin seed caps the entire downstream universe.

---

## 2. Seed discovery - eight free channels

Work each channel per seed service, per top city. Record every candidate with its source channel and the date captured. Stop expanding a channel when it stops producing net-new terms.

**How an agent obtains these signals (`research-input-protocol.md`).** The channels below describe a human in an incognito browser. An agent cannot reliably fetch the JavaScript-gated ones (autocomplete, PAA) directly, so it obtains them by reliability tier: Tier A, the operator's browser-captured `clients/<slug>/research-input.md` (the autocomplete + PAA a human pasted in); Tier B, the agent's own `WebSearch` (works, always run); Tier C, `WebFetch` of the ranking competitor URLs (works for non-Google pages); Tier D, real `brand.yaml` capabilities. A candidate whose demand cannot be traced to any tier stays a flagged candidate; it is never invented (the prime rule). See `research-input-protocol.md` for the full source order and the never-fabricate rule.

### 2.1 `brand.yaml` services + GBP categories and services
Already in hand from step 1. List every service, plural and singular, plus the plain-language synonyms a customer would type (a plumber's "water heater repair" is also "hot water heater fix" and "no hot water"). GBP primary and secondary categories are seeds in their own right ("garage door repair", "garage door supplier").

### 2.2 Google autocomplete (the workhorse)
In an incognito window (logged out, so results are not personalized), type each seed followed by each city and read the dropdown suggestions. Then run the "alphabet soup" pass: type `[service] [city] a`, then `b`, then `c`, and so on, recording every suggestion. Also run question prefixes: `how much [service] [city]`, `who [service] [city]`, `best [service] [city]`. Autocomplete is aggregated real query demand straight from Google, refreshed constantly, and it is free. This channel alone usually produces the bulk of a local keyword universe.

Variations worth a pass each: `[service] near me`, `[service] in [city]`, `[city] [service]` (word order flipped), `[service] cost`, `emergency [service]`.

### 2.3 People Also Ask (PAA)
Search each `[service] [city]` and `[service]` query and read the "People also ask" box. Expand it: clicking one question spawns more. Harvest until net-new questions trail off. PAA is Google telling you the exact question phrasing it associates with the topic; these become H2s and FAQ entries as much as keywords.

### 2.4 Related searches (bottom of the SERP)
Scroll to the "Related searches" / "People also search for" block at the foot of each SERP. These are Google's own adjacency map for the query - modifiers, neighboring services, and competitor brand terms you may have missed.

### 2.5 Google Maps category suggestions
Open Google Maps and start typing the service in the search box; Maps suggests categories and related business types. Search the service in a target city and read the categories of the businesses that rank in the Maps results - those are the GBP categories your competitors chose, which tells you the category-anchored terms to target. This channel is uniquely local: it surfaces the map-pack language classic web search hides.

### 2.6 Competitor page titles, H1s, and navigation
Open the top three to five competitors that rank in the local pack and in the organic results for your head `[service] [city]` query. For each, read: the browser-tab title and on-page H1 of every service and location page, the main navigation and footer menu (their service hubs and city list), and the service menu or "services we offer" block. A competitor's site architecture is a validated map of the demand they chose to chase. Record every distinct service and city they target that the client also serves.

### 2.7 Competitor GBP services and the map pack
For each map-pack competitor, open their Google Business Profile and read the "Services" list and the "from the business" description. These are customer-language service terms already live on a ranking profile. Also note which primary category each pack competitor uses.

### 2.8 Community and review language
Search Reddit, Nextdoor, Yelp, and local Facebook groups for the service plus city. Read how real people phrase the problem before they know the industry term ("garage door won't close all the way", "spring snapped", "door off track"). Mine the client's own Google reviews and competitors' reviews for the exact words customers use for the service and the outcome. This is the most authentic phrasing and the least contested, and it feeds both keywords and the on-page copy voice.

### 2.9 Optional free-tier cross-checks (never required, never an API call)
You may glance at these to sanity-check demand, but the method is complete without them and none is called programmatically:
- **Google Keyword Planner** (free with any Google Ads account) - gives volume ranges, not exact numbers, when logged in. Directional only.
- **Google Trends** - free; useful to confirm seasonality (garage-door demand spikes with weather) and to compare two phrasings' relative interest.
- **AnswerThePublic** / **AlsoAsked** free daily limit - a faster PAA-style question harvester.
- **Ahrefs / Semrush free keyword generators or their free browser toolbars** - if the operator already has them open, a glance at their suggested terms is fine as one more idea source. Do not treat their volume or KD numbers as verdicts (see step 5), and do not build the process around them.

---

## 3. Local modifier expansion - the grid

**The grid is a ceiling, not a plan.** It generates the candidate space; it does not decide which pages exist. `topical-map-protocol.md` filters this grid down to the real map in three passes: the demand filter below, a user-cluster merge (behaviorally-identical geographies collapse into one node), and an evidence gate (a cell becomes a full page only when the client has a first-party specific that makes that page un-copyable; otherwise it stays a coverage-index line). Build the grid honestly here; let the map protocol reduce it. Never treat a full grid as a page list - that is a doorway farm.

This is where a handful of seed services becomes the full keyword universe. Build a grid: **rows are the seed services** (from 2.1 plus every service surfaced in discovery); **columns are the local modifiers**. Each filled cell is a candidate keyword.

The local modifier set (the columns):

| Modifier class | Pattern | Example (service = "garage door repair") | Signals |
|---|---|---|---|
| Bare service | `[service]` | garage door repair | broad, usually homepage/service hub |
| City | `[service] [city]` / `[city] [service]` | garage door repair Tempe | the money-page core |
| Neighborhood / suburb | `[service] [neighborhood]` | garage door repair Warner Ranch | hyper-local, low competition |
| Near me | `[service] near me` | garage door repair near me | high-intent, proximity-driven |
| In-city phrasing | `[service] in [city]` | garage door repair in Mesa | money-page variant |
| Emergency / speed | `emergency / 24 hour / same day [service] [city]` | emergency garage door repair Gilbert | urgent, highest conversion |
| Cost / price | `[service] cost / price / estimate / quote [city]` | garage door spring replacement cost | commercial-investigation |
| Best / top / reviews | `best / top [service] [city]` | best garage door repair Tempe | comparison, considered |
| Brand | `[brand] [service/city]` | [Client Name] garage door | navigational |

Cross every service row against every modifier column, then against every city and neighborhood in `brand.yaml`. Discard cells that produce no real query (confirm against autocomplete and PAA - if nobody suggests it and no SERP exists, it is not demand). What remains is the keyword universe: usually a few hundred rows for a single-location business, more for multi-city.

Keep the grid honest to the client's real footprint. A city the business does not serve does not get a row, no matter how much volume it looks like it has.

---

## 4. Intent classification - six local classes

Tag every surviving keyword with exactly one primary local intent class. Cross-reference `search-intent-taxonomy.md` for the full taxonomy; the six classes used for local service keywords are:

1. **local-pack** - the searcher wants a nearby provider to hire now. Signals: a "near me", "[service] [city]", or "in [city]" phrasing; the live SERP renders a Map pack above the organic results. This is the dominant class for a service business and it maps to the money pages.
2. **emergency** - a local-pack intent with acute urgency and low price-sensitivity. Signals: "emergency", "24 hour", "same day", "broken", "won't close". SERP shows the map pack plus ads and "open now" filtering. Highest conversion value; often its own page or a prominent page section.
3. **considered** - the searcher is comparing providers before committing. Signals: "best", "top", "reviews", "[service] company [city]". SERP mixes the map pack with listicles and directory pages (Yelp, Angi). Maps to service and service-city pages that surface proof and reviews.
4. **commercial-investigation** - the searcher is researching the buy but is not yet choosing a vendor. Signals: "cost", "price", "how much", "estimate", "[service] vs [service]". SERP shows informational articles and cost-guide pages, sometimes with a map pack. Maps to a page section (a cost/pricing block) or a supporting page, not usually its own money page.
5. **informational** - the searcher wants to understand the problem, not hire yet. Signals: "how to", "why", "what causes", "signs of". SERP is articles, PAA, sometimes an AI Overview, rarely a map pack. Mostly out of scope for these six page types (route to a blog in the sister workspace) unless it earns an FAQ block on a money page.
6. **navigational** - the searcher already knows the business. Signals: brand name, "[brand] phone", "[brand] hours". SERP is dominated by the brand's own properties. Maps to the homepage, about page, and GBP.

**The live SERP is the tiebreaker, always.** When the string looks like one class but the ranking pages are another, the SERP wins - it already passed Google's real intent test. Pull the live top ten for any keyword whose class is ambiguous or commercially important, and classify by what actually ranks. Do not ship a page on the string-guess alone for any money keyword.

---

## 5. Free difficulty and opportunity read (manual SERP inspection)

We do not buy a Keyword Difficulty score. We read the live SERP, which is what a KD score is estimating anyway, and judge winnability directly. For each head keyword in a cluster, search it logged-out and answer:

- **Is there a local pack?** If yes, ranking is a Google Business Profile game as much as a content game (see `local-gbp-signals.md`). A strong, category-matched, review-rich GBP plus a genuinely local page usually wins the pack for a single city. This is the single most winnable and most valuable surface for a service business.
- **Who holds the organic top spots?** Read the domains. If they are **directories and aggregators** (Yelp, Angi, Thumbtack, HomeAdvisor, Nextdoor), that is a *weak* organic SERP - a real local business with a specific page can outrank a directory listing. This is an opportunity, not a wall. If they are **strong local competitors with dedicated, deep `[service] [city]` pages**, the bar is higher and you win on specificity and proof, not on beating their domain.
- **How deep are the ranking pages?** Open the top two or three. Thin, templated, near-duplicate city pages are beatable with a genuinely specific page. Deep pages with real local detail, photos, reviews, and pricing set the bar you must clear.
- **Do the same competitors rank across many of your city keywords?** If one competitor owns Tempe, Mesa, and Gilbert with a page each, they have proven the money-page pattern works; you match the pattern and beat it on local specificity.
- **What SERP features fire?** Map pack (local-pack intent confirmed), PAA and AI Overview (informational lean, more zero-click, judge on whether a click is still winnable), ads and shopping (transactional, expect paid competition).

Grade each cluster simply: **Win now** (weak/directory SERP, or a pack you can enter with a solid GBP + specific page), **Winnable with depth** (real competitors, beatable on specificity and proof), or **Hard/defer** (entrenched deep local incumbents plus a locked pack). Sequence the roadmap Win-now first. This read is free, honest, and more useful than a black-box difficulty number because you are looking at the exact thing you have to beat.

---

## 6. Clustering - one cluster equals one page

Group the keyword universe into page-sized clusters. The rule: **a cluster is the set of keywords one page can satisfy without splitting its intent.** Two keywords belong in the same cluster when they share the same intent class *and* the same live top-ten largely overlaps (search both, and if the ranking pages are mostly the same URLs, one page can serve both).

Practical grouping for local service keywords:

- All phrasings of **one service in one city** cluster into one page: `garage door repair Tempe`, `garage door repair in Tempe`, `garage door repair Tempe AZ`, `Tempe garage door fix`, `emergency garage door repair Tempe` (the emergency variant may earn its own section or page if urgency and volume justify it). One cluster, one money page.
- All phrasings of **one service across the whole brand** (no city, or "near me") cluster into the brand-wide service page: `garage door repair`, `garage door repair near me`, `garage door repair company`.
- **Cost/price** phrasings for a service cluster into a pricing section or a supporting page, not usually a standalone money page.
- **Brand** phrasings cluster to the homepage/about.

Keep clusters to a page's worth (roughly a handful to a dozen close variants). If a cluster needs two genuinely different H1s to answer it, it is two clusters. If two clusters would produce near-identical pages, they are one cluster (this is how you avoid cannibalization and doorway pages). Before finalizing, check the client's existing pages: if a page already targets a cluster, upgrade it rather than building a competing URL.

---

## 7. Mapping clusters to the six page types

Each cluster maps to exactly one page type:

| Cluster shape | Dominant intent | Page type | Command |
|---|---|---|---|
| One service x one city (`[service] [city]`, `in [city]`, emergency-[city]) | local-pack | **service-in-city combo page (money page)** | `/write-service-city-page` |
| One service, brand-wide, no single city (`[service]`, `[service] near me`, `[service] company`) | local-pack / considered | **service page** | `/write-service-page` |
| One city, all services (`[city] [trade]`, `[trade] in [city]`, general local presence) | local-pack | **location page** | `/write-location-page` |
| Broad coverage across many served areas without one primary storefront city | local-pack (service-area business) | **service-area page** | `/write-service-area-page` |
| Head term + brand + primary category, the entity anchor | navigational / local-pack | **homepage** | `/write-homepage` |
| Brand, owner, trust, credentials, "[brand] reviews", "about [brand]" | navigational / considered | **about page** | `/write-about-page` |

Notes on the two easily-confused pairs:

- **service page vs service-in-city combo page.** The service page ranks the service brand-wide and for "near me"; the combo page ranks one service in one named city and is the primary money page. A multi-city business builds one service page per service *and* one combo page per service-city pair it can support with genuine local depth.
- **location page vs service-area page.** A location page is for a real, staffed city presence and targets that city across the services (`[trade] [city]`). A service-area page is for a service-area business (SAB) with no public storefront in a given area, covering the coverage footprint without spinning up thin per-city doorway pages. Which one applies is fixed by the client's real address model in `brand.yaml` and its GBP (see `local-gbp-signals.md`), not by keyword volume.

Commercial-investigation (cost/price) and informational clusters usually become sections (a pricing block, an FAQ) inside the mapped money page rather than their own pages, unless a cluster is large enough to earn a supporting page.

---

## 8. Worked example: garage door repair, Tempe / Mesa / Gilbert AZ

A single-owner garage-door-repair company, storefront in Tempe, serving Tempe, Mesa, and Gilbert. `brand.yaml` says:

- `services`: garage door repair, garage door spring replacement, garage door opener repair, garage door installation, off-track door repair.
- `service_areas`: Tempe, Mesa, Gilbert (plus neighborhoods: Warner Ranch, Dobson Ranch, Val Vista Lakes). `primary_city`: Tempe (also in `service_areas`).
- `gbp.primary_category`: Garage door supplier. `gbp.secondary_categories`: Garage door repair service.
- `brand_terms`: "Desert Door Pros", "(480) 555-..."

**Seed list (steps 1-2).** From `brand.yaml`: the five services plus the two GBP categories. Autocomplete on "garage door repair Tempe" yields: `...near me`, `...cost`, `...same day`, `...spring`, `...broken spring`, `...opener`, `...off track`. PAA on the head term yields: "How much does it cost to fix a garage door?", "Why won't my garage door close?", "Is it worth repairing a garage door?", "How long does garage door spring replacement take?". Related searches surface: "garage door repair Mesa", "24 hour garage door repair", "garage door companies near me". Maps category suggestions confirm competitors use "Garage door supplier" and "Garage door repair service". Competitor nav (top pack player) shows service pages for repair, springs, openers, installation, and city pages for Tempe, Mesa, Gilbert, Chandler. Reviews use "spring snapped", "door came off the track", "wouldn't go up".

**Modifier grid (step 3), sampled.** Services (rows) x modifiers (columns), crossed against the three cities:

| Service | +city | +near me | +emergency/same-day | +cost | +best |
|---|---|---|---|---|---|
| garage door repair | garage door repair Tempe / Mesa / Gilbert | garage door repair near me | same day garage door repair Mesa | garage door repair cost | best garage door repair Tempe |
| garage door spring replacement | garage door spring replacement Gilbert | broken spring repair near me | emergency spring replacement Tempe | garage door spring replacement cost | - |
| garage door opener repair | garage door opener repair Mesa | opener repair near me | - | opener repair cost | - |
| garage door installation | new garage door installation Gilbert | - | - | garage door installation cost Tempe | best garage door installers Gilbert |
| off-track door repair | off track garage door repair Tempe | garage door off track near me | emergency off track repair Mesa | - | - |

**Sample of the expanded universe with intent tags and manual competition read:**

| Keyword | Source channel | Intent | Manual SERP read |
|---|---|---|---|
| garage door repair Tempe | autocomplete + competitor nav | local-pack | Map pack + directories organic -> Win now |
| emergency garage door repair Mesa | related searches | emergency | Map pack + ads, thin competitor pages -> Win now |
| garage door spring replacement cost | PAA + autocomplete | commercial-investigation | cost-guide articles, no pack -> section/FAQ |
| best garage door repair Gilbert | autocomplete | considered | Yelp/Angi listicles dominate -> Winnable with depth |
| garage door repair near me | autocomplete | local-pack | Map pack, strong locals -> service page |
| off track garage door repair Tempe | competitor H1 | local-pack/emergency | weak SERP -> Win now |
| Desert Door Pros | brand_terms | navigational | brand owns SERP -> homepage/about |
| why won't my garage door close | PAA | informational | articles + AIO -> FAQ block only |

**Clusters (step 6) and page-type mapping (step 7):**

1. **Cluster A - garage door repair in Tempe** (repair + in-Tempe + near-me-Tempe + emergency-Tempe + off-track-Tempe). Intent local-pack. -> **service-in-city combo page (money page)**, `/write-service-city-page`. Repeat the identical cluster shape for Mesa and Gilbert = three money pages. Emergency and cost phrasings become prominent sections inside each.
2. **Cluster B - garage door spring replacement (brand-wide)** (spring replacement, broken spring, near me, cost). Intent local-pack + commercial-investigation. -> **service page**, `/write-service-page`, with a spring-cost section absorbing the commercial-investigation terms. (Spin per-city combo pages only where the SERP and demand justify them.)
3. **Cluster C - Tempe (all services, staffed city)** (garage door company Tempe, garage door service Tempe, Warner Ranch coverage). Intent local-pack. -> **location page** for Tempe, `/write-location-page` (this is the storefront city).
4. **Cluster D - brand + trust** (Desert Door Pros, reviews, about, owner). Intent navigational/considered. -> **homepage** (`/write-homepage`, anchoring the "Garage door supplier / repair service" entity) and **about page** (`/write-about-page`).

Mesa and Gilbert, if not staffed storefronts, are handled as service-in-city combo pages (Cluster A pattern) rather than full location pages; if the business is a pure SAB with no public address, the coverage across all three cities routes to a **service-area page** (`/write-service-area-page`) instead of per-city location pages. The address model in `brand.yaml` and the GBP decide this, not the keyword volume.

---

## 9. Keyword -> page-type mapping reference

The quick lookup, independent of the worked example:

| Keyword pattern | Local intent | Page type | Command |
|---|---|---|---|
| `[service] [city]` / `[service] in [city]` / `[city] [service]` | local-pack | service-in-city combo (money page) | `/write-service-city-page` |
| `emergency / same-day / 24-hour [service] [city]` | emergency | section within the combo page (or its own page if demand is large) | `/write-service-city-page` |
| `[service]` / `[service] near me` / `[service] company` | local-pack / considered | service page | `/write-service-page` |
| `[service] cost / price / estimate` | commercial-investigation | pricing section / supporting page | (section of the mapped money page) |
| `best / top [service] [city]` / `[service] reviews [city]` | considered | combo or service page (surface proof + reviews) | `/write-service-city-page` or `/write-service-page` |
| `[trade] [city]` (city hub, all services, staffed) | local-pack | location page | `/write-location-page` |
| coverage across many served areas, no single storefront city | local-pack (SAB) | service-area page | `/write-service-area-page` |
| head term + primary GBP category + brand (entity anchor) | navigational / local-pack | homepage | `/write-homepage` |
| `[brand]` / `about [brand]` / `[brand] reviews` / owner / credentials | navigational / considered | about page | `/write-about-page` |
| `how to / why / what causes [problem]` | informational | FAQ block on a money page (or out of scope -> blog) | (section, or sister workspace) |

**Vertical specialization: self-storage.** For a self-storage client (`brand.yaml.vertical == self-storage`), the generic modifier grid in section 3 and the page-type mapping in sections 7 and 9 are replaced by the storage-specific versions in `knowledge/foundations/storage-topical-map.md`: the storage query-cluster library (clusters A-J, each with its dominant intent and the ONE page type it wants), the storage grid's four axes (facility x unit-size x storage-type x audience, crossed with geography), and the storage page types (facility, unit-size, storage-type, audience) and their commands. Use that file's cluster library as the candidate-expansion source, then apply the demand filter and the storage evidence gate exactly as here.

Run this method inside `/build-topical-map` (the `topical-map-architect` agent) once per client to produce `clients/<slug>/topical-map.md`, then re-read the live SERP for a node before each `/write-*` command so the page is built against the SERP as it is today, not as it was when the map was first made. Node selection (which clusters become pages) is gated by `topical-map-protocol.md`, not by this method alone.
