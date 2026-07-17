---
name: local-audit
description: Interprets an audit's LOCAL findings (Google Business Profile, citations/NAP, reviews, local pack / geo-grid) into a local SEO action plan grounded in findings.json. Use when an operator asks about "local SEO", "GBP / Google Business Profile", "map pack / local pack ranking", "NAP consistency / citations", "review velocity / reputation", or wants the local section of an audit read and prioritized. Interpret-first, it reads an existing local audit; running a fresh one routes through /audit (local is a PAID type - spends metered budget, cost-gated server-side).
argument-hint: "[audit-id | client | url]"
arguments: [target]
model: opus
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Interpret the Local Audit

**Purpose.** Turn the local findings of an existing audit into a prioritized local action plan across GBP, citations/NAP, reviews, and local-pack/geo. The engine produced the findings; this skill ranks and explains them against the Team D checklist. No metrics are invented.

**Who runs it.** Any provisioned staff (`view_reports`) - the reads. A fresh run (route-out to `/audit`) needs `run_audits` AND the Paid tier. If the caller lacks `view_reports` the reads 403 - report it and STOP.

## Required inputs / keys
- `$target` - an `audit-id` (preferred), or a client/url to locate the latest `done` audit that includes `local`.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- `local` is a PAID audit type: a fresh run needs the Paid tier and live local-data providers (Google Places/GBP, citation aggregators). If those were dormant on the source run, the local findings are a deterministic subset - REPORT that; do not present it as live GBP/citation data.

**Trigger.** "Local SEO / GBP / map pack / NAP / citations / reviews" questions, or "read the local part of <audit>".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the audit id (GET /audits, filter to done + includes local)
- [ ] Step 2: Confirm it is done (GET /audits/{id})
- [ ] Step 3: Pull findings.json (GET /audits/{id}/findings.json)
- [ ] Step 4: Group LOC-* by Team D area; prioritize; render output
- [ ] Step 5: If no suitable local audit -> route to /audit (Paid; confirm spend first)
```

1. **Resolve the audit.** If `$target` is not an id, run `aios_client.py get /audits` and pick the newest `status=done` row for that client/url whose `types` include `local`.
2. **Confirm done.** Run `aios_client.py get /audits/{id}` -> `status` must be `done` (else STOP / route).
3. **Pull findings.** Run `aios_client.py get /audits/{id}/findings.json`. Keep the `LOC-*` findings.
4. **Group and prioritize.** Bucket by area (below), rank by severity then lowest per-check `score`; flag `confidence < 0.6` as needs-validation (map-grid and review data often carry it). Render the **Output format**.
5. **No local audit? Route, confirm the spend.** If none exists, tell the operator a local run needs the **Paid** tier via `/audit` (spends metered budget, cost-gated). Do NOT create a Paid run from this interpret skill.

Team D areas to bucket into (cite the real check ids you see):
- **GBP (D1):** LOC-001..010 (profile completeness, category, photos, posts, products/services, attributes, hours, Q&A, service-area).
- **Citations/NAP (D2):** LOC-011..020 (citation audit + count, consistency, NAP exactness, missing/duplicate, aggregators, Apple/Bing).
- **Reviews (D3):** LOC-021..028 (count/recency, sentiment, velocity, response rate/quality, keyword-rich reviews, reputation, competitor benchmark).
- **Local pack / Geo (D4):** LOC-029..037 (geo-grid map-pack ranking, geo-keyword optimization, local relevance, LocalBusiness schema fit, service-area page coverage/uniqueness, local content depth, prominence).

## Decision points
- If `$target` resolves to no `done` audit with `local` -> STOP and route to `/audit` (Paid tier, spends, cost-gated); do not fabricate a GBP/NAP picture.
- If `status != done` -> STOP; surface in-flight/failed.
- If a finding's `confidence < 0.6` (common for LOC-029 geo-grid without a live grid pull, or LOC-021 without live review data) -> mark "needs validation"; do not state a rank/velocity as fact.
- If NAP data is missing / `[NEEDS: NAP]` in evidence -> route to a human to supply the canonical NAP; NEVER invent the name/address/phone (a wrong NAP is worse than a flagged gap).
- If local providers were dormant on the source run -> label "degraded (deterministic subset)"; do not present as live GBP/citation data.
- If per-city service-area pages fail LOC-034 uniqueness -> flag as spun/templated; route to content, do not paper over it.

## Common Pitfalls
- Stating a map-pack position (e.g. "ranks #3 in the 3-mile ring") not present in `findings.json` -> grounding rule: report only the grid data the engine returned; else "needs live grid pull".
- Filling a missing NAP or GBP category from memory -> forbidden; route the `[NEEDS:]` to a human.
- Treating a deterministic-subset local run as live GBP/citation/review data -> label degraded.
- Silently triggering a Paid local run to "get the data" -> it spends; route to `/audit` and let the operator confirm.
- Burying LOC-013 (NAP consistency) under minor items -> NAP consistency is foundational; surface it high when it fails.

## Output format
Emit verbatim:

```
LOCAL AUDIT - <client> · <url>
Audit: <id>   Status: done   Tier: <Paid>   Composite: <score>/100
Findings read: <n LOC-*>   Degrade: <"none" | "deterministic subset">
Prioritized local plan (severity then lowest score; grounded):
  1. [<LOC-ID>] <name> - <area GBP|Citations/NAP|Reviews|LocalPack/Geo> - sev:<..> score:<n>/100 conf:<..> - action: <one line from evidence>
  2. ...
NAP status (LOC-013): <consistent | inconsistent | missing | needs live data>
Quick wins (effort <= 2, sev critical/major): <ids or "none">
Needs validation (confidence < 0.6): <ids or "none">
Data gaps / [NEEDS:]: <verbatim or "none">   -> route to a human
By area: GBP <n> · Citations/NAP <n> · Reviews <n> · LocalPack/Geo <n>
Next: <fix roadmap | reconcile NAP via /citation-builder | re-audit via /audit (Paid)>
```

Rubric enforced (reference, not inlined): `danyals-audit-system/checklists/local.yaml` (LOC-* checks) and the Team D SOPs `danyals-audit-system/.claude/agents/local/d1..d4*.md`; prioritization per `.../agents/meta/m2-prioritizer.md`. Shared depth in `${CLAUDE_PLUGIN_ROOT}/reference/`.
