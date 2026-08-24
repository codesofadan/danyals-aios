---
description: Write a complete, publish-ready About / team page (the E-E-A-T and trust surface), running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> [target query]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write an About / team page. Arguments: `$ARGUMENTS` (client slug, and optionally the target query, e.g. `austin-roofing-co "about austin roofing co"`).

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the full pipeline for the **about page** type against `knowledge/playbooks/about-team-page.md`. The About page is the business's **E-E-A-T and trust surface**: the real founding story, the real people (names, roles, years, a specific detail each), the credentials with numbers, the proof. It is where "family-owned since 1998" is made real with the specifics that prove it, or exposed as empty. Do not skip a stage; honor every gate.

**Hard line (Law 8):** no detector-evasion, no humanizer chains, no "passes AI detection" gate. Refuse and cite Law 8 if asked.

**Trust discipline:** the About page is the most damaging place to fabricate. A made-up team member, an invented credential, or a false "since 1998" is a direct trust-penalty and can be a legal problem. Every person, date, and credential comes from `brand.yaml.eeat` or the SME interview, never invented. If the operator does not supply a real detail, the page does not claim it.

## Pipeline

Set `<page-slug>` = `about`. Work in `output/<client-slug>/about/`.

1. **BRIEF.** Load `clients/<client-slug>/brand.yaml` (`eeat.team`, `eeat.credentials`, `eeat.proof`, `founded_year`). Write `brief.md` via `templates/content-brief.md` (the one job: prove experience and trust with real specifics, and convert the trust-checking visitor).

2. **RESEARCH.** Launch **keyword-intent-researcher**. Writes `research.md`. About-page intent is trust-verification and brand-navigational; research what the best local About pages surface (real people, real story, real proof) and the PAA around trust ("is X licensed", "who owns X").

3. **SME.** Launch **sme-interviewer**; **halts** for `sme-answers.md`. Questions pull the real founding moment, the real people and one specific detail each, the credentials with numbers, and the proof (real reviews, awards, notable projects). Continue on `--resume`.

4. **OUTLINE.** Launch **outline-architect** with `sme-answers.md` + `research.md`. Writes `outline.md` per the about-team-page playbook: the real story, the team, the credentials, the proof, the local commitment, CTA. Every section maps to an E-E-A-T marker.

5. **DRAFT + HUMANIZE.** Launch **voice-writer** (writes `draft.md`), then **critical-editor** (writes `edited.md`). The specificity bar is highest here: a team section with no real names/details, or a credentials section with no numbers, fails. Nothing is invented.

6. **GATE.** First launch **conversion-optimizer** against `edited.md` (gate **G13**, conversion readiness): the About page still needs one clear next step (call/booking) after the trust case; it applies surgical conversion fixes only from `brand.yaml`/SME and appends a `conversion_check` block, never inventing a conversion element (Law 20). Then launch **compliance-auditor** against `edited.md`; writes `compliance-report.md` (G0-G12 plus the re-verified G13). The E-E-A-T / specificity gate and the coverage-honesty gate (no invented credentials, no false founding date) are central. On FAIL, route back (conversion-optimizer / critical-editor / outline-architect / sme-interviewer), fix, re-run. Max 2 retries, then halt for the operator.

7. **FINALIZE.** On pass, launch **schema-linking-finisher**. Writes `page.md`, `schema.json` (LocalBusiness subtype + Person nodes for named team members with real credentials + BreadcrumbList; AggregateRating only if real review counts exist), `internal-links.md` (link to homepage, services, and contact), and `sources.md`; validates schema.

## Output contract

Confirm all five files exist in `output/<client-slug>/about/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. Report to the operator: package path, meta title/description, the real E-E-A-T markers surfaced (people, credentials, proof), and any gate retry. Flag explicitly if any expected trust element was missing from `brand.yaml` and could not be claimed.

**ENROLL (Law 18) - not done until enrolled.** Register the finished page in the client's measurement log so it joins the measured set:
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 2 --query "<target query>" --publish-date <today, ISO 8601> --conversion-event <form_submit or click_to_call, per the intent in research.md> --hypothesis "<one-sentence success hypothesis from brief.md>"
```
Use the canonical URL from FINALIZE and tier 2 for this About page. Enroll even if the page is not live yet - `decay_monitor.py` has no GSC data to join until it is indexed, but the row is what makes the page counted. `enroll.py check` is the ship gate: no row, not shipped.
