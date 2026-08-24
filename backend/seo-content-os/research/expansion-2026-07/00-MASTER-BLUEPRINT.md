# SEO-CONTENT-OS - Master Expansion Blueprint

Path to the world's #1 local-SEO content-writing system. Synthesized 2026-07-20 PKT from 7 research territories (files 01-07 in this folder), each live-cited and adversarially graded. This file is the plan of record. Companion evidence lives in the numbered files.

---

## The strategic thesis (what actually makes it #1)

Three independent research streams converge on one moat:

**Experience - the first E of E-E-A-T - is the only ranking and trust signal that cannot be scraped, remixed, or synthesized by any competitor or any model.** It exists only in the business owner and must be extracted on purpose.

- Competitive teardown (05): every commercial AI content tool (Byword, Koala, SEO.ai, Surfer, Jasper, Cuppa) sources from the SERP or the model's parametric memory. None can manufacture first-party Experience. Their strength is volume, which is the exact vector Google penalizes (scaled-content + doorway abuse). We market against volume, not toward it.
- Topical authority (01): the content-optimization SaaS category only scores you toward the SERP consensus. Google's information-gain patent rewards net-new divergence from that consensus. First-party facts are the only durable source of divergence.
- Local authorities (02): review text, first-party stats (price ranges, project counts, settlements), and real local specifics are measured relevance signals, not garnish.

So the number-one system is not the one with the most page types or frameworks. It is the one that **systematically extracts, scores, enforces, and measures first-party Experience**, and closes the loop that proves it ranked and converted. Every recommendation below is ranked by how much it widens that moat.

The current system already holds the doctrine and the knowledge depth (internal audit 07 confirms the 6 playbooks, 10 foundations, doctrine, and gates are genuinely world-class and near-zero-drift). It falls short in four places: broken gate enforcement, thin example libraries, no conversion gate, and no post-publish loop. This blueprint fixes those and then extends the moat.

---

## DO-NOT-BUILD (honest negatives, so we do not ship fake value)

- **llms.txt as a GEO feature** (04). ~10% adoption, AI crawlers skip it, Google will not support it (Illyes Jul 2025), no measured citation lift. Ship a one-paragraph verdict note only.
- **GBP posts sold as a ranking lever** (02). Sterling Sky proved rankings impact is zero. If built, label strictly a CTR/engagement asset. Selling it as ranking violates Law 8.
- **Any detector-evasion / humanizer gate** (all files). Already banned by Law 8. Stays banned.
- **Coverage score as an auto-fail gate** (01). SERP-matching pushes to the mean. Use it as a brief-time floor and a warning only, never a hard gate.
- **Over-claiming "cited by AI engines"** (04, 05). AI citation also depends on off-page consensus we do not control. Claim page-readiness for citation, and measure actual citation; never promise it.

---

## The build map, by wave

Effort key: S = under a session, M = a focused build, L = a large multi-agent build.

### Wave 0 - Fix what is broken (do first, cheap)
Source: internal audit 07. These are defects in what we already shipped.
- **Fix agent-to-script interfaces** [S]. Agents call `scripts/nap_check.py`, `scripts/readability.py` with wrong names and flags; real files are `nap_checker.py`, `readability_scorer.py` with positional paths. Every deterministic gate currently fails silently to "manual." Rename references, align flags.
- **Reclassify G10 source-resolution** [S]. gates.md lists HTTP-200 source checking as an offline script, but scripts cannot make network calls. It is an agent WebFetch task. Fix the label.
- **Tighten eeat-framework Trust marker 8** [S]. Restate the self-serving-review-schema ban where it currently drifts.

