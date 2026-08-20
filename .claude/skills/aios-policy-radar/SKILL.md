---
name: aios-policy-radar
description: Reads the Policy Radar brain (watched sources, detected change-events, the KB, the open recommendation queue) plus the Command Center digest, answers an on-demand policy question (POST /policy/ask - pure Claude Cloud API, no web search), and refreshes or resets the daily brief. Use when the operator says "policy", "algorithm update", "Google guideline change", "core update", "ask policy radar about a topic", "generate/refresh the daily policy brief", "reset the policy feed", "what recommendations are open", or asks what changed and who is exposed. Reads are staff-wide; ask spends one metered call under the policy money-dial; acknowledging/dismissing a rec and generating the brief are lead-only; the feed reset is owner-only and destructive. This skill runs any spend/write only after an explicit operator confirm. Applying a recommendation is routed to /aios-policy-brief.
argument-hint: "[rec-status | ask-topic]"
model: opus
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Read the Policy Radar (+ ask / generate / reset)

**Purpose.** Give the operator one grounded read of the Policy Radar: which change-events fired, which recommendations are open (awaiting a lead's decision), and what the Command Center surfaces first. This is the module hub. It also answers an on-demand policy question (`POST /policy/ask`), refreshes the daily brief (`POST /policy/generate`), and clears the retired scrape feed (`POST /policy/reset`). It drives the low-stakes `acknowledge` / `dismiss` transitions on confirm. It never fabricates a policy update, never invents an impact, and never auto-fires a spend or a destructive action.

**Who runs it.** Any provisioned staff (`view_reports`) may read every surface AND run `POST /policy/ask` (it is staff-gated) - but because `ask` spends one metered call, this skill confirms before firing it. Driving a recommendation (`acknowledge` / `apply` / `dismiss`) and `POST /policy/generate` require a LEAD (owner/admin/manager). `POST /policy/reset` is OWNER-only and destructive. A non-lead who tries a lead action gets a 403; a non-owner who tries reset gets a 403. A portal client holds no staff permission and is 403'd off this whole namespace.

## Required inputs / keys
- `$ARGUMENTS[0]` (optional) - a recommendation `status` filter (`new` | `acknowledged` | `applied` | `dismissed`), OR the free-text `topic` for an on-demand `ask` (e.g. "site reputation abuse", "August core update"). Omitted on a read, the queue merges the DB rows with the evergreen baseline recs so the digest is never empty pre-live.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer). The token's role decides read (any staff) vs. transition/generate (lead) vs. reset (owner).
- The shared client `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py`; shared platform wiring (roles, degrade contract) is in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
- No provider key is required to READ the radar. `POST /policy/ask` and `POST /policy/generate` call the Anthropic Cloud API server-side (pure Claude, NO web search); `ANTHROPIC_API_KEY` lives server-side. Dormant key OR a `policy` money-dial / budget block DEGRADES (still 200): `ask` returns `status='degraded'` with a `reason`; `generate` still enqueues but the run may hold at honest $0. Report the degrade honestly; never present a degraded `ask` answer as a live ruling.
- The change-detection WATCHER that fills sources/changes/KB is retired in favour of the Anthropic daily generator: until a brief has run, `lastChecked` reads "never" and sources/changes/KB may be empty. The recommendation queue still serves the baseline recs. Report this state honestly; do not present an empty feed as "no policy risk".

