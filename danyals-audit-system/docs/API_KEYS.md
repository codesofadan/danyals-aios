# SEO-AUDIT-OS — API Keys & Client Handover

This is the single source of truth for the integrations the audit system uses, what each one unlocks, and exactly where to plug the key.

When the client provides credentials, drop them into a file named `.env` at the repo root (use [.env.example](../.env.example) as the template). The Python engine reads them at startup — no code changes needed.

---

## Required for a complete paid audit

| Env var | Provider | Unlocks | Free tier | Where to get it |
|---|---|---|---|---|
| `SERPER_API_KEY` | Serper.dev | SERP positions, competitor keyword overlap, 49-probe geo-grid for local pack, Google AI Overview citation detection, tier-1 citation discovery + NAP inference | 2,500 searches free (one-time signup); $50/mo for 50k after that | https://serper.dev → Sign up → Dashboard → API key |
| `GOOGLE_API_KEY` | Google Cloud Console | PageSpeed Insights (LCP/CLS/INP, Lighthouse score), Places API (GBP discovery, photos, hours, posts, reviews), Maps for geo-grid | 25k PSI/day + Places at standard pricing (within $200/mo Maps credit) | https://console.cloud.google.com → APIs & Services → Credentials → Create API Key. Enable: PageSpeed Insights API, Places API (New), Maps JavaScript API |

That is the entire required stack. Two providers, $0-$65/month depending on scale (Serper free tier covers most agencies until you cross ~50 audits/month).

## Recommended (optional)

| Env var | Provider | Unlocks | Free tier | Where to get it |
|---|---|---|---|---|
| `GOOGLE_APPLICATION_CREDENTIALS` | Google Cloud NL | Entity salience, sentiment analysis on page copy and review text | 5k units/mo free | https://console.cloud.google.com → Service Accounts → Create → Download JSON key. Set this var to the path of the JSON file |
| `FIRECRAWL_API_KEY` | Firecrawl | JS-rendered crawl for SPAs and dynamic content | 500 pages free | https://www.firecrawl.dev → Sign up → API keys |
| `ANTHROPIC_API_KEY` | Anthropic | Powers the free AI visibility probe (~$0.05 per audit). Optional if you already have Claude Code subscription | Pay-as-you-go | https://console.anthropic.com → API keys |

## Not used by this system

- **BrightLocal** — Removed. Citation discovery + NAP consistency is now handled by Serper SERP queries against a tier-1 directory list with snippet-level NAP inference. See [audit_engine/integrations/citations.py](../audit_engine/integrations/citations.py) for the implementation. Saves $39-$79/month per agency seat.
- **Moz Links API / Moz Local** — Removed by default. The system intentionally does not include a paid backlink audit; the client expense did not justify the reporting value. Can be turned back on via `--moz` on a one-off run if MOZ_ACCESS_ID + MOZ_SECRET_KEY are set.
- **Otterly.AI / Profound** — Removed. AI search visibility is handled via Serper's AI Overview detection + an optional Claude-based probe + a 3-minute manual checklist. Saves $29-$499/month per tracked brand.
- **Ahrefs / Semrush / Majestic** — Not used. Backlink data is out of scope.
- **DataForSEO** — Explicit reject by the client.

## Optional

| Env var | Purpose |
|---|---|
| `SEO_AUDIT_CHROME` | Override the Chromium path used by the PDF reporter. Defaults to the bundled Playwright install |

---

## How to install keys

1. In the repo root, copy the template:
   ```
   copy .env.example .env
   ```
2. Open `.env` in any text editor.
3. Paste each value after the `=` sign. No quotes, no spaces:
   ```
   SERPER_API_KEY=ser_abc...
   GOOGLE_API_KEY=AIzaSy...
   ```
4. Save. The engine picks them up automatically on the next run.

The `.env` file is gitignored — keys never leave the local machine.

---

## How AI Search Visibility is handled (no paid API)

The audit reports AI visibility across three surfaces using free methods:

| Surface | Method | Cost |
|---|---|---|
| Google AI Overview | Serper's `aiOverview` block in the SERP response — detected automatically when present | $0 (already paying for Serper) |
| ChatGPT / Perplexity / Gemini | Claude-based probe — ask Claude 8-12 brand-relevant queries, parse for brand mention | ~$0.05/audit via Claude API, $0 if using Claude Code subscription |
| All four (ground truth) | Manual checklist — the audit generates 10 exact queries the user runs by hand | $0, takes ~3 minutes |

The combination is equivalent in monthly reporting value to Otterly.AI ($29/mo) for a small agency, and far cheaper than Profound ($499/mo) at scale.

---

## What each provider costs for a typical audit run

| Run | API calls | Approximate cost |
|---|---|---|
| `/audit-quick` (20 pages) | 5 PSI = 5 calls | $0 (free tier) |
| `/audit` 100 pages, single client | 5 PSI + 5 Serper SERPs + 1 Places + 2 Serper citation queries = ~13 calls | $0.05 - $0.20 if outside Serper free tier |
| `/audit-local` 30 pages, single client | 1 Places + 2 Serper citation queries + ~49 Serper geo-grid probes = ~52 calls | $0.05 - $0.25 |
| `/audit` + 5-domain competitor benchmark | + 25 Serper = +25 calls | $0.20 - $0.50 |
| Monthly recurring on 10 clients with weekly tracking | ~600 calls | $5 - $15 once past the 2,500-credit Serper signup tier |

Everything stays inside free tiers for the first 15-50 audits. Past that, Serper Hobby ($50/mo for 50k) covers any realistic agency volume. Google Places stays within the $200/mo Maps Platform credit at agency volume.

---

## Verifying a key is wired correctly

Run a tiny smoke test from the project root:

```
python -c "from audit_engine.config import load_settings; s = load_settings(); print({k: 'SET' if v else 'MISSING' for k, v in s.__dict__.items()})"
```

Output should show `SET` next to every key you populated.

---

## Free vs Paid mode

The system asks once at the start of every `/audit` run:

| Mode | CLI flag | Behavior |
|---|---|---|
| Paid | `--mode auto` (default; uses configured keys) or `--mode paid` (requires all) | Calls Serper + Google (PSI + Places). Produces measured SERP positions, CWV, GBP data, Serper-driven citation discovery + NAP inference, AI Overview presence. Final PDF includes these numbers. |
| Free | `--mode free` | Skips every paid integration regardless of keys. Final PDF presents only what was measurable from crawl + schema + on-site signals. The PDF never mentions API keys, blocked dimensions, or upgrade paths. |

Same system, two reports. Free mode is ideal for prospects and demos. Paid mode is for retainer clients.

---

## Degraded-mode behavior (what happens if a key is missing in auto mode)

The engine never fails on a missing key. Instead:

- The integration emits an `error` field in its raw response file.
- Affected checks in `findings.json` are flagged as `status: n_a` with `confidence: 0.3-0.5`.
- The analyst agents (B2 perf, D1 GBP, D2 citations, D3 reviews) detect the n_a status and produce **structural recommendations** (e.g., GBP checklist, citation roadmap) instead of measured findings. D2 specifically caps `confidence` at 0.6 even when Serper is configured, because citation presence is inferred from SERP snippets rather than a direct per-directory crawl.
- The final PDF flags affected dimensions on the scorecard with a `No keys` chip — no fabricated numbers.

This means the audit always produces a usable report. The missing keys just turn measured numbers into actionable roadmaps. Provision the keys, re-run, and the same `findings.json` slot becomes a real metric.
