# Cost control & the money-dial

Cost control is the reason the platform is cloud-hosted. Every paid provider call passes
through **one gate** before it runs. Grounded in `backend/app/services/cost_gate.py`,
`app/services/cost_store.py`, `app/schemas/cost.py` (the `DIAL_FEATURES` registry), and
invariant #10 in `backend/CLAUDE.md`.

## The gate (runs before ANY paid call)

```
dial mode → cache → per-client budget cap → daily spend-stop → call + log
```

- **Dial** — each paid feature has a money-dial mode: **`off`** (never call — degrade),
  **`byhand`** (manual/approval only), **`api`** (call live). An **unregistered** dial key
  resolves to `off` and `PATCH /cost/dials` rejects it, so an unregistered spender is
  *unswitchable-on* (dead on arrival). `tests/test_dial_registration.py` sweeps every
  module's `_FEATURE`.
- **Cache** — a cached response costs **$0** (Redis). Content research is cached by
  `(keyword, geo, serp_date)`; context embeddings by content checksum.
- **Client cap** — a per-client budget cap.
- **Daily spend-stop** — an agency-wide daily ceiling.
- **Call + log** — the real call runs and its cost is written to the cost log.

A block at any stage **DEGRADES** — the job holds at an honest `$0` (content holds at
`drafting`, context holds the watermark, policy leaves the change-event un-enriched). It
**never crashes** and **never retry-loops to force spend**. API: `/cost/*`
(`/cost/dials`, budgets, cost log).

## Product direction (PRODUCT-OVERHAUL-BACKLOG §E — high priority)

- **No predefined/fixed prices.** Remove hard-coded estimates (e.g. the old $1.50 audit
  estimate); cost is computed at **runtime** only.
- **A spend halt stops EVERY API** (internal + external), not just one provider.
- Provider toggles / manual mode / API mode must actually work end-to-end.

## Dial features (the registry — `DIAL_FEATURES` in `app/schemas/cost.py`)

That tuple is the **source of truth**; this table mirrors it (key · provider · default
mode). If it drifts, trust the code.

| Dial key | Feature | Provider | Default |
|---|---|---|---|
| `tech_audit` | Technical Audit (live crawl/rank) | DataForSEO | api |
| `cwv` | Core Web Vitals | PageSpeed (free tier) | api |
| `content` | Content Pipeline (Claude drafting + images) | Anthropic | api |
| `content_research` | Content Research (SERP top-10 teardown) | Serper | api |
| `backlinks` | Backlink Manager (monitoring + Web2 publish) | Serper | byhand |
| `citations` | Citation Builder (auto-submit; CAPTCHA+proxy spend) | Serper | api |
| `local_seo` | Local SEO (GBP + map-pack) | Places | byhand |
| `keywords` | Keyword Research | Serper | off |
| `rank_tracker` | Rank Tracker (standing per-client, client pays) | Serper/DataForSEO | off |
| `competitor_intel` | Competitor Intel | Serper | (module) |
| `on_page` | On-page analysis/apply | — | (module) |
| `site_analytics` | GSC/GA4 import | Google | (module) |
| `context` | Client Context (living summary, Claude) | Anthropic | api |
| `context_embed` | Context Embeddings | Voyage | api |
| `policy` | Policy Radar (change analysis, Claude Haiku) | Anthropic | api |
| `gmb` | GMB Posts (GBP post drafting, Claude) | Anthropic | byhand |
| `ai_assist` | In-Product AI (dashboard assist, Claude) | Anthropic | api |

Notes: **citations** is a distinct dial from **backlinks** because a submission run spends
real money (CAPTCHA solves + proxy bandwidth), whereas backlinks meters near-free
monitoring/publish pulls. **rank_tracker** is the platform's first *standing* per-client
cost (recurs nightly) — the module prices the monthly commitment before a lead can
subscribe, hence default `off`. Two Part-8 modules deliberately reuse an existing dial that
already names their product concept rather than minting a twin (`keyword_research →
keywords`, `local_seo → local_seo`).

## Pricing knobs

Per-provider unit prices are `price_*` settings in `app/config.py` (e.g.
`price_serper_per_query`, `price_dataforseo_per_call`, `price_anthropic_*_per_mtok`,
`price_google_per_call`). These are estimation inputs for the cost log, aligned with the
product direction to compute cost at runtime rather than hard-code per-feature dollar
figures in the UI.
