---
name: audit
description: Runs a URL SEO audit (Free or Paid) via the audit engine, tracks the audit board and KPIs, pulls the report PDF / findings.json, and interprets the top grounded findings for a human. Use when an operator says "audit this site", "run an SEO health check on a url", "how did this client's audit score", "pull the audit report", or asks for the audit board / stats. This is the audit module hub; it delegates deep interpretation to /technical-audit, /local-audit, /geo-audit. A Paid run spends metered audit-provider budget (cost-gated server-side).
argument-hint: "[client] [url] [tier] [types]"
arguments: [client, url, tier, types]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/../../scripts/aios_client.py *) Read
---

# Run and Interpret a URL Audit

**Purpose.** Kick off an audit of `$url` for `$client` (Free or Paid, chosen types), track it to `done`, pull the report artifacts, and read the top grounded findings back to the operator. The Python audit engine owns the run; this skill orchestrates the call order, respects the tier gate, and interprets only what `findings.json` actually returned.

**Who runs it.** Reads (`GET /audits*`) need any provisioned staff (`view_reports`). Creating a run (`POST /audits`) needs `run_audits`. A portal client holds neither and is 403'd off this namespace. If the caller lacks `run_audits`, `POST /api/v1/audits` returns 403 - report "requires run_audits" and STOP.

## Required inputs / keys
- `$client` - the client name or id. `POST /audits` snapshots `client_name` server-side and 404s an unknown/invisible `client_id`; never invent one.
- `$url` - the public target URL. The endpoint runs an SSRF guard; a private/internal address is rejected 400.
- `$tier` - `Free` (default) or `Paid`. Free makes zero paid-provider spend.
- `$types` - subset of `technical, actionable, local, geo, backlink` (default `technical, actionable`). `local`, `geo`, `backlink` are PAID types: on the `Free` tier they are rejected 400.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- Paid audit-provider keys (crawl/SERP/local data) must be live for a true Paid run. When dormant the engine degrades to its deterministic subset - REPORT the degrade, do not present a degraded run as a live Paid audit.

**Trigger.** Any "audit / SEO health check / run a scan on <url>", a request for the audit board or KPIs, or "pull the report / findings" for a completed audit.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the board + KPIs (GET /audits, GET /audits/stats)
- [ ] Step 2: Confirm tier vs types; if any paid type on Free -> resolve before creating
- [ ] Step 3: Create the run (POST /audits) and capture the audit id
- [ ] Step 4: Poll to done/failed (GET /audits/{id})
- [ ] Step 5: Pull findings.json (+ report.pdf); interpret grounded top findings; render output
```

1. **Read the board and KPIs.** Run `../../scripts/aios_client.py GET /audits` and `... GET /audits/stats` -> the audit rows and `{thisMonth, avgScore, runningNow, turnaroundMin}`. Use this to answer board/stats questions without creating a run.
2. **Reconcile tier and types.** If `$types` contains `local`/`geo`/`backlink` while `$tier` is `Free`, apply the tier decision point BEFORE creating.
3. **Create the run.** Run `../../scripts/aios_client.py POST /audits --json '{"client_id":"<id>","url":"$url","tier":"$tier","types":[...]}'` -> `POST /api/v1/audits`. Capture the returned `id` and initial `status` (`queued`).
4. **Poll to a terminal state.** Run `../../scripts/aios_client.py GET /audits/{id}` until `status` is `done` or `failed`. The worker owns `queued -> running -> done|failed`; never force a transition.
5. **Pull and interpret the artifacts.** When `done`, fetch `../../scripts/aios_client.py GET /audits/{id}/findings.json` (and `GET /audits/{id}/report.pdf` if `pdf` is true). Read the composite `score`, then rank findings by severity then lowest per-check score (M2 method). Render the **Output format**. Do NOT invent any metric the artifact did not return.

## Decision points
- If the caller lacks `run_audits` -> `POST /audits` 403s -> report "requires run_audits", STOP. Reads may still proceed.
- If `$tier` is `Free` and a paid type is requested -> `POST /audits` returns 400 ("Paid audit types require the Paid tier") -> tell the operator to either drop the paid types or confirm a **Paid** run (which spends metered budget, cost-gated server-side). Do NOT silently switch to Paid; a Paid run is a deliberate operator choice.
- If `$url` is not a public address -> 400 SSRF guard -> surface the reason, STOP (do not retry with an internal host).
- If `status == failed` -> surface the failure; STOP (do not blindly re-create). Re-run only on the operator's say-so.
- If Paid provider keys are dormant -> the engine ran its deterministic subset -> label the whole result "degraded (paid providers dormant); not a live Paid audit" and do not present fake numbers as live.
- If a finding's `confidence < 0.6` -> mark it "needs validation" (M2 rule), do not present it as settled.
- If a finding carries a data gap / `[NEEDS: ...]` in its evidence -> route it to a human; NEVER fill the missing fact yourself.

## Common Pitfalls
- "Local/geo would be nice, I'll just flip to Paid." -> A Paid run spends metered budget; only switch on explicit operator confirmation. Free stays Free.
- Presenting the deterministic-subset (dormant keys) run as a real Paid audit -> forbidden; label it degraded.
- Reporting a composite `score` that is still `null` (pending) as `0/100` -> it is pending, not zero; say "pending".
- Inventing DA/DR/traffic/ranking numbers to "round out" the summary -> grounding rule: report only what `findings.json` returned.
- Re-creating a `failed` audit in a loop -> surface the failure reason first; a repeat run without a cause change just re-fails and re-spends.
- Deep-interpreting technical/local/geo findings inline here -> hand off to `/technical-audit`, `/local-audit`, `/geo-audit` for the rubric-grounded read; the hub gives the headline.

## Output format
Emit verbatim:

```
AUDIT - <client> · <url>
Audit: <id>   Tier: <Free|Paid>   Types: <t,...>   Status: <queued|running|done|failed>
Composite score: <score>/100   (or "pending")
Runtime: <runtime>   Run: <when>
Artifacts: PDF <yes/no>   findings.json <yes/no>
Top findings (grounded, from findings.json; severity then lowest score):
  [<CHECK-ID>] <name> - sev:<critical|major|minor|info>  score:<n>/100  conf:<0.0-1.0>
  ... up to 5
Needs validation (confidence < 0.6): <check ids or "none">
Data gaps / [NEEDS:]: <list verbatim or "none">   -> route to a human
Degrade notes: <"none" | "paid providers dormant -> deterministic subset, NOT a live Paid audit">
Recommended next:
  <interpret: /technical-audit | /local-audit | /geo-audit>
  <or: run Paid types (spends, cost-gated) | pull report.pdf>
```

Rubric enforced (reference, not inlined): `danyals-audit-system/checklists/README.md` (the 339-check taxonomy + ID prefixes ON-/TECH-/OFF-/LOC-) and the meta SOPs `danyals-audit-system/.claude/agents/meta/m1-orchestrator.md`, `m2-prioritizer.md` (severity x score x confidence ranking). Shared depth in `../../reference/`.
