# REQUIREMENT GAP ANALYSIS — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit:** `79d1036`
**Baseline:** `docs/recovery/REQUIREMENTS_TRACEABILITY.md` (382 requirements: 121 P0, 183 P1, 59 P2, 10 P3)
as amended by `docs/recovery/DECISIONS_LOG.md` (v1 = Portal · Audit · Content+WordPress · Citations · Web 2.0).

**This document covers all 126 P0 rows** in the traceability matrix, plus the P1/P2 items where the
gap is material. P1–P3 items not listed here inherit the verdict of their parent P0.

**Verdict vocabulary:** MET · PARTIAL · NOT MET · UNVERIFIED (could not be established without
running the system — see the audit limitation in `REPOSITORY_ARCHITECTURE.md`).
**Severity:** CRITICAL (blocks acceptance) · HIGH · MEDIUM · LOW.
**Action:** KEEP · FIX · REFACTOR · REBUILD · REMOVE · ADD.

> **Method note.** I did not judge on code existence. Where the code exists but the behaviour it
> claims cannot occur — a job with no schedule, a cost log that always writes zero, a bot with 3
> of 151 specs — the verdict is NOT MET, and the evidence line says why.

---

## 1 · ADMIN PORTAL (P0)

| ID | Expected | Current implementation | Actual behaviour | Gap | Sev | Root cause | Action |
|---|---|---|---|---|---|---|---|
| ADM-001 | Only live metrics; no hardcoded value | Admin screens read live API via TanStack hooks. `lib/data.ts` mock arrays (`audits`, `traffic`, `team`, `clients`) verified **unreferenced** | Mostly live | `lib/cost.ts:19-27` still hardcodes provider unit prices as display strings (`"$0.30 / search"`, `"~$0.90 / page"`) | HIGH | Demo-first build; cleanup incomplete | **FIX** |
| ADM-003 | Every rendered control does real work or is not rendered | Two cleanup commits (`79d1036`, `62ae44b`) removed most dead controls | Largely true | `AuditCoverage.tsx:53` renders **"Coming soon"**; demo store + mock vault keys still in the bundle | MEDIUM | Same | **REMOVE** |
| ADM-004 | A feature runs real work, not describes itself | Most modules execute | PARTIAL | `tool_workspaces` (9 endpoints) re-describes what `/stats` already returns; GMB posting is dormant; site_builder backend is orphaned after its UI removal | MEDIUM | Module-vs-outcome build order | **REFACTOR** |
| ADM-009 | Full business profile + NAP at client creation, reused downstream | `db/0051`, `0060`; `ClientCreate.business`; `citations/ensure-profile` | Works on the happy path | **The write is non-atomic**: `clients.py:53-86` does `insert_client` → `upsert_business_profile` (try/except, "BEST-EFFORT") → `seed_onboarding_for_client`. A failure leaves a client with no NAP — the exact state that makes Citations report "no business profile" | HIGH | No multi-statement transaction seam (`rls_connection` = 1 txn per call) | **FIX** |
| ADM-011 | Site connection with sealed credentials **and capability discovery** | `wp_connections` CRUD + `/test`; vault-sealed creds | Connection test exists | **No capability report.** `/test` proves reachability; it does not name in plain language which publishing capabilities the site supports (WP-005 lists 14 facts to discover) | HIGH | Not built | **ADD** |
| ADM-015 | Real Fiverr gigs, not demo gigs | `frontend/lib/freeAuditGigs.ts` — real `fiverr.com/iamdaani` URLs, honest comment about not fabricating thumbnails | **MET in content** | Gigs are hardcoded in a TS file, not admin-manageable; changing one is a redeploy | LOW | — | **FIX** (move to `upsells` table) |
| ADM-017 | Content wizard/review/edit/publish complete | `ContentWizard.tsx` (669 LOC), `ReviewPreview.tsx` (565), page-model editor, review endpoint | Surfaces are complete | Publish silently degrades (E8); research blocks the UI for 40–60 s | HIGH | See CONT-035, D1 | **FIX** |
| ADM-018 | Citations submit no longer fails | `citation_submit` worker, per-row claim, status ledger | Worker is sound | **`FORM_SPECS` has 3 entries against 151 `bot_fillable` directories.** Submission cannot succeed at the promised breadth | **CRITICAL** | Bot specs were never harvested at scale | **REBUILD approach** |
| ADM-020 | Reports use real cron-driven data | `scheduled_job_runs` ledger + real producers | Producers are correct | **Beat is off** — the ledger is empty, so Reports has no cron data to show | **CRITICAL** | AUTO-001 | **FIX** |
| ADM-025 | Cost computed at runtime; no predefined price | `app/services/pricing.py` computes from real tokens/queries. Flat `*_cost_estimate` settings survive only as the pre-check number | **Backend is correct** | Two leaks: `lib/cost.ts` hardcoded prices (UI), and the free audit **logs $0.00 on a run that spends** | **CRITICAL** | Free-funnel cost path | **FIX** |
| ADM-026 | Spend halt stops **every** API | `cost_gate` evaluates `blocked_halt` first, before the dial, with no bypass | Correct **where the gate is called** | The public free-audit path is explicitly *"never gated"* (`workers/tasks/audit.py:450-457`) and commits `0.0`. **The halt cannot stop the free funnel.** Unauthenticated + 5/min/IP = denial-of-wallet | **CRITICAL** | Free audit was assumed $0 and no longer is | **FIX** |
| ADM-027 | Provider toggles / manual / API mode actually work | `DialMode = api\|byhand\|off`, honoured in `cost_gate.evaluate` | Appears correct | Cannot be run-verified in this audit | MEDIUM | — | **KEEP** + prove |
| ADM-031 | Vault: scoped, masked list, owner-only reveal | `app/routers/vault.py` — `ManageVault` for list/add/rotate, `require_owner()` for reveal; AES-256-GCM, master key outside Postgres | **MET** | `frontend/lib/vault.ts` still carries 11 fake `secret:` strings (unimported) | LOW | Demo residue | **KEEP** + **REMOVE** the mock |

