---
name: assign-task
description: Creates and routes a task to a staff member - validating the client and that the assignee is staff (never a portal client), snapshotting the client name, and stamping the priority and due date. Use when the operator says "assign", "delegate", "create a task for", "give this to", or "route this work". Creating and reassigning tasks is a lead-only action (the assign_tasks holders) that mutates the shared board, so this skill is manual-invocation only. Content Sprint tasks carry the human review gate before delivery.
argument-hint: "[member] [client] [task-title]"
arguments: [member, client, task]
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py get *) Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py post *) Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py patch *) Read
---

# Assign and Route a Task

**Purpose.** Create a work item on the team board: point it at a client, assign it to a staff member, set its type/priority/due, and record it. This skill drives only LEGAL board actions (create, reassign); the lifecycle state machine is enforced at the DB, and the Content Sprint review gate is a lead-only sign-off it never auto-approves.

**Who runs it.** Creating (`POST /tasks`) and reassigning (`PATCH /tasks/{code}`) require the `assign_tasks` permission (leads: owner/admin/manager); a non-lead is 403'd. Advancing a task is the assignee-or-lead action (`POST /tasks/{code}/advance`); signing off the review gate (`POST /tasks/{code}/review`) is owner/admin/manager only. A portal client can neither be an assignee nor reach this namespace.

## Required inputs / keys
- `$member` - the staff member to assign to (resolved to a user id; MUST be staff, never a client).
- `$client` - the client the work is for (resolved to a client id; snapshotted server-side).
- `$task` - the task title.
- Also: `type` (one of Technical Audit, Actionable Audit, Content Sprint, Backlink Audit, Local SEO, Publishing), `priority` (`urgent`|`high`|`med`|`low`, default `med`), optional `due` (`YYYY-MM-DD`).
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer; lead for create/reassign).
- The shared client `${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py` (the plugin's `../../scripts/aios_client.py`); shared wiring in `../../reference/`.
- No metered spend to create a task. The board lifecycle + the review gate are enforced by the `tasks_guard_update` DB trigger, not this skill.

**Trigger.** A request to assign, delegate, create, or route a task to a team member.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client + confirm the assignee is staff (GET /clients, GET /tasks or member lookup)
- [ ] Step 2: Confirm the exact task (member, client, type, priority, due) with the operator
- [ ] Step 3: Create the task (POST /tasks) - lead-only
- [ ] Step 4: Confirm it landed (GET /tasks?assignee=<id>); note the review gate for Content Sprint
- [ ] Step 5: Render the pinned output
```

1. **Resolve + validate.**
   Run `aios_client.py get /clients` to resolve `$client` to a client id (an unknown client 404s on create). Confirm `$member` is a staff user - the endpoint rejects a missing assignee (404) and a portal-client assignee (400); never point a task at a client uid.

2. **Confirm the task.** Restate member + client + `type` + `priority` + `due`. Require the operator's explicit yes (this writes to the shared board). Content Sprint tasks route through the review gate before `done` - note that.

3. **Create (lead-only).**
   Run `aios_client.py post /tasks --json '{"title":"$task","client_id":"<id>","type":"<type>","assignee_id":"<uid>","priority":"<priority>","due":"<YYYY-MM-DD or omit>"}'`. Capture the returned `id` (the public `J-####` code).

4. **Confirm.** Run `aios_client.py get /tasks --query assignee=<uid>` and verify the new `J-####` is present at `status=todo`.

5. **Render** the **Output format**.

## Decision points
- If the caller lacks `assign_tasks` (not a lead) -> **STOP.** Report "assigning tasks requires a lead (the assign_tasks holders: owner/admin/manager)"; do not attempt the POST.
- If `$member` is a portal client (or missing) -> **STOP.** The endpoint rejects a client assignee (400) / missing (404); a task is never pointed at a client. Ask for a staff assignee.
- If `$client` does not resolve -> report "client not found"; do not create against a guessed id.
- If asked to skip the Content Sprint review gate or self-approve it -> refuse. Review is a lead-only sign-off via `POST /tasks/{code}/review`; a non-lead cannot skip it even by a direct PATCH (the DB trigger enforces it). Route it to a lead.
- If asked to reassign/repriority an existing task -> use `aios_client.py patch /tasks/{code}` (lead-only); status is NEVER patched (it moves only via `/advance` and `/review`).
- If asked to force an illegal status jump -> refuse; the DB trigger rejects it. Advance one legal step at a time via `/advance`.

## Common Pitfalls
- Assigning to a portal client -> forbidden and rejected server-side; assignees are staff only.
- Patching `status` to move a task -> status is not patchable; use `/advance` (assignee-or-lead) or `/review` (lead sign-off).
- Auto-approving a Content Sprint at the review gate because the work "looks done" -> the review sign-off is a deliberate lead action; this skill never approves it.
- Creating against a client name you did not resolve -> resolve to a client id first (a wrong id 404s).
- Inventing a due date -> omit `due` if none was given; the board shows no due rather than a guess.

## Output format
Emit verbatim:

```
TASK ASSIGNED
Task: <J-####>  "<title>"
Client: <client name>   Assignee: <member> (<uid>)
Type: <type>   Priority: <priority>   Due: <due or "none">   Status: todo
Review gate: <Content Sprint -> routes through a lead sign-off before done | delivers straight to done>
Confirm: created by a lead (assign_tasks); assignee validated as staff.
Next: assignee advances via /advance; <lead signs off via /review for Content Sprint>
```

Rubric enforced (reference, not inlined): the task state machine (backend invariant, Part 5 - the `tasks_guard_update` trigger owns the lifecycle; the review gate is lead-only). Shared wiring + roles: `../../reference/`.
