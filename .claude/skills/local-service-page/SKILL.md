---
name: local-service-page
description: Generates a ranking-grade LOCAL service page (a city + service landing page) grounded in the client's fresh context, runs the 14-dimension QA gate, and returns the draft, JSON-LD, and QA scorecard for a human to approve. Use when an operator needs a "service in city" page, a "near me" or service-area landing page, or a local page for a client with a physical location or defined service area. Spends metered AI research + generation budget and creates a content job.
argument-hint: "[client] [city] [service]"
arguments: [client, city, service]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Generate a Local Service Page

**Purpose.** Produce a ranking-grade local service page for `$client` targeting `$service` in
`$city`: create the content job, let the pipeline draft and self-QA it, then return the draft,
its JSON-LD, and the QA scorecard to a human at the review gate. The backend does the
generation; this skill orchestrates the call order and enforces the gate.

**Who runs it.** A staff user holding `publish_content` (owner/admin/manager/specialist).
Creating the job needs `publish_content`; approving at the gate is LEAD-only
(owner/admin/manager). If the caller lacks `publish_content`, `POST /content/jobs` returns
403 — report "requires publish_content" and STOP.

## Required inputs / keys
- `$client` — the client name. Resolved to a real `client_id` via the resolve step; the backend
  snapshots the name/color and NEVER accepts a `client_id` you invent.
- `$city` — the target city / service area, exactly as it appears in the client's NAP/GBP.
- `$service` — the service the page sells (e.g. "AC repair", "emergency plumbing").
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN` (the
  skill-token gateway bearer).
- `SERPER_API_KEY` + `ANTHROPIC_API_KEY` must be live server-side for real SERP research +
  generation + the AI QA judge. If either is dormant the pipeline runs on the deterministic
  fake and QA is heuristic-only — REPORT this as "degraded", do not present fake output as live.

**Trigger.** Any request for a "service in city" page, a service-area / near-me landing page,
or a local page for a client with a physical location.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client + read fresh context (resolve-client)
- [ ] Step 2: Create the local content job (create-job, page-type local)
- [ ] Step 3: Wait for the pipeline to reach needs_review (wait-job)
- [ ] Step 4: Pull the QA scorecard + draft + JSON-LD (fetch-job)
- [ ] Step 5: Evaluate the gate; render the pinned output; STOP for the human
```

1. **Resolve the client and pull fresh context.**
   Run `python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py resolve-client --client "$client"`
   → `GET /clients` (matched by name) + `GET /context/client/{id}` + `GET
   /context/client/{id}/health`. Confirm the returned `client_id` and read `health.lag`. This
   grounds the page in the client's real facts (NAP, proof points, unique data) per
   CONTENT-DOCTRINE §1/§2.
   - If `lag > 0` → note "context stale by N events" in the output; the draft may miss recent
     facts, but proceed (the pipeline still grounds against the stored source pack).

2. **Create the local content job.**
   Run `aios_client.py create-job --client-id <id> --page-type local --topic "$service in $city"
   --framework Auto --target WordPress` → `POST /content/jobs`. `Auto` resolves to **BAB** for
   `local` (DOCTRINE §6) and the schema to **LocalBusiness** (§9) server-side. Capture the
   returned `CJ-####` code.
   - Do NOT set the framework/schema yourself — the server resolves them; passing anything but
     `Auto` overrides the doctrine default with no benefit here.

3. **Wait for `needs_review`.**
   Run `aios_client.py wait-job --code CJ-#### --timeout 900` → polls `GET /content/jobs/{code}`
   until `status` is terminal (`needs_review` / `failed` / `rejected` / `done`). The worker owns
   `queued→drafting→needs_review`; this skill never forces a transition.
   - If `status == failed` → surface the failure; STOP (do not re-create blindly).
   - If it times out or holds at `drafting` with `cost == 0` → a spend-stop/cap blocked the paid
     step (honest degrade); report the hold, do not retry-loop to force spend.

4. **Pull the QA scorecard, draft, and JSON-LD.**
   Run `aios_client.py fetch-job --code CJ-####` → `GET /content/jobs/{code}/qa`, `/draft`,
   `/schema`, `/keywords`. Read `qa.passed`, `qa.weighted_total`, the per-dimension scores in
   `qa.dimensions`, `qa.blocked_by`, and scan the `draft` for `[NEEDS: …]` markers. Derive the
   differentiation angle health from `qa.dimensions.information_gain` (see
   `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/output-formats.md` §4).

