---
name: backlink-audit
description: Reviews the referring-domain backlink profile and anchor toxicity, then flags at/above-threshold spam links as toxic (queues them for a disavow review) grounded in the real backlink rows. Use when an operator asks for a "backlink audit", "toxic / spammy links", "disavow", "anchor text profile / over-optimization", "PBN / link farm footprint", or "referring domain review". Flagging toxic backlinks is a LEAD-only write that mutates shared state (it queues a disavow review, it does not submit to Google); cost-gated is not applicable but the write is guarded.
argument-hint: "[client] [spam-threshold]"
arguments: [client, spam_threshold]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Audit the Backlink Profile and Queue Disavows

**Purpose.** Read the referring-domain profile and anchor distribution, judge toxicity against the Team C rubric, and (on a LEAD's go) flag spam links at/above a threshold as `toxic` so they enter the disavow-review queue. Grounded in the real backlink rows; no DA/DR or spam number is invented.

**Who runs it.** Reading the profile needs `view_reports`. Flagging toxic links (`POST /offpage/backlinks/flag-toxic`) is LEAD-only (owner/admin/manager). If a non-lead calls the flag, it 403s - report "requires a LEAD", STOP.

## Required inputs / keys
- `$client` - optional client filter (`clientId`) to scope the profile read.
- `$spam_threshold` - the spam score at/above which a link is flagged toxic. Defaults server-side to a conservative `60` (range 0-100). Choose it deliberately.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- No provider key is required; backlink `authority`/`spam` are monitoring values ingested upstream. Report them as-is.

**Trigger.** "Backlink audit / toxic links / disavow / anchor profile / PBN footprint / referring domains".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the profile + KPIs (GET /offpage/backlinks, GET /offpage/kpis)
- [ ] Step 2: Read the current toxic queue (GET /offpage/backlinks?status=toxic)
- [ ] Step 3: Assess anchor distribution + toxicity; propose a threshold
- [ ] Step 4: STOP - present the proposed flag set; a LEAD confirms the threshold
- [ ] Step 5: On explicit LEAD go, flag (POST /offpage/backlinks/flag-toxic); re-read the queue
```

1. **Read the profile and KPIs.** Run `aios_client.py get /offpage/backlinks` (add `?clientId=<id>`) and `... get /offpage/kpis`. Read each row's `authority`, `spam`, `anchor`, `refDomain`, `status`, and the `toxicFlagged` KPI.
2. **Read the current toxic queue.** Run `aios_client.py get /offpage/backlinks?status=toxic` so you flag the delta, not what is already queued.
3. **Assess and propose.** Summarize the anchor distribution (branded vs exact-match vs naked/generic) and spam concentration against the C1/C2 rubric; recommend a `spam_threshold`. Show which rows the threshold would move to `toxic`.
4. **STOP for the LEAD.** Present the proposed flag set and threshold. Do NOT flag without an explicit LEAD confirmation - the flag mutates shared state.
5. **Flag on confirmation.** On the LEAD's go, run `aios_client.py post /offpage/backlinks/flag-toxic --json '{"spam_threshold":<n>}'`. It returns `{flagged:<count>}` (idempotent). Re-read `?status=toxic` and render the **Output format**.

## Decision points
- If the caller is not a LEAD -> the flag 403s -> report "requires a LEAD (owner/admin/manager)", STOP after presenting the read-only assessment.
- If the operator has not confirmed a threshold -> STOP at step 4; never flag on your own judgement alone.
- If the anchor profile is over-optimized (high exact-match ratio, OFF-018/OFF-020) -> call it out as a toxicity signal even if individual `spam` scores are moderate; recommend the threshold with that context.
- If a PBN/link-farm footprint is visible (OFF-036/OFF-038 patterns: shared IP/subnet, sitewide/footer links) -> surface it explicitly; these often warrant flagging below the default 60.
- If `flag-toxic` returns `flagged: 0` -> no rows met the threshold; report honestly, do not lower the threshold to force a number.
- If a row's `spam`/`authority` is missing -> treat as unknown; do not assume a value.

## Common Pitfalls
- "These look spammy, I'll just flag them." -> flagging is a LEAD write; STOP and get explicit confirmation of the threshold first.
- Reporting "disavowed" after flagging -> `toxic` only QUEUES a disavow review; it does not submit a disavow file to Google.
- Inventing a spam/DR number to justify a flag -> grounding rule: only the row's `spam`/`authority`.
- Lowering the threshold repeatedly until something is flagged -> the threshold is a deliberate risk choice, not a target count.
- Ignoring anchor over-optimization because per-link spam is low -> an exact-match-heavy profile is itself a risk (C2); factor it in.

## Output format
Emit verbatim:

```
BACKLINK AUDIT - <client or "all clients">
Profile: referring domains <n> · new(30d) <n> · lost(30d) <n> · toxic queue <n>
Anchor mix (grounded): branded <n> · exact-match <n> · naked/generic <n> · other <n>
Toxicity signals: <e.g. exact-match over-optimization / PBN footprint / none>
Proposed threshold: spam >= <n>   Would flag: <n rows>
  <refDomain> a:<authority> s:<spam> anchor:"<anchor>"  (up to 5, grounded)
Action taken: <"none - awaiting LEAD" | "flagged <count> as toxic (disavow review queued)">
Note: toxic = queued for disavow review, NOT submitted to Google.
Next: <LEAD confirm threshold | export disavow set for review | re-monitor>
```

Rubric enforced (reference, not inlined): `danyals-audit-system/checklists/off-page.yaml` and the Team C SOPs `danyals-audit-system/.claude/agents/offpage/c1-backlink-profile.md` (OFF-001..016, 070/071 profile) + `c2-anchor-toxicity.md` (OFF-007/008 toxicity, OFF-017..023 anchors, OFF-036..040 PBN/disavow). Shared depth in `${CLAUDE_PLUGIN_ROOT}/reference/`.
