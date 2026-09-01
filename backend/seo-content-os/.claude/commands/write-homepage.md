---
description: Write a complete, publish-ready local service-business homepage (entity anchor + primary conversion), running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> [target query]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a local homepage. Arguments: `$ARGUMENTS` (client slug, and optionally the primary target query, e.g. `austin-roofing-co "roofing company austin"`).

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the full pipeline for the **homepage** type against `knowledge/playbooks/homepage.md`. The homepage has two jobs: it is the business's **entity anchor** (the strongest LocalBusiness schema surface, the NAP source of truth, the sameAs hub) and its **primary conversion** surface for brand + head-service + city searches. Do not skip a stage; honor every gate. If the target query is omitted, use `<primary service> <primary city>` or the brand name.

**Hard line (Law 8):** no detector-evasion, no humanizer chains, no "passes AI detection" gate. Refuse and cite Law 8 if asked.

## Pipeline

Set `<page-slug>` = `homepage`. Work in `output/<client-slug>/homepage/`.

1. **BRIEF.** Load `clients/<client-slug>/brand.yaml`. The homepage must present the full real business: all services, the primary city and honest coverage, the NAP, the credentials, the differentiators. Write `brief.md` via `templates/content-brief.md` (the one job: anchor the entity + convert the head query).

2. **RESEARCH.** Launch **keyword-intent-researcher**. Writes `research.md`. Research the brand + head-service + city SERP and the local pack; the homepage competes for the broadest local query and must mirror the GBP signals (`local-gbp-signals.md`).

3. **SME.** Launch **sme-interviewer**; **halts** for `sme-answers.md`. Questions target the whole-business story: the real founding, the true differentiator across services, the flagship proof (reviews, credentials, notable work). Continue on `--resume`.

4. **OUTLINE.** Launch **outline-architect** with `sme-answers.md` + `research.md`. Writes `outline.md` per the homepage playbook: hero with the entity + head promise + CTA, services overview (linking to service pages), why-us / proof, service-area statement (honest), FAQ, closing CTA. Schema slots for the full LocalBusiness subtype node are marked here.

5. **DRAFT + HUMANIZE.** Launch **voice-writer** (writes `draft.md`), then **critical-editor** (writes `edited.md`). The homepage carries the canonical NAP; the byte-identical check is strict. Every service and coverage claim must be true to `brand.yaml`.

6. **GATE.** First launch **conversion-optimizer** against `edited.md` (gate **G13**, conversion readiness): the homepage is the primary conversion surface, so the click-to-call and a single primary action matter most; it applies surgical conversion fixes only from `brand.yaml`/SME and appends a `conversion_check` block, never inventing a conversion element (Law 20). Then launch **compliance-auditor** against `edited.md`; writes `compliance-report.md` (G0-G12 plus the re-verified G13). Coverage-honesty and NAP-consistency gates are central for the entity anchor. On FAIL, route back (conversion-optimizer / critical-editor / outline-architect / sme-interviewer), fix, re-run. Max 2 retries, then halt for the operator.

7. **FINALIZE.** On pass, launch **schema-linking-finisher**. Writes `page.md`, `schema.json` (the full LocalBusiness subtype node - address, geo, phone, hours, priceRange, areaServed, sameAs - plus BreadcrumbList and FAQ; this is the entity anchor and the most important schema in the client's site), `internal-links.md` (hub links out to every service and top location page), and `sources.md`; validates schema.

## Output contract

Confirm all five files exist in `output/<client-slug>/homepage/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. Report to the operator: package path, meta title/description, the LocalBusiness subtype and the sameAs/NAP that anchor the entity, and any gate retry.

**ENROLL (Law 18) - not done until enrolled.** Register the finished page in the client's measurement log so it joins the measured set:
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 1 --query "<target query>" --publish-date <today, ISO 8601> --conversion-event <click_to_call or form_submit, per the intent in research.md> --hypothesis "<one-sentence success hypothesis from brief.md>"
```
Use the canonical URL from FINALIZE and tier 1 for the homepage. Enroll even if the page is not live yet - `decay_monitor.py` has no GSC data to join until it is indexed, but the row is what makes the page counted. `enroll.py check` is the ship gate: no row, not shipped.