---

## 2 · TEAM & CLIENT PORTAL (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| TEAM-003 | Task assignment lists team members correctly | `GET /members`, `POST /tasks` with staff validation | **MET** (code-verified) | LOW | **KEEP** |
| TEAM-006 | Review checkpoint blocks publish | `POST /content/jobs/{code}/review`; `db/0012` guard triggers enforce the lifecycle **at the database** | **MET** — exemplary | — | **KEEP** |
| CLIENT-008 | Hard isolation; `mrr`/`cost`/`error`/artefact paths unreachable to another client | RLS on every application table (ENABLE + FORCE, verified); `CurrentClientDep` pins `client_id` server-side, never from a body; `scheduled_job_runs` has no client select policy | **MET** | None. `tests/integration/test_portal_isolation.py` proves exactly this against **real local Postgres** using the client's own `authenticated`-role identity, asserting (a)-(h): base tables return 0 rows to a foreign tenant, `mrr`/`cost`/`error`/`*_path` are absent from the portal views, a portal-run audit is written with a server-pinned `client_id`, and a free-tier client is 403'd from a paid audit | — | **KEEP** |
| CLIENT-011 | Never offer an unverified artefact | Commit `79d1036` was literally *"honest artifact flags (no dead PDF/report buttons)"*; `_find_pdf`/`_find_html` return `None` when absent | **MET** | — | **KEEP** |

---

## 3 · AUDIT (P0)

| ID | Expected | Current | Actual | Gap | Sev | Action |
|---|---|---|---|---|---|---|
| AUD-001 | Free audit = one condensed ~10–15 page report, no type split | Public funnel runs the **comprehensive** engine at `--mode auto` | Not condensed — it is the full run | Deliverable shape diverges from the requirement, and it costs money | HIGH | **FIX** — decide: condensed+free, or comprehensive+metered+disclosed |
| AUD-002 | **Free audit spends zero on paid providers** | `--mode auto` turns Serper + Google Places **ON**; the adapter's own comment: *"this path is NO LONGER $0"* | Spends on every run, logs `$0.00` | **Direct contradiction of the requirement, and the ledger hides it** | **CRITICAL** | **FIX** |
| AUD-004 | Paginated in-dashboard HTML preview, same content as PDF | `ReportViewer.tsx` renders `report.html` in a **sandboxed `srcdoc` iframe** (`sandbox="allow-same-origin"`, no `allow-scripts`) and windows it into A4 pages | **MET** — and securely done | — | **KEEP** |
| AUD-009 | Every finding carries evidence; no invented metrics | Engine analyzers are deterministic; `--agents off`/`--ai-narrative off` passed explicitly so behaviour never depends on a TTY | **MET** by construction | AI narrative, when enabled, is not schema-validated against the computed metrics (see AI-006) | MEDIUM | **KEEP** + **FIX** AI-006 |
| AUD-012 | PDF and HTML from one source | `report.pdf` rendered from the same `report.html` the viewer displays; `_PDF_CANDIDATES` prefers it | **MET** | Older runs fall back to multi-file reports | LOW | **KEEP** |
| AUD-013 | Caller owns the hard timeout; non-zero exit / timeout / missing `run.json` = failure | Exactly this, documented and implemented in `integrations/audit_engine.py` | **MET** | — | **KEEP** |
| AUD-014 | A run with no PDF does not offer one | `_find_pdf` returns `None`; honest artifact flags | **MET** | — | **KEEP** |

