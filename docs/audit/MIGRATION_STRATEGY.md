# MIGRATION STRATEGY — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Companion:** `TARGET_ARCHITECTURE.md`, `ENGINEERING_MASTER_PLAN.md`

---

## 0. Strategy in one line

> **Strangle the job layer, swap the transports, delete the lies. Nothing is rewritten wholesale;
> one subsystem (citation submission) changes approach.**

The system is **live on `app.qanry.com`** and the owner has taken possession. Every migration
below is therefore designed to be **reversible**, **incremental**, and **safe to abandon
mid-way**. No step requires a big-bang cutover.

**Three sequencing rules, applied throughout:**

1. **Truth before automation.** Fix the things that report false success *before* restoring the
   schedule — otherwise you industrialise the lie.
2. **Retry before schedule.** Restore beat only *after* retry + DLQ exist, or you convert silent
   manual failure into silent automatic failure at higher volume and higher spend.
3. **Cost gate before volume.** Close the free-funnel spend hole before any acceptance run, or the
   50×10 bar is executed with no cost ceiling.

---

## 1. Migration table

### M1 · Job reliability contract

| | |
|---|---|
| **Current** | 39 tasks, zero retry, no DLQ, `beat_schedule = {}`, "never re-raise" doctrine |
| **Target** | Bounded jittered retry on transient errors; permanent errors fail fast; exhausted retries → DLQ + alert; four explicit terminal states |
| **Method** | **Strangler.** Add a `@aios_task` decorator wrapping `@celery_app.task` with the retry/DLQ/terminal-state contract. Migrate tasks **one at a time**, highest-value first (`run_audit`, `run_content_job`, `publish_content_job`, `citation_submit`). Both decorators coexist; nothing is renamed; task `name=` pins are untouched so routing survives |
| **Dependencies** | `job_failures` (DLQ) table; a `TransientProviderError` / `PermanentProviderError` split in `integrations/errors.py` |
| **Risk** | **Low.** Additive. A wrapped task behaves identically until it fails |
| **Rollback** | Revert the decorator on a single task. Per-task granularity means blast radius is one task |
| **Verify** | Failure-injection test per migrated task: provider 429 → retried; provider 400 → failed immediately; retries exhausted → DLQ row + alert |

### M2 · Restore the schedule

| | |
|---|---|
| **Current** | `celery_app.conf.beat_schedule = {}`; 11 entries preserved verbatim in `_BEAT_SCHEDULE_DISABLED` |
| **Target** | All entries live, each verified, each writing to `scheduled_job_runs` |
| **Method** | **Staged, one entry per deploy** — *not* a single-line restore of all eleven. Order: (1) `mark-past-due-invoices` (safest, zero spend), (2) `refresh-client-audits`, (3) `generate-monthly-reports`, (4) `dispatch-scheduled-content-publishes`, (5) `dispatch-context` + `reconcile-context-vectors`, (6) `refresh-local-ranks`, (7) `dispatch-rank-checks` + `rollup-rank-history`, (8) off-page sweep, (9) `generate-policy-daily` *(gated on decision D-17)*. Watch `scheduled_job_runs` + cost log for one full cycle before enabling the next |
| **Dependencies** | **M1 must be complete for the tasks in that entry.** M5 (cost) must be complete before any spending entry |
| **Risk** | **High if done at once** — eleven jobs firing simultaneously against providers, at volume, with no retry and no cost ceiling, is the worst possible first day. **Low if staged** |
| **Rollback** | Remove that one entry and redeploy beat. Beat holds no state beyond its schedule file |
| **Verify** | Each entry: fires on time · writes exactly one `scheduled_job_runs` row · is idempotent under a redelivered tick · spends what the cost log says |

### M3 · Queue split + browser worker

