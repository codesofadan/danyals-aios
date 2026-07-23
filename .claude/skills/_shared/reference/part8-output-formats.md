# Part-8 Output Formats — the 8 tool modules' response contract

Table of contents
1. `rank_tracker` — `/rank-tracker/*`
2. `keyword_research` — `/keyword-research/*`
3. `competitor_intel` — `/competitor-intel/*`
4. `on_page` — `/on-page/*`
5. `local_seo` — `/local-seo/*`
6. `client_onboarding` — `/client-onboarding/*`
7. `data_import` — `/data-import/*`
8. `billing` — `/billing/*`
9. Shared conventions (paging, the `ToolExtraResponse` workspace, null discipline)
10. Fields that do NOT exist (the invention traps)

This doc pins the **exact fields the Part-8 backend returns** so every Part-8 skill's pinned
output uses real values, never invented ones. It mirrors `backend/app/modules/*/schemas.py` and
`backend/app/modules/*/router.py`. It is the Part-8 sibling of `reference/output-formats.md`
(which pins the content pipeline). If a response model changes, update this doc AND the skills
that cite it (contract-lock discipline). §10 is not optional reading: most of the ways a skill
invents a number are listed there.

**Wire casing.** Attributes are snake_case in Python; the wire keys are camelCase via
`serialization_alias` and FastAPI's `by_alias=True`. **The camelCase name below is the wire
name.** List endpoints return a **bare JSON array** — no `total` / `page` / `items` envelope.

**No `client_id` on any Part-8 response.** Every module returns `client` (the snapshotted
display name) and never the UUID. The public code (`RK-`/`CI-`/`OP-`/`INV-`…) is the identifier.

---

## 1. `rank_tracker`

`RankKeywordResponse` (`GET|POST /api/v1/rank-tracker/keywords`, `PATCH .../keywords/{code}`):

```
code · keyword · client · position (int|None) · change {value, direction} · bestPosition (int|None)
url · targetUrl · tags[] · engine · device · location · cadence · status · features[]
checked (relative string, "never" when unchecked) · stale (bool)
```

`change.direction` ∈ `up | down | flat | new | lost`; `up` means the position **improved**.
`change.value` is the magnitude as a string, or the literal word `"new"` / `"lost"`.

`RankCostProjection` (`GET /api/v1/rank-tracker/cost-projection?clientId=…`, **`clientId` required**;
also nested as `projection` in the add response):

```
client · tracked (int) · daily (int) · weekly (int) · checksPerMonth (float)
costPerCheck (float) · monthlyCost (float) · budgetCap (float) · budgetSpent (float)
budgetRemaining (float) · withinBudget (bool) · provider (str) · live (bool) · message (str)
```

`RankKeywordsAdded` (`POST .../keywords`, 201) = `{keywords: [RankKeywordResponse], projection: RankCostProjection}` — exactly two keys.
`RankCheckQueued` (`POST .../keywords/{code}/check`, 202) = `{code, queued, reason}`.
`RankHistoryPoint` (`GET .../keywords/{code}/history`) = `{date, position (int|None), url, features[], delta (int|None)}`.
`RankStats` (`GET /api/v1/rank-tracker/stats`) = `{tracked, avgPosition, topThree}`. `avgPosition`
averages **ranked rows only**; all-unranked reads `0.0`.

**Enums.** `engine` ∈ `google|bing` · `device` ∈ `desktop|mobile|tablet` · `cadence` ∈
`daily|weekly` (**only these two**) · `status` ∈ `active|paused`.

**The 402.** Raised at two sites: the add (prices the whole book *as it would be after* the add)
and a `status`/`cadence` change that **raises** `monthlyCost` while `withinBudget` is false. A
pause / slow-down is always allowed, even over cap. The 402 `detail` **is**
`RankCostProjection.message`. Tag/URL-only edits are never priced.

**A keyless deploy cannot 402.** Dormant pricing returns `costPerCheck: 0.0`, `provider: "fake"`,
`live: false` → `monthlyCost: 0.0` → `withinBudget: true`. An **uncapped** client (`budgetCap <= 0`,
"0 = uncapped") is also always `withinBudget: true`. Read `live` before trusting a projection.

