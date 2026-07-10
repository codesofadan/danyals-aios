-- CI-ONLY shim. NOT applied in production.
--
-- Supabase provides the `auth` schema (auth.users, auth.uid(), auth.jwt(),
-- auth.role()) in every real project. To run the RLS gate against a vanilla
-- Postgres in CI, we stub just the pieces our migrations reference so they
-- apply cleanly. Applied BEFORE db/migrations/*.sql in the CI job only.

create extension if not exists pgcrypto;

create schema if not exists auth;

create table if not exists auth.users (
  id    uuid primary key default gen_random_uuid(),
  email text
);

-- In real Supabase these read the request's JWT/GUCs; here they return inert
-- defaults so policy expressions type-check and the tables can be created.
create or replace function auth.uid() returns uuid
  language sql stable as $$ select null::uuid $$;

create or replace function auth.jwt() returns jsonb
  language sql stable as $$ select '{}'::jsonb $$;

create or replace function auth.role() returns text
  language sql stable as $$ select 'authenticated'::text $$;