| | |
|---|---|
| **Current** | One default queue, `-c 4`; Playwright + Chromium + the audit venv baked into the **API** image |
| **Target** | Four queues (`sync`, `content`, `browser`, beat dispatchers); a separate `worker-browser` image; per-client in-flight caps |
| **Method** | **Parallel-run.** (a) Add queue declarations and `queue=` to task routes — tasks keep working on the default queue until routed. (b) Build `worker-browser` from a new Dockerfile stage; run it **alongside** the existing worker. (c) Move browser tasks to the `browser` queue one at a time. (d) Only once the browser queue is proven, strip Playwright/Chromium/audit-venv from the API image |
| **Dependencies** | M1 (so a task that lands on the wrong queue retries rather than vanishing) |
| **Risk** | **Medium.** The classic failure is a task routed to a queue no worker consumes — it sits invisibly. Mitigate by adding the consumer **before** the route, and by alerting on queue depth from day one |
| **Rollback** | Remove the `queue=` route; the task returns to default. Keep the fat API image until (d) |
| **Verify** | Queue-depth metric per queue non-zero and draining; an audit runs on `browser` while a GSC sync runs concurrently on `sync`; API p99 unaffected by a running audit |

### M4 · Artefacts to object storage

| | |
|---|---|
| **Current** | Audit artefacts on local disk inside the engine tree; `pg_dump` covers only the database |
| **Target** | Object storage (B2/S3) behind the **existing** `ArtifactStore` Protocol; backups cover DB **and** artefacts |
| **Method** | **Dual-write, then cut over.** (1) Implement `ObjectArtifactStore`. (2) Write to **both** local and object storage; read from local. (3) Backfill historical artefacts. (4) Flip reads to object storage, keep local writes as a fallback for one release. (5) Drop local writes |
| **Dependencies** | The `ArtifactStore` Protocol already exists — this is an implementation swap, not a new seam. B2 credentials already in use by `integrations/b2.py` |
| **Risk** | **Low-medium.** The real risk is a serving-path regression on client-facing reports. Dual-write means a failed read can fall back |
| **Rollback** | Flip reads back to local at any point in steps 2–4 |
| **Verify** | Every historical audit's PDF and HTML resolve from object storage; a report opens from a second host; a restore drill recovers DB **and** artefacts |

### M5 · Cost truthfulness (the free-audit hole)

| | |
|---|---|
| **Current** | Public audit runs `--mode auto` with paid providers **on**, bypasses the cost gate entirely, and commits `0.0` |
| **Target** | Either (a) genuinely zero-spend condensed free audit, or (b) metered comprehensive audit behind its own dial and budget with real cost recorded |
| **Method** | **Decision first, then a small code change.** Recommended: **(a)** — it satisfies `AUD-001` *and* `AUD-002` as written and removes the denial-of-wallet vector outright. Implementation: pass `--mode free` on the public path; add a public-funnel dial + daily cap; replace `_safe_record_cost(..., 0.0)` with the runtime-computed cost; make the IP rate limiter fail **closed** |
| **Dependencies** | An owner decision on free-audit shape (see `REQUIREMENT_GAP_ANALYSIS.md §13`) |
| **Risk** | **Low technically. Commercial risk if (a):** the free report becomes thinner, which is a lead-magnet quality question, not an engineering one |
| **Rollback** | Single-flag revert |
| **Verify** | Negative test: with the spend halt armed, `POST /public/audits` is refused, not run. Cost log shows a non-zero figure for any metered run |

### M6 · Failure visibility (stop faking success)

| | |
|---|---|
| **Current** | The four-way WP publish cascade swallows every exception and completes as `degraded=True`; AI degrades without a named hold; `keyword-research` blocks silently |
| **Target** | `completed` · `degraded` · `blocked` · `failed` as distinct terminal states; **`degraded` never renders as success** |
| **Method** | **Cheap and high-return, do early.** (1) Add the state enum + a `degraded_reason`. (2) Replace each `except: pass` with an explicit state write. (3) Update the UI so `degraded` renders as a warning with the reason, not a tick. (4) Add the `ai_unavailable` state |
| **Dependencies** | None. This is independent of M1–M5 and should run in parallel |
| **Risk** | **Very low technically.** The **social** risk is real: boards that looked green will go amber. That is the point, and the owner should be told before it happens |
| **Rollback** | Not desirable, but the state column is additive and the UI change is revertible |
| **Verify** | Force every publish stage to fail: the job ends `degraded` with a reason, the UI shows it as not-published, and no live URL is claimed |

