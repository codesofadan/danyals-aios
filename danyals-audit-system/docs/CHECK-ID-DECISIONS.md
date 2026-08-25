# Check-ID decisions — what Wave 0 withheld, and why

**Compiled:** 2026-08-25 · **Companion to** the Wave 0 commit (`fix(audit): stop
reporting checks under other checks' names`).

Wave 0 rebound every analyzer that was reporting under another check's name. Six
measurements had an exact checklist row and were simply moved. Five did **not**,
and are now withheld rather than shipped under a borrowed name. Withholding is
reversible and visible in coverage; a wrong label is neither.

Each entry needs one owner decision. The recommendation is engineering's, not a
decision.

---

## O-3 · Two Lighthouse category scores have no checklist row

PageSpeed returns three category scores. Only accessibility has a home.

| Category | Was shipping as | Now |
|---|---|---|
| accessibility | `ON-105` *Generative search optimization* | `TECH-092` *Accessibility analysis* |
| best-practices | `TECH-082` *Malware detection* | withheld |
| seo | `ON-106` *AI crawl readiness analysis* | withheld |

`TECH-092` is a defensible home: it declares `data_sources: [rendered_html,
axe_results]`, and the Lighthouse accessibility category *is* a rendered page
scored by axe-core. The other two have no equivalent row.

**Options.** (a) Add two checklist rows, moving the denominator off 363.
(b) Leave both unreported — the PSI link in the report still reaches them.

**Recommendation: (b).** A Lighthouse best-practices score is a mixed bag
(console errors, deprecated APIs, image aspect ratios) that does not map to a
remediation an operator can action, which is what a checklist row promises.

---

## O-4 · First Contentful Paint has no checklist row

FCP was shipping as `TECH-074` *Semantic HTML structure analysis (technical)*.
The other four PSI metrics have exact rows (`TECH-040`–`043`); FCP does not.

**Options.** (a) Add a row. (b) Leave it unreported — it is a diagnostic for LCP
rather than a target in its own right, and LCP is reported.

**Recommendation: (b).** FCP is not a Core Web Vital and Google does not rank on
it. Adding a row to carry a metric nobody is scored on inflates the denominator.

---

## O-8 · Three analyzers have no checklist row at all

Written, correct, and with nowhere honest to file their output.

| Analyzer | Was shipping as | Measures |
|---|---|---|
| `check_about_contact_pages` | `ON-107` *Semantic HTML structure analysis* | About + Contact page presence (E-E-A-T trust) |
| `check_footer_architecture` | never wired | footer link count sanity (0, or >60) |
| `check_person_schema_completeness` | never wired | Person schema `name`/`url` + bio/sameAs/jobTitle |
| `check_schema_coverage` | never wired | which schema types the page declares |

`ON-107` legitimately belongs to `check_semantic_html_structure` in
`analyzers/ai_search.py`, which emits it correctly. The About/Contact check was
displacing it.

**Recommendation: add rows for About/Contact and Person schema; drop the other
two.** About/Contact is a real E-E-A-T signal for a local business, and Person
schema completeness is actionable. Footer link count is a weak heuristic, and
schema *coverage* overlaps `TECH-035` *Structured data validation* closely enough
that two rows would double-count the same page.

---

## Not a decision: the "8 unwired analyzers" were mostly deliberate

The Wave 0 plan recorded eight analyzers as "written but never called", implying
eight missing checks. On inspection that is not what they are. Four duplicate a
check `onpage.py` already emits:

| Unwired | Duplicates | Already emitted by |
|---|---|---|
| `check_image_filenames` | `ON-069` | `check_image_filename` |
| `check_anchor_text_quality` | `ON-058` | `check_anchor_text_optimization` |
| `check_author_existence` | `ON-029` | `check_author_credibility` |
| `check_h1_title_alignment` | `ON-119` | `check_central_entity_coherence` |

