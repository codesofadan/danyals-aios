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
