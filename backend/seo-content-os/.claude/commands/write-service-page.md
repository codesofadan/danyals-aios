---
description: Write a complete, publish-ready service page for one client and one service (brand-wide, not city-specific), running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> <service> [target query]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a service page. Arguments: `$ARGUMENTS` (client slug, the service, and optionally the exact target query, e.g. `austin-roofing-co "roof replacement" "roof replacement services"`).

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the full pipeline for the **service page** type against `knowledge/playbooks/service-page.md`. The job of a service page: rank and convert for a single service brand-wide, with real process detail, real pricing shape, and the failure modes only an operator knows. Do not skip a stage; honor every gate. If the target query is omitted, derive it from the service name.

**Hard line (Law 8):** no detector-evasion, no humanizer chains, no "passes AI detection" gate. If asked, refuse and cite Law 8.

## Pipeline

Set `<page-slug>` = kebab-case of the target query. Work in `output/<client-slug>/<page-slug>/`.

1. **BRIEF.** Load `clients/<client-slug>/brand.yaml`; confirm the service is one the business actually sells (`brand.yaml.services`). Write `output/<client-slug>/<page-slug>/brief.md` (target query, intent, the one job, proof assets) using `templates/content-brief.md`.

2. **RESEARCH.** Launch **keyword-intent-researcher** with the brief. Writes `research.md` (intent, secondary keywords, verbatim PAA, competitor teardown, info-gain gap, needs-SME facts). For a service page, weight the research toward the buyer's decision questions (cost, process, what-can-go-wrong, how-to-choose).

3. **SME.** Launch **sme-interviewer**. Writes `sme-questions.md`; pipeline **halts** for the operator to fill `sme-answers.md`. Focus the questions on real process detail, real price shape, and the failure modes / differentiators for this service. Continue on `--resume` when `sme-answers.md` is non-empty.

4. **OUTLINE.** Launch **outline-architect** with `sme-answers.md` + `research.md`. Writes `outline.md` (passage-block sections per the service-page playbook: what/how/cost/process/why-us/FAQ, word budget, SME embeds, conversion + NAP + schema + Service-schema + link slots).

5. **DRAFT + HUMANIZE.** Launch **voice-writer** (writes `draft.md`), then **critical-editor** (writes `edited.md`). Real pricing shape, process specifics, and failure-mode honesty are the specificity bar for this page type.

6. **GATE.** First launch **conversion-optimizer** against `edited.md` (gate **G13**, conversion readiness): real pricing shape and a risk-reversal at the ask matter for this page type; it applies surgical conversion fixes only from `brand.yaml`/SME and appends a `conversion_check` block, never inventing a price or guarantee (Law 20). Then launch **compliance-auditor** against `edited.md`; writes `compliance-report.md` (G0-G12 plus the re-verified G13). On FAIL, route back to the named stage (conversion-optimizer / critical-editor / outline-architect / sme-interviewer), fix, re-run. Max 2 retries, then halt for the operator.

7. **FINALIZE.** On pass, launch **schema-linking-finisher**. Writes `page.md`, `schema.json` (LocalBusiness subtype + Service node + BreadcrumbList + FAQ), `internal-links.md` (link up to the homepage and across to related services and to city pages for this service), and `sources.md`; validates schema via `scripts/schema_validator.py`.

## Output contract

Confirm all five files exist in `output/<client-slug>/<page-slug>/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. Report to the operator: package path, meta title/description, the real pricing/process specifics that differentiate the page, and any gate retry.

**ENROLL (Law 18) - not done until enrolled.** Register the finished page in the client's measurement log so it joins the measured set:
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 2 --query "<target query>" --publish-date <today, ISO 8601> --conversion-event <click_to_call or form_submit, per the intent in research.md> --hypothesis "<one-sentence success hypothesis from brief.md>"
```
Use the canonical URL from FINALIZE and tier 2 for this brand-wide service page. Enroll even if the page is not live yet - `decay_monitor.py` has no GSC data to join until it is indexed, but the row is what makes the page counted. `enroll.py check` is the ship gate: no row, not shipped.
