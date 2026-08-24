# Content Decay + Refresh Protocol - the back half of the lifecycle

v1.0 - 2026-07-20 PKT. The doctrine for everything after FINALIZE. The write pipeline (BRIEF -> ... -> GATE -> FINALIZE) ends when a page is published. This file governs what happens next: the **PUBLISH -> MEASURE -> DECIDE -> REFRESH** loop that keeps a page ranked as it ages. Grounded in `research/expansion-2026-07/06-process-measurement.md`.

This is the enforcement of three doctrine laws past the point where the front pipeline stops caring:
- **Doctrine Law 6** (measure or you are guessing): a page unmeasured after publish is a guess.
- **Local Content Law 18** (a page is not shipped, it is enrolled): no measurement row, not done.
- **Local Content Law 19** (no date without a delta): a date bump with no material change is signal-gaming.
- **Doctrine Law 11** (terminate in a verified action): the refresh loop closes on a verified lift, not on the act of editing.

Authority order: founder > seo-system-doctrine.md > local-content-laws.md > this file.

---

## The loop

```
PUBLISH ---> MEASURE ---> DECIDE ---> REFRESH ---> (re-enroll, back to MEASURE)
   |            |            |            |
 enroll      monthly      flag-count    scope checklist
 the row     GSC/GA4      decision      + lift hypothesis
 (Law 18)    export       gate          + 60-day review
```

Each stage is a hard step, not a suggestion. A page that skips MEASURE is invisible by construction. A page that skips the DECIDE gate gets refreshed on vibes and wastes a capacity slot. A REFRESH with no lift hypothesis and no scheduled review is an edit, not a measured action, and violates Law 11.

---

## Stage 1 - PUBLISH (enroll the page)

A finalized page is not counted as shipped until it has a row in the client's measurement sheet (`clients/<slug>/` measurement log, or the client's own tracking Sheet). This is Law 18, made operational.

**The enrollment row** carries, at minimum:

| Field | Value |
|---|---|
| URL | the live absolute URL |
| tier | 1 / 2 / 3 (see tiering below) |
| target query | the primary "[service] [city]" query the page ranks for |
| publish date | ISO 8601 |
| primary conversion event | the GA4 event this page closes on (form submit, click-to-call) |
| success hypothesis | one sentence: what this page is expected to do, by when |
| last-refresh date | initially blank; the publish date is the baseline |

No row, not shipped. The `schema-linking-finisher` agent hands off the finished package; enrollment is the operator's confirmation that the page entered the measured set.

### URL tiering (so the loop chases signal, not noise)

Tiering sets the review cadence. Source: Click Laboratory workflow (`research/06`, Part 3).

- **Tier 1 - money pages.** 30-50 URLs by revenue/pipeline influence. For a local client: the service-in-city combos, the homepage, the top location pages. **Monthly deep review.**
- **Tier 2 - supporting cluster.** Mid-tail service hubs, secondary location pages. **Quarterly review.**
- **Tier 3 - low-traffic / high-backlink.** Reference pages, old assets holding links. **Annual or trigger-based.**

Local sites are small, so most of a client's page set is Tier 1 or Tier 2. Do not tier every page as Tier 1; the monthly cadence only earns its cost on pages that actually move revenue.

---

## Stage 2 - MEASURE (detect decay, no API)

The engine is `scripts/decay_monitor.py`. It is offline and deterministic: it ingests manually-exported GSC CSVs (no API, per the workspace no-API constraint), joins on URL, computes the percentage change per metric across the comparison windows, applies the flag rules below, and outputs a ranked refresh queue with a flag count per URL.

### The export the human drops in

Monthly, the operator exports from Google Search Console (manual CSV export, no API):
- clicks, impressions, CTR, average position, grouped by page.
- A 28-day window versus the prior 28-day window, **same property and same filters every month** (drift in the filter set poisons the comparison).
- Optionally a GA4 organic landing-page CSV (sessions, engaged sessions, conversions) on matching windows.

Use year-over-year when the data exists; month-over-month alone is noisy on low-volume local sites. `decay_monitor.py` reads whatever windows are present and computes against them.

### The flag rules (per Tier-1 URL)

`decay_monitor.py` applies these thresholds. Source: Click Laboratory, corroborated by SEOJuice / ContentForce (`research/06`, Part 3).

| Signal | Flag threshold |
|---|---|
| Impressions down | 15%+ for two consecutive periods |
| Clicks down | 20%+ with flat or falling impressions |
| CTR down | 1+ point at a similar average position |
| Position down | 2+ positions on the primary query |
| Engaged sessions down | 20%+ on organic (GA4) |

### The 2-consecutive-period confirmation rule (local-specific, non-negotiable)

