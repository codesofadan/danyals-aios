# 06 - Editorial Process, Measurement, and Content Lifecycle

Research territory: editorial workflow + measurement loop + content lifecycle (decay/refresh) + internal linking at scale + QA scoring + local measurement without APIs.

Fetched live 2026-07-20 PKT. All URLs verified this session. Critical read applied throughout.

The system's biggest current gap: it GENERATES pages but has no post-publish loop. Doctrine Law 6 (measure or you are guessing), Law 10 (the brain is files that compound), Law 11 (terminate in a verified action) are all unenforced after FINALIZE. This document designs the missing back half of the lifecycle: PUBLISH -> MEASURE -> DECIDE -> REFRESH, plus the QA scoring and internal-linking-at-scale layers that make the front half auditable.

---

## Part 1 - World-class editorial workflow (what the best teams actually do)

The reference operators (Animalz, Grow and Convert, Siege Media, Ahrefs, Semrush) do not differ much on the write half. They differ on two things this system lacks: a **scored gate** before publish, and a **measured loop** after publish.

### Grow and Convert - SME-first, conversion-first
- Start every client with a series of calls across departments (sales, customer success, product) to extract product truth before touching a keyword tool. "Unique brand perspective before SEO tools."
- Pain-point-driven long-form aimed at high-intent, mid/bottom-funnel queries competitors ignore.
- Source: https://www.growandconvert.com/content-marketing/content-creation-process/ (fetched 2026-07-20)
- Read for this system: our SME interview stage already mirrors this. The gap is that G&C's process is explicitly **conversion-measured** (they report Pain-Point SEO revenue, not traffic). Our loop must close on lead/call outcomes, not rankings alone.

### Siege Media / general agency QA - the release checklist
- Content passes a framework checklist (edited? internally linked? metadata?) before it ships. QA is a "release checklist for blog posts and landing pages" that also verifies the asset "continues to meet standards as it ages."
- Source: https://www.siegemedia.com/strategy/on-page-content-marketing-best-practices ; QA-checklist concept: https://easycontent.io/resources/how-to-implement-an-editorial-qa-checklist/ (fetched 2026-07-20)
- Read: the phrase "continues to meet standards as it ages" is the whole thesis. QA is not a one-time gate; it is re-run on a cadence. Our `/qa` command should be runnable against a LIVE published page, not only a fresh draft.

### The editorial arc the best teams run
brief -> draft -> edit -> QA (scored) -> publish -> measure -> refresh. Our pipeline covers brief -> ... -> gate -> finalize. Everything from **publish onward is missing.**

---

## Part 2 - Editorial QA scorecard (score before publish)

Top teams convert "did an editor look at it" into an explicit rubric so quality holds as throughput scales with AI. The best public rubric found:

### Search Roost editorial QA scorecard - 6 categories, pass/needs-work, 3-fail kill
Source: https://searchroost.com/blog/editorial-qa-scorecard-ai-writing (fetched 2026-07-20)

| # | Category | What it checks |
|---|---|---|
| 1 | Sourcing | Every meaningful factual claim has a reputable source; no invented quotes/dates/numbers; inline citations |
| 2 | Structure & clarity | H2/H3 hierarchy, skimmable, TL;DR, facts separated from analysis |
| 3 | Duplication control | Unique primary keyword, title, slug; intentional canonical/noindex |
| 4 | Internal linking | 2-4 relevant internal links including >=1 hub |
| 5 | Metadata & images | Unique meta title/description, descriptive alt text |
| 6 | Technical baseline | Indexability, structured data, site-checklist alignment |

Scoring: each item Pass / Needs-work. **Publication gate: if 3+ items fail, do not publish.** Explicitly framed as the "editorial approval gate" that keeps quality stable "as AI increases throughput."

Read for this system: we already enforce most of this qualitatively inside `knowledge/quality-gates/` and the compliance spine. What we lack is a **single numeric scorecard artifact** emitted per page (a scorecard file), so quality is auditable and trendable across a client's whole page set. This maps 1:1 onto our existing Output contract (add `scorecard.md`). It also gives the refresh loop its baseline: you re-score an aging page against the same rubric.

### Fact-checking / originality without detector-gaming
- The scorecard anchors fact-checking to Google's own guidance: "all meaningful factual claims have reputable sources," no "invented quotes, dates, or numbers," link sources inline, summarize sources at document end.
- This is exactly our `sources.md` output and Law 8 stance. **No plagiarism-detector or AI-detector gate** - consistent with our hard line. Originality is enforced by construction (real local facts, SME specifics), and verified by the Sourcing category, not by a detector score.
- Our advantage over the reference teams: our `sources.md` contract already forces provenance on every fact. Most teams bolt fact-checking on; we have it native. The scorecard just makes it pass/fail visible.

