---
description: Run the content decay + refresh loop for a client - detect decayed pages via decay_monitor.py, pick a page, execute the refresh scope checklist, enforce Law 19 (no date without a delta), write the lift hypothesis, schedule the 60-day review, and append the outcome to the client case log.
argument-hint: <client-slug> [page-slug]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Run the refresh loop. Arguments: `$ARGUMENTS` (client slug, and optionally a specific page slug to refresh, e.g. `austin-roofing-co` or `austin-roofing-co water-heater-repair-round-rock-tx`).

Read `CLAUDE.md`, `knowledge/lifecycle/content-decay-refresh-protocol.md`, and `knowledge/doctrine/local-content-laws.md` (Laws 18 and 19) first if not already in context. This command operationalizes the highest-ROI activity in the lifecycle: recovering decayed pages. It is the MEASURE -> DECIDE -> REFRESH stages of the loop, run on one page.

**Hard line (Law 19):** a date change is earned by a material content delta, never applied to fake freshness. If the only change would be the last-updated date, do not advance the date and do not ship a "refresh"; report that the page needs real new value or does not qualify. A date-only bump is discounted by crawlers and is signal-gaming under Law 8.

**Hard line (Law 8):** no detector-evasion, no "make it pass AI detection" step, ever. The refresh adds real value; it does not launder text.

## Steps

Work in `output/<client-slug>/<page-slug>/`. The client's GSC/GA4 CSV exports live in the client's export folder (`clients/<client-slug>/exports/` or wherever the operator drops them); ask the operator for the path if it is not obvious.

1. **MEASURE - run the decay monitor.** Run:
   ```bash
   python scripts/decay_monitor.py --current <this-28d-gsc.csv> --prior <prior-28d-gsc.csv> [--clicks-drop 20 --impr-drop 15 --pos-drop 2.0]
   ```
   It joins the two GSC windows on URL, computes per-metric change, applies the flag rules, and outputs the ranked refresh queue with a flag count per URL. The script flags a SINGLE period; YOU enforce the **2-consecutive-period confirmation** as the operator (a single-period dip on a low-volume local page is noise, not decay) by checking the prior run or re-running next period. The script takes GSC only (no GA4 input). If the operator named a specific page slug, still run the monitor so the decision is data-backed.

2. **DECIDE - apply the flag-count gate.** Per the protocol: **1 confirmed flag = watch** (report and stop), **2 flags = diagnose** (pull query-level GSC data, find the cause), **3+ flags = schedule a refresh**. Before acting, check for a documented external cause (algo update, seasonality); if one exists, annotate and do not spend a slot. Enforce the capacity cap: **3-5 refreshes per client per month**. If the client is already at cap this month, report the queue and stop; do not start a sixth.

3. **Pick the page.** If the operator named a slug, confirm it actually cleared the gate; if it did not, say so and offer the top queued page instead. Otherwise take the highest-priority page from the ranked queue (tier x flag-count x conversion-value).

4. **Diagnose the "why" and choose one of the six strategies.** From the query-mix change and a live incognito SERP check for the target query, assign exactly one: Expand, Update, Refine on-page, Retarget, Merge, or Repromote. The flag says the page dropped; the diagnosis says what to do. If the correct call is Prune or Consolidate (no equity, or a near-duplicate sibling), report that instead of refreshing - a doorway-risk consolidation is compliance cleanup, not a refresh.

5. **REFRESH - run the scope checklist** (from the protocol, in order):
   - **Intent check** - read current top queries; search incognito with location set; confirm intent has not shifted (if it has, this is a Retarget).
   - **Fact/example update** - replace stale prices/stats/screenshots/broken links with current, real, sourced facts. Every new local specific traces to `brand.yaml`, a tagged SME answer, or a cited source (G1/G10 still apply). Never invent a local specific to freshen a page.
   - **Material delta (Law 19 gate)** - confirm the change is substantive (new facts, new data, restructured answer, corrected info). Only then advance the visible last-updated date and the `dateModified` schema. If no material delta is achievable, halt and report.
   - **Structure pass** - re-check H2s mirror buyer questions and each section leads with a direct answer (passage-block protocol).
   - **Internal-link rewire** - link into any newer hubs/siblings; hand the changed link set to the **link-architect** agent so the site graph stays consistent (spoke -> hub still mandatory).
   - **Snippet test (if CTR-flagged)** - rewrite title/meta; note the 4-week hold before judging CTR.

6. **Re-gate the refreshed page.** Run the affected gates and `python scripts/qa_scorecard.py` to confirm the refresh did not regress another category. A refresh that fixes decay but breaks Sourcing or Structure is not shipped.

7. **Write the one-sentence lift hypothesis (Law 11).** One sentence: what the change is expected to do, on which query, by when. Example: "Adding the real 2026 Round Rock permit-fee band should recover the cost snippet and lift clicks 20%+ within 60 days." No hypothesis, no verifiable outcome, not a valid refresh.

8. **Schedule the 60-day review.** Record a review date (30-day early read, 60-day confirmation) in the client's measurement log, tied to the URL and the hypothesis.

9. **Append to the client case log.** Add an entry to `clients/<client-slug>/brand.yaml` `case_log` in the shape `{date, page, what_worked, client_quirk, outcome}` (outcome initially "pending 60d review"), and update the page's `last-refresh date` in the measurement log. This is what makes the loop compound (Law 10).

## Output

The refreshed page package in `output/<client-slug>/<page-slug>/` (updated `page.md`, `schema.json` with an advanced `dateModified` only if a material delta was made, re-run `qa_scorecard.py` which writes `scorecard.md`, and re-run the gates for `compliance-report.md`), a one-line lift hypothesis, a scheduled 60-day review row, and a new `case_log` entry. Report to the operator: the decay diagnosis, the strategy chosen, the material delta made, the hypothesis, and the review date. If the page did not qualify (single-period dip, at capacity cap, no material delta possible, or a Prune/Consolidate call), report that plainly instead of forcing a refresh.