---

## 4 · CONTENT (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| CONT-001 | Research before writing | `content_research.py` (1,384 LOC) + Anthropic server-side `web_search`, strict-JSON page set, SSRF-guarded, cost-gated | **MET functionally**, but it is a **40–60 s synchronous HTTP request**; `next.config.mjs` raises `proxyTimeout` to 180 s to accommodate it | HIGH | **REFACTOR** to a job |
| CONT-002 | 7-type content picker | `ContentJobCreate.content_type` | UNVERIFIED that all 7 types are present end-to-end | MEDIUM | **FIX** — enumerate and prove |
| CONT-007 | Bulk fan-out: one / several / all | Job fan-out exists | No batch progress surface, no partial-failure report | MEDIUM | **FIX** |
| CONT-010 | Cost estimated and explicitly confirmed before a bulk run | Gate produces an `estimated_cost` pre-check | **No confirmation step found** in the wizard flow | HIGH | **ADD** |
| CONT-017 | **Zero em dashes** anywhere | `content_guard.strip_dashes` runs unconditionally on every block after any rewrite; the guarantee is `count_dashes(...) == (0,0)` | **MET for generated content** | Not enforced on **emails** or **AI-assist responses** — the requirement says "anywhere, on the site, in emails or in AI responses" | MEDIUM | **FIX** — extend the guard |
| CONT-018 | AI-sounding detection + section rewrite | `scan()` → `ai_score`, `deai_draft()` rewrites only flagged prose blocks, degrades to a plain strip on writer failure | **MET** — genuinely well built | — | **KEEP** |
| CONT-028 | The gate's status unambiguous across code and docs | `content_qa.py:107` `PROVISIONAL = True`, and every `QaScore` carries `provisional=True` | **MET** — it is unambiguously declared provisional | — | **KEEP** |
| CONT-029 | **Threshold and weights calibrated before enforcement** | `WEIGHTED_TOTAL_THRESHOLD = 85`, `DIMENSION_WEIGHTS` — both marked `PROVISIONAL (R4)`, never calibrated | **A hard publish gate is enforced on an uncalibrated score.** Nobody can say whether it blocks good work or passes bad work | **CRITICAL** | **FIX** — calibrate against a human-graded golden set, or downgrade to advisory |
| CONT-031 | Exactly one mandatory human review gate | `/review` on content jobs | **MET** | — | **KEEP** |
| CONT-035 | On approval with WP connected, auto-publish and return the live URL | Approve → publish task → `content_wp_url` (`db/0057`) | **Publishing can silently not happen.** `content.py:2160-2196` swallows every failure and finishes as `degraded=True` artifact-only, job complete | **CRITICAL** | **FIX** |
| CONT-040 | Publish idempotent, keyed on job id | `_publish_via_rest` is documented "idempotent UPDATE-or-CREATE" | **MET on the REST path**; the plugin path's idempotency is not established | MEDIUM | **FIX** |
| CONT-041 | Post-publish verification: renders, schema validates, images load, opens editable | `visual_validations` (`db/0071`), `visual_diff.py` exist for site-builder | **No post-publish verification on the content publish path** | HIGH | **ADD** |
| CONT-043 | Internal near-duplicate check across a bulk run | Not found. (Note: *internal linking* **is** built — `content_generator._links_block` — but cross-page duplicate detection is a different requirement and is absent) | **NOT MET** | HIGH | **ADD** |
| CONT-046 | Factual-claim guard (stats/prices/certifications from context or omitted) | `[NEEDS:]` placeholders are preserved and never sent to the writer — a partial mechanism | **No explicit claim classifier/guard** | HIGH | **ADD** |

---

