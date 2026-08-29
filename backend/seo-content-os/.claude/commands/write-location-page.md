---
description: Write a complete, publish-ready local location/city page for one client and one city, running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> <city> [target query]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a location/city page. Arguments: `$ARGUMENTS` (client slug, city, and optionally the exact target query, e.g. `austin-roofing-co "Round Rock" "roofing round rock tx"`).

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the full pipeline for the **location page** type against `knowledge/playbooks/location-page.md`. Do not skip a stage; honor every gate. If the target query is omitted, derive it from the client's primary service + the city.

**Hard line (Law 8):** this system never does detector-evasion, humanizer chains, or "passes AI detection" work. If asked, refuse and cite Law 8. There is no such gate.

**Anti-doorway (this page type especially):** a location page that is a city-swap template of another city's page is a spam-policy violation. Every section must carry unique, genuinely local value (named neighborhoods, real local facts, SME specifics). The outline and the gate both enforce this; do not ship a templated page.

## Pipeline

Set `<page-slug>` = kebab-case of the target query (e.g. `roofing-round-rock-tx`). Work in `output/<client-slug>/<page-slug>/`.

1. **BRIEF.** Run the `/brief` logic for page type `location-page` and this target query: load `clients/<client-slug>/brand.yaml`, confirm the city is in `brand.yaml.service_areas` (if not, STOP and flag doorway/coverage risk to the operator), and write `output/<client-slug>/<page-slug>/brief.md` (target query, intent hypothesis, the one job of the page, proof assets available). Use `templates/content-brief.md`.

2. **RESEARCH.** Launch the **keyword-intent-researcher** agent with the brief. It writes `research.md` (intent, secondary keywords, verbatim PAA, competitor SERP teardown, the info-gain gap, the needs-SME facts).

3. **SME.** Launch the **sme-interviewer** agent. It writes `sme-questions.md` and the pipeline **halts**: surface the questions to the operator and wait for `sme-answers.md`. If invoked with `--resume` and `sme-answers.md` exists and is non-empty, continue.

4. **OUTLINE.** Launch the **outline-architect** agent with `sme-answers.md` + `research.md`. It writes `outline.md` (passage-block sections, word budget, SME embeds assigned, conversion + NAP + schema + link slots, anti-doorway check).

5. **DRAFT + HUMANIZE.** Launch the **voice-writer** agent with `outline.md` + `sme-answers.md`. It writes `draft.md` (copy to the location-page playbook + both voice layers, SME specifics verbatim, inline-sourced external facts, byte-identical NAP, CTAs). Then launch the **critical-editor** agent; it writes `edited.md` (surgical cuts, specificity + anti-doorway + NAP + voice checks, source manifest).

6. **GATE.** First launch the **conversion-optimizer** agent against `edited.md` (gate **G13**, conversion readiness): it verifies the page asks for and earns the call/booking, applies surgical conversion fixes drawn only from `brand.yaml` and the SME answers, and appends a `conversion_check` block; it never invents a price, guarantee, or urgency (Law 20). Then launch the **compliance-auditor** agent against `edited.md`. It writes `compliance-report.md` with pass/fail per gate (G0-G12 plus the re-verified G13). On any FAIL, route back to the stage it names (conversion-optimizer / critical-editor / outline-architect / sme-interviewer), fix, and re-run the gate. Max 2 retries, then halt and flag for the operator.

7. **FINALIZE.** On GATE pass, launch the **schema-linking-finisher** agent. It writes `page.md`, `schema.json`, `internal-links.md`, and `sources.md`, and validates schema via `scripts/schema_validator.py`.

## Output contract

Confirm all five files exist in `output/<client-slug>/<page-slug>/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. The page is not done until all five exist and every gate passed. Report to the operator: the package path, the meta title/description, the anti-doorway specifics that make this page non-templated, and any gate that needed a retry.

**ENROLL (Law 18) - not done until enrolled.** Register the finished page in the client's measurement log so it joins the measured set:
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 1 --query "<target query>" --publish-date <today, ISO 8601> --conversion-event <click_to_call or form_submit, per the intent in research.md> --hypothesis "<one-sentence success hypothesis from brief.md>"
```
Use the canonical URL from FINALIZE and tier 1 for this location page. Enroll even if the page is not live yet - `decay_monitor.py` has no GSC data to join until it is indexed, but the row is what makes the page counted. `enroll.py check` is the ship gate: no row, not shipped.
