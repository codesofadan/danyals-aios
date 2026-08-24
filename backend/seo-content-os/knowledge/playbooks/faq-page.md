# The Standalone FAQ / Q&A Page: The SEO-CONTENT-OS Build Playbook

Leaf-artifact writing spec for `/write-faq-page`. A writer handed this file plus one real client brand profile and a real question corpus (the actual questions the client's customers ask) can produce a standalone FAQ / Q&A page that answers real local questions, gets its answers lifted into AI Overviews and assistant answers, feeds trust and internal-link equity to the money pages, and never degrades into keyword-padded doorway filler.

This is the **standalone** FAQ page: a dedicated URL whose whole job is a corpus of real questions and extractable answers. It is not the FAQ *section* that sits at the bottom of a location or service-city page (that block is owned by each conversion playbook, e.g. `location-page.md` 4.10). Build a standalone FAQ page when the client has a body of real cross-cutting questions worth their own destination, or a topic Q&A hub that would bloat a conversion page if inlined.

Sibling playbooks, do not confuse:
- The six conversion page types (`location-page.md`, `service-city-page.md`, `service-page.md`, `service-area-page.md`, `homepage.md`, `about-team-page.md`) each carry their own inline FAQ block. This page is the standalone hub, not a replacement for those blocks.
- `local-asset.md` - the linkable asset (cost guide, data study, best-of, neighborhood guide). An FAQ page answers many questions shallowly-to-medium; an asset goes deep on one with original data.

Foundation files this playbook executes:
- `knowledge/foundations/passage-block-protocol.md` - **the core dependency.** Every Q&A pair is a passage block: question-form header, answer-first, self-contained, locally specific. Read it first; this playbook applies it to a page made entirely of blocks.
- `knowledge/doctrine/ai-search-reality-2026.md` and doctrine Law 13 (optimize for the answer) - the FAQ page is the most extraction-native page type; each answer is engineered to be lifted and cited.
- `knowledge/foundations/internal-linking.md` - answers link to the money pages they touch, routing intent to conversion.

Governing law: `seo-system-doctrine.md` Law 8, plus:
- **Law 13 / passage-block protocol** is the primary discipline: the page is a stack of extractable answers.
- **Law 17 (add statistics, citations, operator quotes; never stuff)**: real answers with real specifics get cited; keyword-padded pseudo-questions are the one tested tactic that *reduced* generative citation (~-10%, Princeton/Georgia Tech GEO study, KDD 2024; directional, single study, re-verify).
- **Law 15 (information gain)**: an FAQ that answers the bland consensus question with the bland consensus answer earns no citation. The local specific in each answer is the residual.

Every quantitative figure here is directional and carries a source and a verify flag. Re-open the primary before quoting to a client.

---

## 1. Purpose: the one job, and when to build a standalone FAQ page

### 1.1 The one job

A standalone FAQ page is one page doing three jobs:

1. **Win AI-answer citations** for the real questions local buyers ask, where the answer engine owns the SERP. This is the most extraction-native page type in the system: each Q&A is already the shape an answer engine wants (a question, then a direct answer). Whitespark found AI Overviews on 92% of informational and 97% of hybrid local queries (whitespark.ca/blog/case-study-the-prevalence-of-ai-overviews-in-local-search/, read 2026-07-20; verify), and Perplexity cited direct business sites 73% of the time (backlinko.com/location-pages, read 2026-07-20; verify). A well-built FAQ page is a citation surface for both.
2. **Kill objections and build trust** by answering, in the client's real voice, the real reasons a local buyer hesitates (cost, timing, licensing, process, guarantees, local logistics).
3. **Route intent to the money pages** by linking each answer to the conversion page it touches (`internal-linking.md`).

The one job, compressed: **be the definitive, extractable answer set for the real questions this business's local customers actually ask.** A page of invented questions the business wishes people asked, padded with keywords, fails all three jobs and risks a scaled-content classification.

### 1.2 When to build a standalone FAQ page (and when not)

Build one when:
- The client has a **real corpus of recurring questions** (from sales calls, the phone, GBP Q&A, reviews, support) that is larger than any single conversion page's inline FAQ can carry, or spans multiple services/cities.
- The questions have **genuine informational demand** the conversion pages do not fully serve, and answering them well earns citations and trust.
- Each answer can be made **locally specific and real** from `brand.yaml`, the SME interview, or cited research.

Do **not** build one when:
- The questions are invented to hold keywords ("What is the best plumber in [city]? We are the best plumber in [city]."). This is the exact pattern RicketyRoo names as a spam tell (ricketyroo.com/blog/location-page-spam; verify) and the GEO study found keyword-stuffing reduces citation.
- The real home for these questions is the inline FAQ block of a specific conversion page (then put them there, per that page's playbook, and skip the standalone page).
- The client cannot supply real answers, forcing fabrication (G10 fail).

### 1.3 The standalone-vs-inline decision

| Signal | Inline FAQ block (on a conversion page) | Standalone FAQ page (this playbook) |
|---|---|---|
| Question scope | Specific to one page's city/service | Cross-cutting: many services, many cities, or brand-wide |
| Corpus size | 5-8 questions that fit the page | 15+ real questions warranting a destination |
| Primary intent | Objection-kill on a converting page | A citable answer hub + trust surface |
| Risk | Low | Higher: a standalone Q&A page is a doorway/scaled-content risk if padded |

If the questions are city/service-specific and few, they belong inline. Build the standalone page only when a real corpus justifies its own URL.

---

## 2. The local-question sourcing method (the un-inventable input)

The single thing that separates a real FAQ page from a keyword-padded one is that **the questions are real**. Never invent the question set. Source it, in the RESEARCH and SME steps, before drafting a word.

1. **The client's own inbound questions (highest value).** The questions the phone, the sales calls, the quote requests, and the support inbox actually receive. The SME interview must extract these verbatim: "What do customers ask you before they book? What do they get wrong? What surprises them about price, timing, or process?" These are the un-inventable, un-scrapeable questions, and they are the moat.
2. **GBP Q&A and review mining.** The client's Google Business Profile Q&A and their reviews (their own reviews, via the Business Profile Performance API, which they own) surface real questions and real recurring concerns. Do not scrape third-party review text (Places API is capped at 5 and ToS-restricted, per `location-page.md` 4.6); use owned sources.
3. **People Also Ask and autocomplete (verbatim).** Pull the real PAA questions and autocomplete suggestions for the client's service + city in the RESEARCH step. Record them verbatim in `research.md`; these are the questions searchers actually type and the ones answer engines are answering.
4. **The competitor gap.** What do competitors' FAQ pages conspicuously fail to answer (usually: anything with a real local specific)? The unanswered real question is the citation opportunity (Law 15).

The rule: **every question on the page is a real question a real local customer asks, sourced from one of the above, never invented to carry a keyword.** A question with no real local audience is cut. This is the FAQ-page equivalent of the location page's truthful-source rule.

---

## 3. Answer design: every Q&A is a passage block

This is the heart of the page. Each Q&A pair is a passage block (`passage-block-protocol.md`), tuned tighter because the FAQ format is already question-and-answer native.

**The anatomy of one FAQ answer:**

1. **Question header phrased as the real query.** Use the words the customer actually says: "How much does drain cleaning cost in Tempe?" not "Drain Cleaning Pricing Information". Question-form headers get extracted far more often than noun labels. Mark each as a real heading (H2 or H3), not buried in an accordion that hides the text from parsers.
2. **Answer-first, in the first 1-2 sentences.** The direct answer, with a specific local fact, leads. "A standard drain cleaning in Tempe runs $150 to $350 depending on access and severity, and we quote a flat price before we start." Not "There are several factors that affect drain cleaning cost." The lead sentence is what an AI Overview lifts verbatim.
3. **One or two sentences of supporting specific.** The real driver, the real local condition, the real process detail. One idea, concrete anchor (a number, a code, a neighborhood, a timeline).
4. **Length: 40 to 150 words per answer** (`passage-block-protocol.md`). Long enough to carry context for confident attribution, short enough not to get truncated. The whole FAQ page can run long because it is many small blocks; each block stays tight.
5. **Local specificity is mandatory.** An answer that could have been written for any city fails, even if it reads cleanly. The Tempe price, the Maricopa County permit step, the hard-water driver: the local specific is the residual that earns the citation (Law 15).
6. **Self-contained close.** The last sentence is a standalone-citable line (a specific recommendation or fact), not a transition or a sales CTA inside the answer body.
7. **Facts from the client, never the model.** Every price, timeline, permit rule, and credential traces to `brand.yaml`, the SME interview, or cited research. A fabricated answer on a page built to be cited is actively harmful, because an engine will repeat it (G10 fail; Law 20).

**Grouping and structure of the page as a whole:**

- **Cluster questions by topic** (pricing, timing, process, coverage, licensing/trust, guarantees), each cluster under a section header, so a human scans and a parser segments cleanly.
- **Order by real frequency and commercial intent:** the questions customers ask most and closest to hiring go first.
- **A short page-intro block** (2-4 sentences) states whose questions these are and anchors the entity, then the clusters follow. No long preamble; the value is the answers.
- **Link each answer to the money page it touches** with a descriptive anchor ("our same-day drain cleaning in Tempe"), so the FAQ routes intent to conversion (`internal-linking.md`). Do not stuff every answer with links; link where a real next step exists.

---

## 4. The FAQPage schema caveat (cite this to every client)

Ship `FAQPage` JSON-LD, but **do not expect rich-result stars or expandable SERP FAQ dropdowns for a local business.** The honest, current state:

- In **August 2023**, Google restricted FAQ rich results to **authoritative government and health (well-known, authoritative) websites**, removing FAQ rich results for the vast majority of sites (Google Search Central announcement, Aug 2023; also documented in `location-page.md` 4.10 and `schema-library.md`; re-verify before quoting to a client). For a local service business, the visible FAQ dropdown in the SERP is gone.
- **The JSON-LD is still worth shipping** for a different reason: it is **machine-readable structured data** that helps parsers and answer engines segment the questions and answers cleanly, and it is cheap to emit. It aids passage-level extraction even though it renders no visible rich result. Frame it to the client as parsing/AI-extraction support, never as "this gets you FAQ stars in Google."
- **The `mainEntity` must mirror the visible on-page Q&A text verbatim.** Schema that disagrees with the visible page is worse than no schema (a truthfulness and eligibility fail). The questions and answers in JSON-LD are the same strings a human reads on the page.
- **Do not mark up invented questions** to inflate the schema. FAQPage markup on padded pseudo-questions is the structured-data version of keyword stuffing.

The real extraction win comes from the **passage-block design** (Section 3), not from the schema. The schema is a cheap assist; the answer-first, locally specific, self-contained answer is what actually gets cited. Build for the passage, and add the schema because it is nearly free, not because it decorates the SERP.

---

## 5. Best / worst design references

### GOOD (the design standard)

The reference standard is the passage-block protocol's worked examples applied at FAQ length: a question header phrased as the real query, a 40-to-150-word answer that leads with a real local number or rule, one supporting specific, a citable close, and a link to the relevant money page. Roto-Rooter Pflugerville's 13 location-specific FAQs (rotorooter.com/pflugervilletx/, verified live 2026-07-20; re-open before citing) are the inline model of this: each answers a real local logistic (slab leaks in clay soil, tree-root intrusion, local codes) as a liftable passage, not a keyword pad. A standalone FAQ page is that discipline at scale, clustered by topic.

### BAD (the pattern this playbook prevents)

The keyword-padded pseudo-FAQ: invented questions engineered to hold a commercial phrase, answered with a sentence that says nothing to a human. "What is the best plumber in [city]? We are the best plumber in [city]." RicketyRoo names this exact pattern as a spam tell (verify), and the GEO study found keyword stuffing is the one tested tactic that *reduced* generative citation. It fails the passage-block gate, the information-gain gate, and the no-fabrication gate at once. The fix is never to reword the pad; it is to replace invented questions with real sourced questions and real answers, or to cut the page.

The second failure is the **accordion that hides text from parsers when built wrong**: if the FAQ answers are injected only on click via JavaScript with no server-rendered text, an engine may not read them. Handoff note to the build side: the answer text must be in the crawlable HTML, not JS-only. The writer emits real text; flag the rendering requirement in the package.

---

## 6. Google-compliance notes specific to the FAQ page

Every item is on `google-compliance-spine.md` as it applies here. All pass/fail.

1. **Real questions, no keyword padding** (the primary gate): every question is sourced from a real customer/PAA/GBP source, not invented to carry a phrase. Keyword-stuffed pseudo-FAQs fail (scaled-content risk; GEO citation penalty).
2. **No fabricated answers** (Law 20 / G10): every price, timeline, permit rule, and credential is real and traceable. A fabricated answer on a citation-built page is a hard doctrine violation.
3. **Information gain** (Law 15): each answer carries the real local specific, not the bland consensus.
4. **FAQPage schema truthfulness:** `mainEntity` mirrors the visible text verbatim; no rich-result stars expected (Aug 2023 restriction); no markup on invented questions. Validate with `scripts/schema_validator.py` and Google's Rich Results Test.
5. **NAP integrity:** any NAP shown on the page is byte-identical to `brand.yaml` and GBP (`nap-consistency.md`).
6. **Not a doorway:** a standalone FAQ page is not a thin near-duplicate of another city's FAQ page with the city swapped. If the client wants per-city FAQ content, that is the inline FAQ block on each city's conversion page, not a farm of near-identical standalone FAQ pages.
7. **Crawlable answer text** (handoff note): answers in server-rendered HTML, not JS-only accordions, so parsers and answer engines can read them.
8. **AI-crawler access** (handoff note): allow the answer-engine crawlers; add the page to `llms.txt`. Verify current user-agent strings before shipping.

---

## 7. Voice and humanization notes for the FAQ page

Governed by `knowledge/voice/` plus the client's `brand.yaml` voice.

- **Answer like the owner answers on the phone.** The FAQ page is the closest thing in the system to a transcript of the business talking to a customer. Pull the client's real phrasing (the brand voice profile); contractions, plain words, the operator's actual way of explaining the thing. A corporate FAQ voice on a family business is off-brand and less trusted.
- **The specific is the humanizer.** The real price, the real local condition, the named neighborhood: these read human because only a real operator would write them. Fix a generic-sounding answer with a fact, not a rephrase.
- **Answer-first, always.** The reader (and the engine) wants the answer, not a windup. Lead with it.
- **Kill the AI tells** (`vocabulary-blocklist.md`): "when it comes to", "rest assured", "we understand that", "look no further". These are filler in an answer and template flags to a parser.
- **No fabrication.** A question with no real answer is an SME question, never an invented answer.

---

## 8. Meta and the JSON-LD block

### 8.1 Meta title and description

- Title: `[Brand] FAQ - [Service or Topic] Questions Answered | [City, ST]` or `Frequently Asked Questions | [Brand] [City] [Service]`. Front-load the real subject; one brand token.
- Description: 150-160 chars, name the real questions the page answers and the local scope, one clear next step. No fabricated number.

### 8.2 JSON-LD (emit to `schema.json`)

`FAQPage` with `mainEntity` of `Question`/`acceptedAnswer` pairs mirroring the visible text verbatim, plus `BreadcrumbList`, plus the page-level `LocalBusiness` (subtype) node for entity clarity, cross-referenced by `@id`. Do not add self-serving `Review`/`AggregateRating`. Validate with `scripts/schema_validator.py` and the Rich Results Test (expect eligibility, not visible FAQ stars).

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "FAQPage",
      "@id": "https://example.com/faq/#faq",
      "mainEntity": [
        {
          "@type": "Question",
          "name": "How much does drain cleaning cost in Tempe?",
          "acceptedAnswer": {
            "@type": "Answer",
            "text": "A standard drain cleaning in Tempe runs $150 to $350 depending on access and severity, and we quote a flat price before any work starts. A main-line backup that needs hydro-jetting runs higher, and we tell you the number on site before we begin."
          }
        }
      ]
    },
    {
      "@type": "BreadcrumbList",
      "itemListElement": [
        { "@type": "ListItem", "position": 1, "name": "Home", "item": "https://example.com/" },
        { "@type": "ListItem", "position": 2, "name": "FAQ", "item": "https://example.com/faq/" }
      ]
    }
  ]
}
```

The `Answer.text` is character-identical to the visible answer on the page. Add `Question` nodes only for questions actually on the page.

---

## 9. Finished-page checklist (consolidated pass tests)

An FAQ page is done only when every box is checked. Any single failure returns a specific error to fix and re-run (max 2 retries, then human queue). This is the `compliance-report.md` contract for `/write-faq-page`.

**The gates (all binary):**
- [ ] Real questions: every question sourced from a real customer/PAA/GBP/review source, none invented to carry a keyword.
- [ ] Passage-block answers: every answer is answer-first, 40-150 words, self-contained, with a real local specific; the close is a citable line.
- [ ] Information gain (Law 15): each answer carries the residual local specific, not the bland consensus.
- [ ] No fabrication (Law 20 / G10): every price, timeline, rule, and credential real and traceable.

**Structure and routing:**
- [ ] Questions clustered by topic; highest-frequency/highest-intent questions first.
- [ ] Each relevant answer links to the money page it touches with a descriptive anchor; no link-stuffing.
- [ ] Answer text is real prose in crawlable HTML (handoff note flagged if the build uses accordions).

**Compliance gates (any YES = do not publish):**
- [ ] Keyword-padded pseudo-questions present (scaled-content / GEO-penalty fail)?
- [ ] Any fabricated answer, price, or credential (hard doctrine fail)?
- [ ] Is this a city-swap near-duplicate of another FAQ page (doorway fail)?
- [ ] Schema `mainEntity` disagrees with visible text, or marks up invented questions?
- [ ] Self-serving Review/AggregateRating markup present?
- [ ] NAP on the page not byte-identical to brand.yaml/GBP?

**Meta + schema:**
- [ ] Meta title/description front-loads the real subject and local scope; no fabricated number.
- [ ] JSON-LD: `FAQPage` mirroring visible text verbatim + `BreadcrumbList` + `LocalBusiness`, no self-serving review markup, validated (eligibility, not visible FAQ stars).

**Output contract (the five files must all exist):**
- [ ] page.md, schema.json, internal-links.md, compliance-report.md, sources.md - every external fact cited, every SME/first-party fact tagged, and the question corpus's real sources recorded in sources.md.

---

## Method note (honest)

This playbook is built on the 2026-07-20 research pass (`research/expansion-2026-07/02-local-seo-authorities.md`, which flagged a dedicated local-FAQ / real-Q&A framework as an upgrade gap) and executes the passage-block protocol, Law 13, Law 15, and Law 17. The FAQ rich-result restriction to gov/health sites (Aug 2023) is a real, current Google constraint, restated from `location-page.md` 4.10 and `schema-library.md`; re-verify before quoting to a client. The GEO study figures (keyword stuffing reduces citation) are directional and from a single study; re-verify before quoting externally. The core discipline is not the schema, it is the answer design: real sourced questions answered answer-first with real local specifics, which is what actually gets cited. Every answer in a real deliverable comes from the client profile, the SME interview, or cited research, never invented (CLAUDE.md hard rule; doctrine Laws 8, 15, 20).
