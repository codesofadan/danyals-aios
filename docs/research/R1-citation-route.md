# R1 — Citation route — the true coverage number and the tiered strategy

**Track:** R1 · Citation route
**Status:** Decided — gates the Citation rebuild
**Date:** 2026-08-23
**Prior decisions touched:** D-2 (10¢ marginal / 20¢ fail line / loaded cost disclosed), D-14 (50×10 acceptance bar), CIT-001…CIT-027, AUTO-7/8/9/10, MT-013, DATA-2, DATA-7
**Prior findings this record CONTRADICTS, with evidence:**
- `docs/audit/FORENSIC_AUDIT.md:305` and `docs/audit/ENGINEERING_MASTER_PLAN.md:36`, `FEATURE_INVENTORY.md:121`, `SALVAGEABILITY_MATRIX.md:46`, `REQUIREMENT_GAP_ANALYSIS.md:32` — "**`FORM_SPECS` has 3 entries**". It has **50**. §3.1 shows the exact grep that produces 3 and why.
- `docs/recovery/DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1121` — "**53 keys in `FORM_SPECS`**". It is 50.
- `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1129` / `[CIT-CRED]` §4 and `db/migrations/0046_directories_seed.sql:27` — "**Data Axle … no public write API**", "no automatable write path". Data Axle **publishes a documented REST write API with Add / Renew / Update / Delete**, and the endpoint answers live. §4.1.
- `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1137` — class A contains "Bing Places, Foursquare". **Both are dead as coded**; a third path (Apple) that the catalogue marks `captcha_assisted` is in fact a live, documented API. §4.2.
- `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1167` / `[CIT-ECON]` — "**Own Playwright bot, marginal 0.4–0.8¢**". Correct only if the bot never uses a residential proxy. With proxy it is 0.5–2.6¢; and at 100-client volume the *fixed* browser-worker box costs ~11¢/unit on its own. §7.
- `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1156` (§16.4 item 4) — "**~95–110 attempted, ~70–90 live**". Not supported by any measurement. §6 gives the number I will stand behind: **45–65 attempted, 35–50 live per client inside 60 days.**

---

## 1. Decision

**We rebuild the citation module around an aggregator-and-API spine, and we demote browser automation from the strategy to a narrow, earned whitelist.** Concretely: (a) **Route A becomes the spine** — Data Axle Local Listings Premium (`POST https://local-listings-premium.data-axle.com/api/1/submissions`, submission types A/R/U/D), Apple Business Connect / Apple Business (`POST https://businessconnect.apple.com/api/v1/orgs/{orgId}/locations`) and Google Business Profile (`POST https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{accountId}/locations`) — the only three write paths I could reach and authenticate against on 2026-08-23; the Foursquare and Bing submitters in `backend/integrations/citation_apis.py` are **deleted**, not fixed, because their coded endpoints return 404 to a live probe. (b) **`FORM_SPECS` stops being a coverage claim and becomes an empty, earned whitelist**: a directory enters Route B only after a dated human live-DOM verification *and* one successful submission that produced a public listing URL; the 50 existing specs are reclassified `unverified` and none of them may be used in a volume run until it passes that gate (CIT-010). (c) **Route C — the human work queue — is promoted to a first-class, server-side product surface** with vault-held per-client credentials, pre-filled values, a one-click deep link, and evidence capture; `tools/finish_citation.py`, a local desktop script that prints a single shared password for every account (`tools/finish_citation.py:46`), is retired. (d) **Route F is never attempted** — Yelp, Trustpilot and Houzz publish clauses that forbid automated access, and per the standing ceiling rule the whole submission class is capped at **L3** anyway, so no route ever runs without a human approving the action or the batch. (e) **Every listing gets a `live_url`, a `verified_at`, and a re-check**; the module currently reports the *screenshot* path as the "live listing URL" (`backend/app/modules/citations/service.py:296-299`), which is exactly the fabrication class this project exists to eliminate. (f) We tell Daniel the honest number **before** he counts: **45–65 attempted and 35–50 live per client in the first 60 days**, at a **loaded** cost of **53–65¢ per live citation** (at a modelled $5–$10 Data Axle Add; 113¢ at $30) against a 10¢ marginal commitment that, on the corrected arithmetic in §7.3, only ever held for **Route B** — Route A's marginal cost is unpriced and breaches the line at every price modelled, and cannot be quoted until O-2 closes.

---

## 2. Context — the question this track had to settle

The citation module is the one part of the build the audits agree is wrong in *approach*, not merely in *finish*. Before a single line is rewritten, three things had to be settled, and the first was contested:

1. **How much coverage actually exists.** Three prior readings of the same file disagree by 16×: the forensic audit says 3 form specs against 151 bot-fillable directories (`FORENSIC_AUDIT.md:305`), the recovery specification says ~50 specs / "53 keys" against a 155-row catalogue (`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1118-1121`), and the module's own docstring says every spec is unverified (`backend/integrations/citation_bot.py:15`). A rebuild costed against the wrong baseline is a rebuild costed wrong.
2. **Whether hand-maintained DOM specs are a viable strategy at all.** `SALVAGEABILITY_MATRIX.md:46` calls 100 hand-maintained specs "a permanent, unfunded maintenance burden" and says *rebuild the approach*. That is a judgement, not evidence. It needed testing against the live web.
3. **Whether an aggregator route exists that the prior work dismissed.** `[CIT-CRED]` §4 recorded Data Axle and Neustar/Localeze as portal-only with no automatable path, which — if true — leaves browser automation as the only route and makes the ~100-platform target arithmetic impossible at 10¢. That claim was load-bearing and was never re-tested.

This blocks the build because the client holds a written commitment ("Under 10¢", 17 July 2026, `[CIT-ECON]`) and a written acceptance bar ("50 citations across 10 businesses", `[WA-TEAM]` 21/08). Both are counted in *live listings with proof*. Today the system cannot produce a live listing URL at all — the column does not exist (`db/migrations/0045_citation_web2_automation.sql:156-168`).

---

## 3. Findings

### 3.1 `FORM_SPECS` has exactly 50 entries. The "3" is a grep artefact, and I can reproduce it.

**Conclusion: the forensic audit's count is wrong; the recovery specification's is off by three; the true figure at HEAD is 50.**

Parsed from the AST, not grepped: `FORM_SPECS` is declared at `backend/integrations/citation_bot.py:196` and closes at `:875`, and holds **50** keys. Every key is a `FormSpec` with 3–7 `FormField`s, a submit selector and a success indicator; **none** carries a `CaptchaWidget`.

The "3" is reproducible. Of the 50 dict keys, exactly three are entirely lower-case alphanumeric-with-dots — `n49` (`:447`), `192.com` (`:651`), `411.ca` (`:694`). Every other key begins with a capital. A key-matching regex that omits `A-Z` returns precisely the audit's list:

```
$ grep -oE '^    "[a-z0-9._ -]+": FormSpec' backend/integrations/citation_bot.py
    "n49": FormSpec
    "192.com": FormSpec
    "411.ca": FormSpec
```

The "53" in `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1121` is not reproducible by any count I can construct: `grep -c "FormSpec("` also returns 50. Treat it as a transcription error.

Git history confirms the trajectory and rules out "it was 3 at audit time": 12 keys at `fd8c76a` (2026-07-20) → 36 at `95667a0` (2026-08-05) → **50** at `e4d1792` (2026-08-13, commit message "expand bot form-specs 36 -> 50") → unchanged through HEAD `2a502f9`. *(Corrected 2026-08-23: `7a14d82` is 11 commits behind HEAD, not HEAD. `FORM_SPECS` is unchanged from `e4d1792` to `2a502f9`; of the files cited in this record only `tools/finish_citation.py` changed in that window, and its `:46` claim still holds — see the verification pass.)*

`SIGNUP_SPECS` is **1** entry, not zero: `MerchantCircle`, at `backend/integrations/citation_signup.py:95-121`. The audit's "`SIGNUP_SPECS` is likewise empty of concrete entries" is off by one — immaterial to the decision, but it is part of the same over-reading.

### 3.2 The catalogue is 226 distinct rows, not 155 and not 241. The audit's tier split counted raw INSERT rows before the dedup.

**Conclusion: every prior tier count in the docs is a count of INSERT statements, not of table rows.**

Three migrations insert into `public.directories`, which carries `unique (name, market)` (`db/migrations/0045_citation_web2_automation.sql:130`) and every insert ends `on conflict (name, market) do nothing`:

| File | INSERT rows |
|---|---|
| `db/migrations/0046_directories_seed.sql` | 155 |
| `db/migrations/0065_directories_more.sql` | 57 |
| `db/migrations/0067_directories_more2.sql` | 29 |
| **Raw total** | **241** |
| **Distinct `(name, market)` — what the table actually holds** | **226** (188 distinct domains) |

| `tier` | Raw rows (241) | **Table rows (226)** |
|---|---|---|
| `bot_fillable` | 151 | **136** |
| `captcha_assisted` | 51 | **51** |
| `manual_only` | 29 | **29** |
| `aggregator` | 8 | **8** |
| `api` | 2 | **2** |

The forensic audit's table (`FORENSIC_AUDIT.md:308-315`) reads **151 / 51 / 17 / 2** — the raw column for `bot_fillable`, `captcha_assisted` and `api`, and for "manual" it read the *`submit_method`* column (`manual` appears 17 times) rather than the `tier` column (`manual_only`, 29). The recovery specification's "95 · 33 · 17 · 8 · 8" (`:1118`) is the `0046` file alone, with `api` miscounted as 8. Neither is a table count.

**Coverage of the catalogue by a spec:** all 50 spec keys match a catalogue `name` exactly (0 orphans). Because several names exist in more than one market, the 50 specs cover **57 of 226 rows (25%)**, and **51 of the 136 `bot_fillable` rows (37.5%)**. **Hand-verified specs: 0** — the module says so itself at `citation_bot.py:15-22` ("EVERY SELECTOR HERE IS A BEST-EFFORT STARTING SPEC, not hand-verified against each directory's current live DOM").

So all three prior readings are wrong in the same direction: they each report a *number of artefacts* as though it were a *number of working paths*. The number of working paths is the one nobody measured. I measured it.

### 3.3 Measured, 2026-08-23: 7 of the 50 spec URLs are even reachable, and 0 have ever been proven to accept a submission.

**Conclusion: the specs are not 37.5% coverage; they are 14% reachability and 0% proof.**

I fetched all 50 `FormSpec.url` values with a browser User-Agent, following redirects:

| Result | Count | Meaning |
|---|---|---|
| `200`/`202` | **7** | Page served to a plain HTTP client |
| `403` | **29** | WAF / anti-bot refusal (Cloudflare et al.) |
| `404` | **8** | The add-listing path does not exist |
| connection failure | **6** | DNS/TLS/host dead |

Three specs point at directories that **no longer exist as such** — the redirect chain says so:

| Spec | Coded URL | Ends at |
|---|---|---|
| `Cylex USA` (`:276`) | `www.cylex-usa.com/add-company` | `www.cylex.us.com/add-company` (domain moved) |
| `Applegate` (`:678`) | `www.applegate.co.uk/add-your-business` | `www.businessmagnet.co.uk/businessmagnet-acquires-applegate.htm` (**acquired**) |
| `Local.com.au` (`:819`) | `www.local.com.au/add-business/` | `www.airtasker.com/add-business/?…&domain=www.local.com.au` (**absorbed into Airtasker**) |

And `YaSabe` (`:336`) returns `200` only because `/add-business` 301s to the homepage — the path is gone.

I ran the same probe against the **86 raw INSERT rows carrying a researched `signup:` URL** in their `automation_note` (every such row is in `0065`/`0067`, which were researched later and more carefully than the specs). *Precision added 2026-08-23:* 86 is the raw-row count — the same raw-vs-table conflation §3.2 criticises. After the `(name, market)` dedup the table holds **71** such rows carrying **69** distinct URLs (82 distinct URLs across the 86 raw rows). The probe below covers all 86 raw rows; the percentages are unaffected.

| Result | Count |
|---|---|
| `200`/`202` | **36 (42%)** |
| `403` | **42 (49%)** |
| `404` / `5xx` / connection failure | **8 (9%)** |

Two things follow. First, **researched URLs are three times more likely to resolve than hand-guessed spec URLs** (42% vs 14%) — the specs were written faster than the catalogue and are worse. Second, **roughly half the automatable long tail sits behind a WAF**. Under the standing rule that CAPTCHA evasion is dropped, a 403 to an automated client is not an obstacle to engineer around — it is the platform's answer, and it routes the row to the human queue.

### 3.4 Both coded direct-API submitters are dead. A third, uncatalogued one is live.

