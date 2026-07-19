---
name: citation-submit
description: Sets up a client's canonical NAP (a business profile) and dispatches a real citation-SUBMISSION campaign across the directory catalog — the direct-API, aggregator, and self-hosted Playwright-bot engines actually CREATE new listings, as opposed to /citation-builder, which only reconciles an existing monitoring board. Use when an operator says "submit citations", "build citations for <client>", "run a citation campaign", "get this client listed on directories", "citation automation", or "list <client> on <market> directories". Dispatching a campaign is a LEAD-only write with a real (if small, ~1c/directory) per-row spend across potentially dozens of directories at once.
argument-hint: "[client] [market] [tier]"
arguments: [client, market, tier]
model: sonnet
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Submit Citations (Real Directory Submission)

**Purpose.** Get `$client` an actual, new NAP listing across the citation-directory catalog — via a direct API (Bing Places / Foursquare), an aggregator push (Data Axle), or the self-hosted Playwright bot (bot_fillable / captcha_assisted directories) — not just reconcile a monitoring board. This is the skill that DOES the work `/citation-builder` assumes already happened out-of-band.

**Who runs it.** Every write (`business-profiles`, `campaigns`) is LEAD-only (owner/admin/manager). A non-lead call 403s - report "requires a LEAD", STOP. Reading the catalog/profiles needs `view_reports`.

## Required inputs / keys
- `$client` - the client id (`clientId`). Snapshotted server-side; an unknown/invisible client 404s.
- The canonical NAP (business name, address, phone, website, hours, categories) MUST come from the client's real record. If a business profile does not already exist for this client, gather the NAP from a human or the client's own site/GBP listing before creating one - NEVER invent a name/address/phone. A wrong NAP submitted to dozens of directories is far worse than a delayed campaign.
- `$market` - optional filter: `US`, `UK`, `CA`, `AU`, or `GLOBAL` (default: the business profile's own market + `GLOBAL`).
- `$tier` - optional filter: `aggregator`, `api`, `bot_fillable`, `captcha_assisted` (default: all four - `manual_only` NEVER queues, there is no worker path for it).
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer).
- Dispatch spends real (if small) money per directory through the `citations` money-dial (cost-gated: dial -> client cap -> daily spend-stop). It defaults to `byhand` - review the estimate before queuing a large batch.

