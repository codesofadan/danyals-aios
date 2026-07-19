-- 0047_site_analytics.sql - live Google Search Console + GA4 read integration.
--
-- Unlike GBP (0039), the Search Console (`webmasters.readonly`) and Analytics Data
-- API (`analytics.readonly`) scopes are standard OAuth - no Google approval gate -
-- so this module is buildable and connectable today, gated only on Danyal loading
-- ONE shared Google Cloud OAuth client (app/config.py `google_oauth_client_id` /
-- `google_oauth_client_secret`) that covers both scopes in a single consent screen.
--
-- Two tables, one per property type, mirroring `gbp_profiles`' shape exactly:
--   * gsc_properties - one row per client's connected Search Console site, holding
--     a trailing-28-day snapshot (clicks/impressions/ctr/position + top queries).
--   * ga4_properties - one row per client's connected GA4 property, holding a
--     trailing-28-day snapshot (sessions/users/conversions).
-- `oauth_vault_ref` POINTS at the sealed per-client refresh token (a vault key id,
-- kind='client_access') - the token itself lives ONLY in public.vault_keys,
-- AES-GCM sealed. Never store a secret in this table (same discipline as 0039).

create table if not exists public.gsc_properties (
  id                 uuid primary key default gen_random_uuid(),
  client_id          uuid not null references public.clients (id) on delete cascade,
  client_name        text not null default '',
  site_url           text not null default '',
  oauth_connected    boolean not null default false,
  oauth_vault_ref    text,
  last_synced_at     timestamptz,
  clicks_28d         integer not null default 0,
  impressions_28d    integer not null default 0,
  ctr_28d            numeric(6, 4) not null default 0,
  avg_position_28d   numeric(6, 2) not null default 0,
  top_queries        jsonb not null default '[]',
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists gsc_properties_client_id_idx on public.gsc_properties (client_id);

create trigger gsc_properties_set_updated_at
  before update on public.gsc_properties
  for each row execute function public.set_updated_at();

create table if not exists public.ga4_properties (
  id                 uuid primary key default gen_random_uuid(),
  client_id          uuid not null references public.clients (id) on delete cascade,
  client_name        text not null default '',
  property_id        text not null default '',
  oauth_connected    boolean not null default false,
  oauth_vault_ref    text,
  last_synced_at     timestamptz,
  sessions_28d       integer not null default 0,
  users_28d          integer not null default 0,
  conversions_28d    integer not null default 0,
  created_at         timestamptz not null default now(),
  updated_at         timestamptz not null default now()
);

create index if not exists ga4_properties_client_id_idx on public.ga4_properties (client_id);

create trigger ga4_properties_set_updated_at
  before update on public.ga4_properties
  for each row execute function public.set_updated_at();

alter table public.gsc_properties enable row level security;
alter table public.gsc_properties force row level security;
alter table public.ga4_properties enable row level security;
alter table public.ga4_properties force row level security;

create policy gsc_properties_select on public.gsc_properties
  for select using (public.is_staff());
create policy gsc_properties_insert on public.gsc_properties
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy gsc_properties_update on public.gsc_properties
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy ga4_properties_select on public.ga4_properties
  for select using (public.is_staff());
create policy ga4_properties_insert on public.ga4_properties
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy ga4_properties_update on public.ga4_properties
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
