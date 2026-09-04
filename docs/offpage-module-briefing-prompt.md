# Off-page module briefing — message + prompt for ChatGPT

---

## PART 1 — The message to send first

> I'm going to paste a full technical briefing of the off-page module of our SEO platform (AIOS). It covers three sub-systems: **citation audit** (discovering a business's existing directory listings), **citation building** (actually creating new listings), and **Web 2.0** (branded authority articles carrying one editorial backlink each).
>
> This is a real production system, not a design doc — everything in it is the logic as implemented today, including the parts that are deliberately switched off and why. Read it fully, then explain the module back to me: how each pipeline flows end to end, what decides each branch, which guards exist and what they're defending against, and where the real constraints are. Don't substitute generic SEO advice for what's written. Ask me about anything ambiguous rather than guessing.

---

## PART 2 — The prompt (paste everything below this line)

You are being briefed on the OFF-PAGE MODULE of AIOS, a production SEO platform (Python/FastAPI + Celery workers + Postgres with RLS, Next.js frontend, plus a Chrome MV3 extension). Read everything, then be ready to explain the module and answer detailed questions about its logic. Treat every statement as current implemented behaviour unless it is explicitly marked as switched off or not built.

### 0. THE GOVERNING PRINCIPLE

The module was rebuilt to remove one class of defect: **asserting a fact that nothing established**. Concretely: a screenshot path was once rendered to operators as "live listings earned"; a POST returning 200 was treated as a listing existing; 45 refused rows read as 45 built listings. Almost every decision below exists to make a claim traceable to evidence, and to make a shorter-than-promised result *visibly* different from a silent failure.

Three fields are kept strictly apart and may never be derived from each other:
- `proof_url` — a screenshot key. Evidence a *submission happened*.
- `live_url` — the public URL of a listing. Evidence a *listing exists*.
- `external_ref` — the directory-side record id.

### 1. DATA MODEL

- **`public.citations`** — ONE row per (client × directory) carrying BOTH facts: the monitoring fact (`nap_status`: consistent | inconsistent | missing) and the submission fact (`submit_status`: not_started | queued | submitting | submitted | verified | failed | blocked | ready_for_human | live | drifted | delisted). One row, one story — deliberately not two tables that can disagree.
- **`public.directories`** — the citation-directory CATALOG (~226 rows, 4 markets + a GLOBAL/aggregator layer):
  - `tier`: aggregator | api | bot_fillable | captcha_assisted | manual_only
  - `submit_method`: `api:data_axle`, `api:apple_business`, `bot:…`, `bot:signup…`, `aggregator:fed_by_data_axle_foursquare`, `manual`, `closed`
  - `authority` (DA) + `authority_tier` (core | tier1 | tier2)
  - `verticals[]` (empty = general, serves everyone), `is_marketplace`, `market`
  - `route`: A (aggregator/API) | B (verified open form) | C (human queue) | F (never attempt). DERIVED, never hand-set.
  - `tos_position` / `tos_clause` / `tos_source_url` — the EVIDENCE behind `route`.
- **`public.directory_specs`** — the EARNED bot whitelist (§3).
- **`public.citation_accounts`** — a directory login as an entity; the secret lives in the vault, and the vault coordinates are set BY THE DATABASE from the row's own id, never accepted from a writer.
- **`public.citation_campaigns`** — a campaign is a first-class thing with a persisted skip ledger.
- **`public.web2_properties`** — the Web 2.0 placement ledger.
- **`public.web2_accounts`** — a Web 2.0 account as an entity (ownership per_client | house, health, property caps).
- **`public.web2_platforms`** — ~90 catalogue rows joined to a 54-value platform enum via an explicit `platform_enum` column (name-string matching silently failed for instance-level rows like "Mastodon (mastodon.social)").

`route` and `tos_position` are deliberately separate. Google Business Profile and Apple are `tos_position = 'prohibits'` as BOT targets while being perfectly legitimate over their own authenticated APIs — those rows are route 'A' and must stay reachable. Blocking on `route` and not on `tos_position` is what keeps both true.

---

### 2. SUB-SYSTEM ONE — CITATION AUDIT (discovery)

**Question it answers:** which directories ALREADY list this business, and is the NAP consistent — versus which are missing.

**Entry:** `POST /citation-builder/clients/{id}/audit` (lead-only).

1. Resolve the client (RLS-visible) — unknown → 404.
2. Require a NAP. If no submission `business_profile` exists, DERIVE one from the client's own `client_business_profiles` record (name, address, city, region, postal, phone, website, categories with the primary first, hours). No NAP → 400.
   **An unset market defaults to GLOBAL, not US.** Measured with a Lahore business: a US default selected 138 US+GLOBAL directories and queued an operator to submit a Pakistani business to YellowPages.com, Chamber of Commerce and BBB. A WRONG listing is worse than a missing one — NAP pollution is the exact harm a citation campaign prevents.
3. State the money-dial AT CLICK TIME. The `citation_discovery` dial: `off` → 409 refuse outright (enqueueing work the gate will certainly skip manufactures a dead run); `byhand` → still enqueue, because the honest blocked run is a valuable trail, but the response SAYS the sweep will not run and names the fix; `api` → runs.
4. Enqueue the `offpage.monitor` job and return its `jobRunId` so the caller has something to poll. (It used to return a bare `{"status":"queued"}` — an audit that never ran looked identical to one still working.)

