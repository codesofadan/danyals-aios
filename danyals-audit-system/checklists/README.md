# Checklists - Source of Truth

The 4 YAML files in this directory are the **source of truth** for every SEO check the system performs.

Every check has one home:

| File | Owner team | Checks |
|---|---|---|
| `on-page.yaml` | Team A (on-page agents A1-A5) | 118 |
| `technical.yaml` | Team B (technical agents B1-B5) | 101 |
| `off-page.yaml` | Team C (off-page agents C1-C4) | 80 |
| `local.yaml` | Team D (local agents D1-D4) | 40 |
| **Total** | | **339** |

Total = 339 (the 313-item user-supplied master list + 26 added local-specific checks; the local set activates when profile=local).

## Entry schema

```yaml
- id: ON-001                          # category prefix + zero-padded sequence
  name: Search intent match analysis  # human-readable check name
  subcategory: search-intent
  owner_agent: A2                     # M1-M4, A1-A5, B1-B5, C1-C4, D1-D4
  severity_default: critical          # critical | major | minor | info
  data_sources: [crawled_html, serper_top10, gsc_query]
  analyzer: audit_engine.analyzers.search_intent.match
  automation: ai-assisted             # full | ai-assisted | manual-prompt
```

Optional fields added in later phases:
- `evaluation_rubric`: rubric the agent applies
- `score_weight`: 0-10
- `reference`: canonical Google / Schema.org / industry doc URL
- `remediation_template`: path to a per-finding fix template
- `golden_fixture`: path to a test fixture for regression checks

## ID prefixes

- `ON-*` on-page (Team A)
- `TECH-*` technical (Team B)
- `OFF-*` off-page (Team C)
- `LOC-*` local SEO (Team D)

Meta agents (M1-M4) do not own checks directly; they receive findings and produce rollup scores or narrative output. Some `ON-*` scoring rows reference `M2` as the owner because they are rollups computed during synthesis, not raw checks.

## Local extraction

Thirteen items from the user-supplied master list are local-flavored and live ONLY in `local.yaml` (with LOC-* IDs). They do not appear in `on-page.yaml` or `off-page.yaml`:

| User-list item | LOC ID |
|---|---|
| Local SEO relevance analysis | LOC-031 |
| Geo targeted keyword optimization | LOC-030 |
| NAP consistency analysis | LOC-013 |
| LocalBusiness schema optimization | LOC-032 |
| Citation consistency analysis | LOC-012 |
| Local citation audit | LOC-011 |
| Google Business Profile optimization | LOC-001 |
| GBP category optimization | LOC-002 |
| GBP review analysis | LOC-021 |
| Review sentiment analysis | LOC-022 |
| Review velocity analysis | LOC-023 |
| Reputation management analysis | LOC-027 |
| Local prominence score | LOC-037 |

These are tracked in `scripts/verify_coverage.py` under `LOCAL_REROUTES`.

## Verification

```
python scripts/verify_coverage.py
```

The verifier proves every user-list item maps to one (and only one) YAML entry, lists duplicate IDs, and reports team load distribution. Exit code 0 = pass.

## Conventions

- IDs are stable. Once an ID is published do not renumber it. New checks get the next free id in the same category.
- Severities can be overridden per-finding at runtime if evidence justifies it. `severity_default` is the floor.
- `data_sources` is informational - the analyzer module is the authority on what it actually reads.
- Renaming a check is allowed; the ID is the join key.
