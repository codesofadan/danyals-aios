-- 0024_tickets.sql - Part 7 (Support Tickets): the client-support ticket ledger.
--
-- One row per support request a client raises (or the agency logs on their
-- behalf). Staff triage them through a small lifecycle (open -> pending ->
-- resolved) across the channel it arrived on (Email/Portal/Call/Chat). Shapes
-- mirror frontend/lib/data.ts (Ticket): `id` is the PUBLIC T-#### badge (never a
-- UUID); client_name is a display SNAPSHOT so client_id never leaks; `ago` is the
-- humanized time since opened_at (derived in the schema layer, not stored).
--
-- THREAT MODEL (mirrors 0011/0017): any authenticated principal could hit the DB
-- directly with a leaked credential, so RLS is the real boundary. Clients are
-- already excluded by is_staff() (redefined in 0010) - a portal client can NOT
-- read or write this table; the client-facing "open a ticket" path lands here via
-- the server (service_role), not a client base-table write. Any staff may READ;
-- only the leads (owner/admin/manager = the manage_clients holders) triage
-- (INSERT/UPDATE), so the app-layer 403 and this boundary agree. No delete in v1.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
-- ticket_priority is a DISTINCT type from task_priority (0011) even though they
-- share the same four labels - kept separate so a future priority set can diverge
-- per domain without a cross-module migration.
do $$ begin
  if not exists (select 1 from pg_type where typname = 'ticket_channel') then
    create type public.ticket_channel as enum ('Email', 'Portal', 'Call', 'Chat');
  end if;
  if not exists (select 1 from pg_type where typname = 'ticket_priority') then
    create type public.ticket_priority as enum ('urgent', 'high', 'med', 'low');
  end if;
  if not exists (select 1 from pg_type where typname = 'ticket_status') then
    create type public.ticket_status as enum ('open', 'pending', 'resolved');
  end if;
end $$;

-- Public ticket-code sequence. The frontend renders the code as a visible badge
-- (e.g. "T-4821"); it starts at 4822 to continue past the seed data.
create sequence if not exists public.tickets_code_seq start 4822;

-- --- Table -------------------------------------------------------------------
create table if not exists public.support_tickets (
  id           uuid primary key default gen_random_uuid(),   -- internal FK target
  -- The PUBLIC id rendered in the frontend badge (T-####); never a UUID.
  code         text not null unique
                 default ('T-' || to_char(nextval('public.tickets_code_seq'), 'FM0000')),
  -- Tenant linkage. ON DELETE SET NULL keeps the ticket ledger intact if a client
  -- is removed; client_name is snapshotted for display so client_id never has to
  -- be surfaced to the API.
  client_id    uuid references public.clients (id) on delete set null,
  client_name  text not null default '',
  subject      text not null,
  channel      public.ticket_channel not null default 'Portal',
  priority     public.ticket_priority not null default 'med',
  status       public.ticket_status not null default 'open',
  -- When the ticket was raised; `ago` is derived from this (never stored).
  opened_at    timestamptz not null default now(),
  created_by   uuid references public.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists support_tickets_client_id_idx  on public.support_tickets (client_id);
create index if not exists support_tickets_status_idx      on public.support_tickets (status);
create index if not exists support_tickets_opened_at_idx   on public.support_tickets (opened_at desc);

create trigger support_tickets_set_updated_at
  before update on public.support_tickets
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Clients are already excluded by is_staff() (redefined in 0010) - no client
-- select policy, so a portal client can NOT read/triage tickets. Any staff may
-- READ; only leads (owner/admin/manager) may INSERT/UPDATE (triage). No delete.
alter table public.support_tickets enable row level security;
alter table public.support_tickets force row level security;

create policy support_tickets_select on public.support_tickets
  for select using (public.is_staff());

create policy support_tickets_insert on public.support_tickets
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy support_tickets_update on public.support_tickets
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
