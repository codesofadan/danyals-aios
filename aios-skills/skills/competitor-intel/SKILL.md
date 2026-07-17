---
name: competitor-intel
description: Analyzes a client's tracked competitors and reports keyword gaps, keyword overlap, and an estimated share of voice. Use when an operator asks who the competitors are, wants a competitor or rival analysis, a keyword gap report, "what do they rank for that we don't", share of voice or visibility, or wants to add, discover, or stop tracking a competitor. Discovery and analysis SPEND metered provider budget. Share of voice is a modelled estimate, and the backlink-gap data is not ingested yet.
argument-hint: "[client] [competitor-domain]"
arguments: [client, competitor]
model: opus
disable-model-invocation: true
allowed-tools: Bash(python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py:*), Read
---

# Analyze Competitors and Keyword Gaps

**Purpose.** Report `$client`'s competitive position honestly: who is tracked, which keywords are
real gaps, how the measured share of voice estimates out, and which parts of the picture the
backend cannot yet supply.

**Who runs it.** Reading needs `view_reports`. Adding, discovering, analyzing, promoting a gap,
patching, and deleting need the `run_research` module permission (owner/admin/manager). Every
route needs the `competitor_intel` feature grant. Lacking either → 403 → report which one and STOP.

## Required inputs / keys
- `$client` — the client name, resolved to a real `client_id`. Never invent an id.
- `$competitor` — a competitor domain (for add), or omitted for a report.
- `AIOS_BASE_URL` (default `http://localhost:8000/api/v1`) and `AIOS_SKILL_TOKEN`.
- The SERP provider must be live server-side for real discovery and gap analysis. Dormant or
  cost-gate-blocked → the worker skips the pull; the 202 still reads `queued: true` and its
  `reason` is **always `""`**. Verify by re-reading `analyzed` on the competitor.
- Share of voice needs **no provider call** and costs nothing. It is computed from stored
  positions against a modelled CTR curve.

**Trigger.** "Who are our competitors", a competitor / rival analysis, a keyword gap report, "what
do they rank for that we don't", share of voice / visibility, adding or untracking a competitor.

## Steps
Copy this checklist and check items off as you go:

```
- [ ] Step 1: Resolve the client (resolve-client)
- [ ] Step 2: Read the tracked competitors + stats
- [ ] Step 3: Add or discover, if asked (both SPEND)
- [ ] Step 4: Analyze, then re-read `analyzed` to confirm it actually ran
- [ ] Step 5: Read gaps + share of voice; render the pinned output
```

1. **Resolve the client.** Run `python ${CLAUDE_PLUGIN_ROOT}/scripts/aios_client.py
   resolve-client --client "$client"` → `GET /clients` (name match). Capture `client_id`.

2. **Read the board.** Run `aios_client.py get "/competitor-intel/competitors?clientId=<id>&tracked=true"`
   → `GET /competitor-intel/competitors` and `aios_client.py get "/competitor-intel/stats?clientId=<id>"`
   → `GET /competitor-intel/stats`. Fields: `reference/part8-output-formats.md` §3.

3. **Add or discover, only if asked.** Add: `aios_client.py post /competitor-intel/competitors
   --json '{"clientId":"<id>","domain":"$competitor"}'` → `POST /competitor-intel/competitors`
   (201). Discover: `aios_client.py post /competitor-intel/discover --json '{"clientId":"<id>"}'`
   → `POST /competitor-intel/discover` (202; rate-limited; needs tracked keywords to fan out from).

4. **Analyze, then confirm it ran.** Run `aios_client.py post /competitor-intel/competitors/<code>/analyze`
   → `POST /competitor-intel/competitors/{code}/analyze` (202, rate-limited). Re-read the
   competitor and check `analyzed` moved off `"never"` / advanced. The 202's `reason` is always
   empty, so it can never tell you a worker skipped.

5. **Read gaps and share of voice.** Run `aios_client.py get "/competitor-intel/competitors/<code>/gaps"`
   → `GET /competitor-intel/competitors/{code}/gaps` and `aios_client.py get
   "/competitor-intel/share-of-voice?clientId=<id>"` → `GET /competitor-intel/share-of-voice`
   (`clientId` REQUIRED). Promote a gap into the keyword bank on request: `aios_client.py post
   /competitor-intel/competitors/<code>/gaps/<gap_id>/promote` → `POST
   /competitor-intel/competitors/{code}/gaps/{gap_id}/promote`. Render the **Output format**.

## Decision points
- If `clientPosition` is **null** → this is a **PURE gap: the client does not rank for the term at
  all.** It is **NOT position 0**. Reading it as 0 would rank a term the client has never touched
  ahead of a #1 they own outright, inverting the whole board. `gapType` already encodes it:
  `untapped` (null + high volume) or `missing` (null). Report "does not rank".
