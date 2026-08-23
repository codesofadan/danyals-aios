# R4 — Audit tiering — free/standard/deep/type-scoped, one engine, one renderer

**Track:** R4 · **Written:** 2026-08-23 · **Author:** research wave, Phase 1 · **Status:** evidenced decision, gates the audit build
**Repo at time of writing:** commit `79d1036` · **Engine:** `danyals-audit-system/` (20,428 Python LOC, 363 checks, 344 lines of tests)

---

## Decision

We will make the tier a **first-class, engine-resolved object** rather than a caller-assembled argv recipe. The platform passes one `RunPlan` (tier, permitted data-source classes, crawl budget, selected types, externally-supplied run id, vault-injected credentials); the engine freezes it before any analyzer runs, derives the check set **mechanically** from each check's declared `data_sources` in `checklists/*.yaml`, routes every provider call through a `ProviderBroker` that refuses any source outside the plan, records every billable call in a `SpendLedger`, and **exits non-zero with a dedicated spend-violation code if a zero-spend plan ever records a billable call** — so "free costs nothing" is an asserted-and-checked property of the engine, not an intention of the caller. The four tiers are Free (15 pages, the **193 fully-deterministic checks that need no billable provider** — 171 site-only plus the 22 that use the free-of-charge PageSpeed/CrUX APIs, of which 27 are `computed` rollups that must additionally be gated on their upstream inputs having run), Standard (20 pages, **197 checks** with a Search Console connection, 193 without, plus a short AI narrative), Deep (200-300+ pages scaled to the crawled site, **all 363 checks**, 21 agents, competitor set, cost-estimated and confirmed before running), and Type-scoped (onpage 122 / technical 100 / offpage 71 / local 36 / geo 13 / strategy 21, none selected = run all). One document: `report.html` is the deliverable and the PDF is a **print of that exact HTML through Playwright-bundled headless Chromium in the browser worker** — no WeasyPrint, no typesetting path, no system-browser discovery, no fallback chain; charts are inline SVG generated once by `audit_engine/reporters/charts.py` and consumed by both. Findings get a versioned, cause-shaped `fingerprint` (locus kind + locus value + discriminator) that satisfies `UNIQUE (scope_type, scope_id, check_id, fingerprint)`, so 400 broken links from one template are one finding with 400 instances, and a re-run updates `last_seen_at` instead of duplicating. Priority is `impact / effort` where impact is **derived from measured reach, severity, confidence and distance-to-threshold** and effort is derived from the fix's locus/surface/dependencies — with the `impact_usd` column left permanently NULL, because a projected dollar figure is not derivable from anything we measure. A finding may only be reported "fixed" when the check **actually ran**, the **locus was re-observed**, the check **returned pass**, and a **verification evidence blob was stored**. Competitors are the measured pack, frozen per client, compared per-check as facts, never as causal claims. GEO ships as a real audit type built on vendor-documented crawler control (the strongest evidenced check in the set), with `llms.txt` demoted to informational because no major provider documents consuming it. Narrative numbers are emitted by the model as `{{F:<id>:<field>}}` tokens and substituted deterministically, so a fabricated number is structurally impossible rather than merely discouraged.

---

## Context

The audit engine is the strongest asset in the build and the least defended. It is 20,428 lines with 344 lines of tests, it mints its own run identity, it reads its own `.env`, it catches no top-level exception, and it never times itself out — the platform adapter compensates at `backend/integrations/audit_engine.py` but the seam is stdout-parsed prose. **Corrected 2026-08-23:** an earlier draft said "Decision **D-11** vendors it in with a structured exit contract, which means the seam is about to become internal." That is wrong three ways. The seam decision is **D-10**, not D-11; *vendoring* is D-10 **option B** while the *structured exit contract* is D-10 **option A**; and neither decision has been taken — `DECISIONS_REQUIRED.md:140-159` records D-10 as "Decision needed" with the standing recommendation *"A now, C later if audit volume demands it. B only if D-11 says the engine ships to Danyal anyway"*, and this document's own **O-8** lists D-11 as open. So the seam is **not** about to become internal on the recommended path. Everything below is written for option A — harden the subprocess contract (R4-02, R4-57, R4-58) — which is also the only option that stays correct if D-10 later lands on B or C.

Three questions block the build:

1. **What does each tier actually run, and how do we make the free tier's zero-spend guarantee true?** Defect **P0-2** was the free audit running paid providers and committing `$0.00` to the ledger — a denial-of-wallet on an unauthenticated endpoint with no ledger entry to notice it by. The current fix (`build_argv` passes `--mode free`; the CLI hard-clears provider flags at `audit_engine/cli/main.py:577-582` and `:1012-1017`) removes the immediate hole but leaves the guarantee shaped like a caller-side convention. Nothing stops a future analyzer from constructing `SerperClient(api_key=...)` directly, and nothing checks afterwards whether the run actually spent.

2. **Is the report one document or two?** `AUD-012` and `AUD-P4` require the dashboard HTML and the PDF to be the same document. Today `audit_engine/reporters/pdf.py` tries system Chrome/Edge first, then Playwright's Chromium, then WeasyPrint — three renderers, three possible documents, one of which (WeasyPrint) does not run JavaScript and only partially supports the CSS Grid and flexbox the report design uses.

3. **Is a 363-check output a deliverable or a data dump?** Spec §13.4 names it directly: *"A 300-check audit that returns a flat severity-sorted list transfers the prioritisation problem to the client — which is precisely the work an agency is paid to do."* Clustering, impact×effort, delta and fix verification are the difference between a report and an artefact.

Everything below is bounded by the standing constraints: automation ceilings are properties of the task class; CAPTCHA evasion is dropped; no Kubernetes; the builder's name never appears in client-visible output.

---

## Findings

### F1 · The tier axes are currently conflated, and that is the root of the tiering problem

**Conclusion: the engine has three independent axes — spend class, crawl breadth, report density — and today all three are driven off one `--mode` flag. Splitting them is the whole design.**

- Spend class: `--mode free|paid|auto` (`audit_engine/cli/main.py:1008-1037`).
- Crawl breadth: `--max-pages`, defaulting to `CrawlConfig.max_pages_full = 500` / `max_pages_quick = 20` (`audit_engine/config.py:82-84`).
- Report density: derived from spend class — `condensed = str(mode).lower() == "free"` (`audit_engine/reporters/bundle.py:406`), which then drives a hard PDF page cap of 20 (free) or 100 (paid) at `bundle.py:500`.

The consequence is exact and buildable-around: a **Standard** tier — metered, but a routine 20-page check-in — currently cannot exist. Asking for paid providers forces the 100-page uncondensed layout. Asking for the condensed layout forces zero providers. The `condensed` flag must become a plan field, not a function of `mode`.

The type picker has the same shape of problem. `backend/integrations/audit_engine.py:79` declares six types, but `build_argv` can only translate them into coarse provider flags because *"the engine has no per-dimension CLI flag"* (`audit_engine.py:157-162`) — so selecting `geo` means `--agents on`, i.e. **all 21 specialists**, because agents are all-or-nothing. Type scoping is therefore not currently implemented; it is approximated.

### F2 · The check set per tier can be derived mechanically, and the real numbers are known

**Conclusion: every one of the 363 checks already declares its `data_sources`. Classify the 53 distinct sources by cost class once, and the per-tier check set falls out as a set-containment test. No hand-curation, no arbitrary percentage.**

Counted directly from `danyals-audit-system/checklists/*.yaml` on 2026-08-23 (`on-page.yaml` 142, `technical.yaml` 101, `off-page.yaml` 80, `local.yaml` 40 = **363**; every check declares `data_sources`, zero exceptions):

| Permitted source class | Checks that fit | Notes |
|---|---|---|
| Zero-cost only (target site, robots, sitemap, schema, DNS/WHOIS/TLS, computed, rendered DOM, screenshots) | **197** | on-page 99 · technical 82 · off-page 9 · local 7 |
| …of which are `automation: full` (pure Python, no model call) | **171** | the other 26 are `ai-assisted`, i.e. a model call, i.e. billable |
| Zero-cost + PageSpeed/CrUX (free of charge) | **219** (**193** deterministic) | +22 checks, all technical/on-page |
| …+ Search Console (free, needs a client OAuth connection) | **228** (**197** deterministic) | +9 checks |
| Everything (Moz, Serper, Places, Google NL, Otterly, embeddings) | **363** (**276** deterministic, 87 `ai-assisted`) | |

Per-type, with GEO carved out of on-page by owner agent A5 and strategy mapped to owner M2 (`subcategory: scoring`, all 21 zero-cost):

| Type | Total checks | Zero-cost subset | What the free tier runs (zero + `free_quota`, `automation: full`) |
|---|---|---|---|
| `onpage` | 122 | 82 | 72 |
| `technical` | 100 | 81 | 93 |
| `offpage` | 71 | **0** | **0** |
| `local` | 36 | **3** | **1** |
| `geo` (A5) | 13 | 10 | 6 |
| `strategy` (M2 scoring) | 21 | 21 | 21 |
| **sum** | **363** | **197** | **193** |

**Corrected 2026-08-23.** The first version of this table double-counted the 21 M2 `scoring` checks: it subtracted the 13 A5 checks from on-page but left the M2 checks inside their home files as well as in `strategy`, so the totals summed to 384 (= 363 + 21) and the zero-cost column to 218 (= 197 + 21). Under the dimension rule this document actually states — `geo` if `owner_agent == A5`, `strategy` if `owner_agent == M2`, else the checklist file's category — the M2 checks live in `strategy` only, and they are distributed across all four files (off-page 9, on-page 7, local 4, technical 1). The corrected columns sum to 363 and 197 exactly. Counted programmatically from `checklists/*.yaml` on 2026-08-23.

Three consequences worth stating plainly. **First**, the free tier is not a crippled product: 193 fully-deterministic checks (171 site-only plus 22 CWV checks once PageSpeed/CrUX are permitted), carrying 37 critical-default and 89 major-default severities in the 197-check site-only core (39 critical / 87 major in the 193 the free tier actually runs), is a genuinely useful report, which is what `AUD-F9` requires.

**Second**, the free tier's off-page and local sections are emptier than the file-category counts suggest. Nine off-page.yaml checks and seven local.yaml checks are zero-cost, but **all nine off-page ones are M2 rollups** (`OFF-072`-`OFF-080`: link trust, brand trust, authority, toxicity risk, link quality, backlink relevance, brand popularity, off-page sub-rollup, overall off-page score) and four of the seven local ones are too (`LOC-037`-`LOC-040`). At the dimension level the free tier measures **zero** off-page checks and **three** local ones (`LOC-032`/`033`/`034`). `CLAUDE.md:17` mandates that *"the off-page section ALWAYS renders (even when empty of findings) because it carries the Business Citations content block"*, so the free report must label those blocks as universal guidance rather than as measurements, or it becomes padding that reads as findings.

**Third — and this is a defect in the containment rule itself, not just in the counts.** Data-source containment is *necessary but not sufficient*. Twenty-seven of the free tier's 193 checks declare `data_sources: [computed]` only (on-page 13, off-page 9, local 4, technical 1). A `computed` check is a rollup whose real inputs are *other checks*, so containment admits it even when every upstream input was skipped. Run as written, a free audit would emit "Authority score", "Link trust score" and "Backlink relevance score" computed over no link data at all — a fabricated number produced by the very mechanism chosen to prevent fabricated numbers. **`runs_in(plan)` must therefore also require that a check's upstream inputs ran** (see the amended R4-14).

### F3 · Zero-spend must be enforced by a broker plus a ledger, not by clearing flags

**Conclusion: the current guard is a caller-shaped convention at one entry point, and it is never checked after the fact. Replace it with (a) a declared cost class per integration, (b) a broker that is the only way to obtain a client, (c) a transport-level host allowlist, (d) a spend ledger that fails the run.**

The current mechanism, verbatim from source: `if mode == "free": psi = False; moz = False; serper = False; places = False; citations = False` (`audit_engine/cli/main.py:1012-1017`). A grep for the string `mode` across `audit_engine/analyzers/` and `audit_engine/integrations/` returns **zero** functional matches — no analyzer and no integration client consults the run mode. The enforcement lives entirely at the CLI boundary.

That has three failure modes, all realistic:
- a new analyzer imports and constructs an integration client directly;
- a new paid provider is added and someone forgets to add its flag to the clearing block;
- an existing free-mode run spends because a code path was reached that the flags do not gate (e.g. the citations discovery path, which is Serper-backed and gated by a separate `--citations` flag).

None of them would be visible afterwards, because the engine writes no per-run spend record that anyone checks. The `api_calls` table already exists in the engine schema (`audit_engine/db/schema.sql:85-99`, with `provider`, `cost_usd`, `cached`) and is the natural ledger — it is simply not consulted as a gate.

Note also that the definition of "free" needs correcting. `--mode free` currently clears PageSpeed too, and `docs/implementation/KNOWN_LIMITATIONS.md` records this as **T-5/D-1**: *"The free audit loses Core Web Vitals … PageSpeed is genuinely free-tier, so this is an engine inconsistency."* The CrUX API is documented as *"limited to 150 queries per minute per Google Cloud project"* and *"offered without charge"* [crux-api]. PageSpeed Insights is documented as usable *"with or without an API key"* with no billing statement [psi-getstarted]. So the correct requirement is **zero billable spend**, with free-of-charge quota'd APIs permitted and budgeted. That restores CWV to the lead magnet at no cost.

