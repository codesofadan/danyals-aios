# SEO-CONTENT-OS - Complete System Map

Generated 2026-07-20 PKT by direct read of every file in the workspace. Every count, threshold, and file listing below was verified against the actual files, not against CLAUDE.md or README.md. Where the docs and the disk disagree, the disk wins and the drift is flagged in Part 11.

---

## Update log

**2026-07-23 PKT - Self-storage vertical added (the 5th vertical overlay, the 11th example teardown, the 1st net-new page type).** The system was specialized for US self-storage. New files, each wired (no orphans): `knowledge/verticals/self-storage.md` (the SS-* compliance overlay: protection-plan-is-not-insurance, no absolute-security claim, "free" with the admin fee in-line, per-state lien law); `knowledge/playbooks/unit-size-page.md` + `.claude/commands/write-unit-size-page.md` (the storage-native money page, "[size] storage units [city]"); `knowledge/playbooks/examples/self-storage.md` (real GOOD/BAD teardowns, 7 page types); `knowledge/foundations/storage-topical-map.md` (the storage grid axes + query-cluster library A-J + promotion-evidence table + single-facility collapse); `knowledge/voice/self-storage-voice.md` (operator/renter voice + trade glossary + mechanism-not-reassurance); `scripts/storage_lint.py` (the SS-* deterministic linter) + `scripts/storage_cluster_seed.py` (the candidate-ceiling generator); `clients/sample-storage/` + `output/sample-storage/climate-controlled-storage-round-rock/` (the fictional worked demo, all gates green); `research/self-storage-2026-07/` (9 cited intelligence dossiers). Edited-and-rewired: `clients/_template/brand.yaml` (the `storage:` block + `vertical: self-storage`), `scripts/schema_validator.py` (`SelfStorage` subtype + `LeaseOut` check), `knowledge/voice/vocabulary-blocklist.md` (the `### Self-storage cliches` Tier-1 section), `knowledge/foundations/schema-library.md` (section 8b, the `SelfStorage` bundle), and the agents `compliance-auditor`, `topical-map-architect`, `keyword-intent-researcher`, `voice-writer`, `critical-editor` (all now route on `vertical == self-storage`). Count deltas since the 2026-07-20 snapshot below: verticals 4 -> 5, examples 10 -> 11, playbooks 11 -> 12, foundations +1 (storage-topical-map), voice +1 (self-storage-voice), scripts 20 -> 22, commands 17 -> 18. The Part-1..Part-11 body below is the 2026-07-20 baseline; treat this addendum as the current delta.

---

## Part 1 - Statement of the system

**What it is.** A Claude-Code-native operating system that writes local-SEO web copy for service businesses. Claude Code is the writer. The workspace is its constitution, its training, its guardrails, and its memory. There are no external APIs. Deterministic checks run as offline stdlib-only Python. Live web research grounds every external claim at write time.

**What it is for.** Producing a page that does four things at once: ranks in local search, gets cited by AI answer engines, reads genuinely human, and is penalty-proof because every line was written to Google's published rules rather than to a folk theory about them.

**The thesis, in one paragraph.** Every commercial AI content tool (Byword, Koala, SEO.ai, Surfer, Jasper, Cuppa) sources from the SERP or from the model's parametric memory. Both of those are public. Therefore none of them can manufacture first-party Experience - the first E of E-E-A-T - because it exists only inside the operator's head and invoice history. Their one strength is volume, which is precisely the vector Google's scaled-content-abuse and doorway policies target. So the winning system is not the one with the most page types or the most frameworks. It is the one that systematically **extracts, scores, enforces, and measures first-party Experience**, then closes the loop proving the page ranked and converted. Every component below is ranked by how much it widens that moat.

**The two laws that govern everything.**

- **Law 8 - no detector-evasion, ever.** Google's policy is method-agnostic: it punishes scaled low-value publishing, not AI provenance. Measured AI-share-versus-ranking correlation across 600k pages is 0.011, which is zero. AI detectors are all sub-80% accurate and one paraphrase defeats them. So there is no humanizer, no "passes AI detection" gate, ever. A page reads human because it *is* specific and true, not because it was laundered.
- **Law 16 - the moat.** Experience is the one signal no competitor and no model can scrape. It must be extracted via the SME interview and then *shown* with dated first-party artifacts (photos, license numbers, invoice-backed counts, named real results), never merely claimed. An unprovable Experience claim is cut, never softened.

**The design consequence.** The system is built so that a well-written page still fails if its Experience is unprovable. The shipped sample output demonstrates exactly this: `output/sample-dental/dental-implants/compliance-report.md` returns **VERDICT: BLOCKED**, failing G1, G10, and MED-3, because the demo client has fictional license numbers and no photos. The prose is clean. The system refuses it anyway. That is the intended behavior, not a bug.

---

## Part 2 - Wireframe

```
                            +-------------------------------------+
                            |  CLAUDE.md  (constitution, loaded)  |
                            +------------------+------------------+
                                               |
        +--------------------------------------+--------------------------------------+
        |                          KNOWLEDGE LAYER (60 .md)                            |
        |  read-only in practice: settings.json puts knowledge/ behind "ask"           |
        +------------------------------------------------------------------------------+
        |  doctrine/ (7)      Laws 1-20 . 33-rule Google spine . penalty casebook      |
        |                     ai-search-reality . llms-txt verdict . interop spine     |
        |  foundations/ (15)  the reusable mechanics: intent, E-E-A-T, passage blocks, |
        |                     schema, linking, keywords, GBP, NAP, GEO, meta, clusters |
        |  playbooks/ (11)    one deep spec per page type + reviews/GBP                |
        |    examples/ (10)   real good/bad teardowns, one per vertical                |
        |  frameworks/ (11)   canonical copy/CRO models, referenced not re-taught      |
        |  voice/ (7)         universal humanization layer + per-client template       |
        |  verticals/ (4)     YMYL overlays: legal . medical-dental . financial . HS   |
        |  lifecycle/ (3)     measurement loop . decay/refresh . editorial scorecard   |
        |  quality-gates/ (2) the authoritative G0-G13 spec                            |
        +------------------------------------------------------------------------------+
                                               |  loaded in strict order per task
                                               v
   +-----------------------------------------------------------------------------------+
   |                           EXECUTION LAYER (.claude/)                               |
   |  16 commands  .  9 agents  .  2 skills  .  1 PreToolUse hook                       |
   +-------------------------------------------+---------------------------------------+
                                               |
   +-------------------------------------------v---------------------------------------+
   |                              THE PIPELINE (7 stages)                               |
   |                                                                                    |
   |  BRIEF --> RESEARCH --> SME ==HALT==> OUTLINE --> DRAFT --> CONVERT --> GATE -->   |
   |    |          |            |            |           |          |          |        |
   |  command  keyword-      sme-        outline-     voice-   conversion- compliance-  |
   |           intent-    interviewer   architect     writer   optimizer    auditor     |
   |          researcher      |             |        + critical-   (G13)   (G0-G13 +    |
   |             |            |             |          editor       |       vertical)   |
   |             v            v             v            v          v          |        |
   |         research.md  sme-questions  outline.md   draft.md   edited.md     |        |
   |                       ^ operator                          + conversion    |        |
   |                      sme-answers.md                          block        |        |
   |                                                                           v        |
   |                                                              FINALIZE --> ENROLL   |
   |                                                          schema-linking-  (Law 18) |
   |                                                             finisher               |
   +-------------------------------------------+---------------------------------------+
                                               |
                     +-------------------------+--------------------------+
                     |        DETERMINISTIC LAYER  scripts/ (18 .py)      |
                     |  stdlib-only . zero network . every one --self-test |
                     |  exit 0 = pass, 1 = fail, 2 = usage error           |
                     +-------------------------+--------------------------+
                                               |
   +-------------------------------------------v---------------------------------------+
   |                    OUTPUT CONTRACT  output/<client>/<slug>/                        |
   |   page.md . schema.json . internal-links.md . compliance-report.md . sources.md    |
   |   Not done until all five exist, every gate passes, and the page is enrolled.      |
   +-------------------------------------------+---------------------------------------+
                                               |
   +-------------------------------------------v---------------------------------------+
   |              LIFECYCLE LOOP (Law 6, 18, 19)  - manual CSV exports, no API          |
   |   ENROLL --> decay_monitor --> /refresh --> re-gate --> report_builder --> case_log|
   |              share_of_answer_tracker  (Law 13: measured across AI engines)         |
   +-----------------------------------------------------------------------------------+

   STATE:  clients/<slug>/brand.yaml  (facts, NAP, E-E-A-T artifacts, voice, case_log)
           clients/<slug>/link-graph.json  (persistent hub/spoke graph, link-architect)
```