- If `GET /competitor-intel/competitors/{code}/backlink-gaps` returns an **empty array** →
  **the data is not ingested.** Say exactly that: "competitor backlink data is not ingested yet,
  so this is empty by construction, not a finding." Nothing populates competitor-side backlink
  rows (pulling a rival's profile is a paid call the platform does not yet buy). **NEVER** report
  it as "no backlink gaps found" — that presents a missing pipeline as a clean bill of health.
- If share of voice is reported → **label it an ESTIMATE, always.** `provisional: true` rides
  every response. It is a modelled CTR curve (echoed back as `curve`), not measured traffic, and
  the denominator is **only the client plus their TRACKED competitors** — share of the voice we
  measure, not of the whole internet. Untracked rivals are invisible to it.
- To identify the client's own row in `entries` → use **`isClient`**. On the client's row,
  `domain` is the **client's NAME**, not a domain, so a domain string-match silently fails.
- If `analyzed` reads `"never"` → the competitor has never been analyzed; its `keywordGaps`,
  `overlap`, and `shareOfVoice` are stale zeros, not findings. Analyze first or say so.
- If the operator wants to retire a rival → **PATCH `{"tracked": false}`** (`aios_client.py patch
  /competitor-intel/competitors/<code> --json '{"tracked":false}'` → `PATCH
  /competitor-intel/competitors/{code}`) is the supported way; it parks the rival and keeps the
  history. `DELETE /competitor-intel/competitors/{code}` exists but destroys the row, and the
  shared client has **no `delete` verb** — so parking is the path this skill takes.
- If a PATCH sets nothing (or `{"label": null}`) → **400 "No fields to update"**. Send a real change.
- If the client exits **2** with `status: 409` on an add → the domain is already tracked for this
  client. Read it instead of re-adding.

## Common Pitfalls
- "`clientPosition` is null, so they're at position 0 / unranked-but-close." → Null means the
  client does not rank at all. Never coerce it to 0; never imply proximity.
- "backlink-gaps came back empty — good news, no gaps." → The endpoint is structurally empty
  because nothing ingests competitor backlinks. Emptiness here is a **missing data source**, not a
  finding. Report the gap in the pipeline.
- Presenting share of voice as measured traffic or market share → it is an estimate off a modelled
  CTR curve over a denominator of tracked competitors only. Say "estimated", cite `provisional`.
- Matching the client's SoV row by domain string → on that row `domain` holds the client's NAME.
  Use `isClient`.
- "The analyze returned `queued: true`, so gaps are fresh." → `reason` is always `""` and the work
  happens in the worker. Confirm via `analyzed`.
- Reporting `overlap` as "% of their keywords we share" → it is a Jaccard overlap of the two sets.
  Report the number as-is.
- Quoting `CompetitorStats.shareOfVoice` alongside the SoV endpoint's numbers and calling out a
  discrepancy → they are computed differently on purpose (the stats tile floors a remainder).
  Report one or the other, not a false contradiction.
- Inventing `lastAnalyzedAt` → there is no timestamp on the wire, only the relative `analyzed`
  string (literally `"never"` when un-analyzed).

## Output format
Emit verbatim (values copied from the endpoints; never from memory):

```
COMPETITOR INTEL — <client>
Tracked: <tracked>   Keyword gaps: <keywordGaps>   Share of voice: <shareOfVoice>% (ESTIMATE, provisional=<provisional>)

Competitors:
  [<code>] <domain> "<label>"  source=<manual|serp_auto>  tracked=<tracked>
           overlap=<overlap>%  gaps=<keywordGaps>  common=<commonKeywords>  SoV=<shareOfVoice>%  analyzed=<analyzed>
  ...

Keyword gaps — <code> (clientPosition=null means the client DOES NOT RANK, not position 0):
  <keyword>  vol=<volume>  KD=<difficulty>  intent=<intent|unset>
             them=#<competitorPosition|unranked>  us=<#clientPosition | DOES NOT RANK>
             type=<missing|weak|shared|untapped>  opportunity=<opportunity>  promoted=<promoted>
  ...

Share of voice (ESTIMATE — modelled CTR curve, denominator = client + TRACKED competitors only):
  curve used: <curve>
  <label> (<isClient ? "CLIENT" : "rival">)  visibility=<visibility>  share=<share>%
  ...

Backlink gaps: <"NOT INGESTED - competitor-side backlink rows are never populated, so this
  endpoint is empty by construction. This is a missing data source, NOT a finding of zero gaps."
  | list rows if ever non-empty: refDomain / competitors / authority / spam>

Action taken: <read-only | added <domain> | discovery queued | analyze queued | gap promoted | untracked>
Degrade notes: <"none" | "analyze/discover queued but `analyzed` did not move -> the worker skipped
  (gate block or dormant provider); the 202's reason is always empty and cannot tell us">
```

Exact response fields + the null-gap / SoV-estimate / empty-backlink rules:
`reference/part8-output-formats.md` §3.
