# Audit engine — observed output (Phase 0 evidence)

**The audit engine had never been executed end-to-end before 2026-08-24.**
`docs/implementation/KNOWN_LIMITATIONS.md` recorded this; every downstream design was
written against an *assumed* output shape. This directory holds the first real output,
frozen, so every later phase designs against observed data.

## Run 1 — free tier, `example.com`

| | |
|---|---|
| run_uuid | `3055416d-5137-446c-a495-7ef4462ede37` |
| target | `https://example.com` (IANA-reserved documentation domain — no consent question) |
| mode / tier | `free` — `--no-psi --no-serper --no-places --no-citations --agents off --ai-narrative off` |
| pages crawled | 1 |
| findings emitted | 105 (of 363 checks) |
| score | 58.0 (on_page 44.2 · technical 71.8 · off_page **null** · local **null**) |
| wall clock | 28 s |
| engine `duration_sec` | 7.08 s |
| spend | **$0.00, measured** — `api_calls` 0 rows, `agent_runs` 0 rows |

Reproduce:
```
cd danyals-audit-system && ./.venv/bin/python -m audit_engine.cli.main full https://example.com \
  --profile general --max-pages 15 --no-moz --mode free \
  --no-psi --no-serper --no-places --no-citations --agents off --ai-narrative off
```

## What this run settled

**1. Zero-spend on the free tier is TRUE, and now measured rather than asserted.**
`api_calls` is empty and `audit_runs.api_cost_usd = 0.0`. R4-11 turns this into an
enforced postcondition; today it is an observed fact for this run only.

**2. The renormalisation defect (R4-F6) is live and reproducible.**
`overall = 58.0` is the *simple mean* of on_page 44.2 and technical 71.8. `off_page` and
`local` are `null` and were dropped from the denominator entirely. A free score and a deep
score are not comparable, exactly as R4 predicted — now demonstrated on real data.

**3. `subcategory` — the subpoint axis — is only 53% populated (56/105).**
All 363 checks declare a `subcategory` in `checklists/*.yaml`, but the analyzers do not
propagate it; it is `NULL` in the engine's SQLite too, so this is not a serialisation loss.
The pillar x subpoint spine therefore needs a `check_id -> checklist` join at emit time.
That is a lookup against data we already have, not new measurement.
Two emitted values are also absent from the checklist vocabulary — `site-structure` and
`geo-ai` (the YAML says `ai-search`) — so the join must reconcile, not assume.

**4. A finding carries NO url.** It carries `page_id`, a per-run autoincrement (R4-F5
warned this is worthless across runs). The URL lives only in the engine's `pages` table,
which `findings.json` discards. Nano grain is therefore *unreachable from the JSON alone* —
this is the concrete form of the problem the altitude spine exists to fix.

**5. 26 of 105 findings have no `page_id` at all** (79/105 populated). These are site-level
checks (robots, sitemap, TLS). That is correct semantics and maps cleanly onto R4's
`locus_kind = site` vs `url`.

**6. `references_json` is 0/105 populated.** The per-finding citations the deliverable is
supposed to carry do not exist yet. `remediation` is only 42/105. Both are real work, not
a plumbing gap.

**7. `impact_usd` is 0/105 populated** — consistent with R4-42's decision to leave it
permanently NULL. No change needed.

**8. The engine emits FIVE separate PDFs, not one.** `report.pdf` (1.1 MB), `report-full.pdf`
(687 KB), `report-consolidated.pdf` (77 KB), `report-executive.pdf` (148 KB),
`remediation.pdf` (192 KB). R4-F4 described a three-renderer problem; the real number of
documents is worse. R4-18's consolidation is more valuable than it looked.

**9. 75% of wall clock is unmeasured.** The engine reports `duration_sec: 7.08`; the adapter
observed 28 s. The missing ~21 s is report rendering, which the engine does not time. The
per-phase timing work (`audit_run_phases`) has to wrap rendering, not just analysis.

**10. Scale signal.** 57 KB of `findings.json` from a **one-page** crawl. The 200-500 page
target needs the streaming/JSONL path in the plan, not an in-memory list.