**Conclusion: class A today is not "Bing + Foursquare, unverified". It is "Data Axle + Apple + GBP, verified reachable; Bing and Foursquare verified dead".**

Live probes, 2026-08-23, unauthenticated (a 404 means the path does not exist; a 401/403 means it exists and wants credentials):

| Endpoint as coded / documented | Probe | Verdict |
|---|---|---|
| `POST https://api.foursquare.com/v3/places` — `citation_apis.py:99` + `:115` | `404` `{"message":"Endpoint '/v3/places' not found."}` | **Does not exist** |
| `GET https://api.foursquare.com/v3/places/search` (control) | `401` `{"message":"Invalid request token."}` | Read API exists |
| `POST https://places-api.foursquare.com/places` (current host) | `404` `{"message":"Endpoint '/places' not found."}` | **No write path on the new host either** |
| `POST https://ssl.bing.com/webmaster/places/api/v1/locations` — `citation_apis.py:49` + `:68` | `301` → `POST https://www.bing.com/webmaster/places/api/v1/locations` → **`404`** | **Does not exist publicly** |
| `POST https://businessconnect.apple.com/api/v1/orgs/1/locations` | `401` `[{"code":"Unauthorized","message":"Invalid Token"…}]` — an unauthenticated re-probe on 2026-08-23 returned `401 [{"code":"Unauthorized","message":"Missing Authorization header",…}]`; the body varies with what is sent, the 401 does not | **Live, auth-gated** |
| `POST` and `GET https://local-listings-premium.data-axle.com/api/1/submissions` | `403` `{"result":"error","error":"forbidden"}` | **Live, auth-gated** |
| `POST https://local-listings-premium.data-axle.com/api/1/nonexistent` (control) | `404` HTML error page | Confirms the 403 above is authentication, not a missing route |

Foursquare's own product page explains why there is no write endpoint: adding a place is a **Placemaker** contribution — "suggest edits, removals, merges, flags, and statuses" — and a suggested edit "must get enough confirmations from Placemakers to be applied". That is a community-moderation queue, not an API a delivery platform can schedule. Foursquare therefore moves **out of route A entirely**.

Bing Places' API exists but is partner-gated. A Microsoft employee (IoTGirl, Microsoft Q&A, 2026-01-16) gives the onboarding path as emailing `placesfeedback@microsoft.com` from the account email. A widely-repeated eligibility threshold of "an agency managing more than 10,000 business listings" appears in secondary write-ups and in a Microsoft-hosted API PDF whose URL I could not retrieve (HTTP 409 on two attempts) — **[UNVERIFIED]**. At 100 clients this platform manages ~100–150 listings, two orders of magnitude below that figure, so I plan as if Bing API access is unavailable and treat Bing as a Route C human item.

### 3.5 The aggregator route the prior work closed is open, and it is the only route with a delete button.

**Conclusion: Data Axle Local Listings Premium is a real, documented, self-service-after-onboarding write API with Add/Renew/Update/Delete, and it is the correct spine.**

From Data Axle's own developer documentation:

- **Base** `https://local-listings-premium.data-axle.com/api/1`; auth is a token in an `X-AUTH-TOKEN` header, generated from the account settings page.
- **One endpoint, four verbs by submission type:** `POST /api/1/submissions` with type `A` (Add), `R` (Renew), `U` (Update), `D` (Delete). **Up to 100 place submissions per request.** Required fields: Company Name, Location Address, Location City, Location State/Province, Location Zip/Postal Code, Location Phone. `GET /api/1/submissions` polls status (`processing` / `completed` / `failed`, plus `processing_messages`).
- **Billing is on Adds and Renewals only** — "We bill based on the Local Listings Premium detected type for A-Adds and R-Renewals"; updates are free. A Renewal is a resubmission at least **12 months** after the last billable submission. Invoiced monthly in arrears.
- **Verification is real and human:** "A submission goes through multiple stages of verification including automated processing, teleresearch, and manual research"; "Our teleresearch team will make up to three calls over three business days in an attempt to verify the business."
- **Latency:** "The majority of files typically process in a matter of hours… Some files can take up to two weeks to process."
- **Deletion is first-class:** resubmit with type `D`; the FAQ scopes this to businesses that are out of operation, and directs failures to support.
- Bulk CSV/Excel is offered as an alternative, up to 5,000 listings per file.
- A **free, no-API** path also exists for small volumes at `https://local-listings.data-axle.com/search`, whose UI itself says "Submitting more than 10 listings? Learn more" and links to `https://www.data-axle.com/what-we-do/local-listings/#plans`.

**Price is the one thing Data Axle does not publish. [UNVERIFIED]** — no per-Add or per-Renewal figure appears anywhere I could reach; `www.data-axle.com` returns `403 "Site has been Taken Down."` to both WebFetch and curl, and the `/toc` page on the working subdomain also 403s. The `~$30/location managed` note at `db/migrations/0046_directories_seed.sql:27` carries no source and must not be used in a quote. What would settle it: call the number Data Axle publishes on the live tool, **(888) 274-5478**, or email `contentfeedback@data-axle.com`, and ask for the Local Listings Premium rate card for **A** and **R** submission types at ~150 records/year, plus whether an agency org may submit on behalf of unaffiliated clients.

Downstream fan-out is the other unpublished thing. Data Axle describes distribution "through a vast network of channels, such as leading search engines, Internet Yellow Pages (IYPs), navigation systems, smart speakers, mobile applications, and 411 directory services" but **names no publisher**. *Provenance corrected 2026-08-23:* that sentence lives on `https://www.data-axle.com/what-we-do/local-listings/`, which returns 403 to every client tried, so the quote is a **search-engine extraction — secondary**, on the same footing as the Neustar and Yext figures in §3.6. It is neither on the API docs nor in the FAQ, both of which were fetched in full. **[UNVERIFIED]** — and therefore *uncountable*. See §6: we submit to the spine and we **measure** what appears downstream; we never pre-promise a fan-out number.

### 3.6 The other aggregators, priced

**Conclusion: nothing in the managed-listings market gets near 10¢ per citation. The cheapest credible managed comparator is ~$2/citation and the cheapest per-location subscription is $199/year.**

All figures accessed 2026-08-23, from the vendor's own page unless marked.

| Vendor | Status | Published price | What the money buys | API? | Agency/reseller? |
|---|---|---|---|---|---|
| **Data Axle** (Local Listings Premium) | **Operating** | **[UNVERIFIED]** — quote-only | A/R/U/D submissions into its publisher network; teleresearch verification | **Yes**, documented REST | Org accounts exist; reseller terms **[UNVERIFIED]** |
| **TransUnion / Neustar Localeze** | **Operating** (Neustar is a TransUnion subsidiary; product now "TransUnion Digital Business Profile") | "less than $10/month… **$79 per year**" and "over 80 local search platforms" — **secondary** (search-engine extraction of `neustarlocaleze.biz/small-business-services/`; the site 403s to every direct fetch I attempted) | Portal-managed distribution | No public write API found | **[UNVERIFIED]** |
| **Foursquare** | Operating | Places API is pay-as-you-go, "Test select Pro API endpoints at no charge for up to 10,000 calls"; no per-call price published | **Read** POI data; adds go through community-moderated Placemaker | Read only | n/a |
| **Yext** | Operating | Public SMB plans page shows only "40+ online services" scanned, no prices; enterprise is quote-only. Widely-cited $199/$449/$499/$999-per-location-per-year SMB tiers are **secondary** and I could not confirm them on a Yext page — **[UNVERIFIED]** | ~200 publisher network | Yes | Reseller tiers exist, quote-only |
| **Uberall** | Operating | Quote-only; nothing published | Listings + reviews + social | Yes | White-label agency partner programme |
| **Synup** | Operating | **Solo $49/mo (1 location); Premium $299/mo (≤10) = $29.90/loc; Pro $499/mo (≤25) = $19.96/loc; Scale $899/mo (≤50) = $17.98/loc**; annual saves 20% | "catalog of **100+ publishers**" across "50+ countries", "typical locations sync to roughly **65–69** of them"; names Google, Apple, Bing, Facebook, Waze, HERE, TomTom, Garmin, MapQuest, Uber, Lyft and in-car nav | **Yes** — documented listing-management API, "over 80+ platforms", "Update 1,000+ Locations" | **Yes** — white-label, reseller support, multi-client console |
| **Moz Local** | **Operating** (not shut down) | **Lite $16/mo billed yearly ($199/yr) per location**; Preferred $24/mo yearly ($299/yr); Elite $33/mo yearly ($399/yr); 50+ locations → Enterprise custom | "**90+ Listing directories**"; "supports the purchased management of US, UK, and Canadian business listings"; Agency Permissions from Preferred | No listings write API (the "Moz API" is the link index — a different product) | Agency permissions, no reseller rate card |
| **BrightLocal** | Operating | **Citation Builder "Starting at $2 USD / citation"**; "as low as $2 with bulk credits"; a "$3.20 per site" rate also appears; platform plans "Price on request"; Managed SEO $1,299/mo; API "Custom price" | Citation building as a service | Yes, quote-only | n/a |
| **Whitespark** | Operating | **Listings Service packages $20–$999 (one-time)**; **Yext Replacement Service $399 per location (one-time)**; Local Platform $1/mo/location; Local Citation Finder $33–$149/mo | Listings Service = done-for-you citations; Local Platform is **GBP-only** | Not published | Not published |

**Read-through:** at 100 clients, Synup's Scale tier ($899/mo for ≤50 locations, ×2 tenancies = ~$21,576/yr) or Moz Local Lite (100 × $199 = $19,900/yr) buys 65–90 publishers per location with correction and removal built in. That is **$0.22–$0.33 per publisher-listing per year** — an order of magnitude below BrightLocal's $2/citation and completely different in kind from a one-off submission, because it *maintains* the listing. It is also ~2–3× the platform's whole loaded self-build cost (§7). This is the buy-vs-build line and it is close enough that it must be Daniel's decision, not an engineering assumption; §9 records it as an open item with the exact figures needed to close it.

### 3.7 Per-directory ToS position (CIT-022): verified for 12, ruled for the rest

**Conclusion: where terms exist, they ban automated *retrieval*, and a form-filling bot necessarily retrieves. That makes the ban binding on us. Most of the long tail publishes no reachable terms at all.**

Hand-verified today:

| Directory | Clause (quoted) | Source type | Route |
|---|---|---|---|
| **Yelp** (ToS eff. **1 Jan 2026**, §7.2(j)) | "Use any robot, spider, Service search/retrieval application, or other automated device, process or means to access, retrieve, copy, scrape, or index any portion of the Service" | Primary | **F** |
| **Yelp** `robots.txt` | `Disallow: /biz_update`, `/possible_biz_owner`, `/writeareview/`; and `User-Agent: ClaudeBot → Disallow: /` | Primary | **F** |
| **Trustpilot** (consumer terms) | "access, search or collect content from our platform by any means (automated or otherwise) except as provided on our platform **or specifically approved by us**" (§4 — *the trailing five words were missing from the delivered quote and are restored here 2026-08-23; they are a permission path, not a loophole we hold*); the same section separately bans "any text mining, data mining or web scraping of our platform for any purpose without our express permission"; and the definition of "you" expressly includes "automated technologies such as AI agents or screen scrapers" | Primary | **F** |
| **Houzz** (Terms of Use §4) | "You are expressly prohibited from any use of data mining, robots, scraping, or similar data gathering and extraction tools" | Primary | **F** |
| **Thryv** (operator of YellowPages.com / Superpages / DexKnows / Hotfrog) | "use any means to scrape or crawl any Web pages contained in This Website"; also bans "spidering or harvesting" and bypassing "any technological measure" | Primary — but the document says only that it governs "any of our websites on which these terms appear" and **names no property** | **C** (see note) |
| **Hotfrog** `robots.txt` | `Disallow: /add`, `/claim-listing/`, `/edit/`, `/login`; plus `Content-Signal: search=yes,ai-train=no,use=reference` and blocks on ClaudeBot/GPTBot | Primary | **C** |
| **OpenStreetMap** | Community norms forbid bulk/automated POI inserts — already recorded at `db/migrations/0046_directories_seed.sql:34` | Repo, previously sourced | **F** |
| **BBB** | No automation clause found; §2 bans using the Sites "to create, supplement, or compile data for any service…that performs substantially the same functionality" | Primary | **C** (human application + human review anyway) |
| **Google Business Profile** | API is allowlist-gated: "The Google My Business API is only visible in the Google API Console to users who submit and receive approval… through the access request form" (page updated 2025-08-28); create is `POST …/v1/accounts/{accountId}/locations`; "Locations can be used in Ads, but they need to be **verified** to be eligible to appear on Search and Maps" (page updated 2026-08-17) | Primary | **A**, via owned/manager access only — never a bot |
| **Apple Business Connect / Apple Business** | `POST {url}/api/{version}/orgs/{orgId}/locations`, bearer token, required `locationDetails{partnersLocationId, brandId, displayNames, mainAddress}`; a created location comes back in state **`SUBMITTED`** (i.e. reviewed before it is live) | Primary | **A** |
| **n49** `robots.txt` | Disallows `/edit-biz/`, `/actions.php`, `/review-process/`; **does not disallow `/add-business/`**; `Crawl-delay: 5`. No ToS page reachable (both `/terms/` and `/terms-of-use/` canonicalise to the homepage) | Primary | **B-provisional** |
| **Ourbis.ca** `robots.txt` | `User-agent: * / Disallow:` (nothing disallowed) | Primary | **B-provisional** |

