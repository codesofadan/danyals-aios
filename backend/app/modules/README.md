# `app/modules/` — the module-per-feature layout

Every business feature is a **self-contained package**: one directory holds its
router, schemas, repo, service, tasks, and provider seam. You read a feature as a
unit instead of hopping across `routers/`, `services/`, `schemas/`, and `db/`.

```
app/modules/<name>/
  __init__.py     # public surface: `from .router import router`
  router.py       # APIRouter(prefix="/kebab", tags=["kebab"]); THIN — validate → service/repo → return
  schemas.py      # Pydantic contracts (contract-locked to frontend/lib/*.ts where a type exists)
  repo.py         # rls_connection reads / privileged_connection writes (imported from app/db/database.py)
  service.py      # orchestration; cost-gate + activity/context feed live here (omit if trivial)
  tasks.py        # this module's Celery jobs (never-stuck / never-re-raise core)
  provider.py     # external seam (key-gated, degrades to a fake) — optional
  constants.py    # module enums/labels/limits — optional
```

## The shared kernel (import it, never re-implement it)

- `app/db/database.py` — the ONLY two DB seams: `rls_connection(user_id)` (tenant
  reads) and `privileged_connection()` (service_role writes).
- `app/rbac/matrix.py` + `app/core/auth.py` deps — `require_perm` / `require_role`
  / `require_feature`.
- `app/core/*` — pagination (`PageDep`), rate-limit, security (SSRF guard), errors.
- `app/services/cost_gate.py`, `app/services/activity.py`, `app/services/vault.py`.

## Registration (additive — one line each)

1. `app/modules/__init__.py`: `from app.modules.<name> import router as <name>_router`
   and append it to `MODULE_ROUTERS`.
2. Celery-owning modules: append `"app.modules.<name>.tasks"` to `include=[...]` in
   `workers/celery_app.py`.

Migrations stay **global and ordered** in `db/migrations/` (`00NN_<name>.sql`) — never
per-module. The auto-discovering guard suites (`test_route_auth_guard`,
`test_route_contracts`, `db/rls_check.py`) cover new routes automatically.

## Definition of Done (house style — every module PR satisfies all of it)

- [ ] Lives under `app/modules/<snake_name>/`; `__init__.py` exposes exactly `router`.
- [ ] `from __future__ import annotations` at the top of every file.
- [ ] Module docstring on `router.py`: names the `lib/*.ts` type it locks to (if any),
      the tables it owns, its migration number, and its cost-gate dial(s).
- [ ] `router.py` is thin — no SQL, no provider calls, no business branching.
- [ ] `schemas.py` contract-locked where a TS type exists; server-authoritative
      (shape/enum unit tests) where none exists.
- [ ] `repo.py` uses `rls_connection` / `privileged_connection` from the shared kernel.
- [ ] Every route carries `require_perm` / `require_role` / `require_feature`.
- [ ] Every new tenant table is `ENABLE` + `FORCE ROW LEVEL SECURITY`.
- [ ] Tests in `tests/modules/<name>/` split `test_router` / `test_service` / `test_repo` / `test_tasks`.

## Robustness DoD (the "fully active, no jerking, no lost context" bar)

- Worker core never raises (ack-late + return; mark `failed`; a redelivery is a no-op).
- External writes idempotent (keyed by an external id).
- Cost pre-check before any paid call (`GateContext` through the gate first).
- Keyless path degrades (`*_from_settings()` → `None`), never crashes.
- Every mutation calls best-effort `record_activity(...)` (feeds the 6B context memory).
- Lists are `PageDep`-bounded; provider calls have timeouts; beat tasks take the overlap lock.