---

## Part 3 - What the system is, by the numbers

All verified by direct file count on 2026-07-20.

| Component | Count | Notes |
|---|---|---|
| Markdown files, total | **115** | 60 knowledge + 27 execution + 8 research + 5 output + templates/clients/root |
| Python files | **19** | 18 gate/ops scripts + 1 PreToolUse hook |
| Total lines of Python | **6,220** | 6,187 in scripts, 33 in the hook |
| Total lines of knowledge markdown | **~17,000** | `knowledge/` alone |
| Agents | **9** | CLAUDE.md still says 7 - drift, see Part 11 |
| Slash commands | **16** | 11 writers + 5 operations |
| Skills | **2** | corpus-voice-ingest, geo-optimize |
| Hooks | **1** | PreToolUse on Write/Edit, blocks U+2014 |
| Laws | **20** | 14 portable doctrine + 6 local-content extension |
| Google compliance hard rules | **33** | 5 groups A-E |
| Quality gates | **14** | G0 through G13 |
| Page types with full playbooks | **11** | 8 page types + review responses/requests + GBP posts |
| Vertical teardown libraries | **10** | plumbing, hvac, roofing, electrical, dental, PI-law, med-spa, auto-repair, pest-control, landscaping |
| YMYL vertical overlays | **4** | legal, medical-dental, financial, home-services |
| Canonical copy frameworks | **11** | |
| Tier-1 banned terms (machine-parsed) | **108** | across 5 categories, 81 synonym groups |
| Tier-3 structural anti-patterns | **9** | |
| Research territories in the evidence base | **7** | plus the master blueprint |

**Script health, verified this session:** all 18 scripts pass `--self-test`. Every `scripts/*.py` path referenced anywhere in `.claude/` or `knowledge/` resolves to a real file - the Wave 0 interface-rename defect recorded in `research/expansion-2026-07/07-internal-audit.md` has been fixed.

---

## Part 4 - The pipeline and the agent handoff chain

Seven stages. Each write-command runs all of them against its playbook.

```
STAGE       AGENT                     READS                          WRITES
---------------------------------------------------------------------------------------
BRIEF       (the command itself)      brand.yaml + playbook          brief.md
RESEARCH    keyword-intent-researcher brief.md, brand.yaml           research.md
SME         sme-interviewer           research.md, brand.yaml        sme-questions.md
            == PIPELINE HALTS. Operator fills sme-answers.md. This is the moat step. ==
OUTLINE     outline-architect         sme-answers.md, research.md    outline.md
DRAFT       voice-writer              outline.md (binding), SME      draft.md
HUMANIZE    critical-editor           draft.md, outline.md           edited.md
CONVERT     conversion-optimizer      edited.md (G13)                edited.md + conversion block
GATE        compliance-auditor        edited.md + all scripts        compliance-report.md
FINALIZE    schema-linking-finisher   edited.md (PASS-verified)      page.md, schema.json,
                                                                     internal-links.md, sources.md
ENROLL      (operator)                measurement sheet              a row, or it is not shipped
---------------------------------------------------------------------------------------
SITE-LEVEL  link-architect            link-graph.json, brand.yaml    updated graph + internal-links.md
```

**Failure routing.** On any gate FAIL, compliance-auditor routes back by name to critical-editor, outline-architect, sme-interviewer, or schema-linking-finisher. Maximum 2 automated retries, then the page goes to a human queue. This is Law 8 rule against blind self-refinement: refine only against an external gate specific error report, never against the model own second opinion.

**The nine agents and their tool allowlists:**

| Agent | Stage | Tools | Halts on |
|---|---|---|---|
| `keyword-intent-researcher` | 2 | Read, Write, WebSearch, WebFetch, Grep, Glob | city not in `service_areas`; SERP not geo-locatable |
| `sme-interviewer` | 2b | Read, Write only | always halts by design after writing questions |
| `outline-architect` | 3 | Read, Write, Grep, Glob | sme-answers missing or thin; anti-doorway check fails |
| `voice-writer` | 4-5 | Read, Write, WebSearch, WebFetch, Grep | a section needs an unsupplied SME specific; a fact cannot be sourced; a detector-evasion pass is requested (refuse, cite Law 8) |
| `critical-editor` | 5b | Read, Write, Grep, Bash | specificity fails and SME is exhausted; passage-block format fails on 40%+ of sections |
| `conversion-optimizer` | 5c | Read, Write, Grep, Bash | a required real element missing from source; a fabricated conversion element found (hard halt, Law 20) |
| `compliance-auditor` | 6 | Read, Write, Bash, Grep, Glob | any gate FAIL blocks finalize |
| `schema-linking-finisher` | 7 | Read, Write, Bash, Grep, Glob | schema FAIL after 2 fix passes; meta description will not compress under 160 chars |
| `link-architect` | site-level | Read, Write, Bash, Grep, Glob | required parent page does not exist; doorway-risk near-duplicate |

**The 16 commands:**

Writers (each runs the full pipeline): `/write-location-page`, `/write-service-page`, `/write-service-city-page` (the money page), `/write-homepage`, `/write-about-page`, `/write-service-area-page`, `/write-faq-page`, `/write-local-asset`, `/write-review-responses`, `/write-review-requests`, `/write-gbp-posts`.

Operations: `/new-client` (build brand.yaml, runs sme-interviewer in profile mode), `/brief` (BRIEF + RESEARCH only, then stops), `/qa` (standalone gate run), `/refresh` (decay detection and refresh, Laws 18-19), `/report` (monthly KPI report from manual CSV exports).

---

## Part 5 - The 20 laws

**Laws 1-14** live in `knowledge/doctrine/seo-system-doctrine.md`. Portable across every Xegents SEO workspace.

