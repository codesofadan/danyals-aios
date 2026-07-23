---
name: rank-report
description: Reports a client's keyword rankings from the rank tracker - current positions, movement, best-ever, and map of unranked terms - and prices the monthly commitment before any keyword is added. Use when an operator asks "where do we rank", wants a ranking / position / SERP report, asks what a keyword moved to, wants to add or pause tracked keywords, wants to change a check cadence, or asks what rank tracking costs a client. Adding keywords or raising cadence re-prices a STANDING monthly cost the CLIENT pays and can be rejected with a 402.
argument-hint: "[client] [action]"
arguments: [client, action]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Report and Price Keyword Rankings

**Purpose.** Read `$client`'s tracked keywords, report positions and movement honestly, and
price the standing monthly commitment BEFORE adding keywords or raising a cadence.

**Who runs it.** Reading needs `view_reports` (all six staff roles). Adding keywords, changing
a cadence/status, and forcing a check need the `run_research` module permission
(owner/admin/manager). Every route also needs the `rank_tracker` feature grant. Lacking either
→ 403 "the token's role lacks the required permission" → report which one and STOP.

## Required inputs / keys
- `$client` — the client name, resolved to a real `client_id`. Never invent an id.
- `$action` — `report` (default), `add`, `cadence`, or `check`.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- The SERP provider must be live server-side for real positions. Dormant → the projection
  reads `provider: "fake"`, `live: false`, `costPerCheck: 0.0`. REPORT the degrade; a keyless
  deploy can never 402 because the whole book prices at $0.

**Trigger.** "Where do we rank", a ranking / position / SERP report, "what did <keyword> move
to", adding or pausing tracked keywords, changing a check cadence, "what does tracking cost".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client (resolve-client)
- [ ] Step 2: Read the tracked book + stats
- [ ] Step 3: Read the cost projection (ALWAYS before any add/cadence change)
- [ ] Step 4: Read history for any keyword whose movement is being reported
- [ ] Step 5: Apply the gate; render the pinned output; STOP on a 402
```

1. **Resolve the client.** Run `python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py
   resolve-client --client "$client"` → `GET /clients` (name match). Capture `client_id`.

2. **Read the book and the stats.** Run `aios_client.py get "/rank-tracker/keywords?clientId=<id>&limit=200"`
   → `GET /rank-tracker/keywords`, and `aios_client.py get "/rank-tracker/stats?clientId=<id>"`
   → `GET /rank-tracker/stats`. Read `position`, `change`, `bestPosition`, `cadence`, `status`,
   `stale`, `checked` per row. Fields: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/part8-output-formats.md` §1.

3. **Read the cost projection.** Run `aios_client.py get "/rank-tracker/cost-projection?clientId=<id>"`
   → `GET /rank-tracker/cost-projection` (`clientId` is REQUIRED). Read `monthlyCost`,
   `budgetCap`, `budgetRemaining`, `withinBudget`, `live`, `message`. **Do this BEFORE any add
   or cadence change, every time** — tracking is a STANDING per-client cost and the client pays it.

4. **Read history only for keywords whose movement you report.** Run `aios_client.py get
   "/rank-tracker/keywords/<code>/history?limit=30"` → `GET /rank-tracker/keywords/{code}/history`.
   A gap in history is an outage, not a lost ranking (§1).

5. **Act, or hand off.** For an add: `aios_client.py post /rank-tracker/keywords --json
   '{"clientId":"<id>","keywords":["…"],"cadence":"weekly"}'` → `POST /rank-tracker/keywords`.
   For a cadence/status change: `aios_client.py patch /rank-tracker/keywords/<code> --json
   '{"cadence":"weekly"}'` → `PATCH /rank-tracker/keywords/{code}`. For a forced check:
   `aios_client.py post /rank-tracker/keywords/<code>/check` → `POST /rank-tracker/keywords/{code}/check`.
   Render the **Output format**. Never approve a cost increase on the client's behalf.