**The rule for the remaining 214 rows** (because I will not invent 214 ToS positions):

> A directory's `tos_position` is one of `prohibits` / `silent` / `permits` / `unknown`, and it is set only by a dated human check that records the clause text and the URL. Until that check exists the row is `unknown`, and **`unknown` is not automatable** — it queues to Route C, never to Route B. A row moves to `permits`/`silent` (Route B eligible) only when *all four* hold: (1) no clause in the published terms bans automated access, retrieval, scraping or automated account creation; (2) `robots.txt` does not `Disallow` the add-listing path for `User-agent: *`; (3) the add-listing URL returns 2xx to a scripted client; (4) no CAPTCHA, phone, postcard or identity verification gates the submit. Failing (1) → `F`. Failing (2), (3) or (4) → `C`.

Two consequences worth stating plainly. **First, an anti-scraping clause binds a form bot.** Yelp's and Houzz's clauses prohibit automated *access and retrieval*, and a Playwright bot must GET the form page before it can fill it. There is no reading in which "we only submitted, we didn't scrape" survives. **Second, the catalogue currently disagrees with the terms in at least one live case:** `Yelp for Business` (US) is seeded `bot_fillable` with `signup:https://biz.yelp.com/claim`, which returns `200`. Under the rule above it is `F`. `tos_position` must therefore *gate* `tier`, not sit beside it.

### 3.8 What the prior work got right, and must be kept

**Conclusion: the machinery is good; only the strategy and the honesty layer are wrong.**

- **`backend/integrations/citation_discovery.py` (904 lines) is the best thing in the module and stays untouched.** It replaced an unobtainable BrightLocal dependency with Places → Serper → Foursquare → Firecrawl (optional) → Claude classification behind the same `CitationProvider` protocol, so `run_citation_monitor` consumed it unchanged (`:1-36`). It also degrades rather than crashes and never logs a secret. It is now doing double duty: it becomes the **verification engine** (§8), not just the audit engine.
- **The selection engine** (`backend/app/modules/citations/service.py`) — vertical match, authority floor (`DEFAULT_MIN_AUTHORITY = 30`), marketplace gate, build order core → tier1 → tier2, cap (`DEFAULT_CAMPAIGN_CAP = 45`), and a *counted* exclusion for every filter so a cap is never a silent truncation. Keep entirely.
- **`automatable_directories()`** already excludes `manual_only` *and* any row whose `submit_method` starts `aggregator:fed_by_` — i.e. it correctly refuses to submit to HERE, TomTom, Waze, Yahoo Local, MapQuest and Factual because they are fed by the spine. That is exactly right and must survive the rebuild.
- **The submission plumbing:** the `CitationSubmitter` protocol, the per-row claim worker with `task_acks_late` + always-ack (`backend/app/modules/citations/tasks.py:1-12`), the money-dial registration guard, the `citation_submit_status` ledger, the `ready_for_human` enum value and `handoff_url` column (`db/migrations/0064_citation_handoff.sql`), and the honest engine status board (`backend/integrations/citation_status.py`).
- **The `directories` strategy layer** (`0048`): `authority`, `authority_tier`, `access`, `is_marketplace`, `verticals`, `last_verified` — the right columns, deliberately NULLable so an unscored row is honestly NULL. Note that **only 18 of 226 rows carry an `authority` value**, and those values are unsourced "reference plan" figures — `Apple Business Connect = 99` and `MapQuest = 95` are clearly parent-domain metrics, not listing-page authority. **[UNVERIFIED]**; do not quote them to a client.

### 3.9 Four defects that must be fixed before any volume run

**Conclusion: the module can currently report a screenshot as a live listing, cannot store a listing URL, and hands a human one shared password for every account.**

1. **The screenshot is being reported as the live URL.** `backend/app/modules/citations/service.py:296-299` appends `proof_url` — documented as "screenshot/receipt" at `db/migrations/0045_citation_web2_automation.sql:162` — into `CitationGap.live_urls`, which the router serialises as `liveUrls` (`router.py:471`, `schemas.py:278`). A client or an operator reading "live URLs already earned" is reading a list of screenshot paths. This is the fabrication class the whole recovery exists to remove, and it is one field.
2. **There is no column for a live listing URL.** The `citations` table (`0018_offpage.sql:75-85`, extended at `0045:156-168`, `0064:16`) has `proof_url`, `external_ref`, `handoff_url` — and nothing that holds the public URL of the listing. CIT-011 ("live URL **and** screenshot") is therefore unsatisfiable by the current schema.
3. **There is no re-verification of a submitted listing.** `grep` for re-check / re-verify / `last_checked` / `next_recheck` across `backend/` and `db/migrations/` returns no citation hit: no column, no job, no state promotion from `submitted` to `live`. CIT-016 and AUTO-010 are unimplemented, and `directories.last_verified` (the *catalogue* health field, not the *listing* field) is never written. **Corrected 2026-08-23:** an earlier draft said "there is no Celery beat entry for citations" — that is false. `sweep-offpage-monitors` runs weekly (`backend/workers/celery_app.py:300-303` → `sweep_offpage_monitors`, `backend/workers/tasks/reports.py:323` → `monitor_offpage_job` → `run_citation_monitor`, `backend/workers/tasks/offpage.py:255`) and already fans a *discovery* citation monitor out per active client with a domain. What does not exist is any per-listing liveness re-check. This strengthens R25 rather than weakening it: the beat hook to hang the re-check on is already built and already cost-gated.
4. **The human queue is a desktop script with one shared password.** `tools/finish_citation.py` reads `tools/citation_handoffs.json` — an export containing every directory login for a campaign — and prints `Password for all: …` (`:46`). Credentials leave the platform as a file, and a single password compromise is a compromise of every account in the campaign. This directly violates CIT-007 in spirit. (Its NAP hardcode was already fixed — `IMPLEMENTATION_LOG.md:171-175`.)

### 3.10 Strategic context: citations are ~6% of local pack and rising for AI search

**Conclusion: the right deliverable is a small, correct, maintained citation set — not a large one.**

Whitespark's *2026 Local Search Ranking Factors* (published 2025-11-06) puts **citation signals at ~6%** of Local Pack/Maps weight — *corrected 2026-08-23 from ~7%; two independent reads of the report on that date (a direct fetch of the primary page and several secondary summaries) both give 6%* — and states "citations lost about half a percentage point, continuing the downward trend from previous editions." The accompanying group weights this record originally listed (GBP ~28%, reviews ~18%, on-page ~17%, links ~15%, behavioural ~12%) are **[UNVERIFIED]**: the report renders its weighting chart as a graphic, the figures are not extractable from the page text, and the secondary summaries disagree with each other (one gives GBP 32% / reviews 20% / on-page 15% / behavioural 9% / links 8%). Nothing in this record depends on them — only on citations being a small and shrinking single-digit share. What would settle it: read the weighting chart in a browser and record each figure with the chart's own labels. The same report says "3 of the top 5 AI Search visibility factors are citation factors" and "In AI SEO, mentions (citations) are the new link."

Google's Search spam policies (updated 2026-05-15) list "**Low-quality directory or bookmark site links**" as link spam. So the marginal 60th low-DA directory is not merely worth less than the 5th — at the bottom of the tail it is a documented negative. That is the evidentiary basis for keeping `DEFAULT_MIN_AUTHORITY = 30` and for reporting *why we skipped* rather than padding a count (CIT-024).

---

## 4. Classification of the whole catalogue

### 4.1 The rule

Applied to every one of the 226 rows, in order; the first match wins:

```
F  if tos_position = 'prohibits'
   or the platform gates net-new listings on identity/postcard/phone verification
      that only the business owner can clear (GBP, Apple, Facebook, Nextdoor, BBB, D&B)
   or community norms forbid bulk inserts (OpenStreetMap)
A  if tier in ('aggregator','api') AND a live, authenticated write path is verified
   -> today: Data Axle, Apple Business Connect, Google Business Profile
   (rows with submit_method LIKE 'aggregator:fed_by_%' are COVERED, never submitted)
B  if tos_position in ('permits','silent')
   AND robots.txt does not Disallow the add path for User-agent: *
   AND the add URL returns 2xx to a scripted client
   AND no CAPTCHA / phone / postcard / email-account gate
   AND a dated human live-DOM verification exists
   AND one prior submission produced a public listing URL
C  otherwise
```

Note the two clauses at the end of `B`. They are why **Route B starts at zero**: no row in the catalogue satisfies them today, because no spec has ever been verified and no submission has ever been proven live.

### 4.2 Counts

Applying the rule with today's evidence — `tos_position = 'unknown'` for 214 rows, so they fall to C:

| Route | Rows | Composition |
|---|---|---|
| **A — aggregator or direct API** | **3 live** (Data Axle, Apple, GBP-via-owned-access) + **6 covered-not-submitted** (HERE, TomTom, Waze, Yahoo Local, MapQuest, Factual) + **1 auto-generated** (BuildZoom, contractor-licence derived) | 10 catalogue rows carry `tier in ('aggregator','api')`; Foursquare and Bing are **demoted out of A** on the §3.4 probes |
| **B — open form, terms permit automation** | **0 today**; **15–25 within one verification sprint** | The realistic pool is the 36 catalogue signup URLs that returned 2xx plus the 7 spec URLs that did; expect ~60% to survive DOM verification and a real submission |
| **C — human work queue** | **~200** | 51 `captcha_assisted` + 29 `manual_only` + the ~120 `bot_fillable` rows that are WAF-blocked, account-gated, dead, or `tos_position = 'unknown'` |
| **F — prohibited** | **11–15** | Verified today: Yelp (×1 row), Trustpilot (×2 rows), Houzz (×1), OpenStreetMap, Google Business Profile *as a bot target*, Apple Business Connect *as a bot target*, Facebook Business Page, Nextdoor, BBB, D&B. Grows as ToS harvest proceeds |

The C bucket is deliberately enormous. That is the honest shape of this market once you stop treating a WAF as a puzzle. The job of the next six months is to move rows **C → B** one dated verification at a time, and to keep the count of B honest while doing it.

### 4.3 The value-ranked head of the catalogue

Ranked by: aggregator/api tier (+100), seeded `authority` where one exists (+DA), signup URL reachable today (+25), spec URL reachable today (+20), spec exists (+5). Every "signals" cell is measured on 2026-08-23 except `DA…`, which is the unsourced seeded value.