5. **Evaluate the gate and hand off.** Apply the Decision points. Render the **Output format**
   below. Do NOT call `review approve` in this skill — approval is a deliberate LEAD action.

## Decision points
- If `qa.passed` is **false** → **STOP.** List the failing dimensions verbatim (every dim in
  `qa.dimensions` below 70, plus everything in `qa.blocked_by`). Recommend `review --code
  CJ-#### --action edit` (back to drafting) or hand the specific fixes to the operator. NEVER
  recommend approve.
- If the draft contains any `[NEEDS: …]` marker → **STOP.** That fact (NAP, local proof, unique
  data) is absent from the source pack/context; `fact_grounding` will read ~15 and hard-block. A
  human supplies it (update the client facts, then re-run `edit`). NEVER invent it — invented
  local facts are the "scaled content abuse" failure DOCTRINE §7 defends against.
- If `qa.dimensions.local_relevance` fails or per-city uniqueness is flagged in `qa.notes` → the
  page reads as a spun city-swap template; flag it and route to `edit` for real local proof
  (DOCTRINE §8). Do not approve a boilerplate city page.
- If `qa.dimensions.eeat_experience` is low → the page lacks a real Experience/authority block;
  flag it — this is the local page's scarcest ranking signal (DOCTRINE §2).
- If `qa.dimensions.information_gain <= 25` → the mandatory differentiation angle is absent or
  ungrounded → treat as MISSING → route to `edit`.
- If `keywords.degraded` is true (SERPER/ANTHROPIC dormant) → label the whole result "degraded
  (research/QA on fake); do not publish as live" and STOP at review regardless of score.
- If the caller is a LEAD and `qa.passed` is **true** with zero `[NEEDS:]` and no degrade →
  present the output and state that a LEAD MAY approve via `review --code CJ-#### --action
  approve` (which enqueues publish; the DB re-checks the QA gate and refuses a sub-threshold
  draft — invariant #12).

## Common Pitfalls
- "Weighted total is 82, close enough, approve it." → No. 85 is the hard threshold and every dim
  must clear 70; the DB gate raises `PublishBlocked` on approve anyway. Route to `edit`.
- Filling a `[NEEDS: NAP]` / `[NEEDS: local proof]` yourself from memory → forbidden. The marker
  routes the gap to a human; inventing the fact breaks grounding and tanks `fact_grounding`.
- Setting framework=AIDA/schema manually for a local page → pointless; `local` resolves to BAB +
  LocalBusiness server-side. Pass `framework=Auto`.
- Treating deterministic-fake output as shippable when keys are dormant → label degraded, do not
  publish.
- Re-creating the job to "get a better score" instead of using `edit` → wastes budget and loses
  the review trail. Use `--action edit`.
- Calling `approve` from this skill because the score passed → approval is a LEAD's manual
  decision; this skill stops at presenting the scorecard.

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
LOCAL SERVICE PAGE — <client> · <service> in <city>
Job: <CJ-####>            Status: <needs_review|failed|drafting(held)>
QA: <weighted_total>/100  (<PASS|FAIL>)   passed=<true|false>
  Local relevance (#local_relevance): <score>   E-E-A-T/Experience (#eeat_experience): <score>
  Critical dims: fact_grounding=<n> originality=<n> intent_match=<n> eeat_experience=<n> information_gain=<n>
  blocked_by: <list or "none">        Below-70 dims: <list or "none">
Differentiation angle (information_gain=<n>): <present | MISSING -> edit>
[NEEDS:] markers: <list each verbatim, or "none">
Schema: LocalBusiness JSON-LD present? <yes/no>
Context freshness: <lag=0 fresh | lag=N stale by N events>
Degrade notes: <"none" | "SERPER/ANTHROPIC pending -> research+QA on fake, DO NOT publish">
Recommended next action (human gate):
  <PASS -> LEAD may approve via: aios_client.py review --code CJ-#### --action approve>
  <FAIL/NEEDS/degrade -> send to edit / supply the missing fact, then re-run>
Draft (first 40 words of the answer block): "<...>"
```

Rubric enforced (reference, not inlined): `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/CONTENT-DOCTRINE.md` §2 (E-E-A-T), §7
(differentiation angle), §8 (local anatomy + per-city uniqueness), §11 (14 QA dimensions).
Exact response fields: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/output-formats.md`.