---

## Part 3 - Content decay + refresh system (THE priority - biggest gap)

This is the highest-leverage addition. The data on refresh lift is strong and consistent across independent operators.

### The lift data (why this matters)
- Organic content decays at an average **-1.21% per week** once it begins to decline (Animalz, citing 2018 analysis). Source: https://www.animalz.co/blog/content-refresh (fetched 2026-07-20)
- Updated posts see a **median 106% increase** in organic traffic; republished pages jump an **average 4.6 SERP positions** (Ahrefs). Source: https://ahrefs.com/blog/content-decay/ (fetched 2026-07-20)
- A single AdEspresso refresh: **+30,000 pageviews, +55% weekly traffic** (Animalz case).
- Ahrefs individual posts: 680 -> ~4,000 visits in 7 months (+500%); 350 -> 1,050 (+302%) after republish.
- **Quarterly refreshes yield 42% better results than annual** (Animalz), because AI systems favor recent content.
- Freshness and AI citation: AI-cited content is **25.7% fresher** than organic Google results; **76.4% of ChatGPT top-cited pages** were updated within the last 30 days; content updated within 30-90 days is cited at substantially higher rates across ChatGPT, Perplexity, and Google AI Overviews. Sources: https://ahrefs.com/blog/fresh-content/ , https://www.conbersa.ai/learn/freshness-signals-for-ai-search-ranking (fetched 2026-07-20)
- Freshness caveat (critical): AI crawlers compare current content to their cached version. **If only the date changed and content is identical, the freshness signal is discounted.** A date bump alone does nothing. The refresh must materially change content. This kills the lazy "update the date" tactic and validates our substance-over-signal doctrine.

### Decay detection with GSC only (no API) - the workflow to codify
Best operational spec found: Click Laboratory GSC+GA4 monthly workflow. Source: https://www.clicklaboratory.com/content-analytics/content-decay-monitoring-workflow/ (fetched 2026-07-20). Corroborated by SEOJuice and ContentForce.

**Export monthly (manual GSC export -> CSV, no API):** clicks, impressions, CTR, average position, grouped by page, 28-day window vs prior 28-day window, same property and filters every month. GA4 organic landing-page sessions/conversions on matching windows. Use YoY when available; MoM alone is noisy.

**Flag rules (per Tier-1 URL):**
| Signal | Threshold |
|---|---|
| Impressions down | 15%+ for two consecutive months |
| Clicks down | 20%+ with flat/down impressions |
| CTR down | 1+ point at similar position |
| Position down | 2+ positions on primary query |
| Engaged sessions down | 20%+ on organic |

Decision: **1 flag = watch; 2 flags = diagnose this month; 3 flags = schedule refresh** (unless an external cause is documented, e.g. a known algo update or seasonality).

Cross-check (Animalz six triggers, same shape): >20% organic decline over 90 days; ranking drop >5 positions; falling CTR at stable impressions; declining AI citations; rising bounce; no new backlinks in 6+ months.

Alternative threshold (ContentForce/SEOJuice): three consecutive 28-day periods with >=20% click decline AND >=2 position drop = structural decay. Use the stricter of the two for local (local sites have lower volume, so noise is higher; require the 2-consecutive-period confirmation before spending a refresh slot).

### URL tiering (so we don't chase noise)
- **Tier 1:** 30-50 URLs by revenue/pipeline influence -> monthly deep review. For a local client this is the money pages: service-in-city combos + homepage + top location pages.
- **Tier 2:** mid-tail, supporting cluster -> quarterly.
- **Tier 3:** low-traffic, high-backlink -> annual or trigger-based.
- Master sheet fields: URL, tier, owner, target keyword, last-refresh date, primary conversion event.

### Refresh vs prune vs consolidate (the decision matrix)
Animalz three-way call:
- **Refresh:** has backlink equity + valuable keywords, needs updated info or better structure.
- **Prune:** no backlinks, rankings, or traffic; topic covered better elsewhere.
- **Consolidate:** multiple thin pages on similar keywords -> merge into one authoritative page. (For local: two overlapping service-area pages that are near-duplicates are BOTH a decay problem and a doorway-page risk - our doctrine already forbids the near-duplicate, so consolidation doubles as compliance cleanup.)