**Trigger.** Any request about a policy/algorithm/guideline change, an open-recommendation review, "ask the radar about <topic>", "refresh/generate the daily brief", "reset the policy feed", or "what should we act on in the radar".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the open recommendation queue (GET /policy/recommendations)
- [ ] Step 2: Read the Command Center digest + spend (GET /command-center)
- [ ] Step 3: Read the change-events + source status for context (GET /policy/changes, /policy/sources)
- [ ] Step 4: Render the pinned digest; rank the open recs by severity/scope
- [ ] Step 5: On explicit confirm only - drive acknowledge/dismiss (lead), ask (spends), generate (lead), or reset (owner)
```

1. **Read the recommendation queue.**
   Run `aios_client.py get /policy/recommendations` (add `--query status=$ARGUMENTS[0]` if a status filter was passed). Capture each rec's `id`, `title`, `why`, `action`, `scope`, `target`, `region`, `status`, `clients`, `kbId`.

2. **Read the Command Center digest.**
   Run `aios_client.py get /command-center`. Read `digest` (the top open recs the admin home surfaces) and `spend` (the platform snapshot). The digest is the authoritative "awaiting confirmation" queue; align your ranking to it.

3. **Read change-events + sources for grounding.**
   Run `aios_client.py get /policy/changes` and `aios_client.py get /policy/sources`. Use `summary` + `severity` + `sourceName` to explain WHY a rec exists. If a rec has no backing change-event yet (a baseline rec), say so; do not invent a source.

4. **Rank and render.** Order open recs (`status` in {new, acknowledged}) by `severity` of their backing change then `scope` breadth (global > client > site). Emit the **Digest output** below.

5. **Act only on confirm.** Route each requested action:
   - **acknowledge / dismiss** (lead) - restate the rec verbatim, require an explicit yes, then run `aios_client.py post /policy/recommendations/{id}/acknowledge` (or `/dismiss`).
   - **apply** - STOP and route to `/aios-policy-brief` (it writes a live audit overlay).
   - **ask / generate / reset** - use the On-demand & admin actions below.

## On-demand & admin actions (each confirm-gated)

**Ask - on-demand deep-dive (`POST /policy/ask`, staff, SPENDS).**
1. Restate the `topic` back to the operator. Because each call spends one metered Anthropic call under the `policy` money-dial, get an explicit go - NEVER auto-fire on a passing mention.
2. Run `aios_client.py post /policy/ask --json '{"topic":"<topic>"}'`.
3. Read `status`, `answer`, `urgency` (`urgent` | `informational`), `rules`, `sources`, `reason`.
4. If `status == "degraded"` -> report the `reason` (keyless / dial-blocked / no answer) and DO NOT present the message as a live ruling. Otherwise emit the **Ask output** block.

**Generate - refresh the daily brief (`POST /policy/generate`, LEAD, SPENDS).**
1. Confirm the caller is a lead; if not -> report "requires a lead (owner/admin/manager)", STOP. It enqueues the Anthropic daily brief (spends under the `policy` dial), so get an explicit go.
2. Run `aios_client.py post /policy/generate`. Response `{queued:true}`.
3. The 6 brief items land ASYNC in the KB / change-events / recommendations. Re-read the queue (Step 1) before reporting them; do not claim they are present yet.

**Reset - clear the retired feed (`POST /policy/reset`, OWNER, DESTRUCTIVE).**
1. Confirm the caller is the owner; if not -> report "requires the owner", STOP.
2. State plainly what will be cleared: EVERY change event, KB entry, and NON-baseline recommendation (the evergreen baseline recs survive). This is irreversible. Require an explicit, unambiguous confirm.
3. Run `aios_client.py post /policy/reset`. Response `{changeEvents, kbEntries, recommendations}` = the row counts cleared. Emit the **Admin-action output** block.

## Decision points
- If the operator asks to `apply` a recommendation -> **STOP.** Route to `/aios-policy-brief`. `apply` writes an `audit_overlay` row that changes live client guidance; it is owned by that skill, not the read hub.
- If the caller is not a lead and wants to transition a rec or generate the brief -> report "requires a lead (owner/admin/manager)"; the endpoint 403s. Do not attempt the POST.
- If the caller is not the owner and wants to reset -> report "requires the owner"; the endpoint 403s. Do not attempt the POST.
- If `ask` is requested but the operator has not explicitly confirmed the spend -> STOP; confirm first. It is metered under the `policy` dial.
- If `ask`/`generate` come back degraded (`status='degraded'` / honest $0) -> the Anthropic key is dormant or the dial/budget blocked; report it honestly. Do NOT retry-loop to force spend.
- If sources/changes/KB are empty or `lastChecked` is "never" -> no brief has run yet. Report "feed not yet populated; showing baseline recommendations only". Do NOT infer there is no policy risk.
- If a rec's `clients` list is empty -> it is unscoped/global guidance; say "affects all clients" rather than guessing a client.
- If asked for the client-facing impact of a specific change -> hand off to `/aios-policy-brief` (it owns the advisory + overlay).

## Common Pitfalls
- Inventing an algorithm update or an impact number because the queue is thin -> forbidden. State only what `changes`/`recommendations`/`ask` returned; an empty feed is reported as empty.
- Auto-firing `ask` because a topic was mentioned -> no. It spends under the `policy` dial; confirm the spend first.
- Presenting a degraded `ask` answer as a live Google ruling -> forbidden; a degraded answer is keyless/dial-blocked. Label it and surface the `reason`.
- Running `reset` to "tidy up" without an explicit owner confirm -> it is destructive and irreversible (clears changes/KB/non-baseline recs). Owner + explicit yes only.
- Reporting `generate`'s items as already present -> they land async; re-read the queue before claiming them.
- Auto-acknowledging or dismissing a rec because it "looks handled" -> every transition is a lead action behind an explicit operator confirm.
- Calling `apply` from this hub -> it changes live guidance; route to `/aios-policy-brief`.
- Treating a baseline rec's synthetic `kb-base-*` id as a real KB citation -> it is an evergreen default; label it.
- Reading `/command-center` `traffic` as live analytics -> it is an explicit audit-derived placeholder (`placeholder: true`); never quote it as organic traffic.

## Digest output
Emit verbatim:

```
POLICY RADAR - digest
Feed: <populated (daily brief run) | not-yet-populated (sources lastChecked "never")>
Open recommendations (awaiting a lead): <count>
  1. <title>  [<severity-of-backing-change|baseline>] scope=<global|client|site> target=<audit|content|portal>
     Why: <why>
     Action: <action>
     Affects: <clients or "all clients">   Status: <new|acknowledged>   KB: <kbId>
  2. ...
