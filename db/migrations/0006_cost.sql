-- 0006_cost.sql - the cost-control subsystem: per-client budgets, the per-feature
-- dial, the org-wide daily spend-stop, and the per-call cost log.
--
-- The reusable gate (app/services/cost_gate.py) reads these before any paid call:
--   dial allows? -> cached? -> under client cap? -> under daily stop? -> call + log.
-- Budget/daily writes flow through the service_role gate; cost_log is append-only.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'dial_mode') then
    create type public.dial_mode as enum ('api', 'byhand', 'off');
  end if;
end $$;

-- --- Per-client monthly budget caps ------------------------------------------
create table public.client_budgets (
  client_id  uuid primary key references public.clients (id) on delete cascade,
  cap        integer not null default 0,     -- monthly ceiling (USD); 0 = uncapped
  spent      integer not null default 0,     -- month-to-date (USD), maintained by the gate
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);
create trigger client_budgets_set_updated_at
  before update on public.client_budgets
  for each row execute function public.set_updated_at();

-- --- Per-feature cost dial (mode is mutable; metadata lives in code) ----------
create table public.cost_dial (
  feature_key text primary key,
  mode        public.dial_mode not null default 'off',
  updated_at  timestamptz not null default now()
);
create trigger cost_dial_set_updated_at
  before update on public.cost_dial
  for each row execute function public.set_updated_at();

-- --- Org daily spend-stop (singleton) ----------------------------------------
create table public.cost_settings (
  id         boolean primary key default true,
  daily_stop numeric(10, 2) not null default 75,   -- daily spend ceiling (USD)
  halted     boolean not null default false,        -- manual kill-switch
  updated_at timestamptz not null default now(),
  constraint cost_settings_singleton check (id)
);
insert into public.cost_settings (id) values (true) on conflict do nothing;
create trigger cost_settings_set_updated_at
  before update on public.cost_settings
  for each row execute function public.set_updated_at();

-- --- Per-call cost log (append-only) -----------------------------------------
create table public.cost_log (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid references public.clients (id) on delete set null,
  client_name text not null default '',
  job_id      text not null default '',
  job_type    text not null default '',
  provider    text not null default '',
  cost        numeric(10, 2) not null default 0,
  cached      boolean not null default false,
  created_at  timestamptz not null default now()
);
create index cost_log_created_at_idx on public.cost_log (created_at desc);

-- Atomic budget increment (avoids a read-modify-write race under concurrency).
create or replace function public.add_budget_spend(p_client uuid, p_amount numeric)
returns void language sql security definer set search_path = ''
as $$
  insert into public.client_budgets (client_id, spent) values (p_client, p_amount)
  on conflict (client_id) do update set spent = public.client_budgets.spent + excluded.spent;
$$;
revoke execute on function public.add_budget_spend(uuid, numeric) from public;
grant execute on function public.add_budget_spend(uuid, numeric) to service_role;

-- --- RLS ----------------------------------------------------------------------
alter table public.client_budgets enable row level security;
alter table public.client_budgets force row level security;
create policy client_budgets_select on public.client_budgets
  for select using (public.is_staff());
create policy client_budgets_modify on public.client_budgets
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

alter table public.cost_dial enable row level security;
alter table public.cost_dial force row level security;
create policy cost_dial_select on public.cost_dial
  for select using (public.is_staff());
create policy cost_dial_modify on public.cost_dial
  for all
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));

alter table public.cost_settings enable row level security;
alter table public.cost_settings force row level security;
create policy cost_settings_select on public.cost_settings
  for select using (public.is_staff());
create policy cost_settings_modify on public.cost_settings
  for all
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));

-- cost_log: staff read only; writes happen via the service_role gate.
alter table public.cost_log enable row level security;
alter table public.cost_log force row level security;
create policy cost_log_select on public.cost_log
  for select using (public.is_staff());
