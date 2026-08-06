---
name: citation-builder
description: Works the citation / NAP board - reads directory listings by NAP status and the prioritized citation AUDIT PLAN (Generic -> Country -> Niche, each directory built|missing), and on a LEAD's go marks a missing listing Submitted or a drifted listing Updated (single or bulk), resolving each to consistent. Use when an operator says "citations", "NAP consistency", "directory listings", "audit plan", "which directories are missing / built", "citation gap", "geo / niche citations", "submit a citation", "fix / reconcile NAP", or "bulk-update citations". Reading the board and the audit plan needs view_reports; marking listings consistent is a LEAD-only write that mutates shared state; a bulk pass touches many rows at once.
argument-hint: "[client] [nap-status]"
arguments: [client, nap_status]
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Build and Reconcile Citations (NAP)

**Purpose.** Read the citation board and the prioritized audit plan, identify the listings that need work (missing -> Submit, inconsistent -> Update), and on a LEAD's confirmation mark them `consistent` one at a time or in a batch. The endpoint owns the NAP state transition; this skill drives the legal call and keeps the action verb coherent with the NAP status. The audit-plan read is a standalone, read-only view - no write, no spend.

**Who runs it.** Reading the board and the audit plan needs `view_reports`. Every write (`.../action`, `.../bulk`) is LEAD-only (owner/admin/manager). A non-lead write 403s - report "requires a LEAD", STOP. An unknown/invisible client on the audit plan 404s.

## Required inputs / keys
- `$client` - optional client filter (`clientId`) to scope the board. For the audit plan the resolved `client_id` is REQUIRED (it is a per-client path param).
- `$nap_status` - optional filter: `missing`, `inconsistent`, or `consistent`. Work the `missing` and `inconsistent` rows.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- The canonical NAP (name, address, phone) the operator is reconciling TO must come from the client's real record - it is not stored in this endpoint. If it is unknown, that is a `[NEEDS:]` for a human; do not invent it.
- The business profile (the canonical NAP location) now accepts the EXPANDED directory-form fields on create/update - `description`, `email`, `logoUrl`, `facebookUrl` / `instagramUrl` / `linkedinUrl` (socials), `yearFounded`, `paymentTypes`, `tagline`, `serviceArea` - alongside the core NAP. A richer profile fills more directory forms cleanly. These are set via `POST /citation-builder/business-profiles` (create) and `PATCH /citation-builder/business-profiles/{id}` (update), both LEAD-only; supply only real values, never invented ones.

**Trigger.** "Citations / NAP / directory listings / audit plan / which directories are missing / citation gap / submit a citation / reconcile NAP / bulk-update citations".

## Read the audit plan (read-only)
When the operator wants the prioritized "what to build next" view for a client, do this before (or instead of) the reconcile flow:

1. **Resolve the client id.** Match `$client` to a real `client_id` from the client record; never invent one.
2. **Read the plan.** Run `aios_client.py get /citation-builder/clients/{id}/audit-plan`. It returns `client`, `resolvedVertical`, `market`, and three build-ordered buckets: `generic` (GLOBAL core/aggregators/APIs every market builds first), `country` (the client's own-market US/UK/CA/AU general directories), `niche` (vertical-specific directories). Each item: `directoryName`, `market`, `tier`, `url`, `status` (`built` | `missing`).
3. **Render the AUDIT PLAN output.** Priority is Generic -> Country -> Niche; within each bucket keep the returned build order. Do NOT re-rank; the endpoint reuses the same selection + gap logic a campaign uses. `built` = a covering citation already exists; `missing` = a build target. When the client has no citations yet, every item reads `missing`.
4. **Hand off to the build.** A `missing` directory is a Submit candidate; route it into the reconcile flow below (or a real submission via `/citation-submit`). Never mark a plan item "built" from here - the plan derives status from the actual citation records.

## Steps (reconcile flow)
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
5. **Confirm and render.** Re-read the board and render the **Board output** from the real updated rows.

## Decision points
- If the operator wants the "what to build" view -> run the audit-plan read; it is read-only (no LEAD, no spend). An unknown/invisible client -> 404; surface it, do not guess an id.
- If the caller is not a LEAD -> the write 403s -> report "requires a LEAD", STOP after the read-only view.
- If the operator has not confirmed -> STOP at step 3; never write on your own.
- If the canonical NAP is unknown / `[NEEDS: NAP]` -> STOP; route to a human to supply it. NEVER invent a name/address/phone - a wrong NAP submitted to a directory is worse than a flagged gap (LOC-013/LOC-020).
- If a bulk id is not visible to the caller -> it is silently excluded by RLS; report the actual affected count, not the requested count.
- If a single-action row 404s -> the citation id is unknown/invisible; surface it, do not retry with a guessed id.
- If a row is already `consistent` -> no action needed; do not re-submit (idempotent, but noise).

## Common Pitfalls
- Re-ranking the audit plan by your own priority -> forbidden; the endpoint already prioritizes Generic -> Country -> Niche and derives built|missing from real records. Render it as returned.
- Marking a plan item "built" from this skill -> the plan reflects the actual citation records; you build by submitting, not by editing the plan.
- Submitting a listing with a NAP guessed from memory -> forbidden; the canonical NAP must come from the client record. Route the `[NEEDS:]` to a human.
- Inventing the expanded profile fields (description, socials, tagline, serviceArea) to "complete" a directory form -> forbidden; supply only real values or leave them empty.
- Bulk-marking everything `consistent` to clear the board -> only mark rows the operator actually submitted/updated; a false "consistent" hides real drift.
- Using `Submit` for a drifted (not missing) listing -> `missing` -> Submit, everything else -> Update; keep the verb coherent with the NAP status.
- Reporting the requested id count as the affected count after a bulk -> RLS may exclude some; report the returned rows.
- Treating "marked consistent" as "the directory is fixed" -> the status reflects the operator's submit/update action; the live directory update happens out-of-band.

## Audit plan output
Emit verbatim (read-only view):

```
CITATION AUDIT PLAN - <client>
Vertical: <resolvedVertical or "generic">   Market: <US|UK|CA|AU|GLOBAL>
Priority: Generic -> Country -> Niche
Generic (<built>/<total>):
  <directoryName> [<tier>] <built|missing> - <url>   (up to 8, in build order)
Country (<built>/<total>):
  <directoryName> [<tier>] <built|missing> - <url>   (up to 8)
Niche (<built>/<total>):
  <directoryName> [<tier>] <built|missing> - <url>   (up to 8)
Next: <submit the top missing Generic listings first -> reconcile flow or /citation-submit>
```

## Board output
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
