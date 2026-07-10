-- ============================================================================
-- AIOS - current schema snapshot (human-readable reference).
--
-- SOURCE OF TRUTH is db/migrations/*.sql (applied in order). This file is a
-- convenience snapshot kept in sync per chunk; regenerate against an applied
-- database with:  pg_dump --schema-only --schema=public "$DATABASE_URL"
--
-- Conventions (see 0001_conventions.sql): uuid PKs (gen_random_uuid),
-- created_at/updated_at timestamptz + set_updated_at() trigger, and every
-- table ENABLE + FORCE row level security with explicit policies.
-- ============================================================================

-- ---- 0001_conventions --------------------------------------------------------
create extension if not exists pgcrypto;

create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at := now();
  return new;
end;
$$;
