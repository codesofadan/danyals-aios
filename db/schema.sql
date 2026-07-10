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

-- ---- 0002_identity_rbac ------------------------------------------------------
-- Enums: app_role (owner/admin/manager/specialist/analyst/viewer), user_status.
-- Reference data (roles/permissions/features/templates) lives in code
-- (app/rbac/matrix.py), not tables.

create table public.users (
  id           uuid primary key references auth.users (id) on delete cascade,
  email        text not null unique,
  name         text not null,
  title        text not null default '',
  role         public.app_role not null default 'viewer',
  status       public.user_status not null default 'invited',
  avatar_color text not null default '#7B69EE',
  phone        text not null default '',
  two_fa       boolean not null default false,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- + users_set_updated_at trigger; ENABLE + FORCE RLS; policies users_select
--   (self or staff), users_modify (owner/admin).

create table public.user_feature_grants (
  user_id     uuid not null references public.users (id) on delete cascade,
  feature_key text not null,
  level       text not null default 'full' check (level in ('full', 'view', 'off')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (user_id, feature_key)
);
-- + trigger; ENABLE + FORCE RLS; policies select (self or staff), modify (owner/admin).

-- RLS helpers (SECURITY DEFINER, bypass RLS to avoid policy recursion):
--   public.current_app_role() -> app_role,  public.is_staff() -> boolean.
