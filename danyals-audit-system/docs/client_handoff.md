# SEO-AUDIT-OS — Client Handoff

Everything you need to run this audit system on your own machine. Hand this to your developer and they'll be productive in under an hour.

---

## What this is

A multi-agent SEO audit system that crawls a website, runs 363 distinct check types across on-page, technical, off-page, and local SEO, dispatches 16+ specialist AI analysts in parallel, and produces a consulting-grade PDF report. End to end: 15-25 minutes for a 100-page site.

The system is yours. The code lives in this repository. The API keys live in `.env`. The audit history lives in `data/audits/`. Nothing leaves your machine unless an API call needs it.

Built on:
- Python 3.13 (`audit_engine/` — the deterministic crawl + analysis brain)
- Claude Code agents (`.claude/agents/` — the 21 specialist analysts and the report writers)
- Chromium via Playwright (PDF rendering)
- SQLite (audit history at `data/seo_audit.db`)

---

## Quick start

### 1. Open Claude Code in this directory

```
cd <path-to-this-repo>
claude
```

### 2. Run an audit

In the Claude Code chat, type one of:

```
/audit example.com
/audit-quick example.com
/audit-local example.com
```

You'll be asked one question:
- **Paid mode** (uses your API keys for measured SERP, page speed, GBP, citations, AI Overview detection — ~15-25 min) or **Free mode** (no paid APIs, structural audit only — ~10-15 min).

The report always renders in full; there is no condensed mode. Pick your answer and walk away. The system runs the deterministic Python pipeline, dispatches the team agents in parallel, then writes the report. The final PDF lands at the project root and in the run archive.

### 3. Open the report

The client-facing PDF is at the project root:

```
<domain>_SEO_Audit_Report_<DD-Month-YYYY>.pdf
```

Email that file to your client. The archive copy is at `data/audits/<domain>/<run-uuid>/report-final.pdf`.

---

## The three slash commands

| Command | When to use | Duration | Output |
|---|---|---|---|
| `/audit <domain>` | Full audit for retainer clients or sales pitches. Covers on-page, technical, off-page, and local SEO. | 15-25 min | ~30-40 page PDF |
| `/audit-quick <domain>` | Fast technical + top 20 pages of on-page. For preliminary sales conversations. | 3-5 min | ~10 page PDF |
| `/audit-local <domain>` | Local SEO deep dive. GBP, citations, reviews, local pack visibility across the service area. | 5-8 min | ~20 page PDF |

Optional commands:

| Command | Purpose |
|---|---|
| `/audit-fix <check-id>` | Print the detailed remediation guide for a specific finding from a recent audit |
| `/audit-track <domain>` | Compare the latest audit run against the previous one — score deltas, new issues, resolved issues |
| `/audit-report <run-uuid>` | Regenerate the PDF from a cached run without re-crawling |

---

## What's installed and what's needed

### Required (you already have these set up)

| Tool | Purpose |
|---|---|
| Python 3.13 | The audit engine |
| Claude Code CLI | The interactive interface and the AI analyst agents |
| Playwright + Chromium | PDF rendering and JavaScript rendering of crawled pages |

To verify they're installed:

```
python --version
claude --version
playwright --version
```

If any of those fail, see the `Install from scratch` section at the bottom of this doc.

### API keys (already in `.env`)

The system reads its keys from `.env` in the project root. Your current `.env` has the following providers configured (the system never logs the values):

| Provider | Used for | Required? |
|---|---|---|
| `ANTHROPIC_API_KEY` | The 16 specialist AI agents that write the narrative sections | Required for full audits |
| `SERPER_API_KEY` | SERP sampling, citation discovery, competitor SERP comparison | Required for paid mode |
| `GOOGLE_API_KEY` | Universal fallback for PageSpeed Insights, Places, NL | Required for paid mode |
| `GOOGLE_PAGESPEED_API_KEY` | Page speed and Core Web Vitals | Optional (falls back to `GOOGLE_API_KEY`) |
| `GOOGLE_PLACES_API_KEY` | Google Business Profile data | Optional (falls back to `GOOGLE_API_KEY`) |
| `GOOGLE_NL_API_KEY` | Google Cloud Natural Language entity extraction | Optional (falls back to `GOOGLE_API_KEY`) |

If you ever need to add a key, open `.env` in any text editor and add the line:

```
GOOGLE_NL_API_KEY=your-key-here
```

Save the file. The next audit run picks it up automatically. No restart needed.

### What this system does NOT use

- **No DataForSEO.** Rejected by project policy.
- **No Moz / Ahrefs / Semrush.** Backlink data is intentionally out of scope. If a client asks for a backlink audit, that's a separate engagement.
- **No Otterly / Profound.** AI visibility is handled via Serper's AI Overview block plus structural analysis of your on-site signals.

