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

---

# Wave 1 — the registry, the graph, and the ledger

**2026-08-25.** Five new modules, no new checks. This is the foundation Waves
2–5 register into; it adds nothing a client sees except three bug fixes found
along the way.

## O-2 · URL normalisation — RESOLVED as engineering

`audit_engine/analyzers/urls.py` is now the single definition of "the same
page". Each rule carries its reason in the source; the summary:

| Question | Answer | Why |
|---|---|---|
| `/about` vs `/about/` | same page | Servers serve both and every CMS canonicalises one. Treating them as two invents duplicate-title and orphan findings. |
| `/` vs `/index.html` | same page | Same resource, same bytes. |
| `?utm_source=x` | same page | Identifies a traffic source, not content. Also gclid, fbclid, msclkid, mc_*, utm_*, pk_*. |
| `?page=2`, `?id=7` | **different** pages | Real, distinct resources. Collapsing them would hide genuine duplicate content. |
| `?b=2&a=1` vs `?a=1&b=2` | same page | Order is not meaning. |
| Host case | insensitive | RFC 3986. |
| **Path** case | **sensitive** | Unix servers serve `/About` and `/about` as different files. |
| `#fragment` | stripped | Never sent to the server. |
| `www` vs bare | **different** | This is TECH-013's finding. Collapsing it here would hide the very defect the audit reports. |
| `http` vs `https` | **different** | Same reasoning. |

Credentials in a URL are discarded, because a `userinfo` blob would otherwise
reach `evidence_json` and then a client PDF.

The policy is a dataclass, so any of these can be flipped — but 48 tests pin
the current behaviour, so a change breaks a test rather than quietly redefining
what "duplicate" means to a client.

## What the registry makes impossible

Registration is validated at **import** time, so these become unmergeable
rather than merely tested for: an id no checklist row defines; the same id
registered twice; **Python computing a check the checklist marks `ai-assisted`**
(the Wave A defect, now structurally prevented); a rollup with no declared
inputs. Taxonomy is never passed to the decorator — it comes from the checklist,
so an analyzer cannot contradict its own definition.

## Three defects found while building

1. **`ON-101` returned `n_a` with a remediation.** The scoring model drops
   `n_a` as "not measured", but a remediation renders as an action item, so a
   client saw a fix for a check that reported nothing. Moved to evidence as an
   `opportunity`.
2. **Three checks told a client to edit `.env`** — verbatim: *"Configure
   MOZ_ACCESS_ID + MOZ_SECRET_KEY in .env to enable backlink/DA analysis."*
   That text renders in the client report. Moved to `operator_note` in
   evidence. A static test now fails on any client-facing string naming an
   environment variable.
3. **Click depth was reported as 0 for a homepage that was never crawled** — a
   measurement over a page we never fetched. Now returns "unreachable".

---

## O-6 · ANSWERED — DataForSEO replaces Moz, and Moz was never reachable

`MOZ_ACCESS_ID` and `MOZ_SECRET_KEY` are empty in the engine's `.env`, so all
39 Moz-blocked checks were never going to run. **`DATAFORSEO_LOGIN` and
`DATAFORSEO_PASSWORD` exist in `backend/.env` and authenticate successfully.**

| Endpoint | Price | Buys |
|---|---|---|
| `backlinks/summary` | $0.024/request | domain rank, referring domains, backlink counts |
| `backlinks/backlinks` | $0.024/request | the link list |
| `backlinks/anchors` | $0.024/request | anchor text distribution |
| `on_page/instant_pages` | **$0.00015/result** | rendered page data |
| `on_page/content_parsing` | **free** | structured content extraction |
| `on_page/lighthouse` | $0.005 | Lighthouse without PSI quota |

**Current balance is $0.94864** — about 39 backlink requests. Enough to build
and test against, not enough to run production audits. **This needs topping up
before Wave 8 ships.**

## Two more waves are cheaper than the plan assumed

- **Wave 6 (rendered DOM, 9 checks) was deferred** because shipping Chromium
  beside the API is a real operational risk (R4-22). `FIRECRAWL_API_KEY` is
  live with **1016 credits** (1000/month, renewing 2026-09-16), and
  `on_page/instant_pages` costs $0.00015. Either removes the Chromium problem
  entirely. **Recommend un-deferring Wave 6.**
- **Wave 9 (Search Console, 5 checks)** — `GOOGLE_OAUTH_CLIENT_ID`,
  `_SECRET` and `_REDIRECT_URI` are all present. Still blocked on the
  per-client grant, which is a conversation with the client, not an engineering
  task.

`FOURSQUARE_API_KEY` returns **401 Invalid request token** and should be
treated as dead until replaced. `APIFY_API_TOKEN` authenticates and has a
citation actor configured.

---

# Wave 2 — the response headers

**2026-08-25.** The crawler always had `resp.headers` — it read `content-type`
off them — but `CrawledPage` never stored them, so sixteen declared checks had
no data to run on.

`CrawledPage` gains `headers` and `redirect_hops`, both **appended last with
defaults** so every existing positional construction keeps working.
`redirect_chain` is untouched.

**Credential headers are dropped before storage.** A stored header reaches
`evidence_json` → `findings.json` → the client PDF, and that is the one way
this feature leaks something that matters. `set-cookie`, `cookie`,
`authorization`, `proxy-authorization`, `www-authenticate`, `x-api-key`,
`x-auth-token` and the CSRF pair are removed; values are capped at 2 KB and the
map at 100 keys, because a pathological server can return thousands.

`redirect_hops` records the **status** of each hop. `redirect_chain` stores
only URLs, so a permanent 301 and a temporary 302 look identical to any check
that needs to tell them apart.

## Twelve checks implemented