| # | Directory | Market | Seeded tier | Measured signals | **Route** |
|---|---|---|---|---|---|
| 1 | Data Axle (Local Listings) | GLOBAL | aggregator | API live, 403 unauth | **A — spine** |
| 2 | Apple Business Connect | GLOBAL | captcha_assisted | API live, 401 unauth; DA99 | **A** (catalogue tier is wrong) |
| 3 | Google Business Profile | GLOBAL | manual_only | API allowlisted; signup 200 | **A** via owned access; **F** for bots |
| 4 | Bing Places for Business | GLOBAL | api | coded path 404; partner-gated; DA93 | **C** (was A) |
| 5 | Foursquare Places | GLOBAL | api | write path 404; Placemaker-moderated; DA92 | **C** (was A) |
| 6–11 | MapQuest, Waze, HERE, TomTom, Yahoo Local, Factual | GLOBAL | aggregator | `aggregator:fed_by_*` | **A — covered, never submitted** |
| 12 | Superpages / YP Network (Thryv) | GLOBAL | bot_fillable | spec 403; DA89 | **C** (Thryv anti-crawl clause) |
| 13 | Yelp | GLOBAL | captcha_assisted | ToS §7.2(j); robots blanket-blocks; DA93 | **F** |
| 14 | MerchantCircle | US | bot_fillable | signup 403; spec 403; DA88; only `SIGNUP_SPEC` | **C** |
| 15 | Manta | US | captcha_assisted | signup 403; DA87 | **C** |
| 16 | Facebook Business (Page) | GLOBAL | captcha_assisted | DA95 | **F** |
| 17 | OpenStreetMap | GLOBAL | manual_only | community norms | **F** |
| 18 | Hotfrog | US | bot_fillable | spec 403; robots `Disallow: /add`; DA73 | **C** |
| 19 | Chamber of Commerce | US | bot_fillable | spec 403; DA71 | **C** |
| 20 | n49 | GLOBAL/US | captcha_assisted / bot_fillable | **signup 200 + spec 200**; robots permits `/add-business/` | **B-candidate #1** |
| 21–24 | Wellness.com, MyHuckleberry, FindaTopDoc, FindIt | US | bot_fillable | signup 200/202 (spec URL wrong for the first two) | **B-candidates** |
| 25–28 | Ourbis (CA), StartLocal (AU), Local Search (AU), YaSabe (US) | — | bot_fillable | spec 200/202; YaSabe's path 301s to home | **B-candidates** (YaSabe → C) |
| 29–41 | 2FindLocal, eLocal, BizHwy, ListYourBusiness.us, iBegin, Lacartes, iGlobal, Find-Us-Here, Fyple (US), US Chiropractic Directory, ChiroDirectory, Dentist Directory Canada, Lawyer Legion | US/GLOBAL/CA | bot_fillable | signup 200 | **B-candidates** (niche rows only for matching verticals) |
| 42–46 | LawGuru, Lawyer.com, Houzz (Find Pros), Thumbtack, Porch, Bark.com | US | bot_fillable / captcha_assisted | signup 200/202 | **C** — lead-gen marketplaces (`is_marketplace`), operator opt-in; Houzz is **F** on its ToS |
| 47 | Yelp for Business | US | bot_fillable | signup 200 | **F** — catalogue tier contradicts Yelp's ToS |
| 48 | Trustpilot | US + GLOBAL | captcha_assisted / manual_only | signup 200; ToS bans automated access incl. "AI agents" | **F** |
| 49–56 | PureLocal, Pink Pages, List Local Australia, Cylex (global), Fyple UK, Bizify, Europages, Yelp Canada | AU/UK/GLOBAL/CA | captcha_assisted / manual_only | signup 200/202 | **C** |
| 57–60 | Brownbook, Cylex USA, EZLocal, CitySquares, Tupalo, Judy's Book, YellowBot, ShowMeLocal | US | bot_fillable | spec 403 (×6), spec+signup 404 (ShowMeLocal), domain moved (Cylex USA) | **C**, ShowMeLocal → retire |

---

## 5. Options considered and why rejected

