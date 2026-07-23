---
name: policy-radar
description: Reads the Policy Radar brain (watched sources, detected change-events, the KB, and the open recommendation queue) plus the Command Center digest, and returns a prioritized read on what an operator should act on. Use when the operator says "policy", "algorithm update", "Google guideline change", "core update", "what recommendations are open", "policy radar", or asks what changed and who is exposed. Reads are staff-wide; acknowledging or dismissing a recommendation is a lead-only status write that this skill runs only after an explicit operator confirm. Applying a recommendation (the audit-overlay closed loop) is routed to /policy-brief.
argument-hint: "[rec-status]"
model: opus
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Read the Policy Radar

**Purpose.** Give the operator one grounded read of the Policy Radar: which change-events fired, which recommendations are open (awaiting a lead's decision), and what the Command Center is surfacing first. This is the module hub. It reads the real queue and, on explicit confirm, drives the low-stakes `acknowledge` / `dismiss` transitions. It never fabricates a policy update and never invents an impact.

**Who runs it.** Any provisioned staff (holds `view_reports`) may read every Policy Radar surface. Driving a recommendation (`acknowledge` / `apply` / `dismiss`, `POST /policy/recommendations/{id}/{action}`) requires a LEAD (owner/admin/manager); a non-lead read is fine but the transition endpoint returns 403 for them. A portal client holds no staff permission and is 403'd off this whole namespace.

## Required inputs / keys
- `$ARGUMENTS[0]` (optional) - a recommendation `status` filter (`new` | `acknowledged` | `applied` | `dismissed`). Omitted, the queue merges the DB rows with the evergreen baseline recs so the digest is never empty pre-live.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer). The token's role decides read (any staff) vs. transition (lead).
- The shared client `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py`; shared platform wiring (roles, degrade contract) is in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
- No provider key is required to READ the radar. The change-detection WATCHER that fills sources/changes/KB is a deferred backend chunk: until it runs, `lastChecked` reads "never" and sources/changes/KB may be empty. The recommendation queue still serves the baseline recs. Report this state honestly; do not present an empty watcher as "no policy risk".

**Trigger.** Any request about a policy/algorithm/guideline change, an open-recommendation review, or "what should we act on in the radar".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the open recommendation queue (GET /policy/recommendations)
- [ ] Step 2: Read the Command Center digest + spend (GET /command-center)
- [ ] Step 3: Read the change-events + source status for context (GET /policy/changes, /policy/sources)
- [ ] Step 4: Render the pinned digest; rank the open recs by severity/scope
- [ ] Step 5: Only on explicit operator confirm, drive acknowledge/dismiss (lead-only); route apply to /policy-brief
```

1. **Read the recommendation queue.**
   Run `aios_client.py get /policy/recommendations` (add `--query status=$ARGUMENTS[0]` if a filter was passed). Capture each rec's `id`, `title`, `why`, `action`, `scope`, `target`, `region`, `status`, `clients`, `kbId`.

2. **Read the Command Center digest.**
   Run `aios_client.py get /command-center`. Read `digest` (the top open recs the admin home surfaces) and `spend` (the platform snapshot). The digest is the authoritative "awaiting confirmation" queue; align your ranking to it.

3. **Read change-events + sources for grounding.**
   Run `aios_client.py get /policy/changes` and `aios_client.py get /policy/sources`. Use `summary` + `severity` + `sourceName` to explain WHY a rec exists. If a rec has no backing change-event yet (a baseline rec), say so; do not invent a source.

4. **Rank and render.** Order open recs (`status` in {new, acknowledged}) by `severity` of their backing change then `scope` breadth (global > client > site). Emit the **Output format** below.

5. **Act only on confirm.** If the operator wants to acknowledge or dismiss a rec, restate the rec verbatim and require an explicit yes; then run `aios_client.py post /policy/recommendations/{id}/acknowledge` (or `/dismiss`). For `apply` (which writes a live audit overlay), STOP and route to `/policy-brief` - that is the closed-loop, guidance-changing path.

## Decision points
- If the operator asks to `apply` a recommendation -> **STOP.** Route to `/policy-brief`. `apply` writes an `audit_overlay` row that changes live client guidance; it is a deliberate, human-confirmed action owned by that skill, not the read hub.
- If the caller is not a lead and wants to transition a rec -> report "requires a lead (owner/admin/manager)"; the endpoint 403s. Do not attempt the POST.
- If sources/changes/KB are empty or `lastChecked` is "never" -> the watcher has not run (deferred). Report "watcher not yet live; showing baseline recommendations only". Do NOT infer there is no policy risk.
- If a rec's `clients` list is empty -> it is unscoped/global guidance; say "affects all clients" rather than guessing a client.
- If asked for the client-facing impact of a specific change -> hand off to `/policy-brief` (it owns the advisory + overlay).

## Common Pitfalls
- Inventing an algorithm update or an impact number because the queue is thin -> forbidden. State only what `changes`/`recommendations` returned; an empty watcher is reported as empty.
- Auto-acknowledging or dismissing a rec because it "looks handled" -> no. Every transition is a lead action behind an explicit operator confirm.
- Calling `apply` from this hub -> it changes live guidance; route to `/policy-brief`.
- Treating a baseline rec's synthetic `kb-base-*` id as a real KB citation -> it is an evergreen default; label it, do not cite a source it does not have.
- Reading `/command-center` `traffic` as live analytics -> it is an explicit audit-derived placeholder (`placeholder: true`); never quote it as organic traffic.

## Output format
Emit verbatim:

```
POLICY RADAR - digest
Watcher: <live | not-yet-live (sources lastChecked "never")>
Open recommendations (awaiting a lead): <count>
  1. <title>  [<severity-of-backing-change|baseline>] scope=<global|client|site> target=<audit|content|portal>
     Why: <why>
     Action: <action>
     Affects: <clients or "all clients">   Status: <new|acknowledged>   KB: <kbId>
  2. ...
Recent change-events: <n>  (top: "<summary>" - <severity>, <sourceName>, <detected>)
Spend snapshot: $<totalSpent>/<totalCap> (<pct>%)  daily-stop=$<dailyStop>  halted=<yes|no>
Recommended next step:
  <apply an exposed rec -> run /policy-brief for the client-facing advisory + overlay>
  <acknowledge/dismiss (lead + confirm) -> POST /policy/recommendations/{id}/{acknowledge|dismiss}>
```

Rubric enforced (reference, not inlined): the Policy KB (`GET /policy/kb`) and the impact discipline in `backend/docs/CONTENT-DOCTRINE.md`. Shared platform wiring (roles, degrade contract, the closed-loop overlay): `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
