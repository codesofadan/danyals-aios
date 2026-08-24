# The Linkable Local Asset: The SEO-CONTENT-OS Build Playbook

Leaf-artifact writing spec for `/write-local-asset`. A writer handed this file plus one real client brand profile (real prices, real project data, real local knowledge, real completed jobs) can produce a single local content asset that earns editorial links, gets cited by AI answer engines, and pulls third-party corroboration into the client's entity, with zero doorway risk and zero fabricated data.

This is a different job from the six conversion page types. A location page or a service-city page exists to **rank and convert** a ready-to-hire searcher. A linkable local asset exists to **earn links, citations, and mentions** that the conversion pages then inherit through the internal-link graph. It is a top-of-funnel authority asset, not a money page. Judge it on referring domains earned and answer-engine citations won, not on its own booked-lead rate.

Why the system needs this at all: link signals are roughly **15% of local relevance** (Whitespark Local Search Ranking Factors 2026, weight from secondary coverage of the gated report, directional), and the system currently produces **zero** link-worthy assets. Every conversion page competes for links it gives no one a reason to grant. A cost guide with real local prices, a data study with first-party numbers, or a genuinely useful local resource list is a reason. This playbook builds that reason.

Sibling playbooks, do not confuse:
- `location-page.md`, `service-city-page.md`, `service-page.md`, `service-area-page.md`, `homepage.md`, `about-team-page.md` - the six conversion page types. Assets support these; they do not replace them.
- `faq-page.md` - the standalone Q&A hub. An FAQ page answers many questions; a local asset goes deep on one topic with original data.

Foundation files this playbook executes:
- `knowledge/foundations/local-link-assets.md` - the strategy layer (what earns local links, outreach, measurement). Read it first; this playbook is the writing spec beneath it.
- `knowledge/foundations/passage-block-protocol.md` - every answer section is an extractable passage block.
- `knowledge/foundations/internal-linking.md` - how the asset routes earned equity to the money pages.

Every quantitative figure here is directional and carries a source and a verify flag. There is no live A/B test behind this document. Re-open the primary before printing any figure to a client.

Governing law: `knowledge/doctrine/seo-system-doctrine.md` Law 8 (method-agnostic; value over proxies), plus the local content laws that bind assets hardest:
- **Law 15 (information gain over coverage)** is the primary law for this page type. An asset that rehashes the consensus earns nothing. A cost guide that repeats the same national price range every other page cites gives no one a reason to link. The asset's whole value is the residual: the first-party number, the local data point, the operator judgment that is not already on the SERP.
- **Law 16 (experience proven, not asserted)** and **Law 17 (add statistics, citations, operator quotes)**: first-party data is both the link magnet and the moat. It is the one input a competitor's AI cannot scrape or synthesize.
- **Law 20 (no fabricated proof)**: a fabricated statistic in a "data study" is a link earned under false pretenses and a trust-penalty surface. Every number is real or the asset is not built.

---

## 1. Purpose: the one job, and the four asset types

### 1.1 The one job

A linkable local asset is one page doing three jobs at once:

1. **Earn editorial links and mentions** from local publishers, community sites, listed businesses, journalists, and resource pages, which lift the whole domain's link authority (the 15% category).
2. **Earn AI-answer citations** for the informational and "best of" queries around the client's service, where the answer engine (not the local pack) owns the SERP. Whitespark's 540-query study found AI Overviews on 92% of informational and 97% of hybrid local queries versus 15% of pure-local (whitespark.ca/blog/case-study-the-prevalence-of-ai-overviews-in-local-search/, read 2026-07-20; re-verify). Assets live squarely in that informational-and-hybrid space the conversion pages cannot reach.
3. **Route earned authority to the money pages** through contextual internal links (per `internal-linking.md`), so the links the asset earns strengthen the pages that convert.

The one job, compressed: **give the local web a real reason to link to and cite this business, built from facts only this business has.** An asset that any competitor could regenerate earns nothing, because there is nothing in it worth pointing at.

### 1.2 The four asset types this playbook builds

