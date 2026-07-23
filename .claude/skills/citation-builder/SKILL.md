---
name: citation-builder
description: Works the citation / NAP board - reads directory listings by NAP status and, on a LEAD's go, marks a missing listing Submitted or a drifted listing Updated (single or bulk), resolving each to consistent. Use when an operator says "citations", "NAP consistency", "directory listings", "submit a citation", "fix / reconcile NAP", or "bulk-update citations". Marking listings consistent is a LEAD-only write that mutates shared state; a bulk pass touches many rows at once.
argument-hint: "[client] [nap-status]"
arguments: [client, nap_status]
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Build and Reconcile Citations (NAP)

**Purpose.** Read the citation board, identify the listings that need work (missing -> Submit, inconsistent -> Update), and on a LEAD's confirmation mark them `consistent` one at a time or in a batch. The endpoint owns the NAP state transition; this skill drives the legal call and keeps the action verb coherent with the NAP status.

**Who runs it.** Reading the board needs `view_reports`. Every write (`.../action`, `.../bulk`) is LEAD-only (owner/admin/manager). A non-lead write 403s - report "requires a LEAD", STOP.

## Required inputs / keys
- `$client` - optional client filter (`clientId`) to scope the board.
- `$nap_status` - optional filter: `missing`, `inconsistent`, or `consistent`. Work the `missing` and `inconsistent` rows.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- The canonical NAP (name, address, phone) the operator is reconciling TO must come from the client's real record - it is not stored in this endpoint. If it is unknown, that is a `[NEEDS:]` for a human; do not invent it.

**Trigger.** "Citations / NAP / directory listings / submit a citation / reconcile NAP / bulk-update citations".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the board (GET /offpage/citations, filter by nap/clientId)
- [ ] Step 2: Bucket into Submit (missing) vs Update (inconsistent); confirm canonical NAP
- [ ] Step 3: STOP - present the proposed changes; a LEAD confirms
- [ ] Step 4a: Single -> POST /offpage/citations/{id}/action {action, note}
- [ ] Step 4b: Bulk -> POST /offpage/citations/bulk {ids}
- [ ] Step 5: Re-read the board; render output
```

1. **Read the board.** Run `aios_client.py get /offpage/citations` (add `?nap=missing`/`?nap=inconsistent`, `?clientId=<id>`). Each row: `directory`, `nap`, `action`, `note`.
2. **Bucket the work.** `missing` -> `Submit` (create the listing); anything else needing a fix -> `Update`. Confirm the canonical NAP the operator is reconciling to is known and correct.
3. **STOP for the LEAD.** Present the exact rows and the Submit/Update intent. Do NOT write without an explicit LEAD confirmation; a bulk pass mutates many rows.
4. **Apply the change on confirmation.**
   - Single: `aios_client.py post /offpage/citations/{id}/action --json '{"action":"Submit|Update","note":"<detail>"}'` -> resolves that row to `consistent`.
   - Bulk: `aios_client.py post /offpage/citations/bulk --json '{"ids":["<id>",...]}'` -> resolves each visible row to `consistent`. Only rows RLS lets the caller see are touched.
5. **Confirm and render.** Re-read the board and render the **Output format** from the real updated rows.

## Decision points
- If the caller is not a LEAD -> the write 403s -> report "requires a LEAD", STOP after the read-only view.
- If the operator has not confirmed -> STOP at step 3; never write on your own.
- If the canonical NAP is unknown / `[NEEDS: NAP]` -> STOP; route to a human to supply it. NEVER invent a name/address/phone - a wrong NAP submitted to a directory is worse than a flagged gap (LOC-013/LOC-020).
- If a bulk id is not visible to the caller -> it is silently excluded by RLS; report the actual affected count, not the requested count.
- If a single-action row 404s -> the citation id is unknown/invisible; surface it, do not retry with a guessed id.
- If a row is already `consistent` -> no action needed; do not re-submit (idempotent, but noise).

## Common Pitfalls
- Submitting a listing with a NAP guessed from memory -> forbidden; the canonical NAP must come from the client record. Route the `[NEEDS:]` to a human.
- Bulk-marking everything `consistent` to clear the board -> only mark rows the operator actually submitted/updated; a false "consistent" hides real drift.
- Using `Submit` for a drifted (not missing) listing -> `missing` -> Submit, everything else -> Update; keep the verb coherent with the NAP status.
- Reporting the requested id count as the affected count after a bulk -> RLS may exclude some; report the returned rows.
- Treating "marked consistent" as "the directory is fixed" -> the status reflects the operator's submit/update action; the live directory update happens out-of-band.

## Output format
Emit verbatim:

```
CITATION BUILDER - <client or "all clients">
Board (grounded): consistent <n> · inconsistent <n> · missing <n>
Proposed: Submit <n missing> · Update <n inconsistent>
Canonical NAP source: <"confirmed from client record" | "[NEEDS: NAP] -> human">
Action taken: <"none - awaiting LEAD" | "single: <directory> -> consistent" | "bulk: <k>/<requested> -> consistent">
Rows now consistent:
  <directory> - <Submit|Update> - note:"<note>"   (up to 8, grounded)
Excluded by RLS (bulk): <n or "none">
Next: <supply canonical NAP | continue Update pass | re-monitor drift>
```

Rubric enforced (reference, not inlined): `danyals-audit-system/checklists/local.yaml` and the Team D SOP `danyals-audit-system/.claude/agents/local/d2-citations-nap.md` (LOC-011..020: citation audit, consistency, NAP exactness, aggregators). Shared depth in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