**`position: null` = unranked.** The fetch succeeded and the domain is not in the fetched window.
A **failed** check writes nothing at all — no row, no null, no history point, $0 spent. So a null
is always a real observation and a gap in history is an outage, never a lost ranking.

---

## 2. `keyword_research`

`KeywordResponse` (`GET|POST /api/v1/keyword-research/keywords`, `PATCH .../keywords/{code}`):

```
code · keyword · client · volume (int) · difficulty (float 0-100) · cpc (float)
intent (str, "" when unset) · cluster · opportunity (float) · winnable (bool) · targetUrl · geo
```

`ClusterResponse` (`GET /api/v1/keyword-research/clusters`) = `{name, pillar, intent, size, volume, avgDifficulty, client}`.
`CannibalizationConflict` (`GET /api/v1/keyword-research/cannibalization`) = `{targetUrl, intents[], keywords[]}`.
`KeywordStats` (`GET /api/v1/keyword-research/stats`) = `{saved, clusters, avgDifficulty}`.
`ResearchQueuedResponse` (`POST /api/v1/keyword-research/research`, 202) = `{seed, queued}` — **exactly two keys**.

**`difficulty` is NOT winnability-aware.** It is the raw provider KD, 0-100, un-adjusted.
`winnable` is a **separate boolean verdict**, and in production it is **not client-DA-aware**:
the research task hard-codes `client_da=None`, so every judgement runs against the neutral DA
(`content_research_neutral_da`, default 30.0) plus the stretch (default 15.0). Effect: every
researched keyword with **KD <= 45 reads `winnable: true` regardless of which client it is for**.
Report `winnable` as a neutral-DA screen, never as "winnable for this client".

**`intent_source` is real but NOT on the wire.** The DB enum is
`provider | serp_heuristic | llm | manual` and the chain is stored per row, but **no endpoint
emits it** and `llm` is never written by any code path in this module. Same for
`intent_confidence` and `metrics_confidence` (`high|low`). Do not pin them.

**The 202 tells you nothing about spend.** `POST /research` enqueues and returns
`{seed, queued: true}` **unconditionally**. The cost gate runs later, in the worker; a block ends
the job with zero spend and **is invisible to the API caller**. There is **no `degraded`,
`partial`, `confidence`, or `lowConfidence` field anywhere in this module's API surface** —
verify a research run by re-reading `GET /api/v1/keyword-research/keywords` (or `stats.saved`)
and comparing counts, and say plainly when nothing landed.

---

## 3. `competitor_intel`

`CompetitorResponse` (`GET|POST /api/v1/competitor-intel/competitors`, `PATCH .../competitors/{code}`):

```
code · domain · client · label · source (manual|serp_auto) · tracked (bool)
overlap (float, Jaccard %) · keywordGaps (int) · commonKeywords (int) · shareOfVoice (float)
analyzed (relative string, literally "never" when un-analyzed)
```

`KeywordGapResponse` (`GET .../competitors/{code}/gaps`):

```
id · keyword · volume · difficulty · intent (str|None) · competitorPosition (int|None)
clientPosition (int|None) · gapType (missing|weak|shared|untapped) · opportunity · promoted (bool)
```

`ShareOfVoiceResponse` (`GET /api/v1/competitor-intel/share-of-voice?clientId=…`, **`clientId` required**)
= `{client, entries: [ShareOfVoiceEntry], curve: [float], provisional: bool}` where
`ShareOfVoiceEntry` = `{domain, label, isClient (bool), visibility (float), share (float)}`.
`BacklinkGapResponse` (`GET .../competitors/{code}/backlink-gaps`) = `{refDomain, competitors (int), authority (int), spam (int)}`.
`CompetitorStats` (`GET /api/v1/competitor-intel/stats`) = `{tracked, keywordGaps, shareOfVoice, provisional}`.
`DiscoveryQueued` (`POST /api/v1/competitor-intel/discover`, 202) = `{client, queued, reason}`.
`AnalysisQueued` (`POST .../competitors/{code}/analyze`, 202) = `{code, queued, reason}`.
`GapPromoted` (`POST .../competitors/{code}/gaps/{gap_id}/promote`, 201) = `{keyword, code, created}`.