### M7 · Transaction seam

| | |
|---|---|
| **Current** | `rls_connection()` = one transaction per repo call; client creation is three non-atomic writes with two `except: pass` |
| **Target** | `unit_of_work(user_id)` yielding one cursor several repos share |
| **Method** | **Additive.** Add the context manager; give repo methods an optional `cur` parameter defaulting to `None` (open their own as today). Migrate only the composite operations: client creation, upsell reorder, notification prefs, grants update |
| **Dependencies** | None |
| **Risk** | **Low.** Existing call sites are unchanged by construction |
| **Rollback** | Per-call-site |
| **Verify** | Kill the process between `insert_client` and `upsert_business_profile` (fault injection) — no partial client survives |

### M8 · Identity lifecycle (offboarding + revocation)

| | |
|---|---|
| **Current** | No disabled state, no deactivate endpoint, `login()` never checks `status`, 7-day irrevocable token |
| **Target** | `suspended` state enforced at login **and** every request; suspend/reactivate endpoints; `jti` + Redis denylist; shorter TTL + refresh route |
| **Method** | **Sequenced, because order matters.** (1) Add `suspended` to the enum (`ALTER TYPE ... ADD VALUE`, non-breaking). (2) Enforce it in `login()` and `get_current_user` — **suspension works from here, even before revocation**. (3) Add the endpoints + UI. (4) Add `jti` to newly minted tokens; verifier treats a missing `jti` as valid (backwards compatible) for one TTL window. (5) Add the denylist and wire suspend/password-change/logout to it. (6) After one full 7-day window, require `jti`. (7) Shorten TTL and add refresh |
| **Dependencies** | Redis (present) |
| **Risk** | **Medium at step 6** — requiring `jti` before every legacy token has expired logs everyone out. The 7-day wait is what makes it safe |
| **Rollback** | Each step independently revertible; step 6 is the only one-way door and it is time-gated |
| **Verify** | A suspended user cannot log in **and** their existing token is rejected on the next request |

### M9 · Migration-file hygiene

| | |
|---|---|
| **Current** | Two `0070`, two `0072`, `0052` missing; applied in **lexical** order |
| **Target** | Unique ordinals; a CI check enforcing it |
| **Method** | **Rename forward, never renumber applied files.** The `deploy.schema_migrations` ledger keys on **filename**, so renaming an applied file makes it re-apply. Instead: leave the existing four files alone (they have applied everywhere and are independent), and add a CI check that **rejects any new duplicate ordinal**. Document the two known collisions in `db/migrations/README.md` |
| **Dependencies** | None |
| **Risk** | **High if done naively** (renaming applied files causes re-application against a live database); **zero** with the forward-only approach |
| **Rollback** | n/a |
| **Verify** | `db/ci/verify_fresh_apply.py` still passes on a scratch database; the new ordinal check fails a deliberately duplicated file |

### M10 · Schema additions

| | |
|---|---|
| **Current** | No `locations`, no first-class Web 2.0 accounts, no `content_versions`, no `site_capabilities`, no DLQ table, 15 unindexed FK columns |
| **Target** | All present |
| **Method** | **Expand → migrate → contract.** For `locations`: (1) create the table; (2) backfill one location per existing client from its current business profile; (3) add a nullable `location_id` to `business_profiles`/`citations`; (4) dual-read (fall back to client-level) for one release; (5) make it required. Indexes ship as `CREATE INDEX CONCURRENTLY` |
| **Dependencies** | M9's ordinal check |
| **Risk** | **Low** for additive tables and concurrent indexes. **Medium** for the `locations` backfill — a multi-location client that has been modelled as one client will need manual splitting |
| **Rollback** | Additive tables can be left unused; nullable columns are harmless |
| **Verify** | Every existing client has exactly one location after backfill; every existing citation resolves through it |

### M11 · WordPress publish redesign

