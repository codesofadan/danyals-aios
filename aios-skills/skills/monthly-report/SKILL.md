---
name: monthly-report
description: Assembles the monthly client report - an AI-written branded narrative composed strictly from real backend numbers (audit deltas, content shipped, milestone progress, off-page, spend) and then syncs the client's workbook to Google Sheets. Use when the operator says "monthly report", "client update deck", "end-of-month report", or "write this month's client summary". Every figure is grounded in a backend read; the narrative invents nothing. Syncing is a lead-only external write to Google Sheets, so this skill is manual-invocation only.
argument-hint: "[client] [month]"
arguments: [client, month]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py get *) Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py post *) Read
---

# Assemble the Monthly Client Report

**Purpose.** Produce this month's client report: a branded narrative written by the operator model over REAL backend rows (the Command Center KPIs, milestone progress, content-job stats, the report workbook), then push the client's workbook to its Google Sheet. The judgement here is turning grounded numbers into a clean client narrative; the numbers themselves come only from the backend.

**Who runs it.** Reading the Command Center / milestones / content stats / workbooks needs `view_reports` (any staff). The sync (`POST /reports/sync`) requires a LEAD (owner/admin/manager); a non-lead is 403'd. A portal client is 403'd off the namespace.

## Required inputs / keys
- `$client` - the client to report on (resolved to a workbook in Step 4).
- `$month` (optional) - the reporting month label; defaults to the current month.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- The shared client `${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py` (the plugin's `../../scripts/aios_client.py`); shared wiring in `../../reference/`.
- The Google Sheets credential must be live for a REAL sync. Dormant -> `GET /reports/connection` `connected=false`; the sync DEGRADES (status flips, buffer retained, 0 rows pushed). Label it. The report NARRATIVE is composed by this skill from data that is already fetched, so it does not itself spend metered AI budget; content-job spend is gated separately server-side.

**Trigger.** A request for the monthly client report, update deck, or end-of-month summary.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the Command Center KPIs + spend (GET /command-center)
- [ ] Step 2: Read milestone progress for the client (GET /milestones)
- [ ] Step 3: Read the content shipped this period (GET /content/jobs/stats)
- [ ] Step 4: Resolve + read the client's workbook (GET /reports/workbooks, /reports/connection)
- [ ] Step 5: Write the grounded narrative (no invented figures)
- [ ] Step 6: Sync the workbook to Sheets (POST /reports/sync) - lead-only; confirm via sync-events
```

1. **Read the Command Center.**
   Run `aios_client.py get /command-center`. Pull `statTiles` (audits this month + month-over-month `delta`, active clients, active tasks, spend MTD), the `clients` progress row for `$client`, and `spend`.

2. **Read milestones.**
   Run `aios_client.py get /milestones`. Find `$client`'s project: `health`, the per-stage `status` list, and the current stage. Progress % is derived from the stage weights (completed 1.0, in_progress 0.5, blocked 0.25, upcoming 0.0) per the milestone stage model - a formula, not an invented number.

3. **Read content shipped.**
   Run `aios_client.py get /content/jobs/stats` for the content-pipeline counts (drafted / in review / published). Use only these counts.

4. **Read the workbook + connection.**
   Run `aios_client.py get /reports/workbooks` (select `$client`) and `aios_client.py get /reports/connection` (is Sheets live?).

5. **Write the narrative.** Compose the branded monthly summary from Steps 1-4 only. Every figure must trace to a fetched field. Plain client-facing prose: no em/en dashes, no softening adverbs, no fabricated traffic/ranking/DA numbers. Where the Command Center `traffic` series is used, label it the audit-derived placeholder it is (`placeholder: true`) - never as live organic traffic.

6. **Sync (lead-only).** Run `aios_client.py post /reports/sync --json '{"workbookId":"<id>"}'`, then `aios_client.py get /reports/sync-events` to confirm rows pushed. Report the honest connected/degraded state.

## Decision points
- If the caller is not a lead -> deliver the narrative read-only and **STOP** before Step 6; report "sync requires a lead".
- If `connected=false` -> the sync DEGRADES (0 rows, buffer held). Deliver the narrative but label the sync "degraded, Sheets key pending"; do not claim it reached Google Sheets.
- If `$client` has no milestone project or no workbook -> report the gap ("no project/workbook on file for this client") and route to a human; do not fabricate stage progress or a sheet.
- If a KPI is zero for the period -> report zero honestly ("0 content jobs published this month"); a flat month is a real result, not a reason to inflate.
- If the traffic placeholder would carry the narrative -> do not lead with it; anchor on audits/content/milestones which are real rows.

## Common Pitfalls
- Inventing a traffic lift, ranking gain, or DA number -> forbidden. The platform has no live analytics; the `traffic` series is an audit-derived placeholder. State only real audit/content/milestone/spend rows.
- Reporting the sync as delivered when `connected=false` -> a degraded flush pushes 0 rows; say so.
- Deriving progress from vibes -> use the stage-weight formula over the real `status` values, nothing else.
- Em/en dashes or marketing adverbs in the client narrative -> the renderer strips them; write clean declarative prose.
- Padding a flat month with speculative wins -> report the real counts; route any "what next" to milestones/upsells, not fabrication.

## Output format
Emit verbatim:

```
MONTHLY REPORT - <client> - <month>
Health: <on_track|at_risk|completed>   Milestone stage: <current stage> (<progress>% derived)
Audits this month: <value> (<delta> vs last month)
Content shipped: <published> published, <in review> in review, <drafting> drafting
Off-page / authority: <grounded stage note or "no update this period">
Spend (client/platform): <as available from command-center>
--- CLIENT NARRATIVE ---
<3-6 plain sentences summarizing the month from the numbers above. No em dashes, no invented figures. Traffic, if mentioned, labeled an audit-derived estimate.>
------------------------
Sheets sync: workbook <id> -> status=<synced>  rows pushed=<from sync-events>  state=<LIVE | DEGRADED (Sheets key pending)>
Gaps routed to a human: <list any missing project/workbook/data, or "none">
```

Rubric enforced (reference, not inlined): the audit report-design contract and `backend/docs/CONTENT-DOCTRINE.md` narrative discipline; the `GET /reports/types` tab map. Shared wiring + degrade contract: `../../reference/`.
