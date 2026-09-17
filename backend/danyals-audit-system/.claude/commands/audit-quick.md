---
description: Run the fast SEO audit (3-5 min). Crawls up to 20 pages, runs on-page + technical checks, dispatches Team A, produces a Markdown report.
argument-hint: <domain>
---

# /audit-quick $ARGUMENTS

Run the audit-quick skill against the domain `$ARGUMENTS`. Follow `.claude/skills/audit-quick/SKILL.md` (repo-relative) end to end:

1. Validate the domain
2. Run the Python pipeline via `python -m audit_engine.cli.main quick $ARGUMENTS --max-pages 20 --profile general` (use `--profile local` when the target is clearly a local-market business)
3. Capture the run_uuid + artifact_dir from the Python output
4. Dispatch Team A (a1-content-eeat-analyst, a2-keyword-semantic-analyst, a3-headings-meta-analyst, a4-internal-links-analyst, a5-geo-ai-search-analyst) in parallel
5. Sequentially run m2-findings-prioritizer, m3-content-critic, m4-report-writer
6. Summarize: overall score, top 3 critical, top 5 quick wins, report path

If `$ARGUMENTS` is empty or invalid, ask the user for a domain instead of guessing.
