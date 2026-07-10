---
description: Compare an audit run against the prior run for the same domain. Surfaces score deltas + new/resolved findings.
argument-hint: <domain>
---

# /audit-track $ARGUMENTS

Run `python -m audit_engine.cli.main track $ARGUMENTS` from the repo root (with PYTHONPATH set to the repo root). Summarize to the user:

1. Score deltas across Overall + 4 dimensions
2. Top 5 new (regression) findings with their `check_id`
3. Top 5 resolved findings
4. Persisted-issue count
5. Recommendation: prioritize fixing critical regressions first

If `$ARGUMENTS` is empty, ask for a domain. If only one run exists for the domain, surface that and recommend running `/audit` once more to enable diffing.
