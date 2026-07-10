# Knowledge base

Per-agent knowledge slices. Each agent loads only its relevant subset to keep context tight.

## Structure

```
knowledge/
├── google/                Google Search Quality Rater Guidelines, Helpful Content, Search Status Dashboard
├── eeat/                  E-E-A-T operational framework with examples
├── local-seo/             GBP playbook, citations 2026 reality, NAP rules
├── core-web-vitals/       LCP/CLS/INP/TTFB thresholds + diagnosis trees
├── schema-org/            LocalBusiness, Service, FAQ, Article, Breadcrumb specs
├── geo-ai-search/         AI Overviews + Perplexity + ChatGPT citation patterns + llms.txt
├── frameworks/            Aleyda Solis, Cyrus Shepard, Andrew Shotland, Joy Hawkins, Marie Haynes (deferred - cite when adding)
└── 2026-updates/          Confirmed algorithm changes 2024-2026
```

## Files present (Phase 5 baseline)

- `google/quality-rater-guidelines.md` - QRG distilled for A1, A2, M3
- `eeat/framework.md` - operational E-E-A-T rubric for A1
- `local-seo/playbook-2026.md` - 12 pillars + tier-1 citations + GBP rules + geo-grid targets for D1-D4
- `core-web-vitals/thresholds.md` - LCP/INP/CLS thresholds + common causes for B2
- `schema-org/local-business.md` - LocalBusiness required + recommended properties for B4
- `geo-ai-search/playbook-2026.md` - GEO 2026 reality, AI crawler list, citation patterns for A5 + C4
- `2026-updates/algorithm-timeline.md` - confirmed updates 2024-2026 for A1 + M3

## How agents reference these

Each agent's definition (`.claude/agents/<team>/<id>.md`) names the knowledge files it loads at runtime in the "Inputs" section. The runtime is responsible for reading the named files into the agent's context.

## Refresh cadence

Run `/kb-refresh` (or `python -m audit_engine.cli.main kb-refresh` once implemented) quarterly to:

1. Pull the latest Search Status Dashboard
2. Re-summarize confirmed algorithm changes into `2026-updates/algorithm-timeline.md`
3. Refresh citation count benchmarks for `local-seo/playbook-2026.md`

The refresh command is a Phase 6 deliverable.