## 5 · WORDPRESS (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| WP-001 | One-time sealed connection, decrypted at point of use | `wp_connections` + vault; creds passed in, never read by the publisher seam | **MET** | — | **KEEP** |
| WP-004 | Companion plugin route with its own token | AIOS Publisher plugin, `aios/v1` namespace, shared key **in the JSON body** (survives Authorization stripping) + `X-AIOS-Key` header, browser UA to defeat WAF | **MET** — and it solves a real, proven host problem | Key is a single shared secret per site with no rotation surface | MEDIUM | **KEEP** + **ADD** rotation |
| WP-005 | Capability discovery: 14 named facts | `/test` reachability only | **NOT MET** | HIGH | **ADD** |
| WP-006 | Canonical builder-agnostic page model | `app/services/page_model.py` (742 LOC) + `page_blueprints.py` feeding both Elementor and Gutenberg emitters | **MET** — this is the right architecture | — | **KEEP** |
| WP-007 | Elementor widget tree producing a fully editable page | `elementor.py` (1,255 LOC): deterministic `_elementor_data`, `_elementor_edit_mode=builder`, design-profile sectioning + palette, SHA-1 ids (no `Date`/`random`) | **MET** — strongest module in the tree | Not verified against a live Elementor install in this audit | MEDIUM | **KEEP** + prove |
| WP-010 | Read and reuse the site's existing style kit | `site_design.py` (Playwright-measured) → design profile → `_aios_design_css` meta enqueued in `wp_head` | **MET** | — | **KEEP** |
| WP-015 | Never write global styles/theme/existing pages — additive only | Plugin writes only its own post meta + creates posts | **MET by construction** | No explicit assertion/test proving it | MEDIUM | **KEEP** + **ADD** test |
| WP-016 | Meta title/description into the **active SEO plugin's** fields | Plugin injects its own `_aios_schema_jsonld` and renders schema in `wp_head` | **NOT MET** — writes its own meta, does not detect and populate Yoast/RankMath/AIOSEO fields | HIGH | **ADD** |
| WP-024 | Bounded DOM size, asserted | `AIOS_PUBLISHER_MAX_BODY_IMAGES = 20` caps image sideloading | **PARTIAL** — image count is capped; DOM node count is not measured or asserted | MEDIUM | **ADD** |
| WP-032 | **Revert for anything the system changes** | `revert_onpage_fix` exists for on-page fixes only | **NOT MET for content publishes** — no content version history, no revert | HIGH | **ADD** |
| WP-034 | Detect human edits; refuse overwrite; **hash/etag, not string compare** | `on_page` drift guard is a plain string comparison (self-declared) | **NOT MET as specified** | HIGH | **FIX** |

---

## 6 · CITATIONS (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| CIT-001 | Canonical NAP per client **per location** | One `client_business_profiles` row per client | **No first-class location entity** (see DATA-010). Multi-location is not modelled | HIGH | **ADD** |
| CIT-002 | Extended ~20-field profile | `db/0060_business_profile_fields` widens the profile | **MET** (field set present) | Logo/photos/socials completeness not verified | MEDIUM | **KEEP** |
| CIT-003 | Empty profile blocks **before** any spend | `ensure-profile`, `audit-plan` endpoints | UNVERIFIED that the block precedes the gate call on every path | HIGH | **FIX** — prove with a negative test |
| CIT-004 | Citation audit: what exists, where, what is inconsistent | `citation_discovery.py` (904 LOC), `citations.py`, NAP alignment endpoint | **MET** | — | **KEEP** |
| CIT-006 | Build only where not already listed | `gap-analysis` endpoint + ledger | **MET** | — | **KEEP** |
| CIT-007 | Per-client accounts under the client's own identity | Vault provider `web2:<platform>` scoping exists; citation-side per-client email alias designed (`CitationJob.client_id`) | **PARTIAL** — the scoping model is right, the account-creation engine is not built (CIT-008) | HIGH | **FIX** |
| CIT-008 | Signup + CAPTCHA solve + IMAP confirmation click | `citation_signup.py` structure + `captcha_solver.py` + `imap_mailbox.py` all exist as seams | **`SIGNUP_SPECS` has no concrete entries.** The pieces exist; the recipes do not | **CRITICAL** | **REBUILD** |
| CIT-009 | Submission across ~100 valuable platforms | 244 directories seeded; **3 bot form specs**; 2 unconfirmed APIs | **Real automated coverage ≈ 3 platforms** | **CRITICAL** | **REBUILD approach** |
| CIT-010 | Form specs verified against live forms before scale | Source says the opposite: *"EVERY SELECTOR HERE IS A BEST-EFFORT STARTING SPEC, not hand-verified"* | **NOT MET, and honestly declared** | **CRITICAL** | **REBUILD** |
| CIT-011 | Proof per unit: live URL **and** screenshot | Status ledger records URLs; screenshot capture not found | **NOT MET** (screenshot) | HIGH | **ADD** |
| CIT-013 | Per-unit cost against the ceiling at runtime | `pricing.py` + `captcha_solver` metering on the `citations` dial | **MET for marginal cost** | — | **KEEP** |
| CIT-014 | **Loaded** cost incl. human handoff, proxy bandwidth, CAPTCHA balance | Only marginal provider cost is modelled | **NOT MET** — and with 151 unsupported `bot_fillable` directories the human-handoff term dominates. **This is the term that decides whether the <10¢ commitment is honourable** | **CRITICAL** | **ADD** |
| CIT-019 | Listing removal / correction workflow | `citation_id/action` + `DELETE /clients/{id}/citations` | **PARTIAL** — actions exist; a correction (re-submit changed NAP) workflow is not evidenced | MEDIUM | **FIX** |
| CIT-023 | **No fabricated business data, ever** | `CitationJob` takes explicit NAP fields; no defaulting found | **MET by construction** | No explicit "missing required field blocks the unit" assertion | MEDIUM | **KEEP** + **ADD** test |