| | |
|---|---|
| **Current** | Four-way silent cascade; no capability discovery; no post-publish verification; no revert; no SEO-plugin field population |
| **Target** | Capability discovery picks **one** transport explicitly; publish succeeds or fails visibly; post-publish verification; versioned with revert |
| **Method** | **Feature-flag per client.** (1) Build capability discovery as a **read-only** probe, run it against every connected site, store results — **no behaviour change yet**. (2) Compare each discovered capability against what the cascade actually chose (this validates the probe against reality). (3) Add `publish_v2` behind a per-client flag. (4) Enable for one internal test site, then one real client, then all. (5) Remove the cascade |
| **Dependencies** | M6 (explicit states), M10 (`site_capabilities`, `content_versions`) |
| **Risk** | **Medium** — this touches live client sites. The read-only probe first, and the compare-before-switch step, are what make it safe |
| **Rollback** | Flip the per-client flag back to the cascade |
| **Verify** | On a disposable WordPress+Elementor install: publish → page renders → schema validates → images load → **page opens editable in Elementor** → revert restores prior state |

### M12 · Citation approach change

| | |
|---|---|
| **Current** | 3 form specs / 151 `bot_fillable` directories; empty signup specs; two unconfirmed APIs; marginal-only cost model |
| **Target** | Tiered strategy (documented APIs → aggregators → browser as the exception) with a first-class human-handoff queue, proof per unit, and a **loaded** cost model |
| **Method** | **Commercial decision first — this is the one place engineering must wait.** (1) Build the loaded cost model against the real catalogue (`CIT-014`). (2) Present the honest platform/cost curve to the client and re-baseline the ~100-platform and <10¢ commitments. (3) Verify the two API routes (Bing Places, Foursquare) or drop them. (4) Build the human-handoff queue — a paused, pre-filled browser profile an operator finishes — as a **designed state**, not a failure. (5) Add spec health-checking so a broken selector is detected before a campaign, not during. (6) Only then extend browser coverage, prioritised by the cost model |
| **Dependencies** | M10 (`locations`), M3 (browser queue), and an **owner decision** |
| **Risk** | **High commercially, low technically.** The technical work is well understood; the risk is committing to a number that cannot be honoured |
| **Rollback** | The existing 3-directory path keeps working throughout |
| **Verify** | The owner's bar — **50 citations across 10 businesses** — completed with a live URL **and screenshot** per unit and a **loaded** cost per unit inside the agreed ceiling |

### M13 · Web 2.0 safety layer

| | |
|---|---|
| **Current** | 55 working publishers; no pacing, no similarity gate, no account cap, no account entity |
| **Target** | Accounts as entities with health and caps; jittered human-paced posting; cross-property similarity gate |
| **Method** | **Additive, gates default-closed.** (1) Add the account entity and backfill from vault entries. (2) Add the similarity gate in **report-only** mode — measure, do not block, for two weeks. (3) Calibrate the threshold on real data. (4) Enable blocking. (5) Add pacing + jitter once beat is restored (M2) |
| **Dependencies** | M2 (pacing needs a scheduler), M10 |
| **Risk** | **Low.** Report-only first means no campaign is blocked on an uncalibrated threshold — the mistake already made with the content QA gate |
| **Rollback** | Gates revert to report-only |
| **Verify** | Two properties for the same client on the same platform never publish within the pacing window; a near-duplicate is blocked; an account at its property cap is skipped |

### M14 · Frontend cleanup + CI

| | |
|---|---|
| **Current** | Dead demo store mounted at the root seeding plaintext passwords into localStorage; mock vault keys; hardcoded prices; no CI; no total counts |
| **Target** | Mocks deleted; CI blocking on typecheck + build + Playwright smoke; cursor pagination with totals |
| **Method** | (1) Add `frontend-ci.yml` running `tsc --noEmit` + `next build` — **both already pass**, so this is free and locks in current health. (2) Delete `lib/store.tsx`, the `lib/data.ts` seed arrays, `lib/vault.ts` mock keys, the `lib/cost.ts` prices — all verified unreferenced. (3) Remove the `AiosStoreProvider` mount from `layout.tsx`. (4) Add Playwright smoke per portal. (5) Add totals + cursor pagination endpoint-by-endpoint, UI following |
| **Dependencies** | None. Start immediately |
| **Risk** | **Very low** — the deletions are of verified-unreferenced code, and CI proves it |
| **Rollback** | Git revert |
| **Verify** | Build stays green; no `localStorage` key is written on first load except the auth token |

