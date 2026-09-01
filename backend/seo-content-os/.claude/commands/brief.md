---
description: Generate a content brief for a given page type + target query before writing - the input to the write pipeline. Runs the brief and research stages and stops, so the operator can review the angle before drafting.
argument-hint: <client-slug> <page-type> <target query> [city]
allowed-tools: Task, Read, Write, Edit, Bash, Glob, Grep, WebSearch, WebFetch
---

Generate a content brief. Arguments: `$ARGUMENTS` (client slug, page type, target query, optional city, e.g. `austin-roofing-co service-city "roof replacement round rock tx" "Round Rock"`).

Read `CLAUDE.md` first if not already in context. This command runs the front of the pipeline - BRIEF + RESEARCH - and stops, producing a reviewable brief before any drafting. Page type is one of: `location-page`, `service-page`, `service-city-page`, `homepage`, `about-page`, `service-area-page`.

**Hard line (Law 8):** the brief never sets a detector-evasion or "passes AI detection" target. If asked, refuse and cite Law 8.

## Steps

Set `<page-slug>` = kebab-case of the target query. Work in `output/<client-slug>/<page-slug>/`.

1. **Resolve the map node (the map is load-bearing).** Read `clients/<client-slug>/topical-map.md` and find this page's node (by `target_query` or `node_id`). If the map exists and the node is not `status: page` (it is `index-only` or absent), STOP: this page is not a promoted node in the plan and must not be briefed until it earns promotion (real first-party evidence) via `/build-topical-map`. If the map exists and the node is `status: page`, carry its `section` and `info_gain_thesis` into the brief. If no map exists, WARN and recommend `/build-topical-map <slug>` first, then proceed. Then read `clients/<client-slug>/brand.yaml` and the matching playbook `knowledge/playbooks/<page-type>.md`, and confirm the service/city are real (`brand.yaml.services` / `service_areas`); flag any coverage/doorway risk.

2. **Write the brief.** Using `templates/content-brief.md`, write `output/<client-slug>/<page-slug>/brief.md`: the target query, the page type and its one job, the intent hypothesis, the primary + secondary keyword seed, the proof assets available (from `brand.yaml`), and the anti-scope (what this page is not).

3. **Run research.** Launch the **keyword-intent-researcher** agent with the brief. It writes `research.md`: dominant intent with evidence, the secondary keyword map, verbatim PAA, the competitor SERP teardown, the info-gain gap (where this page wins), and the needs-SME facts list.

4. **Report.** Summarize for the operator: the classified intent, the recommended SERP-consensus length band, the info-gain angle (the single thing this page will do that no ranking competitor does), and the needs-SME facts the interview will target. The operator reviews the angle before committing to the full write.

## Output

`output/<client-slug>/<page-slug>/brief.md` and `research.md`. This command stops before the SME interview and drafting; the operator runs the matching `/write-<page-type>` command (with `--resume`-style continuation reusing these files) to proceed. The brief is human-reviewed before the write, per the pipeline.