`iter_per_page_extras`'s own docstring states the rule — *"only checks that fill
a genuine GAP (no overlap with onpage.py's emitted check_ids) live here"* — so
these were parked on purpose. Wiring them would put two scores on one check for
one page, which is exactly the `ON-048`/`ON-049` defect Wave 0 removed.

The extras implementations are marginally better (they name counts in
remediation, and carry `examples` in evidence). **If any are revisited it should
be as a replacement for the onpage version, never as a second emitter.**

One was a genuine gap and is now wired: `check_pagination` → `TECH-025`
*Pagination optimization*. Nothing else emitted it, and it reads `rel=next`/
`rel=prev` off the crawled HTML, which is what that row declares it needs.

---

## Still open from the Wave 0 plan, unaffected by this work

`O-1` rollup weightings · `O-2` URL normalisation policy · `O-5` `ON-041`/`ON-042`
· `O-6` Moz pricing · `O-7` idle agents (B3, B4, D2 and all M\* own zero
`ai-assisted` checks while A1 owns 25).

---

# Wave A — Python no longer shadows an agent

**2026-08-25.** Seventeen checks were marked `ai-assisted` in the checklist *and*
computed in Python. Both paths write a finding for the same check, so one run
could carry two verdicts that disagree. On the paid `smileon.pk` run this was
not hypothetical:

| Check | Two verdicts on the same page |
|---|---|
| `ON-048` | `fail 1.5` vs `warn 6.0`, on all 197 pages |
| `ON-049` | `fail 3.0` vs `warn 6.0`, on all 197 pages |
| `LOC-002` | agent `n_a 0.2` vs Python `n_a 0.4` |

All seventeen checklist rows are now `automation: full`. The Python stays, the
model call goes. Consequences, all verified:

- **A5 is retired.** All 7 of its checks were Python-computed, so it now owns
  zero and the dispatcher skips it — no model call at all. It joins B3, B4, D2
  and M1–M5 as an idle agent, which is what **O-7** asks about.
- A1 drops 25 → 19 checks, A3 4 → 1, D1 2 → 1. Smaller prompts, lower cost.
- The automation split moves 276/87 → 293/70.
- Nine checks now count as free-tier runnable (`n(ZERO, True)` 171 → 180).
  They already *ran* free — Python emits regardless of cost class — so this
  corrects the accounting rather than widening the offer.

`tests/test_check_id_bindings.py` now asserts the invariant two ways: from the
YAML, and through the dispatcher. Both were shown to fail when a single row is
reverted.

---

## O-9 · Eight rows declare data their deterministic implementation never reads

These stay excluded from free-tier coverage even though the Python that
implements them runs free and needs none of the declared inputs:

| Check | Declares | What the Python actually reads |
|---|---|---|
| `ON-022` | `serper_top10` | `word_count`, heading count |
| `ON-035` | `gsc_ctr` | the title string |
| `ON-039` | `gsc_ctr` | the meta description string |
| `ON-044` | `google_nl` | term overlap on body text |
| `ON-046` | `serper_top10` | paragraph, list and table counts |
| `ON-048` | `serper_top10`, `otterly` | headings, first paragraph |
| `ON-105` | `otterly` | H2s, schema types |

(`LOC-002` also stays excluded, but correctly — its Python genuinely calls
Google Places.)

**This is a commercial decision, not an engineering one.** Correcting the
`data_sources` would move seven more checks into the free lead-magnet tier.
The test suite deliberately breaks when the free set changes, so this cannot be
done quietly.

**Options.** (a) Correct `data_sources` to what the code reads — free audits get
seven more checks. (b) Leave them — the rows describe a richer future check that
uses ranking and AI-visibility data, and the free tier stays narrower.

**Recommendation: (a) for `ON-035`/`ON-039`/`ON-044`/`ON-046`, (b) for the
rest.** CTR analysis without Search Console and snippet fitness without SERP
data are still useful structural checks; AI-visibility checks (`ON-048`,
`ON-105`) genuinely want Otterly data to mean much, and `ON-022` content depth
is far more useful benchmarked against the ranking set than against a fixed
900-word threshold.

---

## Four heuristics are now the sole source, and one is wrong

Demoting means the Python verdict is all a client gets. Three are thin but
honest. **`ON-027` Expertise signal detection is not:**

```python
numbers = sum(1 for ch in (p.body_text or "") if ch.isdigit())
citations = sum(1 for u in external if ".gov" in u or ".edu" in u or "doi.org" in u)
score = min(10.0, numbers * 0.2 + citations * 2.0)
```

It counts **digit characters anywhere on the page**. Fifty digits — prices, a
phone number, opening hours — scores full marks for "expertise", with no
citation of any kind. On a dental site that is close to guaranteed. `ON-026`
E-E-A-T is a mean of `ON-027`/`ON-028`/`ON-029`, so it inherits the defect.

`ON-035` and `ON-039` share a milder version: any digit in the title or meta
description scores 10.0.

These were masked while an agent produced a second opinion. **They should be
fixed as Wave 3 quality work**, and the fix for `ON-027` is to count cited
statistics rather than digit characters. Flagged here because Wave A is what
made them load-bearing.
