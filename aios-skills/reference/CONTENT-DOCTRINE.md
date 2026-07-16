# Content Doctrine (Part 7 / Module 02 · Content)

The **single source of truth** for what a ranking-grade page is on this platform.
It is a 2026-SOTA, people-first, grounded-generation standard. Every content
service cites it: the generator (`app/services/content_generator.py`) encodes its
numeric rules as constants that name this doc; the QA gate (a later chunk) scores
a draft against §11 (the 14 QA dimensions); the operator skills reference it when
briefing a job.

**Governing principle: helpful content for people, assembled from verifiable
truth — never invented.** A draft may state only what the per-client
**source-of-truth pack** or the **fresh 6B client context** provides. Where a
needed fact is absent, the generator inserts a literal `[NEEDS: …]` placeholder
rather than hallucinate. This is not a style preference — it is the line between a
trustworthy asset and Google's "scaled content abuse" / "spammy automation"
penalties.

---

## 1. People-first, grounded generation

- Write for the human who searched, then make it machine-extractable — never the
  reverse. Content built primarily to rank ("search-engine-first") is the failure
  mode the whole doctrine defends against.
- **Grounding is mandatory.** Concrete claims (numbers, names, prices, dates,
  addresses, credentials, results) must trace to the **source pack** or **fresh
  context**. The generator records this trace (`grounding`) so QA can audit it and
  a reviewer can spot-check it.
- **No invented facts.** If a section needs a fact that is not supplied, emit
  `[NEEDS: <what is missing>]`. A `[NEEDS:]` marker is a *feature* — it routes the
  gap to a human, and it hard-blocks publish until resolved.
- Prose is the writer LLM's job; **structure, facts, and the trace are the core's
  job.** The deterministic core assembles the skeleton (headings, the answer
  block, entity coverage, links, local anatomy) and feeds the writer only grounded
  facts; the LLM phrases, it does not source.

## 2. E-E-A-T, with **Experience** as the differentiator

Google's quality signal is **E-E-A-T** — Experience, Expertise,
Authoritativeness, Trust. In an era of commodity AI text, **first-hand
Experience** is the scarcest and most defensible signal:

- Surface *first-hand* proof from the source pack: real projects, before/after
  outcomes, photos-taken-on-site, lessons learned, named practitioners.
- Attribute expertise (author/credentials), cite authoritative sources, and make
  trust explicit (guarantees, transparent pricing, verifiable NAP/reviews).
- Every draft carries a dedicated Experience/authority block; a page with zero
  first-hand signal is flagged by QA dimension #4.

## 3. Entity coverage, **not** keyword density

Modern ranking is topical/semantic — cover the **entities and sub-topics** a
complete answer requires, mined from the top-10 teardown, not a keyword quota.

- **Table-stakes entities** (covered by ~all top-10) are the price of entry — the
  draft must cover them.
- **Differentiator entities** (covered by only some) are the opportunity — the
  draft leans into them (see §7).
