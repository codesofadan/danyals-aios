# Quality Gates - Index

The pass/fail stack every local page clears before finalize. Full spec: `gates.md`. This is the one-page index and run order.

A page is not "done" until every gate passes with evidence and `compliance-report.md` is written (the Output contract in `CLAUDE.md`). Run by the `compliance-auditor` agent and the `/qa` command; G13 (conversion) is run one step upstream by the `conversion-optimizer` agent and verified in the report. Deterministic gates run as Python checks in `scripts/` (including `conversion_linter.py` for G13); judgment gates are the agent's evidenced pass.

This is method-agnostic quality enforcement, never detector-evasion (Doctrine Law 8). No gate references an AI detector or an AI-score.

## Run order (cheap-to-expensive, fail-fast)

| # | Gate | What it protects | Type |
|---|------|------------------|------|
| G0 | Intent match and worth-writing | the page has a real job and matches query intent | auto-fail |
| G1 | First-hand specificity and real local facts | genuine, un-copyable local detail | auto-fail |
| G2 | E-E-A-T presence | shown (not claimed) experience and trust | auto-fail on money pages, warning on thin reference |
| G3 | Doorway and thin-content risk | unique per-city value, no templated near-duplicates | auto-fail |
| G4 | Passage-block extractability | self-contained citable answers | warning 60-79%, fail below 60% |
| G5 | Keyword-stuffing and over-optimization | natural density, no spam signal | auto-fail |
| G6 | Meta quality (title, description, H1) | unique, specific, one H1, pixel-fit | auto-fail on missing/duplicate, else warning |
| G7 | Internal-link presence | no orphan, contextual links in and out | fail if orphan, warning if under 2 |
| G8 | Readability | target grade band and human rhythm | warning |
| G9 | Voice fidelity | universal humanization + client brand voice | auto-fail on Tier-1 or client-banned hit |
| G10 | Source resolution and no fabricated facts | every claim traces to a real source | auto-fail |
| G11 | Schema validity | valid JSON-LD, mandatory local set, NAP match | auto-fail |
| G12 | Google compliance spine | penalty-proof by Google's own rules | auto-fail |
| G13 | Conversion readiness | the page asks for and earns the call/booking, truthfully | auto-fail on hard misses, warning on soft |

## How to read the types

- **Auto-fail:** blocks finalize on its own, regardless of the rest of the page.
- **Warning:** logged in the compliance report, should be fixed; two or more warnings on one page escalate to a hold.
- A FAIL returns a specific error, reroutes to the fix, re-runs. Max 2 automated retries, then flag the operator (Law 8: refine only against a specific external error, never blind self-refinement).

## The spine of the stack

The three gates that most define local-content quality and most often halt the pipeline:

- **G1 (first-hand specificity)** - the differentiator versus a vanilla LLM. Most-skipped, never allowed to be skipped.
- **G3 (doorway/thin-content)** - the biggest penalty risk in local SEO at scale.
- **G10 (no fabricated facts)** - the last defense against the plausible-but-false local specific.

G12 (compliance spine) is the final compliance sign-off that re-confirms G2, G3, G5, and G10 at the site level plus the regulated-claim and superlative checks, and proves every conversion element is truthful (Law 20). G13 (conversion readiness) is the last quality gate: it checks that those real, compliant elements are arranged to convert (one primary action, click-to-call, outcome CTA verb, price signal, warranted risk-reversal, distributed proof, an ask after the proof and FAQ). The page finalizes only when both pass.

## Output on pass

When all gates pass, `compliance-report.md` is written with each gate marked PASS and its evidence, completing the page package (page.md, schema.json, internal-links.md, compliance-report.md, sources.md). Results append to the client case file so the system compounds (Law 10).
