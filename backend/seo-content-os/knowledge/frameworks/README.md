# Frameworks Library - the canonical source of truth

Every copywriting and conversion model this system uses is defined **once**, here, in a fixed format (what it is / when to use for local, emergency vs considered / local adaptation / PASS test / anti-pattern / evidence grade). Playbooks, the `/brief` step, the `/write-*` commands, and the AIOS `plan-post` skill **reference** these files; they do not re-teach the models inline. Re-teaching a framework inside a playbook is how the drift returns (PAS was defined three different ways before this library existed). Do not duplicate framework prose back into the playbooks.

## The library

| File | Model | Primary job |
|---|---|---|
| `pas-and-pastor.md` | PAS / PASTOR | Problem-to-proof spine for high-pain intent |
| `aida-and-4ps.md` | AIDA / 4 Ps | Desire-led spine for considered intent |
| `storybrand-sb7.md` | StoryBrand SB7 | Narrative order for homepage + about |
| `cialdini-7-principles.md` | Cialdini's 7 | Persuasion levers, all pages |
| `schwartz-awareness-sophistication.md` | Schwartz | Brief-time directness + lead-claim selector |
| `copyhackers-hero-and-belief.md` | Rule of One, 5-element hero, belief sequencing | Fold + overall block order, all pages |
| `value-equation-and-risk-reversal.md` | Hormozi value equation + guarantee catalog | Offer diagnostic + risk reversal at the ask |
| `objection-handling.md` | Objection = friction reduction | The FAQ block, all pages |
| `scan-layer-formatting.md` | NN/g F-pattern + message match | Mobile scannability + CTA, all pages |
| `voice-of-customer-mining.md` | VoC method | The raw language that fills every framework above |

## Always-on frameworks (every page, every intent)
Load these on every write regardless of page type or awareness:
- **`voice-of-customer-mining.md`** - the input that fills all the others. Mine first.
- **`copyhackers-hero-and-belief.md`** - Rule of One + the 5-element hero + belief sequencing govern the fold and block order.
- **`cialdini-7-principles.md`** - the persuasion ingredients, placed where each does the most work.
- **`value-equation-and-risk-reversal.md`** - run the four-dial diagnostic; place a real guarantee at the ask.
- **`objection-handling.md`** - the FAQ as friction reduction.
- **`scan-layer-formatting.md`** - the mobile scan layer + message match + single attention ratio.

## The spine selector (what changes per page)
The one framework that changes is the **problem-to-proof spine**, chosen by **pain level** (read off the query's awareness via `schwartz-awareness-sophistication.md`):

- **High pain / emergency intent** ("emergency plumber near me," "burst pipe," "AC not working") -> **PAS/PASTOR spine.** The buyer feels it; name it and pitch.
- **Low pain / considered intent** ("kitchen remodel," "cosmetic dentistry," "estate planning") -> **AIDA / 4 Ps spine.** No acute pain to agitate; lead with the picturable outcome.
- **Homepage / about narrative** -> **StoryBrand SB7** (customer as hero, business as guide, explicit plan), with PAS or AIDA compressed inside individual sections.

`schwartz-awareness-sophistication.md` runs first at brief time: the target query sets both the **directness** of the copy and, via market sophistication, whether the lead claim must be a mechanism/specific rather than a table-stakes claim.

## Routing table: page type x intent -> primary spine + hero style

| Page type | Command | Typical intent | Primary spine | Hero style |
|---|---|---|---|---|
| Homepage | `/write-homepage` | Mixed (grunt test) | **StoryBrand SB7** + Schwartz for lead claim | Guide-framed, grunt-test pass in 5s, one action |
| Service page | `/write-service-page` | Full spread, commercial | **PAS** for emergency services; **AIDA/4Ps** for considered services | Outcome H1 + fold trust signal (rating/count) |
| Service-in-city (money page) | `/write-service-city-page` | Transactional, local | **PAS** (emergency trades) or **4 Ps** (considered), + Reciprocity offer | Direct, trust-led, message-matched to `[service] [city]` |
| Location page | `/write-location-page` | Local-intent, branch | Light **PAS** + Liking/Unity heavy | Place-anchored, local proof + click-to-call |
| About / team page | `/write-about-page` | Trust surface | **StoryBrand** (business as guide) + Authority/Liking | Named humans, credentials, the "why we do this" |
| Service-area page | `/write-service-area-page` | Coverage intent | **4 Ps** light + Unity; unique local value (no doorway) | Coverage clarity + genuinely local specifics |

**Worked routing example:** service-in-city page, emergency intent, high pain -> PAS spine + direct trust-led hero (`copyhackers-hero-and-belief.md`) + Reciprocity offer at the CTA (`cialdini-7-principles.md`) + real risk reversal at the ask (`value-equation-and-risk-reversal.md`) + scan layer and click-to-call (`scan-layer-formatting.md`), all filled with mined VoC language.

## Awareness -> directness (Schwartz), quick reference

| Query looks like | Awareness stage | Copy directness |
|---|---|---|
| "[service] near me," brand search | Product / Most-Aware | Direct: lead with the ask + one trust signal; minimal education |
| "best [service] company," "[service] cost" | Solution-Aware (commercial investigation) | Proof-led: compare-and-prove, then ask |
| "why is my [problem] happening" | Problem-Aware | Educate first, then pitch |
| broad symptom, no service named | Unaware | Diagnose the problem before naming the service |

## Evidence-grade legend (grade honestly; never oversell to a client)
- **Controlled-proof / strong empirical:** `scan-layer-formatting.md` (NN/g eye-tracking, primary source) is the strongest. The GEO citation-lift direction behind `objection-handling.md` is controlled but a single study (directional).
- **Craft consensus:** PAS/PASTOR, AIDA/4Ps, StoryBrand, Cialdini, Schwartz, Copyhackers hero, value equation. High explanatory power, no controlled lift figure for local pages. Structural aids. Do not quote a lift number.
- **Folklore (never quote to a client):** the "first-person CTA lifts clicks 90%" figure (single Aagaard/Unbounce test) and the "guarantees lift conversion X%" vendor case studies. Use the **tactic**, never the **number**. The mechanisms are sound and need no fabricated coefficient.

## Hard lines that bind the whole library
- **Law 20 / Cialdini Scarcity:** no fabricated urgency, scarcity, or proof. Real seasonal deadlines, real booked-out calendars, real attributable reviews only. Fabricated pressure is an FTC dark-pattern and a trust penalty.
- **Law 16:** every falsifiable claim these frameworks dress up must resolve to a real, cited, first-party artifact. VoC snippets and proof points are sourced, never invented.
- **Law 8:** these are conversion and clarity tools, never detector-evasion. No humanizer step, ever.

Sources for every grade are in the individual files. All URLs fetched 2026-07-20 PKT; the library was extracted from `research/expansion-2026-07/03-copywriting-conversion.md` and the six playbooks.
