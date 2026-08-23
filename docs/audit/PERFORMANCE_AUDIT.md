# PERFORMANCE AUDIT — AIOS (Daniel Project)

**Audit date:** 2026-08-23 · **Commit:** `79d1036`
**Target scale (per `DECISIONS_LOG.md` D-3):** 50–100 clients with headroom architecture.

> **Measurement limitation.** No load test was run — the backend could not be executed in this
> environment (see `REPOSITORY_ARCHITECTURE.md` preamble). The frontend **was** built and measured.
> Every backend number below is a **structural** finding (what the architecture forces), not a
> benchmark. The repository does contain a real probe (`backend/tests/perf/load_probe.py`) that
> measures p50/p99/throughput on `GET /api/v1/clients` against local Postgres — it should be run
> before any of this is treated as settled.

---

## 0. Verdict

**The frontend is fast and small. The backend's request path is structurally sound. The problems
are all in the job layer and in three specific request-path shapes.**

Nothing here suggests the system will fall over at 50–100 clients on the read path. It will fall
over on **concurrency fairness** (one client's bulk run starves everyone), on **the audit
engine's host coupling**, and on **two synchronous AI endpoints** that hold one of only two
uvicorn workers for a minute at a time.

---

## 1. Frontend — measured

`npm ci && npx tsc --noEmit && npm run build` all completed successfully.

| Metric | Value | Verdict |
|---|---|---|
| TypeScript typecheck | **clean** (0 errors) | Good |
| Production build | **succeeds** | Good |
| Shared first-load JS | **103 kB** | Good |
| Largest route (`/admin/content`) | 18.1 kB route + **148 kB** first load | Good |
| Smallest portal route | ~105 kB first load | Good |
| Route rendering | **30 of 31 routes statically prerendered**; only `/team/tools/[slug]` is dynamic | See §1.1 |
| Fonts | Self-hosted variable woff2 via `next/font/local` — compiled into the build, no runtime fetch | Good |
| Icons | Material Symbols pulled from `fonts.googleapis.com` at runtime with `display=block` | See §1.2 |
| Components | 136 `.tsx`, largest 669 LOC (`ContentWizard`) | Acceptable |
| Excessive DOM | No virtualisation anywhere; every list renders in full, capped only by the API's `limit≤200` | See §1.3 |

### 1.1 Every screen is a client-side waterfall

All data arrives after hydration through TanStack Query. There is no server-side fetching, no RSC
data layer, no streaming. The user sees: HTML → JS parse → hydrate → fetch → render. On the admin
dashboard that is several parallel fetches (`command-center` aggregates six repos server-side,
which helps), but on most screens it is a visible empty-then-populate.

`isLoading` appears in 41 files and `isError` in 41 — so states are handled — but **`Skeleton`
appears in 0 files**. Loading is a spinner or nothing, not a shaped placeholder.

**Impact at target scale:** cosmetic, not structural. Acceptable for v1; worth revisiting.

### 1.2 A third-party font blocks icon rendering

`app/layout.tsx:48-52` loads Material Symbols from Google with `display=block`, which **hides the
glyph until the font loads**. On a slow connection every icon in the product is invisible until
that request completes, and if `fonts.googleapis.com` is unreachable they never appear. The team
already solved exactly this problem for the body font by self-hosting it.

**Fix:** self-host the icon subset, or switch to `display=swap` with a text fallback. Low effort.

### 1.3 No list virtualisation and no total count

`app/core/pagination.py` hard-caps `limit ≤ 200` at the edge — good, no handler can ask for an
unbounded page. But:

- No endpoint returns a **total count**, so no UI can show "1–50 of 1,240" or render a page
  control.
- No cursor pagination, so deep offsets degrade linearly.
- No bulk selection.

This is `ADM-039` ("server-side pagination, search and bulk selection on every list; usable with
500 clients and 10,000 jobs") and it is **not met**. At 100 clients the current shape is
survivable; at the stated 10,000-jobs bar it is not.

---

## 2. Backend request path — structural

### 2.1 What is right

- **Sync repos are offloaded correctly.** Every psycopg call runs under `asyncio.to_thread`, so
  blocking SQL never occupies the event loop.
- **The pool is sized to match.** `_MAX_POOL_SIZE = min(32, cpu+4)` deliberately mirrors CPython's
  default `ThreadPoolExecutor` size, so a burst of concurrent RLS requests cannot starve on
  connections. This is a considered decision, not an accident.
- **SSRF validation is done off the event loop** because `getaddrinfo` blocks — an easy thing to
  get wrong, and it was got right.
- **Payloads are bounded** by the `limit ≤ 200` cap.

### 2.2 A connection and a transaction per repo call — **P1**

`rls_connection()` opens a pooled connection **and an explicit transaction**, sets the identity
GUC, yields, and commits on exit. One repo method = one round trip *plus* transaction overhead.

A handler that calls three repo methods does three checkouts, three `set_config` statements and
three commits. `GET /clients` alone does two (`list_clients` + `site_counts`).

At 50–100 clients this is fine. It is listed because it is the same root cause as the atomicity
defect in `FORENSIC_AUDIT.md §3.3`, so one fix addresses both.

### 2.3 N+1 on the dashboard's own endpoint — **P2**

`app/routers/command_center.py:39-50` — `_resolve_assignees` loops over distinct task assignees
calling `tasks_repo.get_user(uid)`, each a separate connection + transaction. With 20 staff that
is 20 round trips to render one dashboard.

Same shape, lower traffic: `POST /upsells/reorder` (one `UPDATE` per id) and
`PUT /settings/notifications` (one upsert per pref).

**Fix:** a single `WHERE id = ANY(%s)` batch read.

### 2.4 Fifteen foreign-key columns have no index — **P2**

Parsed across all 80 migrations: 139 indexes exist, 110 FK references, and these FK columns carry
no index anywhere in the schema:

```
actor_id · applied_by · audit_id · created_by · decided_by · design_ir_id
dismissed_by · granted_by · import_run_id · list_id · owner_user_id
requested_by · site_id · source_audit_id · uploaded_by
```

Postgres does **not** auto-index the referencing side of a foreign key. Two consequences:

1. **Deleting a parent row requires a sequential scan of the child table** to enforce the
   constraint. `DELETE /clients/{id}` and `DELETE /sites/{id}` are exactly this shape.
2. Any filter on these columns (e.g. "audits for this site", "tasks I created") scans.

Most of these are low-cardinality audit/attribution columns where the cost is currently small.
`site_id` and `audit_id` are not — those are hot join keys.

**Fix:** add indexes on `site_id`, `audit_id`, `import_run_id`, `list_id`, `design_ir_id`,
`source_audit_id` first; the `*_by` attribution columns second.

### 2.5 Two synchronous AI endpoints hold a worker for ~a minute — **P1**

| Endpoint | Duration | Evidence |
|---|---|---|
| `POST /content/research` | **40–60 s** | `frontend/next.config.mjs` raises `proxyTimeout` to **180,000 ms** specifically for it |
| `POST /content/site-design` | long (Playwright + Claude) | `app/services/site_design.py` |

`api` runs `uvicorn --workers 2`. Each of these requests occupies one of two workers for its full
duration. Two concurrent research calls make the entire API unresponsive to everything else.
`infra/deploy/nginx.conf` further sets `proxy_read_timeout 300s`, so the edge will wait five
minutes rather than shed load.

**Fix:** convert both to Celery jobs with a polled status — the pattern the rest of the system
already uses. Then drop `proxyTimeout` and `proxy_read_timeout` back to sane values.

---

## 3. Job layer — the real scalability risk

### 3.1 One queue, no fairness, no per-client cap — **P0**

- `workers/celery_app.py` registers 39 tasks on the **single default queue**. No routing, no
  priority lanes.
- `worker` runs `--concurrency=4`.
- `task_time_limit=1800` (30 min) with `visibility_timeout=3600`.

So a 30-minute comprehensive audit and a 2-second GSC sync compete for the same four slots. One
client dispatching a 50-page bulk content run fills the queue and **every other client waits**.

`MT-004` (per-client job concurrency caps) and `AUTO-015` are **not met**. At 50–100 clients this
is the failure that will actually be experienced.

**Fix:** separate queues by duration class (`audits`, `content`, `sync`, `offpage`) with
dedicated worker pools; add a per-client in-flight cap enforced at dispatch.

### 3.2 The `visibility_timeout` invariant is a comment, not an assertion — **P1**

`celery_app.py:136-141` states the invariant correctly:

> *with `task_acks_late=True` on a Redis broker, `visibility_timeout` MUST be ≥ the longest hard
> `task_time_limit`. Otherwise a job that runs longer than the visibility window is re-delivered
> to a SECOND worker and RUNS TWICE (double API spend).*

Currently satisfied (3600 ≥ 1800). It is enforced by nothing. The next person who raises
`task_time_limit` for a long audit breaks it silently, and the symptom is **duplicated paid
provider spend** — the hardest class of bug to notice. `AUTO-011` requires this asserted at boot.

**Fix:** a one-line boot assertion in `validate_settings`.

### 3.3 No retry means no load shedding

With zero retry/backoff on any task (`FORENSIC_AUDIT.md §3.1`), a provider rate-limiting the
system produces permanent job failures rather than deferred success. Under load this converts a
throughput problem into a correctness problem.

### 3.4 The audit engine pins audits to one host — **P0 for scale**

Each audit forks a subprocess under a second Python interpreter, drives headless Chromium for PDF
rendering, and writes artefacts to the **local filesystem** inside the engine's own tree
(`<engine_dir>/data/audits/<slug>/<uuid>/`). Playwright and Chromium are baked into the **same
image as the API**.

Consequences at scale:

- **Audits cannot be distributed.** A second worker host cannot serve an artefact the first host
  produced.
- **Memory contention.** Chromium spikes share a container with uvicorn; `MT-013` (browser fleet
  separate from the API host) is **not met**.
- **Artefacts are not backed up.** `pg_dump` covers the database; the `aios_state` volume is not
  in backup scope (`MT-008`).
- **Concurrency is uncontrolled.** Nothing limits how many Chromium processes run at once.

**Fix (staged):** (1) move artefact writes to object storage behind the existing `ArtifactStore`
Protocol — the seam already exists; (2) split browser work onto its own worker image and queue;
(3) cap concurrent engine subprocesses.

---

## 4. Caching

| Cache | Present | Note |
|---|---|---|
| Cost-gate result cache (Redis) | **Yes** — a cache hit costs 0 and is logged as cached | Well designed |
| Rate-limit counters (Redis) | **Yes** — fixed window | Fails open |
| HTTP response cache | **No** | Every dashboard load re-queries |
| Query result cache | **No** | — |
| Audit artefact CDN/edge cache | **No** | Reports are served through the API from local disk |
| Frontend client cache | **Yes** — TanStack Query defaults | Staleness settings not audited |

`PERF-*` requirements around caching are largely unmet, but at 50–100 clients the read volume
does not justify a cache layer. **Recommendation: do not add caching yet.** Add the total-count
and cursor pagination first; measure with `load_probe.py`; then decide.

---

## 5. Findings, ranked by risk at 50–100 clients

| # | Finding | Severity | Fix effort |
|---|---|---|---|
| P-1 | One Celery queue, no per-client concurrency cap — one client starves all others | **P0** | Medium |
| P-2 | Audit engine pins audits to one host; artefacts on local disk, unbacked-up; browser shares the API image | **P0** | Large |
| P-3 | Two synchronous AI endpoints hold one of two uvicorn workers for 40–60 s | **P1** | Medium |
| P-4 | `visibility_timeout ≥ task_time_limit` invariant unasserted — silent double spend when broken | **P1** | Trivial |
| P-5 | No retry/backoff — provider throttling becomes permanent failure | **P1** | Small |
| P-6 | No total count, no cursor pagination, no bulk selection (`ADM-039`) | **P1** | Medium |
| P-7 | 15 FK columns unindexed; parent deletes sequential-scan children | **P2** | Trivial |
| P-8 | N+1 in `command_center`, `upsells/reorder`, `settings/notifications` | **P2** | Trivial |
| P-9 | Connection + transaction per repo call | **P2** | Medium (same fix as atomicity) |
| P-10 | Icon font `display=block` from a third-party host blocks all icon rendering | **P2** | Trivial |
| P-11 | No list virtualisation | **P3** | Medium |
| P-12 | No skeleton loading states | **P3** | Small |

**The two that matter for the stated target are P-1 and P-2.** Everything else is either trivial
to fix or does not bind at 100 clients.

---

## 6. What to measure before acting

The repository already contains the right instrument. Before any performance work:

1. Run `backend/tests/perf/load_probe.py` against a seeded local Postgres to get a baseline p50/p99
   on the RLS read path.
2. Add the missing worker/queue metrics (`PERFORMANCE` has no observability today — see
   `TESTING_AUDIT.md §6` and `FORENSIC_AUDIT.md`): queue depth, task duration by name, task
   failure rate, in-flight subprocess count.
3. Only then tune. The current metric surface — three HTTP counters — cannot tell you whether a
   slow dashboard is the API, the database, or a worker holding a connection.