### F4 · One renderer: headless Chromium printing the same HTML the dashboard shows

**Conclusion: HTML + headless-Chromium print-to-PDF is the only option that satisfies "one source, two renderers" with the report design that already exists. WeasyPrint would silently produce a different document; a typesetting path cannot produce the HTML at all.**

**WeasyPrint** (primary, v69.0 docs): supports CSS Paged Media, generated content, bookmarks, hyperlinks, footnotes and custom properties, but flexbox *"works for simple use cases but is not deeply tested"*, CSS Grid *"lacks subgrids and auto-fit/auto-fill"*, [weasyprint-api]. Its **JavaScript** position is `[UNVERIFIED]` against the cited pages: fetched on 2026-08-23, neither the API reference nor the project home states that WeasyPrint does not execute JavaScript. What the home page does state is *"It is based on various libraries but not on a full rendering engine like WebKit or Gecko"* [weasyprint-home], from which no-JS follows but is not documented outright. The rejection does not depend on it — untested flexbox and missing `auto-fit`/`auto-fill` are independently disqualifying for this design. The existing report generator uses `display: flex` for chart rows (`scripts/generate_audit_pdf.py:990`) and `grid-template-columns: 1fr 1fr` / `1fr 1fr 1fr` for chart grids (`:995-996`). A layout engine with untested flexbox is not a second renderer of the same document; it is a second document.

**Typesetting (Typst / LaTeX)**: Typst's own documentation says HTML export *"is still very incomplete and only available for experimentation behind a feature flag. Do not use this feature for production use cases"* and that its primary export targets are PDF, PNG and SVG [typst-html]. Since the dashboard viewer must render HTML (`AUD-004`, `AUD-P4`), a typesetting source forces two authoring paths — exactly the defect. LaTeX has no credible HTML story at all.

**Headless Chromium**: Playwright's `page.pdf()` *"generates a pdf of the page with print css media"* and to use screen media you must call `emulate_media` first [playwright-pdf]; the print-media behaviour and the `emulate_media` requirement are confirmed by direct fetch on 2026-08-23. The further claim that PDF generation is **Chromium-headless only** is `[UNVERIFIED]`: `https://playwright.dev/python/docs/api/class-page` was fetched directly on 2026-08-23 and contains no such statement (the only headless note on it is *"Headless mode doesn't support navigation to a PDF document"*, which is about navigating *to* a PDF, not generating one). It would be settled by locating the sentence in Playwright's own docs or release notes, or by running `page.pdf()` under Firefox and WebKit and recording the error. Nothing in the chosen design depends on it — the design pins Chromium regardless — but the rejection of "any future non-Chromium renderer" does, so do not repeat the claim to anyone until it is sourced. Playwright is already a dependency of the engine (`pyproject.toml` `[project.optional-dependencies] crawl`) and is already used both for crawling (`audit_engine/crawlers/basic.py:227-241`) and for PDF (`audit_engine/reporters/pdf.py:97-110`).

**The fallback chain must go.** `audit_engine/reporters/pdf.py:27-34` discovers a *system* browser from a hardcoded candidate list (`C:\Program Files\Google\Chrome\...`, `/Applications/Google Chrome.app/...`) and prefers it over Playwright's pinned Chromium. On a developer laptop that is one browser version; in the container it is another; and if neither is found it silently falls through to WeasyPrint. Three backends is three documents. Pin one.

Two operational facts that bear on the choice: Chrome removed the old headless mode in **Chrome 132** — `--headless` and `--headless=new` now both run the new headless mode, and old-headless survives only as the standalone `chrome-headless-shell` binary [chrome-headless]. And the platform's own target architecture already calls for splitting the image into `api` (no Chromium, no Playwright, no audit venv) and `worker-browser` (all three), because *"a browser memory spike takes the API with it"* (`docs/audit/TARGET_ARCHITECTURE.md:360`). The renderer decision therefore depends on that split landing first; it is a prerequisite, not a nice-to-have.

**Licensing finding, load-bearing.** The engine hard-depends on `pymupdf>=1.24` (`danyals-audit-system/pyproject.toml:27`) solely as a PDF page-cap safety net. PyMuPDF is *"available under both, open-source AGPL and commercial license agreements"* and advises contacting Artifex *"if you determine you cannot meet the requirements of the AGPL"* [pymupdf-license]. For a white-labelled commercial platform — and especially if **D-11** ships the engine to Danyal — that is a real exposure for a non-essential utility. `pypdf` is BSD-3-Clause and can split, merge, crop and transform pages [pypdf]; it is a drop-in for a page cap.

### F5 · Root-cause clustering and persistent identity are the same problem viewed twice

**Conclusion: clustering must be split into instance grouping (storage) and root-cause presentation (a view). The fingerprint belongs to the first and must never be affected by the second.**

The engine's current dedup is `key = (check_id, page_id, evidence_json[:200])` (`audit_engine/quality/gates.py:161`). That key is *page-scoped and evidence-truncated*: it collapses literal duplicates within one run and nothing else. It cannot express "one template, 42 pages", and because it includes `page_id` (a per-run autoincrement) it is worthless across runs.

The platform's target constraint is `UNIQUE (scope_type, scope_id, check_id, fingerprint)` with a re-run updating `last_seen_at`. That imposes two hard properties on the fingerprint: **stable across runs** (or every re-run creates a new row and every delta is a lie) and **distinct across genuine issues** (or two real problems merge and one is invisible).

The stability requirement rules out three obvious designs:
- **URL in the fingerprint** — a template finding re-fingerprints for every page, and adding one page to the site "creates" a finding.
- **Evidence blob in the fingerprint** — the evidence contains the measured value, which is exactly what changes when the site changes; a title going from 12 to 14 characters would close one finding and open another.
- **DOM hash alone** — a CSS refactor re-fingerprints the entire site and the delta reports hundreds of fixes that did not happen.

The distinctness requirement rules out `check_id` alone (two separately broken templates merge) and URL-prefix clustering alone (fails on flat URL structures and root-heavy CMSes).

### F6 · Impact must be derived from things the engine already measures — and the composite score is currently not comparable across tiers

**Conclusion: there is enough measured signal for a defensible impact model, and exactly zero measured signal for a monetary one.**

Available and measured today: `Verdict.confidence` (0.0-1.0, `audit_engine/analyzers/common.py:23`), `Verdict.score` (0-10), `severity`, and the `pages` table's `crawl_depth`, `page_type`, `indexable`, `word_count` and `is_orphan` (`audit_engine/db/schema.sql:37-56`). Core Web Vitals give a measured distance-to-threshold against published thresholds: LCP good ≤2.5s, INP good ≤200ms, CLS good ≤0.1, all assessed at the **75th percentile** of page loads segmented across mobile and desktop [web-vitals, fetched 2026-08-23]. The **"poor" bounds are not on that page** — it publishes only the "good" thresholds. LCP poor >4.0s is confirmed on the per-metric page [web-vitals-lcp, fetched 2026-08-23]; INP poor >500ms and CLS poor >0.25 are `[UNVERIFIED]` in this pass and would be settled by fetching `web.dev/articles/inp` and `web.dev/articles/cls`. A distance-to-threshold model needs both bounds, so confirm the two open ones before R4-38 is implemented. Competitor pass/fail on the same check gives a measured gap. None of that requires an assertion.

Not available: revenue. The schema carries `impact_usd REAL -- projected monthly $-impact (optional)` (`audit_engine/db/schema.sql:76`). Nothing in the engine can derive that number. A column that invites a plausible invented figure is precisely the failure this project exists to fix.

**A second, quieter defect.** `aggregate()` computes the composite by renormalising over whichever categories produced findings: `for cat, w in weights.items(): v = scores.get(cat); if v is None: continue; total_w += w` (`audit_engine/scorers/aggregator.py:56-63`). A free run produces no measured off-page findings — once the M2 `computed` rollups are excluded by `inputs_ran` (F2, third consequence) `by_category["off-page"]` is empty — so `off_page` is `None`, so the 30% off-page weight of the `general` profile is dropped and the remaining 70% is renormalised to 100%. (On the `local` profile the dropped weight is 15%, and `local` itself is a further 30%, so the distortion is larger still.) **A free score and a deep score are computed over different denominators and are not comparable.** That silently defeats `AUD-021` (deterministic scoring), makes month-over-month deltas meaningless if the tier changes, and makes "you score 62" a number whose meaning depends on which providers happened to be configured.

### F7 · Delta reporting lies by default; the only honest version requires re-observation

**Conclusion: "you fixed 14 issues this month" is true only if the check ran, the locus was re-observed, the check returned pass, and the proof was stored. Anything less reports a skipped provider as a client success.**

The engine already has the raw material: `status: pass | warn | fail | n_a` is a first-class column (`audit_engine/db/schema.sql:69`), so pass findings exist and can be persisted. `/audit-track` already exists as a delta command (`CLAUDE.md`, slash-command table). What does not exist is the distinction between *absent* and *fixed*.

The single most common way this goes wrong in practice is provider-shaped: a Serper key expires, the off-page dimension produces nothing, and a naive diff reports every off-page finding as closed. The second most common is structural: a site redesign changes every template, every template-scoped fingerprint changes, and the delta reports a mass fix. Both must be caught by construction, not by review.

### F8 · GEO is real, but most of the market's GEO advice is not evidenced

**Conclusion: there are three genuinely evidenced GEO check families (crawler control at robots level, crawler control at edge level, and the snippet controls Google names) and a set of structural heuristics that are reasonable but not vendor-confirmed. Ship both; label the second honestly.**

**Evidenced — AI crawler control, per-vendor, with documented consequences:**
- OpenAI documents **OAI-SearchBot** (powers ChatGPT search results; recommended to *allow* so the site appears), **GPTBot** (trains foundation models; recommended to *disallow* to keep content out of training), **OAI-AdsBot**, and **ChatGPT-User** (user-initiated, and *"because these actions are initiated by a user, robots.txt rules may not apply"*) [openai-bots].
- Anthropic documents **ClaudeBot** (training), **Claude-User** (user-initiated web search), and **Claude-SearchBot** (search index quality), each blockable with its own `User-agent` block, and honours `Crawl-delay`; source IPs are published at `claude.com/crawling/bots.json` [anthropic-crawler].
- Perplexity documents **PerplexityBot** (*"To ensure your site appears in search results, we recommend allowing `PerplexityBot`"* — the earlier draft rendered this as a verbatim quote it is not; corrected against the page on 2026-08-23) and **Perplexity-User** (which *"generally ignores robots.txt rules"* because requests are user-initiated), with published IP ranges at `https://www.perplexity.com/perplexitybot.json` and `https://www.perplexity.com/perplexity-user.json` [perplexity-bots].
- Google documents **Google-Extended** as a standalone product token governing whether crawled content *"may be used for training future generations of Gemini models"* and for grounding in Gemini Apps and Vertex AI, and states it **does not affect Search appearance or ranking** [google-crawlers].

That set is a complete, vendor-sourced, checkable matrix. It is the strongest GEO check we can build, and the engine's current implementation is wrong in two ways: `audit_engine/analyzers/geo_ai.py:22-31` lists `Claude-Web` (not in Anthropic's current documentation) while omitting `Claude-User`, `Claude-SearchBot`, `Perplexity-User` and `OAI-AdsBot`; and its parser does a substring match on a lowercased blob (`if f"user-agent: {bot_l}" in raw_lower`, `:74`), which mis-handles grouped user-agent blocks, varied whitespace and case, and `Allow` overrides.

