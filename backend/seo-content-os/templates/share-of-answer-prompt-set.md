# Share-of-Answer Prompt Set + Results Spec

The measurement contract for doctrine Law 13 and Truth 10. Copy this per client to
`clients/<client>/share-of-answer/prompt-set.md`, fill the frozen money queries,
then log results into the CSV described below and feed both to
`scripts/share_of_answer_tracker.py`.

The one discipline that makes this real: **freeze the prompt set.** Citation share
is only comparable across cycles if the denominator does not move. Change the
prompts and the trend line is fiction. Add queries only in a deliberate, dated
version bump, never mid-cycle.

Grounding: `knowledge/foundations/geo-ai-citation.md` and
`research/expansion-2026-07/04-geo-ai-search.md` Section 5.

---

## Part A - the frozen prompt set

Rules:
- **30 to 100 money queries** for a single-location SMB; 250 to 500 only for
  enterprise / multi-location. More is not better: repeated runs of a tight set
  beat a huge set run once.
- Three buckets: **discovery**, **comparison**, **problem/use-case**. Keep them
  labelled so the report can slice by intent later.
- Use the exact words a local buyer types, with the real city and real services
  from `brand.yaml`. Include the queries the GBP card cannot fully answer
  (pricing logic, process, timelines, "what's included"): those are the page's
  citation opening.
- The tracker reads one query per line and ignores `#` headings and list bullets,
  so the format below is parsed as-is.

Prompt-set version: v1 (freeze date: YYYY-MM-DD PKT)
Client: <brand name>   Primary city: <city>

### discovery
- best <service> in <city>
- <service> near me <city>
- emergency <service> <city> open now
- <service> <city> cost

### comparison
- top 3 <service> companies in <city>
- <competitor> vs <brand>
- most reviewed <service> in <city>

### problem / use-case
- <symptom> who to call in <city>
- how much does <service> cost in <city>
- do I need a permit for <service> in <city>

<!-- Expand to 30-100 lines total. Every line must name the real city and a real
service. Delete these HTML comments when filling. -->

---

## Part B - the results CSV header spec

Log every run by hand: query each engine's consumer UI (ChatGPT, Perplexity,
Gemini, Google AI Overview / AI Mode, Copilot), then record the outcome. No API,
no scraping. Save to `clients/<client>/share-of-answer/results.csv`.

**Run each prompt 3 to 5 times per engine per cycle** (10x if feasible). AI answers
are non-deterministic, so citation FREQUENCY across runs is the signal, not a single
yes/no. Log every run as its own row.

Header (exact column names the tracker matches; order is flexible):

```
query,engine,cycle,run,cited,mentioned,competitors,position
```

| Column | Required | Values | Meaning |
|---|---|---|---|
| `query` | yes | text | The exact frozen money query, copied verbatim from Part A. |
| `engine` | yes | ChatGPT / Perplexity / Gemini / Google-AIO / Copilot | One engine per row. Keep spelling consistent across cycles. |
| `cited` | yes | yes / no | Was the client domain cited as a linked source in the answer? |
| `cycle` | recommended | YYYY-MM | The measurement cycle. Omit only if using `date` instead. |
| `run` | recommended | 1, 2, 3... | Which repeated run this row is. |
| `mentioned` | optional | yes / no | Was the brand named without a link? (A citation counts as a mention automatically.) |
| `competitors` | optional | name; name | Competitor domains/brands cited in the same answer (co-citation). |
| `position` | optional | text | Rank in the citation list, or any free-text note. |
| `date` | optional | YYYY-MM-DD | Used to derive `cycle` when `cycle` is blank. |

### Example rows

```
query,engine,cycle,run,cited,mentioned,competitors,position
best emergency plumber in Tempe,ChatGPT,2026-07,1,no,yes,BigCo Plumbing,mentioned not linked
best emergency plumber in Tempe,ChatGPT,2026-07,2,yes,yes,BigCo Plumbing,pos3
best emergency plumber in Tempe,Perplexity,2026-07,1,yes,yes,BigCo Plumbing,pos1
how much does water heater replacement cost in Tempe,ChatGPT,2026-07,1,no,no,,absent
```

---

## Part C - the cycle

1. Freeze the prompt set (Part A). Version and date it.
2. Each cycle (monthly), run every prompt N times per engine, log each run as a row.
3. Run the tracker:
   `python scripts/share_of_answer_tracker.py --prompt-set clients/<client>/share-of-answer/prompt-set.md clients/<client>/share-of-answer/results.csv`
4. Read the one-page report: per-engine citation share, the cycle-over-cycle diff,
   and the single biggest gap. Map that gap back into the next page brief
   (the `geo-optimize` skill turns a missing query into a passage block).
5. Never change the frozen set mid-programme. When a version bump is genuinely
   needed, date it and note that pre-bump and post-bump cycles are not directly
   comparable.