Local sites have low search volume, so a single 28-day dip on a 100-impression page is usually noise, not decay. **Do not spend a refresh slot on a single-period dip.** Require the stricter confirmation before acting: a flag must persist across **two consecutive comparison periods** (or, on the stricter ContentForce reading, three consecutive 28-day periods with 20%+ click decline AND a 2+ position drop = confirmed structural decay). `decay_monitor.py` tracks period-over-period persistence, not just the latest snapshot. A first-period flag is a `watch`, never an auto-refresh.

Cross-check against a documented external cause before trusting any flag: a known algorithm update or a genuine seasonality trough (a snow-removal page in July) is not decay. If an external cause is documented in the client notes, the flag is annotated and does not consume a slot.

---

## Stage 3 - DECIDE (the flag-count gate, then the three-way call)

### The flag-count decision gate

Read the flag count per URL from `decay_monitor.py`, apply after the 2-period confirmation:

| Confirmed flags | Action |
|---|---|
| **1 flag** | **Watch.** Note it, re-check next period. No slot spent. |
| **2 flags** | **Diagnose this period.** Pull the query-level GSC data, find the cause. |
| **3+ flags** | **Schedule a refresh** (unless an external cause is documented). |

This is the same shape across Animalz (six triggers), Click Laboratory, and ContentForce; the flag count is the trigger, the diagnosis is the "why".

### The refresh-vs-prune-vs-consolidate matrix

Once a page clears the gate, decide what kind of action it earns (Animalz three-way call, `research/06` Part 3):

- **Refresh** - the page has backlink equity and still targets valuable, live-intent keywords; it just needs updated facts, better structure, or restored freshness. **This is the default for a money page.**
- **Prune** - no backlinks, no rankings, no traffic, and the topic is covered better by another page. Remove or `noindex`, redirect if it holds any equity.
- **Consolidate** - multiple thin pages fighting over the same keyword. Merge into one authoritative page. For local, two near-duplicate service-area pages are BOTH a decay problem and a doorway-page risk; consolidation doubles as compliance cleanup (see `foundations/cluster-graph-protocol.md`, anti-doorway rule).

### Diagnosing the "why" (assign one of six refresh strategies)

A flag says the page dropped; the diagnosis says what to do. Match the decayed page to one strategy (Animalz six strategies):

1. **Expand** - competitors went deeper; fill the gap with original examples, real data, SME specifics (never consensus filler; Law 15).
2. **Update** - replace stale stats/prices/screenshots, fix broken links, advance the visible last-updated date and `dateModified` schema **only alongside a real content change** (Law 19).
3. **Refine on-page** - rewrite title/meta/headers, close semantic-term gaps.
4. **Retarget** - the intent behind the query shifted; realign to the higher-value intent.
5. **Merge** - consolidate overlapping pages (the consolidate call above).
6. **Repromote** - redistribute (marginal for local web pages; relevant for GBP posts).

---

## Stage 4 - REFRESH (execute, hypothesize, schedule the review)

### Capacity cap (3-5 refreshes per month, per client)

The finding, honestly stated: "most teams ship 3-5 meaningful updates per month without starving new content" (Animalz, `research/06` Part 3). Keep the refresh watchlist **smaller than the refresh bandwidth** so it does not become a guilt-driven backlog. For a solo/small shop running many local clients, cap at **3-5 refreshes per client per month** and let the flag-priority score (tier x flag-count x conversion-value) choose which pages get the slots. `scripts/decay_monitor.py` outputs the ranked queue; the operator draws the top 3-5 for that client and stops.

### The refresh scope checklist (per page that earns a slot)

Run in order. This is the write pipeline re-pointed at an existing page, not a fresh draft:

1. **Intent check.** Read the current top queries for the URL (GSC query export). Search the target query incognito with location set. Confirm the intent has not shifted; if it has, this is a Retarget, not an Update.
2. **Fact and example update.** Replace outdated prices, stats, screenshots, and broken links with current, real, sourced facts. Every new local specific traces to `brand.yaml`, the SME interview, or a cited source (G1/G10 still apply to a refresh).
3. **Material content delta (Law 19 gate).** The refresh must change content in substance: new facts, new data, a restructured answer, corrected information, added SME specifics. **A date-only change is forbidden.** Crawlers discount date-only diffs and presenting a page as fresh when it is not is a low-value tactic under Law 8. Only after a material delta exists do you advance the visible last-updated date and the `dateModified` schema.
4. **Structure pass.** Re-check the H2s mirror the buyer's questions and each section leads with a direct answer (the passage-block protocol). Decayed pages often lost snippets because a competitor's structure got more extractable.
5. **Internal-link rewire.** Link the refreshed page into any newer hubs or siblings that did not exist when it first shipped. Hand the changed link set to the `link-architect` agent so the site graph stays consistent (spoke -> hub still mandatory).
6. **Snippet test (if CTR-flagged).** Rewrite the title and meta, then hold 4 weeks and re-read CTR before judging.
7. **Write the one-sentence lift hypothesis** (below) and **schedule the review** (below).

