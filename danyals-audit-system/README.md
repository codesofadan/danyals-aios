# SEO-AUDIT-OS (Danyal build)

A multi-agent SEO audit system. Runs as a Claude Code slash command. Produces consulting-grade audits covering 300+ checks across on-page, technical, off-page, and local SEO.

Built for an agency that serves every niche: the audit picks a profile per client (general, local, ecommerce, saas, content). For local-market clients, the engine is best-in-class on Google Business Profile, citations, reviews, and local-pack ranking depth.

Client-facing branding (brand name, contact email, colors, logo) lives in `branding.json` at the repo root - edit that one file to re-skin every report.

## Quick start

```
# Open this folder in Claude Code (VS Code extension, JetBrains, or `claude` CLI)
/audit https://example.com
```

The first audit will:

1. Crawl the site (sitemap, robots.txt, page inventory, render diff)
2. Fetch Core Web Vitals (PageSpeed Insights + CrUX)
3. Pull backlinks (Moz, optional, off by default), SERP data + citation discovery (Serper), GBP data (Google Places), AI search visibility (Otterly, optional)
4. Dispatch four agent teams in parallel to evaluate all 300 checks
5. Run quality gates (per-agent self-review, critic, council)
6. Produce four artifacts:
   - `report-executive.pdf` (10-15 pages, top-tier consulting design)
   - `report-full.pdf` (40-80 pages, every check)
   - `remediation.md` (developer-friendly action playbook)
   - `findings.json` (machine-readable)

Outputs land under `data/audits/<domain>/<run_id>/`.

## Slash commands

| Command | Purpose |
|---|---|
| `/audit <domain>` | Full multi-team audit |
| `/audit-quick <domain>` | Technical + top 20 pages on-page (3-5 min) |
| `/audit-local <domain>` | Team D + critical from A/B (5-8 min) - local SEO focus |
| `/audit-page <url>` | Single-URL deep dive |
| `/audit-competitor <domain> <competitor>` | Gap analysis |
| `/audit-track <domain>` | Delta vs previous audit |
| `/audit-report <audit-id> [--format pdf\|html\|md]` | Regenerate report from cache |
| `/audit-fix <finding-id>` | Per-finding remediation guide |
| `/kb-refresh` | Update knowledge base sources |

## Installation

Prereqs:
- Claude Code (VS Code extension or CLI), 2.1.0+
- Python 3.11+
- API keys: Serper.dev, Google Cloud (PageSpeed + Places + NL). Optional: Moz, Otterly.AI

```bash
# Install Python deps
pip install -e .

# Install Playwright browsers (for JS render diff)
playwright install chromium

# Configure API keys
cp .env.example .env
# Edit .env with your keys
```

Then open the directory in Claude Code. The `.claude/skills/` and `.claude/agents/` are picked up automatically.

## Cost and time

Wall-clock and API-spend targets:

| Site size | Wall clock | API spend |
|---|---|---|
| 20 pages | 3-5 min | $0.10-0.30 |
| 100 pages | 8-12 min | $0.50-1.50 |
| 500 pages | 15-25 min | $2-5 |
| 2000+ pages | 30-60 min | $8-20 |

Anthropic spend (agent calls) is on top, typically $1-5 per audit at 100 pages.

## Architecture

```
User runs /audit <domain>
        |
        v
+-----------------------------------------+
| M1 Orchestrator                         |
+-----------------------------------------+
        |
   Phase 1: Discovery (Python, deterministic)
   - Sitemap, robots.txt, page inventory
   - Playwright crawl + Firecrawl
   - PSI / CrUX / Google Places / Serper (SERP + citation discovery + geo-grid)
        |
   Phase 2: Parallel Team Analysis
   |- Team A: On-Page (5 agents)
   |- Team B: Technical (5 agents)
   |- Team C: Off-Page (4 agents)
   `- Team D: Local SEO (4 agents)
        |
   Phase 3: Synthesis
   - M2 Findings Prioritizer
   - M3 Content Critic (quality gate)
   - M4 Report Writer
        |
        v
   Deliverables under data/audits/<domain>/<run_id>/
```

## Repo layout

See [CLAUDE.md](CLAUDE.md) for the full workspace map and operating philosophy.

## Status

**Danyal customization in flight.** Engine is production-ready (adapted from a prior client build). Waiting on Danyal's branding details and API keys - fill `branding.json` and `.env` when they arrive.

## License

Proprietary. Built by Xegents AI for Danyal.
