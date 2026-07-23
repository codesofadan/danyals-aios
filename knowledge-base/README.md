# AIOS Knowledge Base

The **read-this-first** index for the AIOS platform. Both Claude Code and the
dashboard's in-product AI should read this KB before acting, to learn what exists and
how each piece is meant to work. Every page here is a concise, **code-grounded** summary
that points back at the authoritative source file — it never invents behavior.

> **AIOS** is a white-label, cloud SEO-automation platform (one deployment per agency;
> this is the Danyal deployment). It turns agency SEO delivery — audits, content,
> off-page, local, reporting — into a mostly-automated system with a human review gate
> on anything that publishes or spends. Product wordmark is **AIOS** (neutral); the
> agency name is operator-set in Settings. The builder brand name must never appear in
> the software or its output.

## Read these first (in order)

| # | Page | What it covers |
|---|---|---|
| 1 | [architecture.md](architecture.md) | The shape of the system: FastAPI + Celery + PostgreSQL(RLS) + Redis, the two DB seams, the request/worker split, the module-per-feature layout. |
| 2 | [modules.md](modules.md) | Every module — what it does, its DB tables + migration, its API namespace, its cost dial, and its provider key-gate. |
| 3 | [data-model.md](data-model.md) | The tables, grouped by domain, with migration numbers; RLS/tenant boundary; how migrations are applied. |
| 4 | [apis-and-keys.md](apis-and-keys.md) | The provider → consumer map: every external API, the env/vault key that lights it up, and what degrades without it. |
| 5 | [cost-and-dials.md](cost-and-dials.md) | The money-dial + cost-gate: how every paid call is metered, the dial features, budgets, and the daily spend-stop. |
| 6 | [deploy.md](deploy.md) | How it runs in production (native systemd on one VPS) and the local dev gate. |

## The load-bearing invariants (never violate)

1. **RLS is the tenant boundary.** Every tenant table is `ENABLE`+`FORCE ROW LEVEL
   SECURITY`. Staff read via `is_staff()`; a portal **client** reads ONLY through
   security-barrier views filtered by `current_client_id()` — never a base table.
2. **Two DB seams only.** `rls_connection(user_id)` (role `authenticated`, RLS applies)
   for tenant reads/writes; `privileged_connection()` (role `service_role`, BYPASSRLS)
   for server-only writes. service_role bypasses **policies, not triggers**.
3. **Human gate on publish/spend.** Content, Web2, citations, reports, and every paid
   generator stop at a human review checkpoint; a sub-threshold QA draft is a hard STOP.
4. **No invented data.** Every audit finding, metric, and generated fact traces to a
   real provider response or is surfaced as a `[NEEDS: …]` marker for a human — never
   hallucinated (no fake DA/DR, traffic, rankings, or citations).
5. **Provider keys are gated dormant→live.** A missing key **degrades** the feature to a
   deterministic fake / no-op — it never crashes. See `apis-and-keys.md`.
6. **Cost is gated.** Every paid call runs `dial → cache → client cap → daily
   spend-stop → call+log` first. A block **degrades** (honest $0 hold), never a crash.
7. **No hardcoded prices or demo data** (product direction, `PRODUCT-OVERHAUL-BACKLOG`):
   cost is computed at runtime; every dashboard metric is live.

## Where the ground truth lives (this KB summarizes these)

- `backend/CLAUDE.md` — the backend's own operating guide + the numbered invariants.
- `backend/docs/ARCHITECTURE.md`, `CONTENT-MODULE.md`, `CONTEXT-MODULE.md`,
  `CONTENT-DOCTRINE.md`, `CITATIONS-WEB2-CREDENTIALS.md` — module deep-dives.
- `backend/app/modules/README.md` — the module-per-feature contract + Definition of Done.
- `context/ARCHITECTURE-AND-PLAN.md` — the original product architecture + build plan.
- `context/PRODUCT-OVERHAUL-BACKLOG.md` — the current product overhaul spec (source of truth
  for the white-label + no-demo-data + live-cost direction).
- `db/migrations/*.sql` (+ `db/schema.sql` snapshot) — the actual schema.
- `.claude/skills/` — the operator skill layer (one skill per feature) that drives the
  same `/api/v1` routes the dashboard uses; see `.claude/skills/README.md`.

## The two AI surfaces (one backend, two front doors)

- **Operator skills** — `.claude/skills/*` slash commands run in Claude Code; they call
  the backend through `.claude/skills/_shared/aios_client.py` (bearer = skill token).
- **In-product AI** — the dashboard's `POST /api/v1/ai/assist` (cost-gated `ai_assist`
  dial). It routes/summarizes; the module engines do the heavy work.

Both land on the **same** `/api/v1` engines, RLS boundary, RBAC, and cost-gate — they
cannot diverge. See `.claude/skills/_shared/reference/skill-parity.md`.
