-- 0025_settings.sql - Part 7 (Settings): the net-new persistence behind the admin
-- control panel's Security / Notifications / Workspace tabs.
--
-- The Settings module is mostly a VIEW over surfaces that already exist: the
-- account-profile tab edits public.users (0002/0016); client + team credentials
-- reuse the vault (0004) / provisioning; the RBAC matrix reuses rbac (0002). This
-- migration adds ONLY the three genuinely new stores:
--
--   * workspace_settings - agency-global preferences (one shared singleton).
--   * security_policy     - agency-global auth policy (one shared singleton).
--   * notification_prefs  - PER-USER, per-event email/in-app toggles.
--
-- Shapes mirror frontend/lib/data.ts (WorkspaceSettingsData / SecurityPolicy /
-- NotifPref). The static NotifPref label/desc/icon live in code (a server constant,
-- like the rbac matrix), NOT the table - the table holds only the mutable toggles.
--
-- RLS (mirrors 0021/0022 threat model - a leaked credential can hit the DB direct,
-- so RLS is the real boundary): any staff READ the two singletons; only owner/admin
-- MANAGE them. notification_prefs is scoped to the OWNER of the row - a staff user
-- reads/writes ONLY their own toggles (user_id = auth.uid()). Clients are excluded
-- by is_staff() throughout. No delete policies (the danger-zone reset/purge runs
-- server-side on the privileged pool).

-- --- Enums (idempotent guards) -----------------------------------------------
-- default_tier reuses the existing sub_tier enum (0003: Starter/Growth/Scale);
-- week_start is net-new. §3 enum fidelity: week_start mirrors WorkspaceSettingsData
-- .weekStart verbatim.
do $$ begin
  if not exists (select 1 from pg_type where typname = 'week_start') then
    create type public.week_start as enum ('Monday', 'Sunday');
  end if;
end $$;

-- --- Workspace settings (agency-global singleton) ----------------------------
-- Exactly one row (id is pinned to 1 by the check), so a GET is a single-row read
-- and a PUT is a single-row update. Seeded with the frontend defaults so a GET
-- always finds a row even before the first save.
create table if not exists public.workspace_settings (
  id            integer primary key default 1 check (id = 1),
  agency_name   text not null default 'Xegents AI',            -- contract `agencyName`
  support_email text not null default 'support@xegents.ai',    -- contract `supportEmail`
  timezone      text not null default 'Asia/Karachi (PKT)',
  language      text not null default 'English (US)',
  week_start    public.week_start not null default 'Monday',   -- contract `weekStart`
  default_tier  public.sub_tier not null default 'Growth',     -- contract `defaultTier`
  brand_color   text not null default '#7B69EE',               -- contract `brandColor`
  updated_at    timestamptz not null default now()
);

create trigger workspace_settings_set_updated_at
  before update on public.workspace_settings
  for each row execute function public.set_updated_at();

insert into public.workspace_settings (id) values (1) on conflict (id) do nothing;

-- --- Security policy (agency-global singleton) -------------------------------
create table if not exists public.security_policy (
  id               integer primary key default 1 check (id = 1),
  enforce_2fa      boolean not null default true,   -- contract `enforce2FA`
  strong_passwords boolean not null default true,   -- contract `strongPasswords`
  min_pass_length  integer not null default 12,     -- contract `minPassLength`
  rotation_days    integer not null default 90,     -- contract `rotationDays` (0 = never)
  session_timeout  integer not null default 30,     -- contract `sessionTimeout` (minutes)
  single_session   boolean not null default false,  -- contract `singleSession`
  ip_allowlist     boolean not null default false,  -- contract `ipAllowlist`
  audit_logging    boolean not null default true,   -- contract `auditLogging`
  updated_at       timestamptz not null default now()
);

create trigger security_policy_set_updated_at
  before update on public.security_policy
  for each row execute function public.set_updated_at();

insert into public.security_policy (id) values (1) on conflict (id) do nothing;

-- --- Notification preferences (per-user, per-event) --------------------------
-- One row per (user, event); the static label/desc/icon come from the server
-- constant (app/schemas/settings.py NOTIF_EVENTS). email/in_app are the toggles.
create table if not exists public.notification_prefs (
  user_id     uuid not null references public.users (id) on delete cascade,
  event_key   text not null,
  email       boolean not null default true,
  in_app      boolean not null default true,   -- contract `inApp`
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  primary key (user_id, event_key)
);

create index if not exists notification_prefs_user_id_idx on public.notification_prefs (user_id);

create trigger notification_prefs_set_updated_at
  before update on public.notification_prefs
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
alter table public.workspace_settings enable row level security;
alter table public.workspace_settings force row level security;
alter table public.security_policy enable row level security;
alter table public.security_policy force row level security;
alter table public.notification_prefs enable row level security;
alter table public.notification_prefs force row level security;

-- Singletons: any staff read; only owner/admin manage.
create policy workspace_settings_select on public.workspace_settings
  for select using (public.is_staff());
create policy workspace_settings_insert on public.workspace_settings
  for insert with check (public.current_app_role() in ('owner', 'admin'));
create policy workspace_settings_update on public.workspace_settings
  for update
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));

create policy security_policy_select on public.security_policy
  for select using (public.is_staff());
create policy security_policy_insert on public.security_policy
  for insert with check (public.current_app_role() in ('owner', 'admin'));
create policy security_policy_update on public.security_policy
  for update
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));

-- Notification prefs: a staff user reads/writes ONLY their own rows. Clients are
-- excluded by is_staff(); a user can never touch another user's toggles.
create policy notification_prefs_select on public.notification_prefs
  for select using (public.is_staff() and user_id = auth.uid());
create policy notification_prefs_insert on public.notification_prefs
  for insert with check (public.is_staff() and user_id = auth.uid());
create policy notification_prefs_update on public.notification_prefs
  for update
  using (public.is_staff() and user_id = auth.uid())
  with check (public.is_staff() and user_id = auth.uid());
