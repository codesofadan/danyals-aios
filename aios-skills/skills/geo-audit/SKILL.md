---
name: geo-audit
description: Interprets an audit's GEO / AI-search-readiness findings (AI Overview + direct-answer optimization, passage citability, LLM-readable semantic HTML, AI-crawler access, llms.txt, AI-search authority) into a prioritized readiness plan grounded in findings.json. Use when an operator asks about "GEO", "AI Overviews / AI search", "LLM visibility", "ChatGPT / Perplexity citations", "extractability / direct answers", "llms.txt", or "will AI cite this page". Interpret-first, it reads an existing audit; running a fresh one routes through /audit (geo is a PAID type - spends metered budget, cost-gated server-side).
argument-hint: "[audit-id | client | url]"
arguments: [target]
model: opus
allowed-tools: Bash(python ${CLAUDE_SKILL_DIR}/../../scripts/aios_client.py *) Read
---

# Interpret the GEO / AI-Search Audit

**Purpose.** Turn the GEO findings of an existing audit into a prioritized AI-search-readiness plan: extractability, entity clarity, LLM-readable structure, AI-crawler access, and AI-search authority. The engine produced the findings; this skill ranks and explains them against the A5 GEO SOP and the extractable-answer rubric. No citations or metrics are invented.

**Who runs it.** Any provisioned staff (`view_reports`) - the reads. A fresh run (route-out to `/audit`) needs `run_audits` AND the Paid tier. If the caller lacks `view_reports` the reads 403 - report it and STOP.

## Required inputs / keys
- `$target` - an `audit-id` (preferred), or a client/url to locate the latest `done` audit that includes `geo`.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- `geo` is a PAID audit type: a fresh run needs the Paid tier. AI-citation data (Otterly) may be dormant; when it is, the A5 SOP marks the AI-authority checks `confidence: 0.5` - REPORT that; do not claim a page "is cited" without evidence.

**Trigger.** "GEO / AI Overviews / AI search / LLM visibility / extractability / llms.txt" questions, or "read the GEO part of <audit>".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the audit id (GET /audits, filter to done + includes geo)
- [ ] Step 2: Confirm it is done (GET /audits/{id})
- [ ] Step 3: Pull findings.json (GET /audits/{id}/findings.json)
- [ ] Step 4: Group the GEO checks; prioritize; render output
- [ ] Step 5: If no suitable geo audit -> route to /audit (Paid; confirm spend first)
```

1. **Resolve the audit.** If `$target` is not an id, run `../../scripts/aios_client.py GET /audits` and pick the newest `status=done` row for that client/url whose `types` include `geo`.
2. **Confirm done.** Run `../../scripts/aios_client.py GET /audits/{id}` -> `status` must be `done` (else STOP / route).
3. **Pull findings.** Run `../../scripts/aios_client.py GET /audits/{id}/findings.json`. Keep the A5-owned GEO checks (ON-048, ON-049, ON-100..107) and the AI-search-authority checks (OFF-067, OFF-068, OFF-069).
4. **Group and prioritize.** Bucket by the GEO rubric dimensions (below), rank by severity then lowest per-check `score`; flag every AI-authority claim without Otterly evidence as `confidence 0.5` needs-validation. Render the **Output format**.
5. **No geo audit? Route, confirm the spend.** If none exists, a GEO run needs the **Paid** tier via `/audit` (spends metered budget, cost-gated). Do NOT create a Paid run from this interpret skill.

GEO rubric dimensions to bucket into (cite the real check ids you see):
- **Extractable answer / AI Overview (ON-048, ON-049):** a 40-60 word direct answer up front; question/answer-bearing headings. Also enforced by CONTENT-DOCTRINE §4 (extractable answer).
- **Passage citability + structure (ON-100, ON-105, ON-107):** self-contained subsections; clean semantic HTML; structured content.
- **Tables/lists for snippets (ON-101, ON-102):** real `<th>` tables and lists, not `<div>` fakes.
- **LLM readability (ON-104):** answer not gated behind JS-only render / infinite scroll.
- **AI crawl readiness + llms.txt (ON-103, ON-106):** robots allows GPTBot/ClaudeBot/PerplexityBot/Google-Extended (unless client opts out); llms.txt is an informational positive, not required in 2026.
- **AI-search authority (OFF-067, OFF-068, OFF-069):** which prompts already cite the site vs target gaps - ONLY when Otterly evidence exists.

## Decision points
- If `$target` resolves to no `done` audit with `geo` -> STOP and route to `/audit` (Paid tier, spends, cost-gated); do not fabricate AI-visibility findings.
- If `status != done` -> STOP; surface in-flight/failed.
- If an AI-authority finding has no Otterly evidence -> it is `confidence 0.5`; report structure as "supports citation eligibility", NEVER "Google/ChatGPT will cite this" (A5 hard rule).
- If robots blocks AI crawlers -> warn, but note it may be an intentional client opt-out; recommend confirming with the client, do not auto-call it a defect.
- If llms.txt is absent -> info-level only (no platform has confirmed reading it in 2026); do not score it as a critical gap.
- If a finding's evidence carries a `[NEEDS: ...]` (e.g. no manual citation probe) -> route to a human for a manual sampling; do not invent citations.

## Common Pitfalls
- "The structure is great, so AI Overviews will cite it." -> A5 hard rule: no citation claim without Otterly/manual evidence; tone is eligibility, not outcome.
- Scoring llms.txt absence as critical -> it is informational in 2026; keep it info-level.
- Judging LLM-readability by how well the copy reads for humans -> they are independent; judge extractability/structure separately from prose quality.
- Inventing "cited by Perplexity for X" without evidence -> forbidden; grounding rule.
- Treating a dormant-Otterly geo run as full AI-visibility data -> label degraded / needs manual sampling.

## Output format
Emit verbatim:

```
GEO / AI-SEARCH AUDIT - <client> · <url>
Audit: <id>   Status: done   Tier: <Paid>   Composite: <score>/100
Findings read: <n GEO checks>   Otterly evidence: <present | dormant -> conf 0.5>
Prioritized readiness plan (severity then lowest score; grounded):
  1. [<ON-/OFF-ID>] <name> - <dimension> - sev:<..> score:<n>/100 conf:<..> - action: <one line from evidence>
  2. ...
Extractable answer (ON-048/049): <present 40-60w | missing | weak>
AI crawl access (ON-106): <allowed | blocked (confirm opt-out) | n/a>
AI-search authority (OFF-067..069): <evidence-backed gaps | needs manual sampling>
Needs validation (confidence < 0.6): <ids or "none">
Data gaps / [NEEDS:]: <verbatim or "none">   -> route to a human
Next: <fix extractability / structure | re-audit via /audit (Paid) | manual citation probe>
```

Rubric enforced (reference, not inlined): the A5 GEO SOP `danyals-audit-system/.claude/agents/onpage/a5-geo-ai-search.md`, `danyals-audit-system/checklists/on-page.yaml` (ON-048/049, ON-100..107) + `off-page.yaml` (OFF-067..069), and `backend/docs/CONTENT-DOCTRINE.md` §4 (extractable answer). Shared depth in `../../reference/`.
