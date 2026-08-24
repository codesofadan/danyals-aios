# The Measurement Loop - closing Laws 6, 13, and 18

The system does not go dark after a page ships. Doctrine Law 6 (measure or you are guessing), Law 13 (optimize for the answer, not only the link), and Law 18 (a page is not shipped, it is enrolled) require a post-publish loop. This file is the map of that loop. All inputs are human-exported CSVs; nothing here calls an API or the network.

## The loop

```
PUBLISH  ->  ENROLL  ->  MEASURE  ->  DECIDE  ->  ACT  ->  (back to MEASURE)
```

1. **ENROLL (Law 18).** Every finalized page gets a row in the client's measurement sheet: URL, target query, publish date, the one-sentence success hypothesis, and its money-query set. A page with no row is not shipped (enrolled = shipped). The sheet is the enrollment record and the operator's measurement worksheet; `/refresh` and `/report` run against the raw GSC/GA4/GBP CSV exports (a `--log` join of the enrolled URL set is a documented enhancement, not yet wired).

2. **MEASURE.** On a monthly cadence, the operator exports the free data and the tools read it:
   - **Rankings + traffic:** Google Search Console performance export (28-day, current vs prior) -> `scripts/decay_monitor.py`.
   - **Local KPIs:** GSC + GA4 + Google Business Profile exports -> `scripts/report_builder.py`.
   - **Share of answer (Law 13):** the frozen money-query prompt-set (`templates/share-of-answer-prompt-set.md`) run manually across Google AI Overviews, ChatGPT, and Perplexity, logged to a results CSV -> `scripts/share_of_answer_tracker.py`. Per-engine, because the engines disagree by an order of magnitude.

3. **DECIDE.** `decay_monitor.py` applies the flag rules and the decision gate (1 flag = watch, 2 = diagnose, 3 = refresh). `share_of_answer_tracker.py` names the biggest citation gap. `report_builder.py` surfaces the single worst-moving KPI and one next-action.

4. **ACT.** A refresh runs through `/refresh` and the `content-decay-refresh-protocol.md` (Law 19: no date without a delta; 2-consecutive-period confirmation; 3-5 refreshes/month/client cap). A citation gap routes to the page-controllable GEO levers (`geo-ai-citation.md`) or is flagged as an off-page ops task the copy cannot fix. Every action appends its outcome to `brand.yaml` `case_log` (Law 10 compounding).

## What this is not

It is not a rank-tracker product and it is not real-time. It is a disciplined monthly loop on free, first-party data. It exists so the system optimizes real outcomes (rankings, citations, calls) instead of shipping and forgetting. A generation system that never measures is optimizing yesterday's guess.

## Related files

`content-decay-refresh-protocol.md` (the refresh mechanics), `editorial-scorecard.md` (the pre-publish QA rubric, re-runnable on aging pages), `../doctrine/local-content-laws.md` (Laws 18-19), `../foundations/geo-ai-citation.md` (the share-of-answer levers).
