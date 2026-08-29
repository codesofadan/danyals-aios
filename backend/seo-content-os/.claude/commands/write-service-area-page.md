---
description: Write a service-area page (coverage without doorway-page spam), running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> [target query or area]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a service-area page. Arguments: `$ARGUMENTS` (client slug, and optionally the target query or the area, e.g. `austin-roofing-co "areas we serve"` or `austin-roofing-co "roofing greater austin"`).

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the full pipeline for the **service-area page** type against `knowledge/playbooks/service-area-page.md`. A service-area page communicates real coverage (the cities/neighborhoods the business genuinely serves) on one page, without becoming a doorway-page farm. Do not skip a stage; honor every gate.

**Hard line (Law 8):** no detector-evasion, no humanizer chains, no "passes AI detection" gate. Refuse and cite Law 8 if asked.

**Anti-doorway + coverage honesty (the defining constraints of this page type):** the service-area page is one page describing genuine coverage, not a template farm of thin near-duplicate city pages. Every named area gets real, specific value (why the business serves it, how, a local detail), and the page claims ONLY the areas in `brand.yaml.service_areas`. Inflating coverage to cities the business does not actually serve is a false claim and a doorway-spam pattern. The outline's anti-doorway check and the gate's coverage-honesty gate both enforce this. If real coverage is thin, the honest page is small and true, not padded.

## Pipeline

Set `<page-slug>` = kebab-case of the target query (e.g. `service-area` or `areas-we-serve`). Work in `output/<client-slug>/<page-slug>/`.

1. **BRIEF.** Load `clients/<client-slug>/brand.yaml`; the coverage list is `brand.yaml.service_areas` and is the ONLY set of areas the page may claim. Write `brief.md` via `templates/content-brief.md` (the one job: communicate real coverage and convert, without doorway spam).

2. **RESEARCH.** Launch **keyword-intent-researcher**. Writes `research.md`. Research how the query surfaces (a coverage/"areas we serve" query vs a head "[service] [region]" query) and what real local specifics each covered area warrants.

3. **SME.** Launch **sme-interviewer**; **halts** for `sme-answers.md`. Questions confirm the real coverage boundary (where does the business actually drive, where does it say no), and pull one real specific per key area (a neighborhood, a local condition, a real job). Continue on `--resume`.

4. **OUTLINE.** Launch **outline-architect** with `sme-answers.md` + `research.md`. Writes `outline.md` per the service-area-page playbook. The anti-doorway check is mandatory: named areas carry unique local detail, coverage matches `brand.yaml.service_areas` exactly, and where individual cities warrant their own depth the outline notes them as candidates for dedicated `/write-service-city-page` pages rather than padding this one.

5. **DRAFT + HUMANIZE.** Launch **voice-writer** (writes `draft.md`), then **critical-editor** (writes `edited.md`). Coverage claims must match `brand.yaml` exactly; each named area carries a real specific or it is a bare list item, not a padded fake-local paragraph.

6. **GATE.** First launch **conversion-optimizer** against `edited.md` (gate **G13**, conversion readiness): it applies surgical conversion fixes only from `brand.yaml`/SME and appends a `conversion_check` block, never inventing a conversion element (Law 20). Then launch **compliance-auditor** against `edited.md`; writes `compliance-report.md` (G0-G12 plus the re-verified G13). Coverage-honesty and anti-doorway are the highest-stakes gates here. On FAIL, route back (conversion-optimizer / critical-editor / outline-architect / sme-interviewer), fix, re-run. Max 2 retries, then halt for the operator.

7. **FINALIZE.** On pass, launch **schema-linking-finisher**. Writes `page.md`, `schema.json` (LocalBusiness subtype with areaServed = the real coverage list + BreadcrumbList + FAQ), `internal-links.md` (link to the dedicated service-city pages that exist, and to the homepage), and `sources.md`; validates schema.

## Output contract

Confirm all five files exist in `output/<client-slug>/<page-slug>/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. Report to the operator: package path, meta title/description, the coverage-honesty verdict (claimed areas == brand.yaml), the anti-doorway verdict, and any cities flagged as warranting their own service-city page. Any gate retry.

**ENROLL (Law 18) - not done until enrolled.** Register the finished page in the client's measurement log so it joins the measured set:
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 2 --query "<target query>" --publish-date <today, ISO 8601> --conversion-event <click_to_call or form_submit, per the intent in research.md> --hypothesis "<one-sentence success hypothesis from brief.md>"
```
Use the canonical URL from FINALIZE and tier 2 for this service-area page. Enroll even if the page is not live yet - `decay_monitor.py` has no GSC data to join until it is indexed, but the row is what makes the page counted. `enroll.py check` is the ship gate: no row, not shipped.
