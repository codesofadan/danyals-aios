# Backend performance baseline

Measured baseline for the AIOS backend's RLS-backed read path, established while
closing the audit's "Performance & Scale" finding (per-request sync client,
unbounded list endpoints, no measured baseline). All numbers were taken on the
dev box against the live Supabase project (region `ap-southeast-1`, free tier;
this box is far from that region, so the Supabase round-trip dominates and its
tail is wide — treat absolute latency as environment-relative and the
before/after deltas as the signal).

Reproduce:
- Client-construction microbenchmark: see "Per-request client cost" below.
- Concurrency probe: `tests/perf/load_probe.py` (drives the real app in-process
  via `httpx.ASGITransport` with a real JWT; provisions + deletes one owner).
  `./.venv/Scripts/python -c "from dotenv import load_dotenv; load_dotenv('.env'); import asyncio, tests.perf.load_probe as p; asyncio.run(p.main())"`

## 1. Per-request client cost — FIXED (commit `b9b5c8d`)

Every RLS-backed request builds a fresh `client_for_user()` (it carries the
caller's JWT and must never be cached). Profiling found this construction cost
**~307 ms p50** — *larger than an actual Supabase round-trip* — because
`httpx.Client()` rebuilds an `SSLContext` from the certifi CA bundle on every
construction (~300 ms on Windows).

| | p50 | mean |
|---|---|---|
| `client_for_user()` — before (SSL ctx per client) | **307 ms** | 326 ms |
| `client_for_user()` — after (one shared SSL ctx) | **0.9 ms** | ~1 ms* |

\* first call builds the context once (~20 ms), amortized at process start.

**~330× faster construction.** The fix (share one `ssl.SSLContext` via
`SyncClientOptions.httpx_client`) keeps the client per-request and anon-key+JWT
scoped, so RLS is unchanged — proven by the RLS correctness matrix passing 6/6
live on the new client. At 4 vCPU, removing ~300 ms of pure CPU per request lifts
the construction-bound ceiling from ~13 req/s/core to effectively unbounded by
construction (the Supabase round-trip becomes the sole cost).

## 2. Supabase round-trip (the remaining dominant cost)

| `SELECT ... LIMIT 1` round-trip | p50 | p99 |
|---|---|---|
| cached admin client (query only) | **205 ms** | 1150 ms |

The wide p99 is the free-tier cross-region link. This is now the floor for any
single RLS read; the app adds negligible CPU on top.

## 3. End-to-end concurrency probe — `GET /api/v1/clients`

Measured (10 concurrent workers, 100 requests, dev box → free-tier Supabase in
ap-southeast-1):

| concurrency | requests | errors | p50 | p95 | p99 | throughput |
|---|---|---|---|---|---|---|
| 10 | 100 | 0 | 2481 ms | 4500 ms | 5301 ms | 3.4 req/s |

`GET /api/v1/clients` makes **~3 Supabase round-trips** per request (load the
caller's `users` row for auth, list clients, count sites), each over a
cross-region free-tier link with no connection keep-alive — so this measures the
round-trip-bound ceiling, not app CPU (which the §1 fix made negligible). Zero
errors under load. In production (app co-located with the Supabase region, ~1–20 ms
RTT and connection reuse) the same path is expected in the tens-of-ms range with
1–2 orders of magnitude more throughput; the follow-ups in §5 (connection pooling,
folding the auth `users` read into fewer trips) target exactly this.

## 4. Unbounded list endpoints — FIXED (pagination)

Every DB-backed list endpoint now takes `?limit=` (1–200, default 50) + `?offset=`
via a single `PageDep`, translated to a supabase-py `.range(offset, offset+limit-1)`
window, so **no handler can ask the database for an unbounded page**. Responses
stay bare JSON arrays (the frontend contract). The caps are enforced at the edge
(`limit=0` / `limit=201` → 422). Aggregation callers that genuinely need the full
set (`GET /audits/stats`, `GET /portal/dashboard`) deliberately call the repo
unbounded.

Paginated: `/clients`, `/clients/{id}/sites`, `/admin/users`, `/activity`,
`/cost/budgets`, `/cost/log`, `/audits`, `/tasks`, `/portal/audits`,
`/tiers/clients`. Static reference endpoints (`/tiers`, `/tiers/feature-areas`,
`/rbac/*`, `/cost/dial`) are in-code constants and need no DB paging.

## 5. Known follow-ups (measured, prioritized)

1. **Connection-pool reuse.** The per-request client still opens a new TLS
   connection (no keep-alive across requests), so each read pays a TLS handshake
   RTT. Sharing one pooled client safely needs the JWT applied per-HTTP-call
   rather than per-client — cleanest via an async PostgREST path over the shared
   `app.state.http_client`. Deferred (larger change; the ~300 ms CPU cost, the
   dominant local cost, is already removed).
2. **DB-side aggregation for `/audits/stats`.** It scans all audit rows in Python
   to compute KPIs; at scale move `count`/`avg` into SQL. Same for the
   `site_counts` / `_client_map` full scans behind `/clients` + `/cost/budgets`.
