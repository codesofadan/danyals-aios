---
name: blog-post
description: Generates a ranking-grade informational BLOG post grounded in the client's fresh context, with entity coverage, a 40-55 word extractable answer block, and a Q&A/FAQ, then runs the 14-dimension QA gate and returns the draft, JSON-LD, and QA scorecard for a human to approve. Use when an operator says "write a blog / an article / a post on topic", needs informational or how-to / guide content, or wants a top-of-funnel piece for a client. Spends metered AI research + generation budget and creates a content job.
argument-hint: "[client] [topic]"
arguments: [client, topic]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Generate a Blog Post

**Purpose.** Produce a ranking-grade informational blog for `$client` on `$topic`: create the
content job, let the pipeline draft and self-QA it (PAS framework by default, entity coverage,
an extractable answer block, and a Q&A/FAQ), then return the draft, its JSON-LD, and the QA
scorecard to a human at the review gate.

**Who runs it.** A staff user holding `publish_content`. Creating the job needs
`publish_content`; approving is LEAD-only (owner/admin/manager). Lacking `publish_content` →
`POST /content/jobs` 403s → report "requires publish_content" and STOP.

## Required inputs / keys
- `$client` — the client name (resolved to a real `client_id`; never invent one).
- `$topic` — the article topic / head question (e.g. "how tankless water heaters save money").
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- `SERPER_API_KEY` + `ANTHROPIC_API_KEY` live server-side for real SERP research + generation +
  the QA judge. Dormant → the pipeline runs on the deterministic fake and QA is heuristic-only —
  REPORT "degraded", do not present fake output as live.

**Trigger.** "Write a blog / article / post on topic", informational / how-to / guide content, a
top-of-funnel piece for a client.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client + read fresh context (resolve-client)
- [ ] Step 2: Create the blog content job (create-job, page-type blog)
- [ ] Step 3: Wait for needs_review (wait-job)
- [ ] Step 4: Pull QA + draft + keywords + schema (fetch-job)
- [ ] Step 5: Evaluate the gate; render the pinned output; STOP for the human
```

1. **Resolve the client + fresh context.** Run `aios_client.py resolve-client --client
   "$client"` → `GET /clients` (name match) + `GET /context/client/{id}` + `/health`. Confirm
   `client_id`, read `health.lag`. Grounds the article in the client's real facts (DOCTRINE
   §1/§2).
   - If `lag > 0` → note "context stale by N events"; proceed (pipeline grounds on the stored
     source pack).

2. **Create the blog content job.** Run `aios_client.py create-job --client-id <id> --page-type
   blog --topic "$topic" --framework Auto --target WordPress` → `POST /content/jobs`. `Auto`
   resolves to **PAS** for `blog` (DOCTRINE §6) and the schema to **Article** (§9) server-side.
   Capture the `CJ-####` code.
   - Do NOT set the framework/schema yourself unless the operator explicitly asks for a specific
     framework; let `Auto` apply the doctrine default.

3. **Wait for `needs_review`.** Run `aios_client.py wait-job --code CJ-#### --timeout 900` →
   polls `GET /content/jobs/{code}` until terminal. The worker owns
   `queued→drafting→needs_review`; never force a transition.
   - `failed` → surface the failure; STOP. Holds at `drafting` with `cost == 0` → spend-stop/cap
     held the paid step; report the hold, do not retry-loop.

4. **Pull QA + draft + keywords + schema.** Run `aios_client.py fetch-job --code CJ-####` → `GET
   /content/jobs/{code}/qa`, `/draft`, `/keywords`, `/schema`. Read `qa.passed`,
   `qa.weighted_total`, `qa.dimensions` (especially `entity_coverage`, `snippet_extractability`,
   `intent_match`, `information_gain`), `qa.blocked_by`; scan `draft` for `[NEEDS: …]`. Derive
   the angle health from `qa.dimensions.information_gain` (`reference/output-formats.md` §4).

5. **Evaluate the gate + hand off.** Apply the Decision points, render the **Output format**,
   STOP for the human. Do NOT approve here.

## Decision points
- If `qa.passed` is **false** → **STOP.** List every dim below 70 + `qa.blocked_by`. Recommend
  `review --code CJ-#### --action edit`. NEVER approve.
- If any `[NEEDS: …]` marker is in the draft → **STOP.** The fact is missing; `fact_grounding`
  hard-blocks. A human supplies it (then `edit`). NEVER invent it.
- If `qa.dimensions.entity_coverage` is low → the article misses table-stakes entities the top-10
  cover (DOCTRINE §3); flag the missing entities from `qa.notes` and route to `edit`.
- If `qa.dimensions.snippet_extractability` is low → the 40-55 word answer block / lists / Q&A
  are weak (DOCTRINE §4); flag it — this is the featured-snippet + AI-Overview extraction target.
- If `qa.dimensions.information_gain <= 25` → the differentiation angle is absent/ungrounded →
  MISSING → `edit` (rehashing the top-10 earns nothing, DOCTRINE §7).
- If `keywords.degraded` is true → label "degraded (SERPER/ANTHROPIC pending)", do not present as
  live, STOP at review regardless of score.
- If `qa.passed` is **true**, zero `[NEEDS:]`, no degrade, and the caller is a LEAD → present the
  scorecard and state a LEAD MAY approve via `review --code CJ-#### --action approve` (DB
  re-checks the gate, invariant #12).

## Common Pitfalls
- "Weighted total is 83, ship it." → No. 85 is the threshold and every dim must clear 70; the DB
  gate raises `PublishBlocked` on approve. Route to `edit`.
- Padding the draft to hit a word count → the generator never pads and thin content is flagged,
  not filled; route thin drafts to `edit` with a real angle, do not add filler.
- Filling a `[NEEDS:]` fact from memory → forbidden; it routes the gap to a human.
- Forcing an exact-match keyword everywhere to "help ranking" → stuffing tanks `keyword_handling`
  above the density ceiling (DOCTRINE §3). Trust the generator's placement.
- Presenting deterministic-fake output as a live-researched draft → label degraded, do not
  publish.

## Output format
Emit verbatim:

```
BLOG POST — <client> · <topic>
Job: <CJ-####>            Status: <needs_review|failed|drafting(held)>
QA: <weighted_total>/100  (<PASS|FAIL>)   passed=<true|false>
  Entity coverage (#entity_coverage): <score>   Snippet (#snippet_extractability): <score>
  Critical dims: fact_grounding=<n> originality=<n> intent_match=<n> eeat_experience=<n> information_gain=<n>
  blocked_by: <list or "none">        Below-70 dims: <list or "none">
Differentiation angle (information_gain=<n>): <present | MISSING -> edit>
[NEEDS:] markers: <list each verbatim, or "none">
Schema: Article JSON-LD present? <yes/no>            Words: <words>
Context freshness: <lag=0 fresh | lag=N stale by N events>
Degrade notes: <"none" | "SERPER/ANTHROPIC pending -> research+QA on fake, DO NOT publish">
Recommended next action (human gate):
  <PASS -> LEAD may approve: aios_client.py review --code CJ-#### --action approve>
  <FAIL/NEEDS/degrade -> send to edit / supply the missing fact, then re-run>
Draft (first 40 words of the answer block): "<...>"
```

Rubric enforced (reference, not inlined): `reference/CONTENT-DOCTRINE.md` §3 (entity coverage),
§4 (extractable structure), §6 (PAS), §11 (14 QA dimensions). Exact response fields:
`reference/output-formats.md`.
