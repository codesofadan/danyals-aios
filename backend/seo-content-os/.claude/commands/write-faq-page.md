---
description: Write a publish-ready standalone FAQ / Q&A page - a corpus of real customer questions answered as extractable passage blocks for AI-answer citation and trust - running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> [topic scope or target query]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a standalone FAQ / Q&A page. Arguments: `$ARGUMENTS` (client slug, and optionally the topic scope or target query, e.g. `valley-plumbing "plumbing questions chandler"` or `valley-plumbing "water heater faq"`).

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the full pipeline for the **standalone FAQ page** type against `knowledge/playbooks/faq-page.md`. This is the most extraction-native page type in the system: each Q&A is already the shape an answer engine wants. Its job is to win AI-answer citations for the real questions local buyers ask, kill objections, and route intent to the money pages. Do not skip a stage; honor every gate.

This is the **standalone** FAQ page (its own URL, a real question corpus), not the inline FAQ block at the bottom of a conversion page (that block is owned by each page-type playbook, e.g. `location-page.md` 4.10). If the questions are city/service-specific and few, they belong inline; build this page only when a real cross-cutting corpus (15+ real questions) justifies its own destination. If the right home is an inline block, STOP and say so.

**Hard line (Law 8):** no detector-evasion, no humanizer chains, no "passes AI detection" gate. Refuse and cite Law 8 if asked.

**The real-questions gate (the defining constraint).** Every question on the page is a real question a real local customer asks, sourced from the client's inbound questions, GBP Q&A, reviews, or verbatim People-Also-Ask. NEVER invent questions to carry a keyword ("What is the best plumber in [city]? We are the best plumber in [city]."). Keyword-padded pseudo-questions are a named spam tell and the one tactic shown to REDUCE generative citation (Law 17). If the client cannot supply a real question corpus, do not ship a padded page; flag it.

**Answer design (passage-block protocol, binding).** Every answer is answer-first in the first 1-2 sentences, 40-150 words, self-contained, carries a real local specific (Law 15), and closes on a citable line. Every price, timeline, permit rule, and credential is real and traceable to `brand.yaml`, the SME interview, or cited research (Law 20 / G10). A fabricated answer on a page built to be cited is a hard doctrine violation.

## Pipeline

Set `<page-slug>` = kebab-case of the topic scope (e.g. `faq` or `water-heater-faq`). Work in `output/<client-slug>/<page-slug>/`.

1. **BRIEF.** Load `clients/<client-slug>/brand.yaml`. Confirm a real cross-cutting question corpus justifies a standalone page (not a handful of city-specific questions that belong inline). Write `brief.md` via `templates/content-brief.md` (the one job: an extractable, citable answer hub built on real questions, routing intent to conversion).

2. **RESEARCH.** Launch the **keyword-intent-researcher** agent with the brief. It writes `research.md`: the verbatim People-Also-Ask and autocomplete questions for the client's service + city, the informational/hybrid query surface, and the competitor-FAQ gap (the real questions competitors fail to answer, usually anything with a real local specific). This seeds, but does not replace, the client's own questions from the SME step.

3. **SME.** Launch the **sme-interviewer** agent. For an FAQ page this is the **critical** step: it must extract the client's real inbound questions verbatim ("What do customers ask before they book? What do they get wrong? What surprises them about price, timing, or process?") plus the real local answer to each (the price, the timeline, the permit rule, the local condition). It writes `sme-questions.md` and the pipeline **halts**: surface the questions to the operator and wait for `sme-answers.md`. On `--resume` with a non-empty `sme-answers.md`, continue. If the SME cannot supply real questions and real answers, do not fabricate a corpus; flag it.

4. **OUTLINE.** Launch the **outline-architect** agent with `sme-answers.md` + `research.md`. It writes `outline.md` per `faq-page.md`: the real question set clustered by topic (pricing, timing, process, coverage, trust, guarantees), ordered by frequency and commercial intent, each Q&A a passage block with its real local specific and length target assigned, the money-page link assigned to each relevant answer, and the real-questions check (every question sourced, none invented).

5. **DRAFT + HUMANIZE.** Launch the **voice-writer** agent with `outline.md` + `sme-answers.md`. It writes `draft.md`: each answer answer-first, 40-150 words, in the client's real voice (like the owner on the phone), every fact verbatim from the SME answers or cited research, descriptive internal-link anchors to money pages. Then launch the **critical-editor** agent; it writes `edited.md` (surgical cuts, the passage-block and information-gain checks per answer, no-fabrication verification, no keyword-padded pseudo-questions, source manifest).

6. **GATE.** First launch the **conversion-optimizer** agent against `edited.md` (gate **G13**, conversion readiness): per the faq-page playbook's conversion section the bar is a click-to-call and a CTA after the answered objections (not a hard sales pitch on every answer); it applies surgical conversion fixes only from `brand.yaml`/SME and appends a `conversion_check` block, never inventing a conversion element (Law 20). Then launch the **compliance-auditor** agent against `edited.md`. It writes `compliance-report.md` with pass/fail per gate (G0-G12 plus the re-verified G13). The highest-stakes gates here: real questions (no keyword padding), passage-block extractability, information gain per answer (Law 15), no fabricated answers (Law 20 / G10), and FAQPage schema truthfulness. On any FAIL, route back to the stage it names, fix, and re-run. Max 2 retries, then halt for the operator.

7. **FINALIZE.** On GATE pass, launch the **schema-linking-finisher** agent. It writes `page.md`, `schema.json` (`FAQPage` with `mainEntity` mirroring the visible Q&A text **verbatim**, plus `BreadcrumbList`, plus the page-level `LocalBusiness` subtype node for entity clarity, cross-referenced by `@id`; no self-serving `Review`/`AggregateRating`; note in the report that FAQ rich-result stars are NOT expected since the Aug 2023 restriction to gov/health sites - the schema is for machine-readable parsing, not SERP decoration), `internal-links.md` (each relevant answer links to the money page it touches with a descriptive anchor; no link-stuffing), and `sources.md` (every external fact cited, every SME/first-party fact tagged, and the real source of each question recorded). It validates schema via `scripts/schema_validator.py`. Flag the build-side requirement that answer text render in crawlable HTML, not JS-only accordions.

## Output contract

Confirm all five files exist in `output/<client-slug>/<page-slug>/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. The page is not done until all five exist and every gate passed. Report to the operator: the package path, the meta title/description, the **real-questions verdict** (every question sourced, none invented), how many answers are genuinely locally specific and extractable, the money pages each answer routes to, the FAQPage-schema caveat (no rich stars, machine-readable only), and any gate that needed a retry.

**ENROLL (Law 18) - not done until enrolled.** Register the finished page in the client's measurement log so it joins the measured set:
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 2 --query "<target query>" --publish-date <today, ISO 8601> --conversion-event <click_to_call or form_submit, per the intent in research.md> --hypothesis "<one-sentence success hypothesis from brief.md>"
```
Use the canonical URL from FINALIZE and tier 2 for this FAQ page. Enroll even if the page is not live yet - `decay_monitor.py` has no GSC data to join until it is indexed, but the row is what makes the page counted. `enroll.py check` is the ship gate: no row, not shipped.
