---
name: policy-brief
description: Turns a policy change-event or an open recommendation into a client-facing advisory (what changed, who is exposed via the audit overlay, the recommended action) and, on a lead's explicit confirm, applies the recommendation so the change is laid on top of the untouched audit engine. Use when the operator says "brief me on this update", "client impact of the core update", "write the advisory for this policy change", "apply this recommendation", or "close the loop on a policy rec". Applying changes live client guidance (writes an audit_overlay row) and is a lead-only, human-confirmed action, so this skill is manual-invocation only.
argument-hint: "[change-or-rec-id]"
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Write a Policy Brief and Close the Loop

**Purpose.** Produce a grounded, client-facing advisory for a single policy change or recommendation - what changed, who is exposed, the recommended action - and, when a lead confirms, `apply` the recommendation so it becomes an `audit_overlay` the presentation layer lays ON TOP of the untouched engine. The advisory is composed from real KB/change/overlay rows; the apply is the closed loop. Nothing about the audit engine is mutated.

**Who runs it.** Reading the change/KB/overlay/recommendations needs `view_reports` (any staff). The `apply` write (`POST /policy/recommendations/{id}/apply`) requires a LEAD (owner/admin/manager) - the `require_role` on that route IS the human-confirm boundary; a non-lead is 403'd. A portal client is 403'd off the namespace entirely.

## Required inputs / keys
- `$ARGUMENTS[0]` - the recommendation id (or the backing change-event id) to brief on. If only a topic is given, resolve it against the queue in Step 1.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer). The token's role decides read vs. `apply`.
- The shared client `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py`; shared wiring in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
- No provider key is spent by `apply` - the overlay is deterministic (title/guidance/weight from the materialized rec), not a metered AI call. Server-side the transition still records an activity entry and is RLS-gated. If the change-detection watcher has not run, the KB/changes may be empty; brief only on what the recommendation carries and say so.

**Trigger.** A request to explain the client impact of a specific policy/algorithm update, draft the advisory, or apply/close-the-loop on a recommendation.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the target rec + its backing change (GET /policy/recommendations, /policy/changes)
- [ ] Step 2: Pull the KB entry + any active overlay for grounding (GET /policy/kb, /policy/overlay)
- [ ] Step 3: Compose the client-facing advisory from real rows (no invented impact)
- [ ] Step 4: Present it + the exposure; STOP for the lead's explicit apply confirm
- [ ] Step 5: On confirm only, apply the rec (POST /policy/recommendations/{id}/apply); re-read the overlay
```

1. **Resolve the recommendation.**
   Run `aios_client.py get /policy/recommendations` and select the rec matching `$ARGUMENTS[0]` (id or topic). Capture `id`, `title`, `why`, `action`, `scope`, `target`, `region`, `status`, `clients`, `kbId`. Run `aios_client.py get /policy/changes` to find the backing change (`summary`, `severity`, `sourceName`, `detected`).

2. **Ground it in the KB + overlay.**
   Run `aios_client.py get /policy/kb` (optionally `--query category=...`) for the authoritative entry (`summary`, `severity`, `category`, `sourceName`, `sourceUrl`, `version`). Run `aios_client.py get /policy/overlay --query target=<target>` to see if guidance is already applied (`guidance`, `weight`, `active`, `version`).

3. **Compose the advisory.** Write the brief from those rows only. State what changed (KB/change summary), who is exposed (the rec's `clients`/`scope` + the overlay `target`/`auditType`), and the recommended `action`. Use plain client-facing prose: no em/en dashes, no softening adverbs, no fabricated metrics or DA/traffic numbers.

4. **Present and pause.** Emit the **Output format**. If the operator wants to publish/close the loop, restate the exact rec + that `apply` changes live guidance, and require a lead's explicit yes.

5. **Apply on confirm only.** Run `aios_client.py post /policy/recommendations/{id}/apply`. This materializes the rec (if baseline) and writes the overlay. Re-read `aios_client.py get /policy/overlay` to confirm the new `active` row and report its `version`/`weight`.

## Decision points
- If the caller is not a lead -> **STOP** before Step 5. Report "apply requires a lead (owner/admin/manager)"; deliver the advisory read-only. Do not attempt the POST.
- If no explicit apply confirm is given -> deliver the advisory only; do NOT apply. `apply` is never implicit.
- If the KB/change rows are empty (watcher not live) -> brief strictly on the recommendation's own `why`/`action`; label it "baseline guidance, no live source yet". Never invent the source or the severity.
- If an active overlay already exists for this target/region -> say the loop is already closed at `version=N`; re-applying bumps the version. Confirm the operator intends a new version before re-applying.
- If the rec's `clients` is empty -> frame the advisory as global guidance ("applies to all clients"), not a specific named client.

## Common Pitfalls
- Inventing an impact ("this will drop rankings 20%") -> forbidden. State only the KB/change `summary` + the rec `why`; impact framing stays qualitative and grounded.
- Applying because the advisory reads well -> `apply` changes live client guidance; it waits for a lead's explicit confirm every time.
- Em/en dashes or marketing adverbs in the advisory prose -> the client-facing renderer strips them; write clean declarative sentences.
- Claiming the audit engine was updated -> it is NEVER mutated; `apply` writes a SEPARATE overlay laid on top. Say "overlay applied", not "engine changed".
- Treating a baseline rec's `kb-base-*` id as a real citation -> it is a default; do not attach a fake `sourceUrl`.

## Output format
Emit verbatim:

```
POLICY BRIEF - <rec title>
Status: <new|acknowledged|applied|dismissed>   Scope: <global|client|site>   Target: <audit|content|portal>   Region: <regionLabel>
What changed: <KB/change summary, grounded; or "baseline guidance (no live source yet)">
Source: <sourceName> <sourceUrl or "(none - baseline)">   Severity: <critical|major|minor|info>
Who is exposed: <clients or "all clients">
Recommended action: <action>
Existing overlay: <none | active v<version>, weight <weight> for auditType "<auditType>">
--- CLIENT-FACING ADVISORY ---
<2-4 plain sentences: what changed, why it matters for this client, the action we are taking. No em dashes, no invented numbers.>
-----------------------------
Apply gate (closed loop):
  <lead + confirm -> POST /policy/recommendations/{id}/apply (writes the overlay on top of the untouched engine)>
  <not a lead / no confirm -> advisory delivered read-only; not applied>
Applied result: <n/a | overlay now active v<version>, weight <weight>>
```

Rubric enforced (reference, not inlined): the Policy KB (`GET /policy/kb`) and the affected-check mapping in `danyals-audit-system/checklists/*.yaml`; narrative discipline in `backend/docs/CONTENT-DOCTRINE.md`. Shared wiring + the closed-loop overlay contract: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
