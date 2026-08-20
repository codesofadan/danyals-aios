---
name: keyword-research
description: Researches keywords for a client from a seed term, saves them to the keyword bank with volume, difficulty, intent, and clusters, and reports cannibalization conflicts. Use when an operator wants keyword research, a keyword list or bank, keyword ideas from a seed, search volume or difficulty for terms, keyword clusters or a pillar map, an intent breakdown, or wants to know which pages compete for the same term. Research SPENDS metered provider budget; a cost-gate block is silent, so the result must always be verified by re-reading the bank.
argument-hint: "[client] [seed]"
arguments: [client, seed]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py:*), Read
---

# Research Keywords for a Client

**Purpose.** Turn `$seed` into a grounded keyword set for `$client`: queue the paid research,
verify what actually landed, then report volume, difficulty, intent, clusters, and
cannibalization conflicts using only the fields the backend returns.

**Who runs it.** Reading needs `view_reports`. Research, saving keywords, and PATCHing one need
the `run_research` module permission (owner/admin/manager). Every route needs the
`keyword_research` feature grant. Lacking either → 403 → report which one and STOP.

## Required inputs / keys
- `$client` — the client name, resolved to a real `client_id`. Never invent an id.
- `$seed` — the seed term (1-200 chars) research fans out from.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- The keyword-data provider must be live server-side for real volume/difficulty/CPC. Dormant or
  cost-gate-blocked → the worker skips the pull and **saves nothing**. There is **no `degraded`
  flag on this module's wire** — the only honest way to know is to compare the bank before and
  after (Step 4). REPORT "nothing landed", never present an empty result as "no keywords found".

