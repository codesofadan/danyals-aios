# SEO-CONTENT-OS Internal Audit - Where It Falls Short of World-Class

**Auditor stance:** ruthless senior local-SEO editor, pre-expansion critical review.
**Date:** 2026-07-20 PKT.
**Scope:** everything built at `D:\SEO-CONTENT-OS` - CLAUDE.md, 6 playbooks, 10 foundations, 4 doctrine files, 7 voice files, 2 quality-gate files, 7 agents, 9 commands, 5 scripts, brand.yaml template.
**Method:** read every built file (not sampled), plus light live-benchmark research against what top local-SEO writers publish for each page type.

**Headline verdict.** This is a genuinely strong system. The knowledge layer (playbooks, foundations, doctrine, gates, voice) is deep, internally consistent, honest about uncertainty, and cited to primary sources. The corpus upholds Law 8 (no detector evasion), the self-review-schema ban, and the FAQ-deprecation reality with near-zero drift across 30+ files. It is NOT falling short on doctrine. It is falling short in three specific places: (1) **example depth** - the leaf-artifact teardown libraries are thin and plumbing-skewed, which is the single most valuable expansion target and the user's stated priority; (2) **gate enforceability** - several gates the system calls "deterministic Python checks" have no script, or the script exists under a different name/interface than the agents invoke; (3) **a systematic broken reference** between the agents and the real scripts that would fail on first execution.

---

## Part 1 - Benchmark pass: does each playbook match world-class?

Light live research against Backlinko, Whitespark, Sterling Sky, RicketyRoo, BrightLocal, Search Engine Land, and Google's own docs. Findings:

The playbooks already **cite** these sources correctly and current (Whitespark 540-query AIO study, Backlinko location-page guide + citation experiment, Google spam-policy verbatim, Sterling Sky hidden-address finding, RicketyRoo safe/risky/spammy axis, the May-2026 "spam policies now cover AI surfaces" update, FAQ rich-result deprecation). On **frameworks and local nuance**, the playbooks meet or exceed what those sources publish: the strip-the-city test, the external-verifiability moat, the Minimum Unique Local Substance bar, the storefront-vs-SAB honesty rule, the hidden-address paradox, the URL-pattern discipline, and the schema-honesty rules are all present and, in several cases, sharper than the public sources. A world-class writer handed any one playbook could build the page.

Where the playbooks fall short of world-class is **not** the rulebook. It is **worked examples**: the number of real, cited, torn-down good AND bad pages, and the vertical spread of those examples. That is Part 2.

---

## Part 2 - The examples gap (per page type) - THE priority

The user wants MANY good AND bad examples per page type. Current state, counted from the built files:

| Playbook | Good teardowns (deep, live-cited) | Bad teardowns (deep, live-cited) | Verticals covered deeply | Named-but-not-torn-down |
|---|---|---|---|---|
| **location-page** | 1 (Roto-Rooter Pflugerville, plumbing) | 1 (Bill Joplin's Plano, HVAC) | plumbing, HVAC | 8 (Wade Paint, Merit Dental, Sila, Infinity Roofer, Assembly Squad, A.J. Alberts, Big Wave HVAC, Best Choice Roofing) |
| **service-page** | 3 (Morgan&Morgan legal, Benjamin Franklin plumbing, A1 Garage garage-door) | 3 (Telleria legal, Buffalo Lawn pest, Garage Door Expert garage) | legal, plumbing, garage, pest | 0 |
| **service-city-page** | 3 (RR Houston plumbing, Miller&Zois Baltimore legal, RR Pflugerville plumbing) | 0 named live (4 abstract pattern-classes A-D) | plumbing, legal | 0 |
| **homepage** | 2 (Genz-Ryan HVAC, Bear's Plumbing) | 0 named live (5 abstract archetypes) | HVAC, plumbing | 0 |
| **about-team-page** | 2 (Chambliss plumbing, ABC Home&Commercial multi-trade) | 0 named live (6 abstract archetypes) | plumbing, home-services | 0 |
| **service-area-page** | 2 (Len The Plumber, Bayonet plumbing) + 1 graduated-spoke (RR) | 0 named live (pattern-classes + Joplin reference) | plumbing only | 0 |

**Read of the gap:**

1. **Heavy plumbing skew.** 4 of 6 playbooks lean on plumbing/HVAC teardowns. Dental, legal (partial), roofing, electrical, med-spa, garage, pest, cleaning, landscaping, towing, auto-repair, chiropractic are mostly absent as deep teardowns. A writer building a **dentist** location page or a **roofer** service-city page has no in-vertical worked example to pattern-match against.

2. **Bad examples are mostly abstracted to pattern-classes.** service-city, homepage, about, and service-area deliberately replaced named bad pages with archetypes (a defensible defamation-caution call). Legitimate, but it leaves the writer and the `critical-editor` agent without concrete, checkable bad-teardowns to compare a draft against. The two playbooks WITH named bad teardowns (service-page, location-page) are visibly stronger for it.

3. **The winner teardowns lean on national brands** (Roto-Rooter, Morgan & Morgan, Benjamin Franklin, Len The Plumber). Every one carries an honest "authority caveat," but the corpus has few **single-location small-operator** winners - which is the actual client profile. Bear's Plumbing and Chambliss are the only true small-operator winners, both plumbing.

**Quantified example target (to reach world-class), per page type:**

Target ~6-8 good + ~4-6 bad deep teardowns per playbook, spread across the 6 core verticals (plumbing, HVAC, roofing, electrical, dental, legal) plus 1-2 considered/YMYL verticals (med-spa or solar; personal-injury or family law). Concretely:

- **location-page:** has 1 good + 1 bad. Needs **+6 good, +5 bad** across dental, legal, roofing, electrical, HVAC (non-plumbing), and 1 small-operator winner. Highest gap; this is the highest-penalty-risk page type.
- **service-page:** has 3 good + 3 bad (best-covered). Needs **+4 good, +3 bad** to add dental, HVAC, roofing, electrical; already has the strongest base.
- **service-city-page:** has 3 good + 0 named bad. Needs **+4 good, +5 bad** (named live bad teardowns, carefully framed) across dental, HVAC, roofing, electrical.
- **homepage:** has 2 good + 0 named bad. Needs **+5 good, +5 bad** across dental, legal, roofing, electrical, plus a solo-operator winner and named bad pages.
- **about-team-page:** has 2 good + 0 named bad. Needs **+5 good, +5 bad** across dental, legal, roofing, HVAC, electrical.
- **service-area-page:** has 2 good + 0 named bad, plumbing only. Needs **+5 good, +5 bad** across HVAC, roofing, electrical, dental (SAB-relevant trades), and named doorway-network bad teardowns with the defamation-safe framing already modeled in the file.

Total: roughly **+29 good and +28 bad** deep teardowns to reach the "many good and bad, per vertical" bar. This is the core of the expansion.

---

## Part 3 - Layer-by-layer gap list

### 3.1 Scripts vs gates - enforceability gaps (HIGH IMPACT)

The gate spec (`gates.md`, `quality-gates/README.md`) claims: *"The deterministic gates (blocklist scan, keyword density, meta length, schema validity, source resolution) run as Python checks in `scripts/`."* Reality:

| Claimed deterministic check | Script exists? | Gap |
|---|---|---|
| Keyword density (G5) | YES `keyword_density.py` | none - works, self-tested |
| Schema validity (G11) | YES `schema_validator.py` | partial - see D3 gap below |
| NAP consistency (E2/G11) | YES `nap_checker.py` | works, but not pointed at `schema.json` (see below) |
| Readability (G8) | YES `readability_scorer.py` | works, self-tested |
| Compliance lint (structural) | YES `compliance_lint.py` | works (H1, meta-presence, thin-section, em-dash, stuffing) |
| **Blocklist scan (G9)** | **NO** | vocabulary-blocklist.md is lint-ready (Tier-1 tokenizable) but **no script lints it**. G9's "deterministic scan for Tier-1 and client-banned hits" is unbacked. `compliance_lint.py` catches em-dash only, not the ~120-term Tier-1 list. |
| **Meta length (G6)** | **NO** | `compliance_lint.py` checks meta *presence*, not the ~60-char title / 150-160-char description limits. Length is unenforced by script. |
| **Source resolution / URL 200 (G10)** | **NO** | No `link_checker.py`. AND the workspace is "no network calls" by design, so an offline script *cannot* resolve URLs. G10's "deterministic HTTP-200 check" is architecturally impossible as an offline script; it must be an agent WebFetch task. gates.md mislabels it as a deterministic script. |
| **Self-serving Review/AggregateRating on own LocalBusiness (D3)** | **NO** | This is the single most-repeated schema rule in the entire system (in all 6 playbooks + schema-library + local-gbp-signals + compliance spine D3, called "the single most common local manual-action cause"). `schema_validator.py` validates required fields but has **no check to flag a prohibited `review`/`aggregateRating` node on a LocalBusiness/Organization**. The most-emphasized compliance rule is not machine-enforced. |
| **Schema NAP == page NAP == brand.yaml (G11)** | **partial** | `schema_validator.py` checks NAP *presence/shape*; `nap_checker.py` checks *page text* vs a canonical NAP. Nothing cross-checks `schema.json` NAP against `brand.yaml`/page. The byte-identity gate is only half-covered. |
| **Cross-page doorway similarity (G3/B1)** | **NO** | B1 says "diff this page against sibling city pages, >70% shared boilerplate = fail." No sibling-diff script. The single biggest penalty risk is judgment-only. A cheap deterministic shingle-similarity script would materially harden it. |

### 3.2 Broken script references - agents call scripts that do not exist (HIGH IMPACT, will fail on run)

The agents invoke scripts by names and flags that do not match the real files:

- `compliance-auditor.md` (lines 32-33, 121-122) calls **`scripts/nap_check.py`** and **`scripts/readability.py`**. Real files are **`nap_checker.py`** and **`readability_scorer.py`**. Wrong names.
- `critical-editor.md` (lines 220, 222) runs `python scripts/nap_check.py --client <slug> --input ...` and `python scripts/readability.py --input ...`. Both names are wrong AND the flags are wrong: real `nap_checker.py` takes `--brand <path>` plus positional files (no `--client`, no `--input`); real `readability_scorer.py` takes a positional path (no `--input`).
- `schema-linking-finisher.md` (line 45) runs `python scripts/schema_validator.py --input output/.../schema.json`. Name is right, but the real script takes a **positional path** or `--string`, **not `--input`**. This command errors as written.
- `new-client.md` (line 30) references `scripts/nap_check.py`. Wrong name.

Net effect: if an agent executes any of these literally, it gets "file not found" or "unrecognized arguments," silently falls back to "manual check," and the deterministic gate never actually runs. Every documented script call in the pipeline is currently broken. This is a rename/interface-alignment fix, low effort, high impact.

### 3.3 Knowledge-layer consistency - GOOD, with one micro-drift

The doctrine/foundations/voice/gates/playbooks agree on Law 8, the self-review ban, FAQ deprecation, the doorway line, NAP discipline, and passage-block format, with no material contradictions across 30+ files. One micro-drift worth tightening:

- `eeat-framework.md` (Trust marker 8, ~line 123) mentions "review/aggregateRating markup that matches the visible on-page facts" **without** restating the self-serving-on-own-LocalBusiness prohibition that schema-library.md (line 128) and local-gbp-signals.md (line 51) state explicitly. Not a contradiction (it is qualified), but it is the one place a reader could infer self-review markup is fine. One-line tightening.

### 3.4 Pipeline coherence - GOOD

The `brief -> research -> sme -> outline -> draft/humanize -> edit -> gate -> finalize` flow is complete and coherent across the 7 agents and the commands. Inputs/outputs chain cleanly (`brief.md -> research.md -> sme-questions.md -> sme-answers.md -> outline.md -> draft.md -> edited.md -> compliance-report.md -> page.md/schema.json/internal-links.md/sources.md`). Reroute targets on gate fail are named and sane. The SME halt-for-operator step is correctly modeled. No missing stage. The only pipeline defect is the broken script references in 3.2.

### 3.5 Smaller gaps

- **No `/write-service-area-page` verification that the coverage LIST vs individual-PAGE decision is enforced anywhere deterministic.** The service-area playbook's core decision rule (booked-jobs test + local-proof test) is judgment-only; fine, but worth a checklist artifact the agent fills.
- **`keyword_density.py` is never referenced by any agent** (only imported internally by `compliance_lint.py`). It works but is orphaned from the documented pipeline; the G5 gate should call it explicitly.
- **No worked full-page GOLD sample output** anywhere in the repo (`output/` is empty). A single end-to-end reference package (all 5 files, real client, one page type) would anchor every agent's target and let the scripts be tested on real input, not just self-test fixtures. (Cf. the memory lesson: test engines on real inputs, not fixtures.)
- **Meta/title pixel-width** is a craft target in `meta-and-headings.md` and `hooks-and-titles.md` but is unenforced (see 3.1 meta-length gap).
- **Homepage, about, service-area playbooks** deliberately avoid named bad teardowns; the defamation caution is sound, but service-page and location-page show named bad teardowns can be done safely with analytic framing. Standardize that framing so all 6 can carry named bad examples.

---

## Part 4 - Fixes mapped to categories (what / why / effort)

### [Examples] - the priority

1. **Build a per-vertical teardown library** - ~29 good + ~28 bad deep, live-cited teardowns across plumbing, HVAC, roofing, electrical, dental, legal (+ 1-2 considered/YMYL). What: one teardown = URL, live-fetch date, why-it-wins/loses against the playbook's own pass tests, the transferable lesson. Why: the user's stated priority; the single biggest quality lever; kills the plumbing skew and gives every vertical an in-vertical model. Effort: **L** (this is the bulk of the expansion; parallelize by page-type x vertical).
2. **Add named bad teardowns to homepage, about, service-area, service-city** using the defamation-safe analytic framing already modeled in service-page/location-page. What: 4-6 named live bad pages each. Why: concrete bad examples are what `critical-editor` pattern-matches against; abstract archetypes are weaker. Effort: **M**.
3. **Add 1-2 true single-location small-operator winners per page type.** Why: national-brand winners all carry an authority caveat and do not model the real client. Effort: **M**.

### [Python scripts]

4. **`blocklist_lint.py`** - scan a draft against `vocabulary-blocklist.md` Tier-1 (literal) + client `banned_phrases`, with a context/allowlist layer for the annotated conditional terms. Why: backs G9's "deterministic scan" claim, currently unbacked. Effort: **M** (Tier-1 is tokenizable; the conditional-term allowlist is the work).
5. **Extend `schema_validator.py` to flag self-serving `review`/`aggregateRating` on LocalBusiness/Organization nodes (D3).** Why: the most-repeated compliance rule in the system, currently not machine-enforced; called "the single most common local manual-action cause." Effort: **S**.
6. **`meta_check.py`** (or extend `compliance_lint.py`) - title ~50-60 char, description 150-160 char, one H1, city+keyword present. Why: G6 meta-length is unenforced. Effort: **S**.
7. **Cross-surface NAP check** - extend `nap_checker.py` to also read `schema.json` and assert schema NAP == brand.yaml == page. Why: closes the byte-identity half-gap in G11/E2. Effort: **S-M**.
8. **`sibling_similarity.py`** - shingle/Jaccard diff of a page against its sibling city pages, flag >70% shared boilerplate (B1 threshold). Why: hardens the single biggest penalty risk deterministically. Effort: **M**.
9. **`link_checker.py` (network-allowed, opt-in) OR reclassify G10 as an agent WebFetch task.** Why: G10's "deterministic HTTP-200 check" cannot be an offline script under the no-network rule; either allow a scoped online checker or stop calling it deterministic. Effort: **S** (reclassify) / **M** (build online checker).

### [Agents]

10. **Fix all broken script references** in `compliance-auditor.md`, `critical-editor.md`, `schema-linking-finisher.md`, `new-client.md`: correct filenames (`nap_checker.py`, `readability_scorer.py`) and correct CLIs (positional paths, `--brand`, not `--client`/`--input`). Why: every documented script call currently fails on execution. Effort: **S**.
11. **Wire the new scripts into the agents** (blocklist_lint into critical-editor + compliance-auditor G9; meta_check into compliance-auditor G6; sibling_similarity into compliance-auditor G3; keyword_density explicitly into G5). Effort: **S**.

### [MD knowledge files]

12. **Tighten `eeat-framework.md` Trust marker 8** to restate the self-serving-review-schema prohibition explicitly (align with schema-library.md line 128). Effort: **S**.
13. **Correct `gates.md` / `quality-gates/README.md`** to stop listing "meta length" and "source resolution" as deterministic scripts until 6 and 9 land; label them agent-judgment or agent-WebFetch. Effort: **S**.
14. **Standardize the "named bad teardown, safely framed" convention** as a short shared note the 6 playbooks reference, so bad examples are consistent and defamation-safe. Effort: **S**.

### [Laws / doctrine]

15. No new laws needed. The doctrine (Law 8, Law 10, Law 13) is sound and consistently applied. One doctrine-adjacent addition worth considering: a stated **"every deterministic gate must have a runnable script or be labeled judgment"** rule, to prevent the gates.md/scripts drift from recurring. Effort: **S**.

### [Frameworks]

16. No missing frameworks at the rule level - the playbooks already carry the strip-the-city test, external-verifiability moat, Minimum Unique Local Substance bar, hidden-address paradox, URL-pattern discipline, belief-sequencing, PAS/BAB, and the schema-honesty rules. The gap is examples that instantiate these frameworks per vertical, not new frameworks. Effort: n/a.
17. **One framework artifact worth adding: a GOLD end-to-end sample output package** (real client, one page type, all 5 files) in `output/`, doubling as the test fixture the scripts run against on real input. Why: anchors every agent and tests scripts on real, not synthetic, input. Effort: **M**.

---

## Part 5 - Priority order for the expansion

1. Fix the broken script references (10) - S, unblocks the whole gate layer. Do first.
2. Build the per-vertical teardown library (1) - L, the priority and the user's ask.
3. Add the D3 self-review schema check (5) and blocklist_lint (4) - the two highest-value enforceability closures.
4. Named bad teardowns across the 4 abstract-only playbooks (2) + small-operator winners (3).
5. meta_check (6), cross-surface NAP (7), sibling_similarity (8), then wire-in (11).
6. Doc tightening (12, 13, 14, 15) and the GOLD sample (17).

The knowledge is world-class. The examples and the enforcement are not yet. Close those two and the system ships pages no human content shop matches.