## Not yet run

- A paid-tier run (providers + 21 agents + narrative).
- A 200+ page run — settles R4 open item **O-10**, which notes no run above ~100 pages has
  ever been observed. Blocked on owner decision **D-2** (target site).

---

## Run 2 — `www.alpinehomeair.com`, free tier — and a live P0 defect

| | |
|---|---|
| run_uuid (before fix) | `e834b06c-3133-4ef9-87b2-d86fc09f42ac` |
| run_uuid (after fix) | `67125812-dc49-43f5-83e0-0dc84ca0852b` |
| flags | `--mode free --no-psi --no-serper --no-places --no-citations --agents off --ai-narrative off` |
| pages crawled | 10 · **findings 817** · score 75.1 (on-page 57.5 · technical 92.7) |

### P0 — the free tier called a BILLABLE provider, and nothing recorded it

**Observed, not inferred.** The run above emitted:

```
POST https://language.googleapis.com/v1/documents:analyzeSentiment?key=... 200 OK
  Google NL: 762 entities, 4 categories, sentiment 0.10
```

on a run explicitly invoked as `--mode free`.

**Cause.** `--mode free` clears exactly five flags — `psi, moz, serper, places, citations`
(`audit_engine/cli/main.py:1012-1017`). **`google_nl` is not among them, and no `--nl` flag exists.**
`_emit_google_nl_snapshot` was gated on **key presence only** (`if not keys.google_nl`) and called
unconditionally from three sites. Worse, `config.py:69` resolves it as
`GOOGLE_NL_API_KEY or GOOGLE_API_KEY`, so clearing the dedicated key does not disable it — the
general Google key re-enables it.

This is **exactly failure mode 2 of R4-F3**: *"a new paid provider is added and someone forgets to
add its flag to the clearing block."* Predicted 2026-08-23; observed 2026-08-24.

**Blast radius.** `build_argv(comprehensive=False)` produces precisely these flags, so **every
anonymous audit on the public, unauthenticated lead-magnet endpoint made this call.** The engine
wrote **no `api_calls` row** for it (verified: table empty across all three runs), so
`audit_runs.api_cost_usd` reads `0.0`. Spend with no ledger entry to notice it by — the same shape as
P0-2, which the docs record as fixed. The earlier fix cleared the five providers it knew about.

**Secondary defect — the API key is logged.** `google_nl.py:149` places the key in the query string
(`documents:analyzeSentiment?key={self._api_key}`), so httpx's INFO request log prints it in full on
every call. `integrations/base.py:3-4` *documents* that keys are redacted; there is no redaction
helper. R4-58 called this "documentation, not enforcement" — now demonstrated.

### The fix, and its proof

`_emit_google_nl_snapshot` takes `permit_billable: bool = False` and returns early when unset.
**Default False = fails closed**: a future call site that forgets the argument spends nothing rather
than silently billing. `_run_full` — the only path the platform uses — passes
`permit_billable=(mode != "free")`.

Proof, re-running the identical command:

- **No `language.googleapis.com` request.** `google-nl.json` written before, absent after.
- **Verdict set byte-identical** — every `(check_id, status, severity)` across all 817 findings
  matches. The free tier was paying for data that changed no measurement.
- Engine suite still **37/37**.
- Wall clock **14.5s → 4.5s**.

### Run 2 also settled two more things

**The target blocks a declared SEO crawler at the edge.** `GET /sitemaps/sitemap.xml` with
`User-Agent: SEO-AUDIT-OS/0.1` returns **403** while `robots.txt` allows it. The engine's `curl_cffi`
browser impersonation gets through. This is R4-F8's edge-blocking scenario, live on the first real
client-shaped site — and it is itself a findable audit defect worth shipping as a check.

**The engine is NOT run-to-run deterministic.** Re-running the same command against the same site
produced 4 of 817 findings differing in evidence (`ON-120`, `ON-135`), plus unordered `samples` lists
throughout (`["2026","5931","2002"]` vs `["5931","2002","2026"]`). Scores and verdicts were stable;
evidence was not. **Golden-fixture regression therefore cannot be a byte comparison** — it must
compare the normalised verdict set, and the engine should sort sample collections before emitting.

