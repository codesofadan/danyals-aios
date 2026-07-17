---
name: offpage
description: Reads the off-page boards and KPIs (referring-domain / backlink profile, citation / NAP listings, Web 2.0 property ledger) and routes any write to the right guarded feature skill. Use when an operator says "off-page", "link profile / backlinks", "referring domains", "citations / NAP / directory listings", "web 2.0 properties", or "off-page KPIs / new-lost-toxic links". This is the off-page module hub; its spending/publishing/mutating sub-actions live in /backlink-audit, /citation-builder, /web2-build (each LEAD-gated and cost-gated server-side).
argument-hint: "[board] [client]"
arguments: [board, client]
model: opus
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Read the Off-Page Boards and Route the Work

**Purpose.** Give the operator one grounded view of the off-page module - the backlink profile, citation/NAP board, Web 2.0 ledger, and the summary KPIs - and route any action to the correct guarded feature skill. The hub reads; it does not itself flag, submit, or publish.

**Who runs it.** Any provisioned staff (`view_reports`) for the reads; a portal client is 403'd off this namespace. All WRITES (toxic flag, citation actions, web2 plan/approve) are LEAD-only (owner/admin/manager) and are performed by the feature skills, not here.

## Required inputs / keys
- `$board` - optional focus: `backlinks`, `citations`, `web2`, or `kpis` (default: show KPIs + a short read of each board).
- `$client` - optional client filter (`clientId`) to narrow every board.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- No provider key is needed to READ. The backlink/citation data is monitoring data ingested upstream; report it as-is.

**Trigger.** "Off-page / link profile / backlinks / referring domains / citations / NAP / web 2.0 / off-page KPIs" - or a request to act on any of them (which the hub routes).

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the KPIs (GET /offpage/kpis)
- [ ] Step 2: Read the requested board(s) (GET /offpage/backlinks|citations|web2)
- [ ] Step 3: Summarize grounded state; surface the toxic queue + NAP inconsistencies
- [ ] Step 4: Route any write to the guarded feature skill (do NOT mutate here)
```

1. **Read the KPIs.** Run `aios_client.py get /offpage/kpis` -> `{referringDomains, newLinks30d, lostLinks30d, toxicFlagged}`.
2. **Read the board(s).** Per `$board` (add `?clientId=<id>` for `$client`):
   - `aios_client.py get /offpage/backlinks` (add `?status=toxic` for the disavow queue).
   - `aios_client.py get /offpage/citations` (add `?nap=inconsistent` or `?nap=missing`).
   - `aios_client.py get /offpage/web2`.
3. **Summarize grounded state.** Render the **Output format** from the real rows only: referring-domain size, new/lost/toxic, NAP consistency counts, and the web2 ledger (draft / needs_review / published mix).
4. **Route the write.** If the operator wants to act, hand off - do NOT call a mutation from the hub:
   - Flag toxic backlinks / disavow review -> `/backlink-audit` (LEAD).
   - Submit/Update/bulk-reconcile citations -> `/citation-builder` (LEAD for bulk).
   - Plan / approve a Web 2.0 property -> `/web2-build` (LEAD; publishes; cost-gated).

## Decision points
- If the caller lacks `view_reports` -> every read 403s -> report "requires staff (view_reports)", STOP.
- If the operator asks to flag/submit/publish -> route to the feature skill; state it is LEAD-only and (for web2) cost-gated + human-gated. The hub never performs the write itself.
- If `toxicFlagged > 0` -> surface the disavow-review queue size and point to `/backlink-audit`; do not auto-flag more.
- If citations show `inconsistent`/`missing` -> surface the counts and point to `/citation-builder`; NAP fixes are a LEAD action.
- If a board is empty -> report "no rows" (grounded); do not infer a profile that is not there.

## Common Pitfalls
- Flagging toxic links or submitting a citation directly from the hub -> forbidden; the hub is read-only, writes go through the LEAD-gated feature skills.
- Reporting a DA/DR or "spam score" the row does not carry -> grounding rule: only the `authority`/`spam` values in the row.
- Presenting the toxic queue as "already disavowed" -> `toxic` means queued for a disavow review, not submitted to Google.
- Reading `verified=pending` web2 rows as live/verified placements -> pending is not verified.

## Output format
Emit verbatim:

```
OFF-PAGE - <client or "all clients">
KPIs: referring domains <n> · new(30d) <n> · lost(30d) <n> · toxic queue <n>
Backlinks: <n rows shown>  (toxic/disavow queue: <n>)
  top by authority: <refDomain> a:<authority> s:<spam> [<status>]  (up to 3, grounded)
Citations (NAP): consistent <n> · inconsistent <n> · missing <n>
Web 2.0 ledger: draft <n> · needs_review <n> · published <n>   verified <n>/pending <n>
Route the work:
  toxic backlinks / disavow -> /backlink-audit (LEAD)
  citations / NAP fixes     -> /citation-builder (LEAD for bulk)
  web 2.0 build / approve    -> /web2-build (LEAD; publishes; cost-gated)
```

Rubric enforced (reference, not inlined): `danyals-audit-system/checklists/off-page.yaml` (OFF-* checks) + the Team C SOPs `danyals-audit-system/.claude/agents/offpage/c1..c4*.md`; citation/NAP rubric in `local.yaml` (D2). Shared depth in `${CLAUDE_PLUGIN_ROOT}/reference/`.
