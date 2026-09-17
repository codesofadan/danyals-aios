# 03 · Architecture

---

## 1. Style

**A modular monolith with detachable workers.**

One deployable API process, one job-worker process type, one browser-worker process type,
one frontend. Modules are enforced boundaries *inside* the codebase — separate packages
with explicit public interfaces — not separate services. This gives the isolation
benefits of services without the operational cost of a distributed system on a single
VPS, and it leaves every module extractable later if one genuinely needs its own
lifecycle.

**Why not microservices:** 50–100 clients on one VPS. Distributed transactions, service
discovery and cross-service tracing would cost more than they return, and v1's real
failures were correctness failures, not scaling failures.

**Why not a plain monolith:** v1 was one, and its modules reached into each other's
tables. The boundary rules in §5 are the fix.

---

## 2. Stack

| Layer | Choice | Why this, not the alternative |
|---|---|---|
| **API** | Python 3.12 · FastAPI · Pydantic v2 | Async, typed, OpenAPI for free. The domain is AI and data-provider orchestration, which lives in Python |
| **ORM / DB access** | SQLAlchemy 2.0 async + Alembic | Typed queries, real migration tooling. No raw SQL outside the repository layer |
| **Database** | PostgreSQL 16 | One store. RLS gives a database-enforced tenant boundary; `SKIP LOCKED` gives a durable queue; `jsonb` handles the semi-structured artefacts; `pgvector` handles embeddings |
| **Job engine** | **Postgres-backed durable queue** (own implementation, ~600 lines) | Exactly the property v1 lacked. One store means a job's state and its side-effect rows commit in the same transaction. Redis-backed queues lose jobs on a flush; Celery gave no idempotency contract; Temporal is the right answer at 10× this scale and the wrong answer on one VPS |
| **Cache / locks / rate limits** | Redis 7 | Ephemeral only. **Nothing durable lives in Redis.** Losing Redis must cost latency, never data |
| **AI runtime** | LangGraph (Python) · LangChain adapters only · LangSmith tracing | Checkpointed, resumable graph state matches durable jobs exactly. See `06-AI-STACK.md` |
| **Vector** | `pgvector` in the same Postgres | One store. No separate vector database for this data volume |
| **Browser automation** | Playwright (Python), separate worker pool | Design capture, audit rendering, liveness checks, screenshots |
| **Frontend** | Next.js 15 App Router · React 19 · TypeScript strict · TanStack Query · Tailwind · shadcn/ui | Server components for list surfaces, a typed client generated from OpenAPI, no hand-written fetch |
| **Extension** | Chrome MV3 · TypeScript · Vite | Thin actuator. All intelligence is backend-side |
| **Observability** | Sentry · OpenTelemetry · structured JSON logs · LangSmith | One correlation id spans request → job → provider → model call |
| **Deploy** | Docker Compose on one VPS, Caddy in front | Reproducible, revertible by image tag, no orchestrator to operate |

---

## 3. Runtime topology

```
                          Internet
                             │
                    ┌────────▼─────────┐
                    │      Caddy       │  TLS, HTTP/3, rate limit, static
                    └───┬──────────┬───┘
                        │          │
         ┌──────────────▼──┐   ┌───▼───────────────┐
         │  web (Next.js)  │   │   api (FastAPI)   │  N replicas
         │  SSR + RSC      │──►│   stateless       │
         └─────────────────┘   └───┬───────────┬───┘
                                   │           │
    ┌──────────────────────────────▼───┐   ┌───▼──────────────────┐
    │        PostgreSQL 16             │   │      Redis 7         │
    │  • tenant data (FORCE RLS)       │   │  • cache             │
    │  • job ledger (SKIP LOCKED)      │   │  • distributed locks │
    │  • vault (envelope-encrypted)    │   │  • rate-limit tokens │
    │  • cost ledger (append-only)     │   │  • ephemeral ONLY    │
    │  • pgvector embeddings           │   └──────────────────────┘
    │  • LangGraph checkpoints         │
    └──────▲───────────────────▲───────┘
           │                   │
   ┌───────┴────────┐  ┌───────┴──────────────┐
   │  job-worker    │  │  browser-worker      │
   │  pool (N)      │  │  pool (M) — Playwright│
   │  • pipelines   │  │  • design capture     │
   │  • providers   │  │  • audit render       │
   │  • LangGraph   │  │  • screenshots        │
   └───────┬────────┘  │  • liveness checks    │
           │           └───────────────────────┘
           │
   ┌───────▼─────────────────────────────────────┐
   │ External: Anthropic / agentrouter · DataForSEO ·
   │ serper.dev · Firecrawl · Google (Indexing,   │
   │ Places, GBP, OAuth) · WordPress REST ·       │
   │ 32 Web2/social APIs · CapMonster · proxies · │
   │ IMAP/SMTP · Sentry · LangSmith               │
   └──────────────────────────────────────────────┘

   Operator's Chrome ──► extension (MV3) ──► api  (scoped operator token)
```

