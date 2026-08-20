---
name: client-snapshot
description: Builds a one-page client health brief - the client profile, its living AI context (summary plus folded facts), the context freshness signal, and the platform rollup - so an operator instantly knows what the platform knows about a client. Use when the operator says "snapshot", "brief me on this client", "what do we know about", "client health", or "give me the one-pager". Read-only. Grounds strictly in what the backend returned and labels any stale or degraded context honestly.
argument-hint: "[client]"
arguments: [client]
model: opus
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# One-Page Client Snapshot

**Purpose.** Give the operator a single grounded read on a client: who they are, what the platform's living context knows (summary + folded facts), how fresh that context is (lag / stale), and where they sit in the platform rollup. Read-only. The judgement is synthesizing real rows into a crisp brief; it invents no fact the backend did not return.

**Who runs it.** Any provisioned staff. The client profile (`GET /clients/{id}`) needs a signed-in staff user; the context reads (`GET /context/client/{id}` and `.../health`) need `view_reports` (all six staff roles hold it). A portal client is 403'd off this staff surface.

## Required inputs / keys
- `$client` - the client name or id. Resolve the name to a client `id` in Step 1.
- `AIOS_API_BASE` (default `http://localhost:8000/api/v1`) and `AIOS_TOKEN` (EdDSA bearer, any staff).
- The shared client `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py`; shared wiring in `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
- The context provider keys (Anthropic / Voyage / Pinecone) are deferred. When dormant, the context module runs on deterministic fakes: the `summary` may be a fake/degraded string and `status` may be `pending`/`degraded`. The freshness fields (`lag`, `stale`, `event_watermark`, `latest_seq`) stay honest either way. Label a degraded/fake summary explicitly; never present it as a live AI summary.

**Trigger.** A request for a client one-pager, health brief, or "what do we know about this client".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve + read the client profile (GET /clients, GET /clients/{id})
- [ ] Step 2: Read the living context: summary + facts (GET /context/client/{id})
- [ ] Step 3: Read the context freshness signal (GET /context/client/{id}/health)
- [ ] Step 4: Read the platform rollup for standing (GET /command-center)
- [ ] Step 5: Synthesize the one-pager; label freshness + any degrade
```

1. **Resolve the client.**
   Run `aios_client.py get /clients` and match `$client` to a client `id`, then `aios_client.py get /clients/{id}` for the profile (name, tier, status, site count).

2. **Read the living context.**
   Run `aios_client.py get /context/client/{id}`. Capture `summary`, `facts` (last-writer-wins keyed facts), `version`, `status`. Add `--query query=...` only if a focused retrieval is asked (returns ranked `chunks`).

3. **Read freshness.**
   Run `aios_client.py get /context/client/{id}/health`. Capture `lag`, `stale`, `event_watermark`, `latest_seq`, `status`. `lag = latest_seq - event_watermark` = events not yet folded in.

4. **Read the rollup.**
   Run `aios_client.py get /command-center` and pull this client's `clients` progress row (latest audit type + score) and the `spend` snapshot for standing.

5. **Synthesize.** Emit the **Output format** grounding every line in a fetched field. Do not add facts the context did not carry.

## Decision points
- If `stale` is true or `lag > 0` -> label the snapshot "context stale by N events; may miss recent activity". Still deliver it, but flag the lag prominently.
- If `status` is `degraded`/`error`/`pending` (or the provider keys are dormant) -> the summary is a deterministic fake or a held fold. Label it "context degraded/fake (AI keys pending)"; report the facts/freshness but do not quote the summary as a live AI read.
- If `$client` resolves to no client -> report "no client on file"; route to a human, do not fabricate a profile.
- If a fact the operator asks for is absent from `facts`/`summary` -> say "not in context"; route it to a human. Never fill it from memory.
- If the operator needs a client-facing narrative or report -> route to `/monthly-report`; this snapshot is an internal brief.

## Common Pitfalls
- Filling a missing fact (NAP, contact, contract detail) from memory -> forbidden. A gap is reported as "not in context" and routed to a human.
- Quoting a degraded/fake summary as a live AI summary -> label the degrade; the freshness fields tell you the true state.
- Ignoring `lag` and presenting stale context as current -> always surface `stale`/`lag`.
- Reading the Command Center `traffic` as live traffic -> it is an audit-derived placeholder; use the `clients` progress row (real audit score) instead.
- Treating `facts` values as editable here -> this skill is read-only; context is folded from the activity log by the backend.

## Output format
Emit verbatim:

```
CLIENT SNAPSHOT - <client>
Profile: tier=<tier>  status=<active|...>  sites=<count>
Standing (rollup): latest audit=<type> score=<0-100>   spend flag=<near/over cap? or none>
Context freshness: <FRESH (lag=0) | STALE by <lag> events>   status=<summarized|pending|degraded|error>  v<version>
Living summary: <summary>   <"[DEGRADED/FAKE - AI keys pending]" if applicable>
Key facts:
  <fact-key>: <value>
  ...  (or "none folded yet")
Gaps (routed to a human): <asked-for facts absent from context, or "none">
Next: <internal only | client-facing report -> /monthly-report>
```

Rubric enforced (reference, not inlined): the Context module freshness invariant (backend invariant #11 - `event_watermark >= latest_seq` when caught up; `lag = latest_seq - event_watermark`). Shared wiring + the degrade contract: `${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/`.
