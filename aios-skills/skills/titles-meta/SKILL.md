---
name: titles-meta
description: Generates or repairs a page's SERP title tag and meta description to spec (title front-loads the primary keyword and stays under ~60 chars; meta under ~155 chars with the primary, a differentiation hook, and a CTA; both grounded, using the 4 U's framework), then returns the title, meta, their character counts, and the relevant QA signals for a human to approve. Use when an operator asks for "titles and meta", "meta descriptions", "title tags", "SERP snippet copy", or wants to fix a thin or too-long title/description for a client's page. Spends metered AI generation budget and creates (or edits) a content job.
argument-hint: "[client] [topic]"
arguments: [client, topic]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Generate Titles and Meta Descriptions

**Purpose.** Produce (or repair) the SERP title tag and meta description for `$client`'s page on
`$topic` to the DOCTRINE §9 spec, using the 4 U's framework, then return the title, meta, their
character counts, and the QA signals to a human at the review gate.

**Who runs it.** A staff user holding `publish_content` creates or edits the job; a LEAD
(owner/admin/manager) approves at the gate and can PATCH the brief. Lacking `publish_content` →
`POST /content/jobs` 403s → report "requires publish_content" and STOP.

## Required inputs / keys
- `$client` — the client name (resolved to a real `client_id`; never invent one).
- `$topic` — the target page's topic / primary keyword (e.g. "AC repair San Jose"). Also name
  the page type if it is not a service page: `service` (default) | `blog` | `local`.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- `SERPER_API_KEY` + `ANTHROPIC_API_KEY` live server-side for real generation + the QA judge.
  Dormant → the pipeline runs on the deterministic fake — REPORT "degraded", do not present fake
  copy as live.

**Trigger.** "Titles and meta", "meta descriptions", "title tags", "SERP snippet copy", or a
request to fix a too-long / thin title or description for a client's page.

## Where the title + meta live (read, do not invent)
- **Title** = the first `# H1` line of the `draft` markdown.
- **Meta description** = `schema.description` on the JSON-LD (`service`/`blog`/`local`).
- Length rules are DOCTRINE §9: title ≤ ~60 chars, meta ≤ ~155 chars. You MAY measure the
  character length of the returned strings — that is counting, not inventing.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client + read fresh context (resolve-client)
- [ ] Step 2: Create the content job for the target page (create-job, framework "4 U's")
- [ ] Step 3: Wait for needs_review (wait-job)
- [ ] Step 4: Pull draft (title), schema (meta), keywords (primary), qa (fetch-job)
- [ ] Step 5: Measure lengths + evaluate the gate; render the pinned output; STOP for the human
```

1. **Resolve the client + fresh context.** Run `aios_client.py resolve-client --client
   "$client"` → `GET /clients` (name match) + `GET /context/client/{id}` + `/health`. Confirm
   `client_id`. Grounds the copy in the client's real facts (no invented claims in the meta,
   DOCTRINE §9).

2. **Create the content job.** Run `aios_client.py create-job --client-id <id> --page-type
   <service|blog|local> --topic "$topic" --framework "4 U's" --target WordPress` → `POST
   /content/jobs`. The `4 U's` framework (Useful, Urgent, Unique, Ultra-specific) is the
   titles/hero copy framework (DOCTRINE §6); pass it explicitly (it overrides `Auto`). Capture
   the `CJ-####` code.
   - REPAIR mode (an existing job whose only fault is the title/meta): hand the title/meta brief
     change to a LEAD to apply via `PATCH /content/jobs/{code}` (LEAD-only; edits the brief, not
     the status), then re-run the pipeline with `aios_client.py review --code CJ-#### --action
     edit`. Do not spin up a fresh job just to reword a snippet.

3. **Wait for `needs_review`.** Run `aios_client.py wait-job --code CJ-#### --timeout 900` →
   polls `GET /content/jobs/{code}` until terminal. Never force a transition. Holds at `drafting`
   with `cost == 0` → spend-stop/cap; report the hold, do not retry-loop.