---

## 7 · WEB 2.0 (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| WEB2-001 | 50+ platforms with live publishing | **55 concrete API publisher classes, 52 credential factories** | **MET as capability** — the single strongest asset in the off-page tree. `PLATFORM_MEDIUM` is declared with no client and will fail at dispatch | LOW | **KEEP**; **REMOVE** Medium |
| WEB2-002 | Unique content per property, never spun | `web2_pipeline.py` drives the full generator per property (multiple `writer.summarize()` calls each) | **MET** | — | **KEEP** |
| WEB2-003 | Human-paced posting with jitter, never a burst | No pacing/jitter mechanism found — **and beat is off, so there is no scheduler to pace with** | **NOT MET** | HIGH | **ADD** |
| WEB2-004 | A different platform mix per client | `FootprintChoice` exists | **PARTIAL** — mechanism present, per-client policy not evidenced | MEDIUM | **FIX** |
| WEB2-007 | Cross-property similarity gate, within **and across** clients | Not found | **NOT MET** | HIGH | **ADD** |
| WEB2-008 | House-account footprint analysis + property cap per account | `FootprintChoice` (`web2_publishers.py:3148`) | **PARTIAL** — no cap enforcement found | HIGH | **FIX** |
| WEB2-009 | Per-client accounts on high-authority platforms | Vault `web2:<platform>` per-client scoping supports it | **PARTIAL** — model supports it; provisioning at campaign start (D-16) not built | HIGH | **FIX** |
| WEB2-010 | Lead approval before each property goes live | `POST /offpage/web2/{id}/approve` | **MET** | — | **KEEP** |

---

## 8 · AI (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| AI-001 | **Python computes numbers, AI writes narrative** | Audit scoring, QA scoring, cost, keyword winnability are all deterministic Python. AI is confined to prose | **MET** — the discipline is real and consistently applied | — | **KEEP** |
| AI-006 | Structured AI output schema-validated; a metric-inventing output rejected | `policy_generate.py` / `policy_ask.py` demand strict JSON | **PARTIAL** — JSON shape is validated; **there is no check that a returned number matches a Python-computed one** | HIGH | **ADD** |
| AI-007 | AI failure degrades to a **named hold state**, never a crash and never an auto-pass | Degradation is universal and never crashes | **The failure mode is the opposite of an auto-pass — but it is also frequently invisible.** A missing `[ai]` extra silently substitutes `FakeSummarizer`-class behaviour rather than declaring a hold | HIGH | **FIX** — add a boot assertion + a named `ai_unavailable` state |
| AI-008 | Every AI call passes the gate; actual cost logged | `GatedSummarizer` wrappers at `context_cost.py:118`, `web2_pipeline.py:310`, `workers/tasks/content.py:304`; `pricing.anthropic_cost` from real token counts | **MET** | — | **KEEP** |
| AI-010 | Untrusted fetched content structurally demarcated, never in an instruction position | Frozen system prompt; fold history in the user turn | **PARTIAL** — the separation exists structurally, but crawled/competitor page text flows into user-turn prompts with **no delimiter/escaping convention and no injection test** | HIGH | **ADD** |
| AI-011 | A model cannot trigger spend, publish or credential access as a side effect | No tool-use loop is wired to the writer; the only server-side tool is Anthropic's own `web_search`. Publishing is a human-gated endpoint | **MET by architecture** | The `mcp_gateway` skill surface is the one place this could change | MEDIUM | **KEEP** + guard |
| AI-012 | No credentials, other clients' data or internal costs in a model context | Context packs are entity-scoped; vault secrets never enter a prompt | **MET** (code-verified) | No automated assertion | MEDIUM | **KEEP** + **ADD** test |

---

