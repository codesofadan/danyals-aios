# Output Formats — the content skills' shared contract

Table of contents
1. The content-job response (the 15-key `ContentJob`)
2. The four rich reviewer columns (`qa` / `draft` / `keywords` / `schema`)
3. The QA scorecard fields + the pass rule (the gate every skill enforces)
4. Where the title, meta, and differentiation angle come from
5. Degrade + spend-hold signals
6. Shared pinned-output conventions

This doc pins the **exact fields the backend returns** so every content skill's pinned
output uses real values, never invented ones. It mirrors `backend/app/routers/content.py`,
`backend/app/schemas/content.py`, and `backend/app/services/content_qa.py`. If the backend
response model changes, update this doc AND the skills that cite it (contract-lock discipline).

---

## 1. The content-job response (the 15-key `ContentJob`)

`GET|POST /api/v1/content/jobs*` return exactly these camelCase keys (nothing else):

```
id        the PUBLIC job code "CJ-####" (never the UUID)
client    snapshotted client display name       color   snapshotted hex
pageType  service | blog | local                topic   the brief line
framework AIDA|PAS|BAB|FAB|4 Ps|PASTOR|4 U's     auto    bool (was framework Auto-resolved?)
target    WordPress | PDF/Markdown               status  queued|drafting|needs_review|
cost      USD spent so far (float)                       publishing|done|failed|rejected
words     draft word count (int)                 schema  the JSON-LD @type string
images    planned/authored image count           stage   human-readable stage label
ago       relative time ("2h ago")
```

`client_id`, the UUID, and the rich pipeline columns are NEVER in this shape — pull the rich
columns from their own endpoints (§2).

---

## 2. The four rich reviewer columns

`GET /api/v1/content/jobs/{code}/{column}` for `column ∈ {qa, draft, keywords, schema}`
returns `{"id": "CJ-####", "<column>": <payload>}`. An unknown column 404s.

- `draft`   → the full draft **markdown** string (`draft_md`). The H1 is the page title.
- `keywords`→ the `keyword_map`: `{primary, secondary[], semantic_entities[], questions[],
  intent, intent_confidence, content_format{recommended,confidence}, fanout[], cluster{...},
  winnability{...}, low_confidence, degraded, notes}`.
- `schema`  → the assembled **JSON-LD** object. For `service`/`blog` its `description` field is
  the meta description; `@type` is Service / Article / LocalBusiness.
- `qa`      → the QA scorecard (§3).

There is NO endpoint for the `outline` column, so the differentiation angle is not fetched
directly — derive it (§4).

---

## 3. The QA scorecard fields + the pass rule

`qa` (the payload of `.../{code}/qa`) is:

```
dimensions      { <dim>: 0-100, ... }  the 14 named dimensions, canonical order below
weighted_total  0-100 integer          the PROVISIONAL (R4) weighted roll-up
passed          bool                    the publish verdict
blocked_by      [ <dim>, ... ]          critical dims that hard-blocked publish
provisional     true                    thresholds/weights calibrated later (P7A-10)
notes           [ "<dim>: <reason>", ... ]  every deduction, for the reviewer
```

The 14 dimension keys, in canonical §11 order:
`intent_match, eeat_experience, entity_coverage, keyword_handling, structure_readability,
snippet_extractability, originality, fact_grounding, local_relevance, schema_validity,
internal_linking, cta_ux, information_gain, serp_format_fit`.

**The pass rule (read `passed` — do not recompute, but know what it means):**
`passed == true` **iff** every dimension ≥ 70 (`MIN_DIMENSION_SCORE`) AND `weighted_total`
≥ 85 (`WEIGHTED_TOTAL_THRESHOLD`) AND no **critical** dimension fell below 70.

The five **critical / hard-gate** dimensions (below 70 they block publish regardless of the
total, and appear in `blocked_by`):
`fact_grounding, originality, intent_match, eeat_experience, information_gain`.

A skill NEVER approves a draft with `passed == false`. The DB re-checks this gate on approve
and raises `PublishBlocked` on a sub-threshold draft (backend invariant #12) — so "close
enough" is not a thing.

---

## 4. Where the title, meta, and differentiation angle come from

- **Title** = the first `# H1` line of the `draft` markdown.
- **Meta description** = `schema.description` on the JSON-LD (`service`/`blog`/`local`).
  Length rules are Doctrine §9 (title ≤ ~60 chars, meta ≤ ~155). A skill MAY measure the
  length of the returned strings (that is counting, not inventing).
- **Differentiation angle** (Doctrine §7) is not exposed on its own endpoint. Read its health
  from `qa.dimensions.information_gain`:
  - `information_gain <= 25` → the angle is **absent or ungrounded** (`_ANGLE_MISSING_CAP`) →
    treat as MISSING → route to `edit`.
  - `information_gain >= 70` → a grounded, substantive angle is present.
  The angle statement itself appears woven into the `draft` prose; quote it from there, do not
  fabricate one.

---

## 5. Degrade + spend-hold signals

- **Dormant provider key** (Serper/Anthropic): `keywords.degraded == true` and/or
  `keywords.low_confidence == true` mean research/QA ran on the deterministic fake. Label the
  whole result "degraded (SERPER/ANTHROPIC pending)" and do NOT present it as live. The QA
  judge dimensions fall back to conservative proxies (still a real score, just heuristic).
- **Spend hold**: a job that stalls in `drafting` with `cost == 0` was blocked by the
  money-dial / cap / daily spend-stop. Report the hold + honest $0; do not retry-loop.

---

## 6. Shared pinned-output conventions

Every content skill ends with a fenced block a human reads at the gate. Keep the shape
comparable across skills:

```
<SKILL LABEL> — <client> · <topic/target>
Job: <CJ-####>            Status: <status>
QA: <weighted_total>/100  (<PASS|FAIL>)     passed=<true|false>
  Critical dims: fact_grounding=<n> originality=<n> intent_match=<n> eeat_experience=<n> information_gain=<n>
  blocked_by: <list or "none">
  Below-70 dims: <list or "none">
Differentiation angle (QA information_gain=<n>): <present | MISSING -> edit>
[NEEDS:] markers in draft: <list verbatim, or "none">
Schema: <@type> JSON-LD present? <yes/no>
Context freshness: <lag=0 fresh | lag=N stale by N events>
Degrade notes: <"none" | "SERPER/ANTHROPIC pending -> research+QA on fake, DO NOT publish">
Next action (human gate): <PASS -> LEAD may approve via /content review approve
                           FAIL/NEEDS/degrade -> send to edit / supply the missing fact>
```

Values are copied from the endpoints in §1–§4. Never fill a field from memory; a field with no
backing value is written as `unknown` or `[NEEDS: …]`, never guessed.