| Option | Disqualifying fact |
|---|---|
| **Keep the bot-first strategy and write the remaining ~85 form specs** | 29 of 50 existing spec URLs return `403` and 42 of 86 researched signup URLs return `403` to a scripted client (§3.3). Writing more specs does not clear a WAF; clearing a WAF is CAPTCHA/anti-bot evasion, which is out of scope by standing rule. And 3 of 50 specs point at directories that have been acquired, absorbed or renamed — a spec catalogue rots faster than one person can maintain it. |
| **Repair the Foursquare submitter** | `POST https://api.foursquare.com/v3/places` → `404 Endpoint '/v3/places' not found`, and `POST https://places-api.foursquare.com/places` → `404` on the current host. Foursquare's own product page routes place additions to Placemaker, whose suggested edits "must get enough confirmations from Placemakers to be applied". There is no endpoint to repair. |
| **Repair the Bing Places submitter** | Coded path `POST https://ssl.bing.com/webmaster/places/api/v1/locations` 301s to `www.bing.com/...` and returns `404`. Real access is a trusted-partner programme reached via `placesfeedback@microsoft.com` (Microsoft employee answer, 2026-01-16), with a widely-repeated but unconfirmed 10,000-listing eligibility bar — two orders of magnitude above this platform's volume. |
| **Apify actor as the default submission route** | 25¢/unit — 2.5× the 10¢ written commitment and above even the 20¢ hard line (`[CIT-ECON]`, D-2), and the client raised the cost himself (`[WA-ADAN]` 04/08). Already decided: narrow, explicitly-approved fallback only, visible per unit in the ledger (CIT-015). Unchanged. |
| **BrightLocal / Whitespark Citation Builder as the delivery mechanism** | BrightLocal Citation Builder is "Starting at **$2 USD / citation**". At the honest volume (§6) that is $2 × 45 × 100 = **$9,000/year** and it is 20× the commitment. It also produces no proof artefact the platform owns. Rejected as the mechanism; retained as the **price ceiling** the build must beat and as the emergency fallback for a client who must be delivered today. |
| **Yext / Uberall as the aggregator** | Neither publishes a price a one-person agency can plan against; both are quote-only for the tiers that matter, and Yext's SMB per-location figures are **[UNVERIFIED]**. Uberall's own market is "mid-market and enterprise". An un-priceable dependency cannot sit under a fixed-price service. |
| **Moz Local or Synup as the whole citation product (buy, not build)** | **Not rejected — deferred to Daniel.** Moz Local Lite is $199/yr/location for 90+ directories with US/UK/CA coverage; Synup Scale is $899/mo for ≤50 locations (~$216/loc/yr) for 100+ publishers with a documented API and a white-label reseller path. At 100 clients that is ~$19,900–$21,600/year against a self-build loaded cost of ~$1,600–$2,600/year (§7) — but the bought option *maintains and corrects* listings and carries no spec-rot risk. §9, open item **O-1**. |
| **A shared house account per directory across all clients** | CIT-007 (per-client accounts under the client's own identity, never shared) is CONFIRMED and was recorded as a ban-avoidance measure. `tools/finish_citation.py:46` currently prints one password for every account in a campaign, which is the shared-failure-domain risk MT-9 already flagged. Not revisited. |
| **Raise the automation ceiling for well-behaved Route B directories** | Not permitted. The ceiling is a property of the task class: citation submission is capped at **L3** regardless of the bot's success rate. Route B's benefit is that a human approves a *batch* rather than performing each action — not that the human disappears. |

---

## 6. The honest coverage number

**I will stand behind: 45–65 attempted and 35–50 live per client inside 60 days, per market, with every non-live unit explained.** The recovery specification's "~95–110 attempted, ~70–90 live" is not supported by anything I can measure and should be withdrawn before Daniel counts against it.

Arithmetic, per US client, first campaign:

| Route | Attempted | Live-rate basis | **Live** |
|---|---|---|---|
| **A** — Data Axle Add, Apple location, GBP location | **3** | All three endpoints verified reachable; each has a verification gate (Data Axle teleresearch up to 3 calls/3 business days; Apple returns state `SUBMITTED`; GBP requires verification before Search/Maps eligibility) | **2–3** |
| **A-fanout** — HERE, TomTom, Waze, Yahoo Local, MapQuest, Factual + the unnamed Data Axle publisher network | **0 submitted** | Never promised. **Discovered and counted after the fact** by `citation_discovery.py` at the 30- and 60-day re-checks | **measured, reported as a bonus** |
| **B** — verified-spec whitelist | **15–25** | Every entry has already produced one live URL by definition of entry; failures are drift | **11–18** (≈70%) |
| **C** — human work queue | **25–35** | A human clears the gate, so the failure mode is "the directory rejected the business", not "the bot broke" | **20–28** (≈80%) |
| **F** — prohibited | **0** | Each of the 11–15 rows is listed in the client report with the clause and the URL (CIT-024) | **0** |
| **Total** | **43–63** | | **33–49** |

Rounded to the number that goes in front of a client: **45–65 attempted, 35–50 live.** Path to more: grow the Route B whitelist by 5–10 verified specs per month (each verification is 15–25 minutes of human work amortised across all 100 clients), which reaches **~70 live** in roughly six months without a single new line of engine code — because a spec is data.

Against the acceptance bar ("50 citations across 10 businesses"): the bar is **met on the first campaign for a US client and missed for AU** (the AU tail is thinner and more WAF-defended — 4 of 8 AU spec URLs are dead or blocked). Report per market, never as a single number.

---

## 7. Cost model at 100 clients

**Inputs, all sourced 2026-08-23 unless marked:**

| Input | Value | Source |
|---|---|---|
| CapMonster reCAPTCHA v2 | **$0.60 / 1,000** = $0.0006/solve | capmonster.cloud |
| CapMonster Cloudflare Turnstile | **$1.30 / 1,000** = $0.0013/solve | capmonster.cloud |
| CapMonster text CAPTCHA | **$0.30 / 1,000** = $0.0003/solve | capmonster.cloud |
| IPRoyal residential proxy | **$7.00/GB** PAYG @1GB; **$5.25/GB** PAYG @10GB = **$0.00513/MB** | iproyal.com — *corrected 2026-08-23: $5.25/GB is the **pay-as-you-go** 10 GB rate; the 10 GB **subscription** rate is $5.51/GB. The per-MB figure and everything derived from it are unchanged.* |
| Serper SERP query | **$50 / 50,000 credits = $0.001/query** (entry rate); ~~$0.0005 at Scale~~ **[UNVERIFIED]** | serper.dev publishes no pricing table at the cited URL (`serper.dev/pricing` returns 404; the root page carries none), so neither tier name nor the bulk rate could be read from a primary source. The **$50 / 50,000 = $0.001** entry rate is corroborated by several independent secondary write-ups and matches `backend/app/config.py:764` (`price_serper_per_query: float = 0.001`), which is the figure this model actually uses. Bulk rates are reported as low as ~$0.0003/query. Settling it: log in to the Serper dashboard and screenshot the credit-pack table. |
| Browser-worker box | DigitalOcean Basic **4 vCPU / 8 GiB = $48/month** | digitalocean.com/pricing/droplets |
| Human minute | **$0.10/min ($6/hour)** — **[UNVERIFIED — owner input]**; sensitivity at $3/h and $12/h below | — |
| Data Axle Add / Renew | **[UNVERIFIED]** — modelled at $5 / $10 / $30 | — |

**Volumes at 100 clients, one campaign each per year:** Route A 300 submissions (3/client) + 100 Data Axle renewals from year 2; Route B 100 × 20 = **2,000**; Route C 100 × 30 = **3,000**. Total **5,300** units/year, **~4,100** live.

### 7.1 Marginal cost per unit

| Route | Components | Marginal |
|---|---|---|
| **A** | Data Axle Add ($X) + Apple API call ($0) + GBP API call ($0) | **$X/3 per unit** — at $5/$10/$30 per Add: **$1.67 / $3.33 / $10.00** per unit. **Corrected 2026-08-23:** this row previously read "1.7¢ / 3.3¢ / 10.0¢", which is the same arithmetic with the unit off by 100× ($5 ÷ 3 = $1.67, not 1.7¢). At every modelled Data Axle price Route A is **17×–100× the 10¢ marginal line**; three Route-A units come in under 10¢ each only if an Add costs ≤ **$0.30**, which no comparator in §3.6 suggests. Route A's marginal cost is therefore **unknown and probably breaching** until O-2 closes — which is exactly why R33 makes the route block while the price is unset. |
| **B** | Compute only. **No residential proxy**: by the §4.1 rule, a directory that needs a proxy to look human is defended, and a defended directory is Route C. This is the single largest cost change from dropping evasion. | **≈$0.002** (see §7.2) |
| **C — bot-prepared portion** | 1 CAPTCHA solve ($0.0006–$0.0013) + ~3 MB residential proxy ($0.0154) + compute ($0.002) | **≈$0.018** — **flagged 2026-08-23: this line contradicts the rest of the record and the standing constraints.** §3.3 states that CAPTCHA evasion is dropped and §4.1's rule routes any row with a CAPTCHA gate *to* Route C precisely because a human clears it. Paying CapMonster to solve a CAPTCHA on a Route C directory *is* the evasion the standing rule bans, and `backend/app/config.py:627` already defaults `captcha_solver_provider` to a live solver. The build must take the §4.1 reading: **the human clears the CAPTCHA and this component is $0** unless Danyal explicitly reinstates paid solving as a policy decision, in which case it is recorded as a decision and not as an engineering default. The proxy and compute components are unaffected. |
| **C — human portion** | 4–6 min @ $0.10/min | **$0.40 – $0.60** |

**This corrects `[CIT-ECON]`'s "0.4–0.8¢" own-bot figure.** That number implies well under 1 MB of proxied traffic per submission. A modern directory add-form flow is 2–6 MB; at IPRoyal's $0.00513/MB that alone is **1.0¢–3.1¢**. The figure is only right for a proxy-free run — which is precisely what Route B now is, so the *conclusion* survives even though the *reasoning* in the delivered document does not.

### 7.2 The fixed cost nobody counted

A dedicated browser worker at $48/month is **$576/year**. Spread over 5,300 units that is **$0.109 per unit** — on its own, larger than the entire 10¢ marginal commitment. At 100 clients the citation volume is far too small to amortise a dedicated box: 4 concurrent Playwright sessions at ~60 s each is ~240 sessions/hour, so 5,300 units is about **22 hours of work per year** — a 0.25% duty cycle.

**Engineering consequence:** do **not** provision a separate browser-worker VPS for citations at this volume. Run the browser work on the existing single VPS behind a strict concurrency cap, and revisit MT-013 when sustained citation volume exceeds ~50,000 units/year (~208 machine-hours = **~2.4% duty** on a $48 box — *corrected 2026-08-23 from "~10% duty", which does not follow from the 240-sessions/hour figure in the sentence before it* — i.e. ~1¢/unit). If a separate box is provisioned anyway for isolation reasons, book its $576/year as a **fixed platform cost**, never as a per-citation marginal — presenting it as marginal is how a 10¢ ceiling gets "met on paper and missed in reality" (`DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1176`).

### 7.3 Annual, at 100 clients

| Line | Units | Rate | **Annual** |
|---|---|---|---|
| Data Axle Adds (yr 1) | 100 | $5 / $10 / $30 **[UNVERIFIED]** | **$500 / $1,000 / $3,000** |
| Data Axle Renewals (yr 2+) | 100 | same | same |
| Apple + GBP API calls | 200 | $0 | **$0** |
| Route B compute | 2,000 | $0.002 | **$4** |
| Route B spec maintenance — 20 specs × 2 re-verifications/yr × 15 min | 10 h | $6/h | **$60** |
| Route C bot-prep (CAPTCHA + proxy + compute) | 3,000 | $0.0167 *(§7.1 derives $0.018 from its own components — $0.0006 + $0.0154 + $0.002; the $4/yr difference is immaterial and is not carried through the totals below)* | **$50** |
| Route C human time — 3,000 × 5 min | 250 h | $6/h | **$1,500** |
| Re-verification — 4,100 live × 4 checks/yr × 2 Serper queries | 32,800 q | $0.001 | **$33** |
| Re-verification Claude classification — batched 20 listings/call | 820 calls | ~$0.01 | **$8** |
| **Total excluding Data Axle** | | | **$1,655** |
| **Total including Data Axle @ $10/Add** | | | **$2,655** |

**Per live citation (4,100 live/yr):**

| | **Marginal (Routes A+B only)** | **Loaded (all routes, all human time)** |
|---|---|---|
| Data Axle @ $5 | **29.6¢** | **52.6¢** |
| Data Axle @ $10 | **59.1¢** | **64.8¢** ← plan against this |
| Data Axle @ $30 | **176.7¢** | **113.5¢** |
| Human rate $3/h instead of $6/h | unchanged | **45.7¢** (@ $10 Add) |
| Human rate $12/h instead of $6/h | unchanged | **102.8¢** (@ $10 Add) |

**Both columns were corrected on 2026-08-23; the loaded @ $10 and @ $30 figures were already right.**

- *Marginal column, rebuilt.* The delivered figures (3.4¢ / 3.5¢ / 3.7¢) are not reproducible from any input in this section and are internally incoherent: a $5→$10 move in the Add price changes the Data Axle line by $500, and shifting a per-unit figure by 0.1¢ on $500 implies a denominator of 500,000 units — the next step implies 1,000,000. Against the stated volumes the derivation is: A+B marginal spend = 100 Adds × $X + 2,000 Route-B units × $0.002; A+B live ≈ **1,700/yr** (250 Route A + 1,450 Route B, from §6). That gives 29.6¢ / 59.1¢ / 176.7¢. **Route A dominates it entirely and the whole column is an artefact of an unverified price.**
- *Loaded @ $5.* ($1,655 + $500) ÷ 4,100 = **52.6¢**. The delivered 40.4¢ is $1,655 ÷ 4,100 — the total **excluding** Data Axle, i.e. the $5 Add was priced at zero.

**Verdict against D-2 — restated 2026-08-23 after the table above was corrected.** The ≤10¢ **marginal** target holds comfortably for **Route B alone** ($0.002/unit, compute only). It does **not** hold for Route A at any price modelled here, and Route A's true price is `[UNVERIFIED]` (O-2). The blended A+B marginal is **29.6–176.7¢**, so on today's evidence the marginal commitment **breaches both the 10¢ target and the 20¢ hard fail line** the moment a Data Axle Add is priced above **$0.30**. This does not change any engineering requirement — R33 already forces `data_axle_add_cost_estimate` to default to 0 and block the route while unset — but it does change what may be said to the client: *the 10¢ marginal figure is defensible only for the browser route, and Route A cannot be costed until O-2 closes.* The **loaded** figure is **53–65¢** at $5–$10 per Add (113¢ at $30), four to six times the commitment, and it is dominated by one line: **human minutes on Route C are 90% of the loaded cost excluding Data Axle, and 56% of the $2,655 total at $10/Add.** The 20¢ hard fail line is breached by the loaded figure at every price. D-2's resolution ("engineer to ≤10¢ marginal; 20¢ hard fail; report loaded cost separately and proactively") is therefore confirmed and now has real numbers behind it — and its action item ("tell Danyal the 17 July figure was a *marginal* cost, before he discovers it") is now urgent, because the gap is 4–6×, not 2×.

**The lever that moves the loaded number is minutes per item and the Data Axle price — not Route C volume. Corrected 2026-08-23.** The delivered claim — that cutting Route C from 30 to 15 units per client "brings the loaded cost to ~35¢" — is wrong, because halving Route C halves the **numerator and the denominator together**. Route C's own loaded cost per *live* unit is ($0.018 + $0.50) ÷ 0.80 = **$0.648**, which is indistinguishable from the blended $0.648, so the per-live-citation figure does not move: total spend falls from ~$2,655 to ~$1,868 (−30%) while live citations fall from 4,100 to 2,900, giving **~64¢**, essentially unchanged. Cutting Route C volume is still worth doing for the reason §3.10 gives — fewer, better citations — and it genuinely reduces total spend; it is simply not a lever on unit cost. The two real levers are **minutes per queue item** (R20/R4: at 10 minutes instead of 5 the loaded figure roughly doubles) and **the Data Axle Add price** (O-2).

**Buy-vs-build reference point:** Moz Local Lite at 100 locations is $19,900/year for 90+ directories per location, maintained and correctable. That is ~$0.22 per publisher-listing per year and ~7.5× the self-build loaded total — but it eliminates spec rot, the human queue and the correction problem in one purchase. See O-1.

---

## 8. Engineering requirements this imposes

Numbered so a developer can build without re-reading the research.

**Schema**

1. **`ALTER TABLE public.citations`** add: `live_url text not null default ''` (the public listing URL — never a screenshot path); `live_url_verified_at timestamptz`; `verification_method text not null default ''` (`http_probe` | `discovery` | `human`); `verification_evidence jsonb not null default '{}'` (`{http_status, matched_fields:[...], screenshot_path, checked_from}`); `next_recheck_at timestamptz`; `recheck_count int not null default 0`; `route char(1) not null default 'C' check (route in ('A','B','C','F'))`; `blocked_reason text not null default ''`; `skip_reason text not null default ''` (CIT-024). Index `citations (next_recheck_at) where submit_status in ('submitted','verified')`.
2. **Extend `citation_submit_status`** with `live`, `drifted`, `delisted`, `removal_requested`, `removed`. `submitted` must stop meaning "done" — only `live` means a listing exists.
3. **`ALTER TABLE public.directories`** add: `tos_position text not null default 'unknown' check (tos_position in ('prohibits','silent','permits','unknown'))`; `tos_source_url text not null default ''`; `tos_clause text not null default ''`; `tos_checked_at timestamptz`; `tos_checked_by uuid references public.users(id)`; `robots_disallows_add boolean`; `add_url text not null default ''` (promote the `signup:` prefix out of `automation_note`); `add_url_status smallint`; `add_url_checked_at timestamptz`; `route char(1) not null default 'C'`. **`route` is derived, never hand-set** — a nightly job recomputes it from the §4.1 rule.
4. **New table `public.directory_specs`** — the spec whitelist, replacing the in-code `FORM_SPECS`: `(id, directory_id, spec jsonb not null, verified_at timestamptz, verified_by uuid, first_live_url text, drift_detected_at timestamptz, active boolean not null default false)`. `active` may only be set true when `verified_at IS NOT NULL AND first_live_url <> ''`. RLS: staff read, lead write.
5. **New table `public.citation_removals`** — `(id, citation_id, requested_by, requested_at, reason, method text check (method in ('api_delete','account_edit','support_ticket')), ticket_ref text, resolved_at, evidence jsonb)`. Backs CIT-019.
6. **New table `public.client_change_events`** (DATA-7) — `(id, client_id, business_profile_id, field, old_value, new_value, occurred_at, fanout_state jsonb)`. A NAP change writes one row and flips every `live` citation for that profile to `correction_required`.

**Route A — the spine**

7. **`backend/integrations/citation_apis.py`: delete `FoursquareSubmitter` and `BingPlacesSubmitter`.** Both write paths return 404 (§3.4). Remove `api:foursquare_places` and `api:bing_places` from the catalogue's automatable set in the same migration; re-seed both rows as `tier='manual_only'`, `route='C'` with `automation_note` recording the 404 and the date.
8. **New `backend/integrations/citation_aggregators.py` → `DataAxleSubmitter`**, implementing the existing `CitationSubmitter` protocol. Base `https://local-listings-premium.data-axle.com/api/1`; header `X-AUTH-TOKEN: <settings.data_axle_api_key>`; `POST /submissions` with `{"submissions": [ … ]}`, **max 100 per request**; `submission_type` `A` on first submit, `U` on correction (**not billable**), `R` on annual renewal, `D` on removal. Required fields map from `business_profiles`: Company Name ← `business_name`, Location Address ← `address_line1`, City ← `city`, State/Province ← `region`, Zip/Postal ← `postal_code`, Phone ← `phone`. Poll `GET /submissions?…` for `status ∈ {processing, completed, failed}` and surface `processing_messages` verbatim into `citations.error`.
9. **`DataAxleSubmitter` must never return `verified`.** Data Axle runs teleresearch — up to three calls over three business days — and files can take up to two weeks. Return `submitted`, set `next_recheck_at = now() + interval '3 days'`, and let §8-R17 promote to `live`.
10. **Client consent gate for Route A.** Data Axle's teleresearch calls the *client's* phone. A campaign may not queue a Data Axle Add unless the client record carries a stored, dated authorisation (the standing authorisation already PROPOSED at `DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:768`). Block, do not warn.
11. **New `AppleBusinessSubmitter`.** `POST https://businessconnect.apple.com/api/v1/orgs/{orgId}/locations`, `Authorization: Bearer <token>`, body `{"locationDetails": {"partnersLocationId": <citations.id>, "brandId": …, "displayNames": […], "mainAddress": {…}}}`. A created location returns state `SUBMITTED` → map to `submitted`, never `verified`. `partnersLocationId` must be our own `citations.id` so the update/delete path is idempotent.
12. **GBP stays on owned/manager access.** `POST https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{accountId}/locations`. Never bot it. Google's docs state a created location "need[s] to be verified to be eligible to appear on Search and Maps" — so GBP is `submitted` until verification completes, and verification is a Route C human item.
13. **Never submit a `aggregator:fed_by_%` row.** `automatable_directories()` already enforces this (`service.py:27-38`); add a test that fails if HERE, TomTom, Waze, Yahoo Local, MapQuest or Factual ever appears in a queued batch, and render them in the client report as **"covered by aggregator, no separate submission"** with a zero cost.

**Route B — the earned whitelist**

14. **Move `FORM_SPECS` out of Python into `directory_specs.spec` (jsonb) and ship the table empty of `active` rows.** Migrate all 50 existing specs in as `active = false`, `verified_at = NULL`. `PlaywrightCitationSubmitter` loads only `active = true` specs. This is the single change that converts a coverage *claim* into a coverage *fact*.
15. **Spec verification workflow** (CIT-010): an operator screen that, per directory, opens the live add form, diffs each selector against the live DOM, records the diff, and requires an explicit "verified" click plus a first successful submission that returned a public URL before `active` can be set. Store `verified_at`, `verified_by`. A spec older than **90 days** without a successful submission auto-deactivates.
16. **Drift detection** (CIT-020): on any submit failure caused by a missing selector, write `directory_specs.drift_detected_at`, set `active = false`, emit a task to the operator with the selector that vanished and the screenshot, and **do not retry** — AUTO-9 already says never blind-retry a submission.
17. **No residential proxy on Route B.** Route B is by definition undefended; if a Route B directory starts returning 403 or presenting a CAPTCHA, that is a route change (B → C), not a reason to buy proxy bandwidth. Enforce in `citation_bot_from_settings`: if `route='B'` and a proxy URL is configured, ignore it and log once.

**Route C — the human work queue as a product**

18. **Retire `tools/finish_citation.py` and `tools/citation_handoffs.json`.** Credentials must never leave the platform as a file, and one password for every account (`:46`) is a single point of total compromise.
19. **A queue item is a server-side row** rendered at `/admin/citations/queue`, containing exactly: client + location label; directory name + authority + why it was selected; **the exact deep link** (`directories.add_url`, verified 2xx within 24 h); **every field value pre-computed and copy-buttoned** from `business_profiles` (name, address, city, region, postcode, phone, website, categories, description, hours, email alias, logo URL, socials); the per-client per-directory credential **fetched from the vault at render time and never stored in the page's HTML source or logged**; the reason it is in the queue (`captcha` / `waf_403` / `phone_verify` / `postcard` / `tos_unknown` / `account_gated`); an expected-time estimate; and a **"prohibited — do not submit"** banner if `tos_position='prohibits'`.
20. **Target 4 minutes per item.** Pre-filling every field and giving one deep link is what makes 4 minutes possible; it is also the difference between 40¢ and 65¢ per live citation (§7.3). Measure actual minutes per item and surface the rolling median on the cost dashboard — the loaded cost model is only as good as this number.
21. **Completion requires evidence, not a checkbox.** To close an item the operator must supply a **live listing URL**; the system then runs R22 synchronously and refuses the completion if it fails. It also captures a screenshot server-side (not from the operator's machine) and stores it as `proof_url`. `live_url` and `proof_url` are different columns and neither may be populated from the other.
22. **Per-client credential isolation** (CIT-007, CIT-027, MT-9): one vault entry per `(client_id, directory_id)`; a distinct generated password per entry; a **per-client plus-addressed or per-client alias** email rather than one shared catch-all, so one mailbox failure cannot block another client. Rotate on removal.

**Verification and liveness**

23. **The liveness test.** A citation is `live` iff **all** of: (a) `live_url` returns 2xx to an unauthenticated GET; (b) the rendered text contains the canonical `business_name` **and** (normalised `phone` **or** `address_line1`); (c) a dated screenshot exists; (d) the check ran from an IP not used for the submission. Anything less is `submitted`. Record the outcome in `verification_evidence`.
24. **Re-check cadence.** Route A anchors and `authority_tier='core'`: **monthly**. Everything else: **quarterly**. New listings: at **+3 days, +14 days, +60 days**, then the standing cadence. Cost is negligible (§7.3: ~$41/year for 100 clients), so cadence is a quality decision, not a budget one.
25. **The re-check is `citation_discovery.py`, not a new module.** Reuse the Places → Serper → Foursquare → Claude pipeline: it already resolves a canonical NAP anchor and judges consistency. A re-check that finds the listing but with drifted NAP → `drifted` + a task; finds nothing → `delisted` + a task. This is also how **aggregator fan-out gets counted** — a listing that appears on HERE or MapQuest without us submitting is discovered here and reported as covered.
26. **Fix the live-URL lie now.** `backend/app/modules/citations/service.py:296-299` must read `live_url`, not `proof_url`, and must require `submit_status = 'live'`. Add a regression test asserting that a citation with a `proof_url` and no `live_url` contributes zero entries to `CitationGap.live_urls`.

**Correction, removal and honesty**

27. **Correction/removal paths, by route** (CIT-019): **A** → Data Axle `submission_type='U'` (free) or `'D'`; Apple update/delete on `/orgs/{orgId}/locations/{id}`; GBP patch/delete. **B/C** → log in with the vault credential and edit, else raise a `citation_removals` row with `method='support_ticket'` and track the SLA. Every live citation must display a **"Correct" and a "Remove"** action in the admin UI; a listing the system cannot correct must say so in the client ledger.
28. **NAP fan-out** (DATA-7): a change to `business_profiles` writes a `client_change_events` row and flips every `live` citation for that profile to `correction_required` with a queue item per unit. The client portal must not permit a direct NAP edit — it raises a request (already PROPOSED at `:759`).
29. **`skip_reason` is mandatory output** (CIT-024). Every catalogue row not attempted for a client renders in the client report with a one-line reason: `prohibited_by_terms` (+ the clause URL), `below_authority_floor`, `off_vertical`, `marketplace_not_opted_in`, `fed_by_aggregator`, `directory_dead`, `no_verified_spec`. A client comparing "100 promised" to "45 delivered" reads the other 55 here.
30. **No fabricated field, ever** (CIT-023): if a directory's spec requires a field the profile does not carry, the unit blocks with `blocked_reason='missing_field:<name>'` **before** the cost gate fires. Negative test required.
31. **ToS harvest job** (CIT-022): a weekly task that, per directory, fetches `robots.txt` (machine-readable — set `robots_disallows_add`) and probes `add_url` (set `add_url_status`, `add_url_checked_at`), then queues a **human** review item for any row where `tos_position='unknown'` and `route` would otherwise be B. Never let a model infer a ToS position; store the quoted clause and its URL or store `unknown`.
32. **Cost ledger honesty** (CIT-013, CIT-014): each `citations.cost` records the marginal spend; a separate `citation_loaded_cost` view adds allocated human minutes (from R20), allocated spec-maintenance minutes and allocated fixed compute. The dashboard shows **both**, side by side, with the 10¢ line drawn on the marginal chart and the 20¢ line on neither — 20¢ is a marginal fail line, and the loaded figure will exceed it by design.
33. **Config changes:** delete `citation_api_cost_estimate` (`backend/app/config.py:635`) along with the two dead submitters; keep `citation_bot_cost_estimate` at `0.005` but re-comment it as *compute + optional proxy, Route C only*; add `citation_route_b_cost_estimate = 0.002` (compute only, no proxy) and `data_axle_add_cost_estimate` (set from the real rate card once O-2 closes; **must default to 0 and block the route while unset**, so no run ever spends against an invented price).
34. **Do not provision a separate browser-worker VPS for citations at this volume** (§7.2). Cap Playwright concurrency on the existing VPS at 4 and rate-limit per directory and per IP (CIT-017). Revisit MT-013 above ~50,000 units/year.

---

## 9. Risks and failure modes

| # | Risk | Evidence it is real | Mitigation |
|---|---|---|---|
| R1 | **The spine is a single vendor.** If Data Axle's price is prohibitive or an agency org is not permitted, Route A collapses to Apple + GBP and the honest number falls to ~30–45 live. | Price and reseller terms both **[UNVERIFIED]** (§3.5) | Close O-2 **before** any build work on `DataAxleSubmitter`. Synup's documented API + white-label reseller is the named fallback spine. |
| R2 | **Teleresearch calls the client.** Data Axle rings the business up to three times in three days to verify. An unbriefed client hangs up, and the Add fails after we have been billed. | Data Axle FAQ, quoted §3.5 | R10: hard consent gate; plus a "you will receive a verification call" line in the client onboarding email, and a 3-day recheck. |
| R3 | **Spec rot outruns maintenance.** 3 of 50 specs already point at acquired or absorbed directories; 8 more point at 404s. | §3.3 | R15's 90-day auto-deactivation + R16 drift detection. Keep the whitelist small enough that 2 re-verifications/year each is affordable (20 specs = 10 h/year). |
| R4 | **The loaded cost is dominated by a number nobody has measured** — actual minutes per queue item. At 10 minutes instead of 5, the loaded cost doubles to ~$1.30/citation. | §7.3 sensitivity | R20 measures it from day one and surfaces the rolling median. If the median exceeds 6 minutes, cut Route C volume, do not absorb the cost. |
| R5 | **A ToS breach on a high-profile platform.** Yelp's terms explicitly cover "AI Technologies" and its `robots.txt` names `ClaudeBot`. A bot submission to Yelp under a client's identity is the client's exposure, not just ours. | §3.7 | `tos_position='prohibits'` is a hard block in the worker, not a UI warning; add a test that a queued batch containing an F row raises. |
| R6 | **Low-value tail actively harms.** Google lists "low-quality directory or bookmark site links" as link spam. | Google spam policies, updated 2026-05-15 | Keep `DEFAULT_MIN_AUTHORITY = 30`; backfill real authority for the 208 unscored rows before the floor can do any work (O-4). |
| R7 | **`authority` is currently fiction for 208 of 226 rows and unsourced for the other 18.** `Apple Business Connect = 99` is `apple.com`'s metric, not the listing page's. | §3.8 | Never render `authority` client-side until O-4 closes. Show `authority_tier` (an editorial build order) instead — it is honest about being editorial. |
| R8 | **Multi-location clients break the model.** One `business_profiles` row per location already exists, but Data Axle bills per Add and Moz/Synup price per location. A 5-branch client is 5× the cost, not 1×. | DATA-2 is already flagged high-risk | Price per *location*, not per client, in every quote; make `business_profiles` count visible on the client record. |
| R9 | **We cannot remove what we built.** For Route B/C directories with no support path, a wrong listing is permanent. | CIT-S9 called "a serious gap" | R27 makes removability a *property of the route*: prefer A (API delete) for anything containing data that might change; never submit to a directory with no removal path unless the client accepts it in writing. |
| R10 | **Reporting a screenshot as a live URL survives the rebuild.** It is one line and it is currently shipping. | `service.py:296-299` | R26 + a regression test. This is the highest-priority single fix in the track. |

---

## 10. Open items

| # | Question | Why it is not settled | **Exactly what would settle it** |
|---|---|---|---|
| **O-1** | **Buy or build?** Moz Local Lite ($19,900/yr for 100 locations, 90+ directories, US/UK/CA) or Synup (~$21,600/yr, 100+ publishers, documented API, white-label reseller) versus self-build at ~$1,655–$2,655/yr loaded. | This is a commercial decision about margin, maintenance burden and what Daniel resells, not an engineering one. | Daniel's answer to: at what per-client-per-month price does he sell citations, and would he rather carry $17–20k/yr of vendor cost or ~250 h/yr of human queue work? |
| **O-2** | **Data Axle Local Listings Premium price per Add and per Renewal**, and whether an agency org may submit for unaffiliated clients. | Not published anywhere reachable; `www.data-axle.com` returns 403 to every client I tried. The `~$30/location` note in the seed is unsourced. | Call **(888) 274-5478** (published on the live Local Listings tool, 8:30–17:30 EST) or email **contentfeedback@data-axle.com**; ask for the rate card for `A` and `R` at ~150 records/year plus the reseller/agency terms. **Blocks R8, R33 and the whole Route A cost line.** |
| **O-3** | **Which publishers Data Axle actually distributes to.** | Data Axle names channel *categories* ("search engines, IYPs, navigation systems, smart speakers, mobile applications, 411 directory services") and no publisher. | Ask for the publisher list in the same call as O-2; **until then, fan-out is measured by discovery and never promised** (§6). |
| **O-4** | **Real authority scores for the 208 unscored catalogue rows.** | `directories.authority` is deliberately NULLable and only 18 rows are filled, with unsourced values. | One Moz Domain Authority or Ahrefs DR pull over the 188 distinct domains, dated, stored with the source name. Until then `min_authority` filters almost nothing. |
| **O-5** | **Bing Places partner eligibility.** The "agency managing more than 10,000 business listings" threshold is secondary and the primary PDF returns HTTP 409. | Two fetch attempts failed. | Email `placesfeedback@microsoft.com` from the Bing Places account address (path given by a Microsoft employee on Microsoft Q&A, 2026-01-16) and ask for the eligibility bar in writing. |
| **O-6** | **Apple Business Connect / Apple Business API eligibility** for an agency with ~100 single-location clients. The create endpoint is live and documented; the onboarding bar is not. | Apple's support guide sections I could reach only say "Apple Business combines Apple Business Manager, Apple Business Essentials and Apple Business Connect"; secondary sources say "work with your Apple representative". | Create an Apple Business account, attempt `Add Service Account` under the API section, and record whether a rep is required. One hour of work. |
| **O-7** | **TransUnion / Neustar Localeze's real price and whether a write API exists.** The "$79/yr, 80+ platforms" figures are search-engine extractions; the site 403s every fetch. | Primary source unreachable from here. | Load `neustarlocaleze.biz/small-business-services/` in a real browser and screenshot the price panel; ask support whether a bulk/API path exists for an agency. |
| **O-8** | **The human minute rate.** Every loaded figure in §7 pivots on $6/hour. | Owner input; not a research question. | Daniel states the fully-burdened hourly cost of whoever works the queue. |
| **O-9** | **ToS position for 214 of 226 directories.** | 12 hand-verified today; most of the long tail 403s a scripted fetch or publishes nothing. | R31's harvest job plus roughly 15 minutes of human review per directory. Prioritise the ~36 rows whose add URL is reachable — those are the only ones that could ever be Route B. |
| **O-10** | **Whether Daniel accepts 45–65 attempted / 35–50 live**, replacing the ~95–110 / ~70–90 figure now in the recovery specification. | The written commitment and the 50×10 acceptance bar were both set against a number this research does not support. | Present §6's arithmetic and the §7 cost table together — the coverage number and the cost number are the same conversation. Q-2 (which ceiling is of record) should be closed in the same sitting. |

---

## 11. Sources

Every URL below was accessed **2026-08-23**. Repo citations are `path:line` at HEAD **`2a502f9`** *(corrected 2026-08-23 — the record originally said `7a14d82`, which is 11 commits behind HEAD; every cited line was re-resolved at `2a502f9`)*.

**Live probes performed 2026-08-23** (curl, browser User-Agent, redirects followed): 50 `FORM_SPECS` URLs; 86 catalogue `signup:` URLs; the six API endpoints tabulated in §3.4. Raw results are reproducible with the commands shown in §3.1 and §3.3.

**Vendor and platform primary sources**

- [Data Axle Local Listings Premium — API docs] https://local-listings-premium.data-axle.com/docs/api — accessed 2026-08-23
- [Data Axle Local Listings Premium — FAQ] https://local-listings-premium.data-axle.com/docs — accessed 2026-08-23
- [Data Axle Local Listings — free tool] https://local-listings.data-axle.com/search — accessed 2026-08-23
- [Data Axle — plans link surfaced by the tool] https://www.data-axle.com/what-we-do/local-listings/#plans — accessed 2026-08-23 (host returns 403 "Site has been Taken Down." to WebFetch and curl)
- [Apple Business Partner API — Create Location] https://business.apple.com/docs/api/v1/location/create — accessed 2026-08-23
- [Apple Business Partner API — Get Location] https://business.apple.com/docs/api/v1/location/get — accessed 2026-08-23
- [Google Business Profile APIs — Basic setup / access request] https://developers.google.com/my-business/content/basic-setup — accessed 2026-08-23 (page last updated 2025-08-28)
- [Google Business Profile APIs — Location data / create + verification] https://developers.google.com/my-business/content/location-data — accessed 2026-08-23 (page last updated 2026-08-17)
- [Google Search — Spam policies] https://developers.google.com/search/docs/essentials/spam-policies — accessed 2026-08-23 (page last updated 2026-05-15)
- [Foursquare — Places API product page] https://foursquare.com/products/places-api/ — accessed 2026-08-23
- [Foursquare — Placemaker Tools overview] https://docs.foursquare.com/data-products/docs/placemaker-tools-overview — accessed 2026-08-23
- [Foursquare — Placemaker best practices] https://docs.foursquare.com/data-products/docs/placemaker-best-practices — accessed 2026-08-23
- [Foursquare — Review a Place (source of the "must get enough confirmations from Placemakers to be applied" wording)] https://docs.foursquare.com/data-products/docs/review-a-place — accessed 2026-08-23 (`docs.foursquare.com` renders client-side; the page text was recovered by search extraction, so treat the exact wording as **corroborated, not directly fetched**. The "contribute suggested edits, removals, merges, flags, and statuses" wording **was** fetched verbatim from the Places API product page.)
- [Foursquare — APIs overview] https://docs.foursquare.com/developer/reference/foursquare-apis-overview — accessed 2026-08-23
- [Microsoft Q&A — Bing Places partner access to API (Microsoft employee answer, 2026-01-16)] https://learn.microsoft.com/en-us/answers/questions/5708537/bing-places-for-business-partner-access-to-api — accessed 2026-08-23
- [Microsoft Q&A — Bing Places API multi-location (answer dated 2026-01-14; thread contains AI-generated answers — **secondary**)] https://learn.microsoft.com/en-us/answers/questions/5708229/bing-places-for-business-api-multi-location — accessed 2026-08-23
- [Bing Places API PDF — **could not retrieve**, HTTP 409 on two attempts] https://bpprodpublicstorage.blob.core.windows.net/bingplacesapi/BingPlaces_API_v1.0.pdf — attempted 2026-08-23
- [Yelp — Terms of Service, effective 2026-01-01] https://terms.yelp.com/tos/en_us/ — accessed 2026-08-23
- [Yelp — Terms of Service, 2020-01-01 version, §7.2(j) and Business Terms §1.4(c)] https://terms.yelp.com/tos/en_us/20200101_en_us/ — accessed 2026-08-23
- [Yelp — robots.txt] https://www.yelp.com/robots.txt — accessed 2026-08-23
- [Trustpilot — Terms of use for consumers] https://corporate.trustpilot.com/legal/for-reviewers/terms-of-use-for-consumers — accessed 2026-08-23
- [Houzz — Terms of Use, §4] https://www.houzz.com/termsOfUse — accessed 2026-08-23
- [Thryv — Terms of Use] https://www.thryv.com/terms-of-use/ — accessed 2026-08-23
- [Hotfrog — robots.txt] https://www.hotfrog.com/robots.txt — accessed 2026-08-23
- [n49 — robots.txt] https://www.n49.com/robots.txt — accessed 2026-08-23
- [Ourbis — robots.txt] https://www.ourbis.ca/robots.txt — accessed 2026-08-23
- [BBB — Terms of Use] https://www.bbb.org/terms-of-use — accessed 2026-08-23
- [Moz Local — pricing] https://moz.com/products/local/pricing — accessed 2026-08-23
- [Synup — pricing] https://www.synup.com/en/pricing — accessed 2026-08-23
- [Synup — Presence / publisher network] https://synup.com/products/presence — accessed 2026-08-23
- [Synup — Listing Management API] https://www.synup.com/en/listing-management-api — accessed 2026-08-23
- [BrightLocal — pricing incl. Citation Builder] https://www.brightlocal.com/pricing/ — accessed 2026-08-23
- [Whitespark — pricing] https://whitespark.ca/pricing — accessed 2026-08-23
- [Whitespark — Local Platform] https://whitespark.ca/local-platform — accessed 2026-08-23
- [Whitespark — 2026 Local Search Ranking Factors, published 2025-11-06] https://whitespark.ca/local-search-ranking-factors/ — accessed 2026-08-23
- [Yext — PowerListings plans ("40+ online services"; no prices shown)] https://www.yext.com/pl/plans.html — accessed 2026-08-23
- [CapMonster Cloud — pricing] https://capmonster.cloud/en/ — accessed 2026-08-23
- [IPRoyal — residential proxy pricing] https://iproyal.com/residential-proxies/ — accessed 2026-08-23
- [Serper — pricing] https://serper.dev/ — accessed 2026-08-23
- [DigitalOcean — Droplet pricing] https://www.digitalocean.com/pricing/droplets — accessed 2026-08-23
- **Secondary, flagged as such:** TransUnion/Neustar Localeze "$79/yr, 80+ platforms" — extracted by a search engine from `https://www.neustarlocaleze.biz/small-business-services/`, which returns HTTP 403 to every direct fetch; Yext SMB tier prices ($199/$449/$499/$999 per location per year) — third-party pricing round-ups only; Bing Places "10,000 listings" eligibility bar — third-party round-ups plus an unretrievable Microsoft PDF.

**Repository sources**

`backend/integrations/citation_bot.py:9-22`, `:15`, `:196-875`, `:276`, `:336`, `:447`, `:651`, `:678`, `:694`, `:819` · `backend/integrations/citation_signup.py:95-121` · `backend/integrations/citation_apis.py:32`, `:49`, `:68`, `:82`, `:99`, `:115` · `backend/integrations/citation_discovery.py:1-36` · `backend/integrations/citation_status.py:1-18` · `backend/integrations/captcha_solver.py:1-16` · `backend/app/modules/citations/service.py:27-38`, `:255-300`, `:296-299` · `backend/app/modules/citations/schemas.py:36`, `:41-42`, `:278` · `backend/app/modules/citations/router.py:471` · `backend/app/modules/citations/tasks.py:1-12` · `backend/app/config.py:627-638`, `:764` · `tools/finish_citation.py:1-20`, `:46` · `db/migrations/0018_offpage.sql:75-92` · `db/migrations/0045_citation_web2_automation.sql:118-168` · `db/migrations/0046_directories_seed.sql:1-40` · `db/migrations/0048_directories_strategy.sql:1-60` · `db/migrations/0065_directories_more.sql` · `db/migrations/0067_directories_more2.sql` · `db/migrations/0064_citation_handoff.sql:11-17` · `frontend/components/offpage/CitationsTab.tsx:104-224`, `:395-396` · `docs/audit/FORENSIC_AUDIT.md:299-320` · `docs/audit/ENGINEERING_MASTER_PLAN.md:36` · `docs/audit/FEATURE_INVENTORY.md:121` · `docs/audit/SALVAGEABILITY_MATRIX.md:46` · `docs/audit/REQUIREMENT_GAP_ANALYSIS.md:32` · `docs/recovery/DANIEL_PROJECT_RECOVERY_SPECIFICATION.md:1105-1200`, `:759`, `:768` · `docs/recovery/REQUIREMENTS_TRACEABILITY.md:268-294`, `:370`, `:471` · `docs/recovery/DECISIONS_LOG.md:86-94`, `:123` · `docs/recovery/OPEN_QUESTIONS.md:50-54` · `docs/implementation/IMPLEMENTATION_LOG.md:171-175` · `docs/implementation/KNOWN_LIMITATIONS.md:19` · git commits `fd8c76a`, `95667a0`, `06a0848`, `20976e3`, `2b73839`, `e4d1792`, `2833673`, `b7195b6`, `7a14d82`


---

## Verification pass — 2026-08-23

An adversarial verifier re-checked this record against the repository at HEAD `2a502f9` and against the live web, with the brief of refuting it. Every correction below is already applied in place above. **Verdict: CORRECTED** — the measurement work is sound and reproduced exactly; the cost model contained one error of unit and one fabricated column, and both have been rebuilt.

### What was checked

- **Every repository claim** — each `file.py:LINE` citation re-resolved at HEAD; `FORM_SPECS` and `SIGNUP_SPECS` re-counted from the AST, not grepped; all three directory-seed migrations re-parsed and the tier splits, the raw/distinct row counts and the distinct-domain count recomputed; the `grep` artefact in §3.1 re-run verbatim; the `celery beat` schedule enumerated; the `citations`/`directories` DDL read in full.
- **Every live probe** — all six API endpoints in §3.4 re-probed independently; **all 50 `FormSpec.url` values** re-probed; **all 86 raw `signup:` URLs** re-probed.
- **Every external factual claim** for a source URL and an accessed date, then sixteen sources fetched directly, well past the six required spot-checks.

### Sources fetched during this pass

Data Axle Local Listings Premium **API docs** and **FAQ** (`local-listings-premium.data-axle.com/docs/api`, `/docs`) and the free tool (`local-listings.data-axle.com/search`) · **Yelp ToS** (`terms.yelp.com/tos/en_us/`) and **`yelp.com/robots.txt`** · **Trustpilot** consumer terms · **Houzz** Terms of Use · **Thryv** Terms of Use · `hotfrog.com/robots.txt`, `n49.com/robots.txt`, `ourbis.ca/robots.txt` · **Google Business Profile** location-data docs · **Apple Business** create-location docs · **Google Search spam policies** · **Foursquare** Places API product page · **Moz Local** pricing · **Synup** pricing · **BrightLocal** pricing · **CapMonster** pricing · **IPRoyal** residential-proxy pricing · **DigitalOcean** droplet pricing · **Whitespark** 2026 Local Search Ranking Factors · **Microsoft Q&A** Bing Places partner-access thread.

### Reproduced exactly — do not re-litigate these

- `FORM_SPECS` = **50** keys, declared `citation_bot.py:196`, closing `:875`; exactly three all-lowercase keys (`n49` `:447`, `192.com` `:651`, `411.ca` `:694`); the §3.1 `grep` returns those three and nothing else; `grep -c "FormSpec("` = 50. `SIGNUP_SPECS` = **1** (`MerchantCircle`).
- Catalogue: **155 + 57 + 29 = 241 raw**, **226 distinct `(name, market)`**, **188 distinct domains**; raw tiers **151 / 51 / 29 / 8 / 2**, table tiers **136 / 51 / 29 / 8 / 2**; `submit_method = 'manual'` appears **17** times; `0046` alone splits **95 / 33 / 17 / 8 / 2**. Ten rows carry `tier in ('aggregator','api')`; six are `aggregator:fed_by_%`.
- §3.3 spec probe: **7 × 2xx, 29 × 403, 8 × 404, 6 × connection failure** — reproduced to the unit. The Cylex USA, Applegate (→ `businessmagnet.co.uk/businessmagnet-acquires-applegate.htm`), Local.com.au (→ `airtasker.com`) and YaSabe redirect chains all reproduce.
- §3.3 signup probe: **36 × 2xx, 42 × 403, 8 × other** — reproduced to the unit.
- §3.4: Foursquare `/v3/places` → `404 Endpoint '/v3/places' not found.`; `/v3/places/search` → `401 Invalid request token.`; `places-api.foursquare.com/places` → `404`; Bing `ssl.bing.com/...` → `301` → `www.bing.com/...` → **`404`**; Apple → `401`; Data Axle `/submissions` → `403 {"result":"error","error":"forbidden"}` and `/nonexistent` → `404` HTML. All seven rows stand.
- Data Axle FAQ/API, verbatim: `X-AUTH-TOKEN`, "Go to your settings page and generate a token"; `POST`/`GET /api/1/submissions`; A/R/U/D; "up to 100 place submissions per request"; required fields (Submission Type, Company Name, Location Phone, Location Address, Location City, Location State, Location Zip Code); "We bill based on the Local Listings Premium detected type for A-Adds and R-Renewals"; "any resubmission of a Record at least twelve (12) months following the last billable submission"; "make up to three calls over three business days"; "A submission goes through multiple stages of verification including automated processing, teleresearch, and manual research"; "The majority of files typically process in a matter of hours… Some files can take up to two weeks"; `D` "only if its out of business"; 5,000 listings per file; `(888) 274-5478`; `contentfeedback@data-axle.com`; `www.data-axle.com` 403.
- Legal: Yelp ToS effective **2026-01-01**, §7.2(j) verbatim; `yelp.com/robots.txt` disallows `/biz_update` (:140), `/possible_biz_owner` (:167), `/writeareview/` (:195), blocks `ClaudeBot`, **and closes with `User-Agent: * / Disallow: /`**. Trustpilot's "you" definition and Houzz §4 verbatim. Thryv's scrape clause and its "any of our websites on which these terms appear" scoping, naming no property. Hotfrog, n49 and Ourbis `robots.txt` exactly as described — including that n49 does **not** disallow `/add-business/`.
- APIs: GBP `POST https://mybusinessbusinessinformation.googleapis.com/v1/accounts/{accountId}/locations` and "Locations can be used in Ads, but they need to be verified to be eligible to appear on Search and Maps" (page updated **2026-08-17**). Apple `POST {url}/api/{version}/orgs/{orgId}/locations`, bearer token, `locationDetails{partnersLocationId, brandId, displayNames, mainAddress}`, created state **`SUBMITTED`**.
- Prices: Moz Local **$199 / $299 / $399** per location per year, "90+ Listing directories", "supports the purchased management of US, UK, and Canadian business listings", "Enterprise Custom For 50+ locations", and the Moz API confirmed as the link index ("over 44 trillion links"). Synup **$49 / $299 / $499 / $899**, "Annual save 20%". BrightLocal "Starting at $2 USD / citation", "$3.20 per site, or as low as $2 with bulk credits", Managed SEO "$1,299 USD / mo", API "Custom price". CapMonster **$0.60 / $1.30 / $0.30** per 1,000. DigitalOcean 4 vCPU / 8 GiB = **$48.00/month**. Foursquare "Test select Pro API endpoints at no charge for up to 10,000 calls", no per-call price published. Google spam policies list "Low-quality directory or bookmark site links" (page updated **2026-05-15**). Microsoft Q&A answer is by **IoTGirl, Microsoft Employee, 2026-01-16**, giving `placesfeedback@microsoft.com` **and naming no eligibility threshold** — which is exactly how this record already reported it.
- Arithmetic that stands: §6's route table and its 43–63 / 33–49 totals; §7.2's $0.109/unit, 22 machine-hours/year and 0.25% duty; every §7.3 line item; the $3/h and $12/h sensitivities (45.7¢ / 102.8¢); the loaded figures at $10 and $30 per Add (64.8¢ / 113.5¢).

### Corrections made

**Cost model — the material ones**

1. **§7.1, Route A marginal was off by 100×.** "$5/$10/$30 per Add: 1.7¢ / 3.3¢ / 10.0¢" is the right division with the wrong unit — $5 ÷ 3 = **$1.67**, not 1.7¢. Corrected to **$1.67 / $3.33 / $10.00 per unit**, with the consequence stated: Route A meets a 10¢ marginal line only at an Add price ≤ $0.30.
2. **§7.3, the entire "Marginal (Routes A+B only)" column (3.4¢ / 3.5¢ / 3.7¢) was not derivable and was internally incoherent** — its own step sizes imply denominators of 500,000 and then 1,000,000 units. Rebuilt from the record's stated volumes to **29.6¢ / 59.1¢ / 176.7¢**.
3. **§7.3, "loaded @ $5 Add = 40.4¢" was wrong** — 40.4¢ is $1,655 ÷ 4,100, i.e. the total with the $5 Add priced at zero. Corrected to **52.6¢**. (@ $10 and @ $30 were already correct.)
4. **§7.3's verdict against D-2 was overreaching.** "The ≤10¢ marginal target holds comfortably for Routes A and B" survives only for **Route B**. Restated, with the loaded range corrected from 40–65¢ to **53–65¢** and §1(f) from 39–64¢ likewise. No engineering requirement changed — R33 already blocks Route A while the price is unset — but what may be said to the client did.
5. **§7.3's "Route C volume is the lever" claim was wrong.** Halving Route C halves numerator and denominator together; Route C's loaded cost per live unit ($0.648) is indistinguishable from the blended figure, so per-citation cost stays ~64¢ while total spend falls ~30%. The claimed "~35¢" is not reproducible. The real levers — minutes per item and the Data Axle price — are now named.
6. **§7.2's "~10% duty" at 50,000 units/year** contradicts the 240-sessions/hour figure in the preceding sentence; corrected to **~2.4%**. The ~1¢/unit conclusion is unaffected.
7. **§7 input table, IPRoyal mislabelled.** $5.25/GB is the **pay-as-you-go** 10 GB rate, not the subscription rate (that is $5.51/GB). The $0.00513/MB derivation and everything downstream are unchanged.
8. **§7.1's Route C CAPTCHA-solve line flagged as a standing-constraint conflict.** Paying a solver on a Route C directory is the CAPTCHA evasion §3.3 and §4.1 say has been dropped, and `config.py:627` already ships a live solver default. The §4.1 reading is now stated as binding: the human clears the CAPTCHA and that component is $0 unless reinstated as an explicit owner decision.
9. **§7.3 Route C bot-prep rate** is $0.0167 in the table and $0.018 by §7.1's own components; noted inline (a $4/year difference, not carried through).

**Repository citations**

10. **HEAD is `2a502f9`, not `7a14d82`** (§3.1 and §11) — `7a14d82` is eleven commits behind. Every cited line was re-resolved at `2a502f9`; `tools/finish_citation.py` is the only cited file that changed in that window and its `:46` shared-password claim still holds verbatim.
11. **§3.9 said "there is no Celery beat entry for citations". False** — `sweep-offpage-monitors` runs weekly and already fans `run_citation_monitor` out per active client. Corrected to the true and narrower claim (no per-listing liveness re-check, no `next_recheck_at`, no `submitted` → `live` promotion), which strengthens R25.
12. **§3.9's heading said "Three defects" over a list of four.** Corrected.
13. **§3.3's "86 catalogue rows"** is a raw-INSERT count, not a table count — the exact conflation §3.2 convicts the prior audits of. The table holds **71** such rows with **69** distinct URLs. The probe and its percentages are unaffected; the wording now says so.
14. Line-reference fixes: OSM seed note `0046:31` → **`:34`** (`:31` is Apple Business Connect); Foursquare `POST /places` construction `citation_apis.py:107` → **`:115`** (`:107` is a body field); Bing path construction `:70` → **`:68`**; `automatable_directories()` `service.py:26-38` → **`:27-38`**; `SIGNUP_SPECS` `citation_signup.py:95-118` → **`:95-121`**; `0064_citation_handoff.sql:11-18` → **`:11-17`** (the file is 17 lines); recovery-spec `:1157` → **`:1156`** (the "~95–110 / ~70–90" text; `:1157` is the next item) and `:1166` → **`:1167`** (the "0.4–0.8¢" row; `:1166` is the table rule).

**External claims**

15. **Whitespark citation weight 7% → ~6%**, and the five accompanying group weights downgraded to **[UNVERIFIED]** — the report's weighting chart is a graphic, not text, and secondary summaries disagree with each other. The three verbatim quotes in §3.10 are confirmed and were **not** weakened. The section's conclusion is untouched.
16. **Trustpilot's clause was quoted with its last five words missing** — "…or specifically approved by us". Restored, and the separate text/data-mining ban added, since an approval path materially affects the Route F position.
17. **Serper's "$0.0005 at Scale" → [UNVERIFIED]** — `serper.dev/pricing` 404s and the root page carries no pricing table. The $50 / 50,000 = $0.001 entry rate used by the model is corroborated and matches `config.py:764`; it was **not** hedged.
18. **The Data Axle fan-out quote is secondary, not primary** — it lives on the 403-ing `www.data-axle.com` page and is neither in the API docs nor the FAQ, both of which were fetched in full. Relabelled to match how this record already labels the Neustar and Yext figures.
19. **§3.4's Apple 401 body** varies with what is sent (an unauthenticated probe returns "Missing Authorization header"); noted, since the load-bearing fact is the 401, not the message.

### What remains [UNVERIFIED], and why

| Claim | Why it could not be settled here |
|---|---|
| **Data Axle price per Add and per Renewal** (O-2) | Published nowhere reachable; `www.data-axle.com` 403s to every client. Independently confirmed as unpublished — it is not in the API docs or the FAQ. This is the single largest hole in the record: it sets Route A's marginal cost, which corrections 1–4 show is otherwise unbounded. **A phone call, not more research.** |
| **Data Axle's publisher list** (O-3) | Confirmed unpublished; the only description is the secondary channel-category sentence. Fan-out stays measured, never promised. |
| **Whether an agency org may submit for unaffiliated clients** | Not addressed in any Data Axle document fetched. Blocks the whole Route A design, not just its price. |
| **Yext SMB per-location prices** | `yext.com/pl/plans.html` shows no prices; the $199/$449/$499/$999 figures remain third-party round-ups. Correctly already marked. |
| **TransUnion / Neustar Localeze $79/yr, "80+ platforms"** | Site 403s every direct fetch; still a search-engine extraction. Note that `0046_directories_seed.sql:29` independently seeds "~$79/yr for 1-24 locations" — but that seed is itself unsourced, so it corroborates nothing. |
| **Bing Places "10,000 listings" eligibility bar** | The Microsoft employee answer was fetched and **names no threshold**; the figure survives only in third-party round-ups and an unretrievable Microsoft PDF. Correctly already marked. |
| **Serper bulk/Scale per-query rate** | No primary pricing page exists at the cited URL. |
| **Whitespark's five non-citation group weights** | Chart is a graphic; secondary summaries conflict. |
| **`directories.authority` for all 226 rows** (O-4) | Unchanged — the 18 seeded values remain unsourced and the record is already right to forbid quoting them. |
| **The human minute rate ($6/h)** (O-8) | Owner input, not a research question. Every loaded figure pivots on it, and corrections 4–5 make that pivot sharper, not softer. |
| **`tos_position` for 214 of 226 directories** (O-9) | Unchanged. The twelve hand-verified positions were re-fetched and all twelve hold. |

### Standing constraints

**L3 ceiling:** respected — §1(d) and the §5 rejection of a raised ceiling are consistent, and no requirement in §8 automates a submission past a human gate. **No CAPTCHA evasion:** *one violation found and flagged* — the §7.1 Route C solver line (correction 8); everything else in the record, including §4.1's rule and §3.3's treatment of a 403, is correct. **No Kubernetes:** none proposed; §7.2 and R34 argue the other way. **No invented data:** the record's own discipline is good — but corrections 2, 3 and 5 were exactly this failure inside the cost model, which is why the marginal column, the $5 loaded figure and the "~35¢" lever have been rebuilt or removed rather than hedged.