### M15 · Observability

| | |
|---|---|
| **Current** | Three HTTP metrics; Sentry optional with tracing off; no job visibility |
| **Target** | Per-task metrics, queue depth, DLQ depth, cost-per-feature-per-client, an operator page, alerts |
| **Method** | **Do this early — it is what makes every other migration verifiable.** (1) Add Celery signal handlers emitting task duration/failure/retry. (2) Add queue-depth and DLQ-depth gauges. (3) Add a cost-committed counter. (4) Enable Sentry tracing in production. (5) Build the operator page on `scheduled_job_runs` + DLQ + cost log — most of the data already exists |
| **Dependencies** | M1 for DLQ depth |
| **Risk** | **Very low.** Additive |
| **Rollback** | n/a |
| **Verify** | Every migration above can be watched on a dashboard rather than inferred from logs |

---

## 2. Dependency graph

```
M14 frontend cleanup + CI ──┐  (independent, start day 1)
M15 observability ──────────┤  (independent, start day 1 — makes everything else verifiable)
M6  failure visibility ─────┤  (independent, start day 1 — cheapest, highest perceived return)
M9  migration hygiene ──────┘  (independent, trivial)

M1 job contract (retry + DLQ)
      │
      ├──► M2 restore beat  ◄──── M5 cost truthfulness  (MUST precede any spending entry)
      │         │
      │         └──► M13 web2 safety (pacing needs a scheduler)
      │
      └──► M3 queue split + browser worker
                  │
                  └──► M4 artefacts to object storage

M7 transaction seam ──► M10 schema additions ──┬──► M11 wordpress redesign
                                                └──► M12 citations  ◄── OWNER DECISION
M8 identity lifecycle  (independent, sequenced internally)
```

**The critical path is M1 → M2.** Everything the product promises about running on its own sits
behind it, and M5 gates the spending half of it.

---

## 3. Global rollback posture

| Level | Mechanism |
|---|---|
| **Code** | Every migration is additive or feature-flagged. No step deletes a working path before its replacement is proven |
| **Schema** | Expand → migrate → contract. New tables and nullable columns only; `CREATE INDEX CONCURRENTLY`; **no applied migration file is ever renamed or renumbered** (the ledger keys on filename) |
| **Jobs** | Per-task decorator migration; per-entry beat restore. Blast radius is one task or one schedule entry |
| **Publishing** | Per-client feature flag; the cascade stays until v2 is proven per client |
| **Data** | Nightly backups **restore-drilled before** M10 and M11 begin — not after |
| **The one-way door** | M8 step 6 (requiring `jti`). Time-gated behind a full 7-day token window |

---

## 4. What must not be done

| Anti-pattern | Why |
|---|---|
| **Restoring all eleven beat entries at once** | Eleven jobs firing against providers, at volume, with no retry and no cost ceiling. This is how a recovery becomes an incident |
| **Restoring beat before M1 and M5** | Converts silent manual failure into silent automatic failure, and adds uncapped spend |
| **Renumbering the duplicate migration files** | The ledger keys on filename; renaming an applied file makes it re-apply against a live database |
| **Writing 148 more citation form specs** | It does not solve the maintenance model, and it commits the budget before the loaded cost is known |
| **Enabling the Web 2.0 similarity gate at an uncalibrated threshold** | Exactly the mistake already made with the content QA gate. Report-only first |
| **Rewriting auth, RLS, the repos or the audit engine** | All four are GREEN. A rewrite consumes the recovery budget reproducing correct work |
| **Deleting the WordPress cascade before capability discovery is validated against reality** | The cascade is ugly, but it encodes real knowledge about which hosts need which transport. Compare before switching |
