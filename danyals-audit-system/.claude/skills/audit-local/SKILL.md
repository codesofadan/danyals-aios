---
name: audit-local
description: Run the local SEO audit pipeline against a business domain. Crawls the site, identifies the business via Google Places, pulls GBP + citations + reviews, runs deterministic local checks, dispatches Team D (GBP, Citations/NAP, Reviews, Local Pack/Geo) plus critical Team A/B checks, and produces a local-SEO-focused Markdown report. 5-8 minutes. Use when the user types /audit-local <domain> or asks for a GBP/local-pack focused audit.
---

# /audit-local - local SEO deep dive

You orchestrate the local SEO audit. Use it when the audited business lives on local visibility: GBP, citations, reviews, and local-pack rankings are the priorities. On-page and technical findings appear only when they materially affect local SEO.

## Steps

### 1. Validate input

Same as `/audit`. Accept a domain or URL.

### 2. Run the Python pipeline

```
# From the repo root (the directory containing audit_engine/)
$env:PYTHONPATH = (Get-Location).Path
python -m audit_engine.cli.main local <domain> --profile local --max-pages 30
```

The `local` subcommand does:
- Site crawl up to `max_pages`
- Google Places lookup (site domain -> Place ID) for the business
- Serper-driven citation discovery: 1-2 SERP queries scoped to the business name + phone / + address, mapped against a tier-1 directory list, with name/address/phone match scores inferred from each snippet (if SERPER_API_KEY)
- Serper geo-grid SERP for the business's primary service keyword (if SERPER_API_KEY)
- Deterministic on-page (homepage + key pages), technical (subset), and full local analyzer set

Output: `data/audits/<domain>/<run_uuid>/`.

Capture `run_uuid` and `artifact_dir` from the Python output.

### 3. Dispatch teams

In a single message, dispatch in parallel:

**Team D (local SEO, primary)** - all 4:
- `d1-gbp-analyst`
- `d2-citations-nap-analyst`
- `d3-reviews-analyst`
- `d4-local-pack-geo-analyst`

**Team A (critical on-page only)** - 2 agents:
- `a2-keyword-semantic-analyst` for geo-keyword coverage
- `a4-internal-links-analyst` for service-area page internal linking

**Team B (critical technical only)** - 1 agent:
- `b4-schema-analyst` for LocalBusiness schema validation

Skip Teams C unless the user passes `--include-offpage`.

### 4. Sequential meta team

Same as `/audit`: M1 -> M2 -> M3 -> M4.

The M4 report has a different structure for local audits:
- Executive summary leads with the local pack heatmap
- Top 10 findings prioritize GBP + citations + reviews
- Remediation roadmap weeks 1-4 are GBP + citation cleanup; month 2-3 are local content + landing pages

### 5. Summarize to the user

Print:
- Local scorecard (GBP health, citation strength, review health, local pack share)
- Top 5 local critical findings
- Top 5 local quick wins
- Path to report

## Hard rules

- Never claim to have analyzed a Place that the Places API did not return. If Places returned no match, surface that and ask the user for the business name + city to retry.
- Never invent citation data. If `citations.json` carries an `error` field or is missing (no SERPER_API_KEY), run NAP-on-site-only and mark findings `confidence: 0.5`. Cap `confidence` at 0.6 even when citations.json is present, because it is snippet inference, not a direct directory crawl.
- Geo-grid claims need actual grid probe data. Without Serper keys, skip LOC-029 entirely and note the gap.

## Budget

5-8 minutes for a 30-page local-business site with all APIs configured. Without APIs, 1-2 minutes with significant gaps.
