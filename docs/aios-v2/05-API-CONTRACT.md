# 05 · API Contract

One REST API under `/api/v1`. FastAPI generates the OpenAPI schema; the frontend client
and the extension client are **generated from it**. A hand-written request to the backend
is a review rejection.

---

## 1. Principles

1. **Resources, not RPC.** `POST /clients/{id}/audits` — not `/runAudit`. The exceptions
   are explicit actions on a resource: `POST /content/pages/{id}:publish`.
2. **Long work is a job, never a long request.** Any operation that can exceed 25 seconds
   returns `202 Accepted` with a job id and a poll URL. No exceptions — this rule is the
   fix for v1's 30-second proxy timeout killing content research in production.
3. **Every mutation is idempotent** through an `Idempotency-Key` header.
4. **Every response carries provenance** where it carries a measurement.
5. **Errors are typed**, machine-branchable, and never leak internals.
6. **The contract is versioned**; a breaking change means `/api/v2`, not a silent shape
   change. Additive changes are always safe to make.

---

## 2. Authentication

| Principal | Mechanism | Lifetime |
|---|---|---|
| Staff / owner (browser) | Access JWT in memory + refresh token in an `HttpOnly`, `Secure`, `SameSite=Strict` cookie, rotated on use | Access 15 min · refresh 14 days |
| Client portal user | Same, with `scope=client` and a bound `client_id` | Same |
| Extension operator | `operator_token` — opaque, scoped to one `client_id`, one capability set, one session | 8 hours, revocable |
| Public (free audit) | None; `scope=public` with strict rate limits | — |
| Internal worker | Not applicable — workers use a database session, never the HTTP API | — |

Authorisation is by **capability string**, never by role comparison in a handler:

```python
@router.post("/clients/{client_id}/citations/submissions")
async def submit(_: Annotated[User, Requires("citations:submit")], ...):
```

Capabilities are granted to roles in one table and resolved once per request. A handler
that checks `if user.role == "admin"` fails review.

---

## 3. Conventions

### Request
```
GET  /api/v1/clients?q=&status=&page=1&page_size=50&sort=-created_at
Authorization: Bearer <access>
X-Correlation-Id: <uuid>          # echoed through jobs, providers and logs
Idempotency-Key: <uuid>           # required on POST/PATCH/DELETE that cause an effect
```

### Collection response
```json
{
  "items": [ ... ],
  "page": 1, "page_size": 50, "total": 1284,
  "next": "/api/v1/clients?page=2&page_size=50"
}
```
Every collection is server-paginated. `page_size` max 200. There is no unbounded list
endpoint anywhere in the API.

### Measured value
```json
{
  "value": 14,
  "provenance": {
    "method": "measured",
    "source_kind": "provider",
    "source_ref": "dataforseo:serp/organic",
    "confidence": 1.0,
    "measured_at": "2026-09-14T06:11:03Z"
  }
}
```
A numeric field that represents a measurement is **always** this shape. A bare number in a
response body means "a count we computed from our own rows", nothing else.

### Not measured
```json
{ "value": null, "provenance": { "method": "unmeasured", "reason": "provider_not_configured" } }
```
The UI renders this as an explicit "not measured" state. It is never rendered as `0`,
`—` without explanation, or omitted.

### Job acceptance
```
202 Accepted
{
  "job_id": "…", "kind": "content.page_set.run", "state": "queued",
  "poll": "/api/v1/jobs/…",
  "estimated_cost_cents": 1840,
  "estimated_duration_seconds": 9600
}
```

### Job status
```json
{
  "id": "…", "kind": "…", "state": "running",
  "progress": { "total": 50, "succeeded": 31, "failed": 1, "blocked": 2 },
  "children": "/api/v1/jobs/…/children",
  "cost": { "estimated_cents": 1840, "actual_cents": 1122 },
  "result": null, "error": null
}
```

### Error
```json
{
  "error": {
    "type": "cost_blocked",
    "message": "Content dial is set to by_hand; this run needs approval.",
    "details": { "module": "content", "dial": "by_hand", "review_id": "…" },
    "correlation_id": "…"
  }
}
```

| `type` | HTTP | Retryable |
|---|---|---|
| `validation_error` | 422 | no |
| `unauthenticated` | 401 | no |
| `forbidden` | 403 | no |
| `not_found` | 404 | no |
| `conflict` | 409 | no |
| `idempotency_mismatch` | 409 | no |
| `not_configured` | 409 | no — operator action needed |
| `capability_missing` | 409 | no |
| `cost_blocked` | 402 | no — needs approval or a dial change |
| `rate_limited` | 429 + `Retry-After` | yes |
| `provider_unavailable` | 503 | yes |
| `internal_error` | 500 | maybe |

`internal_error` never includes a stack trace, a query, or a provider payload. The
correlation id is how support finds it.

---

## 4. Surface map

Abbreviated; each module spec carries its full endpoint list with schemas.

### Platform
```
POST   /auth/login · /auth/refresh · /auth/logout · /auth/mfa/verify
GET    /me                                   → identity + capabilities + client scope
GET    /health · /ready · /capabilities      → capability truth table (REQ-CORE-020)

GET    /clients · POST /clients · GET|PATCH /clients/{id}
POST   /clients/import:dry-run · /clients/import:commit
GET    /clients/{id}/locations · POST …
GET|PUT /clients/{id}/nap                    → canonical NAP
GET|PUT /clients/{id}/profile

GET    /team · /team/{id} · /team/{id}/workload
GET    /tasks · POST /tasks · POST /tasks/{id}:assign|:complete|:block
GET    /reviews · POST /reviews/{id}:approve|:reject|:request-change
GET    /notifications · POST /notifications/{id}:read
GET    /activity

GET    /vault/keys                           → key NAMES and status, never values
POST   /vault/keys · DELETE /vault/keys/{id} · POST /vault/keys/{id}:rotate

GET    /cost/summary · /cost/ledger
GET|PUT /cost/dials · PUT /cost/clients/{id}/budget · PUT /cost/halt

GET    /jobs · /jobs/{id} · /jobs/{id}/children
POST   /jobs/{id}:cancel · /jobs/{id}:requeue
GET    /jobs/dead-letters
```