**Placement rule:** `browser-worker` is configured by address, not by assumption. It runs
on the same host today; moving it to a second host must be a config change, never a code
change.

---

## 4. Repository layout

```
aios/
├─ CLAUDE.md                      # agent standing instructions
├─ AGENTS.md                      # working agreement
├─ docker-compose.yml             # full local stack, one command
├─ Makefile                       # every gate as a target
│
├─ backend/
│  ├─ pyproject.toml              # uv, ruff, mypy strict
│  ├─ alembic/                    # forward-only migrations
│  ├─ src/aios/
│  │  ├─ main.py                  # app factory only
│  │  ├─ config.py                # typed settings, one source
│  │  │
│  │  ├─ platform/                # ── primitives every module uses ──
│  │  │  ├─ db/                   # engine, session, base, RLS context
│  │  │  ├─ jobs/                 # the durable job engine
│  │  │  ├─ vault/                # envelope encryption
│  │  │  ├─ cost/                 # gate, ledger, dials
│  │  │  ├─ provenance/           # value + source + method + measured_at
│  │  │  ├─ rbac/                 # capabilities, policy evaluation
│  │  │  ├─ ai/                   # model router, graphs, tracing
│  │  │  ├─ providers/            # external seams (see §7)
│  │  │  ├─ events/               # domain events + outbox
│  │  │  ├─ obs/                  # logging, tracing, metrics
│  │  │  └─ errors.py             # the error taxonomy
│  │  │
│  │  ├─ modules/                 # ── one package per module ──
│  │  │  ├─ portal/
│  │  │  ├─ audit/
│  │  │  ├─ content/
│  │  │  ├─ citations/
│  │  │  ├─ web2/
│  │  │  ├─ policy/
│  │  │  ├─ tracking/
│  │  │  ├─ keywords/
│  │  │  ├─ indexing/
│  │  │  ├─ local/
│  │  │  ├─ reporting/
│  │  │  └─ billing/
│  │  │     ├─ api.py             # PUBLIC: what other modules may import
│  │  │     ├─ router.py          # HTTP surface
│  │  │     ├─ service.py         # use cases
│  │  │     ├─ repo.py            # the ONLY place SQL lives
│  │  │     ├─ models.py          # SQLAlchemy
│  │  │     ├─ schemas.py         # Pydantic
│  │  │     ├─ jobs.py            # job handlers
│  │  │     └─ graphs/            # LangGraph definitions
│  │  └─ workers/
│  │     ├─ job_worker.py
│  │     └─ browser_worker.py
│  └─ tests/
│     ├─ unit/ integration/ contract/ eval/ chaos/
│     └─ gates/                   # the seven CI gates as tests
│
├─ frontend/
│  ├─ app/                        # Next.js App Router
│  ├─ components/
│  ├─ lib/api/                    # GENERATED from OpenAPI — never hand-edited
│  └─ tests/
│
├─ extension/
│  ├─ src/{background,content,sidepanel,lib}/
│  └─ tests/
│
├─ wordpress-plugin/              # AIOS publisher companion plugin
├─ scripts/                       # gates, seeds, drills, one-off ops
└─ docs/                          # this pack, living
```

---

## 5. Module boundary rules

These are enforced by an import-linter check in CI, not by good intentions.

1. **A module may import from `platform/` freely.**
2. **A module may import another module only through its `api.py`.** Reaching into
   another module's `repo.py`, `models.py` or tables is a build failure.
3. **A module may never write another module's tables.** Cross-module writes go through
   that module's public service, or through a domain event.