| # | Law | Meaning |
|---|---|---|
| 1 | The loop is the product; the report is the funnel | A system terminating in a document is unfinished |
| 2 | Write access is the product boundary | Power equals owned write surfaces; no rented JS overlays |
| 3 | Decouple collection from analysis; the cache is the speed | Crawl once, re-report without re-fetching |
| 4 | Judgment is versioned code | Decision logic as git-diffable rule catalogs, not model vibes |
| 5 | Guardrails ship before capabilities | Hard risk tiers A/B/C; blast radius bounded by structure |
| 6 | Measure or you are guessing | SearchPilot: ~75% of SEO changes inconclusive, 7-8% negative |
| 7 | Route models like money | Strong model ~20% of tokens, cheap tier ~80% |
| 8 | **Optimize the reward function, not proxies** | No detector-evasion, ever. AI-share/rank correlation 0.011 |
| 9 | Few strong models beat many weak ones | Ensembles plateau at 6-10; cap the council at 2-4 |
| 10 | The brain is files that compound | Every run appends to the client case file |
| 11 | Every capability terminates in a paid, verified action | Name the click that buys it and the report that proves it |
| 12 | Name your assets; count honestly | Every published number survivable live |
| 13 | Optimize for the answer, not only the link | Share of answer is a first-class measured outcome |
| 14 | One canonical spine, or the systems rot | Extend a contract, never fork one |

**Laws 15-20** live in `knowledge/doctrine/local-content-laws.md`. Workspace-specific, downstream of Laws 8 and 13.

| # | Law | Enforced by |
|---|---|---|
| 15 | Information gain over coverage | `information_gain_scorer.py` - 30% residual floor |
| 16 | **Experience must be proven, not asserted** | `experience_gate.py` + the SME harvest |
| 17 | Add statistics, citations, operator quotes; never stuff | `geo_page_linter.py`, `keyword_density.py` |
| 18 | A page is not shipped, it is enrolled | `decay_monitor.py` + the client case log |
| 19 | No date without a delta | `/refresh` protocol |
| 20 | No fabricated urgency, scarcity, or proof | G13 + the compliance spine |

Law 15 carries a sharp implication most of the industry gets backwards: Surfer, Clearscope, MarketMuse, and Frase score a draft by how completely it matches the term profile of the current top results, which can only make a page converge on the consensus. Google information-gain patent rewards divergence. So coverage is a floor to clear, never a goal, and **never an auto-fail gate**.

---

## Part 6 - The Google compliance spine (33 hard rules)

`knowledge/doctrine/google-compliance-spine.md`. Severity key: AF = auto-fail, W = warning.

**Group A - Content helpfulness and people-first (6):** A1 people-first purpose (AF) . A2 original value over sources (AF) . A3 satisfying complete answer (W) . A4 no unhelpful automation tells (W, AF with A2) . A5 honest title and headings (W) . A6 content quality execution (W)

**Group B - Spam policy hard lines (9, all AF):** B1 scaled content abuse . B2 doorway pages . B3 keyword stuffing . B4 hidden text and links . B5 cloaking . B6 sneaky redirects . B7 misleading functionality . B8 expired-domain and site-reputation abuse . B9 no thin affiliate or copied merchant content

**Group C - E-E-A-T and YMYL (6):** C1 trust present, not deceptive (AF) . C2 first-hand experience shown, 3+ markers (AF) . C3 author expertise evident (W, AF if YMYL) . C4 YMYL classification applied (AF process gate) . C5 YMYL heightened requirements (AF) . C6 no fabricated E-E-A-T (AF)

**Group D - Structured data content rules (7):** D1 markup matches visible content (AF) . D2 relevant and accurate markup (AF) . D3 no self-serving review markup (AF) . D4 honest ratings, real reviewers (AF) . D5 no deceptive or impersonating markup (AF) . D6 FAQPage no rich-result reliance (W) . D7 schema crawlable (W)

**Group E - Business representation and local accuracy (5):** E1 real business name, no keyword or geo stuffing (AF) . E2 NAP accuracy and consistency (AF) . E3 real accurate location (AF) . E4 honest categories and services (W) . E5 consistent entity across page, schema, and GBP (W)

D3 deserves a call-out because it is the rule most sites break without knowing: putting `aggregateRating` or `review` on your *own* LocalBusiness or Organization node is self-serving review markup and a manual-action surface. `schema_validator.py` flags it specifically.

---

## Part 7 - The gate stack (G0-G13)

Authoritative spec: `knowledge/quality-gates/gates.md`. Binding script map: the gate-stack line in `CLAUDE.md`. Run order is cheap-to-expensive, fail-fast. Two or more warnings on one page escalate to a hold.

| Gate | Name | Script | Type | Threshold / verdict |
|---|---|---|---|---|
| G0 | Intent match and worth-writing | none | judgment | AF. Page must state its one job |
| G1 | First-hand specificity, real local facts | `experience_gate.py`, `information_gain_scorer.py` | mixed | AF, cannot be bypassed. 30% info-gain residual |
| G2 | E-E-A-T presence | none | judgment | AF on money pages, W on thin reference pages |
| G3 | Doorway and thin-content risk | `duplication_gate.py` | deterministic | AF. Jaccard at or above 0.70 on 5-word shingles fails |
| G4 | Passage-block extractability | none | judgment | 80%+ clean = PASS, 60-79% = WARN, under 60% = FAIL |
| G5 | Keyword stuffing | `keyword_density.py` | deterministic | AF. Max exact-phrase density 2.5% |
| G6 | Meta quality | `compliance_lint.py` | deterministic | AF on missing or duplicate title, missing or multiple H1 |
| G7 | Internal-link presence | `link_graph.py` | mixed | Under 2 contextual links = WARN, orphan = FAIL |
| G8 | Readability | `readability_scorer.py` | deterministic | W. FK grade band 6.0-9.0, max 15% sentences over 25 words |
| G9 | Voice fidelity, AI tells | `blocklist_lint.py` | mixed | AF on any Tier-1 or client-banned hit |
| G10 | Source resolution, no fabricated facts | none - agent WebFetch | agent | AF, cannot be overridden. Scripts make no network calls |
| G11 | Schema validity + NAP | `schema_validator.py`, `nap_checker.py` | deterministic | AF on invalid JSON, missing mandatory type, or NAP mismatch |
| G12 | Google compliance spine | `compliance_lint.py` | judgment | AF. Final sign-off across all 33 rules |
| G13 | Conversion readiness | `conversion_linter.py` | mixed | AF on missing `tel:`, competing CTAs, no ask after proof, any fabricated urgency |

Plus `geo_page_linter.py` for the Law 17 GEO levers, and `qa_scorecard.py` as a separate 6-category editorial scorecard with a 3-fail kill gate sitting on top of the numbered gates.

**Why G10 is not a script.** Every script in this system is stdlib-only and makes zero network calls, by design. Source resolution requires fetching a URL and confirming it returns 200 and actually says what the draft claims. That is necessarily an agent WebFetch task. The internal audit caught this mislabeled as a script gate and it was corrected.

---

## Part 8 - Complete .md inventory with use cases

### 8.1 Root and configuration (2)

| File | Use case |
|---|---|
| `CLAUDE.md` | The constitution. Auto-loaded every session. Prime directive, pipeline, load order, gate map, hard rules, directory map |
| `README.md` | Human-facing description of the system and the 4-step run flow. Currently stale on the command list |

### 8.2 doctrine/ (7) - the standard and the rules