4. **Pull the title, meta, primary, and QA.** Run `aios_client.py fetch-job --code CJ-####` →
   `GET /content/jobs/{code}/draft` (title = first H1), `/schema` (meta = `description`),
   `/keywords` (`primary`), `/qa`. Note `qa.dimensions.keyword_handling` (primary front-loaded in
   the title) and `qa.dimensions.snippet_extractability`.

5. **Measure + evaluate.** Count the title and meta characters. Confirm the `primary` keyword is
   present and front-loaded in the title and present in the meta. Apply the Decision points,
   render the **Output format**, STOP for the human. Do NOT approve here.

## Decision points
- If the title > 60 chars or the meta > 155 chars → **flag it** (DOCTRINE §9) and route to
  `review --action edit` (or hand the operator a PATCH of the brief) to tighten. Do not silently
  truncate.
- If the `primary` keyword is absent from the title → `keyword_handling` drops (the generator
  penalizes "primary not front-loaded in the title"); flag it and route to `edit`.
- If the meta contains a claim (number/price/guarantee) not in the source pack → that is an
  invented claim; `fact_grounding` hard-blocks. STOP; route the fact to a human. NEVER invent it.
- If the `draft`/`schema` carry a `[NEEDS: …]` marker → **STOP.** A human supplies the fact,
  then `edit`.
- If `qa.passed` is **false** overall → **STOP.** The page (not just the snippet) is
  sub-threshold; surface `qa.blocked_by` and route to `edit`. NEVER approve.
- If `keywords.degraded` is true → label "degraded (SERPER/ANTHROPIC pending)", do not present as
  live, STOP at review.
- If everything is within spec, `qa.passed` is **true**, and the caller is a LEAD → present the
  snippet + state a LEAD MAY approve via `review --code CJ-#### --action approve` (DB re-checks
  the gate, invariant #12).

## Common Pitfalls
- Truncating a 68-char title yourself to "fix" length → forbidden; the copy must be regenerated
  grounded, not chopped mid-phrase. Route to `edit`.
- Writing a punchier meta from imagination → that invents claims; `fact_grounding` hard-blocks.
  Only the backend-grounded meta ships.
- Approving the snippet while `qa.passed` is false → the whole page is gated; the DB raises
  `PublishBlocked`. Route to `edit`.
- Padding the meta to exactly 155 with filler adjectives → the meta must be useful + specific (4
  U's), not stretched. Tighten via `edit`, do not filler-pad.
- Presenting fake-mode copy as live SERP-tested → label degraded.

## Output format
Emit verbatim:

```
TITLES & META — <client> · <topic> (<page_type>)
Job: <CJ-####>            Status: <needs_review|failed|drafting(held)>
Title:  "<title text>"                 (<N> chars; limit ~60 -> <OK|OVER>)
Meta:   "<meta description text>"       (<N> chars; limit ~155 -> <OK|OVER>)
Primary keyword: "<primary>"           front-loaded in title? <yes/no>   in meta? <yes/no>
QA: <weighted_total>/100  (<PASS|FAIL>)   passed=<true|false>
  keyword_handling=<n>  snippet_extractability=<n>  fact_grounding=<n>
  blocked_by: <list or "none">
[NEEDS:] markers: <list verbatim, or "none">
Degrade notes: <"none" | "SERPER/ANTHROPIC pending -> generation+QA on fake, DO NOT publish">
Recommended next action (human gate):
  <in-spec + PASS -> LEAD may approve: aios_client.py review --code CJ-#### --action approve>
  <OVER length / missing primary / NEEDS / FAIL -> aios_client.py review --code CJ-#### --action edit>
```

Rubric enforced (reference, not inlined): `reference/CONTENT-DOCTRINE.md` §9 (titles, meta,
media), §6 (4 U's), §11 (`keyword_handling`, `snippet_extractability`, `fact_grounding`). Exact
response fields: `reference/output-formats.md`.