---

## Where things live

```
<repo root>\
├── docs\client_handoff.md     ← THIS FILE
├── CLAUDE.md                  ← Operating rules + style guide
├── README.md                  ← Repo overview
├── branding.json              ← YOUR branding: name, contact email, colors (edit this one file)
├── .env                       ← API keys (gitignored, never committed)
├── audit_engine\              ← Python crawler + analyzers + scoring
├── .claude\                   ← Agent definitions + slash commands
│   ├── skills\                  - One folder per slash command
│   ├── agents\                  - 21 specialist analysts
│   └── settings.json            - Permissions
├── checklists\                ← 363 check definitions (YAML)
├── knowledge\                 ← Knowledge base used by agents
├── data\
│   ├── audits\<domain>\<uuid>\  - Per-run artifacts (PDF, JSON, MD sections)
│   └── seo_audit.db             - SQLite history
├── docs\
│   ├── references\              - Spec docs and benchmark reports
│   ├── resources\               - Manual audit checklist spreadsheets (the spec the reports mirror)
│   └── API_KEYS.md              - Notes on how each key was provisioned
├── generated-audits\          ← Client-facing PDF archive
├── scripts\
│   └── generate_audit_pdf.py    - The PDF renderer
├── templates\                 ← Report templates
└── tests\                     ← Unit + integration tests
```

After every audit, the client-facing PDF is copied to the project root with the filename `<domain>_SEO_Audit_Report_<date>.pdf`. The archive lives at `data\audits\<domain>\<run-uuid>\`.

---

## Tuning the report

### Branding

All client-facing branding lives in **`branding.json` at the repo root**. Edit that one file and every report picks it up on the next run:

```json
{
  "brand_name": "Your Agency Name",     // cover + footer "Prepared by" line
  "brand_bold": "YOUR-AGENCY",          // bold part of the PDF footer strip
  "brand_suffix": "· Audit Engine",     // rest of the footer strip
  "contact_email": "you@youragency.com",// closing CTA page (QA-gate enforced)
  "accent_color": ""                    // optional hex; empty = default cyan
}
```

No code changes needed. The `--brand-bold` / `--brand-suffix` CLI flags still exist for one-off overrides. For deeper recolouring, edit the `PALETTE` dict at the top of `scripts/generate_audit_pdf.py`.

### Tone

The voice is owner-facing plain English. No SEO jargon. If you want a more technical tone (for in-house SEO clients), edit `.claude/skills/audit/SKILL.md` and adjust the "CLIENT-FACING WRITING RULES" block. Each agent then inherits the new rules on the next run.

### Page count

There is no page cap and no condensed mode. The report renders every issue the audit finds; page count follows the site's actual state.

---

## What to do when something fails

### "API key missing" message

Add the key to `.env` and re-run. No restart needed.

### Audit hangs at "Crawling..."

The site is probably blocking the user agent or returning 403/429. Check:

```
curl -A "SEO-AUDIT-OS/0.1 (+https://github.com/xegents/seo-audit-os)" -I https://<domain>
```

If you get a 403, the client's hosting provider is blocking the audit crawler. Ask the client to whitelist the user agent, or run in free mode against a smaller page count.

### PDF generation fails with "Playwright render failed"

Run:

```
playwright install chromium
```

This installs the headless browser the renderer uses. One-time setup.

### Google Places returns 403

Your `GOOGLE_PLACES_API_KEY` doesn't have the Places API enabled in Google Cloud Console. Go to https://console.cloud.google.com, find the key, and turn on the "Places API (New)" library. Some keys are restricted to specific APIs; if Places is blocked, the local SEO section runs in degraded mode using on-site signals only (the report does not surface the failure to the client).

### Agent dispatch failed: "Anthropic SDK missing"

Run:

```
pip install anthropic
```

The audit engine needs the SDK to dispatch the 21 specialist agents.

### A team agent timed out

The system writes partial output to disk every few steps, so even a half-finished agent leaves something useful in `data/audits/<domain>/<run-uuid>/agent-<short>.md`. Re-dispatch only the failed agent by running the audit again — completed agents are skipped on the second pass via the cache.

---

## What the audit does behind the scenes

When you type `/audit <domain>`:

1. **Validate input.** Reject malformed domains, private IPs, etc.
2. **Ask for mode + depth.** Paid/Free, Condensed/Full.
3. **Run the deterministic Python pipeline.** Crawl up to 100 pages, parse HTML and schema, fetch PageSpeed Insights for the homepage, query Serper for 4-5 SERP samples, query Google Places for GBP data, check 18 tier-1 directories for citation coverage, run Google Cloud NL for entity extraction. All findings persist to `data/seo_audit.db` + `findings.json`.
4. **Dispatch 16 specialist AI agents in parallel.** Team A (5 on-page analysts), Team B (5 technical), Team C (2 brand/AI), Team D (4 local). Each agent reads the run artifacts, judges the AI-assisted checks, and writes its narrative to `agent-<short>.md`.
5. **Dispatch 7 report-writer agents in parallel.** One per report section (executive summary, on-page, technical, off-page/AI, local, action plan, methodology/appendix). Each pulls from the team-agent narratives and writes a polished section markdown file.
6. **Render the PDF.** The Python script `scripts/generate_audit_pdf.py` stitches the section files into HTML, then Chromium renders to PDF.
7. **Copy to root.** Final PDF is copied to `<domain>_SEO_Audit_Report_<date>.pdf` at the project root for easy access.

The whole pipeline is deterministic where it can be (crawl, parse, score) and AI-judged where it has to be (content quality, E-E-A-T, semantic SEO, narrative writing). The split is enforced by the architecture — Python files don't call Anthropic, agent definitions don't call the engine directly.

---

## How the scoring works (in case a client asks)

The four dimension scores (Content, Site Health, Search Visibility, Local Presence) are each a severity-weighted average of findings in that category, rescaled to 0-100.

- Each check produces a per-check score 0-10
- Severity weights: critical=3, major=2, minor=1, info=0.5
- Dimension score = (sum of score × weight) / (sum of weights), times 10

The overall score blends the four dimensions:
- General profile (default): Content 30% / Site Health 30% / Search Visibility 30% / Local Presence 10%
- Local profile (`--profile local`, for local-market clients): Content 30% / Site Health 25% / Search Visibility 15% / Local Presence 30%
- Other profiles (ecommerce, saas, content) defined in `audit_engine/scorers/aggregator.py`

When a dimension can't be measured (e.g. Search Visibility when Search Console isn't connected), it's excluded and the remaining weights renormalize.

Color bands:
- **75+** healthy (green)
- **50-74** needs work (amber)
- **<50** critical gap (red)

This is also documented in Section 07 of every audit report so clients can self-check.

---

## What's intentionally out of scope

Two things this audit doesn't cover. Document this to clients up front:

1. **Backlink profile.** No third-party backlink data is used. The system measures on-site brand and authority signals only. If a backlink audit is needed, that's a separate engagement using Ahrefs/Majestic.
2. **Google Search Console performance data.** Not currently wired in. Section 7 of the report explicitly notes this and recommends a 15-minute setup before the next quarterly audit run.

Both are explicitly stated in every report's methodology section so clients know what they're getting.

---

## When you need to update the knowledge base

Search algorithms change. The 2026 updates timeline lives in `knowledge/2026-updates/algorithm-timeline.md`. Local SEO best practices live in `knowledge/local-seo/playbook-2026.md`. GEO and AI search live in `knowledge/geo-ai-search/playbook-2026.md`.

When Google ships a confirmed algorithm update (Core, Helpful Content, Spam, Reviews), or when a new AI search platform launches (or one shuts down), update the relevant `.md` file. The agents read these on every run, so changes propagate to the next audit.

Quarterly refresh is the right cadence. Set a recurring calendar block.

---

## Install from scratch (only if onboarding a new machine)

```
# 1. Install Python 3.13 from python.org
python --version           # confirm 3.13+

