# db

Database schema and migrations for the AIOS platform (Supabase Postgres).

## Layout

```
db/
├── migrations/     # ordered NNNN_*.sql, applied in lexical order (source of truth)
├── schema.sql      # human-readable snapshot, kept in sync per migration
├── seed/           # optional seed/fixture data (see seed/README.md)
└── ci/             # CI-only Supabase shim (auth/vault/roles) - never used in prod
```

## Apply

```bash
for f in db/migrations/*.sql; do psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"; done
```

In production the `auth` schema + Supabase Vault already exist. Locally/CI they
are stubbed by `ci/00_supabase_shim.sql` (applied **before** the migrations).

## RLS gate

Every application table must have `ENABLE` **and** `FORCE` row-level security.
After applying, verify (from `backend/`):

```bash
DATABASE_URL=... python -m app.db.rls_check
```

CI's `db-rls` job runs this against an ephemeral Postgres on every backend/db change.

## Current schema (Part 2 — the Shared Base)

| Migration | Tables / objects |
|---|---|
| `0001_conventions` | `pgcrypto`, `set_updated_at()` trigger fn, conventions |
| `0002_identity_rbac` | `users` (↔ `auth.users`), `user_feature_grants`; `current_app_role()` / `is_staff()` |
| `0003_clients_sites` | `clients` (subscription + contact + portal metadata), `sites` |
| `0004_vault` | `vault_keys` metadata + `vault_*` service_role-only Vault wrappers |
| `0005_activity_log` | append-only `activity_log` |
| `0006_cost` | `client_budgets`, `cost_dial`, `cost_settings`, `cost_log`, `add_budget_spend()` |
| `0007_delivery_tier` | `delivery_tier` enum + `clients.delivery_tier` |

Roles, permissions, features, templates and the tier/dial metadata are **static
reference data kept in code** (`backend/app/rbac/matrix.py`, `app/schemas/{cost,tiers}.py`),
not in tables — a single source of truth, mirrored from `frontend/lib/*.ts`.

The module operational stores (audits, content jobs, backlinks, …) live in
**Google Sheets**, not Postgres — see `../context/AIOS-Data-Flow-Structure.pdf`.
