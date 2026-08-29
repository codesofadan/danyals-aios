---
description: Write a publish-ready linkable local content asset (local cost guide, local data study, "best of / top local" resource page, or neighborhood guide) - built on real first-party data to earn links and AI-answer citations - running the full BRIEF -> RESEARCH -> OUTLINE -> DRAFT -> HUMANIZE -> GATE -> FINALIZE pipeline and emitting the 5-file output package.
argument-hint: <client-slug> <asset-type> [topic or target query]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Write a linkable local asset. Arguments: `$ARGUMENTS` (client slug, asset type, and optionally the topic/target query, e.g. `valley-plumbing cost-guide "water heater replacement cost chandler"` or `valley-plumbing data-study "chandler water heater failure patterns"`). Valid asset types: `cost-guide`, `data-study`, `best-of`, `neighborhood-guide`.

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the full pipeline for the **local asset** type against `knowledge/playbooks/local-asset.md`, with the strategy layer in `knowledge/foundations/local-link-assets.md`. This is not a conversion money page: its job is to **earn links and AI-answer citations** from real first-party substance, then route that earned authority to the money pages. Judge it on referring domains and citations earned, not its own booked-lead rate. Do not skip a stage; honor every gate.

**Hard line (Law 8):** no detector-evasion, no humanizer chains, no "passes AI detection" gate. Refuse and cite Law 8 if asked.

**The first-party-input gate (the defining constraint of this page type).** An asset must be built on a real first-party input the client actually holds and will publish: real prices, real operational data, real deep local knowledge, or a real, verified set of third-party recommendations. If the only input is "generate a generic guide from what is already online", STOP and flag: that fails Law 15 (information gain) by construction, earns no links, and risks scaled-content classification. No real input, no asset.

**The no-fabrication gate (Law 20, hard).** Every statistic, price, data point, and recommendation is real and traceable to a client record or cited research. A fabricated number in a link asset propagates into every page and answer that cites it; it is a hard doctrine violation and a legal/trust exposure. Nothing estimated is presented as measured.

## Pipeline

Set `<page-slug>` = kebab-case of the topic/target query (e.g. `water-heater-replacement-cost-chandler`). Work in `output/<client-slug>/<page-slug>/`.

1. **BRIEF.** Load `clients/<client-slug>/brand.yaml`. Confirm the chosen asset type has a real first-party input available (prices in `brand.yaml` or committed by the client, real operational data, real local knowledge, or verifiable third-party recommendations). If not, STOP and flag the first-party-input gate. Identify the plausible **link audience** (who would cite/link this - publishers, community sites, listed parties, journalists); an asset with no audience is flagged per `local-link-assets.md`. Write `brief.md` via `templates/content-brief.md` (the one job: earn links + citations from real substance, and route equity to money pages).

2. **RESEARCH.** Launch the **keyword-intent-researcher** agent with the brief. It writes `research.md`: the informational/hybrid query surface, the bland consensus answer for this topic (so the information-gain diff can be run later), what competitors' equivalent assets conspicuously lack, and the local facts to verify. Weight it toward the residual over the consensus (Law 15).

3. **SME.** Launch the **sme-interviewer** agent. For an asset this is the **critical** step: it must extract the real first-party data - the actual prices, the actual operational dataset (with sample size and timeframe), the real local knowledge, or the verified recommendations and the honest reason for each. It writes `sme-questions.md` and the pipeline **halts**: surface the questions to the operator and wait for `sme-answers.md`. On `--resume` with a non-empty `sme-answers.md`, continue. If the SME cannot supply real first-party substance, do not ship a rehash; flag it.

4. **OUTLINE.** Launch the **outline-architect** agent with `sme-answers.md` + `research.md`. It writes `outline.md` per the asset type's section spec in `local-asset.md`: passage-block sections, the first-party data assigned to each block, operator quotes assigned (Law 17), the information-gain check (residual over consensus is substantive), the internal links out to the money pages, and the anti-thin verdict.

5. **DRAFT + HUMANIZE.** Launch the **voice-writer** agent with `outline.md` + `sme-answers.md`. It writes `draft.md`: copy to the asset playbook + both voice layers, every price/statistic/data point verbatim from the SME answers or cited research, operator quotes attributed, answer-first passage blocks, descriptive internal-link anchors to money pages. Then launch the **critical-editor** agent; it writes `edited.md` (surgical cuts, the information-gain and genuine-utility checks, source manifest, no-fabrication verification).

6. **GATE.** First launch the **conversion-optimizer** agent against `edited.md` (gate **G13**, conversion readiness): a linkable asset earns links and citations first, so the conversion bar here is light per the local-asset playbook (a soft next-step and contextual links out to the money pages, not a hard CTA that would undercut link-worthiness); it applies only the page-appropriate surgical fixes from `brand.yaml`/SME and appends a `conversion_check` block, never inventing a conversion element (Law 20). Then launch the **compliance-auditor** agent against `edited.md`. It writes `compliance-report.md` with pass/fail per gate (G0-G12 plus the re-verified G13). The highest-stakes gates here: information gain (Law 15), first-party input, no fabricated/estimated-as-measured data (Law 20), FTC disclosure on any "best of" recommendations, and genuine utility. On any FAIL, route back to the stage it names, fix, and re-run. Max 2 retries, then halt for the operator.

7. **FINALIZE.** On GATE pass, launch the **schema-linking-finisher** agent. It writes `page.md`, `schema.json` (the correct type per asset: `Article` for cost-guide/neighborhood-guide, `Dataset` for data-study, `Article` + `ItemList` for best-of; add `FAQPage` where the asset carries Q&A; `BreadcrumbList` always; author/publisher referencing the `LocalBusiness` `@id`; no self-serving `Review`/`AggregateRating`), `internal-links.md` (contextual links OUT to the relevant money pages so earned equity routes to conversion, plus the crawlable resources/guides hub link so the asset is not orphaned), and `sources.md` (every external fact cited, every first-party fact tagged to its client-record source, and the identified link audience recorded). It validates schema via `scripts/schema_validator.py`.

## Output contract

Confirm all five files exist in `output/<client-slug>/<page-slug>/`: `page.md`, `schema.json`, `internal-links.md`, `compliance-report.md`, `sources.md`. The asset is not done until all five exist and every gate passed. Report to the operator: the package path, the meta title/description, the **information-gain verdict** (what real first-party residual makes this asset link-worthy and un-copyable), the identified **link audience** for outreach, the money pages it routes equity to, and any gate that needed a retry. Remind the operator that the asset earns links only with the outreach half of the loop (`local-link-assets.md`); the system wrote the asset and named the audience, the outreach is theirs.

**ENROLL (Law 18) - not done until enrolled.** A linkable asset is an indexable, decay-eligible page; register it in the measurement log so it joins the measured set:
```bash
python scripts/enroll.py add --log clients/<client-slug>/measurement-log.csv --url <canonical URL from FINALIZE> --tier 2 --query "<primary target query from brief.md>" --publish-date <today, ISO 8601> --conversion-event <the asset's goal, e.g. money_page_click> --hypothesis "<one-sentence success hypothesis: the links/citations this asset should earn>"
```
Use tier 2 (a supporting/linkable asset, not a tier-1 money page). Enroll even if the page is not live yet. `enroll.py check` is the ship gate: no row, not shipped.