**`clientPosition: null` = a PURE gap** — the client does not rank at all. It is **not** position 0.
Reading it as 0 would rank a term the client has never touched ahead of a #1 they own outright.
`gapType` encodes it: `null` → `untapped` (high volume) or `missing`; a worse-than-rival position
→ `weak`; otherwise `shared`.

**Share-of-Voice is an ESTIMATE, and it says so.** `provisional: true` rides every SoV response
and `CompetitorStats`. It is a modelled CTR curve (config `competitor_intel_ctr_curve`, echoed
back on the wire as `curve` so any number can be reproduced), not measured traffic. The
denominator is **the client plus their TRACKED competitors only** — share of the voice we
measure, not of the whole internet. Zero provider cost.

**`entries[].domain` is the CLIENT'S NAME on the client's own row**, not a domain. Identify the
client's row by **`isClient`**, never by string-matching a domain.

**`backlink-gaps` returns an honestly EMPTY set today.** Structural, not incidental: the query
inner-joins `competitors` on `backlinks.competitor_id`, and the only writer of that table never
populates that column, so it can never match. Nothing ingests competitor-side backlink rows yet
(pulling a rival's profile is a new paid call Phase 2C does not buy). An empty array therefore
means **"this data is not ingested"**, NOT "no gaps found". The alternative — presenting other
monitored clients' referring domains as this client's competitors' links — would fabricate a fact.

---

## 4. `on_page`

`RecommendationResponse` (`GET /api/v1/on-page/recommendations`):

```
id · analysis (the parent OP-#### code) · client · page · issue · issueCode
impact (High|Med|Low) · status (open|applied|dismissed|held|reverted) · fixKind
current (str, "" when null) · proposed (str, "" when null) · priority (float)
quickWin (bool) · autoApplicable (bool)
```

`RecommendationDetail` (`GET .../recommendations/{rec_id}`) = the above **plus exactly**
`detail (dict)` and `analysisStatus`.
`AnalysisResponse` (`GET /api/v1/on-page/analyses`) = `{code, client, page, keyword, status, score (flat float), openCount, appliedCount, error ("" when null)}`.
`AnalysisQueuedResponse` (`POST /api/v1/on-page/analyze`, 202) = `{code, queued}` — **no `reason`**.
`ApplyResultResponse` (apply / revert) = `{id, state, reason, recommendation (may be null)}`.
`ApplyBulkResponse` (`POST /api/v1/on-page/recommendations/apply-bulk`) = `{applied (int), skipped (int), results: [ApplyResultResponse]}`.
`OnPageStats` (`GET /api/v1/on-page/stats`) = `{analyzed, open, applied}` — exactly three.

`state` vocabulary: `applied | reverted | noop | skipped | held | blocked | failed`.
`fixKind` ∈ `title | meta | heading | schema | content | manual`.
`AnalysisStatus` ∈ `queued | analyzing | done | failed | held`.

**The drift guard is a plain string comparison, NOT a hash.** There is no checksum / etag /
version field anywhere in this module. Apply re-reads the live field and compares it to the
`current` snapshot taken at analysis time; **revert** compares the live value against
`fix_payload.proposed_value` (what we wrote) instead. A mismatch → **409**, distinct messages:

- apply: *the live page changed after this analysis - applying would overwrite a manual edit; re-analyze, or apply with force to overwrite it anyway*
- revert: *the live page changed since this fix was applied - reverting would overwrite a later manual edit*

**`confirm` is `StrictBool` + an "is True" validator.** `1`, `"true"`, `"yes"`, `[1]` and a
missing key are all **422 before the route body runs**. Only a literal JSON `true` passes.

**A `held` is a 200, not a failure, and nothing was written to the site.** Hold reasons, verbatim:

- `SEO-plugin bridge missing: WordPress accepted the request but did not store the value (the SEO plugin has not registered this meta key with show_in_rest)`
- `no WordPress credential for this site (add the app password to the vault)`
- `no WordPress post is linked to this page`
- `no automated apply path for a {kind} fix - a human must make this change`
- `the recommendation carries no proposed value`

**`autoApplicable` does NOT predict success.** It is derived as `fixKind != "manual"`, so
`heading`/`schema`/`content` read `true` — yet only `title`/`meta` are bridge-deliverable, and the
rest **hold** with the "no automated apply path" reason. **`quickWin` is the narrower, honest
signal.** A no-op reads `state: "noop"`, `reason: "already applied (idempotent)"`.

---

## 5. `local_seo`

`LocalRankingResponse` (`GET|POST /api/v1/local-seo/rankings`, `PATCH .../rankings/{ranking_id}`):

```
id · location · client · keyword · geo · rank (int|None) · previousRank (int|None) · change (int)
inMapPack (bool) · foundUrl · topCompetitors[] · provider · isActive (bool) · lastCheckedAt
```

`GbpProfileResponse` (`GET|POST /api/v1/local-seo/profiles`, `GET|PATCH .../profiles/{profile_id}`):

```
id · client · location · placeId · primaryCategory · secondaryCategories[] · napName · napAddress
napPhone · website · hours (dict) · reviewCount (int) · avgRating (float|None) · completeness (int)
oauthConnected (bool) · lastSyncedAt
```

`ProfileAuditReport` (`GET .../profiles/{profile_id}/audit`) = `{id, location, client, completeness, primaryCategory, secondaryCategories[], findings (dict), missing[]}`.
`findings` keys are **snake_case** (unlike the wire keys): `primary_category`, `secondary_categories`,
`hours`, `website`, `phone`, `name`, `address`. Values ∈ `ok | missing | thin`. `missing` is the
subset whose verdict is not `ok`. The audit is **recomputed fresh**, not read from the stored score.

`NapAlignmentReport` (`GET .../profiles/{profile_id}/nap-alignment`) = `{id, location, client, napName, napAddress, napPhone, directories: [{directory, status, note, cosmeticOnly}], consistent, inconsistent, missing, cosmeticOnly, aligned}`.
`LocalRankHistoryPoint` (`GET .../rankings/{ranking_id}/history`) = `{rank (int|None), inMapPack, provider, checkedAt}`.
`LocalStats` (`GET /api/v1/local-seo/stats`) = `{gbpProfiles, avgMapRank, citations}`.
`RefreshQueuedResponse` (refresh / sync, 202) = `{id, queued (bool), held (bool), reason (str)}`.

**The field is `rank`, not `position`.** `position` does not exist on this module's wire.
`rank: null` = checked, **not in the map pack**. A failed check writes nothing, so a null is
always a real observation.

**No geo-grid.** Out of contract scope, structurally: the provider takes a single scalar `geo` —
there is nowhere to put grid points. No grid, no radius, no lat/lng fan-out, no heatmap.

**GBP sync is READ-ONLY and it HOLDS.** No posting, no review replies; the migration creates no
such tables. Missing OAuth client → `{queued: false, held: true, reason: "no_oauth_client"}` at
**202** — the whole `reason` is that literal token, there is no prose message. **This hold is the
expected steady state, not an error.** And `queued: true` does **not** mean a sync will happen:
**no GBP reader is wired at all today**, so even with OAuth set the worker holds with
`no_reader` (the third reason, `no_oauth_token`, is also worker-side and never reaches the API).

**`POST .../rankings/{ranking_id}/refresh` kicks the WHOLE due sweep, not one row.** The
`ranking_id` is used only for the 404 check and the echoed `id`. The paid check is gated in the
**worker** so an on-demand refresh can never bypass the money dial. The registered cost dial is
**`local_seo`** (`local_rank` is only the cost-log job label; two source comments say otherwise
and are wrong).

---

## 6. `client_onboarding`

`OnboardingStepResponse`:

```
id · stepKey · label · client · status · owner · ownerInit · ownerColor · due
notes · verified (bool) · hasCredential (bool) · sortOrder (int)
```

`OnboardingRunResponse` = `{id, client, template, status, owner, step, stepStatus, progress (int), target, steps: [OnboardingStepResponse]}`.
`steps` is `[]` on the **list** route and populated only on detail / create / complete.
`OnboardingStats` (`GET /api/v1/client-onboarding/stats`) = `{inOnboarding, stepsPending, completed30d}`.

`RunStatus` ∈ `in_progress | on_hold | completed | archived` (live = `in_progress`, `on_hold`).
`StepStatus` ∈ `pending | in_progress | blocked | completed | skipped`.

**The 11 step keys** (template `local_seo_default`, sort order 1-11): `kickoff`, `collect_gbp`,
`collect_website_cms`, `collect_analytics`, `collect_search_console`, `brand_assets`,
`competitor_list`, `keyword_seeds`, `baseline_audit`, `content_plan`, `reporting_setup`.

**There are FOUR `collect_*` steps, not five.** `collect_gbp`, `collect_website_cms`,
`collect_analytics`, `collect_search_console`. `brand_assets` is labelled "Collect brand assets"
but its **key** does not start with `collect_`, so it **cannot** carry a credential (400). One
source comment and a test name both say "five" and are wrong.

**Sealing is not verifying.** A `credential` on a `collect_*` step is AES-256-GCM sealed into the
vault; only the returned id lands on the step, surfaced as the boolean **`hasCredential`**. The
seal deliberately does **not** touch `verified` — sealing proves a credential was TYPED, not that
it WORKS. **`verified` moves only when a caller explicitly sends it.** There is **no
"test every login" step key** — that rule is encoded by the `verified` / `hasCredential`
separation, not by a step. Do not name a step that does not exist.

**Secrets never come back.** `secret` is `SecretStr`, exists on exactly one request model and no
response model — absent by construction, not by exclusion. `vaultSecretId` never reaches the
wire either. There is no reveal path in this module.

---

## 7. `data_import`

`ImportRunResponse` (`GET /api/v1/data-import/runs`):

```
id · file · sourceType · sourceLabel · status · client · rows (int) · mapped (int) · errors (int)
detectedColumns[] · columnMap (dict) · created (humanised string, e.g. "Today · 09:14")
```

`ImportRunDetail` (`GET .../runs/{run_id}`) = the above **plus exactly one key**:
`errorSample: [{row, field, value, reason}]`, capped at **50 entries at rest** (not just on the
wire); `errors` still reports the true total.
`ImportUploadResponse` (`POST /api/v1/data-import/uploads`, 201) = `{run, columns: [{column, samples[]}], suggested (dict), template (may be null)}`.
`ImportFieldsResponse` (`GET /api/v1/data-import/fields?sourceType=…`, **required**) = `{sourceType, fields[], required[]}`.
`ImportMappingResponse` = `{id, name, sourceType, columnMap, created}`.
`ImportCommitQueued` (`POST .../runs/{run_id}/commit`, 202) = `{id, queued, reason}`.
`ImportStats` (`GET /api/v1/data-import/stats`) = `{imports30d, rowsMapped, rowsError}`.

**Row counts are `rows` / `mapped` / `errors`** on the wire. There is **no `rows_total`,
`rows_ok`, or `rows_rejected`** anywhere.

**Statuses** (7): `uploaded`, `mapping`, `validating`, `importing`, `imported`, `partial`,
`failed`. Terminal = `imported | partial | failed`.

**`partial` = some rows were rejected AND at least one landed.** Two sharp edges: zero data rows
→ **`failed`** ("the file has no data rows"); every row rejected → **`failed`** ("every row was
rejected"), *not* `partial`.

**The per-`sourceType` allow-list** (`GET /api/v1/data-import/fields` publishes it; **required** in bold):

| sourceType | allowed target fields | required |
|---|---|---|
| `search_console` | `query`, `page`, `clicks`, `impressions`, `ctr`, `position`, `date` | *(none)* |
| `keywords` | `keyword`, `volume`, `difficulty`, `cpc`, `intent`, `geo` | **`keyword`** |
| `rankings` | `keyword`, `location`, `target_url`, `device`, `engine`, `language`, `country` | **`keyword`** (and the run **requires a client**) |
| `backlinks` | `ref_domain`, `anchor`, `authority`, `spam`, `first_seen`, `status` | **`ref_domain`** |
| `citations` | `directory`, `nap_status`, `note` | **`directory`** |
| `custom` | **EMPTY — every mapping is invalid by construction** | — |

Server-derived columns (`client_id`, `client_name`, `import_run_id`, `source`, …) are **never
mappable**. A field outside the allow-list → **400**:
`'{field}' is not an importable field for {sourceType} (allowed: …)`.

**Keyless**, but it does need one config value: `import_artifact_dir`. Unset → `POST /api/v1/data-import/uploads`
returns **503** `File imports are not configured (no import root)`. That is a filesystem root, not
a provider key. File upload is the only ingress — there is no live GSC/GA API surface.

---

## 8. `billing`

`InvoiceResponse` (`GET|POST /api/v1/billing/invoices`, the four lifecycle routes):

```
number · client · amount (float) · subtotal (float) · tax (float) · currency · status · kind
issued · due · periodStart · periodEnd · notes · paidAt · paidMethod
```

Dates are **ISO strings, `""` when unset** (`due == "2026-08-27"`). `amount` is the DB `total`.
`InvoiceDetailResponse` = the above **plus exactly one key** `lines: [{id, description, quantity, unitAmount, lineTotal, sortOrder}]`.
`BillingStats` (`GET /api/v1/billing/stats`) = `{mrr (int), openInvoices, pastDue}`.
`RevenuePeriodResponse` (`GET /api/v1/billing/revenue?months=…`, 1-60, default 12) = `[{period ("YYYY-MM"), invoices (int), collected (float)}]`.

`InvoiceStatus` ∈ `draft | open | paid | past_due | void | refunded`.

**MRR comes from `clients.mrr`, never `sum(invoices)`.** `BillingStats.mrr` reads
`sum(mrr) from clients where status = 'active'` — it never touches the invoice table. The three
numbers answer three different questions and **will not agree**:

- **MRR** — the forward subscription run-rate (`clients.mrr`, active clients only).
- **openInvoices / pastDue** — ledger counts over `invoices`.
- **`/billing/revenue.collected`** — backward cash: `status = 'paid'` only, bucketed on
  **`paid_at`** (not `issue_date`), newest first. Refunded is excluded; void/open/draft never arrived.

**There is no payment gateway.** No charge, no dunning, no webhook, no reconciliation. Every
status move is a **manual operator action**. `paidMethod` is free text — an operator's statement,
not a gateway enum. The one automated move is a nightly beat that flips an already-issued `open`
invoice past its `due_date` (plus a grace period) to `past_due`; it only notices a date passed.

**Legal transitions** (the app guard and the DB trigger are twins):

```
draft    -> open, void          open     -> paid, past_due, void
past_due -> paid, void          paid     -> refunded
void     -> (terminal)          refunded -> (terminal)
```

An illegal move → **409** `Illegal invoice transition: {current} -> {target}`. Re-finalizing an
already-`open` invoice is a clean 409 (the diagonal is not legal at the app layer).

**Financial fields FREEZE once an invoice leaves `draft`.** Enforced in the app **and** by a DB
trigger. The 13 frozen columns: `client_id`, `client_name`, `kind`, `currency`, `issue_date`,
`due_date`, `period_start`, `period_end`, `subtotal`, `tax`, `total`, `notes`, `created_by`. Only
`status` + the `paid_*` stamps may move. Line items are insert/update/delete-able **only while the
parent is `draft`**. Editing a non-draft → **409**
`Invoice is {current}, not a draft - issued invoices cannot be edited`. `id` / `number` /
`created_at` are immutable **forever**, even in draft.

**Billing writes are owner/admin ONLY** — `require_role("owner", "admin")`. This **excludes
`manager`**, unlike every other module's LEAD write set, and mirrors the RLS policy byte-for-byte.
Reads need the `billing` feature grant + `view_reports`; the grant is not in the seo/content/va
role templates.

**The identifier is `number`, format `INV-####`** (`INV-0001`, sequence-assigned). The uuid `id`
never reaches the wire. Past 9999 the number simply grows (`INV-10000`) — the pad does not truncate.

A guarded `update … where number = %s and status = %s` backs every mutation; a miss → **409**
`Invoice changed concurrently`. There is **no `DELETE /billing/invoices/{number}` route** — void it.

---

## 9. Shared conventions

**Paging.** `?limit=` (1-200, **default 50**) `&offset=` (>= 0). Opaque; no cursor, no total.
Exception: `GET /api/v1/competitor-intel/competitors/{code}/backlink-gaps` **accepts `offset` and
ignores it** — paginating past page 1 silently re-returns page 1 (moot while the set is empty).

**The `workspace` route** on every module returns `ToolExtraResponse`:
`{kpis: [{label, value, delta?, dir?}], table: {title, icon, cols[], rows[][]} | null, primary: {label, icon} | null, bullets[]}`.
KPI `value` is a **pre-formatted display string** (`"$28.4k"`, `"—"`), not a number to compute on.
The Part-8 modules deliberately emit **no KPI deltas** (no stored baseline to compare against) —
an absent `delta` is not a zero-change, it is "not measured".

**Null discipline (the module family's cardinal rule).** `position` (rank_tracker), `rank`
(local_seo), and `clientPosition` (competitor_intel) are `int | None`, and every one of them
refuses `or 0` coercion on purpose: collapsing a null to 0 invents a rank **better than #1**. In
all three modules a **failed** fetch writes nothing at all, so a null is always a real observation
("checked, not there") and never a failure. **Never report a null as a lost or dropped ranking.**

**Queued is not done.** `{queued: true}` from any 202 means "enqueued", nothing more. The cost
gate, the provider call, and every hold live in the **worker**, after the response. Confirm an
outcome by re-reading the resource; never infer it from the 202.

---

## 10. Fields that do NOT exist (the invention traps)

Named here so a pinned output cannot reach for them:

- **rank_tracker** — no `searchVolume`, `cpc`, `previousPosition`, `nextCheckOn`, `clientId`, `id`
  on `RankKeywordResponse` (the identifier is `code`; movement is only the nested `change` object).
  No `currency` on the projection. History has no `cost` / `provider` / `own_urls`.
- **keyword_research** — no `intentSource`, `intentConfidence`, `metricsConfidence`, `competition`,
  `source`, `clientDa`, `winnabilityReason`, `degraded`, `partial`, `confidence`. **`tags` is
  writable via PATCH but is NOT in the response** (write-only from the API's view).
- **competitor_intel** — no `lastAnalyzedAt` (only the relative `analyzed`, literally `"never"`),
  no `competitorCode` / `keywordId` on a gap, no `overlap` on `CompetitorStats`, no `url` /
  `anchor` / `firstSeen` on a backlink gap, no `generatedAt` on SoV. `DiscoveryQueued.reason` and
  `AnalysisQueued.reason` are **always `""`** from the endpoint (the skip happens in the worker).
- **on_page** — no `reason` on `AnalysisQueuedResponse` (its competitor_intel twin has one — do not
  copy across). `score` is a **flat float**, not the breakdown (no `score.total` / `subScores`).
  `ApplyBulkResponse.skipped` **lumps together** skipped + blocked + held + failed — there is no
  per-state tally. `recommendation` is always `null` in apply-bulk results. `OnPageStats` has no
  `held` / `dismissed` / `quickWins` tile. No `appliedAt` / `appliedBy` / `wpPostId` on the wire.
- **local_seo** — no `position` (it is `rank`), no `rankChange` (it is `change`), no
  `googleLocationId` on the response (write-only in practice), no `status` on
  `RefreshQueuedResponse`, no `audit` embedded on a profile. Input `websiteUri` / `regularHours` /
  `locationLabel` are output **`website` / `hours` / `location`**. `avgRating` is `float|None`
  (null, not 0.0, when un-synced); `lastCheckedAt` / `lastSyncedAt` are `""` (not null) when unset.
- **client_onboarding** — no `vaultSecretId` / `secret` / `credential` on any response (only
  `hasCredential`), no `dueDate` (the key is **`due`**, and it is a **formatted display string**
  like `"Aug 14, 2026"` or `"—"`, not ISO), no `completedAt`, no `runId` on a step, no
  `ownerUserId`. No cost dial (this module makes no provider call).
- **data_import** — no `rows_total` / `rows_ok` / `rows_rejected` (see §7), no `stored_path`, no
  top-level failure `reason` on a run (a fatal error is appended **into** `errorSample` as a
  synthetic `{row: 0, …}` entry), no `progress`, no `sourceSignature` on a mapping response.
  `errorSample` is on **`ImportRunDetail` only**, not on list rows. `created` is **not ISO**.
- **billing** — no `total` (the wire key is **`amount`**), no `id`, no `clientId`, no `issue_date` /
  `due_date` (they are **`issued`** / **`due`**), no `mrr` on `RevenuePeriodResponse`, no
  `collected` on `BillingStats`, no MRR delta or trend anywhere. `lines` is on
  `InvoiceDetailResponse` only. No gateway fields (`payment_intent`, `receipt_url`, `dunning`, …).
  `status` / `kind` can serialize as **`""`** if a row ever holds an off-vocabulary value.
