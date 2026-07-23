---
name: report
description: The Reports module hub - reads the per-client workbooks, sync-event feed, report-type tab map, and the Google Sheets connection panel, then refreshes one client's workbook by flushing its buffer to its sheet. Use when the operator says "report", "client report", "refresh the workbook", "sync the sheet", "workbook status", or "push the report to Google Sheets". Syncing is a lead-only external write to Google Sheets and is manual-invocation only. For the monthly AI-written narrative use /monthly-report; to push every workbook at once use /sheets-sync.
argument-hint: "[client-or-workbook-id]"
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Refresh a Client Report Workbook

**Purpose.** Read a client's report workbook and the Sheets connection, then refresh it: flush the workbook's Redis write-buffer through the SheetStore to its Google Sheet in one batched update, and confirm the push via the sync-event feed. This skill moves real workbook data; it never fabricates a row count or a sync it did not perform.

**Who runs it.** Reading workbooks/sync-events/types/connection needs `view_reports` (any staff). Syncing (`POST /reports/sync`) requires a LEAD (owner/admin/manager) - the same set the RLS insert/update policies gate to; a non-lead is 403'd. A portal client is 403'd off the namespace.

## Required inputs / keys
- `$ARGUMENTS[0]` - the client name or the workbook row id to refresh. Resolve the name to a workbook `id` in Step 1.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer). The role decides read vs. sync.
- The shared client `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py`; shared wiring in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
- The Google Sheets service-account credential must be configured for a REAL push. When it is dormant, `GET /reports/connection` returns `connected=false` and a sync DEGRADES: the status still flips to `synced` optimistically but the buffer is retained and the sync events record 0 rows pushed. Report the degrade honestly; do not claim rows landed in Sheets when `connected=false`.

**Trigger.** A request to refresh/sync a single client's report workbook or to read the Reports module state.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the workbooks + resolve the target (GET /reports/workbooks)
- [ ] Step 2: Read the connection panel (GET /reports/connection) - is Sheets live?
- [ ] Step 3: Sync the workbook (POST /reports/sync {workbookId}) - lead-only
- [ ] Step 4: Confirm the push via the sync feed (GET /reports/sync-events)
- [ ] Step 5: Render the pinned output with the honest connected/degraded state
```

1. **Read the workbooks.**
   Run `aios_client.py get /reports/workbooks` and select the target by `client` name or `id`. Capture `client`, `sheet`, `tabs`, `rows`, `lastSync`, `status`.

2. **Read the connection.**
   Run `aios_client.py get /reports/connection`. Read `connected`, `accountShort`, and `buffer` (`queued`, `flushedToday`). This decides whether Step 3 is a real push or a degraded no-op. Optionally run `aios_client.py get /reports/types` for the tab/column map.

3. **Sync the workbook (lead-only).**
   Run `aios_client.py post /reports/sync --json '{"workbookId":"<id>"}'`. The response is the updated workbook (`status`, `rows`, `lastSync`).

4. **Confirm the push.**
   Run `aios_client.py get /reports/sync-events` and read the newest events for this `client` (`dataset`, `rows`, `ago`). Real rows pushed appear here; a degraded flush records 0.

5. **Render** the **Output format**, labeling the connection state precisely.

## Decision points
- If the caller is not a lead -> **STOP** before Step 3. Report "sync requires a lead (owner/admin/manager)"; deliver the read-only workbook + connection state.
- If `connected=false` (no Sheets key) -> the sync is a DEGRADE: status flips to `synced` but 0 rows pushed and the buffer is retained. Report "degraded: Sheets not connected, buffer held, 0 rows pushed"; do NOT present it as a live sync.
- If the workbook id is unknown -> the endpoint 404s. Re-resolve from Step 1; do not sync a guessed id.
- If `buffer.queued` is 0 and `connected=true` -> there is nothing new to push; the sync is a no-op refresh. Say so rather than implying fresh data moved.
- If the operator wants EVERY client synced -> route to `/sheets-sync` (POST /reports/sync-all).

## Common Pitfalls
- Reporting rows as landed in Google Sheets when `connected=false` -> forbidden. A degraded flush pushes 0; state that.
- Inventing a `rows` count -> use only the `sync-events` `rows` the push recorded.
- Syncing a workbook id you guessed -> resolve it from `/reports/workbooks` first (a wrong id 404s).
- Treating the optimistic `status=synced` as proof of a real push -> the status flips even when degraded; verify via `connected` + the sync events.
- Composing the monthly client narrative here -> that is `/monthly-report` (opus); this hub just refreshes the workbook.

## Output format
Emit verbatim:

```
REPORT - <client>
Workbook: <id>   Sheet: <sheet fragment>   Tabs: <audit|content|milestones list>
Sheets connection: <connected (account <accountShort>) | NOT connected (degraded)>
Buffer: queued=<queued>  flushedToday=<flushedToday>
Sync result: status=<synced>  rows pushed=<sum from sync-events>  lastSync=<lastSync>
  <per dataset: <dataset> +<rows> (<ago>)>
State: <LIVE push | DEGRADED (buffer held, 0 rows, Sheets key pending)>
Recommended next: <monthly narrative -> /monthly-report | push all clients -> /sheets-sync>
```

Rubric enforced (reference, not inlined): the `GET /reports/types` tab/column map and the audit report-design contract. Shared wiring + the Sheets degrade contract: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
