-- 0001_conventions.sql - base conventions for the AIOS application schema.
--
-- Applied first. Establishes gen_random_uuid(), a shared updated_at trigger,
-- and documents the conventions every later migration follows.
--
-- CONVENTIONS (every application table MUST follow these):
--   * Primary key : id uuid primary key default gen_random_uuid()
--   * Timestamps  : created_at timestamptz not null default now()
--                   updated_at timestamptz not null default now()
--                   + a "set_updated_at" BEFORE UPDATE trigger
--   * RLS         : alter table ... enable row level security;
--                   alter table ... force row level security;   -- forces even the table owner
--                   + explicit policies (NO table is left policy-less).
--   * Reference/catalog tables still get RLS, with a permissive
--     "for select using (true)" so any authenticated role can read them.
--
-- The `auth` schema (auth.uid(), auth.users, auth.jwt()) is provided by
-- Supabase in real deployments; CI stubs it via db/ci/00_supabase_shim.sql.

create extension if not exists pgcrypto;   -- gen_random_uuid()

-- Shared trigger function: stamp updated_at on every row UPDATE.
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

comment on function public.set_updated_at() is
  'Trigger fn: sets updated_at = now() on row UPDATE. Attach one per table.';