**The worker (`run_citation_monitor`):** cost-gate → `provider.fetch_citations(business)` → `diff_citations` vs the stored ledger (NEW = a directory not yet stored; CHANGED = a stored directory whose `nap_status` now differs) → insert/update. Discovered names are resolved to CATALOG IDS via a canonical-normalised lookup before writing — a row written with a name alone matched nothing later, and the client was told to build a listing they already had. Never raises.

**The discovery provider is NOT BrightLocal.** The client cannot obtain a BrightLocal key, so in production the audit found 0 listings and treated all ~155 catalog rows as missing. `SearchCitationProvider` satisfies the identical Protocol and runs on keys the platform already holds:

1. **Places anchor** — Google Places (or Serper `/places`) → the CANONICAL NAP every other listing's consistency is judged against, plus the GBP listing itself emitted as the anchor citation.
2. **Serper web search** — exact name + city; the phone number; the name scoped to known directory domains. Result domains map to directory names via a curated table; search engines, Wikipedia, Reddit, Amazon, Indeed etc. are skipped as never-citations.
3. **Foursquare** — a direct Places read.
4. **Firecrawl (optional)** — render the top few found listings for their exact on-page NAP before judging.
5. **Claude, strict JSON** — drop false positives (a listing that is not this business), assign each a directory name, judge NAP consistency vs the canonical NAP. A deterministic heuristic classifier takes over if Claude is absent or fails.

Every sub-call is caught: that source is skipped and discovery returns whatever it found. No secret is ever logged.

**Reading the audit — `GET /citation-builder/gap-analysis?clientId=`.** The coverage vocabulary is precise and load-bearing:

- **DONE** (covers the directory): `submitted`, `verified`, `live`, `drifted`. `drifted` counts as done because the listing EXISTS — its NAP has merely gone stale, so the fix is a correction, not a fresh build. `delisted` does NOT: the listing is gone and that directory is an open gap again.
- **IN-FLIGHT**: `queued`, `submitting`. These DEDUPE (a campaign must not double-queue them) but are NOT coverage — nothing has been delivered. If `updated_at` is older than **15 minutes** the row is reported as **STUCK by name** — the exact signature of a dispatch nobody is consuming. Before this split, 45 refused rows rendered as 45 built listings.
- **OPEN GAP**: `failed`, `blocked`, `delisted`, never-started.
- A monitoring row that FOUND a listing (`nap_status` consistent or inconsistent) also covers its directory.
- `live_urls` is populated ONLY from rows at `live` WITH a `live_url`. Never from `proof_url`.

**The ordering rule that makes the number correct:** coverage is SUBTRACTED FIRST, and the cap is applied AFTER. It used to run the other way (cap to 45, then remove covered rows from that 45), so `missing` depended on whether a client's existing listings happened to fall inside the top 45 of the catalog — producing 41 on one run and 45 on the next with `covered_count` reading 4 both times.

