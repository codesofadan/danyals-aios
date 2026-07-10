-- 0002_identity_rbac.sql - identity (users <-> auth.users) + per-user feature grants.
--
-- Roles, permissions, features and their defaults are STATIC reference data kept
-- in code (app/rbac/matrix.py), not in tables, so enforcement needs no DB round
-- trip. Here we persist only what is per-user: the users row (governance role +
-- profile) and any per-user feature-grant overrides.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'app_role') then
    create type public.app_role as enum
      ('owner', 'admin', 'manager', 'specialist', 'analyst', 'viewer');
  end if;
  if not exists (select 1 from pg_type where typname = 'user_status') then
    create type public.user_status as enum ('active', 'away', 'invited', 'offline');
  end if;
end $$;

-- --- Identity: one row per agency user, PK-linked to Supabase Auth ------------
-- Passwords live ONLY in auth.users (Supabase Auth); this table never stores a
-- credential. id = auth.users.id so RLS can compare against auth.uid() directly.
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

create trigger users_set_updated_at
  before update on public.users
  for each row execute function public.set_updated_at();

-- --- Per-user feature-grant overrides (the Add-Member "adjust toggles" flow) --
-- Seeded from a template at provisioning; absence of a row means "off".
create table public.user_feature_grants (
  user_id     uuid not null references public.users (id) on delete cascade,
  feature_key text not null,
  level       text not null default 'full' check (level in ('full', 'view', 'off')),
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (user_id, feature_key)
);

create trigger user_feature_grants_set_updated_at
  before update on public.user_feature_grants
  for each row execute function public.set_updated_at();

-- --- RLS helper functions -----------------------------------------------------
-- SECURITY DEFINER + owned by the migration role (BYPASSRLS in Supabase/CI), so
-- reading public.users from INSIDE a users policy does NOT recurse. search_path
-- is pinned empty and every name is schema-qualified (injection-safe).
create or replace function public.current_app_role()
returns public.app_role
language sql stable security definer set search_path = ''
as $$ select role from public.users where id = auth.uid() $$;

create or replace function public.is_staff()
returns boolean
language sql stable security definer set search_path = ''
as $$ select exists (select 1 from public.users where id = auth.uid()) $$;

comment on function public.is_staff() is
  'True if the caller (auth.uid()) is a provisioned agency user. Used by RLS.';

-- --- RLS: users ---------------------------------------------------------------
alter table public.users enable row level security;
alter table public.users force row level security;

-- Any provisioned user may read their own row; staff may read the whole roster.
create policy users_select on public.users
  for select using (auth.uid() = id or public.is_staff());

-- Only owner/admin (manage_team) may write via a user-JWT client. Server-side
-- provisioning uses the service_role client, which bypasses RLS by design.
create policy users_modify on public.users
  for all
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));

-- --- RLS: user_feature_grants -------------------------------------------------
alter table public.user_feature_grants enable row level security;
alter table public.user_feature_grants force row level security;

-- A user may read their own grants; staff may read any (to render access UIs).
create policy user_feature_grants_select on public.user_feature_grants
  for select using (user_id = auth.uid() or public.is_staff());

-- Only owner/admin (access_control) may change grants via a user-JWT client.
create policy user_feature_grants_modify on public.user_feature_grants
  for all
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));