| File | Use case |
|---|---|
| `seo-system-doctrine.md` | Laws 1-14 plus Part I mindset, Part III hard lines, Part IV audit protocol, Part V seven frontier bets. Portable across workspaces |
| `local-content-laws.md` | Laws 15-20, the content-writing laws general SEO doctrine does not cover |
| `google-compliance-spine.md` | The 33 hard rules in 5 groups, each with an AF/W severity and a detection method |
| `seo-system-spine.md` | Law 14 implementation: the 6 canonical data contracts (CrawlRecord, Finding, ActionPlan, ChangeOutcome, RuleCatalogEntry, ClientCaseFile) that let sister systems interoperate. Not a duplicate of the doctrine, deliberately factored apart |
| `penalty-casebook.md` | 3 real enforcement cases: Nov 2024 site-reputation-abuse manual actions (Forbes, WSJ, Time, CNN); March 2024 scaled-content enforcement (~1,446 of ~79,000 monitored sites); a regional HVAC per-suburb doorway network losing 80%+ of rankings. Teaches why G3 is auto-fail |
| `ai-search-reality-2026.md` | 10 empirical truths about AI search. Ahrefs March 2026: only 38% of AI Overview citations come from top-10 URLs, down from ~76% seven months earlier. Cited passages run 100-300 words, median 150-200. BrightLocal: 45% of consumers used AI to find a local business in the past year, up from ~6% |
| `llms-txt-verdict.md` | The verdict: do not build it. AI crawlers do not fetch it, Illyes confirmed no Google support July 2025, Mueller compared it to the keywords meta tag, no study shows citation lift. Ship only as an honest unproven courtesy if a client insists |

### 8.3 foundations/ (15) - the reusable mechanics

| File | Use case |
|---|---|
| `search-intent-taxonomy.md` | 6 local intent classes (EMERGENCY, LOCAL-TRAN, NEAR-ME, LOCAL-COMM, LOCAL-INFO, NAV), each mapped to query patterns, page type, and a 6-step SERP classification procedure |
| `eeat-framework.md` | The 4-pillar scoring model with priority Experience over Expertise over Authoritativeness over Trust, the claimed-vs-shown test table, and minimum marker counts per page type |
| `experience-signals.md` | The 7 provable Experience marker types with a PASS test and `brand.yaml` field mapping for each. Home of the provability principle |
| `passage-block-protocol.md` | The exact block format spec. 6-part anatomy, length targets, worked BAD and GOOD examples |
| `schema-library.md` | JSON-LD spec: LocalBusiness with a 13-subtype table, Service, BreadcrumbList, FAQPage, Organization, Person with `hasCredential`, plus the `@id` and `@graph` linking pattern and a full worked example |
| `internal-linking.md` | Anchor-text distribution targets and link-equity flow rules |
| `cluster-graph-protocol.md` | Site topology: 6 node types, two axes (service, geography), money page at the intersection with 2 mandatory parent edges, the orphan rejection rule |
| `keyword-research-method.md` | Free and manual research with no paid APIs. 8 seed-discovery channels, SERP-read grading into Win-now, Winnable-with-depth, Hard-defer |
| `local-gbp-signals.md` | Website-to-GBP alignment. The local ranking triad: Proximity (fixed), Relevance (content lever), Prominence (content lever) |
| `nap-consistency.md` | Byte-level NAP exactness spec, two phone forms (human-readable display and E.164), multi-location and service-area-business handling, 10-item mismatch audit |
| `geo-ai-citation.md` | The AI-citation framework. Track A page-controllable levers vs Track B off-page ops, with the full Princeton study lift table |
| `meta-and-headings.md` | Title and meta specs plus a 6-formula title library and 4 meta-description patterns |
| `citation-description-library.md` | Business description blurbs at 4 fixed lengths for directory and citation consistency |
| `local-link-assets.md` | Link-earning strategy. Ranks sources original-local-data over genuine-usefulness over community over best-of over reclamation. Carries an explicit content-is-necessary-not-sufficient honesty rule |
| `review-content-strategy.md` | The review corpus as ranking and content asset. Sterling Sky finding: review *text*, not just stars, is a relevance signal Google reads |

### 8.4 playbooks/ (11) - one deep spec per page type

Each carries: purpose and the one job, target intent, current SERP and AI reality, section-by-section architecture, best-in-class teardowns, worst and penalty-risk teardowns, compliance notes, voice notes, meta and JSON-LD formulas, and a finished-page checklist.

| File | Page type | Defining constraint |
|---|---|---|
| `service-city-page.md` | Service x city - **the money page** | The Minimum Unique Local Substance bar: 5 hard items. Strip-the-city test plus external-verifiability test, both binary |
| `location-page.md` | City / location hub | Strip-the-city test AND market-insider test. 14-item default skeleton. 2+ named neighborhoods, 1 named local condition, 1 dated job reference as hard minimum |
| `service-page.md` | Service, brand-wide | Un-cityed head term, no spoke cannibalization. Answer in first 100 words. Real price range, never bare contact-us |
| `homepage.md` | Homepage | Four jobs at once: entity anchor, primary conversion, trust surface, internal-link hub. Grunt test in 5 seconds at 375px |
| `about-team-page.md` | About / team | The E-E-A-T and trust surface. Real photos, license numbers as copyable text, values behavioral and falsifiable |
| `service-area-page.md` | Service-area | The doorway decision test runs **first**: every city page must pass a booked-jobs test and a local-proof test, or it does not exist |
| `faq-page.md` | Standalone FAQ | Real-questions gate. Build standalone only at 15+ genuine recurring questions |
| `local-asset.md` | Linkable asset | 4 types: cost guide, data study, best-of, neighborhood guide. Judged on information gain and real first-party input |
| `review-responses.md` | Review replies | 4-beat positive, 5-beat LATER negative, fake-review handling. PII-safe, no templated duplication |
| `review-requests.md` | Review asks | The compliance boundary: no gating, no incentives, same link for everyone |
| `gbp-posts.md` | GBP posts | Opens with THE HONESTY LABEL. Engagement and CTR only. Sterling Sky proved ranking impact is zero; selling it as a ranking lever violates Law 8 |

### 8.5 playbooks/examples/ (10) - vertical teardown libraries

Each file covers all 6 page types with 2+ live-verified good and 2+ bad examples, each tied to a named gate or law, ending with the sharpest insight for that vertical.

| File | The vertical defining hazard and moat |
|---|---|
| `plumbing.md` | Master-plumber license number printed alongside measurable local physics (hard water gpg, gumbo clay, freeze-burst) wins two games at once |
| `hvac.md` | Two opposite emergencies in one market. SEER2 and the R-410A to R-454B refrigerant transition are 2026 freshness signals |
| `roofing.md` | The storm, claim, and certification triad. GAF Master Elite and CertainTeed SELECT are externally verifiable moats |
| `electrical.md` | YMYL by physics, not opinion. The state-board-lookupable license number is the un-fakeable moat; NEC code citations signal real expertise |
| `dental.md` | YMYL at the medical tier. Four cross-cutting gates sit atop every page type, including HIPAA before-and-after consent |
| `personal-injury-law.md` | The verdict and settlement record tied to a named jurisdiction, backed by public court records. Contains the file cleanest contrast pair |
| `med-spa.md` | The moat is the person, not the place. A named licensed injector defeats find-and-replace better than neighborhood copy |
| `auto-repair.md` | The 3-D doorway multiplier: service x make/model x city. The vertical defining hazard |
| `pest-control.md` | Pest pressure by climate, soil, species, and season. Safety claims like 100% non-toxic are an FTC and EPA trap |
| `landscaping.md` | The real project gallery is uncopyable visual proof. Climate and plant-zone specificity is the un-fakeable local substance |

### 8.6 frameworks/ (11) - canonical copy and CRO models

