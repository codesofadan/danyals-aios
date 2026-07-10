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

-- Supabase's predefined roles (grants in migrations target service_role).
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated nologin;
  end if;
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role nologin;
  end if;
end $$;

-- Supabase Vault shim: a table standing in for the vault.decrypted_secrets view
-- + the create/update functions our public wrappers call.
create schema if not exists vault;

create table if not exists vault.decrypted_secrets (
  id               uuid primary key default gen_random_uuid(),
  name             text,
  decrypted_secret text
);

create or replace function vault.create_secret(
  new_secret text, new_name text default null, new_description text default ''
) returns uuid language plpgsql as $$
declare sid uuid;
begin
  insert into vault.decrypted_secrets (name, decrypted_secret)
  values (new_name, new_secret) returning id into sid;
  return sid;
end $$;

create or replace function vault.update_secret(
  secret_id uuid, new_secret text default null, new_name text default null, new_description text default null
) returns void language plpgsql as $$
begin
  update vault.decrypted_secrets
  set decrypted_secret = coalesce(new_secret, decrypted_secret)
  where id = secret_id;
end $$;