| Check | Measures | Threshold source |
|---|---|---|
| `TECH-050` | response is compressed at all | — |
| `TECH-051` | gzip (Brotli and zstd count) | — |
| `TECH-052` | Brotli | Google: 15–20% smaller than gzip for text |
| `TECH-053` | cache policy suits the content type | RFC 9111 §5.2.2.1 |
| `TECH-055` | HTTPS end-to-end plus HSTS | RFC 6797 §7.2 |
| `TECH-072` | **time to first byte** | web.dev/ttfb: 800 ms good, 1800 ms poor |
| `TECH-095` | required headers, and version disclosure | RFC 9110 §6.6.1 |
| `TECH-096` | Content-Type, charset, nosniff | — |
| `TECH-098` | HTTP/3 on the wire or via Alt-Svc | — |
| `TECH-099` | origin latency vs network latency | — |
| `TECH-006` | **X-Robots-Tag noindex** | — |
| `TECH-021` | Link-header vs HTML canonical conflict | — |

`TECH-072` is the id that spent months carrying an `interaction_to_next_paint`
measurement under the name "Server response analysis". It now measures what it
says, against Google's own published bands, so a client sees one story from
PageSpeed and from us.

`TECH-006` is the highest-value check in the wave: an `X-Robots-Tag: noindex`
is **invisible in the HTML**. It is the easiest way to deindex a site by
accident and the hardest to spot by looking at the page.

Two judgement calls are marked as such in the source: compression is reported
`n_a` below ~1.5 KB (gzip can make a tiny response *larger*), and HTML cached
beyond an hour is flagged because a published correction cannot reach visitors
who already hold the page.

## Four were NOT implemented, and the ledger now says why

Storing headers did not unblock these, so parking them under
"needs_response_headers" would have been a false excuse. That reason is now
**retired entirely** — a test fails on any reason nobody uses.

- **`TECH-082` Malware detection** — its declared sources (`crawled_html`,
  `http_headers`) *cannot* detect malware; a header scan would be security
  theatre. Google Safe Browsing v4 is free with the existing `GOOGLE_API_KEY`
  and is the correct implementation. **Its declared `data_sources` are wrong** —
  same family as O-9.
- **`ON-070`, `TECH-090`** — need the HTTP response of each *image*. The
  crawler fetches HTML documents only, so both need an image-fetch pass with
  its own budget.
- **`TECH-003`** — needs a site-scope cross-reference of sitemap URLs against
  crawled status. Buildable now; Wave 3.

Ledger: **170 → 158**.

---

# Wave 3 — 33 checks over data already crawled

**2026-08-25.** Twenty site-wide checks over the crawl graph, thirteen per-page
checks over parsed data that was being thrown away. No new inputs, no new
spend.

## The crawl graph (20)

Broken pages: `TECH-012` 404s (separating **linked** 404s, which strand a
visitor, from unlinked ones that cost nothing), `TECH-014` 5xx, `TECH-013` soft
404s — a page returning 200 while telling the visitor it was not found.

Redirects, now possible because `redirect_hops` records the **status** of each
hop: `TECH-016` loops, `TECH-017` chains, `TECH-018` temporary redirects used
for permanent moves. The hop threshold is labelled an **adopted convention** in
its own evidence — Google publishes no hop limit, and the figure everyone
quotes is community lore.

Reachability and duplication: `TECH-009` orphans, `TECH-026` crawl traps,
`TECH-022` duplicate URLs, `TECH-076` duplicate page bodies, `TECH-023`
parameter entry points, `TECH-024` faceted navigation, `TECH-027` indexable
internal search. Domain form: `TECH-059` www, `TECH-060` trailing slash.
Linking: `TECH-068` click depth, `TECH-069` equity flow. Sitemap agreement:
`TECH-004` status, `TECH-003` indexability contradictions, `TECH-083` hidden
pages.

## A false positive caught by running it

The first live run reported `TECH-068` as a **failure**: 6 of 8 pages
unreachable from the homepage. The site was fine. With `--max-pages 8` against
a 108-URL sitemap, pages look unreachable because the pages linking to them
were never fetched.

**That is a measurement of our page cap, not of their site.** `CrawlContext`
now exposes `is_partial` and `coverage`, and the three reachability checks
(`TECH-068`, `TECH-009`, `TECH-083`) return `n_a` with the coverage figure
rather than a fabricated failure. Tests pin both directions: suppressed on a
partial crawl, still reported on a complete one.

## Per-page (13)

`TECH-019` canonical (using the O-2 normalisation, so a trailing-slash
difference is not a false conflict), `TECH-035`/`036`/`093`/`037`/`038`
structured data, `TECH-086` Open Graph, `TECH-087` Twitter cards, `TECH-057`
mixed content, `TECH-074` semantic landmarks, `TECH-067` AMP, `ON-081`
crawlability, `ON-098` slug.

Two are worth naming:

**`TECH-093`** catches the quiet failure — schema that is valid JSON, that
Search Console reports as present, and that never produces a rich result
because a property Google requires is absent. A `Recipe` with no
`recipeIngredient` is the classic.

**`TECH-086`** is precise rather than conventional, because Open Graph has an
exact primary source: ogp.me lists `og:title`, `og:type`, `og:image` and
`og:url` as required. Most SEO thresholds do not get to be this definite, and
the evidence says which authority it is citing.

`TECH-067` reports `n_a` for a page with no AMP and says why: **Google dropped
the Top Stories AMP requirement in 2021**, so absence is not a defect. Only a
page that *claims* AMP is checked.

`TECH-074` and `TECH-069` are two more ids that Wave 0 freed — they were
carrying a First Contentful Paint measurement and an HTTP-version check
respectively.

Ledger: **158 → 125**.
