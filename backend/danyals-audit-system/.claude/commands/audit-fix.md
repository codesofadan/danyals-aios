---
description: Print a detailed remediation guide for a specific check ID from a recent audit.
argument-hint: <check_id> [--run <run_uuid>]
---

# /audit-fix $ARGUMENTS

Run `python -m audit_engine.cli.main fix $ARGUMENTS` from the repo root. If the output shows multiple matching findings, summarize the common pattern across pages and propose one consolidated fix.

For each finding shown, write the remediation as a numbered step list with:
1. What to change (line, file, element, schema property)
2. The expected outcome (which check transitions from fail to pass)
3. Time estimate (5 min / 30 min / 1 hour / half day)

If the user passes an unknown check_id, suggest the closest matches from `checklists/*.yaml`.
