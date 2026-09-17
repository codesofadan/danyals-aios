# M02 · Audit

Requirements: `REQ-AUD-001` … `REQ-AUD-010`.

Two products from one engine: a **free** condensed audit that converts strangers into
leads, and **paid** audits in six types that an SEO team actually works from.

---

## 1. Architecture decision

**The audit engine is a package inside the backend, not a subprocess.**

v1 vendored a separate 20k-line engine invoked as a subprocess, which minted its own run
id, never timed itself out, and did not catch its own top-level exceptions — so the caller
owned failure handling for a process it could not see into. That seam produced a
disproportionate share of v1's reliability problems.

In v2, `modules/audit/` is an ordinary module: it runs as jobs, uses the shared job engine,
the shared cost gate and the shared provider seam. The domain knowledge from v1's engine
(the checklists, the scoring, the GEO checks) is **ported**; the process boundary is not.

---

## 2. Audit types

| Type | Sections | Typical page budget | Primary providers |
|---|---|---|---|
| `technical` | Crawl & index · rendering · Core Web Vitals · structured data · security & infra · hreflang · sitemaps/robots | 200 | Browser worker, PageSpeed, crawl |
| `local` | GBP completeness · NAP consistency · citation coverage · reviews · local pack / geo-grid | 30 + grid | Places, serper.dev, citation ledger |
| `geo` | AI Overview readiness · passage citability · semantic HTML for LLMs · AI-crawler access · `llms.txt` · AI-search authority | 50 | Browser worker, SERP |
| `content` | Coverage vs topical map · thin/duplicate detection · intent alignment · internal linking · E-E-A-T signals | 200 | Crawl, keyword bank |
| `offpage` | Referring domains · anchor profile · toxicity · citation gaps · Web 2.0 footprint | — | Backlink provider, citation ledger |
| `full` | All of the above, plus a cross-section narrative | 200 | All |

**Free audit** is a fixed condensed subset of `technical` + `local` signals over at most
10 pages, tuned to produce something specific and true within three minutes.

---

## 3. The findings contract

`findings.json` is the **single source**. The HTML viewer, the PDF and the remediation
sheet are three renderers over it. Nothing is authored twice.

```jsonc
{
  "audit_id": "...", "type": "technical", "target": "https://example.com",
  "engine_version": "2.0.3",
  "started_at": "...", "finished_at": "...",
  "coverage": { "pages_requested": 200, "pages_crawled": 187, "pages_failed": 13 },
  "sections": [
    {
      "key": "core_web_vitals",
      "state": "measured",                 // measured | degraded | skipped
      "degrade_reason": null,              // enum when state != measured
      "score": 62,
      "findings": [
        {
          "code": "CWV_LCP_POOR",
          "severity": "high",              // critical|high|medium|low|info
          "title": "Largest Contentful Paint is 4.8s on the service template",
          "evidence": {
            "url": "https://example.com/services/roof-repair",
            "measured_value": 4.8, "unit": "s", "threshold": 2.5,
            "selector": "img.hero__image",
            "captured_at": "...", "source": "pagespeed:mobile"
          },
          "standard_ref": "web.dev/lcp",
          "affected_urls": 34,
          "effort": "medium",
          "remediation": "Serve the hero image as AVIF at 1600px and preload it.",
          "owner_role": "dev"
        }
      ]
    }
  ]
}
```

**Rules:**
- A finding **must** carry evidence with a measured value and where it was measured. A
  finding with no evidence is not emitted.
- A section that could not run emits `state: "degraded"` with a reason and **renders as an
  explicit "not measured" block**. It is never omitted and never estimated (`REQ-AUD-007`).
- Scores are computed only from measured sections, and the report states which sections
  contributed.

---

## 4. Flow

```
  request (free or paid)
    └── cost gate: estimate from type + page budget
    └── job: audit.run
          ├── resolve target, robots, sitemap
          ├── crawl (browser-worker, budgeted, concurrency-capped)
          ├── per-section analyzers (parallel, each isolated)
          │     └── a section failure degrades that section only
          ├── assemble findings.json
          ├── LangGraph: audit_narrative  (may reference ONLY values in findings.json)
          ├── render HTML + PDF
          └── persist artefacts, emit audit.completed
```

A section analyzer that raises does **not** fail the audit. It degrades its own section,
records the reason, and the audit completes `partial`. This is the difference between "the
audit failed" and "12 of 13 sections measured".

---

## 5. Free audit as a lead magnet

The conversion mechanics matter as much as the analysis.

| Control | Value |
|---|---|
| Rate limit | 3 per IP per day; 1 per domain per 7 days |
| Verification | Email verified before the report is delivered; the link is the delivery |
| Spend ceiling | A global daily cap; when hit, the form says the queue is full and captures the lead anyway |
| Abuse | Disposable-domain blocklist; a honeypot field; no report for a domain the requester cannot be associated with beyond the free tier |
| Output | ~10–15 pages, 3 concrete specific findings surfaced above the fold, one clear next step |
| Lead ownership | The agency. Leads land in `free_audit_leads`, convert to a client record on signup |

The free audit is public and unauthenticated, so it is the most exposed surface in the
system. It goes through the same SSRF guard as everything else, and it runs under a
`scope=public` RLS policy that can touch nothing but its own rows.

---

## 6. Deliverables

- **HTML viewer** — the working surface. Filterable by severity and section, each finding
  expandable to its evidence, each convertible to a task in one action.
- **PDF** — the client artefact, rendered from the same document model by M11.
- **Remediation sheet** — CSV/Sheets export grouped by owner role and effort, which is what
  a dev team or a client's webmaster actually uses.
- **Diff** — against the previous audit of the same site and type: resolved, new, worsened.

---

## 7. Cost control

Every audit type declares a page budget and a cost ceiling, both enforced **before** the
run starts and monitored during. A run that would exceed its ceiling stops, marks itself
`partial`, and reports what it did measure. It never silently truncates and reports a
score as if it had full coverage — `coverage` in the findings makes truncation visible.

---

## 8. Acceptance criteria

| # | Criterion |
|---|---|
| A1 | Each of the six paid types completes on a fully-keyed environment with zero degraded sections |
| A2 | Removing one provider key degrades exactly the sections that depend on it, and the report renders explicit "not measured" blocks for them |
| A3 | A free audit completes end to end in under 3 minutes on a 10-page site |
| A4 | Every finding in a full audit carries evidence with a measured value and a source |
| A5 | The narrative contains no numeric claim absent from `findings.json`, proven by an automated post-check |
| A6 | HTML and PDF render from the same document model — a change to a finding appears in both with no template edit |
| A7 | An audit whose crawl is truncated by budget reports `coverage` honestly and marks itself `partial` |
| A8 | Free-audit abuse controls hold under a scripted attempt: rate limit, domain cooldown, disposable domains and the honeypot all fire |
| A9 | A finding converts to an assigned task carrying its evidence |
| A10 | An audit diff correctly classifies resolved, new and worsened findings against a seeded prior audit |