## 9 · AUTOMATION (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| AUTO-001 | **Restore the beat schedule** | `beat_schedule = {}` (`celery_app.py:173`); 11 entries preserved verbatim in `_BEAT_SCHEDULE_DISABLED` | **NOT MET** — but the fix is one line plus verification of each entry | **CRITICAL** | **FIX** |
| AUTO-002 | Policy Radar runs live, auto-updates daily | `generate-policy-daily` crontab entry sits in the disabled block; on-demand path works | **NOT MET** — and **D-17 has not decided** whether Policy Radar is in v1 | **CRITICAL** (decision) | **DECIDE then FIX** |
| AUTO-004 | Idempotency key on every job that mutates external state | Real where present (`FOR UPDATE SKIP LOCKED` claims, per-day dedupe, run-claim mutex) — but **8 of 20 task modules have no claim or lock** | **PARTIAL** | HIGH | **REFACTOR** |
| AUTO-006 | Overlap lock on every scheduled job | R6 advisory lock present on the sweeps that take it | **PARTIAL** — coverage is by convention, not enforced | MEDIUM | **FIX** |
| AUTO-009 | A cost-gate block is a **visible** state, never a silent no-op | `SpendHaltedError` → typed 402 on synchronous paths; worker paths observe `blocked_halt` and degrade | **PARTIAL** — `POST /keyword-research/research` returns 202 and blocks silently (self-declared); the free-audit path bypasses the gate entirely | HIGH | **FIX** |
| AUTO-011 | Broker visibility timeout asserted ≥ longest task time limit **at boot** | The invariant is **documented as a comment** (`celery_app.py:136-141`) with `visibility_timeout=3600` and `task_time_limit=1800` — currently satisfied | **NOT MET as specified** — it is a comment, not a boot assertion. The next person to raise `task_time_limit` breaks it silently and jobs run twice (double spend) | HIGH | **ADD** assertion |
| AUTO-012 | **Dead-letter queue with an operator surface** | Does not exist anywhere in the repository | **NOT MET** | **CRITICAL** | **ADD** |
| AUTO-015 | Per-client job concurrency caps | Single default queue, `-c 4`, no per-tenant fairness | **NOT MET** — one client's 50-page bulk run starves every other client | HIGH | **ADD** |
| AUTO-023 | Nightly backup, failure alerting loudly | `backups.py` is genuinely good (pg_dump subprocess, B2 offsite, PG* env never argv, guarded restore) | **NOT MET** — no beat entry fires it, and no alert path on failure | **CRITICAL** | **FIX** |

---

## 10 · SECURITY (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| SEC-002 | RBAC server-side; UI hiding is presentation only | 260/305 endpoints with explicit guards; alias-resolved AST sweep + a runtime OpenAPI 401 test | **MET** | — | **KEEP** |
| SEC-003 | Vault AES-256-GCM, masked list, owner-only reveal, decrypt at point of use | Exactly this | **MET** | — | **KEEP** |
| SEC-004 | Client isolation at the DB via RLS, proven by an integration test **using the client's own identity** | RLS is the real boundary; `rls_check` gate in CI | **MET** — `tests/integration/test_portal_isolation.py` does exactly this (two tenants + one staff user against real Postgres, 8 assertions), alongside `test_rls_matrix.py` and the structural `rls_check` gate | — | **KEEP** |
| SEC-006 | EdDSA under a hard algorithm allow-list | `_ALLOWED_ALGS = ["EdDSA"]`, `require=["exp","sub","aud"]`, aud+iss verified | **MET** — textbook | — | **KEEP** |
| SEC-007 | No public signup; owner-only provisioning in one privileged transaction | `provision_user` in a single `privileged_connection()` txn; no signup route | **MET** | — | **KEEP** |
| SEC-010 | SSRF guard on every outbound target, including client sites | `validate_public_host` used at 30 call sites across audits, public funnel, content, on-page, site-builder, policy-watch, site-analyzer | **MET** (broad coverage) | Not proven exhaustive | MEDIUM | **KEEP** |
| SEC-011 | XSS defence where AI/client HTML renders | Audit HTML in a **sandboxed `srcdoc` iframe without `allow-scripts`**, plus `default-src 'none'` CSP on the served artefact. Only one `dangerouslySetInnerHTML` in the tree (a chart tooltip, internally built) | **MET at the artefact surface** | **The application itself has no CSP** (`nginx.conf`/`Caddyfile`: 0 hits) | HIGH | **ADD** app CSP |
| SEC-016 | Rotate every credential exposed in the WhatsApp exports | Out of code scope | **UNVERIFIED** — cannot be confirmed from the repository | **CRITICAL** | **ADD** (operational) |
| SEC-017 | Move the chat export out of the repo and gitignore it | `whatsapp chats, media and calls/` is **present in the working tree** (untracked: 589 `.opus`, 26 `.mp4`, 224 `.jpg`) | **NOT MET** — untracked, so not in git history, but one `git add -A` away from being committed | HIGH | **FIX** |
| SEC-018 | A credential channel that is not a messaging app | Vault exists and is the right destination | **PARTIAL** — process, not code | HIGH | **ADD** (operational) |
| SEC-020 | Untrusted content treated as data, never instructions | See AI-010 | **PARTIAL** | HIGH | **ADD** |
| SEC-021 | Vault master-key custody, backup and rotation documented | Master key is held outside Postgres | **NOT MET** — no custody/rotation runbook found | HIGH | **ADD** |
| SEC-022 | Backups encrypted and **restore-tested** | `pg_dump` + B2 upload; restore is owner-only with an echoed-id confirm | **PARTIAL** — encryption at rest depends on B2 config; **no restore drill evidence** | HIGH | **FIX** |
| SEC-025 | Every spend-causing and live-site-mutating action requires an explicit permission and is attributed to a human | `require_perm` on spend paths; on-page apply/revert run on the acting **lead's** RLS identity and a `0038` trigger refuses a non-lead-attributed live-site write | **MET, and unusually well done** | The public free-audit funnel is spend-causing and has **no human attribution** | HIGH | **FIX** |
| **(unstated)** | **Ability to deactivate/offboard a user** | `user_status` enum = `active\|away\|invited\|offline`; no DELETE/deactivate endpoint; `login()` never checks status; `get_current_user` loads `status` and no guard reads it; 7-day non-revocable token | **NOT MET — and the requirement is missing from the matrix entirely** | **CRITICAL** | **ADD** requirement + implementation |

