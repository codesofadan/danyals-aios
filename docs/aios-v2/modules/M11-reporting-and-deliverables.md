# M11 · Reporting & Deliverables

Requirements: `REQ-REP-001` … `REQ-REP-006`.

Everything the client actually sees. It is also the module where every integrity rule in the
platform either pays off or fails publicly.

---

## 1. One document model, two renderers

`REQ-REP-001`. A report is assembled once into a **document model** — an ordered tree of
typed blocks (heading, paragraph, stat, table, chart, evidence card, gallery, callout). HTML
and PDF are two renderers over that tree.

There is **no second template.** v1's audit and report surfaces drifted because the HTML and
the PDF were authored separately; a change to one silently failed to reach the other.

```
  facts (measured, from every module)
    └── assembler (per report type)
          └── DocumentModel
                ├── HTMLRenderer  → the portal viewer
                └── PDFRenderer   → the client artefact
```

Charts are rendered server-side into the document model as data plus a specification, so
both renderers draw the same chart from the same numbers.

## 2. Honesty rules

These are the point of the module.

- **Measured facts only** (`REQ-REP-002`). Every figure traces to a stored record with
  provenance.
- **Unmeasured sections are stated, never omitted.** "Geo-grid: not measured this period —
  provider quota exhausted on 14 Sep" is a better report than a missing section, and an
  infinitely better one than an interpolated heat map.
- **Every figure carries its measured-at date.** A volume, a rank, a citation count and a
  link count all age differently.
- **Source labelling.** A rank from DataForSEO and an average position from GSC appear as
  different things, never in one series.
- `REQ-REP-005` (P1): every figure is click-traceable from the HTML viewer to the record
  that produced it.

## 3. Report types

| Report | Audience | Cadence |
|---|---|---|
| **Monthly client report** | The end client | Monthly, scheduled, emailed, filed in the portal |
| **Audit report** | Client or their developer | On demand (rendered by M02's assembler) |
| **Citation report** | Client | On demand, and included monthly |
| **Campaign report** | Client on a Web 2.0 campaign | At campaign close |
| **Internal delivery report** | The agency | Weekly — what shipped, what is blocked, what it cost |

### Monthly report contents
Work delivered this period (pages published with links, citations built with proof, posts
placed) · rankings movement with sources labelled · local visibility and NAP consistency ·
indexation of what we published · what is planned next · anything not measured this period
and why.

## 4. Branding and delivery

- `REQ-REP-004`: agency branding — logo, colours, name — applied from settings. The
  architecture supports white-label later (`00` §4 defers the tenancy, not the theming).
- `REQ-REP-003`: scheduled generation, email delivery, and the artefact filed in the client
  portal. Generation is idempotent — two runs in a month produce one report.
- `REQ-REP-006`: Sheets/CSV export is a **format**, never a store. Nothing in the platform
  reads its own data back out of a spreadsheet.

## 5. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | HTML and PDF render from one document model; a change to a fact appears in both with no template edit |
| A2 | Every figure carries provenance and a measured-at date |
| A3 | A period with an unmeasured section renders an explicit "not measured" block with a reason |
| A4 | No report contains a number that cannot be traced to a stored record |
| A5 | DataForSEO rank and GSC average position never appear in the same chart or series |
| A6 | Monthly generation is idempotent and delivers by email with the artefact filed in the portal |
| A7 | Agency branding applies to every client-facing artefact from one settings change |
| A8 | A generated PDF is A4, paginated correctly, and contains no blank pages |
