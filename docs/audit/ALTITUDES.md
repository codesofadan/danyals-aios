# The audit altitudes — what was built, and why

**Status:** built and verified on real data, 2026-08-25.
**Anchor run:** `smileon.pk` — 197 pages, 15,617 findings (`docs/audit/fixtures/README.md`).

## The problem, in one measurement

A real 197-page audit produced **15,617 findings**, of which **8,077** were `fail`/`warn`.
Those 8,077 rows contain **461 distinct causes**. The client was being handed 8,077 things to
read when there were 461 things to fix — rendered as an **833-page, 15.4 MB PDF**.

Two further defects were measured on the same run:

- **`subcategory` was 38% populated** and sometimes carried values absent from the checklist
  vocabulary, so the pillar × subpoint spine could not be trusted.
- **Technical scored 97.2 having run 25 of 100 technical checks**, and `strategy` scored nothing
  at all while being silently dropped from the denominator.

## The three altitudes

```
MACRO   audit_rollups              pillar / subpoint verdict + COVERAGE
                                   "Technical 88.7 — ran 25 of 100"
                                   "Strategy  not measured — ran 0 of 21"
MICRO   audit_findings             one CAUSE, N instances
                                   "Image alt text optimization — 121 pages"
NANO    audit_finding_instances    one occurrence, one locus
                                   "/about-us/  images=23, missing_alt=6"
        audit_pages                the page-side pivot
```

Measured collapse: **8,077 rows → 461 findings + 8,077 instances**, a **94.3% reduction** in what
a human reads, with **zero instances lost** (asserted in tests).

## The rules that make it honest

**A cause is `(check_id, locus, discriminator)`, and the locus is where the fix goes.** A missing
H1 across 42 pages of one template is one edit, not 42 problems. Two *different* broken templates
stay two causes — merging them means one gets fixed, the finding stays open, and the client is
told nothing changed.

**Nothing that moves with the site enters the fingerprint** — no URL, no evidence value, no page
id, no run id, no count. Otherwise "is this the same problem as last month" is unanswerable.

**One flat score formula at every level**, over the checks that actually ran there:
`score = 100 × (1 − severity_mass(failed) / severity_mass(ran))`. A pillar score is *not* an
average of its subpoints. There is no per-category weight table, so the renormalisation defect
that produced the 58.0 composite is **not representable**.

**`checks_ran == 0` ⇒ `score = null`**, rendered "not measured". Never 0 — a zero score and an
unmeasured dimension are opposite claims.

**`url_health_pct`** ships alongside as a basis-free number: denominator is *pages*, so it stays
comparable across tiers and months. Critical-only, because including `major` returned 0.0% on the
real run and could not discriminate.

**`basis_hash`** on every row. Two scores compare only when it matches.

## The roadmap

Findings → a sequenced plan, with **every number measured or operator-supplied**:

```
impact   = severity weight × reach × confidence     (all measured)
effort   = fix locus + fix surface (+ volume, url-locus only)
priority = impact / effort
phase    = greedy bin-pack into windows sized by ONE operator input
```

`capacity_points_per_month` (default 40) is the **only** origin of any timeline number. Phases are
**relative windows** (`p0_30d`, `p1_90d`, `p2_180d`, `p3_365d`) — never dates. Overflow goes to
`backlog` explicitly. Verified: at 40 pts/month 162 of 461 items plan; at 80, 322 plan.

A template fix costs the same whether it covers 4 pages or 400 — that is the entire reason causes
and instances are separate.

## The deliverable

`audit-workbook.xlsx` + uncapped CSVs + `audit-pack.zip`. Built in **1.2s** for the 197-page audit:
**690 KB**, against the engine's 15.4 MB / 833-page PDF.

| Sheet | Altitude | Rows on the anchor run |
|---|---|---|
| `00_Read_Me` · `01_Executive_Summary` | macro | 22 · 7 |
| `02_Pillar_Scorecard` · `03_Subpoint_Scorecard` | macro | 7 · 95 |
| `05_Roadmap` | macro | the plan, in relative windows |
| `10_Findings` | **micro** | 462 |
| `20_Instances` | **nano** | 8,078 |
| `21_Pages` · `22_Coverage` | pivot / macro | 198 · 364 |

The XLSX caps instances at 100,000 to stay openable; **the CSV never caps**, and `00_Read_Me` says
so when the cap bites.

## Files

**Engine** — `audit_engine/checklist.py` (the 363-check registry, previously never read at
runtime), `audit_engine/emit.py` (pages.json, coverage.json, taxonomy enrichment),
`db/repository.py` (`PageRepository.by_run`), `cli/main.py` (emission hooks + the google_nl
zero-spend fix).

**Migrations** — `0094_audit_altitudes.sql`, `0095_audit_roadmap.sql`.