### The six refresh strategies (what to actually do to a flagged page)
1. **Expand** - match top-competitor depth; fill gaps with original examples/data/SME specifics.
2. **Update** - replace outdated stats/prices/screenshots, fix broken links, add visible last-updated date + `dateModified` schema.
3. **Refine on-page** - title/meta/headers/alt, semantic-term gaps.
4. **Retarget** - align to a higher-value keyword if intent shifted.
5. **Merge** - consolidate overlapping pages.
6. **Repromote** - redistribute (less relevant for local web pages; relevant for GBP posts).

### Capacity discipline (a real finding, not fluff)
"Most teams ship 3-5 meaningful updates per month without starving new content." Keep the refresh watchlist smaller than refresh bandwidth to avoid a guilt-driven backlog. For a solo/small shop running many local clients, cap refreshes per client per month and let the flag-priority score choose.

### Refresh scope checklist (per page that earns a slot)
Intent check (read top queries, search incognito) -> fact/example updates + last-updated date -> structure pass (H2s mirroring buyer questions, direct-answer paragraphs = our passage-block protocol) -> internal links to newer hubs -> snippet test if CTR-flagged (rewrite title/meta, run 4 weeks) -> **write a one-sentence hypothesis before publishing, review lift at 30-60 days.** That hypothesis-then-verify step is Law 11 (terminate in a verified action) made concrete.

### Portfolio health metrics (quarterly)
Share of Tier-1 URLs with zero flags (health rate); avg Tier-1 clicks (rolling 90d); **refresh win rate** (% improved within 60 days); decay-backlog age (avg days before action). These are the KPIs that prove the loop works.

---

## Part 4 - Internal linking at scale (as pages are added)

Sources: https://www.searchenginejournal.com/hub-spoke-internal-links/442005/ , https://searchengineland.com/guide/website-structure , https://blog.hubspot.com/website/silo-seo (fetched 2026-07-20)

### The model for a growing local site
"Organize like silos, link like clusters." Each **service** is a silo; each **location** cross-links where relevant. Hub-and-spoke: the service hub (or city hub) is the authority node; service-in-city combos are spokes.

### Link-equity routing rules
- Hubs receive **more inbound internal links** than spokes. When an external backlink lands on any spoke, equity flows back to the hub through internal links and the whole cluster rises together.
- Direction: spoke -> hub (mandatory, every spoke links up); hub -> spoke (the hub lists/links its spokes); spoke -> spoke only where context genuinely supports it (avoid over-linking).
- Anchor text to commercial pages should match transactional/commercial-intent queries, not general informational anchors, and not be "overly branded." Place links "at appropriate junctures," never shoe-horned.
- Do NOT mass-link 30 pages from one page. John Mueller: too many links "makes it harder for search engines to understand the context of the individual pages." Distribute links across template zones (contextual body links + a curated "related" block), not a wall of links.

### Managing it as the site grows
Treat each hub "as its own microsite" with **template-based linking** so a new spoke inherits the structure automatically (secondary nav + related-content block) without hand-wiring every page. Method: content inventory + topical map -> pilot link rules on one cluster -> roll out with staged checks on link equity and CTR.

Read for this system: we already have `foundations/internal-linking.md` and `cluster-graph-protocol.md`, and each page emits `internal-links.md`. The gap is a **site-level link graph** that persists and updates as pages are added - right now linking is decided per-page with no memory of the whole graph. This is a compounding-brain (Law 10) opportunity: a per-client link-graph file that every new page reads and updates, so the Nth page links correctly into the existing N-1 without re-deriving the structure.

---

## Part 5 - Measurement that matters for local (close the loop, no APIs)

Sources: https://www.semrush.com/blog/tracking-local-seo-performance/ , https://www.dreamhost.com/blog/tracking-measuring-local-performance/ , https://bippermedia.com/seo/local-seo-reporting-dashboard/ , https://agencyanalytics.com/blog/seo-kpis (fetched 2026-07-20)

### Three data layers for local
1. **Geo-grid rank tracking** - the single most revealing local tool. Track 9-16 points across a 3x3 or 4x4 grid; city-center-only checks miss micro-local variation. Free/manual method: incognito + location-set searches, or free local-rank-checker tools (no login). Log positions per grid point per money keyword to a sheet.
2. **GBP Performance insights** - calls, website clicks, direction requests, search vs maps appearances, tied directly to the Maps listing. Manual monthly read from the GBP dashboard (no API). Note: Google has trimmed some historical GBP metrics, so capture monthly or lose the series.
3. **GA4** (free) - organic landing-page sessions, engaged sessions, key conversion events (form submits, click-to-call). Clean attribution trick: add **UTM parameters to the website URL in GBP settings** so GBP-driven clicks are separable from organic web.

