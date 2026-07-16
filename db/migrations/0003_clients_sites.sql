-- 0003_clients_sites.sql - the agency's clients + their sites (tenant core).
--
-- These are agency-internal records managed by staff. Client-portal users (a
-- separate role introduced with the Portal module) will get row-scoped policies
-- then; for now every policy is staff-scoped. WordPress credentials are NOT
-- stored here - per-site creds live encrypted in the Key Vault (0005).
--
-- Portal login passwords are deliberately NOT persisted: client logins are
-- Supabase Auth users, so there is no plaintext to store or reveal.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'sub_tier') then
    create type public.sub_tier as enum ('Starter', 'Growth', 'Scale');
  end if;
  if not exists (select 1 from pg_type where typname = 'sub_status') then
    create type public.sub_status as enum ('active', 'trial', 'past_due', 'paused');
  end if;
end $$;

create table public.clients (
  id                   uuid primary key default gen_random_uuid(),
  name                 text not null,
  industry             text not null default '',
  since_year           int,
  -- Primary contact (frontend Contact: name/role/email + avatar accent).
  contact_name         text not null default '',
  contact_role         text not null default '',
  contact_email        text not null default '',
  contact_color        text not null default '#7B69EE',
  -- Subscription (billing) tier + status. Delivery tier is added in 0006.
  tier                 public.sub_tier not null default 'Starter',
  status               public.sub_status not null default 'trial',
  renews_at            date,
  mrr                  integer not null default 0,
  -- Portal access metadata (NO password column - see header).
  portal_admin         text not null default '',
  portal_seats         integer not null default 0,
  portal_two_fa        boolean not null default false,
  portal_last_login_at timestamptz,
  created_at           timestamptz not null default now(),
  updated_at           timestamptz not null default now()
);

create trigger clients_set_updated_at
  before update on public.clients
  for each row execute function public.set_updated_at();

create table public.sites (
  id         uuid primary key default gen_random_uuid(),
  client_id  uuid not null references public.clients (id) on delete cascade,
  domain     text not null,
  cms_type   text not null default 'wordpress',
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create index sites_client_id_idx on public.sites (client_id);

create trigger sites_set_updated_at
  before update on public.sites
  for each row execute function public.set_updated_at();

-- --- RLS: clients -------------------------------------------------------------
alter table public.clients enable row level security;
alter table public.clients force row level security;

create policy clients_select on public.clients
  for select using (public.is_staff());

-- manage_clients holders (owner/admin/manager) may write.
create policy clients_modify on public.clients
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- RLS: sites ---------------------------------------------------------------
alter table public.sites enable row level security;
alter table public.sites force row level security;

create policy sites_select on public.sites
  for select using (public.is_staff());

create policy sites_modify on public.sites
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
