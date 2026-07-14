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

-- ---- 0003_clients_sites ------------------------------------------------------
-- Enums: sub_tier (Starter/Growth/Scale), sub_status (active/trial/past_due/paused).
-- No portal password column (client logins are Supabase Auth users).

create table public.clients (
  id                   uuid primary key default gen_random_uuid(),
  name                 text not null,
  industry             text not null default '',
  since_year           int,
  contact_name         text not null default '',
  contact_role         text not null default '',
  contact_email        text not null default '',
  contact_color        text not null default '#7B69EE',
  tier                 public.sub_tier not null default 'Starter',
  status               public.sub_status not null default 'trial',
  renews_at            date,
  mrr                  integer not null default 0,
  portal_admin         text not null default '',
  portal_seats         integer not null default 0,
  portal_two_fa        boolean not null default false,
  portal_last_login_at timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create table public.sites (
  id         uuid primary key default gen_random_uuid(),
  client_id  uuid not null references public.clients (id) on delete cascade,
  domain     text not null,
  cms_type   text not null default 'wordpress',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- + triggers; ENABLE + FORCE RLS; select (is_staff), modify (owner/admin/manager).

-- ---- 0004_vault -------------------------------------------------------------
-- Raw secrets live in Supabase Vault; this table holds only metadata + a masked
-- preview + the vault secret_id. Reveal/store/rotate go through SECURITY DEFINER
-- public.vault_* wrappers whose EXECUTE is granted only to service_role.

create table public.vault_keys (
  id         uuid primary key default gen_random_uuid(),
  provider   text not null,
  label      text not null,
  masked     text not null default '',
  scope      text not null default 'Agency-global',
  site       text,
  secret_id  uuid not null,
  rotated_at timestamptz not null default now(),
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
-- + trigger; ENABLE + FORCE RLS; select + modify restricted to owner/admin
--   (reveal further restricted to owner in the app). Wrappers:
--   public.vault_create_secret / vault_update_secret / vault_reveal_secret.

-- ---- 0005_activity_log ------------------------------------------------------
-- Append-only audit feed. Actor identity snapshotted. Staff read only; writes
-- happen solely via the service_role server client (no user can tamper).

create table public.activity_log (
  id          uuid primary key default gen_random_uuid(),
  actor_id    uuid references public.users (id) on delete set null,
  actor_name  text not null default '',
  actor_init  text not null default '',
  actor_color text not null default '#7B69EE',
  kind        text not null,
  action      text not null,
  target      text not null default '',
  meta        text,
  created_at  timestamptz not null default now()
);
-- + created_at index; ENABLE + FORCE RLS; select (is_staff) only, no write policy.

-- ---- 0006_cost --------------------------------------------------------------
-- The cost-control subsystem. dial_mode enum (api/byhand/off).
--   client_budgets(client_id PK, cap, spent)      - staff read, manage_clients write
--   cost_dial(feature_key PK, mode)               - staff read, owner/admin write
--   cost_settings(singleton: daily_stop, halted)  - staff read, owner/admin write
--   cost_log(client, job, provider, cost, cached) - append-only, staff read
-- add_budget_spend(client, amount) RPC = atomic spent increment (service_role).
-- The gate (app/services/cost_gate.py) reads these before any paid call.

-- ---- 0007_delivery_tier -----------------------------------------------------
-- delivery_tier enum (free/semi/fully) + clients.delivery_tier column. SEPARATE
-- from the subscription tier (clients.tier = Starter/Growth/Scale). Delivery tier
-- is a preset over the cost dial; the two are never conflated.
alter table public.clients add column delivery_tier public.delivery_tier not null default 'free';

-- ---- 0008_audits ------------------------------------------------------------
-- Module 01 Audit job ledger. One row per run against the external audit engine
-- (invoked as a subprocess by a Celery worker). Enums: audit_tier (free/paid),
-- audit_status (queued/running/done/failed). Shapes mirror lib/audit.ts.
create table public.audits (
  id           uuid primary key default gen_random_uuid(),
  client_id    uuid references public.clients (id) on delete set null,
  site_id      uuid references public.sites (id) on delete set null,
  client_name  text not null default '',
  url          text not null,
  types        text[] not null default '{}',       -- technical|actionable|local|geo|backlink
  tier         public.audit_tier not null default 'free',
  status       public.audit_status not null default 'queued',
  run_uuid     text,                                 -- engine mints this; we parse + store it
  artifact_dir text,
  pdf_path     text,
  json_path    text,
  score        integer,                              -- 0-100 composite; null while pending
  scores       jsonb not null default '{}',          -- per-category detail from run.json
  cost         numeric(10, 2) not null default 0,
  error        text,
  runtime_seconds integer,
  started_at   timestamptz,
  finished_at  timestamptz,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);
-- + client_id & created_at indexes; ENABLE + FORCE RLS. select (is_staff);
-- modify by run_audits holders (owner/admin/manager/specialist/analyst). The
-- worker updates rows via the service_role client (bypasses RLS by design).