---

## Run 3 — `smileon.pk`, PAID + LOCAL, whole site — the scale run

A dental clinic in Lahore: a real local business, the exact client shape the product serves.
196 sitemap URLs, WordPress + Yoast. **This settles R4 open item O-10** — no run above ~100 pages
had ever been observed.

| | |
|---|---|
| run_uuid | `837b75d6-4786-4188-b1b4-6b2472795e1f` |
| flags | `--profile local --max-pages 250 --mode paid --psi --serper --places --citations --city Lahore --agents on --ai-narrative on` |
| pages crawled | **197** (whole site) |
| wall clock | **236 s** — crawl+analysis ~180 s, rendering ~180 s of overlap |
| findings | **15,617** |
| scores | overall 63.3 · on-page 57.5 · technical 97.2 · off-page 56.7 · local 44.2 |
| agent calls | **15** (not 21) · 515,508 in / 27,329 out on Haiku 4.5 |
| measured AI cost | **$0.652** |
| measured provider cost | **unknown — see P0-2 below** |

Reproduce: same command, `--max-pages 250`. Full `findings.json` is 9.3 MB and stays out of git;
`summary.json` and a 150-row `findings.sample.json` are committed here.

### The headline: 8,077 rows are 81 problems

Of 15,617 findings, **8,077 are `fail` or `warn`** — what a client is shown today. They contain
**81 distinct causes**. Grouping by cause and counting instances is a **99.0% reduction in what a
human must read**, and the result reads exactly like the deliverable this project is trying to build:

```
[major] Image alt text optimization              - 197 pages
[major] Content readability analysis             - 197 pages
[major] Organization schema entity completeness  - 197 pages
[major] AI overview optimization                 - 394 pages
```

That is the macro/micro/nano case proven on real data, not argued. **This is the single strongest
justification for the altitude spine**, and it is why today's output is a data dump rather than a
deliverable.

### P0-2 — the engine records NO provider spend, on ANY run

`api_calls` and `agent_runs` are **empty after a full paid run**. They are not merely "not consulted
as a gate" (R4-F3's wording) — **they are never written at all**: the only occurrence of either table
name in the engine's Python is a comment added today. Consequences:

- Serper, Google Places and PageSpeed calls are **invisible**. Provider spend for this run is
  unknown and unknowable from the artifacts.
- `run.json.usage` carries only `{agent_calls, input_tokens, output_tokens, model}` — **no
  `serper_queries`, no `places_calls`**. So `pricing.audit_cost`'s "precise path" can never fire for
  providers and always falls back to the derived estimate.
- R4-10 is therefore **larger than R4 describes**: the ledger must be *built*, not just *read*.

### The deliverable is not yet a deliverable

| artifact | pages | size |
|---|---|---|
| `report-full.pdf` | **833** | **15.4 MB** |
| `remediation.pdf` | 447 | 6.2 MB |
| `report.pdf` | 44 | 2.5 MB |
| `report-executive.pdf` | 4 | 0.1 MB |
| `report-ai-narrative.pdf` | 3 | 0.1 MB |
| `report-consolidated.pdf` | 1 | 0.0 MB |

An 833-page, 15.4 MB PDF is precisely what spec §13.4 warns against. **Six** PDFs now, not five —
`report-ai-narrative.pdf` appears only on a narrative run.

### Other measurements

- **Only 160 of 363 checks fired**, and nothing records why the other 203 did not. This is the
  coverage gap R4-43 / AUD-024 describe, quantified.
- **`subcategory` is 38% populated at scale** (worse than 53% on the 1-page run). The subpoint axis
  needs the checklist join before it can carry a report.
- **`references_json` 0%** and **`remediation` 50%** — unchanged at scale.
- **A local audit produced 19 local findings** out of 15,617 (on-page 15,156 · technical 418 ·
  off-page 24 · local-seo 19). For the product's core vertical, the local dimension is nearly silent.
  Worth an owner conversation: it is the dimension Daniel sells.
- **Agents: 15 of 21 ran.** Nothing records which six did not, or why.
