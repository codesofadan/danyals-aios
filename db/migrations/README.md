# migrations

Ordered SQL migrations for the AIOS Postgres schema (self-hosted PostgreSQL 16).
Files are named `NNNN_name.sql` and **applied in lexical order**. They are the
source of truth; `../schema.sql` is a synced snapshot.

## Apply

Against any PostgreSQL 16 server via `psql`, as a BYPASSRLS superuser owner:

```bash
for f in db/migrations/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

`0000_local_platform.sql` sorts first and provisions the substrate the rest depend
on: the `auth` schema + `auth.uid()/role()/jwt()` GUC readers and the
`anon`/`authenticated`/`service_role` roles. No Supabase and no CI shim are needed.
Migrations **MUST** be applied by a superuser/BYPASSRLS owner (locally `postgres`)
so the SECURITY DEFINER RLS helpers (`is_staff`/`current_app_role`/
`current_client_id`) read `public.users` without recursing through RLS.

## RLS gate

Every application table must have `ENABLE` **and** `FORCE` row-level security.
After applying migrations, verify with the checker (from `backend/`):

```bash
DATABASE_URL=... python -m app.db.rls_check
```

It exits non-zero and names any `public` table missing forced RLS. CI runs this
against an ephemeral Postgres on every backend/db change.

## Conventions

See `0001_conventions.sql`. Each tenant table: uuid PK, `created_at`/`updated_at`
+ `set_updated_at()` trigger, `enable`+`force` RLS, and explicit policies.

## Reading a column's CURRENT type

**The `CREATE TABLE` is not the schema.** A column's type is its creating migration
plus every later `ALTER`, and with 80+ ordered files that is not something to eyeball.

Two sessions got `client_budgets.cap`/`.spent` wrong on 2026-08-23 by reading
`0006_cost.sql` (which creates them as `integer`) and missing
`0044_cost_budget_numeric.sql` (which widens them to `numeric(10,2)`). One of those
readings was then relayed onward as "verified at source". A grep found the definition;
it did not find the truth.

Ask a built database instead — about ninety seconds, and it cannot be wrong:

```bash
# from backend/, with DATABASE_MIGRATE_URL pointing at a scratch server
python ../db/ci/verify_fresh_apply.py --keep     # builds the schema from zero, keeps it

psql "$SCRATCH_DSN" -c "
  select table_name, column_name, data_type, numeric_precision, numeric_scale
  from information_schema.columns
  where table_schema='public' and table_name in ('cost_log','client_budgets','job_runs')
    and column_name in ('cost','cap','spent','cost_usd')
  order by table_name, column_name;"
```

The same rule applies to anything a later migration can change: enum labels (a
`create type` tells you nothing once an `alter type ... add value` exists elsewhere),
constraints, defaults, indexes and RLS policies. Grep to find *where* something is
defined; build the schema to find *what it currently is*.

This is also why `verify_fresh_apply.py` exists and why CI runs it: applying every
migration in order from zero is the only statement about the schema that is not an
inference.
