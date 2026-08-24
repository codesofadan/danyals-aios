---
description: Generate the monthly local-SEO KPI report for a client from their manually-exported GSC/GA4/GBP CSVs - runs report_builder.py, produces the 8-12 KPI scorecard with vs-last-period direction, a short narrative on major changes, and the single next-action for the month.
argument-hint: <client-slug> [report-month YYYY-MM]
allowed-tools: Read, Write, Edit, Bash, Glob, Grep
---

Generate the monthly client report. Arguments: `$ARGUMENTS` (client slug, optional report month, e.g. `austin-roofing-co 2026-07`).

Read `CLAUDE.md`, `knowledge/lifecycle/content-decay-refresh-protocol.md`, and `knowledge/lifecycle/measurement-loop.md` (if present) first if not already in context. This command closes the loop on outcomes without any API: the operator drops the month's exports into the client folder, `report_builder.py` joins and flags them, and this command writes the narrative and the one next-action.

**No API, no live data.** All inputs are manual CSV exports (GSC, GA4, GBP dashboard read). If an export is missing, report which one and produce a partial report clearly marked, never fabricate a metric.

**No vanity, no harm.** Cut third-party Domain Authority (not a Google signal), raw keyword count, social shares, and GA4 bounce rate from the client report; they mislead the client. Report only KPIs tied to rankings, traffic, conversions, and local visibility.

## Steps

Work from the client's export folder (`clients/<client-slug>/exports/<report-month>/` or wherever the operator drops the CSVs). Ask for the path if it is not obvious.

1. **Confirm the exports are present.** Expected: GSC page-level CSV (clicks, impressions, CTR, average position) for the report month and the prior month on matching 28-day windows; GA4 organic landing-page CSV (sessions, engaged sessions, key conversion events - form submits, click-to-call); a GBP monthly read (calls, website clicks, direction requests, search vs maps views) captured manually. Note any missing file; produce a partial report if one is absent.

2. **Run the report builder.** Run:
   ```bash
   python scripts/report_builder.py --client <client-slug> --gsc <current-gsc.csv> --gsc-prior <prior-gsc.csv> --ga4 <current-ga4.csv> --ga4-prior <prior-ga4.csv> --gbp <current-gbp.csv> --gbp-prior <prior-gbp.csv>
   ```
   It aggregates each source into the site-level KPI totals for the month and computes each KPI vs the prior period with a green/red direction. (Per-URL decay flagging is NOT this script's job; that is `decay_monitor.py` via `/refresh`. Surface the top decayed page from the latest `/refresh` run in the narrative; do not expect a flagged-page list from `report_builder`.)

3. **Assemble the KPI scorecard (8-12 KPIs, top of the report).** The first screen answers "up or down vs last period?": 4-6 headline scorecards with the vs-last-period delta and direction, then supporting detail. The local KPI set: organic clicks, primary keyword / geo-grid rankings, conversions (forms + calls), GBP engagement actions (calls / website clicks / direction requests), review trend, top landing pages, technical health. Tie conversions to each money page's primary conversion event.

   Add the AI-answer citation share (Law 13) when the operator has logged the month's AI-citation results CSV against the frozen prompt set: run `python scripts/share_of_answer_tracker.py --prompt-set clients/<client-slug>/share-of-answer/prompt-set.md <results.csv>` (the client's FILLED frozen prompt set, copied once from `templates/share-of-answer-prompt-set.md`; pointing this at the blank template makes every real logged query read as unlogged) and include the per-engine citation share (never blended - the engines disagree). If no results CSV was logged this cycle, mark share-of-answer unmeasured this month rather than omitting it silently.

4. **Write the narrative.** A short notes section: what changed and why (a decayed page recovering after a refresh, a seasonal swing, a new page ranking, a GBP action spike). Reference the refresh loop where relevant (a page flagged by `decay_monitor.py`, a refresh whose 60-day review lands this month). Keep it plain and client-readable; no jargon, no third-party DA, no bounce rate.

5. **Name the single next-action.** Exactly one action for next month, chosen for leverage: usually the top decayed money page to refresh (hand off to `/refresh`), or the highest-intent page not yet built, or the GBP gap to close. One action the client can say yes to, not a menu.

## Output

`clients/<client-slug>/reports/<report-month>-report.md` (or the client's designated report location): the 8-12 KPI scorecard with vs-last-period direction at the top, the supporting detail, the short narrative, and the single next-action. Report to the operator the headline direction (traffic and conversions up or down vs last period), the flagged decay pages feeding into `/refresh`, and the one next-action. If an export was missing, state which KPI is unavailable rather than filling it in.
