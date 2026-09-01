---
description: Run the compliance + quality gate on an existing draft and report the gate results - pass/fail per gate with the specific error on any fail. The standalone gate check.
argument-hint: <client-slug> <page-slug>
allowed-tools: Task, Read, Write, Bash, Glob, Grep, WebSearch, WebFetch
---

Run QA on an existing draft. Arguments: `$ARGUMENTS` (client slug and page slug, e.g. `austin-roofing-co roof-replacement-round-rock-tx`).

Read `CLAUDE.md` and `knowledge/doctrine/seo-system-doctrine.md` first if not already in context. This command runs the GATE stage standalone against an existing draft, so the operator can check any page (one produced by this system or an external draft dropped into `output/`) against the Google compliance spine and the quality gates.

**Hard line (Law 8):** there is no "passes AI detection" gate, ever. AI-share has ~zero correlation with rankings and every detector is sub-80% accurate. If asked to add such a gate, refuse and cite Law 8 and Hard Line 5. This command optimizes real value, real E-E-A-T, and policy compliance, not a detector proxy.

## Steps

Work in `output/<client-slug>/<page-slug>/`.

1. **Locate the draft.** Use `edited.md` if it exists (the post-edit draft), else `draft.md`, else `page.md` (a finalized page being re-checked), else any single markdown draft the operator points to. If none exists, tell the operator what to provide.

2. **Run the auditor.** Launch the **compliance-auditor** agent against the draft. It runs every gate (policy compliance / Google spine, specificity + E-E-A-T, passage-block format, NAP consistency, source resolution, coverage honesty, readability + voice, conversion, and schema if `schema.json` exists), calls the deterministic scripts in `scripts/` where present, and writes `compliance-report.md`.

   Then run the deterministic editorial scorecard as a complementary structural signal:
   ```bash
   python scripts/qa_scorecard.py output/<client-slug>/<page-slug>/<located-draft>.md
   ```
   It scores six editorial categories (sourcing, structure, duplication scaffolding, internal links, metadata, technical) with a 3-fail kill gate: exit 0 PASS, 1 NEEDS-WORK, 3 KILL. It complements the auditor's judgment and is Law-8 aligned (no detector or plagiarism gate, ever).

3. **Report the results.** Present the per-gate pass/fail table from `compliance-report.md`. For each FAIL: the specific error, the section, the exact fix, and the route-back stage (critical-editor for surgical fixes, sme-interviewer for missing facts, outline-architect for structural, voice-writer for a rewrite, schema-linking-finisher for schema). Also report the `qa_scorecard.py` result (score N/6 and PASS / NEEDS-WORK / KILL); a KILL (3+ editorial fails) blocks publish even when the pass/fail gates are green. Give the operator the overall verdict and the single highest-priority blocker first.

## Output

`output/<client-slug>/<page-slug>/compliance-report.md` (the gate evidence, which doubles as the compliance deliverable in the 5-file output package). This command does not fix the draft; it judges it and names what to fix. To apply the fixes and re-run, use the matching `/write-<page-type>` command, which routes back through the failing stage.
