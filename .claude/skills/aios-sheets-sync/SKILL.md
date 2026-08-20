---
name: sheets-sync
description: Mechanically pushes every client report workbook to its Google Sheet in one pass (POST /reports/sync-all), then confirms the pushes via the sync-event feed and reports the connection state. Use when the operator says "sync all sheets", "push all reports to Google Sheets", "flush the sheets buffer", or "sync everything". This is a lead-only external write to Google Sheets and is manual-invocation only. To sync a single client use /report.
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Sync All Report Workbooks to Google Sheets

**Purpose.** Push every client workbook to its Google Sheet in one batched pass and confirm what actually landed. This is the mechanical bulk-sync: it flushes each workbook's Redis write-buffer through the SheetStore and records a sync event per dataset. It reports only rows a real push wrote; a degraded (keyless) flush is reported as 0.

**Who runs it.** `POST /reports/sync-all` requires a LEAD (owner/admin/manager) - the RLS insert/update set; a non-lead is 403'd. Reading the connection/sync feed needs `view_reports`. A portal client is 403'd off the namespace.

## Required inputs / keys
- No positional input - this pushes ALL workbooks (bounded to 500 per pass server-side).
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer, lead role for the sync).
- The shared client `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py`; shared wiring in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
- The Google Sheets credential must be live for a REAL push. Dormant -> `GET /reports/connection` `connected=false`; every workbook flips to `synced` optimistically but the buffers are retained and each sync event records 0 rows. Report the degrade; do not claim rows reached Sheets when `connected=false`.

**Trigger.** A request to sync/flush/push ALL report workbooks to Google Sheets at once.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the connection panel (GET /reports/connection) - is Sheets live?
- [ ] Step 2: Read the pre-sync buffer state (connection.buffer.queued)
- [ ] Step 3: Sync every workbook (POST /reports/sync-all) - lead-only
- [ ] Step 4: Confirm via the sync feed (GET /reports/sync-events)
- [ ] Step 5: Render the pinned summary with the honest live/degraded state
```

1. **Read the connection.**
   Run `aios_client.py get /reports/connection`. Read `connected`, `accountShort`, `buffer.queued`, `buffer.flushedToday`. This determines whether the pass is a real push or a degraded no-op.

2. **Note the queued buffer** so you can report what was pending before the push.

3. **Sync all (lead-only).**
   Run `aios_client.py post /reports/sync-all`. The response is the list of updated workbooks (each `client`, `status`, `rows`, `lastSync`).

4. **Confirm the pushes.**
   Run `aios_client.py get /reports/sync-events`. Sum the `rows` across the newest events per `client`/`dataset` - that is what actually landed.

5. **Render** the **Output format** with the precise connected/degraded label.

## Decision points
- If the caller is not a lead -> **STOP** before Step 3. Report "sync-all requires a lead (owner/admin/manager)"; deliver the read-only connection state.
- If `connected=false` (no Sheets key) -> the whole pass DEGRADES: every workbook flips to `synced` but 0 rows push and buffers are retained. Report "degraded: Sheets not connected, N buffers held, 0 rows pushed"; do NOT present it as a live bulk sync.
- If `buffer.queued` was 0 and `connected=true` -> nothing new to push; report a clean no-op rather than implying data moved.
- If the operator wants ONE client -> route to `/report` (POST /reports/sync with a `workbookId`) instead of the bulk pass.

## Common Pitfalls
- Reporting a total row count from the optimistic workbook `status` -> use the `sync-events` `rows`, which count only real pushes; degraded flushes are 0.
- Presenting a keyless run as "all clients synced to Sheets" -> it is degraded; buffers are held and nothing left the box.
- Re-running the pass to "force" rows when `connected=false` -> it will keep pushing 0; the fix is the Sheets credential, not a retry. Surface the key gap.
- Spamming per-workbook confirmations -> the backend records ONE aggregate activity entry; summarize per client, do not narrate each.

## Output format
Emit verbatim:

```
SHEETS SYNC-ALL
Connection: <connected (account <accountShort>) | NOT connected (degraded)>
Buffer before: queued=<queued>   flushedToday=<flushedToday>
Workbooks pushed: <count>
  <client> -> +<rows> rows (<datasets>)   status=<synced>
  ...
Total rows landed: <sum from sync-events, 0 if degraded>
State: <LIVE bulk push | DEGRADED (buffers held, 0 rows, Sheets key pending)>
Single-client sync instead: /report
```

Rubric enforced (reference, not inlined): the `GET /reports/types` tab/column map. Shared wiring + the Sheets degrade contract: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