### Audit
```
POST   /public/audits                        → free audit (rate-limited, email-verified)
GET    /public/audits/{token}
POST   /clients/{id}/audits                  → 202, paid audit
GET    /audits/{id} · /audits/{id}/findings · /audits/{id}/artifacts
GET    /audits/{id}/diff?against={auditId}
POST   /audits/{id}/findings/{fid}:to-task
```

### Content
```
POST   /clients/{id}/design-profiles         → 202, capture from previous_website_url
GET    /design-profiles/{id}
PATCH  /design-profiles/{id}/tokens/{tokenId}
POST   /design-profiles/{id}:approve
POST   /design-profiles/{id}:recapture

GET    /clients/{id}/keyword-bank · POST … · PATCH /keyword-bank/{termId}
GET    /clients/{id}/clusters · /clients/{id}/topical-map
POST   /clients/{id}/page-sets:propose       → 202, AI proposes
GET    /page-sets/{id} · POST /page-sets/{id}:approve
POST   /page-sets/{id}:run                   → 202, fan-out

GET    /content/pages · /content/pages/{id} · /content/pages/{id}/preview
PATCH  /content/pages/{id}
POST   /content/pages/{id}:approve|:reject|:publish|:go-live|:revert
GET    /content/pages/{id}/qa · /content/pages/{id}/claims
GET    /clients/{id}/internal-links · POST /internal-links/{id}:apply

GET    /clients/{id}/wordpress · POST /clients/{id}/wordpress:probe
```

### Citations
```
GET    /clients/{id}/citations/audit         → existing listings, NAP inconsistencies
GET    /clients/{id}/citations/gaps          → prioritised directory set
GET    /directories

POST   /citations/sessions                   → operator session + scoped token
GET    /citations/sessions/{id}/queue
POST   /citations/analyze                    → form digest in, fill plan out
POST   /citations/accounts:create            → 202, account-creation graph
GET    /citations/accounts/{id}/verification
POST   /citations/submissions                → records a HUMAN-submitted submission
POST   /citations/submissions/{id}/proof
GET    /clients/{id}/citations/report
```
There is no endpoint that transmits a directory form. The extension fills; the human
submits; the API records.

### Web 2.0 / social
```
GET    /platforms
GET    /clients/{id}/web2/accounts · POST /web2/accounts:connect (OAuth start)
GET    /web2/accounts/{id}/health
POST   /clients/{id}/campaigns · GET /campaigns/{id}
POST   /campaigns/{id}:approve · :start · :pause
GET    /campaigns/{id}/posts · POST /campaigns/{id}/posts:generate
POST   /web2/posts/{id}:approve · :schedule · :publish
GET    /clients/{id}/placed-links
GET    /clients/{id}/calendar
```

### Tracking · keywords · indexing · local · reporting · billing
```
GET    /clients/{id}/rankings · POST /clients/{id}/rankings:run
GET    /clients/{id}/grids · POST /grids/{id}:run · GET /grid-runs/{id}
POST   /clients/{id}/keywords:research       → 202
GET    /clients/{id}/keywords
POST   /indexing/submit · GET /clients/{id}/indexing/status
GET    /clients/{id}/gbp · POST /clients/{id}/gbp/posts
GET    /clients/{id}/reports · POST /clients/{id}/reports:generate
GET    /tiers · PUT /clients/{id}/tier · GET /clients/{id}/entitlements
```

---

## 5. Idempotency

- `Idempotency-Key` is **required** on every `POST`/`PATCH`/`DELETE` that causes an
  external effect or spends money. Missing it returns `422`.
- The key is stored with a digest of the request body. A replay with the same key and the
  same body returns the original response. A replay with the same key and a *different*
  body returns `409 idempotency_mismatch`.
- Keys are retained 7 days.
- The key propagates into the job's `idempotency_key`, which propagates into the
  `side_effects` ledger. One key, one effect, end to end.

---

## 6. Rate limiting

| Scope | Limit |
|---|---|
| Public free audit | 3 per IP per day, 1 per domain per 7 days, plus a global daily spend ceiling |
| Authenticated read | 600/min per user |
| Authenticated write | 120/min per user |
| Extension analyze | 60/min per operator session |
| Per-client job enqueue | Governed by the client concurrency cap, not by HTTP rate limit |
| Per-provider egress | Token bucket shared across all clients, held in Redis |

`429` always carries `Retry-After`. The generated clients honour it automatically.

---

## 7. Realtime

Server-Sent Events at `/api/v1/stream` for job progress, notifications and review-queue
changes. SSE, not WebSockets: the traffic is one-directional, SSE survives proxies, and
it costs no extra infrastructure. Every event carries the correlation id.

---

## 8. Contract testing

- The OpenAPI schema is committed and diffed in CI. An unintended shape change fails the
  build.
- `schemathesis` fuzzes every endpoint against the schema on every PR.
- The frontend client and the extension client are regenerated in CI; a stale generated
  client fails the build.
