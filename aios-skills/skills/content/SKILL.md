---
name: content
description: The Content module hub for Danyal AIOS. Creates any content job (service, blog, or local page), reads the content board + KPIs, pulls a job's draft/keywords/QA/schema, and runs the human review gate. Use when an operator says "write content", "make a page", "write an article/blog", "create a service or local page", "check the content board", "what's awaiting review", or "review/approve/reject a draft" for a client. Routes to the deep skill for the page type. Creating a job spends metered AI budget; approving is a LEAD action.
argument-hint: "[client] [page-type] [topic]"
arguments: [client, page_type, topic]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Content Module Hub

**Purpose.** Be the single entry point for the Content module: read the board, create a content
job of any page type, drive it to the review gate, and surface the QA scorecard for a human to
approve. For the page-type rubric detail, route to the deep skill.

**Who runs it.** Any `view_reports` staff can read the board (`GET /content/jobs*`). Creating a
job needs `publish_content`. The review gate (approve/edit/reject) is LEAD-only
(owner/admin/manager). A portal client holds none of these and is 403'd off the surface.

## Required inputs / keys
- `$client` — the client name (resolved to a real `client_id`; never invent one).
- `$page_type` — `service` | `blog` | `local`. Decides the deep skill + the server-resolved
  framework/schema.
- `$topic` — the brief line (e.g. "AC repair in San Jose", "how tankless heaters save money").
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- `SERPER_API_KEY` + `ANTHROPIC_API_KEY` live server-side for real research + generation + the
  QA judge; dormant → the pipeline degrades to the deterministic fake (report it, never present
  fake as live).

**Trigger.** "Write content / a page / an article / a blog / a service or local page", "content
board / content jobs / awaiting review", "review this draft" for a client.

## Route by page type first
- `page_type == local` → prefer **/local-service-page** (city + service; DOCTRINE §8 local
  anatomy). Its SOP is the reference implementation.
- `page_type == blog` → prefer **/blog-post** (informational; PAS default; entity coverage +
  extractable answer + FAQ).
- Bulk titles + meta descriptions only → prefer **/titles-meta**.
- `page_type == service` (or a general request) → run the hub SOP below.

The deep skills carry the tighter, rubric-embedded SOP; the hub does not duplicate their rubric.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Read the board / KPIs if the operator wants status (stats / list-jobs)
- [ ] Step 2: Resolve the client + fresh context (resolve-client)
- [ ] Step 3: Create the content job for the page type (create-job)
- [ ] Step 4: Wait for needs_review (wait-job)
- [ ] Step 5: Pull QA + draft + schema + keywords (fetch-job)
- [ ] Step 6: Evaluate the gate; render the pinned output; STOP for the human
```

1. **Read the board (status requests only).** Run `aios_client.py stats` → `GET
   /content/jobs/stats` (in-pipeline / awaiting-review / published-this-month / avg cost) and/or
   `aios_client.py list-jobs [--status needs_review]` → `GET /content/jobs`. Report the KPIs and
   stop if the operator only asked for status.

2. **Resolve the client + fresh context.** Run `aios_client.py resolve-client --client "$client"`
   → `GET /clients` (name match) + `GET /context/client/{id}` + `/health`. Confirm `client_id`,
   read `health.lag`. Grounds the job in real facts (DOCTRINE §1/§2).

3. **Create the content job.** Run `aios_client.py create-job --client-id <id> --page-type
   $page_type --topic "$topic" --framework Auto --target WordPress` → `POST /content/jobs`. The
   server resolves the framework (`Auto` → AIDA/PAS/BAB per page type, DOCTRINE §6) + the JSON-LD
   schema (§9) + the source pack. Capture the `CJ-####` code.

4. **Wait for `needs_review`.** Run `aios_client.py wait-job --code CJ-#### --timeout 900` →
   polls `GET /content/jobs/{code}` until terminal. The worker owns the pipeline transitions;
   never force one.

5. **Pull the rich columns.** Run `aios_client.py fetch-job --code CJ-####` → `GET
   /content/jobs/{code}/qa`, `/draft`, `/schema`, `/keywords`. Read `qa.passed`,
   `qa.weighted_total`, `qa.dimensions`, `qa.blocked_by`; scan `draft` for `[NEEDS: …]`.

6. **Evaluate the gate + hand off.** Apply the Decision points, render the **Output format**,
   STOP for the human. Do NOT approve here.

## Decision points
- If the caller lacks `publish_content` → `POST /content/jobs` 403s → report "requires
  publish_content", STOP.
- If `qa.passed` is **false** (weighted total < 85, or any dim < 70, or `blocked_by` non-empty)
  → **STOP.** Surface the failing dimensions + `blocked_by`. Recommend `review --action edit`.
  NEVER approve.
- If any `[NEEDS: …]` marker is in the draft → **STOP.** The fact is missing; `fact_grounding`
  hard-blocks. A human supplies it (then `edit`). NEVER invent it.
- If `qa.dimensions.information_gain <= 25` → the differentiation angle is absent/ungrounded →
  MISSING → `edit`.
- If `keywords.degraded` is true → label "degraded (SERPER/ANTHROPIC pending)", do not present as
  live, STOP at review.
- If a job holds in `drafting` at `cost == 0` → a spend-stop/cap held the paid step; report the
  hold + honest $0; do not retry-loop.
- If `qa.passed` is **true**, zero `[NEEDS:]`, no degrade, and the caller is a LEAD → present the
  scorecard and state a LEAD MAY approve via `review --code CJ-#### --action approve` (DB
  re-checks the gate, invariant #12).

## Common Pitfalls
- Approving because "the number is close" → the DB gate re-checks and raises `PublishBlocked`;
  route to `edit`.
- Re-implementing a page-type's rubric in the hub instead of routing to its deep skill → the deep
  skill owns the rubric; route to it for `local`/`blog`/titles-meta.
- Filling a `[NEEDS:]` from memory → forbidden; it routes the gap to a human.
- Passing an explicit framework "to be safe" → let `Auto` resolve it per DOCTRINE §6 unless the
  operator explicitly asked for a specific framework.
- Presenting degraded/fake output as live metrics → forbidden; grounding rule.

## Output format
Emit verbatim:

```
CONTENT JOB — <client> · <page_type> · <topic>
Job: <CJ-####>            Status: <status>            Stage: <stage>
QA: <weighted_total>/100  (<PASS|FAIL>)   passed=<true|false>
  Critical dims: fact_grounding=<n> originality=<n> intent_match=<n> eeat_experience=<n> information_gain=<n>
  blocked_by: <list or "none">        Below-70 dims: <list or "none">
Differentiation angle (information_gain=<n>): <present | MISSING -> edit>
[NEEDS:] markers: <list verbatim, or "none">
Schema: <@type> JSON-LD present? <yes/no>            Words: <words>   Cost: $<cost>
Context freshness: <lag=0 fresh | lag=N stale by N events>
Degrade notes: <"none" | "SERPER/ANTHROPIC pending -> research+QA on fake, DO NOT publish">
Deep skill for this page type: </local-service-page | /blog-post | /titles-meta | hub>
Next action (human gate):
  <PASS -> LEAD may approve: aios_client.py review --code CJ-#### --action approve>
  <FAIL/NEEDS/degrade -> aios_client.py review --code CJ-#### --action edit / supply the fact>
```

Rubric enforced (reference, not inlined): `reference/CONTENT-DOCTRINE.md` (all sections; QA
§11). Exact response fields: `reference/output-formats.md`. Page-type rubric detail lives in the
deep skills.