- **Primary keyword placement** stays natural: front-loaded in the H1, the answer
  block, the meta, and one early heading. Target density **0.5–1.5 %**; hard
  ceiling **2–3 %** (above it reads as stuffing and QA #6 fails). Density is
  `occurrences(primary) / total_words`.
- Use secondary + semantic terms and synonyms for coverage — do not repeat the
  exact primary to hit a number.

## 4. Intent-matched, extractable structure

Match the SERP-derived **intent** and **format** from the research brief, then make
the page extractable for featured snippets **and** AI Overviews:

- **Exactly one `H1`** (the title), then a logical `H2`/`H3` hierarchy.
- A **40–55-word direct answer** immediately under the key heading (the first
  `H2`, phrased as the head question). This is the snippet/AIO extraction target —
  self-contained, no "as mentioned above".
- **Lists, tables, and a Q&A/FAQ block** (built from the brief's PAA + AI-Overview
  fan-out questions) — the formats snippets and AI Overviews lift.
- **Internal links**: pillar→cluster and cluster→pillar from the brief's cluster
  map, plus a **keyword→URL registry** so each target keyword points at one URL
  (the cannibalization guard, upheld from research).
- One primary intent per URL; never split the same intent across two pages.

## 5. Format ↔ framework ↔ page-type

The research brief recommends a **format** from the live SERP (blog / product /
tool / video / local / comparison). The page-type (`service` / `blog` / `local`)
selects the default **copywriting framework** (§6). Honor both: the format sets
the shape (e.g. comparison ⇒ a comparison table is table-stakes), the framework
sets the persuasion arc.

## 6. The 7 frameworks (and when each fits)

| Framework | Moves | Fits |
|-----------|-------|------|
| **AIDA** | Attention · Interest · Desire · Action | Service / landing pages driving one action (**default for `service`**) |
| **PAS** | Problem · Agitate · Solution | Problem-aware informational blogs (**default for `blog`**) |
| **BAB** | Before · After · Bridge | Transformation stories; local service outcomes (**default for `local`**) |
| **FAB** | Features · Advantages · Benefits | Product / comparison pages where specs must convert to value |
| **4 Ps** | Picture · Promise · Prove · Push | Persuasive landing pages needing vivid proof |
| **PASTOR** | Problem · Amplify · Story · Testimonial · Offer · Response | Long-form sales / story-led pages |
| **4 U's** | Useful · Urgent · Unique · Ultra-specific | Punchy, CTA-dense pages and hero sections |

`Auto` resolves via `schemas.content.auto_framework`: `service→AIDA`,
`local→BAB`, `blog→PAS`. An explicit framework always overrides `Auto`.

## 7. The mandatory information-gain / differentiation angle

**Every draft MUST carry one explicit differentiation angle** — the
anti-"scaled-content-abuse" lever. Rehashing the top-10 earns nothing; the page
must add **information gain**. The angle is derived from the top-10 teardown's
**differentiator entities** and grounded in the source pack, in priority order:

1. **Unique data** — proprietary numbers, a study, original benchmarks (source
   pack `unique_data`).
2. **First-hand experience** — a real project / result / on-site proof (source
   pack `proof_points`).
3. **Better format** — a clearer table / calculator / checklist than competitors.
4. **Missed angle** — a differentiator entity the top-10 underserve.

The generator resolves and **exposes** the angle (`differentiation_angle`) so QA
#3 can enforce its presence and provenance. If none of 1–4 can be grounded, the
generator emits `[NEEDS: unique data or first-hand experience …]`.

## 8. White-hat local page anatomy

A `local` page is **not** a spun template with the city swapped. Required blocks:

- **Locale intro** — the service framed for the specific city/area (grounded).
- **Local proof** — real local projects / landmarks / named local clients from the
  source pack (first-hand Experience, §2).
- **Localized FAQ** — the fan-out questions phrased for the locale.
- **NAP** — exact Name / Address / Phone, consistent with the GBP listing; if
  absent ⇒ `[NEEDS: NAP …]`.
- **GBP alignment** note — the page must not contradict the Google Business
  Profile (categories, service area, hours).
- **Per-city uniqueness** — each city page's body must be **≥ 60–70 % unique**
  versus sibling city pages. The generator computes a per-city uniqueness ratio;
  boilerplate-only city pages (proof missing) fail this and emit `[NEEDS: local
  proof for <city>]`.

## 9. Titles, meta, and media

- **Title** ≤ ~60 chars, primary front-loaded, one clear promise.
- **Meta description** ≤ ~155 chars, primary + the differentiation hook + a CTA;
  grounded (no invented claims).
- **Images**: a hero + one per major section, each with descriptive **alt text**
  (accessibility + on-page SEO); the alt is authored by the core and is
  authoritative. Media count aims at the teardown's media target.
- Every page declares the right **schema** (`schemas.content.schema_for`:
  `service→Service`, `local→LocalBusiness`, `blog→Article`).

## 10. Word / section budgets

- Target word count = the teardown's `word_count_target` (match/beat the winners),
  clamped to a **floor of 600** and a **hard ceiling of 3500** words.
- Section prose is hard-bounded (truncated to its token budget) so a runaway
  provider can never blow the budget — the bound is a guarantee, not a hint
  (mirrors the context compactor's `_enforce_budget`).
- Thin content (well under target) is allowed to generate but is flagged by QA so a
  human decides — the generator never pads with filler to hit a number.

## 11. The 14 QA dimensions (consumed by the QA gate)

The QA chunk scores a draft on these; the generator is built so each is
*checkable* (it exposes the trace, angle, structure, and counts the gate needs):

1. **Intent match** — structure/format matches the brief's intent.
2. **Grounding / factual accuracy** — every concrete claim traces to source/context;
   zero unresolved `[NEEDS:]`.
3. **Information gain** — a differentiation angle is present and provenance-backed.
4. **E-E-A-T / Experience** — first-hand experience + expertise + trust signals.
5. **Entity coverage** — all table-stakes entities covered; differentiators leaned into.
6. **Keyword placement & density** — primary in H1/answer/meta/early heading; density
   0.5–1.5 %, never above the 2–3 % ceiling.
7. **Extractable answer block** — 40–55 words, self-contained, under the key heading.
8. **Heading structure** — exactly one H1; logical, non-skipping H2/H3.
9. **Snippet / AI-Overview formatting** — lists/tables/Q&A present where useful.
10. **Internal linking** — pillar↔cluster links; keyword→URL registry respected.
11. **Readability & people-first tone** — plain language, no fluff, scannable.
12. **Meta title & description** — within length, compelling, primary present.
13. **Local anatomy & per-city uniqueness** — local blocks present; ≥ 60–70 % unique.
14. **Originality / anti-scaled-content-abuse** — no duplicated boilerplate; the page
    would be worth publishing even if search did not exist.

---

### How the code consumes this doc

`content_generator.py` encodes §3/§4/§7/§8/§10 as named constants
(`ANSWER_MIN_WORDS`, `ANSWER_MAX_WORDS`, `PRIMARY_DENSITY_TARGET_MAX`,
`PRIMARY_DENSITY_HARD_CEILING`, `WORD_COUNT_FLOOR`, `WORD_COUNT_CEILING`,
`LOCAL_UNIQUE_MIN`, …) and the §6 framework moves + §11 `QA_DIMENSIONS` as tables,
each citing the section here. Change a number here **and** in the constant it
governs — the doc is the source of truth, the constant is its enforcement.