### The one-sentence lift hypothesis (Law 11 made concrete)

Before the refreshed page republishes, write one sentence stating what the change is expected to do and by when. Format:

> "Expanding the pricing section with the real 2026 Round Rock permit-fee band and a same-day-callout stat should recover the featured snippet for 'water heater repair round rock cost' and lift clicks 20%+ within 60 days."

This is not optional decoration. It converts an edit into a measured action: at review time you either verified the lift or you did not, and that result feeds the client case log. A refresh with no hypothesis has nothing to verify against and violates Law 11.

### The 60-day review

Every refresh schedules a review at **30-60 days** (30-day early read, 60-day confirmation). At review:
- Pull the same GSC/GA4 windows for the URL.
- Compare against the pre-refresh baseline and the hypothesis.
- **Win** (recovered or improved within 60 days) -> log the win, update `last-refresh date`, return the page to normal cadence.
- **Flat or worse** -> the hypothesis was wrong. Re-diagnose (usually a deeper intent shift, a stronger competitor, or a technical issue the content refresh could not fix). Do NOT reflexively re-refresh; a second failed refresh on the same page is a signal to prune or consolidate.

Append the outcome to the client case log (`clients/<slug>/brand.yaml` `case_log`, entry shape `{date, page, what_worked, client_quirk, outcome}`), so the loop compounds (Law 10).

---

## Portfolio health (quarterly, per client)

The KPIs that prove the loop works, not vanity traffic:
- **Health rate** - share of Tier-1 URLs with zero confirmed flags.
- **Avg Tier-1 clicks** - rolling 90-day.
- **Refresh win rate** - percent of refreshes that improved within 60 days. This is the number that tells you whether the diagnosis step is any good.
- **Decay-backlog age** - average days a confirmed-decay page waits before action. Rising backlog age means the capacity cap is too tight for the client's page count, or the watchlist is bloated with Tier-2 noise.

---

## The evidence, flagged honestly

The refresh-lift figures below are **self-reported by content-tool vendors** (Animalz, Ahrefs) who have an obvious incentive to make refresh look good. The **direction** (refresh a decayed page with real new value and it tends to recover) is robust and corroborated across independent operators. The **magnitudes** are order-of-magnitude, not guarantees. This is exactly why the hypothesis-then-verify step exists: per-page lift is unpredictable, so the system measures each refresh instead of assuming the vendor median.

- Organic content decays ~**-1.21% per week** once it begins to decline (Animalz, citing 2018 analysis). Source: animalz.co/blog/content-refresh (fetched 2026-07-20).
- Updated posts: **median +106%** organic traffic; republished pages jump an **average 4.6 SERP positions** (Ahrefs). Source: ahrefs.com/blog/content-decay (fetched 2026-07-20). Vendor-reported.
- **Quarterly refreshes ~42% better than annual** (Animalz). Vendor-reported; directionally consistent with AI-freshness data.
- Freshness / AI citation: AI-cited content is ~**25.7% fresher** than organic results; ~**76.4% of ChatGPT top-cited pages** were updated within 30 days (Ahrefs, Conbersa, fetched 2026-07-20). Independent of the refresh vendors; corroborates the freshness direction.
- **Critical caveat that overrides the lift numbers:** if only the date changed and the content is identical, the freshness signal is **discounted**. A date bump alone does nothing. This is the empirical basis for Law 19 and the material-delta gate above.

Re-verify these figures before quoting any of them externally to a client. Constants current 2026-07-20 PKT.

---

## Scripts this protocol drives

| Script | Role in the loop |
|---|---|
| `scripts/decay_monitor.py` | MEASURE + DECIDE input: ingest GSC (and optional GA4) CSVs, join on URL, compute per-metric change, apply flag rules with 2-period confirmation, output the ranked refresh queue with flag counts. |
| `scripts/qa_scorecard.py` | Re-score an aging page against the 6-category editorial rubric (`knowledge/lifecycle/editorial-scorecard.md`) to catch quality drift as the page ages. |
| `scripts/link_graph.py` | REFRESH step 5: keep the site link graph consistent when a refreshed page's link set changes (owned by the `link-architect` agent). |
| `scripts/report_builder.py` | The monthly client-facing report that surfaces the decay signals and the one next-action (`/report`). |

The operator-facing entry points are the `/refresh` command (runs this whole protocol on one page) and the `/report` command (the monthly KPI narrative).
