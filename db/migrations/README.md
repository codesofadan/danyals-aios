# migrations

Ordered SQL migrations for the AIOS Postgres schema (Supabase). Files are named
`NNNN_name.sql` and **applied in lexical order**. They are the source of truth;
`../schema.sql` is a synced snapshot.

## Apply

Against a Supabase project (or any Postgres) via `psql`:

```bash
for f in db/migrations/*.sql; do
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$f"
done
```

`DATABASE_URL` is the Postgres connection string (Supabase: Project Settings →
Database → Connection string). In production the `auth` schema already exists
(Supabase Auth); locally/CI it is stubbed by `../ci/00_supabase_shim.sql`,
which is applied **before** these migrations and never in production.

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
