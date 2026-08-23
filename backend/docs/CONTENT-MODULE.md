# Content module (Part 7 · Module 02)

A **content job** = a content type + topic pushed through an ~90%-automated
pipeline with a single HUMAN review gate (the "10%"). The pipeline researches the
SERP, drafts a ranking-grade long-form page, assembles JSON-LD, scores it against
a 14-dimension QA scorecard, and STOPS at the human gate — a lead then approves,
edits, or rejects; an approved job publishes to WordPress or renders PDF/Markdown.

Shapes mirror `frontend/lib/content.ts` (`ContentJob`): `code` is the PUBLIC
`CJ-####` badge (never a UUID); `client_name`/`color` are display SNAPSHOTS so the
internal `client_id` never leaks to the API. The 15-key response contract is
locked by `tests/test_contract_lock.py`.

## The pipeline (create → worker → review → publish)

```
POST /content/jobs  (publish_content)
   │  snapshot client name+color · resolve Auto→framework · resolve schema_type
   │  seed source_pack (client facts + WP config) · insert queued row (RLS path)
   └─ enqueue run_content_job(code) ─────────────────────────────────────────────┐
                                                                                  ▼
        execute_content_job  (workers/tasks/content.py — the pure core)   [WORKER]
          research → cluster → serp_format → fan_out → winnability → teardown
            → outline → draft → titles_meta → schema → images → assemble → qa
          advances  queued → drafting → needs_review   (STOPS at the gate; never
          auto-publishes) · attaches the QA scorecard · streams cost/words/stage

   POST /content/jobs/{code}/review  (LEAD: owner/admin/manager, RLS path)
     approve → needs_review → publishing  ── enqueue publish_content_job(code) ──┐
     edit    → needs_review → drafting                                           │
     reject  → needs_review → rejected                                           ▼
                                                     publish_content_job  [WORKER]
                                                       re-check the QA HARD GATE
                                                       WordPress (idempotent via
                                                       wp_post_id) or PDF/Markdown
                                                       → publishing → done
```

Rich retrieval (staff-only, NOT contract-locked):
`GET /content/jobs/{code}/{draft|keywords|qa|schema}` returns the server-only
pipeline columns (`draft_md` / `keyword_map` / `qa_score` / `json_ld`) a reviewer
needs. `GET /content/jobs/stats` returns the 4 board KPIs (in-pipeline,
awaiting-review, published-this-month, avg cost of priced jobs).

## The guard's 3-actor model (the load-bearing invariant)

