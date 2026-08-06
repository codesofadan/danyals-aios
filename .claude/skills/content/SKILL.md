---
name: content
description: The Content module hub for Danyal AIOS. Creates any content job (service, blog, or local page), recommends a research-first page SET for a site and bulk-generates the picks, extracts a target site's DESIGN profile so a published page matches it, reads the content board + KPIs, pulls a job's draft/keywords/QA/schema, and runs the human review gate. Use when an operator says "write content", "make a page", "write an article/blog", "create a service or local page", "research pages / recommend a page set", "bulk-generate pages", "match the site's design", "check the content board", "what's awaiting review", or "review/approve/reject a draft" for a client. Routes to the deep skill for the page type. Research, bulk generation, and site-design each spend metered AI budget (content dials); approving is a LEAD action.
argument-hint: "[client] [page-type] [topic]"
arguments: [client, page_type, topic]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
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

## Research-first bulk flow (recommend a page set, then generate the picks)
When the operator wants a WHOLE SET of pages for a site (not one topic) - "research pages",
"recommend a page set", "bulk-generate service/location pages" - use this flow. It spends
per recommended-and-selected page; run it deliberately, never fan out the full set on your own.

Copy this checklist and check items off as you go:

```
- [ ] Step R1: (optional) Extract the target site design (POST /content/site-design)
- [ ] Step R2: Recommend a page set (POST /content/research)
- [ ] Step R3: STOP - the operator selects which items to build
- [ ] Step R4: Resolve the client id + gather >=1 real proof point (shared grounding)
- [ ] Step R5: Bulk-generate the picks (POST /content/research/generate)
- [ ] Step R6: For each CJ-#### -> wait/fetch/review through the normal gate
```

R1. **Extract the site design (optional but recommended).** Run `aios_client.py post
   /content/site-design --json '{"site":"https://example.com","maxPages":5}'`. Read
   `status`, `profile` (`palette`, `typography`, `layout.section_order`, `components`,
   `notes`), `reason`. If `status=='degraded'` the `profile` is null (ANTHROPIC dormant /
   dial-blocked / analysis failed) - report it and proceed WITHOUT a design match. Keep a
   good `profile` to attach as `designProfile` in R5 so the published page matches the site.

R2. **Recommend a page set.** Run `aios_client.py post /content/research --json
   '{"site":"https://example.com","contentType":"service","count":10}'`. `contentType` is
   one of `service` | `location` | `service_location` | `service_area` | `blog` | `faq`.
   Read `status`, `items` (each: `title`, `pageType`, `primaryKeyword`, `secondaryKeywords`,
   `estVolume`, `difficulty`, `rationale`, `city`, `service`), `reason`. If
   `status=='degraded'` the research ran on the deterministic fallback (keyless / dial-blocked
   / failed) - label it and do NOT present the set as live SERP-grounded.

R3. **STOP - the operator selects.** Present the items (title / pageType / primaryKeyword /
   estVolume / difficulty / rationale). The operator picks which to build; each pick spends.
   Never auto-select the whole set.

R4. **Resolve the client + shared grounding.** Run `aios_client.py resolve-client --client
   "$client"` for the real `client_id`. Gather at least one REAL first-hand `proofPoints`
   value shared across every job - without it every fanned-out job hard-fails the QA publish
   gate (`fact_grounding` / `eeat_experience`, DOCTRINE §2/§7). Never invent it.

R5. **Bulk-generate the picks.** Run `aios_client.py post /content/research/generate --json
   '{"clientId":"<id>","items":[<the selected items verbatim>],"proofPoints":["<real proof>"],
   "designProfile":<the R1 profile, or omit>}'`. Each item's `title` becomes the job topic and
   its `pageType` maps to the generator's page type; `framework` defaults `Auto`, `target`
   `WordPress`, and the grounding + design profile are shared across every job. Returns
   `{jobs:["CJ-####", ...]}` - one code per fanned-out job.