4. **`platform/` may never import a module.** Dependencies point one way.
5. **SQL exists only in `repo.py`.** Services take and return domain objects.
6. **Routers contain no logic.** Parse, authorise, delegate, serialise.
7. Anything two modules need becomes a `platform/` primitive, not a shared import.

Cross-module communication that is not a synchronous read uses **domain events** with a
transactional outbox: the event row commits in the same transaction as the state change,
and a relay delivers it. `content.page.published` → indexing registers the URL, reporting
increments the rollup, milestones advance.

---

## 6. The job engine

This is the piece v1 did not have, and the reason most of its defects were possible.

### Contract

Every long-running or spending operation is a **job**, described by a row:

```
jobs(
  id, kind, client_id, idempotency_key UNIQUE,
  state,            -- queued|leased|running|succeeded|partial|failed|blocked|timed_out|dead
  payload jsonb, result jsonb, error jsonb,
  attempt, max_attempts,
  lease_owner, lease_expires_at,
  scheduled_for, started_at, finished_at,
  cost_estimated_cents, cost_actual_cents,
  parent_job_id, correlation_id,
  created_at, updated_at
)
```

### The eight guarantees

| # | Guarantee | Mechanism |
|---|---|---|
| 1 | **At-least-once execution** | `SELECT … FOR UPDATE SKIP LOCKED` with a lease and a heartbeat. A worker that dies has its lease expire and the job is re-picked |
| 2 | **Effectively-once side effects** | Every job carries an `idempotency_key` unique per `(kind, natural key)`. Every external side effect is recorded in a `side_effects` ledger keyed by that id before it is attempted, and checked before it is retried |
| 3 | **Atomic state + effect** | State changes and their outbox events commit in one Postgres transaction. There is no window where a page is published and the ledger does not know |
| 4 | **Bounded retry** | Exponential backoff with jitter, `max_attempts` per kind, and a distinction between retryable (transport, 429, 5xx) and terminal (401, 403, validation) failures |
| 5 | **Dead-letter with context** | A job exhausting retries lands in `state='dead'` with the full error chain, the last provider response, and a one-click requeue |
| 6 | **Honest terminal states** | `succeeded` · `partial` (some children failed) · `failed` (retryable exhausted) · `blocked` (a precondition is missing — no credentials, no capability) · `timed_out` · `dead`. **`succeeded` requires the effect to be confirmed**, not merely attempted |
| 7 | **Caps and fairness** | Per-client concurrency cap and per-provider token-bucket rate limit, both checked at lease time, so one client's 50-page run cannot starve the rest |
| 8 | **Resumability** | Fan-out jobs are parent/child. A parent's progress is the child ledger, so a restart resumes at the first incomplete child. AI pipelines additionally checkpoint their LangGraph state |

### Scheduling

A `schedules` table drives recurring work (policy sweep, rank runs, liveness checks,
report generation, token refresh). The scheduler is a job that enqueues jobs, so
scheduling inherits every guarantee above. **Schedules ship disabled** and are enabled
per-module once that module's job contract is proven by the chaos suite.

---

## 7. The provider seam

Every external dependency sits behind a protocol in `platform/providers/`.

```python
class KeywordProvider(Protocol):
    async def volumes(self, terms: list[str], geo: Geo) -> ProviderResult[list[KeywordVolume]]: ...

@dataclass(frozen=True)
class ProviderResult[T]:
    status: Literal["ok", "degraded"]
    data: T | None
    reason: DegradeReason | None     # enum — NOT a string
    cost_cents: int
    measured_at: datetime | None
```

**Rules:**
- A provider that is not configured returns `degraded` with `reason=NOT_CONFIGURED`. It
  **never** returns invented data. There is no `Fake*` provider outside `tests/`, and a CI
  gate asserts that no test double is importable from application code.
- Callers branch on the `reason` enum. Parsing a message string is a review rejection.
- Every provider call passes the cost gate first and commits actual cost after.
- Every provider has a documented note in `docs/provider-notes/` recording how it really
  behaves, which is rarely how its documentation says it behaves.

---

## 8. Cost gate