| File | Model | Evidence grade |
|---|---|---|
| `README.md` | Master index plus the page-type x intent routing table and the evidence-grade legend | - |
| `scan-layer-formatting.md` | NN/g F-pattern, message match. Users read ~25% of words. Tap target 44px minimum | **controlled proof** - the best-evidenced file in the library |
| `pas-and-pastor.md` | PAS and PASTOR. Home of emergency and high-pain intent | craft consensus |
| `aida-and-4ps.md` | AIDA and 4Ps. The considered-intent counterpart | craft consensus |
| `storybrand-sb7.md` | SB7 7-part narrative plus the grunt test | craft consensus |
| `cialdini-7-principles.md` | The 7 principles. Fabricated Scarcity is an FTC dark pattern, auto-refuse | craft consensus |
| `schwartz-awareness-sophistication.md` | 5 awareness x 5 sophistication stages. A brief-time selector, not a page section | craft consensus |
| `copyhackers-hero-and-belief.md` | Rule of One, 5-element hero, belief sequencing | craft consensus |
| `value-equation-and-risk-reversal.md` | Hormozi value equation plus a guarantee catalog | flags guarantee-lift percentages as folklore |
| `objection-handling.md` | FAQ as friction reduction, not a help center | GEO study backing |
| `voice-of-customer-mining.md` | The input layer feeding every other framework | craft consensus |

The evidence-grade legend is itself a feature: the library explicitly separates controlled-proof from craft-consensus from folklore, and names two specific claims as folklore not to be quoted (the first-person-CTA-lifts-clicks-90% single Unbounce test, and any guarantee-lift percentage).

### 8.7 voice/ (7) - the layered humanization system

| File | Use case |
|---|---|
| `humanization-layer.md` | The master philosophy. Law 8 governs. Defines the 2-layer stack and the write-time order: draft, then Layer 1 universal, then Layer 2 per-client |
| `vocabulary-blocklist.md` | Tier 1 hard ban (108 machine-parsed terms), Tier 2 context-banned, Tier 3 structural anti-patterns (9), em dash, per-client appends |
| `natural-voice-engineering.md` | 12 named generative techniques, each with mechanism, citation, example, and frequency budget. Plus an AI-tell inversion table and a 10-item naturalness rubric |
| `sentence-rhythm.md` | Measurable rhythm targets and the adjacent-sentence-variance rule |
| `sentence-patterns.md` | 12 named sentence shapes. Use 2-3 per page maximum |
| `hooks-and-titles.md` | Opening-line, H1, hero, and meta patterns. 3 hero hook archetypes |
| `brand-voice-template.md` | The Layer-2 schema mirroring the `brand.yaml` voice block. Forces checkability via contrast pairs, not adjectives |

### 8.8 verticals/ (4) - YMYL overlays

Applied by compliance-auditor on top of the base gate stack, triggered by `brand.yaml.vertical`.

| File | Adds | Sharpest rule |
|---|---|---|
| `legal.md` | LEG-1 to LEG-7. ABA Model Rule 7.1, Rule 1.5(c) | Never promise an outcome; never present a real result as typical without a disclaimer |
| `medical-dental.md` | MED-1 to MED-6. FTC Health Products Compliance Guidance Dec 2022, 45 CFR 164.508 | MED-4: no patient asset without a keyed HIPAA authorization on file |
| `financial.md` | FIN-1 to FIN-6. FINRA Rule 2210(d)(1), SEC Marketing Rule 206(4)-1 | No guaranteed-return or performance promise; regime depends on `registration_type` |
| `home-services.md` | HS-1 to HS-6. California Bus. and Prof. Code 7030.5 | License number required in all advertising; heightened safety-claim scrutiny for YMYL trades |

### 8.9 lifecycle/ (3), quality-gates/ (2), templates/ (3)

| File | Use case |
|---|---|
| `lifecycle/measurement-loop.md` | PUBLISH, ENROLL, MEASURE, DECIDE, ACT. All human-exported CSVs, zero API calls. Defines the required enrollment row |
| `lifecycle/content-decay-refresh-protocol.md` | The decay loop with URL tiers, flag thresholds, the decision gate, and 6 refresh strategies. Capacity cap 3-5 refreshes per month per client |
| `lifecycle/editorial-scorecard.md` | Numeric QA rubric: 6 categories scored 2/1/0, raw score 0-12, kill gate at 3+ fails |
| `quality-gates/gates.md` | The authoritative G0-G13 spec with detect-a-fail methods |
| `quality-gates/README.md` | Run order, escalation policy, deterministic-vs-judgment split |
| `templates/content-brief.md` | The BRIEF-stage input contract, 13 numbered sections |
| `templates/outline-templates.md` | Starter H1/H2 skeletons for all 6 core page types with word-count bands |
| `templates/share-of-answer-prompt-set.md` | The Law 13 measurement contract: a frozen 30-100 query prompt set plus the results CSV spec |

### 8.10 research/expansion-2026-07/ (8) - the evidence base

| File | Territory |
|---|---|
| `00-MASTER-BLUEPRINT.md` | The plan of record. The Experience thesis, the explicit DO-NOT-BUILD list, and the 8-wave build map |
| `01-topical-authority-tooling.md` | How commercial optimizers score (consensus-matching, structurally capped) vs Google information-gain patent. Source of Law 15 |
| `02-local-seo-authorities.md` | Whitespark 2026 weights, Sterling Sky measured studies, BrightLocal survey, Near Media, Local SEO Guide. Source of the review, GBP, and local-asset commands and the verticals folder |
| `03-copywriting-conversion.md` | Catalogs the conversion frameworks and identifies the two gaps: no canonical frameworks library, no conversion gate. Source of G13 |
| `04-geo-ai-search.md` | The Princeton GEO paper, per-engine citation mechanics, and the llms.txt verdict. Source of the share-of-answer protocol |
| `05-competitive-eeat-teardown.md` | Tears down Byword, Koala, SEO.ai, Surfer, Jasper, Cuppa. Names the SME interview as the category only Experience-extraction mechanism: not a feature, it is the moat |
| `06-process-measurement.md` | The post-publish gap. Source of Laws 18-19 and the decay, report, and scorecard scripts |
| `07-internal-audit.md` | A ruthless self-audit. Verdict: doctrine and knowledge are world-class; three real defects found (thin example libraries, broken agent-to-script interfaces, mislabeled deterministic gates). Origin of the Wave 0 fixes |

### 8.11 clients/ and output/

| File | Use case |
|---|---|
| `clients/_template/brand.yaml` | The client fact schema (see Part 10) |
| `clients/sample-dental/brand.yaml` | A filled reference instance demonstrating the medical-dental overlay fields |
| `clients/sample-dental/sme-answers.md` | A filled SME harvest example |
| `output/sample-dental/dental-implants/*` | The 5-file contract, working as a gold test fixture. Its compliance report returns BLOCKED, by design |

---

## Part 9 - Complete .py inventory with use cases and thresholds

**Shared conventions across all 18:** stdlib-only, zero network calls, `--self-test` built in, positional `path` defaulting to `-` for stdin, exit 0 = pass, 1 = fail, 2 = usage error. Several import siblings directly: `compliance_lint` imports `keyword_density.analyse`; four scripts import `strip_markdown` and `split_sentences` from `readability_scorer`.

### 9.1 Gate scripts

**`experience_gate.py`** (292 lines) - **G1, and the enforcement arm of Law 16.** Every falsifiable Experience claim must resolve to a proving artifact.
- CLI: `path`, `--manifest` or `--brand`, `--self-test`
- 4 marker regexes: image, license number, cited source, named team
- 5 claim patterns each mapped to a required proof-category set: years-in-business, review count, rating, volume count, credential
- 7 manifest signal categories: founding_date, review_source, count_source, license_permit, credential_source, photo, named_team
- Fails on `NO_EXPERIENCE_MARKERS` (marker total is zero) or any `UNPROVEN_CLAIM`

