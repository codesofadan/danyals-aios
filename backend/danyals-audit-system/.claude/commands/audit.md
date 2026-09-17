---
description: Run the full multi-team SEO audit (15-30 min). Crawls 100+ pages, runs on-page + technical + off-page + local SEO (if applicable), dispatches all 4 teams, produces consulting-grade reports.
argument-hint: <domain>
---

# /audit $ARGUMENTS

Run the audit skill against `$ARGUMENTS`. Follow `.claude/skills/audit/SKILL.md` (repo-relative) end to end:

1. Validate the domain
2. Run the Python pipeline: `python -m audit_engine.cli.main full $ARGUMENTS --profile <profile> --max-pages 100` (profile per the skill's selection rule: `local` for local-market businesses, else `ecommerce`/`saas`/`content`/`general`)
3. Capture run_uuid + artifact_dir from output
4. Dispatch Teams A + B + C (and D if profile=local) in parallel
5. Sequentially run M1 -> M2 -> M3 -> M4
6. Summarize: scorecard, top 10 critical, top 10 quick wins, report paths, methodology footer

If `$ARGUMENTS` is empty or invalid, ask the user for a domain rather than guessing.