**Audit plan — `GET /citation-builder/clients/{id}/audit-plan`:** the same selection and gap logic, uncapped, bucketed and prioritised **Generic (GLOBAL) → Country (the client's own market) → Niche (vertical-specific)**, each directory tagged `built | missing | in_flight | stuck`. Bucketing: a directory naming verticals is NICHE; else a GLOBAL one is GENERIC; else COUNTRY. It never re-ranks — it reuses the campaign's own ordering.

---

### 3. SUB-SYSTEM TWO — CITATION BUILDING (submission)

**Entry:** `POST /citation-builder/campaigns` (lead-only). Nothing submits synchronously.

**Selection (pure — no DB, no network, fully unit-testable):**

1. `automatable_directories` removes, once, for every caller:
   - `manual_only` tier rows;
   - `aggregator:fed_by_*` rows (nothing to submit — the listing arrives by seeding the upstream aggregator);
   - `route = 'F'` rows (terms forbid automated ACCESS — a form-filling bot must GET the form before it can fill it, so the clause binds; "we only submitted, we didn't scrape" is not a reading that survives).
2. `select_campaign_directories`:
   - vertical match (no verticals = general = applies to all; with NO resolved vertical only general rows are kept — never blast a niche directory at an unknown industry);
   - marketplace gate (lead-gen marketplaces compete for the client's own keywords — opt-in only);
   - authority floor, default **DA 30** (the sub-DA30 spam tail adds risk more than rank; an UNSCORED row with NULL authority is kept, not dropped, and sorts just below scored rows in its tier);
   - sort: `authority_tier` rank (core → tier1 → tier2), then DA descending, then name;
   - cap, default **45** (~40–50 clean citations beat 100+ scattergun).
3. **Every exclusion is COUNTED and written to a `skipped` ledger with a reason and detail.** Reasons: `prohibited_by_terms` (reported WITH the clause text and source URL), `fed_by_aggregator`, `not_automatable`, `off_vertical`, `marketplace_not_opted_in`, `below_authority_floor`, `over_campaign_cap`. This is a required output, not a nicety: without it a shorter list is indistinguishable from a system that quietly failed, and "so what happened to Yelp?" has no answer.
4. If the operator ticked specific `directory_ids` (audit-first "build only these"), the strategy filters and cap are bypassed — an explicit choice is not second-guessed.

**Dispatch:** the campaign row is created BEFORE the fan-out, so every queued row carries its `campaign_id`, the job ledger groups on it, and a mid-loop crash leaves an inspectable record instead of orphans. A directory whose previous attempt ended blocked/failed is RE-QUEUED IN PLACE, never silently skipped — a past cost-gate hold must not permanently fence a directory off. Idempotency key = row × campaign.

**THE WORKER'S GUARD ORDER IS THE WHOLE DESIGN** (`execute_citation_submit` — never raises, because with `task_acks_late` a raised exception redelivers the job and re-runs a PAID stage = double spend):

1. Load the joined citation + directory + business_profile row. Terminal or non-queued status → clean idempotent no-op.
2. **No business name** → `blocked` / `no_nap`. There is no NAP to submit; dispatching anyway sends an empty listing the directory rejects, and the row returns `failed` as if the ENGINE broke when in truth we had no data.
3. **`route = 'F'`** → `blocked` / `tos_prohibits`, with the clause URL. Runs BEFORE the cost gate because a prohibited submission must not even be priced. A hard block in the worker, never a warning in the UI — a submission made under a client's identity against a platform's terms is the CLIENT's exposure.
4. **Price guard** — `api:data_axle` while `data_axle_submits_enabled` is false → `blocked` / `price_unknown`. Keyed on the METHOD, not the tier: the `api`/`aggregator` bucket also holds Apple and GBP, which are FREE per submission, so a tier-keyed guard blocked them quoting a rate card for a different vendor.
5. **Engine resolution** (`submitter_for` — pure dispatch, never raises):
   - `aggregator:fed_by_*` → None, "no action needed — covered by seeding the core aggregator(s)"
   - `api:<key>` → the configured API submitter, else an honest "no API submitter configured for `<key>`"
   - `bot:signup*` → the account-creation engine (matched BEFORE the generic `bot:` prefix so a signup directory never falls through to the no-signup engine)
   - `aggregator:` / `bot:` → the Playwright bot
   - `manual` → "manual submission only — queued for an operator"; `closed` → "directory is closed to new submissions" (these are DECISIONS, not gaps, and they read differently to an operator)
   No engine → `disposition_for_block` decides where the row goes.
6. **`can_submit(job)`** — does an EARNED spec exist? No → `ready_for_human` / `no_verified_spec`.
7. **Cost gate** (`citations` dial) → `blocked` / `spend_blocked`.
8. `submitting` → `submitter.submit(job)` → commit the metered cost → write `submit_status`, `proof_url`, `external_ref`, `error`, and the per-row `cost`.

**Steps 5 and 6 run BEFORE the cost gate, and that ordering is the point.** They used to run after: the gate charged, the row moved to `submitting`, and only then did the worker discover there was no engine — so a client was billed for a submission that could not physically happen. That was survivable while the bot fell back to a 50-entry in-code catalogue; it stopped being survivable once the whitelist started empty and "no engine" became the common case.

**`blocked` vs `ready_for_human` is the product, not a synonym:**
- `blocked` = NOBODY should act.
- `ready_for_human` = a machine cannot, but a person can, in their own browser, in their own session.

Human-workable reasons: `no_engine`, `no_verified_spec`, `captcha`, `waf_403`, `account_gated`. NOT human-workable: `tos_prohibits` (a human retrieving the form is the same prohibited act), `fed_by_aggregator` (nothing to submit), `no_nap` (fix the data, not the row), `price_unknown` (a spend decision for a lead). An unknown reason falls to `blocked` deliberately — a new failure mode must not silently start generating human work whose value nobody has assessed, and a queue full of items an operator cannot complete destroys trust in the queue itself.

**Nothing in the submit path ever writes `nap_status = consistent` or returns `verified`.** Data Axle runs teleresearch for up to three business days; Apple returns state SUBMITTED; GBP needs verification before appearing at all; a form bot only ever knows that a page changed. None of those is a listing.

#### The engines

**Route A — direct API.** Verified by unauthenticated probe on 2026-08-23 (a 401/403 means the endpoint EXISTS and wants credentials — that is the whole difference from a 404):
- **Data Axle** Local Listings Premium → 403. Built, but **price-gated OFF**: its per-Add price is published nowhere reachable, and at the modelled $5/$10/$30 the per-unit cost is 17×–100× the 10c commitment. `data_axle_add_cost_estimate` defaults to 0.0 and BLOCKS the route rather than pricing it as free. A key without a price is a way to spend money by accident.
- **Apple Business Connect** → 401. Built; needs keys.
- **Google Business Profile** → documented and allowlisted, but **NO ENGINE IS WRITTEN**. A GBP row blocks with "no API submitter configured for 'gbp'". Credentials alone do NOT open that route — stated explicitly because the catalogue row, the `api` tier and the config key all exist and make it look wired.
- **Bing Places and Foursquare** write submitters were **DELETED**: their coded endpoints 404 (a Foursquare READ endpoint returning 401 was the control, so these are missing routes, not auth failures). Foursquare routes additions to a community-moderated Placemaker queue; Bing Places API is a partner programme. FOURSQUARE_API_KEY remains live for citation DISCOVERY (a read path).

**Route B — the Playwright bot.** A `FormSpec` is DATA: url + CSS selectors mapped to NAP fields + submit button + success indicator (+ optional CAPTCHA widget). Adding a directory is one spec entry, never new Python.
- The bot drives **ONLY** rows in `public.directory_specs`. The 50-entry `FORM_SPECS` dict in code is an **IMPORT SEED, NOT A WHITELIST** — it was a coverage CLAIM, and measured, 29 of its 50 URLs return 403, 8 return 404, 6 hosts are dead, 7 answer, and none ever produced a proven listing. With no spec source configured the bot submits NOTHING (fail-closed) rather than falling back to it.
- Anti-detection, measured against a fingerprint harness rather than assumed: stealth launch args, a randomised UA / viewport / locale+timezone per run, masks for `navigator.webdriver`, `plugins`, `languages`, `mimeTypes` and the WebGL UNMASKED_VENDOR/RENDERER pair (raw headless reports "SwiftShader", which no consumer machine reports and which identifies the session as a datacentre bot on its own), human-cadence typing and pauses, an optional residential proxy. Explicitly NOT a silver bullet: TLS fingerprint, IP reputation and behavioural scoring are decided off-page — a clean fingerprint is necessary, not sufficient.
- The proxy is SUPPRESSED on route B: a route B directory is by definition undefended, so one that starts answering 403 has BECOME route C — a route change to record, not bandwidth to buy.
- A drifted selector fails CLEANLY (`failed`, with whatever screenshot could be captured attached), never a silent false "submitted".

**The signup engine.** Most real directories require an account before you can submit. A `SignupSpec` describes the signup URL + name/email/password selectors + submit + a verification kind (click a link, or type a code) + the post-verify add-business step, which REUSES the existing `FormSpec`. It subclasses the bot so it inherits all the anti-detection unchanged. Flow: open signup → fill a generated unique alias email on the shared catch-all IMAP mailbox + a generated strong password → submit → poll the mailbox → extract link/code → verify → run the add-business FormSpec. The password is SEALED into `citation_accounts` — it used to be generated, typed into the form, and never stored, so every account the bot ever created had an irrecoverable login and the only remaining move was to abandon it and create a duplicate, which is the exact problem a citation campaign exists to prevent.

#### How a directory earns the automated route (the spec lifecycle)

1. `POST /specs` — a new spec revision, always INACTIVE. `spec` is **IMMUTABLE after insert** (a revision is a NEW ROW). Reason: the obvious guard "editing selectors voids the verification" is defeated by deactivate → edit → reactivate. The spec's URL host must BE the catalogue row's host or a subdomain of it, enforced by a trigger — that URL is a browser navigation target, so `https://169.254.169.254/latest/meta-data/` would otherwise turn an authenticated headless browser inside our own network into a screenshot-returning request forgery.
2. `POST /specs/{id}/verify` — WRITE-ONCE. A dated human diff of every selector against the live DOM, with evidence. A stale verification cannot be quietly refreshed, because the date is the whole value.
3. `POST /specs/{id}/first-live` — WRITE-ONCE. The first PUBLIC listing URL this exact spec produced. CHECKED, not asserted: the server fetches it.
4. `POST /specs/{id}/activate` — a CHECK constraint (`active_is_earned`) enforces both halves, and activation SETS `directories.route = 'B'` in the same transaction. Gating the loader on `route = 'B'` while nothing could ever set route B produced a whitelist that could never have a member. **The activation IS the evidence.** Route B therefore starts at ZERO and grows one dated verification at a time.

Every invariant is a CHECK or a trigger, NOT Python — the Celery worker connects as `service_role`, which is BYPASSRLS, so RLS policies gate the HTTP surface only, while CHECKs and triggers bind the operator and the worker equally.

#### Route C — the human queue (the most valuable part today)

Route C is roughly 200 of the 226 catalogue rows and, measured, **56% of the loaded cost per live citation**. The two levers on that cost are the aggregator per-Add price and MINUTES PER ITEM — and minutes per item cannot be improved without first being measured. It replaced a desktop script that exported every directory login to a JSON file and printed "Password for all: …" — one password covering every account, credentials outside the platform, and no record of who worked what.

- The claim lives on the `citations` row itself, not in a second queue table: a second ledger keyed to the same listing is a second thing that can disagree about what happened to it.
- `ready_for_human` is not a new status — a row is IN the queue when its status says so. Adding a `queued_for_human` beside it would be a synonym, and synonyms are how a state machine stops being checkable.
- Columns: `claimed_by`, `claimed_at`, `claim_expires_at`, `human_attempts` (a rising count is what moves a row from "we keep trying" to "stop offering this one"), `worked_seconds` (ACCUMULATED across claims — the number the whole loaded-cost model rests on, previously never measured), `operator_note`.
- Endpoints: board (including the operator's own in-hand items, served from the server so a reload does not lose them and re-bump `human_attempts`), claim (**a 20-minute LEASE, not a lock** — a closed laptop must not strand an item), heartbeat (extends the lease and banks time, so a crash costs one heartbeat of measurement, not the session), release, complete, blocked.
- **COMPLETION IS CHECKED, NOT ASSERTED.** The operator supplies the live URL; the server runs the same liveness probe and looks for the business name plus phone or address. Not found → the completion is REFUSED and the item stays claimed, so the operator finds out while the tab is still open rather than at a re-check three days later when the context is gone. That refusal is a normal response, not an error — the commonest cause is a directory that has queued the submission for moderation, in which case "not live yet" is the honest answer and the operator should release the item.
- `blocked` takes a CLOSED reason vocabulary (captcha_wall, account_required, paid_only, form_changed, duplicate_listing, directory_dead, phone_verification, postcard_verification, other) so the board can answer "which directories are wasting our time?" — which is what eventually removes a row from the offer list.
- **The Chrome extension** ("AIOS Citation Assistant", MV3, side panel) fills the form from the canonical profile using the ACTIVE spec's selectors, in the operator's own browser, signed into their own account; the human reviews and presses submit; the extension records what happened. It is the posture of a password manager's autofill, **NOT a crawler** — a measured decision, since 29/50 catalogue form URLs 403 a scripted client and Yelp/Trustpilot/Houzz ban automated access outright. Its token reaches the citation queue and NOTHING else (the scope vocabulary is closed **in the database** by a CHECK constraint, so no scope exists that reaches the vault, the client roster or the cost dials even if a future route forgets to ask), is not a JWT so the dashboard's auth rejects it everywhere else by construction, and expires in 12 hours. Deliberately never published to the Chrome Web Store.

#### Liveness — the only thing permitted to write `live`

A pure decision function over an already-fetched page (no network, no DB, no clock), so every branch unit-tests without a fixture server:

- host did not answer → `submitted` (hold). An unreachable host is OUR failure to LOOK, not evidence the listing is gone. Delisting because our DNS blipped is a fabrication in the opposite direction — and the more dangerous one, because it invents work to redo.
- 4xx/5xx → `delisted`. The directory answered and said there is nothing there.
- 2xx but the business NAME is absent → `delisted`. The soft-404 case, and the common one: a removed listing usually 301s to the directory's homepage, which returns a healthy 200.
- 2xx, name present, but neither phone nor address matches → `drifted`. The listing EXISTS (so it still covers that directory) but what it says is wrong — the fix is a correction.
- 2xx, name present, AND phone or address matches → `live`.

Requiring name AND one of phone/address is deliberate: a name alone is met by any page that merely mentions the business; a phone alone is met by a directory listing a completely different branch. The verdict's evidence (`http_status`, `final_url`, `matched_fields`, `checked_from`) is stored verbatim so "why is this live?" stays answerable a year later.

Re-check cadence per row: **+3d, +14d, +60d** (a submission is most likely to become live — or be rejected — in its first fortnight, which is exactly when a client asks), then **30d** for route A / `core` rows and **90d** for everything else. A failed LOOK does not consume a rung of the ladder: it retries in 1 day and the row's status is left exactly as it was, so a network blip cannot push the next real check three months out or silently downgrade a confirmed `live` row.

The sweep is SSRF-guarded (`is_public_url` before every fetch), identifies itself honestly in its User-Agent, is unauthenticated on purpose (a listing that only renders for a logged-in session is not publicly visible, and public visibility is the entire point of a citation), and never raises — one unreachable directory must not cost the other 199 their re-check.

#### NAP corrections

When the canonical record moves, only the fields a LISTING ASSERTS count: business_name, address_line1/2, city, region, postal_code, phone, website_url. Editing a description or a logo flags nothing — flagging on every field trains operators to ignore the flag, which is the same as not having one. Only rows at `live` or `drifted` are flagged for correction: a `submitted` row may have nothing out there to correct, and if a listing does appear it will be checked against the NEW canonical NAP anyway.

#### Costs (the `citations` money-dial)

bot_fillable 0.005 · captcha_assisted 0.006 · route B 0.002 (compute only — no proxy, no solve) · Apple/GBP 0.0 (priced at zero because it IS zero, not because the price is unknown) · Data Axle 0.0 but BLOCKED. The per-row cost is written back onto the citation row, mirroring the cost log.

---

### 4. SUB-SYSTEM THREE — WEB 2.0

**Definition, enforced in code:** an on-topic, branded authority article posted to a client-owned or house blog, carrying **exactly ONE** editorial backlink to the client's page. White-hat authority work, never link spam — which is exactly why it is **NEVER** auto-published: a lead must APPROVE it at the `needs_review` gate.

**Pipeline:** `plan → write → HUMAN REVIEW GATE → publish → verify (live + link) → track`. The core stages are pure of Celery, DB and network (injected seams), so the whole flow runs with deterministic fakes and zero keys.

**Platform catalogue:** 50+ real publisher adapters — WordPress.com, Blogger, Tumblr, dev.to, Write.as, Telegra.ph, Mataroa, Ghost, Mastodon, GitHub/GitLab Pages, Micro.blog, Hashnode, Hatena, LiveJournal, Dreamwidth, Webflow, HubSpot, Drupal, Joomla, HackMD, Gists, Snippets, Paste.ee, Pastebin, Netlify, Neocities, Rentry, dpaste, Misskey, Lemmy, Bluesky, WhiteWind, Disqus, Plurk, Pixelfed, Notion, Gravatar, Minds, Zenodo, Internet Archive, OSF, Figshare, Codeberg Pages, Livedoor, FC2, Seesaa, Warpcast, SourceHut Pages, Sanity, Storyblok, Hygraph, WriteFreely. **Medium is DRAFT-ONLY** — its publish API was retired, so a Medium placement is prepared as a draft for a human and the pipeline never claims it is live. Some (Disqus, Gravatar) are honestly labelled THIN PROFILE placements, not articles. Hive/Steemit (custody-sensitive private keys), Gab (brand risk), Evernote, Issuu and Nostr were investigated and deliberately NOT built, with reasons recorded.

#### Eligibility — the distinction the module exists to hold

The catalogue's `automation_ready` answers "can the pipeline publish here?" — a fact about our CODE. It says nothing about "should THIS client publish here at all?" — a fact about the CLIENT and the platform's own terms. Conflating them produces the module's worst output: a plumber's marketing article on a developer community, which dev.to's Content Policy forbids in as many words ("not designed primarily for the purposes of promotion or creating backlinks"), Hashnode's forbids, and GitHub's AUP forbids. The adapter is not the problem; pointing it at the wrong client is.

Five honest states per platform per client:
- `eligible`
- `not_connected` — a missing credential an operator can fix in ten minutes
- `not_eligible` — a judgement about this client that no credential changes
- `not_reviewed` — 72 of the 90 catalogue rows sit at the migration DEFAULT of `do_not_use` because nobody has read their terms yet. Presenting a safe default as a reviewed policy verdict was a lie the board told with a straight face.
- `not_supported`

The whole catalogue stays on the board; what varies is which rows are eligible, and every ineligible row carries its reason. A dev-tools SaaS legitimately unlocks the developer platforms; a local plumber sees the topic-agnostic set. **The connected set comes from ACCOUNTS, never from the operator's own selection** — feeding the selection back in declares every requested platform connected by construction, so a campaign would be planned, its properties created and its drafting PAID FOR against platforms holding no credential, surfacing only at publish time.

#### Accounts and identity

An account is an ENTITY, not a secret: ownership (`per_client` vs `house`), health, property caps and the similarity grouping key all need somewhere to live. The retired pattern copied ONE house credential into every client's vault row — one shared failure domain, where a single suspension removes every client's property at once and links our clients to each other in a way no content-level check can see.

Per-client identity: a brand-derived `web2_handle_base` (so the handle is a real brand asset, not a generated string that reads as machinery), the CLIENT'S OWN mailbox for verification mail, and optional IMAP coordinates — the password is sealed in the vault, never a column.

**Why the client's own mailbox:** measured — an alias minted per (platform, client) on one agency catch-all shares a platform prefix, a client-id hash and a registrant domain, so a trust-and-safety team suspending ONE account can enumerate every other client by prefix, by suffix and by domain. The content-similarity gate cannot see that footprint and cannot fix it. The agency catch-all remains correct for ANONYMOUS HOUSE accounts, which carry no durable identity to correlate.

`register_account` is the single choke point for all three creation paths (the CLI, the operator's "add the token" step, and the auto-lane worker): handle hygiene (no platform slug, no client hash), no shared registration domain for `per_client`, credential sealed under the ACCOUNT id rather than the client id, the account row created before anything reports live, and an empty credential refused outright — an account row with nothing sealed behind it shows green on the board and cannot publish.

#### Provisioning queue

Turning "this client should publish on nine platforms" into nine tracked pieces of work that survive being half-finished. States: `queued → identity_ready → awaiting_account → awaiting_verification → awaiting_credential → live` (plus `blocked`, `cancelled`). The state machine is explicit rather than a boolean because the waits have DIFFERENT OWNERS: we decide the identity, a human (or an API) creates the account, the PLATFORM sends mail on its own schedule, and only then does a token exist to seal. Illegal transitions are refused, so the board can never go green with nothing sealed behind it.

Two lanes: **auto** — only Telegra.ph and Write.as, the two with a real documented API signup (deliberately short and measured; claiming a lane the code cannot drive would park work in `awaiting_account` forever while reporting it automatic) — and **guided**.

The tick does exactly two things: mint+seal auto-lane accounts, and watch for verification mail (ONE mailbox check per tick, never a sleep-loop — a blocking `wait_for_message` would hold a worker slot for its whole timeout, so twenty pending signups would hold twenty workers asleep). It deliberately does NOT drive a browser through a signup form: Tumblr's guidelines forbid registering accounts "automatically, systematically, or programmatically", and an account created that way is a client asset built on a terms breach. **The guided lane is a design, not a gap waiting to be automated.**

#### Single property — `POST /offpage/web2/plan` (lead-only)

Runs the SAME guards as the campaign path (it previously ran none of them, so two doors into one table had different rules): eligibility (a judgement-state platform raises 422 quoting the platform's own rule and asks for `acknowledgePlatformAdvisory` — not a refusal, a question asked with the evidence attached), the pacing BURST CAP (N calls to this route were otherwise the same burst through a different door), the ANCHOR check, then a source pack of first-hand proof so the draft is gap-free instead of holding at `[NEEDS:]`, then create the `draft` and enqueue the write worker.

#### Write (`run_write`, never raises)

Idempotent — a row not in `draft` is untouched. No writer configured → a `[NEEDS:]` placeholder held at `needs_review`: degraded, never hallucinated. Cost pre-check on the **`content`** dial; then EVERY internal generator call (one per section, the answer block, photo briefs) is individually gated and committed at its REAL usage-derived cost, never one flat estimate for the whole article. The similarity check then runs, its verdict is ALWAYS recorded, and the row parks at `needs_review`. A gate block landing mid-draft leaves the row at `draft` for a clean retry — never half-billed and half-written.

#### The four safety controls (each answers a measurement, not an intuition)

**1. Cross-property similarity.** The moment two properties share a skeleton, the set stops being N independent blog posts and becomes one detectable pattern — which gets a whole client base actioned at once rather than one placement removed. Ordinary originality checks compare a document only against ITSELF; only a cross-document, cross-client comparison can see this.

The critical departure from the spec: it said to shingle raw text. Measured on real generator output, raw shingling does not detect the templated case at all —

```
w=3   raw 58.2%   entity-masked 100.0%
w=5   raw 27.6%   entity-masked 100.0%
```

Both raw scores sit UNDER the duplicate ceiling, so a raw gate PASSES every templated page, and it gets WORSE as the window grows. The cause: the varying entity token (the city, the brand) sits inside most shingles and hides the duplication being looked for — which is exactly two properties for two plumbers in two cities, the primary local-business use. So the client entity is MASKED before shingling. Without that, the gate ships, passes its own tests, and silently approves precisely what it exists to stop.

Body 5-word shingles, headings 3-word (headings are short strings, so a 5-word window leaves most unrepresented), MOD_m sampled. Thresholds: body block 0.25 / warn 0.15; heading block 0.80 / warn 0.60. Scopes: same client, same house account, same platform within 90 days. The module never sees another client's TEXT — it compares hashes and returns a verdict, a scope label and the colliding property id.

**It runs TWICE, and the second run is the load-bearing one.** At draft time it is FAIL-OPEN (a gate outage must not stop drafting). At APPROVAL it is FAIL-CLOSED. Re-running there is not belt-and-braces: a campaign drafts N properties before a human approves any, so at draft time none of the siblings exists in the corpus and none can possibly collide. Fingerprints are persisted ON APPROVAL, so the duplicate only becomes visible at that moment. Enforcing the frozen draft-time verdict would wave through an entire campaign of near-identical articles, each honestly "clean" when it was written.

**2. Anchor safety.** The classic way a link profile gets actioned is not volume, it is anchor text: N links whose clickable words are the exact commercial phrase the page is trying to rank for. Natural editorial links are overwhelmingly brand names, bare URLs or ordinary sentence fragments. **A hard refusal, not a ratio** — there is no published safe percentage; every number in circulation is somebody's correlation study, and encoding one would be inventing a threshold and then defending it. What IS defensible is the shape: an anchor that is exactly the money phrase has no editorial justification at all. So the rule is a floor (zero exact matches), and everything above it is the operator's judgement. The money phrase is derived from the DESTINATION SLUG, not asked for separately — an operator made to declare their own target keyword will simply declare a different one. Stopwords are ignored, so "the drain unblocking service" is still recognised as the money phrase wearing filler.

**3. No property-to-property links.** The strictest rule in the module. Every other control fights a STATISTICAL tell needing judgement and thresholds; this one is a hard EDGE in a graph anyone can walk from the open web with no inference required. One crawl of our own published pages reconstructs the network, whatever the prose looks like. Banned outright, not rate-limited. Matching is by normalised URL AND by host — so a draft on one Telegra.ph property linking to any Telegra.ph page is refused even when that page is a stranger's. That over-blocks a genuine third-party reference on a path-based host, and the trade is taken on purpose: the cost is one reference an operator can swap; the alternative is emitting the one signal no amount of good prose hides. Mirror rule: exactly ONE link to the client's money site — three links to one destination stops reading as an article that cites a source and starts reading as a link vehicle.

**4. Publish pacing.** A property is defensible while it reads as a real, low-volume brand blog. Thirty articles across one client's properties in an afternoon does not read that way no matter how good each one is: the PATTERN is the tell, it is independent of the prose, and no content-level check can see it. Caps: 7d same property · 72h same client+platform · 24h same client · 1 publish/client/day · 3/day and 20/30d per house account · 10 properties per house account · 4 properties per client campaign · 14d between client properties · up to 36h jitter. A MISSING settings row falls back to the conservative defaults, never to "no limits" — turning a failed read into an uncapped burst is the single worst way for this to fail. Choosing "publish now" packs the schedule as tightly as the caps allow and shows the resulting completion date UP FRONT, so the honest timeline is visible before the campaign is committed rather than discovered afterwards.

#### Campaigns

The unit of work the module was missing: everything underneath already worked — 50+ publishers, a grounded generator, the similarity gate, pacing — but there was no way to ASK for thirty properties, so it meant thirty separate calls with no shared budget, no shared schedule, no single approval, and nothing that could answer "how is it going?".

The design is decided by one measurement:

```
same client, SAME topic, 30 platforms  -> body r = 1.000, heading r = 1.000  (BLOCK)
same client, DISTINCT topics           -> body r = 0.034, heading r = 0.406  (pass)
```

Publishing one topic to thirty platforms produces thirty BYTE-IDENTICAL articles — exactly the "fan one branded article out to every selected platform" behaviour the old UI advertised. So "thirty blog posts" cannot mean thirty copies: the planner must produce **thirty distinct topics**, and a campaign that cannot is REFUSED AT PLANNING TIME rather than after thirty metered drafting runs.

Two further measured facts shape the layout: rotating the writing framework across the set (PAS, AIDA, BAB, FAB, 4 Ps, PASTOR, 4 U's) halves worst-case heading resemblance (0.406 → 0.208), because same-framework articles share a fixed heading skeleton; and spreading across PLATFORMS is both FASTER (the 24-hour any-platform rule instead of the 72-hour same-platform one: ~30 days versus ~87 for thirty properties) AND lower-footprint — the fast route and the safe route are the same route.

Routes: estimate (price + schedule + projected completion, with per-platform refusals RETURNED rather than silently dropped — a selection quietly shrunk from thirty platforms to four is a lie the operator would discover weeks later), create, approve, list, placements. The campaign-level approval hands each property a review request carrying NO acknowledgement, so a campaign-level decision can never acknowledge a collision on a property the operator has not looked at individually.

#### Approval — `POST /offpage/web2/{id}/approve` (lead-only)

Status must be `needs_review` (409 otherwise). The LIVE similarity verdict wins over the one recorded at draft time. `sim_unavailable` → 409 (publishing on "we could not check" is precisely the harm the gate exists to prevent). `sim_block` while enforcement is on → 409. A `warn` (or a block with enforcement off) passes only with an explicit `acknowledgeSimilarity`. Then the row moves to `publishing` and is enqueued immediately UNLESS its pacing slot is in the future. `reject` moves it to `rejected`.

#### Publish (`run_publish`, never raises)

Order of holds:
- already `published` → no-op; not `publishing` → skipped (not approved).
- unknown platform → `failed`.
- **`shared_origin` frozen** → held at `needs_review`. A property published through a credential later found to be SHARED across clients receives no further posts. The article already live is left alone deliberately — deleting a live page is a larger, stranger signal than letting it sit — but continuing to post to it keeps extending a correlation between clients we can no longer defend.
- unresolved `[NEEDS:]` gaps or an empty body → hold at review.
- no publisher (no per-account credential) → hold at review.
- cost gate on the **`backlinks`** dial → hold at review.
- publish → commit the metered cost → `verify_live_and_indexable` (Medium draft-only is never marked live) → **`check_link`**.

**`check_link` is a separate measurement, and that is the point.** "Published" only means the platform's API accepted the post. It does NOT mean our link is on the page: platforms strip links, rewrite them through redirectors, or add `rel="nofollow"` server-side, and none of that comes back in the create response. Reporting a placement as delivered on the strength of a 201 is how an agency invoices for a link that is not there. Three outcomes, deliberately three rather than two: `found` (with the `rel`, which says whether it passes equity), `missing` (a real, actionable defect), `unknown` (we could not look — NOT a pass and never shown as one; a control that cannot distinguish "absent" from "unchecked" quietly converts every outage into a false accusation, or every failure into a tick).

**Credential check** follows the same three-outcome discipline: one cheap authenticated GET against the account's own profile endpoint → `ok` / `bad` (401/403 — re-issue the token) / `unknown`. Read-only by construction, so a verification can never create, publish or modify anything. It exists because a completeness check proves SHAPE, not VALIDITY — a revoked token, a typo and a key pasted from the wrong platform all look identical, and the operator otherwise finds out after the drafting spend.

#### Drip release — built, tested, and DELIBERATELY PARKED

An owner decision. Approved campaigns publish immediately, `scheduled_for` stays NULL, and no scheduler entry runs the release tick. The module is kept tested so re-enabling drip is a wiring task, not a rewrite. Its design (copied from the content module's proven scheduled-publish shape rather than invented) re-checks the caps AT RELEASE, not only at planning — a schedule laid out three weeks ago does not know what has happened since, and a property whose slot has arrived but whose caps would now be breached is DEFERRED, never published anyway. Deferring is the safe direction: the worst case is a placement going out later than planned.

---

### 5. CROSS-CUTTING RULES

- **Every worker never raises.** With `task_acks_late`, a raised exception redelivers the job and re-runs a PAID stage = double spend. So every orchestrator marks a terminal state and returns a small result dict.
- **Money dials + cost gate.** Every paid stage runs a PRE-CHECK before the call and COMMITS the real cost after. Dials used here: `citations` (submits), `citation_discovery` (audit sweeps), `content` (Web 2.0 drafting), `backlinks` (Web 2.0 publishing and off-page monitor pulls). A blocked gate HOLDS and spends nothing. The liveness re-check makes plain HTTP GETs and no provider call, so it is NOT metered and needs no dial.
- **The job contract.** Each task writes a `job_runs` row with a typed outcome (completed / blocked / degraded / failed), an idempotency key, and dead-letter + reaper coverage. `ready_for_human` renders as BLOCKED with its reason, never as a success — "is_success" may be true only when a submission actually went out. A bare Celery task wrote no run row, so a 45-row campaign was invisible in Operations and, with no worker consuming the queue, indistinguishable from a platform that was merely idle.
- **RLS vs the worker.** The worker runs as `service_role` (BYPASSRLS), so RLS policies gate the HTTP surface only. Every invariant that actually matters is a CHECK constraint or a trigger, which `service_role` does not bypass.
- **SSRF.** Any URL fetched or navigated server-side is guarded: `is_public_url` before liveness probes and operator-supplied completions; a trigger binding a spec's URL to its own directory's host.

---

### 6. THE HONEST CURRENT STATE (early September 2026)

State this plainly whenever describing capability — the system is built to report it, not to flatter it.

- **Earned specs: ZERO.** Route B is empty, so in practice virtually every campaign row is classified `ready_for_human` / `no_verified_spec` and lands in the operator queue. The engine-status board's HEADLINE is deliberately `machine_submittable_directories` (the active-spec count), because the board once read "3/5 engines connected" — counting a proxy and a CAPTCHA solver — while ZERO directories were machine-submittable.
- **Route A:** Data Axle blocked pending a real per-Add rate (an open owner decision); Apple needs keys; GBP has no engine written; Bing and Foursquare write paths retired as non-existent.
- **Scheduled jobs (Celery beat) are OFF** by owner instruction. Consequences: the citation liveness re-check does not fire on a schedule (reachable on demand at `POST /citation-builder/recheck`), and the Web 2.0 drip release never fires. Nine tests asserting a populated schedule are deliberately left RED as the acceptance suite for restoring cron, so the backend lint/test CI job has been failing on `main` since 2026-08-19.
- **Web 2.0's binding constraint is credentials**, not adapters: 50+ publishers exist, but most catalogue rows report `not_connected` for a given client, and the automatic signup lane covers only two platforms.
- **Nothing "auto-lists with a live link" today.** Anything claiming otherwise is describing engines that are not configured.

---

### YOUR TASK

Explain this module back to me. Cover:

1. The three pipelines end to end, as flows — what triggers each stage, what decides each branch, and what state a row is in at every point.
2. Every guard and refusal, and the specific failure it defends against.
3. The status vocabularies (`nap_status`, `submit_status`, the Web 2.0 statuses) and exactly what each value licenses us to claim to a client.
4. Where the real constraints are today, and what would move each one.
5. Anything here that looks internally inconsistent or under-specified — flag it and ask, rather than smoothing it over.

Be specific and use the module's own vocabulary. Do not substitute generic SEO advice for what is written here.
