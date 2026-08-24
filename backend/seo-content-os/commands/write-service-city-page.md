---
description: Write the money page - a service-in-city combo page (one service x one city) - running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> <service> <city> [target query]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a service-in-city page (the money page). Arguments: `$ARGUMENTS` (client slug, service, city, and optionally the exact target query, e.g. `austin-roofing-co "roof replacement" "Round Rock" "roof replacement round rock tx"`).

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the full pipeline for the **service-city page** type against `knowledge/playbooks/service-city-page.md`. This is the highest-intent, highest-conversion page in local SEO: one service, one city, a ready-to-hire searcher. Do not skip a stage; honor every gate. If the target query is omitted, build it as `<service> <city>`.

**Hard line (Law 8):** no detector-evasion, no humanizer chains, no "passes AI detection" gate. Refuse and cite Law 8 if asked.

**Anti-doorway (critical for this page type):** service-city pages are the most abused doorway-page pattern in local SEO - hundreds of near-identical "[service] [city]" pages with the city name swapped. That is a spam-policy violation with real penalty risk. Every service-city page must carry unique local value: the named neighborhoods, the local conditions that affect this service in this city, a real local project, real local pricing. The outline's anti-doorway check and the gate both enforce this. If the SME cannot supply city-specific specifics, do not ship a templated page; flag it.

## Pipeline

Set `<page-slug>` = kebab-case of the target query. Work in `output/<client-slug>/<page-slug>/`.

1. **BRIEF.** Load `clients/<client-slug>/brand.yaml`; confirm the service is in `brand.yaml.services` AND the city is in `brand.yaml.service_areas`. If either is false, STOP and flag coverage/doorway risk. Write `brief.md` via `templates/content-brief.md`.

2. **RESEARCH.** Launch **keyword-intent-researcher**. Writes `research.md`. Weight it toward this-service-in-this-city specifics: what does the local SERP reward, what local conditions matter, what do competitors' city pages conspicuously lack (usually: any real local specificity).

3. **SME.** Launch **sme-interviewer**; **halts** for `sme-answers.md`. The questions must pull city-specific facts for this service: neighborhoods where this problem is common, a real job done in this city, local pricing, local conditions. These are what make the page non-templated. Continue on `--resume`.

4. **OUTLINE.** Launch **outline-architect** with `sme-answers.md` + `research.md`. Writes `outline.md`. The anti-doorway check is mandatory and must PASS: named-local specifics assigned to sections, and the "could this be any city by swapping the name" test answered NO with evidence.

5. **DRAFT + HUMANIZE.** Launch **voice-writer** (writes `draft.md`), then **critical-editor** (writes `edited.md`). Specificity and anti-doorway are the bar; a section with no city-specific fact gets a fact injected or gets cut.

6. **GATE.** First launch **conversion-optimizer** against `edited.md` (gate **G13**, conversion readiness): this is the highest-intent page, so the click-to-call, the price signal, and the closing ask after proof/FAQ are load-bearing; it applies surgical conversion fixes only from `brand.yaml`/SME and appends a `conversion_check` block, never inventing a conversion element (Law 20). Then launch **compliance-auditor** against `edited.md`; writes `compliance-report.md` (G0-G12 plus the re-verified G13). The doorway gate and coverage-honesty gate are the highest-stakes here. On FAIL, route back (conversion-optimizer / critical-editor / outline-architect / sme-interviewer), fix, re-run. Max 2 retries, then halt for the operator.

7. **FINALIZE.** On pass, launch **schema-linking-finisher**. Writes `page.md`, `schema.json` (LocalBusiness subtype with areaServed = this city + Service node + BreadcrumbList + FAQ), `internal-links.md` (link to the parent service page, the city location page, and sibling service-city pages), and `sources.md`; validates schema.

## Output contract

Confirm all five files exist in `output/<client-slug>/<page-slug>/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. Report to the operator: package path, meta title/description, and specifically the anti-doorway verdict and the local specifics that make this money page un-copyable. Any gate retry.

**ENROLL (Law 18) - not done until enrolled.** Register the finished page in the client's measurement log so it joins the measured set:
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 1 --query "<target query>" --publish-date <today, ISO 8601> --conversion-event <click_to_call or form_submit, per the intent in research.md> --hypothesis "<one-sentence success hypothesis from brief.md>"
```
Use the canonical URL from FINALIZE and tier 1 for this money page. Enroll even if the page is not live yet - `decay_monitor.py` has no GSC data to join until it is indexed, but the row is what makes the page counted. `enroll.py check` is the ship gate: no row, not shipped.