**Trigger.** Keyword research, a keyword list / bank, ideas from a seed, volume or difficulty for
terms, keyword clusters / a pillar map, an intent breakdown, "which pages compete for this term".

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client (resolve-client)
- [ ] Step 2: Read the bank BEFORE (the baseline count)
- [ ] Step 3: Queue the research (202 = enqueued, nothing more)
- [ ] Step 4: Re-read the bank; compare to the baseline to see what actually landed
- [ ] Step 5: Read clusters + cannibalization; render the pinned output
```

1. **Resolve the client.** Run `python ${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/aios_client.py
   resolve-client --client "$client"` → `GET /clients` (name match). Capture `client_id`.

2. **Read the baseline.** Run `aios_client.py get "/keyword-research/stats"` →
   `GET /keyword-research/stats` and record `saved`. This is the ONLY way to detect a silent
   cost-gate block later.

3. **Queue the research.** Run `aios_client.py post /keyword-research/research --json
   '{"seed":"$seed","clientId":"<id>"}'` → `POST /keyword-research/research`. It returns **202**
   `{seed, queued: true}` **unconditionally** — this says the job was enqueued and **nothing
   about spend or success**. The cost gate runs later, in the worker.

4. **Verify what landed.** Re-read `aios_client.py get "/keyword-research/stats"` →
   `GET /keyword-research/stats` and `aios_client.py get "/keyword-research/keywords?clientId=<id>&limit=200"`
   → `GET /keyword-research/keywords`. If `saved` did not move, the research pulled nothing —
   a cost-gate block, a dormant provider, or a seed with no fan-out. Report that plainly.
   To save keywords by hand instead: `aios_client.py post /keyword-research/keywords --json
   '{"clientId":"<id>","keywords":["…"]}'` → `POST /keyword-research/keywords`.

5. **Read clusters and conflicts.** Run `aios_client.py get "/keyword-research/clusters?clientId=<id>"`
   → `GET /keyword-research/clusters` and `aios_client.py get "/keyword-research/cannibalization?clientId=<id>"`
   → `GET /keyword-research/cannibalization`. To correct one keyword's intent or target:
   `aios_client.py patch /keyword-research/keywords/<code> --json '{"intent":"Commercial"}'` →
   `PATCH /keyword-research/keywords/{code}`. Render the **Output format**.

## Decision points
- If `stats.saved` is unchanged after the research → **the run landed nothing.** Say so:
  "research returned no saved keywords (cost-gate block, dormant provider, or no fan-out)". Do
  **NOT** re-queue to force it — a gate block is a money decision, and re-queuing either burns
  budget or repeats the same no-op. Do **NOT** report an unchanged bank as a completed research.
- If the client exits **2** with `status: 404` → the `clientId` is unknown or invisible under RLS.
  Re-resolve; never pass an id the resolve step did not return.
- If `winnable` is true → report it as a **neutral-DA screen, not a per-client verdict.** The
  research task does not pass the client's DA, so every keyword with difficulty <= 45 reads
  `winnable: true` regardless of which client it is for. Saying "winnable for <client>" claims a
  judgement the backend never made.
- If `difficulty` is quoted → it is the **raw provider KD (0-100)**, not adjusted for the client's
  authority. Do not describe it as "winnability-aware".
- If `intent` is `""` → the intent is unset or unrecognized. Report "unset", not a guess. The
  stored provenance (`intent_source`) is **not on the wire** — never claim a keyword's intent came
  from the provider, a SERP heuristic, or an LLM; the API does not tell you.
- If a cannibalization conflict is returned → two or more keywords with **different intents**
  point at one `targetUrl`. Report the conflict and the URL; the fix (split or consolidate the
  page) is a human's call.
- If the exit code is **3** (transport) or **5** (no token / no matching client) → report it; never
  present a partial read as the client's keyword picture.

## Common Pitfalls
- "The research returned 202 `queued: true`, so it worked." → The 202 only means enqueued. The
  gate, the provider call, and any block all happen afterwards in the worker and are invisible to
  the caller. Verify by re-reading the bank.
- "The gate blocked it, I'll retry." → A block is the money-dial working. Retrying either forces
  spend the operator did not authorize or repeats the same no-op. Report the hold.
- "`winnable: true` means <client> can rank for this." → It means KD <= a neutral DA of 30 plus a
  15-point stretch. The client's real DA is never passed. Say "neutral-DA screen".
- Reporting an empty bank as "no keywords match this seed" → an empty result is far more likely a
  gate block or a dormant provider. Distinguish them by whether `saved` moved.
- Pinning `intentSource`, `intentConfidence`, `metricsConfidence`, or a `degraded` flag → **none
  of these exist on this module's wire.** They are DB-only or belong to a different module.
- Reporting the `tags` you just PATCHed back to the operator from the response → `tags` is
  writable but is **not in `KeywordResponse`**. It will not be there.
- Treating `opportunity` as a traffic or revenue estimate → it is a backend-computed score. Report
  the number, do not translate it into clicks or dollars.

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
KEYWORD RESEARCH — <client> · seed "<seed>"
Bank: <saved before> -> <saved after>   (<landed N | NOTHING LANDED>)
Clusters: <clusters>   Avg difficulty: <avgDifficulty>

Keywords (volume · difficulty=raw provider KD · winnable=neutral-DA screen, not per-client):
  <keyword>  vol=<volume>  KD=<difficulty>  cpc=<cpc>  intent=<intent|unset>  cluster=<cluster>
             opportunity=<opportunity>  winnable=<winnable>  geo=<geo>  target=<targetUrl|none>
  ...

Clusters:
  <name>  pillar="<pillar>"  intent=<intent>  size=<size>  volume=<volume>  KD=<avgDifficulty>
  ...

Cannibalization conflicts (same URL, different intents):
  <targetUrl>  intents=<intents>  keywords=<keywords>
  ...
  <or "none">

Research outcome: <N keywords saved | NOTHING LANDED - cost-gate block, dormant provider, or no
  fan-out. Not re-queued: a gate block is a money decision for the operator.>
Not available from this API (do not infer): intent provenance (intent_source), per-client DA
  winnability, any degrade/confidence flag.
```

Exact response fields + the winnable / intent_source / silent-block rules:
`${CLAUDE_PROJECT_DIR}/.claude/skills/_shared/reference/part8-output-formats.md` §2.