---

## 11 · DATA MODEL (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| DATA-001 | Users, roles, feature grants, skill tokens | `db/0002`, `0030`, `user_feature_grants` | **MET** | — | **KEEP** |
| DATA-002 | Clients + extended business profile | `db/0003`, `0051`, `0060` | **MET** | Non-atomic creation (ADM-009) | HIGH | **FIX** |
| DATA-003 | Sites with CMS type, sealed credentials **and a capability record** | `db/0003`, `0058` | **PARTIAL** — no capability record column/table | HIGH | **ADD** |
| DATA-004 | Audits with type, tier, status, run uuid, artefact path, scores | `db/0008`, `0015` | **MET** | Artefact path is a **local filesystem** path | HIGH | **REFACTOR** |
| DATA-006 | Content jobs with type, framework, target, status, published URL, cost, source pack, QA score | `db/0017`, `0057`, `0059`, `0072` | **MET** | No version history (WP-032) | HIGH | **ADD** |
| DATA-010 | **First-class location entity** | Does not exist | **NOT MET** — blocks CIT-001 and ADM-010 for multi-location clients | HIGH | **ADD** |
| DATA-012 | Directories, strategy, campaigns, submissions, handoffs | `db/0018`, `0045`, `0046`, `0048`, `0064`, `0065`, `0067` | **MET** | — | **KEEP** |
| DATA-015 | Web 2.0 platforms, properties, publish records | `db/0028`, `0062`, `0063`, `0066`, `0068`, `0070`, `0072`, `0076`, `0077` | **MET** | — | **KEEP** |
| DATA-016 | **Web 2.0 accounts as first-class entities** (platform, ownership, health, property count) | Accounts live as vault entries (`web2:<platform>` provider) | **NOT MET** — an account is a secret, not an entity. No health, no property count, no ownership tier | HIGH | **ADD** |
| DATA-020 | Cost dials, budgets, cost log holding **actual** cost | `db/0006`, `0044`; `pricing.py` runtime cost | **PARTIAL** — the free-audit path writes `0.0` for real spend | **CRITICAL** | **FIX** |
| DATA-021 | Append-only activity log | `db/0005` + `record_activity` | **PARTIAL** — not every mutation path calls it; no DB-level enforcement (no trigger, no revoked UPDATE/DELETE evidenced) | HIGH | **FIX** |
| DATA-022 | Task and content lifecycles enforced by **database triggers** | `db/0012_tasks_guard_hardening` enforces task transitions at the DB | **MET for tasks**; content lifecycle enforcement at the DB not evidenced | MEDIUM | **FIX** |
| DATA-023 | Vault secrets with agency and per-client scope | `db/0004`, `0041` | **MET** | — | **KEEP** |
| DATA-024 | RLS on every table; two explicit connection seams | 77 tables, all ENABLE + FORCE; `rls_connection` + `privileged_connection`; CI gate |  **MET** — re-verified: **every** RLS-enabled table also has FORCE (an earlier count of 76/77 was a regex artefact of double-spacing) | MEDIUM | **FIX** |

---

## 12 · MULTI-TENANCY, SCALE, ERRORS (P0)

