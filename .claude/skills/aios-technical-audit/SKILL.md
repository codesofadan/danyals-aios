---
name: technical-audit
description: Interprets an audit's TECHNICAL findings (crawl/index, Core Web Vitals, rendering, schema, security/infra) into a prioritized, evidence-backed fix list grounded in findings.json. Use when an operator asks about "technical SEO", "crawlability / indexation", "Core Web Vitals / LCP / CLS / INP", "rendering / JavaScript SEO", "structured data / schema errors", "HTTPS / security headers / hreflang", or wants the technical section of an audit read and prioritized. Interpret-first, it reads an existing audit; running a fresh technical audit routes through /audit.
argument-hint: "[audit-id | client | url]"
arguments: [target]
model: opus
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Interpret the Technical Audit

**Purpose.** Turn the technical findings of an existing audit into a prioritized fix list: crawl/index, Core Web Vitals, rendering/JS, schema, and security/infra. The engine produced the findings; this skill ranks and explains them against the Team B checklist. No new metrics are invented.

**Who runs it.** Any provisioned staff (`view_reports`) - the read endpoints. Creating a fresh run (the optional route-out to `/audit`) needs `run_audits`. If the caller lacks `view_reports` the reads 403 - report it and STOP.

## Required inputs / keys
- `$target` - an `audit-id` (preferred), or a client/url to locate the latest `done` audit that includes `technical`.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- No paid provider key is required to READ findings. `technical` is a Free-tier type, so a run needs no paid key; if the source audit ran with dormant crawl/PSI providers its technical findings may be a deterministic subset - REPORT that, do not present it as a full live crawl.

**Trigger.** "Technical SEO / crawl / indexation / Core Web Vitals / rendering / schema / security" questions, or "read the technical part of <audit>".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the audit id (GET /audits, filter to done + includes technical)
- [ ] Step 2: Confirm it is done (GET /audits/{id})
- [ ] Step 3: Pull findings.json (GET /audits/{id}/findings.json)
- [ ] Step 4: Group TECH-* findings by Team B area; prioritize; render output
- [ ] Step 5: If no suitable audit exists -> route to /audit (do NOT silently run one)
```

1. **Resolve the audit.** If `$target` is not an id, run `aios_client.py get /audits` and pick the newest `status=done` row for that client/url whose `types` include `technical`.
2. **Confirm done.** Run `aios_client.py get /audits/{id}` -> `status` must be `done` (else STOP / route).
3. **Pull findings.** Run `aios_client.py get /audits/{id}/findings.json`. Keep only `TECH-*` (and the technical `ON-*` rollups the Team B SOPs own, e.g. ON-084 to ON-089 CWV impact).
4. **Group and prioritize.** Bucket by area (below), rank each by severity then lowest per-check `score`, boost by `impact_usd` if present (M2 method). Flag any `confidence < 0.6` as needs-validation. Render the **Output format**.
5. **No audit? Route, do not spend.** If nothing suitable exists, tell the operator to run one via `/audit` (technical is Free-tier). Do NOT create a run from this interpret skill unless the operator explicitly asks.

Team B areas to bucket into (cite the real check ids you see):
- **Crawl/Index (B1):** TECH-001..027, 068..071, 075..078 (robots, sitemaps, crawlability, canonicals, redirects, thin/dup/index-bloat).
- **CWV/Performance (B2):** TECH-010, 039..054, 063..066, 090; ON-084..089 (LCP/CLS/INP/TTFB, blocking + unused CSS/JS, compression/caching/CDN, mobile).
- **Rendering/JS (B3):** TECH-028, 030..034, 084 (JS render, CSR issues, hidden content, cloaking).
- **Schema (B4):** TECH-035..038, 086, 087, 093; ON-073..078 (structured-data validity, rich-result eligibility, breadcrumb, OG/Twitter).
- **Security/Infra (B5):** TECH-055..062, 067, 072..074, 082, 085, 092, 095..100 (HTTPS/SSL/mixed-content, www + trailing-slash, hreflang, headers, HTTP/2-3, latency).

## Decision points
- If `$target` resolves to no `done` audit with `technical` -> STOP and route to `/audit` (Free-tier technical run); do not fabricate findings.
- If `status != done` -> STOP; the run is still in flight or failed (surface which).
- If a finding's `confidence < 0.6` -> mark "needs validation" (e.g. B3 marks JS/cloaking `confidence: 0.5` without a render diff); do not present as settled.
- If a finding's evidence carries a data gap / `[NEEDS: ...]` (e.g. no crawl-log for TECH-070) -> route to a human; NEVER invent the missing data.
- If the source audit ran with dormant crawl/PSI providers -> label the technical read "degraded (deterministic subset)"; do not claim a full live crawl.
- If two findings share a root cause (e.g. a redirect chain causing both TECH-016 and a canonical conflict) -> group under the parent, prioritize once (M2 rule).

## Common Pitfalls
- Quoting a CWV number (LCP/INP ms) that is not in `findings.json` -> grounding rule: only report measured values the engine returned.
- Calling a JS-render or cloaking finding definitive when its `confidence` is 0.5 -> B3 flags these for validation; keep the tone "supports / suggests", not "confirmed".
- Listing every minor/info finding -> lead with critical + major; quick wins are effort <= 2 AND severity in (critical, major).
- Treating a Free-tier deterministic subset as a full technical crawl -> label degraded.
- Running a new audit from here to "get fresh data" -> route to `/audit`; this skill interprets, it does not own the run/spend.

## Output format
Emit verbatim:

```
TECHNICAL AUDIT - <client> · <url>
Audit: <id>   Status: done   Composite: <score>/100
Findings read: <n TECH-* (+ rollups)>   Degrade: <"none" | "deterministic subset">
Prioritized fixes (severity then lowest score; grounded):
  1. [<TECH-ID>] <name> - <area B1..B5> - sev:<...> score:<n>/100 conf:<..> - fix: <one line from evidence>
  2. ...
Quick wins (effort <= 2, sev critical/major): <ids or "none">
Needs validation (confidence < 0.6): <ids or "none">
Data gaps / [NEEDS:]: <verbatim or "none">   -> route to a human
By area: crawl/index <n> · CWV <n> · rendering <n> · schema <n> · security <n>
Next: <fix roadmap week1 / month1 | re-audit via /audit after fixes>
```

Rubric enforced (reference, not inlined): `danyals-audit-system/checklists/technical.yaml` (TECH-* checks) and the Team B SOPs `danyals-audit-system/.claude/agents/technical/b1..b5*.md`; prioritization per `.../agents/meta/m2-prioritizer.md`. Shared depth in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