### Wave 1 - The Experience moat + gate enforcement (the strategic core)
The highest-leverage wave. Turns the moat from prose into enforced, scored machinery.
- **Law 15: Information gain over coverage** [S]. A page earns rank by what it adds beyond the SERP consensus, not by how completely it matches it. Patent-grounded extension of Law 8.
- **Law 16: Experience must be proven, not asserted** [S]. Every falsifiable Experience claim resolves to a dated first-party artifact (photo, invoice count, permit, named result) or it is cut.
- **`knowledge/foundations/experience-signals.md`** [M]. The catalog of provable Experience marker types per QRG, mapped to brand.yaml fields and SME questions.
- **`knowledge/doctrine/penalty-casebook.md`** [S]. Turns Law 8 from assertion into cited evidence (real doorway/scaled-content/parasite penalties with sources).
- **SME Experience-Extraction upgrade** [M]. Upgrade `sme-interviewer` from "collect facts" to a structured Experience harvest: dated results, before/after, named team, original-photo checklist, street-level proof. Widens the moat at the source.
- **`scripts/information_gain_scorer.py` (FLAGSHIP)** [M]. Generate the bland SERP consensus, diff the draft, score the net-new residual (numbers, named local facts, SME quotes). Offline, no API, no detector. Converts G1 from a qualitative gate into a tracked number that maps to what the patent rewards. No competitor tool does this.
- **`scripts/experience_gate.py`** [M]. Enforces original-photo presence, dated first-party results, named authorship.
- **`scripts/duplication_gate.py`** [M]. Deterministic shingle-similarity across sibling multi-location pages. Hardens the B1 doorway rule (currently judgment-only) so we scale safely where competitors get penalized.
- **Harden existing scripts** [S each]: add self-serving-review-schema check to `schema_validator.py`; add `blocklist_lint.py` (G9 has ~120 lint-ready Tier-1 terms, nothing lints them); add meta-length (60/150-160) and schema-NAP-byte-identity checks to `compliance_lint.py`.

### Wave 2 - The example libraries (your stated priority)
Source: internal audit 07. Current teardown counts are thin and plumbing-skewed (location 1 good/1 bad; homepage, about, service-city have 0 named-live bad examples; 4 of 6 lean plumbing).
- **+~29 good and +~28 bad deep, cited, live-verified teardowns** [L], across at least 6 verticals (plumbing, HVAC, roofing, electrical, dental, legal) x the 6 page types, so a writer building any vertical has an in-vertical model. Each teardown: real URL, what works or fails, why, tied to the gate that catches it. Stored as `knowledge/playbooks/examples/<page-type>/` or appended per playbook.
- **`knowledge/verticals/{legal,medical-dental,financial,home-services}.md`** [L]. YMYL overlay modules (medically-reviewed-by, attorney authorship, license/bond proof) enforced by `compliance-auditor`. Google segments ranking factors by vertical; this is the depth bar competitors miss.

### Wave 3 - The conversion layer (ranks AND converts)
Source: copywriting 03. Every current gate can pass on a page that still converts poorly.
- **`knowledge/frameworks/` canonical library** [M]. One file per model (PAS, AIDA/4Ps, StoryBrand SB7, Cialdini 7, Schwartz awareness x sophistication, Copyhackers hero, value-equation + risk-reversal, objection-handling, scan-layer), fixed format: what / when-local / adaptation / PASS test / anti-pattern / evidence grade. ~80% harvestable from existing playbooks. Kills the drift of re-teaching each framework differently in six places.
- **G13 conversion gate + `conversion-optimizer` agent** [M] (or fold G13 into `critical-editor`).
- **`scripts/conversion_linter.py`** [M]. Flags competing CTAs, missing click-to-call, non-first-person CTA verb, missing price signal, missing guarantee, CTA absent after proof.
- **VoC mining method + framework-selector routing table + no-fabricated-urgency hard line** [S each].

### Wave 4 - GEO / AI-answer optimization
Source: GEO 04. Evidence-backed, mostly small effort.
- **Law: statistics + citations + operator quotes, domain-weighted** [S]. Princeton GEO study: Quotation +44%, Statistics +34%, Cite-Sources +29%, Fluency +30%; keyword-stuffing is the only tactic that hurt (-8%). For the Business/Facts domain local pages live in, substance beats authoritative tone.
- **Local AI-Citation Stack framework** [S]. Splits every brief into page-controllable levers vs off-page ops (GBP, NAP corroboration, Wikidata/sameAs), so a well-written page that is not cited gets diagnosed off-page.
- **`scripts/share_of_answer_tracker.py` + `prompt-set-builder`** [M]. Frozen prompt-set + manually logged results CSV -> citation share per engine with cycle diff. The write-measure-fix loop no competitor content system has. Per-engine is mandatory (Perplexity cites ~46x more than ChatGPT).
- **`scripts/geo_page_linter.py` + `geo-optimize` skill** [M]. Score/rewrite a draft on the evidenced levers (stat density, quote/source presence, direct-answer-first, freshness).
- **`knowledge/doctrine/llms-txt-verdict.md`** [S]. The DO-NOT-BUILD note, written down so it is not re-litigated.