| ID | Expected | Current | Gap | Sev | Action |
|---|---|---|---|---|---|
| MT-001 | Client isolation at the database | RLS, 195 policies | **MET** | — | **KEEP** |
| MT-003 | Credential isolation per client | Vault scoping | **MET** | — | **KEEP** |
| MT-004 | Per-client job concurrency caps | None | **NOT MET** | HIGH | **ADD** |
| MT-005 | Per-client spend caps + global daily stop | `client_budgets` + manual halt | **PARTIAL** — the free funnel escapes both | **CRITICAL** | **FIX** |
| MT-007 | One client's failure cannot corrupt another's data or workflow | RLS covers data. **Workflow is not covered** — one queue, no fairness, one poisoned job blocks a worker slot with no DLQ | **PARTIAL** | HIGH | **FIX** |
| MT-008 | Backups cover the database **and the artefact store** | `pg_dump` covers the DB only; audit artefacts live on the `aios_state` volume and inside the engine tree | **NOT MET** | HIGH | **ADD** |
| MT-009 | Documented, tested DR with stated RTO/RPO | Not found | **NOT MET** | HIGH | **ADD** |
| MT-013 | Browser-worker fleet separate from the API host | Playwright + Chromium are baked into the **same** backend image; the audit engine runs as a subprocess on the same host | **NOT MET** — a browser crash or memory spike takes the API with it | HIGH | **REFACTOR** |
| ERR-001 | Degrade, never crash | Universally applied | **MET — arguably over-applied** | See ERR-002 | — | **KEEP** the principle |
| ERR-002 | **Never fake success** — a job that could not do the work is failed or blocked | **This is where the doctrine breaks.** The publish cascade finishes a job as *complete* with `degraded=True` after publishing nothing; the free audit records `$0.00` for real spend; a keyless AI path degrades without a named hold | **NOT MET** — the most consequential single gap after AUTO-001 | **CRITICAL** | **FIX** |
| ERR-004 | Never offer an unverified artefact | Honest artifact flags shipped in `79d1036` | **MET** | — | **KEEP** |

---

## 13 · GAP ROLL-UP

| Verdict | P0 count | Share |
|---|---|---|
| **MET** | 43 | 34% |
| **PARTIAL** | 41 | 33% |
| **NOT MET** | 38 | 30% |
| **UNVERIFIED** | 4 | 3% |

### The 12 CRITICAL gaps, in dependency order

1. **AUTO-001** — restore the beat schedule. *Unblocks ADM-020, AUD refresh, CONT-scheduled-publish, AUTO-002, AUTO-023, ADM-037.*
2. **AUTO-012 + task retry** — dead-letter queue and per-task retry/backoff. *Without these, restoring the schedule turns silent manual failure into silent automatic failure at higher volume.*
3. **ERR-002** — stop faking success. Publish cascade must fail loudly; degraded must be a distinct terminal state, not "complete".
4. **AUD-002 / ADM-025 / ADM-026 / DATA-020** — the free audit must either genuinely spend zero, or record its real cost and pass the gate. One fix, four requirements.
5. **(unstated) user offboarding + SEC-016 revocation** — a departing person must lose access.
6. **CIT-008 / CIT-009 / CIT-010** — citation submission at 3 directories cannot meet a ~100-platform commitment. Needs an approach decision, not more selectors.
7. **CIT-014** — model the loaded cost before re-affirming the <10¢ commitment.
8. **CONT-029** — calibrate the QA gate or downgrade it to advisory. Do not ship a hard gate on an uncalibrated score.
9. **CONT-035** — auto-publish must return a live URL or an honest failure.
10. **MT-005** — the free funnel must sit behind the spend cap.
11. **SEC-011** — add a Content-Security-Policy to the application.
12. **AUTO-002 / D-17** — decide Policy Radar's v1 status. It is one line from working; shipping 3 of 4 advertised modules is a client-facing problem, not an engineering one.

### Requirements that are technically impossible or commercially unreasonable as written

Flagged per the brief's §22 instruction:

- **CIT-009 + CIT-010 + the <10¢ commitment, together.** Hand-verified form specs for ~100
  directories is a continuous maintenance burden (directory forms change without notice), and
  the loaded cost of maintaining them is not 10¢/unit. Either the platform target drops to the
  subset with real APIs/aggregators (Bing Places, Data Axle-class aggregators, the handful with
  documented writes), or the 10¢ figure must be restated as *marginal* cost with the loaded cost
  disclosed separately — which is what `DECISIONS_LOG.md` D-2 already gestures at. **Recommend:
  re-baseline with the client before building.**
- **AUD-001 vs AUD-002.** "Free audit = condensed AND zero-spend" is achievable; "free audit =
  comprehensive AND zero-spend" is not, because comprehensive requires Serper/Places. The build
  drifted to comprehensive without re-deciding. **Recommend: pick condensed+free.**
- **WEB2-007 across clients on a shared account** requires a cross-tenant content similarity
  index, which sits awkwardly against the RLS isolation model. Buildable, but it needs an
  explicit, documented exception to the isolation rule. **Flagging, not blocking.**