| Asset type | Core input (the moat) | Primary link/citation source | Primary schema |
|---|---|---|---|
| **Local cost guide** | First-party pricing data ("what we actually charge for X in [city]") | Homeowners, journalists, comparison/resource pages citing real local prices; AI cost-query citations | `Article` (+ `FAQPage` if it carries Q&A) |
| **Local data study** | Original first-party operational data (job counts, failure patterns, seasonal call data, local permit-cost analysis) | Journalists, local news, industry blogs (digital PR); AI statistic citations | `Dataset` or `Article` |
| **"Best of / top local" resource page** | Curated, genuinely useful, verified third-party local recommendations (not self-serving) | The listed businesses and community sites linking back; AI "best X in [city]" citations | `Article` + `ItemList` |
| **Neighborhood / local guide** | Deep operator knowledge of a real neighborhood or local condition | Neighborhood associations, community hubs, homeowner resources; AI local-how-to citations | `Article` (+ `FAQPage`) |

The honest boundary on "best of": the Whitespark 2026 signal that matters is **inclusion in third-party "best [service] in [city]" listicles** (someone else's page naming the client), which is a digital-PR outcome, not something the client publishes about itself. This playbook's "best of" asset is different: a **genuinely useful, non-self-serving** resource the client curates about *other* things a local customer needs (best dog parks for a mobile groomer's city, trusted specialist referrals for a plumber, homeowner resources for a roofer). That earns links from the listed parties and community and can be AI-cited; it does not claim the client is the best. A client publishing "the best plumber in [city] is us" is worthless and reads as manipulation. Never build that.

### 1.3 When to build an asset (and when not)

Build a local asset when **all** of these hold:
- The client has a **real first-party input** for it: actual prices they will publish, actual operational data, actual deep local knowledge, or a real, verifiable set of third-party recommendations. If the only input is "write a generic cost guide from what is already online", do not build it. That fails Law 15 by construction and earns nothing.
- The topic has **informational or hybrid search demand** the conversion pages cannot serve (cost questions, "how does X work in [climate]", "best resources for [local need]").
- There is a **plausible link audience**: publishers, community sites, listed businesses, or journalists who would reference it. An asset with no one to link it is a blog post, not a link asset. `local-link-assets.md` owns identifying that audience.

Do **not** build an asset when:
- The client will not release real data or real prices (then it is a rehash; skip or downgrade to a conversion page).
- The "asset" is a thin scholarship-bait or "ultimate guide" page with no first-party substance. That tactic is dead (lseo.com local link-building, read 2026-07-20; verify) and risks scaled-content-abuse classification under Google's spam policy.
- The real intent is conversion for a "[service] [city]" query. That is a money page; use the location or service-city playbook.

The build-vs-skip gate is the same shape as the location page's truthful-source rule: **no first-party substance, no asset.** The absence of real data is not a copywriting problem to paper over.

---

## 2. Target intent and the query surfaces each asset serves

Assets are written into the informational and hybrid surface, where AI answers dominate and the goal is citation, not a blue-link click.

- **Cost guide** serves "how much does [service] cost in [city]", "[service] price [city]", "is [service] worth it". Highest-value asset because cost queries are ubiquitous, AI-answered, and impossible for a national page to answer with a real local number. Perplexity cited direct business sites 73% of the time in Backlinko's experiment (backlinko.com/location-pages, read 2026-07-20; verify), so a real-priced cost guide is a Perplexity citation magnet.
- **Data study** serves "[topic] statistics", "how common is [problem] in [region]", and the journalist searching for a local stat to cite. Its job is the pickup, not the query rank.
- **Best-of / resource page** serves "best [related need] in [city]", "[city] homeowner resources". Google AI Mode and ChatGPT skew toward "best of" editorial lists (Backlinko experiment: ChatGPT favored editorial best-of lists 22% of citations; verify), so a genuinely useful list is citable there.
- **Neighborhood / local guide** serves "[neighborhood] [problem]", "living in [neighborhood] [service concern]". Deep local altitude the conversion pages only touch.

Map the client's real informational demand to these before outlining. If none maps to a real first-party input, there is no asset.

---

## 3. Section-by-section architecture, by asset type

Every asset, whatever its type, is a **federation of passage blocks** (`passage-block-protocol.md`): each H2 is a self-contained, answer-first, locally specific, extractable unit. The sections below are the type-specific spine. For each: **Must-contain / Framework / Link-and-citation logic / Schema / Anti-pattern / PASS test.**

### 3.1 Local cost guide

**Must-contain:** a real local price band for each variant, stated in the first sentence of its block ("A standard 40-to-50-gallon tank water heater in [city] runs $X to $Y installed"); the specific local drivers that move the price (code, permit fee, fuel type, local conditions); a "what is included / what is extra" breakdown; a last-updated date tied to a real content delta (Law 19); and at least one operator quote explaining a local price driver (Law 17).

**Framework:** answer-first passage blocks. Each price question is its own H2 phrased as the query. A comparison table (variant vs price band vs driver) where it genuinely helps extraction, but prose leads every block.

**Link-and-citation logic:** the first-party price is the entire link value. National cost pages (HomeAdvisor, Angi) give ranges; a real local number with real local drivers is what a homeowner, a comparison page, or an AI answer cites over the generic range. This is Law 15 in its purest form: the residual over the consensus is the real local number.

**Schema:** `Article` describing the guide; add `FAQPage` for the Q&A block (rich stars not expected since the Aug 2023 restriction, but machine-readable, see `faq-page.md`). Never wrap the business's own reviews in `Review`/`AggregateRating` here.

**Anti-pattern:** a "cost guide" that only republishes national ranges with the city name dropped in. Zero information gain, nothing to cite, doorway-adjacent. A price presented as fact that the client will not actually honor (a bait number).

**PASS test:** every price band is a real client figure or cited local data; each cost block leads with the number; at least one operator quote and one local price driver per major variant; strip the city and the numbers stop making sense.

### 3.2 Local data study

**Must-contain:** an original first-party dataset the client actually holds (e.g., "we logged 512 water heater failures across [city] over 4 years"); a headline finding stated as a citable statistic in the opening; the method in one honest paragraph (sample size, timeframe, what was and was not measured); the limitations stated plainly; and a downloadable or clearly presented data table. Every number traces to the client's real records.

**Framework:** the inverted-pyramid data story. Lead with the finding a journalist would headline, then the breakdown, then method and limitations. Law 17: statistics with a clear source lift citation; this asset is nothing but sourced statistics.

**Link-and-citation logic:** original data is the strongest link-bait that still works, because a publisher can only cite the number by linking the source. This is the digital-PR asset: it earns links through outreach to local news and industry blogs (`local-link-assets.md` owns the outreach). AI answer engines cite statistics preferentially (Law 17 evidence), so a real local stat gets pulled into answers.

**Schema:** `Dataset` (schema.org/Dataset) with `name`, `description`, `creator` referencing the `LocalBusiness`, `temporalCoverage`, and `spatialCoverage`; or `Article` if the study is narrative-led. Validate with `scripts/schema_validator.py`.

**Anti-pattern:** a fabricated or "estimated" dataset dressed as measured data. This is a Law 20 hard violation and a trust-and-legal exposure: a link earned on a fake statistic is fraud, and a journalist who catches it burns the client. If the client has no real data, there is no data study. A "study" of n=6 presented as authoritative without stating the sample.

**PASS test:** every figure traces to a real client record; sample size, timeframe, and limitations stated; headline finding is a self-contained citable sentence; nothing estimated is presented as measured.

### 3.3 "Best of / top local" resource page

**Must-contain:** a genuinely useful curated list of **verified, real, highly-rated third parties or resources** a local customer needs (not the client, and not the client's competitors dressed as endorsements); an honest, specific reason for each inclusion; the client's own relevant service positioned as *context*, not as the "best" entry; and real external links to each listed party.

**Framework:** curation as a service. The page earns its links because the listed parties and the community find it genuinely useful and link or share it. Sterling Sky names "related local business recommendations (verified real, highly rated) with external links" as a legitimate unique-content element for local pages (sterlingsky.ca service-area guide, read 2026-07-20; verify).

**Link-and-citation logic:** listed businesses and community sites link back; the page becomes the reference for "best [related need] in [city]" and is AI-citable for those queries. It also earns goodwill that supports the digital-PR ask for the client's *own* inclusion in others' best-of lists.

**Schema:** `Article` + `ItemList` of the recommended entries. Do not mark the client as the top-ranked item in `ItemList`; the list is about others.

**Anti-pattern:** a self-serving "best plumber in [city]: us" page (worthless, manipulative, never build). A list of the client's own paying partners disguised as objective recommendations (undisclosed, an FTC and trust problem). A thin directory scrape with no real reason-for-inclusion per entry.

**PASS test:** every listed party is real, verified, and genuinely recommendable; each has a specific honest reason; the client is context, not the "winner"; external links resolve; no undisclosed paid placements.

### 3.4 Neighborhood / local guide

**Must-contain:** deep operator knowledge of one real neighborhood or local condition tied to the service (the housing stock, the soil, the code, the common failure mode, the seasonal pattern); 2+ named local specifics per the location-page hard minimum; a dated real local job reference where one exists; and genuine utility for a resident, not a sales pitch.

**Framework:** the un-templated local-proof block (location-page.md 4.4) expanded to a full asset. The strip-the-city and market-insider tests apply in full: strip the neighborhood name and the guide must collapse.

**Link-and-citation logic:** neighborhood associations, community hubs, and homeowner-resource pages link genuinely useful local guides; AI answers cite them for local-how-to queries. This is the asset closest to a conversion page, so the anti-doorway discipline is strictest.

**Schema:** `Article`; add `FAQPage` if it carries a real local Q&A.

**Anti-pattern:** a city-swap "guide to [neighborhood]" template with the name as the only variable. This is the doorway pattern and the single biggest risk for this asset type. If the client has no real neighborhood knowledge, do not build it.

**PASS test:** passes the strip-the-city test; 2+ named local specifics + 1 named local condition; genuinely useful to a resident independent of hiring the client; at least one specific externally verifiable.

---

## 4. Best-in-class references (open live before quoting to a client)

Assets are harder to point to a single canonical "winner" than conversion pages, because the best ones are proprietary. Reference classes, verify each live before citing in a deliverable:

- **Cost guides:** the strongest real-priced local cost content out-cites generic national range pages precisely because it names a real local number and driver. The reference standard is the passage-block cost example in `passage-block-protocol.md` (the Tempe water-heater block) built out to a full guide.
- **Data studies:** the reference class is any local operator that has published real operational data (seasonal service-call patterns, local failure-rate analysis) and earned local-news pickup. The mechanic is original data plus outreach, not the copy alone.
- **Best-of / resource pages:** Sterling Sky's "related local business recommendations" element (sterlingsky.ca, read 2026-07-20; verify) is the doctrinal basis; a real example is any service business that curates a genuinely useful local-resource hub and earns links from the listed parties.
- **Neighborhood guides:** Backlinko cites Wade Paint Co's Sullivan's Island page (barrier-island "historic preservation requirements") as the un-templated local-hook standard (backlinko.com/location-pages, read 2026-07-20; verify live).

Method-honest note: unlike the location-page playbook, this file does not carry a single fetched-live "winner" teardown, because the best link assets are first-party and not publicly reproducible. The quality bar is the law set (15, 16, 17) and the passage-block protocol, not a copied structure.

---

## 5. The anti-thin-content rules (the heart of this page type)

The linkable asset is a scaled-content-abuse risk if built wrong, because "publish 40 local guides / cost pages" is exactly the pattern Google's spam policy targets when the pages exist to rank, not to serve (developers.google.com/search/docs/essentials/spam-policies, read 2026-07-20). Four sharp rules.

1. **The information-gain rule (Law 15, binding).** Generate the bland consensus answer for the asset's topic, then diff the draft against it. If the residual (what is in the draft but not in the consensus) is thin, the asset is a rehash and must not ship. The durable residual is first-party: the real price, the real data point, the real operator judgment, the verified local recommendation. Measured against `scripts/information_gain_scorer.py`.

2. **The first-party-input rule (the build-vs-skip gate).** Every asset must be built on a real first-party input the client actually holds and will publish. No real input, no asset. A cost guide with no real prices, a data study with no real data, a best-of list with no verified parties, a neighborhood guide with no real local knowledge: each is a rehash and each fails at the brief stage, not the draft stage.

3. **The no-fabricated-proof rule (Law 20, hard line).** Every statistic, price, data point, and recommendation is real and traceable. A fabricated number in a link asset is worse than a fabricated number on a conversion page, because the asset's purpose is to be cited: a fake stat propagates into every page and answer that cites it, and a journalist or skeptic who catches it destroys the client's credibility. If a number cannot be sourced to a client record or cited research, it is cut, never estimated-and-presented-as-fact.

4. **The genuine-utility rule.** The asset must be useful to a real person independent of hiring the client. A resident should get value from the neighborhood guide, a homeowner from the cost guide, a reader from the data study, whether or not they ever call. Utility-independent-of-the-sale is what earns the link; a thinly veiled sales page earns nothing and reads as manipulation.

The scaled-content smoke detector applies here too: watch Google Search Console index coverage across the asset cohort. "Crawled / Discovered - currently not indexed" spreading across a set of assets is the signal Google is treating them as scaled low-value content. One strong asset the operator can truthfully source beats ten thin ones.

---

## 6. Google-compliance notes specific to local assets

Every item is on `google-compliance-spine.md` as it applies to assets. All pass/fail.

1. **Scaled-content and information-gain compliance** (Section 5): every asset carries genuine first-party residual; assets are tied to real inputs, not a keyword list; flat, browseable URL structure (`/resources/`, `/guides/`, `/[city]-cost-guide/`), never an auto-generated farm.
2. **No fabricated data** (Law 20): every statistic, price, and data point real and traceable. This is the hardest line for the data study and cost guide.
3. **FTC disclosure on recommendations:** any material connection behind a "best of" recommendation (paid placement, affiliate, reciprocal deal) must be disclosed. Undisclosed paid endorsements violate FTC endorsement guides. Prefer purely editorial, unpaid recommendations.
4. **Financing / pricing claims:** a cost guide that quotes financing terms with a repayment period triggers Reg Z; flag for the client's counsel. Prices published must be prices the client will honor.
5. **Data-study honesty:** sample size, timeframe, method, and limitations stated; nothing estimated presented as measured; no cherry-picked window that misrepresents the finding.
6. **Reviews:** display any testimonials as HTML; no self-serving `Review`/`AggregateRating` markup on the business's own nodes (renders nothing since 2019, `schema-library.md`).
7. **Schema truthfulness:** `Article`/`Dataset`/`ItemList` mirrors the visible content and makes no invented claim; validate with `scripts/schema_validator.py` and Google's Rich Results Test.
8. **AI-crawler access** (handoff note to the build side): allow the answer-engine crawlers so the asset can be cited; verify current user-agent strings against each provider's list before shipping. Add the asset to `llms.txt`.
9. **No "AI-assisted content" disclosure** required by Google; the real requirement is real data and named, accountable authorship (the SME and operator quotes provide it).

---

## 7. Voice and humanization notes for assets

Governed by `knowledge/voice/` plus the client's `brand.yaml` voice. Law 8 method: humanize via real facts, never paraphrase laundering.

- **The data is the humanizer.** A real price, a real dataset, a real operator quote reads human because only a real operator would have it. Fix genericness with a fact, never a thesaurus pass.
- **Write to the person the asset serves**, not to a search engine: a homeowner comparing quotes, a resident researching a neighborhood, a journalist scanning for a citable stat. The register shifts by type (a cost guide is plain and transactional; a data study is precise and sourced), but every block leads with the answer.
- **Operator quotes carry the expertise** (Law 17). Pull the real operator's real explanation of a price driver or a local pattern and attribute it. A named operator quote is more citable and more human than any polished sentence.
- **Kill the AI tells** (`vocabulary-blocklist.md`): "in today's fast-paced world", "when it comes to", "look no further", "nestled in the heart of". A data study that opens with filler is a data study no one cites.
- **No fabrication, ever.** A missing number is an SME question, never an invention.

---

## 8. Meta, and the JSON-LD block by type

### 8.1 Meta title and description

- **Cost guide:** title `[Service] Cost in [City], [ST] (2026 Prices) | [Brand]`; description leads with the real local price band and the last-updated context.
- **Data study:** title `[Finding] - [City] [Topic] Study | [Brand]`; description leads with the headline statistic and sample.
- **Best-of / resource:** title `Best [Related Need] in [City] | [Brand]`; description names what the list covers and that it is curated/verified.
- **Neighborhood guide:** title `[Neighborhood] [Topic] Guide | [Brand]`; description leads with the local hook.

Rules: front-load the real subject; include the year only on time-sensitive assets and only with a real content delta (Law 19); no fabricated numbers in the meta.

### 8.2 JSON-LD by asset type (emit to `schema.json`)

- **Cost guide:** `Article` (+ `FAQPage` for the Q&A), `author`/`publisher` referencing the `LocalBusiness` `@id`, `datePublished`/`dateModified` matching the real content delta.
- **Data study:** `Dataset` with `name`, `description`, `creator` (the `LocalBusiness`), `temporalCoverage`, `spatialCoverage`, `variableMeasured`; or `Article` if narrative-led.
- **Best-of / resource:** `Article` + `ItemList` (`itemListElement` of the recommended parties; do not rank the client first).
- **Neighborhood guide:** `Article` (+ `FAQPage`).

Common rules: cross-reference nodes with `@id`; mirror visible content exactly; add `BreadcrumbList`; do not add self-serving `Review`/`AggregateRating`; validate with `scripts/schema_validator.py` and Google's Rich Results Test before the asset is marked done.

---

## 9. Finished-asset checklist (consolidated pass tests)

An asset is done only when every box is checked. Any single failure returns a specific error to fix and re-run (max 2 retries per the pipeline, then human queue). This is the `compliance-report.md` contract for `/write-local-asset`.

**The three gates (all binary):**
- [ ] Information gain (Law 15): the residual over the bland consensus is substantive first-party material, not a rehash.
- [ ] First-party input: the asset is built on a real client data/price/knowledge/recommendation input; nothing fabricated to fill it.
- [ ] Genuine utility: a real person gets value from the asset independent of hiring the client.

**Type pass tests:**
- [ ] Cost guide: every price is a real client figure or cited local data, answer-first per block, operator quote + local driver present, strip-the-city holds.
- [ ] Data study: every figure traces to a real record; sample, timeframe, limitations stated; headline finding is a citable sentence; nothing estimated shown as measured.
- [ ] Best-of / resource: every listed party real, verified, honestly reasoned; client is context not "winner"; external links resolve; material connections disclosed.
- [ ] Neighborhood guide: passes strip-the-city; 2+ named local specifics + 1 named condition; useful independent of the sale.

**Compliance gates (any YES = do not publish):**
- [ ] Is the residual over the consensus thin (Law 15 fail)?
- [ ] Any fabricated, estimated-as-measured, or unsourced statistic/price (Law 20 fail)?
- [ ] Undisclosed paid placement in a "best of" list (FTC fail)?
- [ ] Financing terms without Reg Z sign-off?
- [ ] Self-serving Review/AggregateRating markup present?
- [ ] Is the asset part of an auto-generated farm with no per-asset first-party input (scaled-content fail)?
- [ ] Any fabricated local fact, price, credential, or data point (hard doctrine violation)?

**Link-and-routing:**
- [ ] The asset links out to the relevant money page(s) with descriptive anchors (`internal-linking.md`), so earned equity routes to conversion pages.
- [ ] The asset is not orphaned: linked from a crawlable resources/guides hub.
- [ ] The outreach audience is identified in `sources.md` (per `local-link-assets.md`); an asset with no plausible link audience is flagged.

**Meta + schema:**
- [ ] Meta title/description front-loads the real subject, no fabricated number, year only with a real delta.
- [ ] JSON-LD: correct type per asset (`Article`/`Dataset`/`ItemList`/`FAQPage`), mirrors visible content, `BreadcrumbList` present, no self-serving review markup, validated.

**Output contract (the five files must all exist):**
- [ ] page.md, schema.json, internal-links.md, compliance-report.md, sources.md - every external fact cited, every first-party fact tagged to its client-record source.

**Post-publish monitor (hand to the client):**
- [ ] Track referring domains earned and answer-engine citations (the asset's real KPI, not booked leads); watch GSC index coverage across the asset cohort for the scaled-content smoke signal.

---

## Method note (honest)

This playbook is built on the 2026-07-20 research pass (`research/expansion-2026-07/02-local-seo-authorities.md`), which surfaced linkable local assets as an evidenced gap: links are ~15% of local relevance (Whitespark 2026, secondary/directional), "best of" inclusion is a named 2026 signal, and the system produced zero link-worthy assets. It executes local content Laws 15, 16, 17, and 20, and the passage-block protocol. Unlike the conversion-page playbooks it carries no single fetched-live "winner" teardown, because the best link assets are proprietary first-party work, not publicly reproducible structures; the quality bar is therefore the law set and the information-gain test, not a copied layout. All figures are directional and carry a source and a verify flag. Every price, statistic, data point, and recommendation in a real deliverable comes from the client's own records, the SME interview, or cited research, never invented (CLAUDE.md hard rule; doctrine Laws 8, 16, 20).