```
  caller ──► CostGate.check(module, client, estimate)
                 │
                 ├─ global halt on?          ──► BLOCKED(global_halt)
                 ├─ module dial off?         ──► BLOCKED(dial_off)
                 ├─ module dial by_hand?     ──► BLOCKED(needs_approval) → review queue
                 ├─ client month cap hit?    ──► BLOCKED(client_cap)
                 └─ ok ──► provider call ──► CostLedger.commit(actual)
```

The ledger is append-only, records estimate and actual, and carries `module`, `client_id`,
`job_id`, `provider`, `unit` and `quantity`. Loaded cost adds operator minutes at a
configured rate, so citation and campaign economics are reportable in both figures.

---

## 9. Provenance

A shared column group, not a per-module convention:

```
value, source (provider/url/human), method (measured|derived|declared|inferred|defaulted),
confidence, measured_at
```

The UI renders method and age wherever a number is shown. A `defaulted` or `inferred`
value is visually distinct from a measured one. **A number with no provenance cannot be
displayed** — the component throws in development and renders a "not measured" state in
production.

---

## 10. Error taxonomy

One hierarchy, in `platform/errors.py`. Every error is one of these; there is no bare
`Exception` raised in application code.

| Class | Meaning | Retryable | Surfaces as |
|---|---|---|---|
| `ValidationError` | The request is wrong | No | 422 |
| `AuthError` / `ForbiddenError` | Identity or capability | No | 401 / 403 |
| `NotConfiguredError` | A required credential or capability is absent | No | `blocked` |
| `CapabilityMissingError` | The target system cannot do this (no Elementor, REST blocked) | No | `blocked` |
| `ProviderTransportError` | Network, timeout, 5xx | Yes | retry |
| `ProviderRateLimitError` | 429, with `retry_after` | Yes | backoff |
| `ProviderContractError` | The response does not match what we parse | No | `dead` + alert |
| `CostBlockedError` | The gate refused | No | `blocked` |
| `ConcurrencyError` | Lease lost, optimistic conflict | Yes | retry |
| `TenantViolationError` | An access crossed a tenant boundary | No | 403 + **security alert** |

---

## 11. Frontend architecture

- **Server components by default.** Client components only where interaction demands it.
- **The API client is generated** from the OpenAPI schema into `lib/api/`. Hand-written
  `fetch` to the backend is a review rejection.
- **TanStack Query** for all client-side server state; no bespoke caching.
- **Every list is server-paginated**, searchable and sortable through the API, never
  through client-side filtering of a full fetch.
- **Every number displays its provenance** via a shared `<Measured>` component that takes
  the value and its provenance and refuses to render without both.
- **Degraded states are first-class UI**, designed, not an error toast.
- Design system: Tailwind tokens + shadcn/ui primitives; agency branding applied through
  CSS custom properties so a white-label pass later is a token swap.

---

## 12. Extension architecture

Thin by design. See [`modules/M04-citations.md`](modules/M04-citations.md).

```
  content script            service worker              backend
  ────────────              ──────────────              ───────
  observe DOM        ──►    collect digest       ──►    POST /citations/analyze
  (PII-free digest)         (scoped token)              LangGraph: map fields
                                                        ◄── fill plan + confidence
  apply fill plan    ◄──    dispatch plan
  (never submits)
  render review UI   ──►    side panel shows every value, flags low confidence
  human clicks submit ──►   capture proof ──► POST /citations/proof
```

The extension holds **no credentials and no client data at rest**, only a short-lived
token scoped to one client and one session. All intelligence — field mapping, account
creation strategy, verification — runs in the backend graph.

---

## 13. Performance targets

| Surface | Target |
|---|---|
| API read p95 | < 200 ms |
| API write p95 | < 400 ms |
| Dashboard first contentful paint | < 1.5 s |
| Free audit end-to-end | < 3 min |
| One content page, research → staged draft | < 4 min |
| 50-page fan-out | < 4 h wall clock at the default concurrency cap |
| Design capture per page | < 20 s |
| Citation form analysis (cache miss) | < 6 s; cache hit < 400 ms |
| Job pickup latency | < 2 s from enqueue |

Any synchronous HTTP path that can exceed 25 seconds must be a job with a polled status
endpoint, not a long request. v1's production incident — a 30-second proxy timeout
killing content research — was caused by breaking this rule.
