# Content Doctrine — CANONICAL SOURCE MOVED

> **Authority transfer (2026-07-24).** This document is **no longer the source of
> truth** for what a ranking-grade page is. The single canonical spine is now the
> **SEO-CONTENT-OS knowledge base**, committed in-repo at:
>
> ```
> backend/seo-content-os/knowledge/
> ```
>
> The content module is being migrated to run on those `.md` rules (operator
> decision, 2026-07-24). This file remains only as a **code ↔ knowledge cross-map**
> so an engineer can trace each enforced constant back to the doctrine passage it
> implements. Where the code and the knowledge disagree, **the knowledge wins** —
> the code is being brought into line, not the other way around.

## The canonical spine (read these, in order)

| Layer | File(s) under `backend/seo-content-os/knowledge/` |
|---|---|
| Governance / laws | `doctrine/seo-system-doctrine.md`, `doctrine/seo-system-spine.md` |
| Google compliance | `doctrine/google-compliance-spine.md` (33 hard rules) |
| Local content laws | `doctrine/local-content-laws.md` (Laws 15–20) |
| AI-search / GEO | `doctrine/ai-search-reality-2026.md`, `doctrine/llms-txt-verdict.md` |
| Penalty casebook | `doctrine/penalty-casebook.md` |
| Quality gates | `quality-gates/` — the PLAN + G0–G13 fail-fast gate stack |
| Editorial scorecard | `lifecycle/editorial-scorecard.md` — 6 categories, 3-fail kill gate |
| Frameworks | `frameworks/` — PAS/PASTOR, AIDA/4 Ps, StoryBrand SB7, Cialdini, value-equation, … |
| Passage / meta protocol | `foundations/passage-block-protocol.md`, `foundations/meta-and-headings.md` |
| Voice | `voice/` — brand-voice model + AI-tell blocklist |
| Playbooks | `playbooks/` — per page-type deep method (location, service, service-city, homepage, about, service-area, …) |

The non-negotiables carried verbatim from the spine (enforced today): **no
AI-detector evasion** (doctrine Law 8), **cite-or-do-not-claim** (grounding is
mandatory; absent facts emit a literal `[NEEDS: …]` marker, never a hallucination),
and **no em dash (U+2014)** in generated copy (enforced by
`app/services/content_guard.py` + `tests/test_content_guard.py`).

## Code ↔ knowledge cross-map (what the code enforces, and its source)

The generator (`app/services/content_generator.py`) and the QA gate
(`app/services/content_qa.py`) enforce a **named numeric subset** of the spine. The
publish gate is load-bearing: `workers/tasks/content.py` blocks any draft whose
`QaScore.passed` is not `True` (invariant #12). The migration keeps that contract
(`QaScore.passed` / `.blocked_by`) stable while re-deriving the thresholds from the
knowledge base.

| Code constant (content_generator.py) | Enforces (knowledge source) | Status |
|---|---|---|
| `ANSWER_MIN_WORDS` / `ANSWER_MAX_WORDS` | passage-block opener band — `foundations/passage-block-protocol.md` | re-deriving (opener 60–120; each H2 a 120–220-word block) |
| `PRIMARY_DENSITY_*` | anti-stuffing gate G5 — `quality-gates/` + Law 17 (no density gaming) | re-deriving (drop target band, keep anti-stuffing signal) |
| `WORD_COUNT_FLOOR` / `CEILING` | per-passage budgets, not a global page floor/ceiling | re-deriving |
| `LOCAL_UNIQUE_MIN` | strip-the-city + external-verifiability tests — `local-content-laws.md` (Law 15/16) | re-deriving (~0.50 majority heuristic, non-safe-harbor) |
| `MAX_INTERNAL_SPOKES` | G7 internal-link presence (2–4 contextual) | re-deriving |
| `TITLE_MAX_CHARS` = 60 / `META_MAX_CHARS` | `foundations/meta-and-headings.md` (~50–60 title / ~160 meta) | title kept; meta → ~160 |
| `MAX_COVERAGE_ENTITIES` | coverage is a floor to clear, never an auto-fail — Law 15 | kept |
| `DIFFERENTIATION_KINDS` | information-gain angle — Law 15 (first-party fact = durable divergence) | kept |
| QA: 14 weighted dims, `weighted_total ≥ 85` | the PLAN + G0–G13 fail-fast gate stack + the 6-category editorial kill gate (≥3 fails = block) | **replacing model** — see migration note below |
| Frameworks enum (AIDA/PAS/BAB/FAB/4 Ps/PASTOR/4 U's) | `frameworks/` library + pain-level→spine selection | wire-enum kept this pass; internal taxonomy layered (see note) |
| Page types (service/blog/local/gbp_post) | playbooks (location / service-city / service-area / homepage / about / …) | wire-enum kept this pass; internal split layered (see note) |

## Migration note (why this is staged, not a big-bang rewrite)

Two facts constrain the order of work:

1. **The QA object changes shape.** SEO-CONTENT-OS is a fail-fast gate stack
   (auto-fail / warning per gate) plus a fail-count kill gate — not a weighted
   0–100 score with a single ≥85 threshold. The migration preserves
   `QaScore.passed` + `.blocked_by` (the only fields the publish gate reads) and
   keeps a `dimensions` / `weighted_total` compatibility projection so the DB
   `qa_score` jsonb and the portal readers keep working, while the *decision* is
   re-derived from the gates.
2. **Page-type and framework strings are wire enums** locked front↔back by
   `tests/test_contract_lock.py` (`frontend/lib/content.ts` ↔
   `app/schemas/content.py`). Expanding them (adding StoryBrand, splitting `local`
   into location / service-city / service-area, dropping `blog`) is a **coordinated
   frontend + backend contract change**, done as its own versioned step — not a
   backend-only edit. Until then the richer SEO-CONTENT-OS taxonomy is layered
   *internally* behind the stable wire enums.

Everything an operator or agent should treat as authoritative lives under
`backend/seo-content-os/knowledge/`. This file is a map, not the territory.
