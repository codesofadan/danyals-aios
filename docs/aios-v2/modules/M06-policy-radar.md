# M06 · Policy Radar

Requirements: `REQ-POL-001` … `REQ-POL-007`.

Watches the search industry for changes that affect clients, and turns those changes into
per-client recommendations. It is the module that keeps the agency from being the last to
know about a core update.

---

## 1. Why it is in scope

It was sold to the client as Module 04 of four in the platform overview. Shipping without it
means shipping three of four advertised modules. It is also cheap to run and cheap to build
relative to its visibility — a daily brief in front of the owner every morning is the
highest-frequency evidence the platform is alive.

---

## 2. Flow

```
  watched sources (registry, per-source cadence)
    └── fetch + normalise
          └── change detection: content diff against the last snapshot
                └── change_event(date, source, diff, confidence, classification)
                      ├── knowledge base update
                      ├── per-client exposure analysis
                      │     └── recommendation queue (acknowledge / dismiss / → task)
                      └── daily brief → Command Center
```

## 3. Sources

Seeded registry, each with its own cadence and parser:

Google Search Central blog and changelog · Google Search Status dashboard · algorithm-update
trackers · Google Business Profile help changes · the Search Quality Rater Guidelines
revision history · major platform policy pages for every M05 platform (their terms position
is a `platforms` field that this module keeps current) · the spam policies page.

**Each source records `terms_checked_on`** so a stale parser is visible rather than silently
returning "no change" forever. A source that fails to parse for two consecutive runs raises
a task — silence is not evidence of stability.

## 4. Change detection

- Normalise to text, strip volatile chrome, diff against the last snapshot.
- Classify: `announcement` · `policy_change` · `guideline_revision` · `product_change` ·
  `noise`.
- Attach a confidence. A low-confidence change is surfaced but not acted on.
- **Never infer a change that was not observed.** If a source is unreachable, the run is
  degraded for that source, not "no changes found".

## 5. Exposure analysis (`REQ-POL-004`)

For a given change, which clients are affected and why:

- A GBP policy change → clients with GBP connected, ranked by local dependence.
- A change to a platform's terms → clients with live properties on that platform, with the
  affected property count.
- A core update → clients whose tracked rankings moved outside their normal band in the
  window, which is a *correlation*, and is labelled as one.

**Exposure is evidence-linked or it is not shown.** "This client may be affected" with no
evidence is noise, and noise trains the operator to ignore the module.

## 6. Recommendations and the brief

- Recommendations carry: the change, the affected clients, the suggested action, the effort,
  and the evidence. Lead-gated actions: acknowledge, dismiss (with reason), or convert to a
  task in M01's queue.
- The **daily brief** is generated on a schedule and surfaced in the Command Center: what
  changed in 24 hours, who is exposed, what is open.
- **On-demand ask** (`REQ-POL-007`): a question answered from the knowledge base with
  citations, metered under the policy money dial. It answers from the KB — it does not run a
  live web search, so the answer is traceable to a stored source.

## 7. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | A seeded change in a fixture source is detected, classified and dated correctly |
| A2 | An unreachable source produces a degraded run for that source; the brief says so rather than reporting no changes |
| A3 | A parser that stops matching raises a task within two runs |
| A4 | Exposure analysis links every named client to specific evidence |
| A5 | A recommendation converts to a task carrying its evidence |
| A6 | The daily brief generates on schedule and is idempotent — two runs in one day produce one brief |
| A7 | An on-demand ask cites stored KB sources and is metered against the policy dial |
