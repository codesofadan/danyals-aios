---
name: milestones
description: Reads the client project milestones (the five-stage delivery timeline per engagement) and the recently-auto-advanced feed, and surfaces stalled or blocked projects. Use when the operator says "milestones", "project status", "delivery timeline", "roadmap", "which projects are stalled", or "what advanced recently". Read-only; stages are auto-advanced from delivery events, never edited by hand here.
argument-hint: "[client]"
model: sonnet
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Read Client Milestones

**Purpose.** Show where each client engagement sits on its five-stage delivery timeline (onboarding, baseline audit, content sprint, off-page/authority, reporting), what advanced recently, and which projects are blocked or at risk. Read-only: stages advance automatically from real delivery events; this skill reports them, it does not edit them.

**Who runs it.** Any provisioned staff (holds `view_reports`). A portal client is 403'd off this namespace.

## Required inputs / keys
- `$ARGUMENTS[0]` (optional) - a client name to filter to a single project. Omitted, report the whole board.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer, any staff).
- The shared client `${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py`; shared wiring in `${CLAUDE_PLUGIN_ROOT}/reference/`.
- No provider key required. This is a pure read.

**Trigger.** A request about project status, the delivery timeline/roadmap, stalled projects, or recent auto-advances.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the projects + their stage timelines (GET /milestones)
- [ ] Step 2: Read the recent auto-advance feed (GET /milestones/auto-advance)
- [ ] Step 3: Compute derived progress per project from stage weights
- [ ] Step 4: Flag blocked/at-risk projects; render the pinned board
```

1. **Read the projects.**
   Run `aios_client.py get /milestones` (filter to `$ARGUMENTS[0]` in-memory if given). Each project carries `client`, `site`, `health` (`on_track` | `at_risk` | `completed`), and its five ordered `stages` (`key`, `status`, `auto_source`, `updated_at`).

2. **Read the auto-advance feed.**
   Run `aios_client.py get /milestones/auto-advance`. Each entry: `client`, `milestone`, `trigger` (the delivery event that advanced it), `ago`, and `flag` (true = a block/at-risk flag rather than a forward advance).

3. **Derive progress.** Per project, progress % = average of the per-stage weights (completed 1.0, in_progress 0.5, blocked 0.25, upcoming 0.0), rounded - the milestone stage-model formula. This is derived from real `status` values, not invented.

4. **Flag and render.** Mark any project with a `blocked` stage or `health=at_risk` as needing attention. Emit the **Output format**.

## Decision points
- If a project has a `blocked` stage -> surface it first with its `auto_source` (why it blocked); recommend the operator investigate. Do not guess the fix.
- If `health=at_risk` -> flag it even if no stage is `blocked`; state which stage is current.
- If `$ARGUMENTS[0]` matches no project -> report "no project on file for that client"; route to a human, do not fabricate a timeline.
- If the auto-advance feed is empty -> report "no recent auto-advances"; an empty feed is a real state, not a reason to invent activity.
- If asked to advance/edit a stage -> not supported here; stages advance only from backend delivery events. Route the underlying work (e.g. a content sprint) to `/assign-task` or the relevant module.

## Common Pitfalls
- Inventing a progress % or a due date -> use only the stage-weight formula over real `status` values; the API exposes no manual due date here.
- Reading `updated_at`'s em-dash (an un-advanced `upcoming` stage) as a date -> it means "not yet reached", report it as upcoming.
- Treating a `flag=true` auto-advance entry as forward progress -> it marks a block/at-risk event; report it as a flag.
- Trying to edit a stage -> there is no manual stage-edit endpoint; stages are auto-advanced.

## Output format
Emit verbatim:

```
MILESTONES - <all projects | client filter>
Needs attention:
  <client> (<site>) - health=<at_risk|...>  current stage=<stage> [blocked: <auto_source>]
  ...  (or "none")
Board:
  <client> (<site>)  health=<on_track|at_risk|completed>  progress=<n>% (derived)
    onboarding=<status>  baseline=<status>  content=<status>  authority=<status>  reporting=<status>
    current stage: <stage>  (last advance: <trigger>, <ago>)
  ...
Recent auto-advances:
  <client>: <milestone> <- <trigger>  (<ago>) <FLAG if blocked/at-risk>
  ...  (or "no recent auto-advances")
```

Rubric enforced (reference, not inlined): the milestone stage model (the five-stage lifecycle + stage weights). Shared wiring: `${CLAUDE_PLUGIN_ROOT}/reference/`.
