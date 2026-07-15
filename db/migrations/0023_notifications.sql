-- 0023_notifications.sql - Part 7 (7F-1): the DELIVERY layer.
--
-- Two net-new stores that sit BESIDE the append-only activity_log (0013) and
-- CONSUME the per-user notification_prefs added in 0025:
--
--   * notifications - PER-USER in-app inbox. One row = one delivered notification
--     (kind/title/body); `read` flips to true when the owner opens it. The WRITER is
--     the server (app/services/notifications.py::notify) on the PRIVILEGED pool -
--     exactly like log_activity - because a notification is addressed to SOMEONE ELSE
--     than the actor, so its write must not be gated by the actor's RLS identity.
--   * alerts - the STAFF signal queue (rank-drop / lost-link / budget). One row = one
--     raised alert (type/severity/detail); `acknowledged` flips true when a lead
--     clears it. Written server-side (raise_alert) on the privileged pool; read by
--     any staff, acknowledged by a lead.
--
-- RLS threat model (mirrors 0025's per-user prefs + 0018's staff/lead split): a
-- leaked credential can hit the DB directly, so RLS is the real boundary, not the
-- FastAPI dependency.
--   * notifications: a user reads/updates ONLY their own rows (user_id = auth.uid()) -
--     the same per-owner scoping as notification_prefs. This works for a portal client
--     too (they simply have no rows). NO insert policy: the only writer is service_role
--     (BYPASSRLS) via notify(); a user can never fabricate a notification. NO delete.
--   * alerts: any staff READ (is_staff()); only a lead (owner/admin/manager) may
--     acknowledge (UPDATE) - matching the "staff read, lead manage" split of tickets
--     (0024) / off-page (0018). NO insert policy (service_role writes via raise_alert);
--     NO delete. Clients are excluded by is_staff() throughout.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
-- The v1 alert taxonomy. rank_drop / lost_link are the paid-tier monitoring signals
-- (a tracked keyword slid, a monitored backlink went dark); budget is the money-dial
-- guardrail (a client's spend crossed its cap). Additive: new kinds append here.
do $$ begin
  if not exists (select 1 from pg_type where typname = 'alert_type') then
    create type public.alert_type as enum ('rank_drop', 'lost_link', 'budget');
  end if;
end $$;

-- --- Notifications (per-user in-app inbox) -----------------------------------
create table if not exists public.notifications (
  id          uuid primary key default gen_random_uuid(),
  -- The recipient. ON DELETE CASCADE: a removed user's inbox goes with them.
  user_id     uuid not null references public.users (id) on delete cascade,
  -- Free-text event kind. When it matches a notification_prefs event_key (0025 /
  -- NOTIF_EVENTS) the recipient's stored email/in_app toggles govern delivery;
  -- an unknown kind falls back to in-app-only. Kept text (not an enum) so a new
  -- event needs no migration - the schema layer owns the catalogue.
  kind        text not null,
  title       text not null,
  body        text not null default '',
  read        boolean not null default false,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

-- The inbox query is "my rows, newest first"; the composite index serves it directly.
create index if not exists notifications_user_created_idx
  on public.notifications (user_id, created_at desc);

create trigger notifications_set_updated_at
  before update on public.notifications
  for each row execute function public.set_updated_at();

-- --- Alerts (staff signal queue) ---------------------------------------------
create table if not exists public.alerts (
  id            uuid primary key default gen_random_uuid(),
  -- The client the alert is about. ON DELETE CASCADE: a removed client's alerts go
  -- with it (an alert is meaningless without its client).
  client_id     uuid not null references public.clients (id) on delete cascade,
  type          public.alert_type not null,
  -- info | warning | critical - kept text (not an enum) so the service tunes the
  -- ladder without a migration; it is a display/sort hint, never an RLS predicate.
  severity      text not null default 'warning',
  detail        text not null default '',
  acknowledged  boolean not null default false,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists alerts_client_id_idx  on public.alerts (client_id);
create index if not exists alerts_created_at_idx  on public.alerts (created_at desc);

create trigger alerts_set_updated_at
  before update on public.alerts
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
alter table public.notifications enable row level security;
alter table public.notifications force row level security;
alter table public.alerts enable row level security;
alter table public.alerts force row level security;

-- Notifications: a user reads + marks-read ONLY their own rows. No insert policy
-- (service_role writes via notify()); no delete. WITH CHECK on update pins the row
-- to the caller so it can never be reassigned to another user.
create policy notifications_select on public.notifications
  for select using (user_id = auth.uid());
create policy notifications_update on public.notifications
  for update
  using (user_id = auth.uid())
  with check (user_id = auth.uid());

-- Alerts: any staff read; only a lead (owner/admin/manager) may acknowledge. No
-- insert policy (service_role writes via raise_alert); no delete. Clients are
-- excluded by is_staff().
create policy alerts_select on public.alerts
  for select using (public.is_staff());
create policy alerts_update on public.alerts
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