### Call tracking basics (no paid platform required)
Cleanest free approach: GA4 events for click-to-call (`tel:` link clicks) as key events; UTM-tag the GBP link. Paid call-tracking (dynamic number insertion) is the upgrade path but not required to start - measure click-to-call intent first.

### Conversion measurement
GA4 key events for form submissions and calls. Tie each money page to its **primary conversion event** (already a field in the decay master sheet). This is what makes the loop close on outcomes, not vanity traffic - matching Grow and Convert's revenue-first stance.

### Lightweight per-client reporting cadence
- **Cadence:** weekly health spot-check, monthly report, quarterly zoom-out. (AgencyAnalytics / DashThis consensus.)
- **Monthly report = 4-6 KPI scorecards up top** with vs-last-period + green/red direction, then supporting charts. First screen answers "up or down vs last period?"
- **Local KPI set (8-12):** organic clicks, keyword/geo-grid rankings, conversions (forms + calls), GBP engagement actions (calls/clicks/directions), review trend, top landing pages, technical health, plus a short notes section explaining major changes and the ONE action for next month.
- **Cut from client reports (noise/harm):** third-party Domain Authority (not a Google signal), raw keyword count, social shares, GA4 bounce rate (redefined, confuses clients).

Read: this maps to a per-client `report.md` generated monthly from the manually-exported CSVs. No API needed - the human drops GSC/GA4/GBP exports into a client folder, a script joins and flags, the agent writes the narrative. That is the whole loop, offline, consistent with our no-API constraint.

---

## Part 6 - Recommendations mapped to categories

Priority order reflects the brief: measurement loop + refresh system first (biggest gap).

### [Python scripts]
1. **`decay_monitor.py`** (PRIORITY, effort M) - ingest manually-exported GSC CSV (current vs prior 28-day) + optional GA4 CSV, join on URL, compute % change per metric, apply the flag rules (Part 3), output a ranked refresh queue with flag counts per URL. Why: turns the Click Laboratory workflow into a deterministic offline tool; this is the core of the missing loop. Source: clicklaboratory.com decay workflow.
2. **`refresh_prioritizer.py`** (effort S) - score flagged URLs by tier x flag-count x conversion-value, cap at 3-5/month/client, emit the month's refresh slate. Why: capacity discipline (Animalz 3-5/mo finding) prevents guilt-backlog. Source: animalz.co/blog/content-refresh.
3. **`link_graph.py`** (effort M) - maintain a per-client site link graph (hub/spoke/silo), validate every new page's `internal-links.md` against equity-routing rules (spoke->hub mandatory, no 30-link walls), flag orphans and over-linked pages. Why: makes internal linking compound as pages are added (Law 10). Source: SEJ hub-spoke, Search Roost (2-4 links, >=1 hub).
4. **`qa_scorecard.py`** (effort S) - compute the 6-category pass/needs-work scorecard, enforce the 3-fail kill gate, emit `scorecard.md`. Why: makes quality numeric and trendable; reusable on live pages for re-scoring. Source: searchroost.com scorecard.
5. **`report_builder.py`** (effort M) - join monthly GSC/GA4/GBP exports per client, emit the 8-12 KPI monthly `report.md` with vs-last-period direction and the one next-action. Why: closes the loop on outcomes without APIs. Source: agencyanalytics KPIs, bippermedia local dashboard.

### [skills]
6. **`/refresh` command** (PRIORITY, effort M) - run decay_monitor -> prioritizer -> for each slated page, execute the refresh scope checklist (intent check, fact/date update with material content change, structure pass, internal-link rewire, snippet test), write the one-sentence lift hypothesis, schedule the 30-60d review. Why: operationalizes the single highest-ROI activity (median +106% traffic). Source: ahrefs.com/blog/content-decay, animalz.
7. **`/report` command** (effort S) - generate the monthly per-client report from exports. Why: reporting cadence the loop needs.
8. **Extend `/qa`** (effort S) - emit the numeric scorecard AND allow running against a LIVE published page (re-score on cadence), not only fresh drafts. Why: "content continues to meet standards as it ages" (Siege). Source: siegemedia, easycontent.