## Decision points
- If the client exits **2** with `status: 402` → **STOP and report.** The commitment exceeds the
  client's remaining monthly cap. The `detail` IS the projection's `message` — surface it
  verbatim. Do NOT retry, do NOT split the add into smaller batches to sneak under the cap, do
  NOT drop to a cheaper cadence without the operator asking. The operator raises the cap,
  lowers the cadence, or tracks fewer keywords. This is a money decision, not a retry.
- If `withinBudget` is false BEFORE you call the add → do not call it. Report the projection and
  ask the operator to decide.
- If `position` is **null** → the term is **unranked**: checked successfully, not in the top-N.
  Report it as "unranked (not in top-N)". It is **never** a failed check and **never** a lost
  ranking. Reporting a null as a drop fabricates a loss out of a fact.
- If a keyword has **no history point** for a date → the check errored and wrote nothing ($0). An
  honest gap. Do NOT interpolate, do NOT call it a drop.
- If `live` is false / `provider` is `"fake"` → label the whole report "degraded (SERP provider
  dormant); positions are deterministic fakes, not live" and note the $0 projection is not a
  real price. Do NOT present fake positions as live rankings.
- If `budgetCap <= 0` → the client is **uncapped** ("0 = uncapped"), so `withinBudget` is always
  true. Say "uncapped" — do not report it as "within budget", which implies a cap was checked.
- If the exit code is **3** (transport) or **4** (timeout) → the API is unreachable / slow. Report
  it; never present a partial read as the client's ranking picture.
- If `$action` is a cadence change that LOWERS cost (pause, weekly→ nothing faster) → it is always
  allowed, even over cap. Only increases are gated.

## Common Pitfalls
- "Position is null, so we lost the ranking." → No. Null = unranked (checked, not in top-N). A
  failure writes nothing at all. Report unranked, never a drop.
- "The add 402'd, I'll add them in two smaller batches." → The projection prices the WHOLE book
  as it would be after the add; smaller batches hit the same wall and each one that slips through
  raises a bill the client did not agree to. STOP and report.
- Skipping the projection because "it's only a few keywords" → every add re-prices a standing
  monthly commitment the client pays. Read it first, every time.
- "`withinBudget: true`, so it's affordable." → Check `live` first. A dormant provider prices
  everything at $0 and passes trivially; an uncapped client passes trivially too.
- Reading `change.direction: "up"` as a worse position → `up` means the position **improved**.
- Reporting `avgPosition` as the client's average across all tracked terms → it averages **ranked
  rows only**, and reads `0.0` when nothing ranks. Say how many are unranked alongside it.
- Treating a 202 from `check` as a completed check → `{queued: true}` means enqueued. The gate and
  the provider call run in the worker. Re-read the keyword to see a new position.

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
RANK REPORT — <client>
Tracked: <tracked>   Avg position (ranked rows only): <avgPosition>   Top 3: <topThree>
Unranked (position=null, checked/not in top-N): <count of null positions>
Provider: <provider>   Live: <true|false>

Movement (from change.direction; "up" = improved):
  <keyword> — pos <position|unranked>  <direction> <value>  best <bestPosition|none>  <cadence>  checked <checked>
  ...
Stale rows (stale=true): <list or "none">
Paused rows (status=paused): <list or "none">

COST PROJECTION (the CLIENT pays this, monthly, standing):
  Tracked: <tracked>  (daily=<daily>, weekly=<weekly>)   Checks/mo: <checksPerMonth>
  Cost/check: $<costPerCheck>       Monthly cost: $<monthlyCost>
  Cap: <$<budgetCap> | "uncapped (cap=0)">   Spent: $<budgetSpent>   Remaining: $<budgetRemaining>
  Within budget: <withinBudget>     message: "<message>"
Degrade notes: <"none" | "provider dormant (live=false) -> positions are fakes, $0 is not a real price">
Result of this run: <read-only | added N keywords | cadence changed | check queued | STOPPED: 402>
<if 402> 402 detail (verbatim): "<detail>"
  -> STOP. Operator decides: raise the cap, lower the cadence, or track fewer keywords.
```

Exact response fields + the null / 402 / degrade rules: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/part8-output-formats.md` §1.