**Backend** — `app/services/{audit_altitude,audit_rollups,audit_ingest,audit_workbook,audit_roadmap}.py`,
`app/db/audit_findings_repo.py`, `app/routers/audit_findings.py`, `workers/tasks/audit.py` (wiring).

**API** — `GET /audits/{id}/rollups` · `/findings` · `/findings/{fid}/instances` · `/pages` ·
`/roadmap` · `/download/{name}`.

## Verification

- **130 new tests**, all green: checklist 13, emit 18, altitude 24, rollups 16, workbook 15,
  roadmap 21, endpoints 16, integration-against-real-Postgres 7.
- Backend suite **5,793 passed** (9 pre-existing `beat_schedule` failures, unrelated — verified by
  re-running with this work stashed). Engine suite **68 passed**.
- All **96 migrations** fresh-apply in order; RLS gate passes, 99 tables all FORCE RLS.
- Ingest of the 197-page audit: **1.3s**, idempotent — a second ingest produces identical counts
  and advances `last_seen_at` rather than duplicating.
- The registry independently reproduces **every** containment count in `R4-audit-tiering.md`
  (197/219/228 and 171/193/197), which is a mutual check on both documents.

---

## A finding that changes what "363 checks" means

While building the coverage record, the reason strings were too coarse: a check that ran and found
nothing and a check that never executed both read `no_finding_emitted`, which tells a client their
site was checked when it may not have been.

Splitting them surfaced this, measured on run `837b75d6`:

> Of the **90 free, deterministic checks that produced nothing**, **82 have no analyzer module at
> all** and 8 have a module but no function. **None** were implemented-but-silent.

So the checklist is partly a **catalogue of intent**, not a statement of capability. On a paid,
all-providers run the engine emitted findings for **160 of 363** checks.

**An over-claim was caught and corrected during this work, and the correction matters.** The first
version of this diagnostic labelled those checks `analyzer_not_implemented`. That label is wrong:
**160 checks ran while only 31 declared `analyzer:` paths resolve by import**, so roughly 129
*working* checks are dispatched by some route other than their declaration. A path that fails to
import proves the **declaration** is unusable — not that the check is unimplemented. The reason
string is therefore `analyzer_path_unresolved`, and a test pins the wording so the stronger claim
cannot creep back:

```python
def test_the_path_check_is_not_treated_as_proof_of_implementation():
    assert emit.SKIP_UNRESOLVED_ANALYZER == "analyzer_path_unresolved"
    assert "not_implemented" not in emit.SKIP_UNRESOLVED_ANALYZER
```

On a free-tier run the coverage now reads:

```
planned 171 · ran 76
  source_not_permitted      192   the tier forbids the provider   (correct, expected)
  analyzer_path_unresolved   94   catalogued, declaration broken  (a real backlog)
  no_finding_emitted          1   ran, site was clean             (a real pass)
```

Previously all 287 of those were one undifferentiated bucket.

**What this is worth to the owner:** it converts a vague "the engine runs 363 checks" into a costed,
prioritised backlog — 90 checks that are free, deterministic, and unbuilt. That is the highest-value
engine work available, and it is now visible in `22_Coverage` of every workbook rather than needing
an investigation to find.

---

## The operator surface

Route `/admin/audit/[auditId]`, linked from the audit list. Plain CSS on the app's
own tokens (this codebase uses no Tailwind and no component library), `.card`/`.seg`
primitives, Material Symbols, TanStack Query.

| Tab | Altitude | What it answers |
|---|---|---|
| Overview | macro | Where is this site weak — and did we actually look? |
| Plan | macro | What do we do first? |
| Findings | micro → nano | One card per problem; expand for every affected URL |
| Pages | pivot | Which pages are worst |
| Downloads | — | The workbook and the uncapped CSVs |

**The rule the UI enforces.** `scoreDisplay` is the only sanctioned way to render a
score; `score ?? 0` in a component is a bug, and a test pins it. An unmeasured
dimension renders "Not measured", states *why* (a tier restriction is an operator
action; a missing analyzer is engineering work), and is styled **absent** — muted and
dashed — rather than **bad** — red. Verified live: Strategy renders
`Not measured — ran 0 of 21 checks`.

**Three walls of data were found by looking at the rendered page**, not by reasoning
about it, and all three are fixed:

| View | Before | After |
|---|---|---|
| Subpoint table | 95 rows, half "100 / 0 issues" | defaults to subpoints *with findings* |
| Plan | **17,025 px** tall | **1,539 px**, 8 per column + expander |
| Findings | **13,016 px** tall | **1,973 px**, paged at 25 |

Every collapse states the count it is holding back. A filtered view that does not
say what it filtered is how a dashboard starts lying by omission.

Also caught on inspection: a finding displayed `Owner A3` — an internal engine agent
code where a job title belongs. It now resolves the dimension through the same role
vocabulary the workbook and roadmap use, so all three name the same person.