### [agents]
9. **`decay-analyst` agent** (effort M) - reads the refresh queue, diagnoses WHY each page decayed (intent shift via query-mix change, competitor overtook, stale facts, lost snippet), assigns the correct one of the six refresh strategies. Why: the flag tells you a page dropped; the diagnosis tells you what to do. Source: clicklaboratory query-level check, animalz six strategies.
10. **`link-architect` agent** (effort M) - owns the site link graph; on every new page, decides its hub/silo placement and the inbound links existing pages should add. Why: the graph must be actively managed, not per-page guessed.

### [MD knowledge files]
11. **`knowledge/lifecycle/content-decay-refresh-protocol.md`** (PRIORITY, effort S) - the decay thresholds, tiering, refresh-vs-prune-vs-consolidate matrix, six strategies, capacity cap, hypothesis-then-verify. The doctrine for the whole back half. Sources: animalz, clicklaboratory, ahrefs.
12. **`knowledge/lifecycle/measurement-loop.md`** (effort S) - the three local data layers, free geo-grid method, GBP UTM trick, GA4 call/form events, reporting cadence + KPI set + cut-list. Source: semrush, dreamhost, agencyanalytics.
13. **`knowledge/quality-gates/editorial-scorecard.md`** (effort S) - the 6-category rubric + 3-fail kill gate + fact-check anchoring. Source: searchroost.
14. **Extend `foundations/internal-linking.md`** (effort S) - add equity-routing rules, template-zone linking, the no-mass-link rule, growth management. Source: SEJ, searchengineland.
15. **`knowledge/lifecycle/freshness-and-ai-citation.md`** (effort S) - the freshness-signal data, the "date-only bump is discounted" caveat, dateModified schema requirement, 30-90d citation window. Source: ahrefs/blog/fresh-content, conbersa.

### [laws]
16. **New Law: "A page is not shipped, it is enrolled."** (effort S) - every finalized page is registered in the client's decay master sheet with tier + primary conversion event + last-refresh date, or it is not done. Extends the Output contract past FINALIZE. Enforces Law 6 + Law 11.
17. **New Law: "No date without a delta."** (effort S) - never update a last-updated date or `dateModified` without a material content change; a date-only bump is discounted by crawlers and is signal-gaming. Directly extends Law 8 (no signal-gaming) into the refresh phase. Source: conbersa freshness caveat.

### [frameworks]
18. **The PUBLISH -> MEASURE -> DECIDE -> REFRESH loop** (PRIORITY, effort S) - the named lifecycle framework that bolts onto the existing brief->finalize pipeline, with the flag-count decision gate (1 watch / 2 diagnose / 3 refresh) and the 3-5/month capacity cap. This is the organizing spine for everything above.
19. **URL-tiering framework** (effort S) - Tier 1 (money pages, monthly) / Tier 2 (cluster, quarterly) / Tier 3 (backlink pages, annual) drives all cadence decisions. Source: clicklaboratory.
20. **Editorial QA scorecard framework** (effort S) - 6 categories, pass/needs-work, 3-fail kill. Source: searchroost.

### [examples]
21. **A worked decay-to-refresh example** (effort M) - one fictional local client (e.g. an HVAC service-in-city page), showing a GSC export with a decaying page, the flag computation, the diagnosis, the chosen strategy, the refreshed sections, the lift hypothesis, and the 60-day result. Why: examples are how the playbooks teach; the refresh loop needs its own teardown pair like the page playbooks have.
22. **A filled monthly client report** (effort S) - the `report.md` template populated with realistic local numbers, so the reporting cadence has a concrete target artifact. Source: bippermedia local dashboard shape.

---

## Critical caveats (be honest)

- **Refresh lift numbers are self-reported by tool vendors** (Animalz, Ahrefs) with obvious incentive. The direction is robust across independent operators, but treat "+106% median" and "42% better quarterly" as order-of-magnitude, not guarantees. The hypothesis-then-verify step exists precisely because per-page lift is unpredictable.
- **Local sites have low volume, so GSC data is noisy.** Require the 2-consecutive-period confirmation before spending a refresh slot; single-month dips on a 100-impression page are often noise, not decay.
- **GBP metrics are being trimmed by Google** and lack a free API, so capture is manual and monthly or the time series is lost. Build the loop to tolerate a human dropping CSVs, not to expect live data.
- **Geo-grid "free" methods** either use limited free tiers or manual incognito checks; a true 4x4 grid tracked continuously usually needs a paid tool. Start with manual monthly grid snapshots on the top 3-5 money keywords, not continuous tracking.
- **Freshness is not a free lunch:** date-only updates are discounted. The refresh system must force material content change, which is a cost, not a trick.