**Evidenced — edge-level blocking, which robots.txt cannot see:** Cloudflare announced on **1 July 2025** that it became *"the first Internet infrastructure provider to block AI crawlers accessing content without permission or compensation, by default"*, and that *"every new domain will now be asked if they want to allow AI crawlers"*; Cloudflare states it *"helps manage and protect traffic for 20% of the web"* [cloudflare-pr]. Its AI Crawl Control product *"works automatically on all Cloudflare plans"*, with Pay Per Crawl in private beta [cloudflare-aicc]. **Therefore a robots.txt-only check is insufficient**: a site can allow every AI bot in robots.txt and still return 403 at the edge, invisibly to its owner. The only way to detect it is to send a request presenting the documented user-agent string and record the status. That is a genuinely novel, defensible, high-value check — and it is also a policy decision, because it means issuing requests with third-party bot user-agent strings (see Open item O-5; it must never run against a stranger's site in the public funnel).

**Evidenced — the controls Google actually names:** Google's AI-features page states *"There are no additional requirements to appear in AI Overviews or AI Mode, nor other special optimizations necessary"* and *"You don't need to create new machine readable files, AI text files, or markup to appear in these features. There's also no special schema.org structured data that you need to add"*, directing owners instead to `nosnippet`, `max-snippet`, `noindex` and `Google-Extended` [google-ai-features, page last updated 2025-12-10]. That makes `max-snippet:0` / blanket `nosnippet` a **real, checkable AI-visibility defect** — and it makes "add schema for AI" an unevidenced recommendation we must not make.

**`llms.txt` — demote to informational.** The proposal itself (Jeremy Howard, published 2024-09-03, v2 2026-08-10) specifies a Markdown file at the site root with an H1, a blockquote summary and H2-delimited link lists, and its own page's strongest adoption claim is that *"The AI labs themselves publish llms.txt files for their own developer docs: OpenAI, Anthropic, and Gemini"* — i.e. that labs **publish** one, not that any lab **consumes** one [llmstxt]. OpenAI's own bots documentation references `/llms.txt` only as an index of its own docs, and says nothing about consuming third-party files [openai-bots]. Google's guidance says no AI text file is needed [google-ai-features]. Secondary reporting puts adoption near 10% of domains with negligible bot traffic to the files [ppc-land, secondary — search-result summary, page not fetched]. The client asked for it (spec §13.4, `[WA-ADAN]` 10/07), so the check stays — but the engine currently returns `warn`/`minor` with the remediation copy *"Not yet a confirmed ranking signal but a fast-trending best practice in 2026"* (`audit_engine/analyzers/geo_ai.py:51-56`). That is vendor-marketing register in a report that is supposed to be evidence-only. It must become `info`, neutral-scored, with an evidenced one-liner.

**Heuristic, ship-but-label:** passage-level citability (a self-contained 40-80 word direct answer high on the page — already `ON-049`), question-shaped headings, table/list snippet fitness (`ON-100/101/102`), semantic HTML for extraction (`ON-107`), and raw-vs-rendered content delta (AI fetchers do not document JS execution). The *measurements* are exact; the *consequence* is inferred. Google's passage ranking exists but I could not confirm it from a primary Google Search Central page (see O-9).

**Measurement, not inference:** whether the client is actually cited in AI Overviews / ChatGPT / Perplexity is a measurement requiring a provider. `CLAUDE.md` lists Otterly.AI as an integration and notes it is *"not used by /audit"*. Without a contracted provider the report must say **"not measured"** — never "you are not visible".

Context for scoping the investment, all secondary: Semrush's own study of 10M+ keywords (Jan-Nov 2025, with Datos clickstream) measured AI Overview prevalence at 6.49% in January 2025, peaking at 24.61% in July, settling at 15.69% in November, with commercial-intent AIO coverage rising 8.15% → 18.57% year over year [semrush-aio, vendor study]. Take the trend, not the number.

### F9 · The narrative contract is enforceable structurally, not by instruction

**Conclusion: if the model writes the digits, the model can invent the digits. If the model writes a reference token and Python substitutes the digits, it cannot. The enforcement is a substitution step plus a residual-number validator, and the fallback is the deterministic reporter that already exists.**

`AI-001` is a P0 requirement: *"Python computes numbers, AI writes narrative — no metric may originate in a model."* The engine already has the honest fallback: `audit_engine/reporters/consolidated.py` is 604 lines of *"free, deterministic Python"* narrative (`bundle.py:3-4`), so a failed validation can always degrade to a shippable report rather than to no report.

It also already has the enforcement machinery to extend: `audit_engine/quality/report_contract.py` is a deterministic, AI-free validator over the assembled `report.html` string, with blockers, warnings, auto-patchers and a validate → patch → re-validate loop persisted to `qa-report-contract.json`. Its current blockers are section order, index count, em/en dashes, CTA email and severity highlighting. Numeric traceability belongs in exactly that list.

### F10 · The test debt is concentrated where it hurts most

**Conclusion: 344 lines of tests over 20,428 lines is not "thin coverage", it is "the engine is unverified". The highest-leverage fixture is a template farm, because it is the only way to test clustering, fingerprint stability and delta at all.**

Current state: `tests/test_parsers.py` (129), `tests/test_quality_gates.py` (100), `tests/test_analyzers.py` (~115), plus three HTML fixtures (`clean.html`, `thin.html`, `broken-schema.html`). `CLAUDE.md` claims a quality gate of *"pytest tests/ — green, 37+ tests"*. `pyproject.toml` already declares the right markers (`unit`, `integration`, `live_api`) and `asyncio_mode = "auto"` — the scaffolding exists, the tests do not.

The four seam requirements from **D-10 option A** are all still open and all cheap:
- The engine mints its own run id and prints it; the adapter regex-parses stdout (`_RUN_UUID_RE` defined at `backend/integrations/audit_engine.py:84`, applied at `:270`).
- The engine reads its own `.env` (`audit_engine/config.py:16-21`), so the platform vault is bypassed for every paid run.
- The engine catches no top-level exception and never times out; the adapter owns the 1500s timeout (`audit_engine.py:93`, `:351-362`).
- **A real bug in the current timeout**: `subprocess.run(..., timeout=...)` kills the direct child only. The engine spawns Chromium (crawl fallback and PDF render); on timeout the Python process dies and Chromium survives. The worker must start a new session and kill the process group.

---

## Options considered and why rejected

### Tiering model

| Option | Disqualifying fact |
|---|---|
| Keep tier as a caller-side argv recipe (`build_argv`) | The platform must encode the engine's internals to scope a run, and it cannot scope by dimension because *"the engine has no per-dimension CLI flag"* (`backend/integrations/audit_engine.py:157`). Selecting `geo` today fires all 21 agents. |
| Tier as a fraction of checks ("free = 30% of checks") | Arbitrary, undefensible to a client, and unstable — adding checks silently changes what free means. |
| Tier as a hand-curated check list per tier | 363 entries × 4 tiers maintained by hand, drifting the moment a check's data source changes. |
| **Chosen: tier as a permitted data-source class set, check set derived by containment** | Defensible in one sentence to a client, self-updating, and testable by asserting the derived counts against a frozen `checklists/tiers.yaml`. |

### Zero-spend enforcement

| Option | Disqualifying fact |
|---|---|
| Keep CLI flag-clearing (status quo) | Caller-shaped guard at one entry point; no analyzer or integration consults the mode (grep across `analyzers/` and `integrations/` returns no functional match); and nothing checks after the run whether spend occurred. |
| A separate "free build" of the engine with paid integrations stripped | Two artefacts and two test matrices for a codebase with 344 lines of tests. Divergence is certain. |
| Container-level network egress blocking as the sole mechanism | Cannot distinguish a free run from a paid run in the same worker, and converts a policy violation into an opaque connection error with no ledger entry. Retained as defence-in-depth *beneath* the broker, never as the mechanism. |
| **Chosen: cost-class registry + ProviderBroker + transport host allowlist + SpendLedger assertion with a dedicated exit code** | The guarantee becomes a checked postcondition. |

### Renderer

| Option | Disqualifying fact |
|---|---|
| WeasyPrint | Flexbox *"works for simple use cases but is not deeply tested"*; Grid *"works for simple cases, but has some limitations"* and does not support subgrids or `repeat(auto-fill, *)` / `repeat(auto-fit, *)` [weasyprint-api, fetched 2026-08-23]. The existing design uses both (`scripts/generate_audit_pdf.py:990,995-996`), so HTML and PDF would silently diverge — a direct `AUD-012` violation. (No-JavaScript is also true of it but is `[UNVERIFIED]` against the cited pages — see F4.) |
| Typst (or LaTeX) typesetting | Typst HTML export is *"still very incomplete … Do not use this feature for production use cases"* [typst-html]; LaTeX has no HTML path. Forces two authoring paths. |
| System Chrome/Edge discovery, current default | `_CHROME_CANDIDATES` is developer-machine-shaped; version differs between laptop and container; falls through to a third backend on failure. Three backends is three documents. |
| Client-side JS charts (Chart.js, D3) | Requires JS at render time, makes the HTML non-self-contained, and forfeits any future non-Chromium renderer. |
| Rasterised charts (matplotlib PNG) | Blurry in print, heavier artefacts, and a second styling system that will drift from the HTML's. |
| **Chosen: pinned Playwright Chromium in the browser worker, no fallback chain, charts as Python-generated inline SVG** | One document by construction; already in the dependency set; failure is loud and the report degrades to HTML-only, which `AUD-014` already requires the UI to handle. |

### Clustering / fingerprint

| Option | Disqualifying fact |
|---|---|
| Cluster by `check_id` only | Merges two genuinely different broken templates into one finding; one gets fixed, the finding stays open, the client is told nothing changed. |
| Cluster by URL prefix only | Fails on flat URL structures and root-heavy CMSes; also fails when one template serves several prefixes. |
| Cluster by DOM similarity only | Identity churns on any CSS/markup refactor; the delta reports a mass fix that did not happen. |
| Include URL or evidence in the fingerprint | Adding a page "creates" findings; changing a measured value closes one finding and opens another. Both break `last_seen_at` semantics outright. |
| **Chosen: URL-shape primary + DOM SimHash as splitter, frozen into a versioned `fingerprint`** | Stable under page addition and content change; splits only when the template genuinely differs. |

### Impact model

| Option | Disqualifying fact |
|---|---|
| Severity-only ordering (status quo) | Named as the defect in spec §13.4 — it transfers prioritisation to the client. |
| Monetary impact projection (`impact_usd`) | Not derivable from anything the engine measures. It is the fabricated-number failure mode with a column reserved for it. |
| ML-learned priority | Zero labelled data today. Revisit only after the 50-audit acceptance wave (D-14) produces actual fix-time labels. |
| **Chosen: `impact / effort` from measured reach, severity, confidence and distance-to-threshold; effort from fix locus/surface/dependency** | Every input traces to a finding field or a published threshold. |

### Delta / verification

| Option | Disqualifying fact |
|---|---|
| Diff `findings.json` between runs | Cannot distinguish "fixed" from "not checked this time". A lapsed Serper key reads as a client success. |
| Trust the re-run's absence of a finding | Same defect, one layer down: a check that did not execute emits no finding. |
| **Chosen: fingerprint-keyed state machine requiring check-ran + locus-re-observed + pass + stored evidence** | The only version where the sentence "you fixed 14 issues" is defensible. |

### Competitor comparison

| Option | Disqualifying fact |
|---|---|
| Buy Semrush/Ahrefs competitive data | The engine's stated position is *"No DataForSEO. No BrightLocal"* and Semrush is optional-only (`CLAUDE.md`); the comparison the client actually needs is per-check pass/fail, which we can measure ourselves. Revisit only if traffic/keyword estimates are explicitly requested. |
| Compare against an industry benchmark average | We have no dataset. An invented benchmark is a fabricated number. |
| Score the competitor and publish the score | Implies a measurement completeness we do not have on a site we crawled 10 pages of. |
| **Chosen: freeze the measured pack per client; publish per-check pass/fail facts plus a stated-basis score comparison** | Every cell is a measurement with evidence; no causal claim is made. |

---

## Engineering requirements this imposes

Requirements are grouped and numbered `R4-nn`. Paths are repo-relative. Engine paths are under `danyals-audit-system/`; platform paths under `backend/` and `db/`.

### A. The RunPlan — one object, resolved before any work

1. **R4-01** Add `audit_engine/plan.py` defining a frozen `RunPlan` dataclass: `run_id: str`, `tier: Literal["free","standard","deep","scoped"]`, `types: frozenset[str]`, `max_pages: int`, `max_depth: int`, `permitted_source_classes: frozenset[Literal["zero","free_quota","connection","billable"]]`, `permitted_hosts: frozenset[str]`, `condensed: bool`, `ai_narrative: bool`, `agents: bool`, `spend_ceiling_usd: float`, `phase_budgets_sec: dict[str,int]`, `fingerprint_version: int`, `scoring_model_version: str`.
2. **R4-02** Add CLI flags `--plan <path.json>` and `--run-id <uuid>` to `audit_engine/cli/main.py`. `--plan` supersedes the individual provider flags; passing both raises `typer.BadParameter`. When `--run-id` is supplied the engine uses it verbatim as `run_uuid` and as the artifact directory name; absent, it mints one (backward compatible). This removes the stdout-parse dependency at `backend/integrations/audit_engine.py:84`/`:270`.
3. **R4-03** The resolved plan is written verbatim to `<artifact_dir>/plan.json` before the crawl starts, and echoed into `run.json` under `plan`. Every downstream consumer reads the plan from the artifact, never re-derives it.
4. **R4-04** `condensed` becomes a plan field. Delete the derivation `condensed = str(mode).lower() == "free"` at `audit_engine/reporters/bundle.py:406` and the mode-derived page cap at `:500`; the cap becomes `plan.report_page_cap`.
5. **R4-05** Boot-time assertion in the platform's `validate_settings`: the engine path resolves and `python -m audit_engine.cli.main --help` enumerates `--plan` and `--run-id`. A missing flag means an engine/platform version skew and must fail startup, not fail the first audit.

### B. Cost classes, the broker, and the zero-spend guarantee

6. **R4-06** Add `cost_class` to every data source. Create `checklists/data_sources.yaml` mapping each of the ~50 declared sources to `zero | free_quota | connection | billable`, with `unit_price_usd` and `provider` where billable. Initial classification (from the audit of `checklists/*.yaml` on 2026-08-23): **zero** = `crawled_html*`, `rendered_html*`, `computed`, `internal_links`, `site_pages`, `http_headers`, `http_status`, `http_resp`, `http_timing`, `sitemap`, `schema_blocks`, `crawl_graph`, `robots`, `crawl_log`, `dns`, `whois`, `tls_handshake`, `llms_txt`, `screenshot*`, `web_fetch`, `competitor_crawl`, `axe_results`, `w3c_validator`, `wikidata`; **free_quota** = `psi`, `psi_mobile`, `crux`; **connection** = `gsc_query`, `gsc_ctr`, `gsc_coverage`, `server_logs`; **billable** = `moz_*`, `competitor_moz_*`, `serper*`, `google_places`, `google_nl`, `otterly`, `embeddings`, `web_search`.
7. **R4-07** Add `COST_CLASS` and `UNIT_PRICE_USD` module constants to each of `audit_engine/integrations/{serper,places,moz,pagespeed,google_nl,citations,geo_grid}.py` and to `audit_engine/agents/dispatcher.py`.
8. **R4-08** Add `audit_engine/providers/broker.py`. `ProviderBroker.get(name) -> Client` is the **only** sanctioned way to obtain an integration client; it raises `ProviderNotPermitted(name, plan.tier)` when the provider's `COST_CLASS` is not in `plan.permitted_source_classes`. `BaseClient.__init__` requires a broker-issued token and raises `RuntimeError` on direct construction.
9. **R4-09** Add `audit_engine/net.py` exposing the only sanctioned `httpx.AsyncClient` factory, which installs an event hook rejecting any request whose resolved host is not in `plan.permitted_hosts` (free tier: the target site's hosts plus `rdap.org`). Add a ruff `flake8-tidy-imports` banned-api rule forbidding `httpx.AsyncClient`, `httpx.get` and `httpx.post` outside `audit_engine/net.py`, enforced in the engine's CI.
10. **R4-10** Add `audit_engine/providers/ledger.py`. Every permitted billable call appends a row to the existing `api_calls` table (`audit_engine/db/schema.sql:85`) **and** to an in-process `SpendLedger`. The ledger is serialised into `run.json` as `usage.billable_calls`, `usage.by_provider`, `usage.est_cost_usd`.
11. **R4-11** **Postcondition assertion.** At the end of any run whose plan permits no billable class, assert `ledger.billable_calls == 0`. On violation, write `run.json` with `status: "failed"`, exit **12** (`EXIT_SPEND_VIOLATION`), and the platform marks the audit failed and raises an operator alert. The zero is then derived and checked, not asserted.
12. **R4-12** Free-of-charge quota'd APIs (`psi`, `crux`) are permitted on the free tier — this closes `KNOWN_LIMITATIONS` T-5/D-1 and restores Core Web Vitals to the lead magnet. They are budgeted by a platform-side Redis token bucket keyed per API per day; on exhaustion the engine records the check in `checks_skipped` with reason `quota_exhausted` and the report's "what we could not check" section (`AUD-024`) names it.
13. **R4-13** Free tier must not run the AI-crawler user-agent probe (R4-31) or any competitor measurement. Both require an authorised client relationship; the public funnel has none.

### C. Tier definitions, buildable

14. **R4-14** Derive the check set as `runs_in(plan) = { c | classes(c.data_sources) ⊆ plan.permitted_source_classes AND (not plan.types or dimension(c) ∈ plan.types) AND inputs_ran(c) }`, where `dimension(c)` is `geo` if `owner_agent == "A5"`, `strategy` if `owner_agent == "M2"`, else the checklist file's category. Freeze the expected result in `checklists/tiers.yaml` and add a golden test asserting the counts below; a check whose `data_sources` change must break that test.

    **`inputs_ran(c)` is not optional** (added by the 2026-08-23 verification pass; see F2's third consequence). Data-source containment alone admits the 27 `computed`-only rollup checks into the free tier even when the checks they roll up were all skipped, which would publish an invented authority score. Add an `inputs:` list to every check whose `data_sources` is exactly `[computed]` — naming the check ids it aggregates — and evaluate `runs_in` as a fixpoint: a rollup runs only when at least one named input ran, and it is otherwise emitted into `checks_skipped` with reason `inputs_not_gathered` and named in the `AUD-024` "what we could not check" section. The nine `OFF-072`-`OFF-080` rollups and `LOC-037`-`LOC-040` are the first ones to wire up, because they are the ones a free run would otherwise fabricate.

| Tier | `max_pages` / depth | Source classes | Checks that run | AI | Report |
|---|---|---|---|---|---|
| **free** | 15 pages, depth ≤3, crawl budget 120s | `zero` + `free_quota` | **193** — 219 checks fit by data source, minus the 26 `ai-assisted` ones, because a model call is billable | none — `consolidated.py` writes the prose | condensed, 12-20 pages, hard cap 20 |
| **standard** | 20 pages (15-25), depth ≤4 | `zero` + `free_quota` + `connection` | **197** with a Search Console connection, **193** without — 228 fit by data source, minus the 31 `ai-assisted` ones, since Standard runs no agent fan-out | short narrative only (Sonnet 5) | 20-30 pages |
| **deep** | `clamp(2 × sitemap_url_count, 200, 3000)`, depth unlimited | all | **363** (276 deterministic + 87 `ai-assisted`, which is what the agent fan-out is for) | 21 agents + M-layer narrative | 40-120 pages, cap 120 |
| **scoped** | as `standard` unless `deep_scope=true` | union of selected types' declared sources | union of selected types (onpage 122 · technical 100 · offpage 71 · local 36 · geo 13 · strategy 21; sums to 363) | agents only for the selected dimensions | sections for selected types only |

15. **R4-15** Empty `types` means run all (`ADM-012`, `AUD-005`). `strategy` maps to the 21 M2 `subcategory: scoring` checks plus the narrative; it owns no crawl work of its own and must state that in the methodology page.
16. **R4-16** Deep tier is **cost-estimated and confirmed before running**. Before enqueueing, the platform computes an estimate from `sitemap_url_count`, the selected types and the unit prices, and presents it for explicit operator confirmation. The estimate and the confirming user are stored on the audit row; the run is then gated by the existing `CostGate` (`backend/workers/tasks/audit.py:126-141`) at the estimate, and the committed cost is the runtime-derived figure from `pricing.audit_cost` (`backend/app/services/pricing.py:137-182`).
17. **R4-17** The free report must label its universal content blocks (the GBP self-audit checklist, the 20-directory priority list in `_PRIORITY_DIRECTORIES`) as **guidance**, not findings, since at the dimension level the free tier measures **zero** off-page checks and **three** local ones (the nine zero-cost off-page.yaml entries and four of the seven local ones are M2 `computed` rollups, excluded by `inputs_ran`). The section header's issue count must count only measured findings.

### D. One engine, one renderer

18. **R4-18** `report.html` is the deliverable. Replace `audit_engine/reporters/pdf.py:html_to_pdf` with a single backend: Playwright's bundled Chromium, pinned by version in the `worker-browser` image, invoked with `emulate_media(media="print")`, `format="A4"`, `print_background=True`, `prefer_css_page_size=True`. **Those four arguments are already exactly what `_playwright_pdf_sync` passes today (`audit_engine/reporters/pdf.py:101-107`)** — the change here is not the invocation, it is deleting everything around it: remove `_find_system_chrome` (`:37`), `_CHROME_CANDIDATES` (`:27-34`) and `_weasyprint_pdf` (`:145`), and make `_playwright_pdf` the only branch in `html_to_pdf` (`:163-171`). On failure the run succeeds with `pdf_path=None` and the UI offers no PDF (`AUD-014`).
19. **R4-19** Move `svg_donut` (`scripts/generate_audit_pdf.py:1100`), `svg_mini_donut` (`:1138`), `svg_sparkline` (`:1173`) and the bar/grid renderers into `audit_engine/reporters/charts.py` as pure functions returning self-contained inline `<svg>` with explicit `width`/`height`/`viewBox`, no external references, no `<foreignObject>`, no JavaScript. They become the only chart source for both outputs.
20. **R4-20** Fonts are embedded as base64 WOFF2 data URIs inside `report.html`. No `<link>` to a font host — the browser worker may be network-restricted and a fallback font makes the PDF a different document from the dashboard.
21. **R4-21** Replace `pymupdf>=1.24` (`danyals-audit-system/pyproject.toml:27`) with `pypdf` (BSD-3-Clause) for the page-cap net. PyMuPDF is AGPL/commercial dual-licensed [pymupdf-license] and this is a non-essential utility inside a commercial white-label product.
22. **R4-22** Prerequisite: split the backend image into `api` (no Chromium, no Playwright, no audit venv) and `worker-browser` (all three), per `docs/audit/TARGET_ARCHITECTURE.md:360`. The renderer decision is not shippable before this.
23. **R4-23** Render regression test: for each golden fixture, assert PDF page count within ±1 of the frozen value, extracted text equal to the HTML's text content modulo whitespace, and no page rendering blank. Do not byte-compare PDFs (creation timestamps are not stable).

### E. Clustering and persistent identity

24. **R4-24** `fingerprint = sha1(canonical_json({v: FINGERPRINT_VERSION, check: check_id, scope: locus_kind, locus: locus_value, disc: discriminator}))[:16]`, computed in `audit_engine/findings/fingerprint.py`. `locus_kind ∈ {site, template, url, entity}`. **No URL, no evidence value, no page id, no run id, no count ever enters the hash.**
25. **R4-25** `template_id` derivation, deterministic and in this order: (a) normalise the URL path to a shape by collapsing any segment that varies across ≥2 siblings sharing a parent prefix to `{slug}`, digits to `{n}`, ISO dates to `{date}`, UUIDs to `{uuid}` — producing e.g. `/services/{slug}`, `/blog/{date}/{slug}`; (b) compute a 64-bit SimHash over the sequence of `(tag, class-token)` pairs of the body DOM skeleton with text removed, including only structural tags (`header nav main section article aside footer h1-h6 table ul ol form`) and only class tokens present on ≥50% of candidate pages; (c) if the URL-shape group splits into >1 SimHash cluster (Hamming distance >3) with ≥3 members each, suffix the template id with an ordinal keyed by the lexicographically smallest member URL. Store `template_id` on the `pages` row.
26. **R4-26** Discriminators are check-specific, normalised and low-cardinality. Examples to implement first: broken link → `(target_status, target_registrable_domain, target_path_shape)`; redirect chain → `(hop_count_bucket, final_status)`; missing/short title, missing H1, missing schema → `""`; CWV → `(metric, field|lab)`; NAP mismatch → `(directory_key, mismatched_field)`; citation missing → `directory_key`.
27. **R4-27** Instances are stored, not collapsed. Table `audit_finding_instances (finding_id, url, evidence jsonb, first_seen_at, last_seen_at, closed_at, UNIQUE(finding_id, url))`. `instance_count` on the finding is `count(*) where closed_at is null` and is never written by hand.
28. **R4-28** Presentation: one card per finding, headline naming the **cause** ("The service template omits the H1 — 42 pages"), body carrying instance count, up to 3 sample URLs (the engine already appends `For example: /contact, /services` per `CLAUDE.md`), shared evidence, and a "fix once" remediation naming the template.
29. **R4-29** Root-cause **clusters** are a view, never an identity. Build a finding↔page bipartite graph; two findings are co-caused when `jaccard(pages(f1), pages(f2)) ≥ 0.8` **and** they share a `template` locus. Connected components render as one "root cause" heading with member findings nested. Each member keeps its own fingerprint row.
30. **R4-30** `fingerprint_version` participates in identity and is stored on every row. Bumping it requires a migration that closes existing rows with `closure_reason='superseded'` and opens new ones — never a silent hash change.

### F. GEO checks

31. **R4-31** Rewrite `audit_engine/analyzers/geo_ai.py:check_ai_crawler_directives` to evaluate real robots.txt rules through `audit_engine/parsers/robots.py` (grouped user-agent blocks, `Allow` overrides, case and whitespace), against the **documented** token set: `GPTBot`, `OAI-SearchBot`, `OAI-AdsBot`, `ChatGPT-User` [openai-bots]; `ClaudeBot`, `Claude-User`, `Claude-SearchBot` [anthropic-crawler]; `PerplexityBot`, `Perplexity-User` [perplexity-bots]; `Google-Extended` [google-crawlers]; plus `Applebot-Extended`, `CCBot`, `Bytespider` as best-effort. Remove `Claude-Web` (not in Anthropic's current documentation). Each verdict states the **vendor-documented** consequence, quoting the vendor.
32. **R4-32** New check `GEO-EDGE-001` (paid tiers only, authorised sites only): issue one `GET /` per bot presenting that bot's documented user-agent string and record the status code. A 403/429 while robots.txt allows is a `major` finding: "requests presenting the PerplexityBot user-agent receive 403 from your CDN". Rationale on the finding cites Cloudflare's default-block-for-new-domains policy and its ~20% share of web traffic [cloudflare-pr].
33. **R4-33** New check `GEO-SNIP-001`: detect `nosnippet`, `max-snippet:0`, blanket `data-nosnippet` on primary content, and `noindex`, and report them as AI-surface opt-outs, citing Google's own naming of those controls [google-ai-features].
34. **R4-34** Demote `check_llms_txt` (`audit_engine/analyzers/geo_ai.py:44-58`) to `status="info"`, `severity="info"`, neutral score. Replace the remediation string with the evidenced statement: the file is a community proposal whose own site documents labs *publishing* rather than *consuming* it, and Google states no AI text file is required. Report presence/absence as a fact.
35. **R4-35** Label the heuristic GEO checks (`ON-048`, `ON-049`, `ON-100`-`ON-105`, `ON-107`) with `confidence_label='inferred'` and render that label in the report. Their measurements are exact; their AI-visibility consequence is not vendor-confirmed.
36. **R4-36** Any statement about actual citation in AI answers requires a measurement provider. Absent one, the report says **"not measured"**. Never derive non-visibility from on-page properties.
37. **R4-37** Do not build: a marketed composite "GEO score"; `llms-full.txt` as a required artifact; any recommendation to add schema "for LLMs" (Google states no special schema is needed [google-ai-features]).

### G. Scoring, delta and verification

38. **R4-38** `audit_engine/scorers/impact.py`: `impact = reach × severity_weight × confidence × opportunity`. `reach = Σ page_value(instances) / Σ page_value(crawled)` where `page_value` is derived from crawl depth, internal inlink count, sitemap membership, `page_type`, and GSC clicks when a connection exists (GSC dominates when present). `severity_weight` keeps `{critical:3, major:2, minor:1, info:0.5}` (`audit_engine/scorers/aggregator.py:15`) but every check gains `severity_rationale` + `reference` in its YAML so severity itself is traceable. `opportunity` may take exactly two forms, both measured: CWV distance-to-threshold against the published p75 thresholds (LCP 2.5/4.0s [web-vitals, web-vitals-lcp]; INP 200/500ms and CLS 0.1/0.25 — good bounds sourced, poor bounds `[UNVERIFIED]`, see F6), and the count of pack competitors passing the same check.
39. **R4-39** `audit_engine/scorers/effort.py`: `effort_points = base[fix_surface] + locus_multiplier + 2 × dependency_count`, with `fix_surface ∈ {config, template, content, platform, dev}`, `fix_locus ∈ {site, template, per_page, external}`, and dependencies being measured booleans (needs client credential / needs a developer / needs third-party approval). The base table is a versioned module constant and is **printed in the report's methodology page**.
40. **R4-40** `priority = impact / effort_points`, rendered as a 2×2 quadrant plus an explicit ranked top five (`AUD-019`). Ties broken by `check_id` ascending so ordering is deterministic (`AUD-021`). `scoring_model_version` is stored on every finding row and printed on the methodology page.
41. **R4-41** The scorer must be a pure function of findings. Add a test asserting identical output over two runs on the same `findings.json`, and a lint rule asserting `audit_engine/scorers/` imports nothing from `agents/` or `integrations/`.
42. **R4-42** Drop or permanently NULL `impact_usd` (`audit_engine/db/schema.sql:76`). No projected dollar figure is derivable from anything the engine measures.
43. **R4-43** Fix the score-basis defect. `run.json` gains `scores.basis = {tier, types, checks_run, checks_skipped, providers_degraded}`. The report renders "62 / 100 across the 197 checks this tier runs" and never compares scores across different bases. Delta comparison requires equal `scores.basis.tier` and `types`; otherwise the delta section says so and shows nothing.
44. **R4-44** Finding lifecycle states: `open | closed_verified | closed_unverified | regressed | unknown_not_checked`. A finding may be reported **fixed** to a client **only** in `closed_verified`, which requires all four: (i) the check executed in run N (same basis), (ii) the locus was re-observed (≥1 page of the template crawled / the URL fetched with a non-5xx / the entity queried), (iii) the check returned `pass` on that locus, (iv) a verification evidence blob was stored. Anything else that merely stopped appearing is `closed_unverified` and is reported separately as "no longer detected (not re-verified)".
45. **R4-45** `verify_finding(fingerprint)` — a targeted micro-run that fetches only the locus, runs only that check, writes an `audit_finding_verifications` row, and (for entity checks) passes through the cost gate. This is what makes `AUD-020` real.
46. **R4-46** Regression: a `closed_verified` fingerprint reappearing sets `regressed_at` and raises priority one band automatically.
47. **R4-47** Structural-change guard: if >40% of open findings would close in one run **and** the set of `template_id`s changed, mark the run `structural_change`, suppress every "fixed" claim, and surface "the site changed structurally; findings re-baselined".

### H. Competitor-relative scoring

48. **R4-48** Competitor selection is derived, never typed. Local profile: the map-pack occupants for the client's primary service+city query at the client's own lat/lng (Serper local results). Non-local: the organic top-10 for 3-5 head terms, filtered of directories, aggregators, marketplaces and the client, ranked by cross-term frequency, top 3.
49. **R4-49** The competitor set is **frozen per client** in a `client_competitors` table on first computation and refreshed only on explicit operator action or quarterly. A drifting set makes month-over-month comparison meaningless.
50. **R4-50** What is measured on a competitor: a robots-respecting crawl of ≤10 public pages via their own sitemap; PSI/CrUX on their homepage and one template exemplar; schema types, title/H1 discipline, word counts, HTTPS and security headers, `llms.txt`, AI-crawler directives; and for local, their public GBP fields via Places. **Not** their backlinks (cost — see O-2), **not** traffic estimates, **never** a login or paywall bypass. Google's terms, under "Don't abuse our services", prohibit *"using automated means to access content **from any of our services** in violation of the machine-readable instructions on our web pages (for example, robots.txt files that disallow crawling, training, or other activities)"* [google-tos, effective 2026-07-30, fetched 2026-08-23]. **Read the scope precisely:** that clause binds automated access to *Google's own* surfaces — it is the governing authority for anything touching SERPs, the local pack or Places, and it is why SERP data comes through a contracted provider rather than our own scraper. It does **not** govern crawling a competitor's own website. Robots compliance on third-party sites is therefore a policy this project adopts, not an obligation this clause imposes; it is still not negotiable here, but the requirement must not be justified to the client by citing this clause. `[UNVERIFIED]` — no primary source was found in this pass that makes robots.txt legally binding on a third-party crawl; settle with counsel if the client ever asks for the legal basis in writing.
51. **R4-51** Presentation is a per-check pass/fail table with evidence per cell, plus one basis-stated headline: "Your score 62 · pack median 74 · pack leader 81, measured on the same 197 checks on 2026-08-23". No causal language — "they pass this check, you do not" is a fact; "they rank because of this" is not. A mandatory caveat block states the sampling limits, and every competitor finding carries `confidence_label='sampled'`.

### I. The narrative contract

52. **R4-52** The narrative model receives only `narrative_input.json`: per finding `{id, fingerprint, check_id, title, severity, instance_count, sample_urls[≤3], measured:{name:value}, priority_rank}`, plus `run_facts:{pages_crawled, checks_run, checks_skipped, score, score_basis, competitors[]}`. No raw HTML, no provider payloads, no database rows.
53. **R4-53** The model must emit every quantity as a token — `{{F:<finding_id>:<field>}}` or `{{R:<run_fact>}}` — never as digits. A deterministic post-processor substitutes real values from the structured input. **A fabricated number is structurally impossible because the model's digits are discarded.**
54. **R4-54** Add a `numeric_traceability` blocker to `audit_engine/quality/report_contract.py`. After substitution, every remaining numeric literal in prose must be either substitution-produced or in an explicit allowlist (page numbers, the year, section numbers, the published score bands). Extend the scan to number-words (`zero`-`ninety-nine`, `hundred`, `thousand`, `percent`) so the check cannot be evaded by spelling. Violation: regenerate the section once, then fall back to the deterministic narrative in `audit_engine/reporters/consolidated.py`. The honest path always ships.
55. **R4-55** Every substitution writes a `narrative_claims (report_id, section, claim_text, finding_id, field, value)` row, and the rendered claim carries a reference to its finding card. "Traceable" then means a query returns the finding for every number in the report — the auditable form of `AI-001` and `AUD-009`.
56. **R4-56** Extend the existing style-hygiene blocklist to causal constructions binding an unmeasured outcome ("because of this you rank", "will increase traffic by"), alongside the current em-dash, banned-term and API-name scans.

### J. Seam hardening and tests

57. **R4-57** Structured exit contract. Wrap every CLI command body in a top-level handler and always write `run.json` — including on failure — carrying `{status, exit_code, error:{type,message,where}, plan, usage, scores, counts, checks_skipped}`. Exit codes: `0` ok · `2` bad input · `10` target unreachable / zero pages crawled · `11` required provider hard-failed · `12` spend violation · `13` report-contract blocker · `20` internal error. Print one final machine-readable line `AUDIT_RESULT {json}` so the adapter stops parsing prose.
58. **R4-58** Credentials from the platform vault. Add `--credentials-fd <n>` (or an inherited pipe carrying JSON) and `config.APIKeys.from_payload()`. **Never argv** — argv is world-readable via `/proc`. The engine must not write a key into `run.json`, logs, or any artifact; `audit_engine/integrations/base.py:3-4` *asserts in its module docstring* that *"The base never logs secrets; keys are redacted from any log line that mentions them"* — that is documentation, not enforcement (the module has a single `log.error` call, at `:139`, and no redaction helper). Add the test that makes the docstring true.
59. **R4-59** Fix the process-group timeout bug. `backend/integrations/audit_engine.py` must launch with `start_new_session=True` and, on `TimeoutExpired`, `os.killpg` the group. Today `subprocess.run(timeout=…)` kills only the direct child, leaving a Chromium spawned by the crawl fallback (`audit_engine/crawlers/basic.py:232`) or the PDF render alive.
60. **R4-60** Per-phase soft budgets inside the engine (crawl / providers / agents / render), taken from `plan.phase_budgets_sec`, that **degrade** — skip the phase, record it in `checks_skipped` — rather than abort. A slow site should yield a partial honest report, not a worker-level timeout. The hard wall-clock stays with the caller (`AUD-013`).
61. **R4-61** Golden-site fixtures under `tests/fixtures/sites/`: `clean/` (near-zero findings), `broken/` (one deliberate defect per check family, hand-labelled), `template-farm/` (40 pages across 3 templates, one defective). Each ships `expected/findings.json`, `expected/fingerprints.json` and `expected/clusters.json`. Served from local disk by the harness; no network.
62. **R4-62** Per-check test manifest. Add a `test:` field to every check in `checklists/*.yaml`. A meta-test walks all 363 checks and fails on any check with an `analyzer:` and no `test:`. Enforce 100% for the free tier's 193-check set first (it is what strangers see), then technical, then the rest. Print "checks with a test / checks implemented" in CI.
63. **R4-63** Provider contract tests recorded, not live: a `respx`/`vcrpy` cassette per integration pinning response shapes, plus a `@pytest.mark.live_api` variant (the marker already exists in `pyproject.toml`) run manually or weekly, never in PR CI.
64. **R4-64** Fingerprint property tests (Hypothesis): stability under page-set permutation, under adding a page, under re-crawl with unchanged content; and distinctness across the hand-labelled distinct causes in the fixtures.
65. **R4-65** A zero-spend integration test: run the free plan against the local golden site with a transport that raises on any host outside `plan.permitted_hosts`, and assert `ledger.billable_calls == 0` and exit code `0`.
66. **R4-66** PR CI must run without network and without a Chromium download; render tests sit behind a `--render` marker on the browser image.

### K. Platform schema

67. **R4-67** New migration `db/migrations/00NN_audit_findings.sql`:

```sql
CREATE TABLE audit_findings (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  client_id             uuid NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  scope_type            text NOT NULL,          -- 'site' | 'client'
  scope_id              uuid NOT NULL,
  check_id              text NOT NULL,
  fingerprint           text NOT NULL,
  fingerprint_version   int  NOT NULL,
  locus_kind            text NOT NULL,          -- site | template | url | entity
  locus_value           text NOT NULL,
  discriminator         text NOT NULL DEFAULT '',
  category              text NOT NULL,
  dimension             text NOT NULL,          -- onpage|technical|offpage|local|geo|strategy
  severity              text NOT NULL,
  status                text NOT NULL,          -- open|closed_verified|closed_unverified|regressed|unknown_not_checked
  confidence            numeric,
  confidence_label      text,                   -- measured | inferred | sampled   (AUD-022)
  impact_score          numeric,
  effort_points         numeric,
  priority              numeric,
  scoring_model_version text NOT NULL,
  instance_count        int  NOT NULL DEFAULT 1,
  evidence              jsonb NOT NULL,
  remediation           text,
  first_seen_run        uuid, first_seen_at timestamptz NOT NULL,
  last_seen_run         uuid, last_seen_at  timestamptz NOT NULL,
  closed_run            uuid, closed_at     timestamptz, closure_evidence jsonb, closure_reason text,
  regressed_at          timestamptz,
  UNIQUE (scope_type, scope_id, check_id, fingerprint)
);
CREATE INDEX ON audit_findings (client_id, status, priority DESC);
CREATE INDEX ON audit_findings (scope_id, last_seen_at DESC);
```
plus `audit_finding_instances`, `audit_finding_verifications`, `narrative_claims`, `client_competitors`, and RLS policies on `client_id` matching every other tenant table.
68. **R4-68** Ingest is an upsert on the unique key: `ON CONFLICT (scope_type, scope_id, check_id, fingerprint) DO UPDATE SET last_seen_at = excluded.last_seen_at, last_seen_run = ..., instance_count = ..., evidence = ..., status = 'open', regressed_at = CASE WHEN audit_findings.status = 'closed_verified' THEN now() ELSE audit_findings.regressed_at END`.
69. **R4-69** `AUD-025` (one-click finding → task) becomes trivial once findings are rows: the task carries `finding_id`, and closing the task triggers `verify_finding`.

---

## Cost model at 100 clients

**Volume assumptions** (stated as assumptions, not evidence — they come from the platform's own scale target, not from measurement): 100 clients; 1 Standard audit per client per month (100/mo); 1 Deep audit per client per quarter (≈33/mo); 1 Type-scoped run per client per month (100/mo); 500 free public audits per month (the true ceiling is whatever the abuse-control cap is set to, not demand).

**Unit prices used**, each with provenance:

| Input | Price used | Source / status |
|---|---|---|
| Claude Opus 5 | $5.00 / MTok in · $25.00 / MTok out | [anthropic-pricing], accessed 2026-08-23 |
| Claude Sonnet 5 | $2.00 / MTok in · $10.00 / MTok out | [anthropic-pricing] — the $2/$10 introductory rate is now the standard price |
| Claude Haiku 4.5 | $1.00 / MTok in · $5.00 / MTok out | [anthropic-pricing] |
| Batch API | 50% off input and output | [anthropic-pricing] |
| Prompt cache read | 0.1× base input; 5-min write 1.25× | [anthropic-pricing] |
| Google Places — Place Details Pro | $17.00 / 1,000 above **5,000 free calls/month** | [places-pricing], page last updated 2026-08-19 |
| Google Places — Text Search Pro | $32.00 / 1,000 above **5,000 free calls/month** | [places-pricing] |
| Google Places — Place Details Essentials | $5.00 / 1,000 above **10,000 free calls/month** | [places-pricing] |
| PageSpeed Insights API | **$0.00** | No billing statement in Google's own docs [psi-getstarted, psi-about, psi-faq]; **quota `[UNVERIFIED]`** — see O-3 |
| CrUX API | **$0.00**, 150 queries/min per Cloud project | [crux-api] |
| Serper.dev | **$0.001 / query assumed** | **`[UNVERIFIED]`** — `serper.dev/pricing` returned HTTP 404 on 2026-08-23 and `serper.dev/` shows only "Get 2,500 free queries, no credit card required". The engine's own source comment says *"paid tier ~$1/1000 queries at scale"* (`audit_engine/integrations/serper.py:6-7`); secondary 2026 sources quote $1/1,000 at the $50 pack falling to ~$0.30/1,000 at the largest. See O-1. |
| Moz Links API | **not priced** | **`[UNVERIFIED]`** — moz.com is unreachable from this environment. See O-2. This is the one input that can move the Deep figure materially. |

### Per-audit arithmetic

**Free (15 pages, 193 deterministic checks including PSI/CrUX)**
- Billable providers: none, by plan construction and asserted by R4-11 → **$0.000**
- AI: none (the deterministic `consolidated.py` writes the prose) → **$0.000**
- Free-quota consumption: 2 PSI calls (home + one template exemplar) + 1 CrUX origin call
- **Marginal cost per free audit: $0.000**

**Standard (20 pages, 197 checks, short narrative)**
- Billable providers: none → **$0.000**
- Narrative on Sonnet 5, ~25,000 input tokens (the reduced `narrative_input.json` for 60-120 findings) + ~3,000 output:
  `25,000 × $2 / 1,000,000 = $0.0500` · `3,000 × $10 / 1,000,000 = $0.0300` → **$0.0800**
- **Per Standard audit: $0.080**

**Deep (250 pages, 363 checks, 21 agents + M-layer, competitors)**
- Serper ≈ **51 queries**: 5 head-term SERPs + 1 local pack + **25 geo-grid probes** — *an assumption*, not a value read from the code. `make_ring_grid` (`audit_engine/integrations/geo_grid.py:40-64`) yields `1 centre + 8 compass points × len(radii_km)`; `radii_km` is a **required parameter with no default and no caller anywhere in `audit_engine/`**, so the engine does not currently fix the radius count. 25 is what a 3-radius ring costs. Pin the radii in the `RunPlan` so this line becomes a measured figure rather than an assumed one + ~20 citation-discovery operator queries.
  `51 × $0.001 = $0.051` **`[UNVERIFIED price]`**
- Google Places: 1 Text Search Pro + 4 Place Details Pro (client + 3 competitors). At list price: `1 × $0.032 + 4 × $0.017 = $0.100`. **At 33 Deep audits/month = 33 Text Search + 132 Details, both far inside the 5,000/month free caps → $0.000 in practice.** Both figures stated deliberately; the free cap is a real allowance, not a discount, and it evaporates if volume changes.
- PSI/CrUX: 5 client template exemplars + 3 competitor homepages = 8 calls → **$0.000**
- 21 specialist agents on Sonnet 5 at ~12,000 in / 1,500 out each:
  `21 × (12,000 × $2/1e6 + 1,500 × $10/1e6) = 21 × ($0.0240 + $0.0150) = 21 × $0.0390 = $0.819`
- M-layer + narrative on Opus 5 at ~40,000 in / 6,000 out:
  `40,000 × $5/1e6 = $0.200` · `6,000 × $25/1e6 = $0.150` → **$0.350**
- AI subtotal **$1.169**. With 5-minute prompt caching on the shared findings context across the 21 agents (write 1.25×, reads 0.1×) the agent half falls to roughly **$0.28**, taking the AI subtotal to ≈**$0.63** — budget the un-cached figure and treat caching as headroom.
- Moz: **`[UNVERIFIED]`**, excluded from the total.
- **Per Deep audit: ≈ $1.32** (Serper $0.051 + Places $0.10 worst-case + AI $1.169), or **≈ $1.22** once the Places free cap applies.

**Type-scoped (weighted average across the type mix)**
- `technical` / `onpage` / `geo`: zero billable providers; short narrative only → ≈ **$0.02**
- `local`: 25 geo-grid + 1 local-pack Serper (`$0.026`) + 2 Places (free-capped) + narrative `$0.10` → ≈ **$0.13**
- `strategy`: 5 Serper (`$0.005`) + Opus narrative `$0.350` → ≈ **$0.36**
- `offpage`: Moz **`[UNVERIFIED]`** + ~10 Serper (`$0.010`)
- Mix assumption 40% / 30% / 20% / 10%:
  `0.40 × $0.02 + 0.30 × $0.13 + 0.20 × $0.36 + 0.10 × $0.01 = $0.008 + $0.039 + $0.072 + $0.001 =` **$0.120 + 0.10 × Moz_per_audit**

### Monthly total at 100 clients

| Tier | Runs / month | $ / run | Monthly |
|---|---|---|---|
| Free (public funnel) | 500 | $0.000 | **$0.00** |
| Standard | 100 | $0.080 | **$8.00** |
| Deep | 33 | $1.320 | **$43.56** |
| Type-scoped | 100 | $0.120 | **$12.00** |
| **Total (excluding Moz)** | **733** | | **≈ $63.56 / month** |

That is **≈ $0.64 per client per month** and **≈ $0.087 per audit** averaged across 733 audits. Moz is the only line that can change the shape of this, which is why O-2 gates whether off-page is on by default in Deep.

### Free-quota headroom

PSI calls/month = `500 × 2 (free) + 100 × 2 (standard) + 33 × 8 (deep) + ~60 × 2 (scoped) = 1,000 + 200 + 264 + 120 =` **1,584/month ≈ 53/day**. CrUX ≈ **700/month**, against a documented 150 queries/**minute** [crux-api]. Both are comfortably inside any plausible quota — but PSI's actual quota is `[UNVERIFIED]` (O-3), so the token bucket in R4-12 must be configured conservatively until it is confirmed.

### Compute, which is the real constraint

Not billable, but real, and it is what decides whether the single VPS holds. Assuming a browser-worker slot per run: Deep ≈ 20 min × 33 = **11 h**; Standard ≈ 4 min × 100 = **6.7 h**; Free ≈ 2 min × 500 = **16.7 h**; Scoped ≈ 5 min × 100 = **8.3 h**. **≈ 43 worker-hours / month ≈ 1.4 h/day.** One `worker-browser` container at concurrency 2 absorbs that with a wide margin, which is consistent with the no-Kubernetes constraint. The binding risk is not throughput, it is a Chromium memory spike co-resident with the API — which is why R4-22 (image split) is a prerequisite rather than a preference.

---

## Risks and failure modes

| # | Risk | Why it bites | Mitigation |
|---|---|---|---|
| **RK-1** | Free funnel is unauthenticated; zero billable spend is not zero cost | 500 free audits is 16.7 worker-hours and 500 crawls of strangers' sites from our IP. The audit found the rate limiter **fails open** (`docs/audit/ENGINEERING_MASTER_PLAN.md:35`) | Per-IP **and** per-domain limits that fail **closed**, a global daily queue cap, domain validation, robots compliance, and R4-13 (no UA probe, no competitor work on the free tier) |
| **RK-2** | A site redesign closes hundreds of template findings at once and the delta reports a mass fix | Template fingerprints legitimately change; the delta cannot tell that from remediation | R4-44 (verification required) plus R4-47 (structural-change guard suppresses "fixed" claims) |
| **RK-3** | A lapsed provider key silently changes the score and the delta | `aggregate()` renormalises over present categories (`scorers/aggregator.py:56-63`); a missing Serper key shrinks the denominator and moves the number | R4-43 (`scores.basis`), delta only within basis, and `AUD-024` "what we could not check" |
| **RK-4** | PyMuPDF's AGPL obligations in a commercial white-label product | Hard dependency at `pyproject.toml:27`, dual AGPL/commercial [pymupdf-license]; **D-11** may ship the engine to the client, making it a distribution question | R4-21: replace with `pypdf` (BSD-3-Clause) |
| **RK-5** | The engine's own `.env` remains a second key store | A free-plan run on a host with keys present is one code path away from spending | R4-08 broker + R4-11 ledger assertion + R4-58 vault injection |
| **RK-6** | A 250-page Deep crawl looks like an attack; a WAF ban breaks the audit and pages the client | Concurrency default is 8 (`config.py:85`) | Cap Deep concurrency at 4, honour `Crawl-delay` (Anthropic documents supporting it, so it is a live convention [anthropic-crawler]), declare a UA with a contact URL, and show the operator a pre-flight request count |
| **RK-7** | Competitor measurement is the highest legal-surface item in the track | Google's terms prohibit automated access to content *"from any of our services"* in violation of machine-readable instructions [google-tos] — which governs SERP/Places access, **not** a competitor's own site; the third-party-crawl position rests on adopted policy, not on that clause (see R4-50) | R4-50: robots-respecting, ≤10 public pages, no login, no paywall bypass, measurements only — never republish competitor content |
| **RK-8** | The AI-crawler UA probe (R4-32) sends requests presenting third-party bot user-agent strings | Defensible on an authorised client site; indefensible against a stranger. Also a policy call the owner must make | R4-13 excludes it from the free tier; O-5 requires a written owner decision before it ships |
| **RK-9** | The narrative validator is evaded by a spelled-out number | "forty-two pages" passes a digit-only regex | R4-54 extends the scan to number-words; a written-out quantity is itself a blocker |
| **RK-10** | The 21-agent fan-out is the largest cost line and the least deterministic part of Deep | $0.82 of the $1.32, and agent output varies run to run | Sonnet 5 for specialists, Opus 5 only for the M-layer; shared-context prompt caching; a hard per-run token ceiling (spec `AI-R7`); and R4-41 keeps *scoring* deterministic even when *prose* is not |
| **RK-11** | Chromium co-resident with the API takes the API down on a memory spike | Already recorded at `docs/audit/TARGET_ARCHITECTURE.md:360` | R4-22 image split is a hard prerequisite for the renderer |
| **RK-12** | Free-tier off-page/local sections read as findings when they are universal guidance | At dimension level the free tier measures 0 off-page and 3 local checks (the zero-cost off-page.yaml entries are all M2 rollups), but `CLAUDE.md:17` mandates the off-page section always renders because it carries the Business Citations content block | R4-17: label guidance as guidance; count only measured findings in the header |
| **RK-13** | Fingerprint version bumps silently rewrite history | A changed hash orphans every open finding | R4-30: version is stored, and a bump is a migration that closes rows as `superseded` |

---

## Open items

| # | What could not be settled | Exactly what would settle it | Blocks |
|---|---|---|---|
| **O-1** | Serper.dev's per-query price. `serper.dev/pricing` returned **HTTP 404** on 2026-08-23; the homepage shows only "2,500 free queries". The $0.001/query used in the cost model is `[UNVERIFIED]`, taken from the engine's own source comment and corroborated only by secondary 2026 blog sources | Log into the Serper dashboard and screenshot the credit-pack table, **or** obtain a written rate from Serper support. Record the date | Deep and `local`/`strategy` scoped cost lines |
| **O-2** | Moz Links API pricing and row semantics — moz.com is unreachable from this environment | Fetch `https://moz.com/products/api/pricing` from an unblocked network, or read the account's plan page in the Moz dashboard. Needed: monthly price, included rows, per-row overage | Whether off-page is enabled by default in Deep, and the whole `offpage` scoped cost line |
| **O-3** | PageSpeed Insights API's documented quota. Google's own PSI pages (`get-started`, `about`, `faq`) state **no** quota and **no** price; the widely-quoted 25,000/day + 400/100s figures are secondary only | Create the API key, open Google Cloud Console → APIs & Services → PageSpeed Insights API → Quotas, screenshot the per-day and per-minute limits | The token-bucket configuration in R4-12; currently must be set conservatively |
| **O-4** | Whether a contracted provider exists that measures actual AI-answer citation (AI Overviews / ChatGPT / Perplexity) for a domain+keyword set, and at what price. Otterly.AI is listed in `CLAUDE.md` but noted as *"not used by /audit"* | Vendor pricing page + a trial run on one client domain, comparing its output against a manual check of the same 10 queries | R4-36; without it, GEO reports "not measured" and cannot claim visibility either way |
| **O-5** | Whether the owner authorises the AI-crawler user-agent probe (R4-32), which sends requests presenting third-party bot UA strings to a client's own CDN | An explicit written owner decision. It is a policy call, not a technical one | The single highest-value evidenced GEO check |
| **O-6** | How many current clients have granted Search Console access. Nine checks (228 − 219) fit by data source once GSC is permitted, but only **four** of them are `automation: full` and therefore actually run at Standard (193 → 197); the other five are `ai-assisted` and belong to Deep. Those four are free but connection-gated, and GSC is the strongest input to the `page_value` term in the impact model | Count granted connections across the current client set | Whether the Standard tier advertises 193 or 197 checks, and how much of the impact model is depth-based versus click-based |
| **O-7** | Whether `impact_usd` (`audit_engine/db/schema.sql:76`) may simply be dropped | Grep every consumer of the engine's SQLite `findings` table and of `findings.json`; if none reads it, drop it in the same migration that adds `impact_score` | R4-42 |
| **O-8** | **D-11** — does the audit engine ship to Danyal? | An explicit owner decision, recorded in `DECISIONS_LOG.md` and communicated to the client | If yes: the PyMuPDF AGPL question becomes a distribution question, and the vault-injection design (R4-58) must degrade gracefully to a local key store |
| **O-9** | Whether Google Search Central documents passage-level ranking at a primary source. Only SEO-blog secondaries were found on 2026-08-23 | Locate the statement on `developers.google.com/search` or an official Search Central blog post; if none exists, the passage-citability checks stay `confidence_label='inferred'` permanently | The honesty labelling of `ON-049` and the structured-content checks |
| **O-10** | Deep tier's `max_pages` upper bound in practice. `CrawlConfig.max_pages_full` defaults to 500 (`audit_engine/config.py:84`) and the brief asks for "200-300+ scaled to actual site size", but no run above ~100 pages has been observed end-to-end (`KNOWN_LIMITATIONS`: *"The audit engine was never executed"*) | Run one Deep audit against a real 500-page client site and record wall-clock, peak worker memory, artifact size and PDF page count | The `clamp(2 × sitemap_url_count, 200, 3000)` bound in R4-14 and the compute figures above |

---

## Sources

Primary unless marked. All accessed **2026-08-23**.

- `[google-ai-features]` https://developers.google.com/search/docs/appearance/ai-features — accessed 2026-08-23 (page states last updated 2025-12-10)
- `[google-crawlers]` https://developers.google.com/search/docs/crawling-indexing/google-common-crawlers — accessed 2026-08-23 (page states last updated 2026-07-14)
- `[google-tos]` https://policies.google.com/terms — accessed 2026-08-23 (effective 2026-07-30)
- `[openai-bots]` https://developers.openai.com/api/docs/bots — accessed 2026-08-23 (no last-updated date shown)
- `[anthropic-crawler]` https://support.claude.com/en/articles/8896518-does-anthropic-crawl-data-from-the-web-and-how-can-site-owners-block-the-crawler — accessed 2026-08-23
- `[anthropic-bots-json]` https://claude.com/crawling/bots.json — cited by `[anthropic-crawler]` as the published source-IP list; **not independently fetched** in this pass
- `[perplexity-bots]` https://docs.perplexity.ai/guides/bots — accessed 2026-08-23
- `[cloudflare-pr]` https://www.cloudflare.com/press-releases/2025/cloudflare-just-changed-how-ai-crawlers-scrape-the-internet-at-large/ — accessed 2026-08-23 (announcement dated 2025-07-01)
- `[cloudflare-aicc]` https://developers.cloudflare.com/ai-crawl-control/ — accessed 2026-08-23
- `[llmstxt]` https://llmstxt.org/ — accessed 2026-08-23 (proposal published 2024-09-03 by Jeremy Howard; v2 dated 2026-08-10)
- `[crux-api]` https://developer.chrome.com/docs/crux/api — accessed 2026-08-23
- `[psi-getstarted]` https://developers.google.com/speed/docs/insights/v5/get-started — accessed 2026-08-23
- `[psi-about]` https://developers.google.com/speed/docs/insights/v5/about — accessed 2026-08-23
- `[psi-faq]` https://developers.google.com/speed/docs/insights/faq — accessed 2026-08-23
- `[web-vitals]` https://web.dev/articles/vitals — fetched 2026-08-23 (page states last updated 2024-10-31). Carries the **good** thresholds (LCP 2.5s, INP 200ms, CLS 0.1) and the 75th-percentile rule only; it does **not** carry the "poor" bounds
- `[web-vitals-lcp]` https://web.dev/articles/lcp — fetched 2026-08-23; source for LCP good ≤2.5s / poor >4.0s at p75
- `[places-pricing]` https://developers.google.com/maps/billing-and-pricing/pricing — accessed 2026-08-23 (page states last updated 2026-08-19)
- `[places-billing]` https://developers.google.com/maps/documentation/places/web-service/usage-and-billing — accessed 2026-08-23 (page states last updated 2026-08-19)
- `[anthropic-pricing]` https://platform.claude.com/docs/en/about-claude/pricing — accessed 2026-08-23
- `[weasyprint-api]` https://doc.courtbouillon.org/weasyprint/stable/api_reference.html — accessed 2026-08-23 (WeasyPrint 69.0)
- `[weasyprint-home]` https://doc.courtbouillon.org/weasyprint/stable/ — fetched 2026-08-23; source for *"It is based on various libraries but not on a full rendering engine like WebKit or Gecko"*. Neither this page nor `[weasyprint-api]` states that WeasyPrint does not execute JavaScript
- `[playwright-pdf]` https://playwright.dev/python/docs/api/class-page#page-pdf — accessed 2026-08-23
- `[playwright-pdf-note]` https://playwright.dev/python/docs/api/class-page — **fetched directly 2026-08-23 and the claim was NOT found**. The "PDF generation is only supported in Chromium headless" sentence does not appear on this page; the only headless note present is "Headless mode doesn't support navigation to a PDF document". The claim is now `[UNVERIFIED]` — see F4.
- `[chrome-headless]` https://developer.chrome.com/blog/removing-headless-old-from-chrome — accessed 2026-08-23 (announcement dated 2024-10-23; old headless removed in Chrome 132)
- `[typst-html]` https://typst.app/docs/reference/html/ — accessed 2026-08-23
- `[pymupdf-license]` https://pymupdf.readthedocs.io/en/latest/about.html — accessed 2026-08-23
- `[pypdf]` https://pypi.org/project/pypdf/ — accessed 2026-08-23 (BSD-3-Clause; 6.16.2 released 2026-08-23)
- `[serper-home]` https://serper.dev/ — accessed 2026-08-23 (shows "Get 2,500 free queries, no credit card required"; **`serper.dev/pricing` returned HTTP 404 on this date**)
- `[semrush-aio]` https://www.semrush.com/blog/semrush-ai-overviews-study/ — accessed 2026-08-23 — **SECONDARY**, vendor-published study (10M+ keywords, Jan-Nov 2025, with Datos clickstream)
- `[ppc-land]` https://ppc.land/llms-txt-adoption-rises-8-8x-but-97-of-files-get-zero-ai-requests/ — **SECONDARY**, surfaced as a search result on 2026-08-23 and **not fetched**; cited only as the origin of the ~10% adoption / negligible-bot-traffic figures, which are therefore `[UNVERIFIED]`

**Repo sources** (verified by reading the file at commit `79d1036`):

- `danyals-audit-system/CLAUDE.md` — report design contract, M5 checklist, API stack, quality gates
- `danyals-audit-system/audit_engine/cli/main.py:577-582`, `:1008-1037`, `:1575-1577` — free-mode flag clearing, paid-mode warnings, usage snapshot
- `danyals-audit-system/audit_engine/config.py:16-21`, `:82-84` — `.env` loading, crawl limits
- `danyals-audit-system/audit_engine/analyzers/common.py:19-31` — the `Verdict` shape (status, score, severity, confidence, evidence)
- `danyals-audit-system/audit_engine/analyzers/geo_ai.py:22-31`, `:44-58`, `:60-80` — AI-crawler token list, `llms.txt` verdict, robots substring parsing
- `danyals-audit-system/audit_engine/analyzers/ai_search.py:1-22` — the ON-048/049/100-107 GEO check map
- `danyals-audit-system/audit_engine/scorers/aggregator.py:15-63` — severity weights, profile weights, the renormalising composite
- `danyals-audit-system/audit_engine/quality/gates.py:151-175` — the current L2 dedup key
- `danyals-audit-system/audit_engine/quality/report_contract.py:1-40` — the deterministic report-contract validator and its blocker list
- `danyals-audit-system/audit_engine/reporters/pdf.py:27-34`, `:85-170` — the three-backend fallback chain
- `danyals-audit-system/audit_engine/reporters/bundle.py:406`, `:500` — `condensed` derived from mode, tier page cap
- `danyals-audit-system/audit_engine/integrations/base.py` — retry, circuit breaker, key-redaction
- `danyals-audit-system/audit_engine/integrations/serper.py:6-7` — the in-source price note
- `danyals-audit-system/audit_engine/integrations/geo_grid.py:40-64` — `make_ring_grid`, which yields `1 + 8 x len(radii_km)` points
- `danyals-audit-system/audit_engine/db/schema.sql:9-100` — runs, pages, findings, `api_calls`, `impact_usd`
- `danyals-audit-system/checklists/{on-page,technical,off-page,local}.yaml` — 363 checks with declared `data_sources`, counted programmatically on 2026-08-23
- `danyals-audit-system/pyproject.toml:27` — the `pymupdf>=1.24` dependency
- `backend/integrations/audit_engine.py:19-21`, `:79`, `:87`, `:96`, `:140-260`, `:308-427` — the exit contract as it stands, the type map, `build_argv`, the subprocess timeout
- `backend/workers/tasks/audit.py:126-153`, `:427-606` — the cost gate and the public free-audit lifecycle
- `backend/app/services/pricing.py:137-182` — runtime-derived audit cost
- `docs/recovery/DANIEL_PROJECT_RECOVERY_SPECIFICATION.md` §13.1-13.5 — audit architecture, free/paid requirements, AUD-R1..R9
- `docs/recovery/REQUIREMENTS_TRACEABILITY.md:131-156`, `:338` — AUD-001..026, AI-001
- `docs/recovery/DECISIONS_LOG.md:11-25` **D-1** — the v1 scope baseline, which is also where *"Free (condensed, ~10-15 pages, public lead magnet)"* is decided. (An earlier draft also cited **D-16** for "free = condensed"; D-16 is *"Web 2.0 runs per-client / per-campaign, not for everyone"* and has nothing to do with this track. The condensed-and-free *resolution* is additionally recorded at `docs/audit/ENGINEERING_MASTER_PLAN.md:500`.)
- `docs/recovery/DECISIONS_REQUIRED.md` D-10, D-11, D-13, D-14 — the engine seam, engine ownership, free-audit abuse controls, acceptance waves
- `docs/audit/ENGINEERING_MASTER_PLAN.md:35`, `:165`, `:500` — the free-audit cost hole, P0-2, the "condensed + free" resolution
- `docs/audit/TARGET_ARCHITECTURE.md:70`, `:142`, `:360` — object storage for artefacts, the `browser` queue, the image split
- `docs/implementation/KNOWN_LIMITATIONS.md` T-5, D-1, and the "engine was never executed" note

---

## Verification pass — 2026-08-23

An adversarial verification pass was run against this document at repo commit `2a502f9` (the `79d1036` named in the header is an ancestor of it; nothing under `danyals-audit-system/` or `backend/integrations/` changed between the two in a way that affects any citation here). The brief was to refute the document, not to agree with it. Corrections were made in place; verified claims were left at full strength.

### What was checked

**Every repo claim.** All 363 checks were re-counted programmatically from `danyals-audit-system/checklists/*.yaml`; all four tier set-containment counts were recomputed from scratch; every `file.py:LINE` citation in the document was opened and read; every referenced module, table, column, constant and requirement ID was confirmed to exist and to say what was claimed.

**Every external claim** was checked for a source URL and an accessed date, and the highest-stakes ones were fetched directly rather than trusted.

**Sources fetched in this pass** (all 2026-08-23): `platform.claude.com/docs/en/about-claude/pricing`; `developer.chrome.com/docs/crux/api`; `developers.google.com/maps/billing-and-pricing/pricing`; `policies.google.com/terms`; `cloudflare.com/press-releases/2025/cloudflare-just-changed-how-ai-crawlers-scrape-the-internet-at-large/`; `support.claude.com/.../8896518-does-anthropic-crawl-data-from-the-web...`; `developers.openai.com/api/docs/bots`; `docs.perplexity.ai/guides/bots`; `developers.google.com/search/docs/appearance/ai-features`; `llmstxt.org`; `pypi.org/project/pypdf/`; `pymupdf.readthedocs.io/en/latest/about.html`; `typst.app/docs/reference/html/`; `developer.chrome.com/blog/removing-headless-old-from-chrome`; `doc.courtbouillon.org/weasyprint/stable/api_reference.html` and `/stable/`; `playwright.dev/python/docs/api/class-page`; `web.dev/articles/vitals` and `web.dev/articles/lcp`; `semrush.com/blog/semrush-ai-overviews-study/`.

### Corrections made

**Substantive.**

1. **The per-type check table double-counted the 21 M2 `strategy` checks.** It read onpage 129 / technical 101 / offpage 80 / local 40 / geo 13 / strategy 21, summing to 384 = 363 + 21, with a zero-cost column summing to 218 = 197 + 21. Under the dimension rule the document itself states, the correct figures are **onpage 122 / technical 100 / offpage 71 / local 36 / geo 13 / strategy 21**, summing to 363, and zero-cost **82 / 81 / 0 / 3 / 10 / 21**, summing to 197. Corrected in F2, in the Decision paragraph, and in R4-14's `scoped` row.
2. **"The free tier's off-page section will contain at most 9 measured checks, and its local section at most 7" was wrong at the dimension level.** All nine zero-cost off-page.yaml checks are M2 rollups (`OFF-072`-`OFF-080`) and four of the seven local ones are (`LOC-037`-`LOC-040`). The free tier measures **zero** off-page checks and **three** local ones. Corrected in F2, R4-17 and RK-12.
3. **A defect in the chosen mechanism itself, found while re-deriving the counts.** Twenty-seven of the free tier's 193 checks declare `data_sources: [computed]` only. Data-source containment admits every one of them even when the checks they roll up were skipped, so a free run as specified would publish "Authority score", "Link trust score" and "Backlink relevance score" computed over no link data — the exact fabricated-number failure this project exists to eliminate, produced by the mechanism chosen to prevent it. F2 gains a third consequence and **R4-14 now requires `inputs_ran(c)`** with an `inputs:` list on every `computed`-only check and a fixpoint evaluation.
4. **F6 contradicted F2.** F6 asserted "a free run produces no off-page findings" while F2 said nine off-page checks were zero-cost. Resolved in favour of F6 *once the rollups are excluded by `inputs_ran`*; the renormalisation defect stands as described, and the `local` profile's weighting was added because it distorts more, not less.
5. **The Context misattributed the engine-seam decision.** It said "Decision **D-11** vendors it in with a structured exit contract, which means the seam is about to become internal." The seam decision is **D-10**; vendoring is D-10 **option B** while the structured exit contract is **option A**; and neither is decided — `DECISIONS_REQUIRED.md:140-159` records D-10 as "Decision needed" recommending "A now", and this document's own O-8 lists D-11 as open. The premise that "the seam is about to become internal" was false. Rewritten, and the requirements re-anchored to option A (which they already matched).
6. **The Google ToS quote was truncated in a way that changed its scope.** The full clause is *"using automated means to access content **from any of our services** in violation of the machine-readable instructions on our web pages"*. It binds access to **Google's own** surfaces — it does not govern crawling a competitor's own website. R4-50 and RK-7 were using it as the authority for third-party robots compliance. Corrected: robots compliance on third-party sites is now stated as adopted policy, and the absence of a primary legal source for it is marked `[UNVERIFIED]`.
7. **WeasyPrint "does not support JavaScript" is not supported by either cited page.** Fetched directly: neither the API reference nor the project home says it. Downgraded to `[UNVERIFIED]` and re-anchored to the sentence that *is* documented — *"not on a full rendering engine like WebKit or Gecko"*. The rejection of WeasyPrint does not depend on it; the flexbox and Grid limitations are directly sourced and are independently disqualifying.
8. **The Playwright "PDF is Chromium-headless only" note was flagged SECONDARY; fetched directly, the claim is not on the page at all.** Downgraded to `[UNVERIFIED]` with the exact test that would settle it.
9. **The Core Web Vitals "poor" bounds are not on the cited page.** `[web-vitals]` publishes only the good thresholds and the p75 rule. LCP poor >4.0s was confirmed on the per-metric page (added as `[web-vitals-lcp]`); INP >500ms and CLS >0.25 are now marked `[UNVERIFIED]`. This matters because R4-38's distance-to-threshold term needs both bounds.
10. **A Perplexity quotation was a paraphrase presented as verbatim.** *"Allow this bot to ensure your site appears in search results"* is not what the page says; the actual sentence is *"To ensure your site appears in search results, we recommend allowing `PerplexityBot`"*. Corrected, and the published IP-range URLs added.
11. **"25 geo-grid probes … per `geo_grid.py:make_ring_grid`" over-attributed an assumption to the code.** `radii_km` is a required parameter with no default and no caller anywhere in `audit_engine/`; the code yields `1 + 8 × len(radii_km)` and fixes nothing. Relabelled as an assumption, with a requirement to pin the radii in the `RunPlan`.
12. **"`base.py` already refuses to log key values" overstated a docstring.** The module *documents* that it never logs secrets (`base.py:3-4`); there is no redaction helper and one `log.error` call at `:139`. Corrected to name it as documentation, not enforcement.
13. **Sources misattributed "free = condensed" to `DECISIONS_LOG` D-16.** D-16 is "Web 2.0 runs per-client / per-campaign". The decision is in **D-1** (`DECISIONS_LOG.md:11-25`), whose v1 scope table reads *"Free (condensed, ~10-15 pages, public lead magnet)"*. Corrected.
14. **O-6 overstated what a Search Console connection buys the Standard tier.** Nine checks fit by data source, but only **four** are `automation: full` and actually run at Standard (193 → 197); the other five are `ai-assisted`. Corrected.
15. **R4-18 read as if it were prescribing new `page.pdf()` arguments.** All four are already passed at `pdf.py:101-107`. Rewritten so a developer sees the actual work is deleting the fallback chain, with the exact line ranges to delete.

**Citation line numbers corrected** (each opened and re-read): `common.py:27`→`:23`; `schema.sql:79`→`:76` (three occurrences); `schema.sql:71`→`:69`; `schema.sql:86-100`→`:85-99` and `:86`→`:85`; `geo_ai.py:24-33`→`:22-31` (two occurrences); `geo_ai.py:~72`→`:74`; `pyproject.toml:26`→`:27` (three occurrences); `backend/integrations/audit_engine.py:87`→`:84` defined / `:270` applied (two occurrences); `audit_engine.py:96`→`:93`; `config.py:83`→`:84`; `bundle.py:5-7`→`:3-4`; `geo_grid.py:38-60`→`:40-64`. "~50 distinct data sources" → **53** (exact).

### Verified correct — deliberately left unhedged

Over-hedging a sourced fact is also a defect, so the following were confirmed and left at full strength.

**Repo.** 363 checks (on-page 142 · technical 101 · off-page 80 · local 40), every one declaring `data_sources`, zero exceptions. The four containment counts are exact: zero-only **197** (171 `full`), +PSI/CrUX **219** (193 `full`), +GSC **228** (197 `full`), all **363** (276 `full` / 87 `ai-assisted`). 37 critical and 89 major defaults in the 197-check site-only core. 20,428 Python LOC; 344 lines of tests; `consolidated.py` 604 lines. `cli/main.py:577-582` and `:1012-1017`; a grep for `mode` across `analyzers/` and `integrations/` returns **literally zero matches**. `gates.py:161` dedup key. `bundle.py:406` and `:500`. `pdf.py:27-34`, `:97-110`, and the three-backend order. `generate_audit_pdf.py:990`, `:995-996`, `svg_donut:1100`, `svg_mini_donut:1138`, `svg_sparkline:1173` — all four exact. `aggregator.py:15` and `:56-63`. `backend/integrations/audit_engine.py:79` and `:157-162`; `workers/tasks/audit.py:126-141`; `pricing.py:137-182`. `ENGINEERING_MASTER_PLAN.md:35`, `:165` (P0-2), `:500`; `TARGET_ARCHITECTURE.md:360`; `KNOWN_LIMITATIONS` T-5 and "the audit engine was never executed"; spec §13.4 and its quoted sentence; `AUD-F9`, `AUD-P4`, `AI-R7` and every `AUD-*`/`AI-001` id used. pytest markers and the three HTML fixtures. **The process-group timeout bug in R4-59 is real**: `subprocess.run` at `:351-362` passes no `start_new_session` and there is no `killpg` anywhere in the adapter.

**External.** Anthropic pricing — Opus 5 $5/$25, Sonnet 5 $2/$10 (with the page's own note that the introductory rate is now standard), Haiku 4.5 $1/$5, Batch 50% off both, cache read 0.1× and 5-minute write 1.25× — **every figure exact**. CrUX *"limited to 150 queries per minute per Google Cloud project, which is offered without charge"* — exact. Google Places — Details Pro $17/1,000 above 5,000 free/month, Text Search Pro $32/1,000 above 5,000, Details Essentials $5/1,000 above 10,000, page last updated 2026-08-19 — **every figure exact**. Cloudflare — the first-infrastructure-provider claim, the new-domain prompt, and "20% of the web", press release 1 July 2025 — exact. Anthropic's crawler docs — ClaudeBot / Claude-User / Claude-SearchBot, `Crawl-delay` supported, `claude.com/crawling/bots.json`, and **`Claude-Web` genuinely absent** — exact, so F8's criticism of `geo_ai.py` stands. OpenAI — GPTBot, OAI-SearchBot, OAI-AdsBot and ChatGPT-User all real, the robots.txt-may-not-apply sentence exact, and `/llms.txt` referenced only as OpenAI's own docs index. Google's AI-features page — all three quotes exact, last updated 2025-12-10, so R4-37's "do not recommend schema for LLMs" is correctly grounded. `llmstxt.org` — Jeremy Howard, 2024-09-03, v2 dated 2026-08-10, the labs-*publish* quote exact, and the page makes **no** consumption claim. PyMuPDF's dual AGPL/commercial licence — both quotes exact. pypdf 6.16.2, BSD-3-Clause, released 2026-08-23 — exact (the same-day release date looked invented and is not). Typst's "do not use this feature for production use cases" — exact. Chrome 132 headless removal and `chrome-headless-shell` — exact. WeasyPrint 69.0 flexbox and Grid limitations — exact. Semrush's 6.49% / 24.61% / 15.69% and 8.15% → 18.57%, 10M+ keywords, Jan-Nov 2025, Datos — **every figure exact**, and correctly labelled a vendor study.

**Arithmetic.** Every figure in the cost model was recomputed independently: the Standard $0.080, the Deep $0.819 agent line, the $0.350 M-layer, the $1.169 AI subtotal and the $1.320 total; the 40/30/20/10 scoped weighted average of $0.120; the monthly $0.00 / $8.00 / $43.56 / $12.00 totalling $63.56 over 733 runs; $0.64 per client per month and $0.087 per audit; 1,584 PSI calls/month ≈ 53/day; and 43 worker-hours ≈ 1.4 h/day. **All correct.**

**Constraints.** No requirement in this track touches citation submission, Web 2.0 publishing, content publishing or Elementor body edits, so the L3 automation ceiling is not engaged. No CAPTCHA evasion is proposed. No Kubernetes is proposed, and R4-22's image split is explicitly consistent with `TARGET_ARCHITECTURE.md`'s "Do not adopt Kubernetes". The rejected options are rejected on stated disqualifying facts rather than preference, with one soft spot noted: "Rasterised charts (matplotlib PNG)" is rejected partly on "a second styling system that will drift", which is a judgement rather than a fact — the print-resolution argument carries it.

### Still `[UNVERIFIED]` and why

| # | Claim | Why it is still open |
|---|---|---|
| 1 | Serper.dev's $0.001/query | Unchanged from O-1. `serper.dev/pricing` was 404 in the original pass; the figure comes from the engine's own source comment. It flows into the Deep, `local` and `strategy` cost lines. |
| 2 | Moz Links API pricing | Unchanged from O-2. moz.com unreachable. Excluded from every total. |
| 3 | PageSpeed Insights API quota | Unchanged from O-3. Google's PSI pages state no quota and no price; the widely-quoted 25,000/day is secondary only. The $0.00 price is well-evidenced by absence-of-billing across three Google pages; the **quota** is not. |
| 4 | Playwright PDF is Chromium-headless-only | **Newly downgraded.** Fetched directly on 2026-08-23; the sentence is not on the page. Settle by finding it in Playwright's docs or release notes, or by running `page.pdf()` under Firefox and WebKit. |
| 5 | WeasyPrint does not execute JavaScript | **Newly downgraded.** True by reputation, undocumented on both cited pages. Settle from WeasyPrint's FAQ or issue tracker. Not load-bearing. |
| 6 | INP poor >500ms and CLS poor >0.25 | **Newly downgraded.** Absent from `[web-vitals]`. Settle by fetching `web.dev/articles/inp` and `web.dev/articles/cls`. Needed before R4-38 is implemented. |
| 7 | Any legal obligation to respect robots.txt on a **third-party** site | **Newly raised.** The Google ToS clause cited for this governs Google's own services only. The practice stays; the justification needs counsel if the client ever asks for it in writing. |
| 8 | `llms.txt` adoption ≈10% with negligible bot traffic | Unchanged. `[ppc-land]` was never fetched. Already correctly marked. |
| 9 | Otterly.AI or any AI-citation measurement provider | Unchanged from O-4. No pricing obtained. R4-36's "not measured" is the correct posture until it is. |

### Verdict

**CORRECTED.** The architecture survives the pass intact — the four-tier model, the broker-plus-ledger zero-spend guarantee, the single-renderer decision, the fingerprint design, the impact/effort model with `impact_usd` left NULL, the four-condition fix-verification rule and the token-substitution narrative contract are all sound, and the external evidence behind the cost model and the GEO check matrix is unusually well sourced. Two findings were material rather than cosmetic: the per-type table was arithmetically wrong in a way that would have failed R4-14's own golden test on day one, and the containment rule admits 27 `computed` rollups that would have made a free audit publish an invented authority score. Both are fixed above. Nothing in the document should be implemented against the `[UNVERIFIED]` rows in the table above without settling them first.