The state machine **cannot live only in FastAPI** — any authenticated principal
could hit the DB directly with a leaked credential. It lives in the
`content_jobs_guard_update` BEFORE-UPDATE trigger (migration `0017_content.sql`),
the ONE gate that binds all three actor classes. `service_role` bypasses RLS
POLICIES but **not TRIGGERS** (invariant #3), so the trigger governs the worker too.

| Actor | Identity | Path | May do |
| --- | --- | --- | --- |
| **WORKER / system** | `service_role`, `auth.uid()` IS NULL | `privileged_connection` | `queued→drafting`, `drafting→needs_review`, `publishing→done`, any `→failed`, same-status streaming (cost/words/stage/draft). **Nothing else.** |
| **LEADS** (owner/admin/manager) | `current_app_role()` ∈ leads | `rls_connection` | the review exit `needs_review→publishing` (approve) / `→rejected` (reject) / `→drafting` (edit), plus any other legal edit. |
| **NON-LEAD staff** (the assignee) | `auth.uid() = assignee_id`, not a lead | `rls_connection` | **NOTHING** — not a status change, not a column edit. The pipeline + the leads own the whole lifecycle. |

Consequences the router honours:

- The review/edit endpoints (`approve→publishing`, `edit→drafting`,
  `reject→rejected`) and the PATCH run as a **LEAD on the RLS path** — never the
  worker path. The worker path could not perform a `needs_review→publishing`
  transition (it is illegal for the system branch).
- `approve` sets `needs_review→publishing` as the lead, THEN hands publishing off
  to the worker (`publishing→done`) via `publish_content_job`.
- Every human write uses optimistic `expect_status` (409 on a lost race); the DB
  trigger remains the real transition gate (defense in depth).

`tests/integration/test_content_flow.py` proves this boundary against local
Postgres via the direct authenticated-role probe (a leaked DB credential):
a non-lead's `needs_review→publishing`/`→done`/column-edit is REJECTED, a lead
CAN approve/reject/edit, the worker CAN do the system transitions (and an illegal
system jump is rejected), and a portal client is fully excluded.

## The QA score (ADVISORY — there is no automated publish gate)

> **Corrected 2026-08-23.** This section previously described a hard publish gate.
> It does not exist and did not exist at the audited commit. `PublishBlocked` is
> defined (`workers/tasks/content.py:382`) and caught twice (`:2129`, `:2371`) but
> **raised nowhere** — `grep -rn "raise PublishBlocked" app workers integrations`
> returns nothing, and the code says so at `:47`, `:2102` and `:2358`. WU-6 corrected
> three docstrings and missed this file and `CLAUDE.md`. Anyone reading the old text
> would reasonably believe an automated quality gate stood between a bad draft and a
> client's live site. **Nothing does.** Making one real is P0-4 / D-4.

The merged `content_qa` §11 scorecard scores 14 dimensions (0–100) and rolls them
up with a weight vector into a weighted total. The score's VERDICT is:

> **no single dimension < `MIN_DIMENSION_SCORE` (70) AND weighted total ≥
> `WEIGHTED_TOTAL_THRESHOLD` (85) AND no hard-gate dimension tripped.**

What actually happens today:

* The score IS computed and STORED on the `qa_score` column at `needs_review`
  (`workers/tasks/content.py:1052`), and is fetchable at `GET /content/jobs/{code}/qa`.
* At publish time `publish_content_job` reads it and **only logs it**
  (`content_publish_qa_advisory`, `:2110`), then publishes regardless. **A
  sub-threshold draft is published.**
* `qa_score` is NOT part of the 15-key `ContentJobResponse` the review endpoint
  returns, so **the approving lead is not shown the verdict and is never required to
  acknowledge it.** D-4 asks for "advisory **+ mandatory acknowledgement**"; only the
  advisory half exists.

**The only enforced quality boundary is the human review gate** — a lead must move
`needs_review → publishing`, and the DB trigger enforces that. `PublishBlocked` and
its two catch sites are deliberately KEPT as the seam a calibrated gate re-enables
through; the `acks_late` reasoning for catching rather than re-raising is still
correct and worth not re-deriving.

### Golden-set & calibration honesty (R4 → P7A-11)

The **threshold (≥85) and the weight vector are PROVISIONAL (R4)** — engineering
estimates, NOT yet validated against real ranking outcomes or a human SEO grade.
`tests/test_content_golden.py` is the LIVE golden-set eval harness: a curated set
of `{brief → expected-quality assertions}` run through the REAL Serper SERP + REAL
Claude (no DB/broker — an in-memory store + permissive cost gate), asserting the
provisional bar. It **auto-SKIPS unless `SERPER_API_KEY` + `ANTHROPIC_API_KEY` are
set** (keys are deferred), so it never fails the default gate today.

**Calibration is the P7A-11 milestone:** run the golden set WITH keys + have a
human SEO grade the drafts, then reconcile the weights + threshold. Until then, a
golden-set failure once keys land is a CALIBRATION SIGNAL, not necessarily a
regression.

## Key-gating & cost

The module composes `content_providers_from_settings`: the WRITER (Claude) is the
gate — a missing `ANTHROPIC_API_KEY` DEGRADES the whole module to `None`, and the
worker HOLDS the job at `drafting` with an honest $0 marker until keys land (never
a crash). Research (`SERPER_API_KEY`) and images (`IMAGE_GEN_API_KEY`) light up
per-key; WordPress app-passwords are per-site and live encrypted in the vault (not
settings) — the publish path reveals them per publish, degrading to artifact-only
when absent.

All content AI spend is **cost-gated** (dial features `content` for generation +
images, `content_research` inside the researcher). An R5 cost pre-check estimates
the full job at entry and DEFERS an over-budget job (no half-spend); a mid-pipeline
block DEGRADES (holds at `drafting`), it does not crash. Cost is streamed to the
`cost` column and logged through the Part-2 cost log.

## Files

- `app/routers/content.py` — the HTTP surface (list/stats/get/rich-retrieval,
  create+enqueue, review gate, limited PATCH) + the overridable enqueuer deps.
- `app/schemas/content.py` — the 15-key `ContentJobResponse` (contract-locked),
  `ContentJobCreate`/`ContentReviewRequest`/`ContentJobUpdate`, the `auto_framework`
  /`schema_for` server rules, and `compute_content_stats`.
- `app/db/content_repo.py` — `ContentRepo` over `content_jobs` (RLS-scoped).
- `workers/tasks/content.py` — the pipeline core `execute_content_job` +
  the QA-gated `publish_content_job` + the Celery tasks.
- `db/migrations/0017_content.sql` — the table, RLS policies, and the 3-actor
  `content_jobs_guard_update` trigger.
- `docs/CONTENT-DOCTRINE.md` — the copywriting/ranking doctrine the generator + QA
  scorecard implement.