**`information_gain_scorer.py`** (301 lines) - **G1, Law 15.** Measures the net-new residual of a draft against a consensus baseline.
- CLI: `path`, `--consensus` or `-c`, `--min-gain` (default **0.30**), `--self-test`
- Method: residual = 1 minus matched_tokens over draft_tokens, via `difflib.SequenceMatcher`
- Emits a net-new inventory of NUMBERS, QUOTES, ENTITIES. Without a consensus file it runs inventory-only and passes

**`duplication_gate.py`** (207 lines) - **G3, hardens rule B1.** Pairwise near-duplicate detection across sibling pages.
- CLI: `paths` (2+ files or a directory), `--threshold` (default **0.70**), `--shingle-size` (default **5**), `--self-test`
- Method: Jaccard similarity over 5-word token shingles. Any pair at or above threshold fails

**`keyword_density.py`** (202 lines) - **G5.** Exact-phrase stuffing detector. Also imported as a library by `compliance_lint`.
- CLI: `path`, `--keyword` (repeatable), `--keywords` (csv), `--brand` (auto-builds service-plus-city phrases), `--max-density` (default **0.025**), `--self-test`
- Formula: density = occurrences x words_in_phrase / total_words
- The **2.5% ceiling is the single canonical density threshold**, reused identically in `compliance_lint.py` and `geo_page_linter.py`

**`compliance_lint.py`** (499 lines) - **G6 and G12.** Static red-flag lint across headings, meta, thin sections, stuffing, em dash, and schema-NAP match.
- CLI: `path`, `--keyword` or `--keywords`, `--min-section-words` (default **40**), `--max-density` (default **0.025**), `--schema`, `--root`, `--strict`, `--self-test`
- Meta bands: title **50-60** chars, description **150-160** chars
- 16 issue codes including `MISSING_H1`, `MULTIPLE_H1`, `THIN_SECTION`, `KEYWORD_STUFFING`, `OVER_EXACT_HEADING` (more than 2 uses), `EM_DASH`, `SCHEMA_NAP_MISMATCH`
- Fails on any error, or on warnings under `--strict`

**`readability_scorer.py`** (213 lines) - **G8.** Flesch Reading Ease and Flesch-Kincaid grade with a self-implemented syllable counter.
- CLI: `path`, `--min-grade` (default **6.0**), `--max-grade` (default **9.0**), `--long-sentence` (default **25** words), `--max-long-ratio` (default **0.15**), `--self-test`
- flesch_ease = 206.835 - 1.015 x wps - 84.6 x spw; fk_grade = 0.39 x wps + 11.8 x spw - 15.59

**`blocklist_lint.py`** (396 lines) - **G9.** Scans for Tier-1 AI-tell vocabulary parsed live from `knowledge/voice/vocabulary-blocklist.md`.
- CLI: `path`, `--blocklist`, `--banned` (repeatable), `--self-test`
- Currently parses **108 Tier-1 regex terms** across 5 categories: Phrases 40, Adjectives 27, Verbs 25, Nouns and metaphors 12, Tricolons 4. Organized into **81 synonym groups** so 2+ synonyms on one line trip a stacked-group flag
- 16 allow-markers plus an allow-signal regex (currency sign, digit, percent, lic, license, hash) suppress hits where a real number makes the word literal
- Notably, the term list is **not hardcoded** - it is parsed from the markdown at runtime, so editing the blocklist doc changes the gate

**`schema_validator.py`** (405 lines) - **G11.** JSON-LD validation.
- CLI: `path`, `--string`, `--self-test`
- 35 LocalBusiness subtypes; required-field map for LocalBusiness, Service, BreadcrumbList, FAQPage, Person, Organization; 5 required address fields
- Geo range checks: latitude -90 to 90, longitude -180 to 180
- **The standout check:** flags `aggregateRating`, `review`, or `reviews` on the business own LocalBusiness or Organization node as self-serving review markup, enforcing spine rule D3

**`nap_checker.py`** (318 lines) - **G11.** NAP byte-consistency across page files versus canonical `brand.yaml`.
- CLI: `files...`, `--brand`, or explicit `--name --phone --street --city --region --postal`, `--self-test`
- 14 abbreviation groups (street, avenue, boulevard, road, drive, lane, suite, apartment, N/S/E/W, highway, parkway)
- Phone matching tolerates country codes via a 7-digit-minimum suffix match
- Three-way verdict per field: exact match = pass, format difference = variant, absent = miss

**`conversion_linter.py`** (372 lines) - **G13.** Deterministic pre-check for the conversion elements.
- CLI: `path`, `--intent` urgent or considered, `--strict`, `--self-test`
- Regex families: 7 lead-CTA patterns, 6 mechanical-verb patterns, 10 off-goal patterns, 6 price patterns, 10 guarantee patterns, plus a `tel:` matcher
- 7 codes. ERRORS: `MISSING_CLICK_TO_CALL`, `NO_CTA`, `NO_CTA_AFTER_PROOF_FAQ`. WARNINGS: `OFF_GOAL_CTA`, `WEAK_CTA_VERB`, `MISSING_PRICE_SIGNAL`, `MISSING_GUARANTEE`
- Note: `_only_mechanical()` is a stub that always returns False, so that branch is currently dead logic

**`geo_page_linter.py`** (429 lines) - **Law 17 GEO levers.** Scores 6 AI-citation levers.
- CLI: `path`, `--min-stat-density` (default **1.0** per 100 words), `--min-sources` (default **1**), `--min-quotes` (default **1**), `--max-phrase-density` (default **0.025**), `--self-test`
- 16 filler-opener regexes, 29 stopwords, 7 citation cue phrases, a freshness-stamp matcher
- Quotes must span 4+ words to count; a phrase must occur 3+ times to be flagged as repeated

### 9.2 Lifecycle and operations scripts

**`decay_monitor.py`** (294 lines) - **Laws 6, 18, 19.** Joins two GSC CSV exports and ranks a refresh queue.
- CLI: `--current`, `--prior`, `--clicks-drop` (default **20.0%**), `--impr-drop` (default **15.0%**), `--pos-drop` (default **2.0** points), `--self-test`
- Decision by flag count: **0 = ok, 1 = watch, 2 = diagnose, 3 = refresh**

**`qa_scorecard.py`** (293 lines) - The 6-category editorial scorecard with a kill gate.
- CLI: `path`, `--min-sources` (default **2**), `--min-h2` (default **3**), `--max-internal` (default **6**), `--self-test`
- Categories: sourcing, structure, duplication, internal_links, metadata, technical
- Internal-link band **2 to 6**; title **30-65** chars; description **70-160** chars
- Exit **0** PASS, **1** NEEDS-WORK (1-2 fails), **3** KILL (3+ fails)

**`link_graph.py`** (324 lines) - The persistent per-client hub, spoke, and silo graph.
- CLI subcommands: `add`, `report`, `list`, each requiring `--graph`; `--over-link-cap` default **25**
- Detects orphans, over-linked pages, missing spoke-to-hub edges, cross-silo spoke-to-spoke links, dangling targets, and zero-or-multi hub per silo

**`report_builder.py`** (379 lines) - The monthly KPI scorecard from manual GSC, GA4, and GBP CSV exports.
- CLI: `--client`, `--gsc` and `--gsc-prior`, `--ga4` and `--ga4-prior`, `--gbp` and `--gbp-prior`, `--flat-band` (default **1.0%**), `--self-test`
- 10 KPIs. `avg_position` is the only one where down is good
- **Deliberately excluded by design:** third-party Domain Authority, raw keyword count, social shares, GA4 bounce rate. This is Law 8 applied to reporting - no proxy metrics

