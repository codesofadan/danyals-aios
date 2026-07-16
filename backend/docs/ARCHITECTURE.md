# Danyal AIOS backend — architecture map

FastAPI + Celery + local PostgreSQL (psycopg3, per-tenant Row-Level-Security) + Redis.
A **modular monolith**: one deployable, organized as a **package per feature** with a
**shared kernel** the features build on.

## Top-level layout

```
backend/
  app/
    main.py            # FastAPI app + lifespan (pool/redis/httpx clients)
    config.py          # Settings (env); all external keys optional / dormant→live
    modules/           # feature packages (see app/modules/README.md) — the primary home for features
    routers/           # api_v1 aggregator + legacy layer-based routers (migrating into modules/)
    services/          # legacy layer-based services (migrating into modules/)
    schemas/           # legacy layer-based Pydantic contracts (migrating into modules/)
    db/
      database.py      # THE two DB seams: rls_connection() / privileged_connection()
      rls_check.py     # CI gate: every base table is ENABLE+FORCE RLS
      *_repo.py        # legacy repos (migrating into modules/)
    core/              # cross-cutting: auth, deps, errors, pagination, ratelimit, security(SSRF), metrics
    rbac/              # matrix.py: perms + feature-grants + role templates
    util/              # small pure helpers (timefmt, ...)
  integrations/        # external provider seams (key-gated; each *_from_settings → real client | None)
  workers/
    celery_app.py      # Celery app + beat schedule + include=[...]
    tasks/             # legacy Celery task modules (migrating into modules/<name>/tasks.py)
  tests/               # unit + integration + mutation + perf; tests/modules/<name>/ for new modules
db/migrations/         # GLOBAL ordered SQL (0000+); verify_fresh_apply.py proves order-cleanliness
```

## The shared kernel (stable; imported by every feature, never re-implemented)

`app/db/database.py` (the two connection seams), `app/rbac/matrix.py`, `app/core/*`,
`app/services/{cost_gate,activity,vault}.py`. Features depend inward on the kernel;
the kernel never depends on a feature.

## Two invariants that never move

1. **Migrations are one global ordered sequence** in `db/migrations/`. Never per-module —
   the fresh-apply + RLS gates depend on the order.
2. **RLS is the tenant boundary.** Every base table is `ENABLE` + `FORCE ROW LEVEL
   SECURITY`; staff read via `is_staff()`, clients read only through security-barrier
   views filtered by `current_client_id()`. Workers write on `privileged_connection`
   (service_role, BYPASSRLS) but are still bound by DB guard triggers.

## Migration status (Part 8)

New features land under `app/modules/`. The existing Parts 1–9 modules are being
migrated file-by-file into the same layout (behavior-preserving `git mv`, gate green
after each) so the whole backend reads as one consistent structure. See
`app/modules/README.md` for the module contract and Definition of Done.