**Trigger.** "Submit citations / build citations / citation campaign / get listed on directories / citation automation".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Check for an existing business profile (GET /citation-builder/business-profiles?clientId=)
- [ ] Step 2: If none exists, confirm the canonical NAP with a human, then create one
- [ ] Step 3: Preview the directory catalog for the requested market/tier (GET /citation-builder/directories)
- [ ] Step 4: STOP - present the plan (directory count, tiers, estimated cost) for a LEAD's go
- [ ] Step 5: On explicit LEAD go -> dispatch the campaign (POST /citation-builder/campaigns)
- [ ] Step 6: Report queued/alreadyQueued/skippedManualOnly; point to /offpage/citations for live progress
```

1. **Check for a business profile.** Run `aios_client.py get /citation-builder/business-profiles?clientId=<id>`. If one exists, use its id. If several, prefer the one marked `isPrimary`.
2. **No profile yet -> get the real NAP first.** Do NOT invent business_name/address/phone. Ask the operator, or read it from the client's own site/GBP if already grounded elsewhere in context. Then `aios_client.py post /citation-builder/business-profiles --json '{"clientId":"<id>","businessName":"<name>","addressLine1":"<addr>","city":"<city>","region":"<state>","postalCode":"<zip>","market":"<US|UK|CA|AU>","phone":"<phone>","websiteUrl":"<url>"}'`.
3. **Preview the catalog.** Run `aios_client.py get /citation-builder/directories?market=<m>&tier=<t>` (repeat `market=`/`tier=` for multiple values) to see what will be targeted - note the tier mix (direct API vs bot-fillable vs CAPTCHA-assisted) and that `manual_only` rows are never included.
4. **STOP for the LEAD.** Present: directory count by tier, the markets covered, and the R5 cost estimate the dispatch call will report (roughly directory-count × $0.005-0.01). Do NOT dispatch without explicit confirmation - a campaign can queue dozens of directories and each spends, however small.
5. **Dispatch on confirmation.** `aios_client.py post /citation-builder/campaigns --json '{"clientId":"<id>","businessProfileId":"<bp-id>","markets":["<market>",...],"tiers":["<tier>",...]}'` (omit `markets`/`tiers` for the defaults). Returns `{queued, alreadyQueued, skippedManualOnly, estimatedCost, citationIds}` immediately - the actual submissions run asynchronously per row afterward.
6. **Report and point to progress.** Each queued row cost-gates + submits independently; check `aios_client.py get /offpage/citations?clientId=<id>` afterward (poll, do not block) for `submitStatus` (`queued -> submitting -> submitted|verified|failed|blocked`) and `proofUrl` (a screenshot/receipt once a Playwright submit completes).

## Decision points
- If the caller is not a LEAD -> `business-profiles`/`campaigns` 403s -> report "requires a LEAD", STOP.
- If no business profile exists and the NAP is unknown -> STOP; route to a human. NEVER invent a name/address/phone.
- If the operator has not confirmed the plan -> STOP at step 4; never dispatch on your own.
- If a spend-stop/cap blocks a row -> that row lands `blocked` (never a guess); report the hold, do not retry-loop to force spend.
- If `skippedManualOnly > 0` -> that is expected and correct (BBB, FindLaw, Psychology Today, etc. have no automatable path) - do not attempt to route those anywhere.
- If a directory's engine is unconfigured (e.g. no CAPTCHA-solver key, no Playwright installed, no vault credential for a direct API) -> that row lands `blocked` with an honest reason; report it, do not claim it succeeded.
- If `alreadyQueued > 0` -> those directories are already in flight or done for this client from a prior campaign; the dispatch never double-queues one.

## Common Pitfalls
- Inventing a business address/phone to "just get started" -> forbidden; a wrong NAP submitted to dozens of directories compounds the mistake dozens of times over. STOP and get the real record.
- Dispatching without presenting the cost estimate first -> a campaign can span 50+ directories; the LEAD reviews the batch, not just approves a vague "sure, go".
- Reading `submitted` as `verified` -> `submitted` means the engine reported success; `verified` means it was independently re-confirmed live. Report the actual status, not an upgraded one.
- Treating `blocked` as a crash -> it is the honest, expected outcome for an unconfigured engine or a spend-stop; distinguish it from `failed` (the engine tried and errored) when reporting.
- Re-running the same campaign repeatedly "to be sure" -> `alreadyQueued` exists precisely so a re-dispatch is a safe no-op, not a duplicate-submission risk; do not manually re-queue a directory that is already in flight.

## Output format
Emit verbatim:

```
CITATION SUBMIT - <client>
Business profile: <label> - <businessName>, <city> (<market>)  [<existing|newly created>]
Catalog preview: <n> directories  (api <n> · aggregator <n> · bot_fillable <n> · captcha_assisted <n> · manual_only skipped <n>)
Estimated cost: $<estimatedCost>
Dispatch decision (LEAD only): <"awaiting LEAD" | "DISPATCHED - <n> queued / <n> already in flight">
Progress (poll /offpage/citations): <"not yet dispatched" | "check submitStatus per directory">
Next: <LEAD confirms the plan | poll for submitStatus | add a vault credential for a blocked direct-API engine>
```

Rubric enforced (reference, not inlined): `danyals-audit-system/checklists/local.yaml` and the Team D SOP `danyals-audit-system/.claude/agents/local/d2-citations-nap.md` (LOC-011..020: citation audit, consistency, NAP exactness, aggregators). Shared depth in `${CLAUDE_PLUGIN_ROOT}/reference/`.