**`share_of_answer_tracker.py`** (424 lines) - **Law 13.** Per-engine AI citation share from a manually logged results CSV.
- CLI: `results`, `--prompt-set`, `--min-runs` (default **15**), `--self-test`
- Flags any engine-cycle under 15 runs as a low-n sample. Names the biggest gap engine and the page fix

**`review_response_lint.py`** (413 lines) - Lints a batch of review responses.
- CLI: `path`, `--dup-threshold` (default **0.6**), `--self-test`
- 20 off-voice corporate-tell phrases; PII regexes for email, SSN, phone, street address, account number, long number
- Thresholds: a word flagged at 3+ uses in one reply, a bigram at 2+, near-duplicate at Jaccard 0.6 on 3-word shingles, templated opening at the same first-5-token opening reused 3+ times
- ERRORS: PII_SSN, PII_ACCOUNT, PII_ADDRESS, PII_LONGNUM, NEAR_DUPLICATE, EM_DASH

**`voice_fingerprint.py`** (443 lines) - Measures idiolect statistics to seed the `brand.yaml` voice block.
- CLI: `path`, `--top` (default **20**), `--min-count` (default **2**), `--max-filler-ratio` (default **0.15**), `--json`, `--self-test`
- ~90 filler tokens, 26 filler phrases, ~40 imperative CTA verbs
- Sentence bins: short 8 words or fewer, medium 9-20, long over 20
- **The interesting behavior:** it exits 1 if the corpus filler ratio exceeds 15%, meaning it *refuses to learn a voice from AI slop*. This is the one gap where a corpus-trained competitor voice would otherwise beat a template

### 9.3 The hook

**`.claude/hooks/block_em_dash.py`** (33 lines) - PreToolUse hook on Write and Edit. Reads the tool payload from stdin, scans `content`, `new_string`, and `old_string` for U+2014, exits 2 with a stderr message to block. Enforces the founder hard style rule at the filesystem boundary rather than by reminder. **Currently broken at the invocation layer - see Part 11, finding 10.**

---

## Part 10 - Matrices, targets, and practices

Every number below is a real threshold enforced somewhere in the system.

### 10.1 The GEO citation lever table

From the Princeton and Georgia Tech GEO study (KDD 2024, arXiv 2311.09735), as recorded in `foundations/geo-ai-citation.md`. Baseline is 19.3% position-adjusted word count.

| Lever | Result | Lift |
|---|---|---|
| Quotation Addition | 27.8% | about +44% |
| Statistics Addition | 25.9% | about +34% |
| Fluency Optimization | 25.1% | about +30% |
| Cite Sources | 24.9% | about +29% |
| Technical Terms | - | about +20% |
| Easy-to-Understand | - | about +15% |
| Authoritative tone | 21.8% | about +13% |
| Unique Words | - | about +7% |
| **Keyword Stuffing** | **17.8%** | **about -8% (hurts)** |

Two findings the system is built around. First, **fluency beats authority** - the counterintuitive result most GEO advice gets backwards, and the reason the readability gate is treated as a citation lever rather than a UX nicety. Second, **GEO is a leveler**: when all sources optimize, a rank-5 source gained about +115% on Cite Sources while rank-1 sources *lost* 23 to 30% of their share. A page ranking 5th to 12th that is structured for extraction can take citation share from a 1st that is not.

### 10.2 Passage-block targets

| Element | Target |
|---|---|
| Standard block | **120-220 words**, median 150-180 |
| Short-answer opener | 60-120 words |
| FAQ entry | 40-150 words each |
| FAQ section total | 400-800 words |
| Direct answer | first 1-2 sentences of every H2 |

Anatomy: H2 as a real question, direct answer first, supporting specifics, mandatory local specificity, self-contained close, facts only from `brand.yaml`, SME, or cited research.

### 10.3 Sentence rhythm targets

| Band | Length | Share |
|---|---|---|
| Short jab | 5-12 words | 20% minimum |
| Mid | 12-20 words | 40-55% |
| Long sweep | 20-30 words | 15-25% |
| Very long | 31+ words | 0-5%, max 1 per ~250 words |

Plus: no two consecutive sentences within 3 words of each other. First sentence 5-12 words, last 6-15. Paragraphs 1 to 4 sentences standard, 5-6 only when load-bearing. Semicolons capped at 2-3 per page.

### 10.4 E-E-A-T minimum marker counts per page type

| Page type | Experience | Expertise | Authority | Trust |
|---|---|---|---|---|
| About | 3 | 2 | 4 | 4 |
| Service-city (money page) | 3 local | 3 | 2 (1 local) | 3 |
| Location | 3 local | 2 | 2 (1 local) | 3 |
| Service | 2 | 3 | 2 | 3 |
| Homepage | 2 | 1 | 3 | 4 |
| Service-area | 2 | 1 | 2 | 3 |

The 7 provable Experience marker types: original photos, dated results and case data, named team with bios, license and permit and bond numbers, invoice-backed counts and reviews, street-level local detail, operator judgment and failure-mode observation.

**The provability principle:** if a sentence stays true when pasted onto a competitor site, it is asserted, not shown, and it fails.

### 10.5 Anchor text distribution

| Type | Target share |
|---|---|
| Partial-match / descriptive | 40-50% |
| Branded | 15-25% |
| Natural-phrase | 15-25% |
| Bare URL | 5-15% |
| Exact-match | **under 10%**, max once per target site-wide |

Money pages within 2 clicks of homepage, others within 3, flag at 4+. Practical body-link count 3-8 per page.

### 10.6 Meta and heading targets

Title ~50-60 characters (575px), primary keyword in the first 30-40. Meta description ~150-160 characters. Exactly one H1, 3-10 words. City appears in only 1-3 load-bearing H2s. `qa_scorecard.py` uses a looser 30-65 and 70-160 band than the 50-60 and 150-160 in `compliance_lint.py`.

### 10.7 The Minimum Unique Local Substance bar (the money page)

The five hard items a service-city page must carry:

1. 3+ named hyper-local anchors, excluding the city name itself
2. 1+ named causal local condition
3. 1+ externally verifiable proof
4. 2+ city-specific FAQ answers
5. A real local conversion path terminating on-page

Plus a working floor of roughly 50%+ of body content being city-specific. Both binary tests must pass: the **strip-the-city test** (delete the city name; does the page still make sense as this city page?) and the **external-verifiability test**.

### 10.8 Decay and refresh thresholds

Flags: impressions down 15% or worse over 2 consecutive periods, clicks down 20% or worse with flat or falling impressions, CTR down 1pt or more at similar position, position down 2 or more, engaged sessions down 20% or worse. Decision: 1 flag = watch, 2 = diagnose, 3+ = schedule refresh. Capacity cap 3-5 refreshes per client per month. Six strategies: Expand, Update, Refine, Retarget, Merge, Repromote.

### 10.9 Local ranking weight distribution

Whitespark 2026, as recorded in research file 02: GBP 32%, reviews ~20%, on-page 19%, links 15%, behavioral ~8%. NAP consistency carries a practitioner-estimated ~10-11%. All flagged directional.

### 10.10 The brand.yaml schema

The client fact contract. Every local specific on every page traces back to a field here, to the SME interview, or to a cited source.