Recent change-events: <n>  (top: "<summary>" - <severity>, <sourceName>, <detected>)
Spend snapshot: $<totalSpent>/<totalCap> (<pct>%)  daily-stop=$<dailyStop>  halted=<yes|no>
Recommended next step:
  <apply an exposed rec -> run /aios-policy-brief for the client-facing advisory + overlay>
  <acknowledge/dismiss (lead + confirm) -> POST /policy/recommendations/{id}/{acknowledge|dismiss}>
  <deep-dive a topic (confirm - spends) -> POST /policy/ask>
```

## Ask output
Emit verbatim after a `POST /policy/ask`:

```
POLICY ASK - "<topic>"
Status: <ok | degraded>            Urgency: <urgent | informational>
Answer: <answer>
Rules:
  - <rule>   (grounded, up to 6; "none stated" if empty)
Sources: <official URLs cited, or "none cited">
Degrade: <"none" | "<reason> - NOT a live ruling">
```

## Admin-action output
Emit verbatim after a `POST /policy/generate` or `POST /policy/reset`:

```
POLICY ADMIN ACTION - <generate | reset>
Role check: <"lead confirmed" | "owner confirmed">
generate -> queued=<true|false>   (6-item brief lands async; re-read the queue to see it)
reset    -> cleared: changeEvents=<n> kbEntries=<n> recommendations=<n>  (baseline recs survive)
Next: <re-read the queue | proceed with the refreshed brief>
```

Rubric enforced (reference, not inlined): the Policy KB (`GET /policy/kb`) and the impact discipline in `backend/docs/CONTENT-DOCTRINE.md`. Shared platform wiring (roles, degrade contract, the closed-loop overlay): `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