**Verified end to end in a real browser** against the live API and the real 197-page
audit: logged in, all five tabs rendered, a finding expanded to its three exact URLs
with observed evidence, all six downloads served `200`, the allow-list refused
traversal `404`, an unauthenticated read was refused `401`, and there were zero
console errors.

## Final state

| Suite | Result |
|---|---|
| Backend | **5,809 passed** (9 pre-existing `beat_schedule` failures, unrelated) |
| Backend integration (real Postgres) | **7 passed** |
| Engine | **71 passed** |
| Frontend | **71 passed**, new files lint-clean, `next build` green |
| Migrations | all 97 fresh-apply in order; RLS gate passes |

---

## The deliverables

### The client report — `app/services/audit_report.py`

A **Python template filled from measured rows**. Everything on it is arithmetic over
data the audit already produced, so a model has nothing to add and two things to cost:
money per report, and the standing risk of a fabricated number in a document a client
acts on. The layout is code, the content is a query, and the same input renders the same
bytes — regenerating a report next year produces the report that was sent.

Charts are **inline SVG generated in-process**: no chart library, no JavaScript, no font
host, no remote asset. It renders identically in a browser, in an email client and
through a print pass, with no network at all.

| | engine's report | this |
|---|---:|---:|
| pages | 833 | **11** |
| size | 15.4 MB | **530 KB** |
| render | ~3 min | **0.01 s** |
| marginal cost | model calls | **$0** |

Sections: cover · executive summary · where the site stands · weakest areas · the plan ·
the issues · what we checked · how to read this.

It enforces the **same three rules a third time** — no score without its coverage, no
unmeasured dimension as zero, no calendar date on a phase — because this is the artefact
that leaves the building.

### The workbook

Every data sheet is now a real **Excel table**: filter dropdowns, sort, banding,
structured references — not a bare grid whose first use is Ctrl+T. Plus a
score-and-coverage bar chart and a severity breakdown.

The trade: tables and charts need a normal worksheet, and `openpyxl`'s write-only mode
supports neither. At 8,077 rows normal mode builds in ~1.4 s, so streaming bought
nothing at this scale and cost both features.

**Per-pillar issue exports** ship alongside — `issues-onpage.csv` (370),
`issues-geo.csv` (80), `issues-local.csv` (5), `issues-technical.csv` (4),
`issues-offpage.csv` (2). A dimension with no issues gets **no file**: an empty CSV reads
as "nothing wrong here" when the truth is often "we never looked".

### Subpoint names

94 subpoints had been printing their internal keys onto a client-facing scorecard.
`semantic-3.8-koray` is a researcher's surname; `semantic-3.9-info-quality` is a section
number. They now read **"Contextual hierarchy"** and **"Information density"**.

Keyed by pillar *then* subcategory, because the same key means different things in
different files: on-page `crawlability` is one page's own directives, technical `crawl`
is site-wide access. The keys are never renamed — they are the join between YAML, finding
and rollup. The engine publishes the names in `coverage.json`, so the platform carries no
second copy of a vocabulary it does not own.

## A bug the report found, and it was destroying history

Building the report against a second audit of the same site cut the **first** audit from
8,077 occurrences to 3,225. Two causes:

- instances were deleted by `finding_id` alone, so a later run erased an earlier run's
  evidence for every cause they shared;
- instance identity was `(finding_id, instance_key)` with no audit in it, so the second
  audit to observe the same page failing the same check was silently dropped by
  `on conflict do nothing`.

A finding is a persistent **cause** many audits observe; an instance is what **one** audit
saw. Migration `0097` puts the audit into the identity and makes the FK cascade —
`on delete set null` was wrong twice over: it orphans evidence from the observation that
produced it, and nulling the column collapsed instances from different audits onto one
identity, so **deleting an audit failed outright**.

Reports now read findings through their own audit's instances, never
`audit_findings.audit_id`, which is last-writer-wins. Two regression tests pin both halves.

## Client visibility

`portal_audits` filtered on `client_id` **alone** — so every client-linked audit was
visible in that client's portal the moment it was created: queued runs, failed runs,
exploratory runs on a prospect's site. Nobody ever chose to show it; a foreign key did.

Migration `0096` adds `visible_to_client`, default **false**, with an explicit checkbox at
creation. Existing rows are backfilled **true** in the opposite direction — they are
visible now, and defaulting them off would silently remove reports clients can currently
open.

## Scores of zero — which are real, and which were not

Most are real: `meta-description` ran 3 of 3 and failed all three across 151 pages.

Two were misleading: `technical/performance` ran **1 of 7** and `off-page/authority`
**1 of 5**, and one failing check rendered as a catastrophic 0. Those now carry an
**indicative** marker. The score still shows — it is real signal — it just no longer
wears the authority of a full verdict.