### Wave 5 - The closed loop (measurement + lifecycle)
Source: process 06. The biggest structural gap: the system goes dark after FINALIZE.
- **`scripts/decay_monitor.py` + the PUBLISH -> MEASURE -> DECIDE -> REFRESH framework** [M]. Ingest manual GSC CSV exports (28-day vs prior), flag decay, output a ranked refresh queue. 1 flag = watch, 2 = diagnose, 3 = refresh. Core of Law 6, no API.
- **`/refresh` command + `content-decay-refresh-protocol.md`** [M]. Refreshed content: median +106% traffic, +4.6 positions (Ahrefs). Requires 2-consecutive-period confirmation before spending a slot; cap 3-5/month/client.
- **`scripts/qa_scorecard.py` + `editorial-scorecard.md`** [S]. Numeric 6-category rubric per page, trendable as AI throughput scales.
- **`scripts/link_graph.py` + `link-architect` agent** [M]. Persistent per-client link graph so the Nth page links correctly into the existing N-1 (Law 10 compounding). Enforces spoke-to-hub routing, no 30-link walls.
- **`scripts/report_builder.py` + `/report` command** [M]. Monthly per-client local KPI report from GSC/GA4/GBP exports, one next-action, no vanity metrics.
- **Two laws** [S]: "A page is not shipped, it is enrolled" (register in the decay sheet or it is not done); "No date without a delta" (date-only bumps are signal-gaming under Law 8).
- **Wire FINALIZE to append to the client `case_log`** [S]. Law 10 compounding, currently unwired.

### Wave 6 - Scope expansion (new local content types)
Source: local authorities 02. New commands + playbooks at the same depth bar.
- **`/write-review-responses` + `/write-review-requests`** [M] + `review-content-strategy.md` + `scripts/review_response_lint.py`. Reviews are ~20% of local ranking and review text is a measured signal; we only surface reviews passively today. Highest-value new type.
- **`/write-gbp-posts`** [S], labeled engagement-only.
- **`/write-local-asset`** [M] + `local-link-assets.md` (local resource pages, cost guides). Links are 15%; we produce zero link-worthy assets today.
- **FAQ / Q&A page type** [M] + `citation-description-library.md` (NAP-locked).

### Wave 7 - Voice moat closure
Source: competitive 05. The one place a competitor (Jasper) genuinely beats us.
- **`corpus-voice-ingest` skill** [M]. Ingest the client's existing copy to derive voice params automatically, matching Jasper's corpus-trained voice consistency.

Also: the `.claude/skills/` folder is currently empty. Waves 1-7 populate it (content-completeness, geo-optimize, corpus-voice-ingest, refresh, report).

---

## Recommended sequence

1. **Wave 0** immediately (it is bug-fixing shipped work).
2. **Wave 1 + Wave 2** as the core of "becoming #1": the moat machinery plus the example libraries you asked for. This is where the differentiation is built and made real.
3. **Prove it**: run one real page end-to-end (still never done) to validate the whole chain before building further.
4. **Waves 3-5** to make it rank-and-convert-and-compound.
5. **Waves 6-7** to widen scope and close the last competitive gap.

Doctrine grows from 14 to ~18 laws (15 information gain, 16 experience-proven, 17 stats-citations-quotes, 18 enrolled-not-shipped). Scripts grow from 5 to ~15. Skills from 0 to ~5. Agents from 7 to ~10. Playbook examples roughly triple. Every addition traces to cited evidence in files 01-07.