R6. **Drive each job through the one gate.** For each `CJ-####` run `wait-job` then
   `fetch-job` and apply the SAME Decision points + QA gate as a single job, STOP for the
   human on each. The bulk call only CREATES the jobs; each still passes the one human review
   gate before publish. Emit the **Research/bulk output** then the per-job **Output format**.

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
   **Always pass first-hand grounding** — repeatable `--proof "<real project/result/credential>"`
   (at least one), plus optional `--testimonial`, `--unique-data`, `--service`. Without a proof
   point the QA publish gate (`fact_grounding` / `eeat_experience`, DOCTRINE §2/§7) HARD-BLOCKS the
   job: it generates but can never pass review. Gather the proof from the client's context (step 2)
   or ask the operator; never invent it.

4. **Wait for `needs_review`.** Run `aios_client.py wait-job --code CJ-#### --timeout 900` →
   polls `GET /content/jobs/{code}` until terminal. The worker owns the pipeline transitions;
   never force one.

5. **Pull the rich columns.** Run `aios_client.py fetch-job --code CJ-####` → `GET
   /content/jobs/{code}/qa`, `/draft`, `/schema`, `/keywords`. Read `qa.passed`,
   `qa.weighted_total`, `qa.dimensions`, `qa.blocked_by`; scan `draft` for `[NEEDS: …]`.

6. **Evaluate the gate + hand off.** Apply the Decision points, render the **Output format**,
   STOP for the human. Do NOT approve here.

## Decision points
- If the caller lacks `publish_content` → `POST /content/jobs`, `POST /content/research`,
  `POST /content/research/generate`, and `POST /content/site-design` all 403 → report
  "requires publish_content", STOP.
- If `contentType` is not one of the six (service / location / service_location /
  service_area / blog / faq) → reject as an invalid content type; do not guess.
- If `POST /content/site-design` returns `status=='degraded'` (`profile` null) → proceed
  WITHOUT a design match and report the degrade; never present a null profile as a match.
- If `POST /content/research` returns `status=='degraded'` → the set is the deterministic
  fallback; label it, do NOT present as live SERP research.
- If the operator says "generate all" without picking → confirm the count first (each page
  spends under the content dial); do not silently fan out the whole set.
- If no real `proofPoints` is available for the bulk fan-out → STOP; every job will hard-fail
  the QA gate (`fact_grounding`). Route the `[NEEDS:]` to a human; never invent a proof.
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
- Bulk-generating the entire recommended set without the operator selecting → each page
  spends; present the set and confirm the picks first.
- Omitting `proofPoints` on the bulk `research/generate` call → every fanned-out job
  hard-fails the publish gate; pass ≥1 real proof shared across the fan-out.
- Presenting a degraded research set as live SERP research, or a null design profile as a
  match → forbidden; report the degrade honestly.
- Approving a bulk-created job without its OWN gate check → each `CJ-####` passes the QA
  §11 gate individually; the bulk call only created them.
- Re-implementing a page-type's rubric in the hub instead of routing to its deep skill → the deep
  skill owns the rubric; route to it for `local`/`blog`/titles-meta.
- Filling a `[NEEDS:]` from memory → forbidden; it routes the gap to a human.
- Passing an explicit framework "to be safe" → let `Auto` resolve it per DOCTRINE §6 unless the
  operator explicitly asked for a specific framework.
- Presenting degraded/fake output as live metrics → forbidden; grounding rule.

## Research/bulk output
Emit verbatim after the research-first flow (then the per-job Output format for each job):

```
CONTENT RESEARCH — <site> · <contentType>
Status: <ok | degraded>   (degraded → deterministic fallback, NOT live SERP)
Recommended pages (<n>):
  1. <title>  [<pageType>]  kw:<primaryKeyword>  vol~<estVolume>  diff:<difficulty>
     Why: <rationale>
  2. ...
Site design: <matched (profile extracted) | none | degraded (profile null)>
Selected to build: <k>/<n>  (operator-picked; each spends)
Shared grounding: <"≥1 real proofPoint confirmed" | "[NEEDS: proof] → human, STOP">
Bulk jobs queued: <CJ-####, CJ-####, ...>  (each still passes the human review gate)
Next: for each job → wait-job → fetch-job → QA gate → LEAD review
```

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

Rubric enforced (reference, not inlined): `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/CONTENT-DOCTRINE.md` (all sections; QA
§11). Exact response fields: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/output-formats.md`. Page-type rubric detail lives in the
deep skills.
