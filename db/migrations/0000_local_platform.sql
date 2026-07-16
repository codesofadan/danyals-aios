-- 0000_local_platform.sql - the self-hosted-Postgres SUBSTRATE (sorts FIRST).
--
-- Replaces the objects Supabase provides for free (the `auth` schema + auth.uid()/
-- auth.jwt()/auth.role(), and the anon/authenticated/service_role roles) with
-- production-grade local equivalents, so every LATER migration (0001..) that
-- references auth.uid()/auth.users or GRANTs to these roles applies
-- BYTE-FOR-BYTE UNCHANGED on a plain PostgreSQL 16 server. Idempotent; safe to
-- re-run. This file is the production-grade replacement for the deleted
-- db/ci/00_supabase_shim.sql.
--
-- OWNERSHIP INVARIANT (load-bearing): these migrations MUST be applied by a
-- BYPASSRLS superuser owner (locally: `postgres`) so the SECURITY DEFINER helpers
-- defined in later migrations (public.is_staff / public.current_app_role /
-- public.current_client_id) run as a bypassrls owner and can read public.users
-- from INSIDE the users_select policy WITHOUT recursing through RLS. Applying as a
-- non-bypassrls role would make is_staff() re-enter users_select -> infinite
-- recursion / default-deny. service_role (BYPASSRLS) is the privileged runtime
-- pool; authenticated (NOT bypassrls) is the RLS-bound per-request pool.

create extension if not exists pgcrypto;                 -- gen_random_uuid(), digest(), gen_random_bytes()

-- --- Roles: mirror the Supabase names so all existing GRANTs keep working -----
-- service_role : privileged server identity, BYPASSRLS (the admin pool DSN).
-- authenticated: the RLS-bound identity (per-request pool DSN); RLS APPLIES to it.
-- anon         : parity with existing GRANTs (the portal_* views grant to anon).
--
-- Passwords are NOT set here (kept out of version control); the install step runs
-- `ALTER ROLE authenticated PASSWORD :'pw'` / `... service_role ...` from env.
-- NOTE: anon is `nologin` locally on purpose -- in the FastAPI-only topology the
-- browser never holds a DB credential (all access is server-mediated), so the
-- 0010 `grant select ... to anon` is VESTIGIAL parity, not a live login path. Do
-- NOT change anon to login.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'service_role') then
    create role service_role login bypassrls;            -- password set out-of-band
  end if;
  if not exists (select 1 from pg_roles where rolname = 'authenticated') then
    create role authenticated login;                     -- NOT bypassrls: RLS binds it
  end if;
  if not exists (select 1 from pg_roles where rolname = 'anon') then
    create role anon nologin;                            -- vestigial; no DB login in this topology
  end if;
end $$;

grant usage on schema public to anon, authenticated, service_role;
-- authenticated gets blanket table DML that RLS then CONSTRAINS (the Supabase
-- model); default privileges cover the tables the migration owner creates in the
-- later migrations (applies to objects created by the current -- superuser -- role).
alter default privileges in schema public
  grant select, insert, update, delete on tables to authenticated, service_role;
alter default privileges in schema public
  grant usage, select on sequences to authenticated, service_role;

-- --- auth schema + identity table (the FK target for public.users) ------------
-- Credentials are service-only: anon/authenticated can neither see the schema nor
-- the table. auth.users mirrors the columns the app needs (id is the uuid PK that
-- RLS / auth.uid() compare against; password_hash holds argon2id, or an imported
-- bcrypt hash, rehashed on next login).
create schema if not exists auth;
revoke all on schema auth from public;
-- USAGE lets a role RESOLVE + call the identity functions below (RLS policies run
-- auth.uid() as the querying role, so authenticated/anon MUST have schema usage).
-- It grants NO access to auth.users, which is locked down by its own table grants.
grant usage on schema auth to anon, authenticated, service_role;

create table if not exists auth.users (
  id            uuid primary key default gen_random_uuid(),
  email         text not null unique,
  password_hash text not null,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);
revoke all on auth.users from public, anon, authenticated;
grant select, insert, update, delete on auth.users to service_role;

-- --- Request-identity GUC readers (replace the Supabase auth.* built-ins) ------
-- The RLS pool runs, INSIDE each transaction: SET LOCAL app.user_id = '<verified
-- uuid>' (and optionally app.user_role / app.jwt_claims). auth.uid() returns it;
-- NULL when unset (a privileged or unauthenticated connection), which every
-- existing policy already treats as "no access" for role authenticated.
--
-- STABLE (not IMMUTABLE): current_setting() reads mutable session state, so these
-- must not be folded/cached across the SET LOCAL. search_path is PINNED to
-- pg_catalog (fix): every function these call (nullif/current_setting/coalesce +
-- the ::uuid / ::jsonb casts) resolves from pg_catalog, so a hostile search_path
-- can never shadow them. Grant EXECUTE to all three roles (policies invoke them).
create or replace function auth.uid() returns uuid
  language sql stable
  set search_path = pg_catalog
  as $$ select nullif(current_setting('app.user_id', true), '')::uuid $$;

create or replace function auth.role() returns text
  language sql stable
  set search_path = pg_catalog
  as $$ select coalesce(nullif(current_setting('app.user_role', true), ''), current_user) $$;

create or replace function auth.jwt() returns jsonb
  language sql stable
  set search_path = pg_catalog
  as $$ select coalesce(nullif(current_setting('app.jwt_claims', true), '')::jsonb, '{}'::jsonb) $$;

grant execute on function auth.uid(), auth.role(), auth.jwt()
  to anon, authenticated, service_role;