```yaml
client:        { slug, legal_name, brand_name, founded_year, primary_url }
nap:           { name, phone, street, city, state_region, postal_code, country,
                 geo: {lat, lng} }
schema:        { local_business_type, price_range, opening_hours[], same_as[] }
services:      []
service_areas: []
primary_city:  ""
eeat:
  credentials[] . team[] . proof[] . differentiators[]
  media[]        # {url, caption, geotag, date}
  reviews[]      # {platform, count, rating, profile_url}
  attorneys[]    # legal: {name, bar_number, state, practice_areas}
  providers[]    # medical/dental: {name, credential, license_number, reviewed_by}
  consents[] . registration_type . required_disclaimers[]
  license_bond_insurance{} . warranties[]
vertical:        ""      # legal | medical-dental | financial | home-services
trade_is_ymyl:   false
voice:         { one_line_direction, reading_level, tone_by_context{},
                 banned_phrases[], good_examples[], off_brand_examples[] }
guardrails:    { banned_competitor_mentions[], compliance_notes, review_pii_rule }
case_log:      []        # {date, page, what_worked, client_quirk, outcome}  <- Law 10
```

`case_log` is the compounding mechanism. Law 10 test is that diffing a client case file before and after a run must show growth; no growth means no compounding.

### 10.11 The permission and safety model

`settings.json` encodes a deliberate hierarchy: **`knowledge/` is the constitution and sits behind ask**; `output/` and `clients/` are freely writable; `.env`, `credentials.json`, and service-account files are denied outright; `rm -rf`, force push, and hard reset are denied. Agents can read doctrine freely but cannot silently edit it.

---

## Part 11 - Verified findings: where the system drifts from its own documentation

These were found by direct comparison this session. All are real.

**1. `conversion-optimizer` is an orphaned agent.** Its own file defines it as pipeline stage 5c owning the mandatory G13 gate. Zero of the 16 command files reference it by name. Verified: grep for conversion-optimizer across `.claude/commands/` returns nothing. The write commands jump straight from critical-editor to compliance-auditor. G13 currently only gets run inside compliance-auditor own gate table, which means the judgment layer the agent was written to provide (is the guarantee a real mechanism or a hollow badge, is the price driver honest) is not being applied. **This is the highest-value fix on the list.**

**2. `link-architect` is only wired into `/refresh`.** It is referenced in `refresh.md` and nowhere else. No page-writing command invokes it, so the persistent `link-graph.json` does not get updated when a new page ships. Law 10 compounding claim for the link graph is therefore not currently holding on the write path.

**3. Agent count drift.** CLAUDE.md says 7 agents in two places. There are 9 on disk.

**4. Foundations count drift.** CLAUDE.md says 12 foundations and names 12. There are 15 on disk; `citation-description-library.md`, `local-link-assets.md`, and `review-content-strategy.md` are unlisted.

**5. Law 17 GEO numbers do not match the source table.** `local-content-laws.md` cites quotes +41%, statistics +37%, sources +30%, stuffing -10%. `geo-ai-citation.md` carries the actual study table at +44%, +34%, +29%, -8%. The +37% appears to have been pulled from the live-Perplexity validation row rather than the main table. Direction is identical and the practice is unaffected, but the doctrine file should be reconciled to the foundation file before either number is quoted externally.

**6. gates.md names only 2 of its 13 scripts inline.** Only `schema_validator.py` (G11) and `conversion_linter.py` (G13) appear in the prose. Every other gate-to-script binding lives solely in the CLAUDE.md gate-stack line. gates.md is nominally the authoritative spec, so the authority is split.

**7. README.md is stale.** It lists 6 page-type commands plus 3 operations commands. There are 11 and 5. Missing: `/write-faq-page`, `/write-local-asset`, `/write-review-responses`, `/write-review-requests`, `/write-gbp-posts`, `/refresh`, `/report`.

**8. Minor: FAQ rich-result certainty conflict.** `objection-handling.md` states deprecation as settled fact as of May 2026; `schema-library.md` hedges with largely-gone-verify-current-state. Both converge on the same practical guidance, so this is wording, not substance.

**9. Minor: `conversion_linter.py:172` `_only_mechanical()` always returns False.** Dead branch.

**10. The em-dash hook is broken and currently blocks every Write and Edit in this workspace.** The command string in `settings.json` uses Windows backslashes, and at invocation the path collapses to a mangled form with the separators stripped and the directory doubled. Python then fails with No such file or directory, the harness surfaces it as a PreToolUse hook error, and the tool call aborts. The practical effect is that the style guard is not actually guarding anything (it never inspects content) while also making the Write and Edit tools unusable here. This document had to be written through a shell heredoc as a result. Fix is a one-line change to the command value in `settings.json` (forward slashes, or a properly escaped path), which sits behind the ask permission and so needs an explicit go.

**Verified as already fixed:** the Wave 0 agent-to-script interface defect recorded in the internal audit. No stale script name (`nap_check.py`, `readability.py`) appears anywhere in `.claude/` or `knowledge/`, and all 18 referenced script paths resolve.

---

## Part 12 - What the system is trained on

Not model weights. The system is trained in the sense that its judgment is encoded as versioned files (Law 4), sourced from an auditable evidence base.

**Primary-source Google documentation:** the spam policies, the helpful-content guidance, the structured-data content rules, the business-representation rules, and the Quality Rater Guidelines (September 11 2025 revision, 182 pages) - together yielding the 33-rule spine.

**Controlled studies and measured data:** the Princeton and Georgia Tech GEO study (KDD 2024) for the citation levers; NN/g eye-tracking for the scan layer, the single controlled-proof-grade item in the frameworks library; the SearchPilot A/B corpus for the 75%-inconclusive figure behind Law 6; the 600k-page AI-share and rank correlation of 0.011 behind Law 8; Self-MoA for the ensemble plateau behind Law 9.

**Industry measurement:** Whitespark 2026 local ranking factors, Sterling Sky measured studies (address hiding, review recency, the zero-ranking-impact GBP post finding), Ahrefs March 2026 on AI Overview citation decoupling, BrightLocal consumer surveys, Near Media, Local SEO Guide.

**Enforcement history:** the November 2024 site-reputation-abuse manual actions, the March 2024 scaled-content enforcement wave, and a documented per-suburb HVAC doorway network collapse.

**Adversarial competitive teardown:** Byword, Koala, SEO.ai, Surfer, Jasper, Cuppa - the analysis that produced the Experience-as-moat thesis.

**Live verticalized teardowns:** roughly 40+ real named business pages across 10 verticals, each graded good or bad against a specific gate, with the URLs recorded.

**Regulatory sources for the YMYL overlays:** ABA Model Rules 7.1 and 1.5(c); FTC Health Products Compliance Guidance (December 2022); 45 CFR 164.508 (HIPAA authorization); FINRA Rule 2210(d)(1); SEC Marketing Rule 206(4)-1; California Bus. and Prof. Code 7030.5; the FTC 2024 fake-reviews rule and dark-patterns guidance.

**The honesty discipline that makes the evidence base usable:** the system labels claim strength everywhere. The frameworks library grades each model controlled-proof, craft-consensus, or folklore, and names two specific folklore claims not to quote. The doctrine flags its own constants as drifting and requiring quarterly re-verification. The master blueprint carries an explicit **DO-NOT-BUILD** list: llms.txt as a GEO feature, GBP posts sold as a ranking lever, any detector-evasion gate, coverage score as an auto-fail, and over-claiming AI citation. A system that documents what it refuses to build is considerably more trustworthy than one that only documents its features.

---

*Generated by direct file read, 2026-07-20 PKT. All 18 scripts verified passing --self-test at time of writing. Counts are disk-accurate, not doc-accurate.*
