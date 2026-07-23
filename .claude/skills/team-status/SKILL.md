---
name: team-status
description: Reads the team's live workload - the caller's own record and real performance metrics, the task queue (mine or a named member's), and the Command Center team feed - so an operator sees who is working on what. Use when the operator says "team status", "my tasks", "who is working on what", "my queue", "workload", or "how is the team doing". Read-only; assigning work is a separate action in /assign-task.
argument-hint: "[member]"
model: sonnet
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Read Team Status

**Purpose.** Show the live team workload: the caller's own record with real performance metrics, the task queue (theirs or a named member's), and the platform team-tracking feed. Read-only. Every number is a live ledger read; this skill assigns nothing.

**Who runs it.** Any provisioned staff (holds `view_reports`). `GET /me` returns the caller's own record; `GET /tasks` is staff-wide with `mine`/`assignee` scoping; `GET /command-center` is the staff aggregate. A portal client is 403'd off this namespace.

## Required inputs / keys
- `$ARGUMENTS[0]` (optional) - a member id to scope the queue to that person; omitted, scope to the caller (`mine=true`).
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer, any staff).
- The shared client `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py`; shared wiring in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
- No provider key required. Pure read.

**Trigger.** A request about team status, my/a member's task queue, workload, or who is working on what.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the caller's own record + live metrics (GET /me)
- [ ] Step 2: Read the task queue (GET /tasks?mine=true or ?assignee=<id>)
- [ ] Step 3: Read the Command Center team feed (GET /command-center)
- [ ] Step 4: Render the pinned status
```

1. **Read the caller.**
   Run `aios_client.py get /me`. Capture `name`, `role`, `activeTasks`, `completed`, `onTime`, `utilization`, `quality`. These are live: `activeTasks`/`completed` from the tasks ledger, and `onTime`/`utilization`/`quality` computed by the team-metrics service.

2. **Read the queue.**
   Run `aios_client.py get /tasks --query mine=true` (or `--query assignee=$ARGUMENTS[0]` for a named member). Capture per task: `id` (the J-#### code), `title`, `client`, `type`, `priority`, `status`, `due`.

3. **Read the team feed.**
   Run `aios_client.py get /command-center`. Pull `team` (per-member job counts) for the whole-team picture.

4. **Render** the **Output format**, ordering the queue by `priority` then `status`.

## Decision points
- If `$ARGUMENTS[0]` names a member with no tasks -> report "no active tasks for that member"; an empty queue is a real state, not a reason to invent one.
- If a task sits in `review` -> flag it: it is at the content review gate and needs a lead's sign-off (route to `/assign-task`'s review path or a lead).
- If a task's `due` is empty -> report "no due date"; the API exposes none rather than a guessed date.
- If the operator wants to assign/reassign/route work -> route to `/assign-task`; this skill is read-only.
- If metrics read 0 across the board for a new member -> report the zeros honestly (a fresh member has no history yet).

## Common Pitfalls
- Inventing `onTime`/`utilization`/`quality` -> use only the `GET /me` values; they are computed server-side from real ledgers.
- Guessing another member's full metrics -> `GET /me` returns only the caller's; for others, report their task queue (`?assignee=`) and their `team` job count, not fabricated percentages.
- Reading a `review` task as done -> it is awaiting sign-off; it is not delivered until a lead approves.
- Assigning or advancing a task from here -> read-only; route mutations to `/assign-task`.

## Output format
Emit verbatim:

```
TEAM STATUS - <caller name> (<role>)
My metrics: active=<activeTasks>  completed=<completed>  onTime=<onTime>%  utilization=<utilization>%  quality=<quality>%
Queue (<mine | member <id>>): <count> tasks
  <J-####>  <title>  [<priority>]  <status>  client=<client>  type=<type>  due=<due or "none">
  ...  (or "no active tasks")
At the review gate: <list J-#### in review, or "none">  -> needs a lead sign-off
Team load (from command-center):
  <member> - <jobs> jobs
  ...
Next: <assign/route work -> /assign-task>
```

Rubric enforced (reference, not inlined): the task lifecycle (Part 5 - `todo -> in_progress -> [review] -> done`, review gate is lead-only). Shared wiring: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
