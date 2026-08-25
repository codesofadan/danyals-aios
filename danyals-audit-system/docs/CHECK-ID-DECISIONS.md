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