# 2. Install Claude Code CLI
npm install -g @anthropic-ai/claude-code
claude --version           # confirm latest

# 3. Clone or copy this repository

# 4. Install Python dependencies (from the repo root)
pip install -e .

# 5. Install Playwright + Chromium
pip install playwright
playwright install chromium

# 6. Provision the .env file
copy .env.example .env
# then edit .env and paste in your API keys

# 7. Initialize the database
python -m audit_engine.cli.main init-db

# 8. Test
python -m audit_engine.cli.main quick example.com --max-pages 5
```

Once that quick test produces a PDF, you're live.

---

## Questions

The system is yours; the code is readable; everything is local. If something breaks in a way this doc doesn't cover, the answer is almost always in one of three places:

- `data/audits/<domain>/<run-uuid>/` — the per-run artifact directory has every intermediate file. If a section looks wrong in the PDF, open the matching `section-XX-*.md` and the agent files alongside it.
- `data/seo_audit.db` — SQLite. Open with any DB browser to inspect raw findings.
- `audit_engine/cli/main.py` — the pipeline orchestrator. Reading this top to bottom takes 30 minutes and shows exactly what every command does.

The whole point of this system is that it's transparent. Nothing is hidden, no black-box scoring, no proprietary buried decisions. Every number in every report traces back to a finding in `findings.json`, and every finding traces back to a check in `checklists/*.yaml`.

You own it. Make it yours.
