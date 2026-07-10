---
description: Run the local SEO audit (5-8 min). Focused on GBP, citations, reviews, NAP consistency, local pack rankings. For local-market clients.
argument-hint: <domain>
---

# /audit-local $ARGUMENTS

Run the audit-local skill against `$ARGUMENTS`. Follow `.claude/skills/audit-local/SKILL.md` (repo-relative):

1. Validate the domain
2. Run the Python pipeline: `python -m audit_engine.cli.main local $ARGUMENTS --profile local --max-pages 30`
3. Capture run_uuid + artifact_dir from output
4. Dispatch Team D (4 agents) + critical Team A (a2, a4) + critical Team B (b4) in parallel
5. Sequentially run M1 -> M2 -> M3 -> M4
6. Summarize: local scorecard, top 5 critical, top 5 quick wins, report path

If `$ARGUMENTS` is empty or invalid, ask the user for a domain rather than guessing.
