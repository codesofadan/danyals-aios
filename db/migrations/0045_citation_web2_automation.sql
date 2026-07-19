-- 0045_citation_web2_automation.sql - Off-page ACTIVE BUILDING: the schema for
-- actually submitting citations and publishing Web 2.0 properties, not just
-- monitoring them.
--
-- 0018/0028 gave the off-page module read-mostly MONITORING ledgers (a third-party
-- pull tells us whether a listing/backlink already exists) plus a Web 2.0 publish
-- pipeline gated on per-account credentials that were never wired. This migration
-- adds the three pieces that were missing before any of that pipeline could
-- SUBMIT something new on its own:
--
--   * business_profiles - the canonical NAP (name/address/phone/hours/categories)
--     a citation submission actually needs to fill a form with. Multi-location
--     (one client can have many), because a franchise/multi-branch business is a
--     real case and a single NAP column on `clients` cannot express it.
--   * directories        - the citation-directory CATALOG (market, automation
--     tier, link type, pricing note) - reference data, not tenant data. Seeded in
--     0046. `tier` is the same automation vocabulary the reference plan uses:
--     aggregator (one push, fans out downstream) / api (direct write) /
--     bot_fillable (a plain form our Playwright bot can fill, no CAPTCHA) /
--     captcha_assisted (the same, but a CAPTCHA-solver + human spot-check gate
--     it) / manual_only (no automatable path - catalogued for completeness, never
--     worked by a worker).
--   * citations pipeline columns - additive, exactly like 0028 additively grew
--     web2_properties: the existing monitoring ledger becomes ALSO the
--     submission ledger, so a directory row's lifecycle is one continuous story
--     (missing -> queued -> submitted -> verified consistent) instead of two
--     disconnected tables that have to be kept in sync by hand.
--
-- web2_platform grows from 4 to 17 values (ALTER TYPE ... ADD VALUE - safe as a
-- standalone statement; nothing in THIS file consumes a new value in the same
-- transaction, which is the one construct Postgres forbids). The new values are
-- every platform this pass adds a REAL Web2Publisher client for (see
-- integrations/web2_publishers.py); Python/TS keep the same enum-fidelity
-- discipline §3 of offpage.py already documents.

-- --- Enums ---------------------------------------------------------------------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'business_market') then
    -- GLOBAL covers the aggregator/API platforms that are not market-specific
    -- (Foursquare, Bing Places, Apple Business Connect, ...); everything else is
    -- one of the four markets the reference plan scopes to.
    create type public.business_market as enum ('US', 'UK', 'CA', 'AU', 'GLOBAL');
  end if;
  if not exists (select 1 from pg_type where typname = 'directory_tier') then
    create type public.directory_tier as enum
      ('aggregator', 'api', 'bot_fillable', 'captcha_assisted', 'manual_only');
  end if;
  if not exists (select 1 from pg_type where typname = 'link_rel') then
    create type public.link_rel as enum ('dofollow', 'nofollow', 'mixed', 'unknown');
  end if;
  if not exists (select 1 from pg_type where typname = 'citation_submit_status') then
    create type public.citation_submit_status as enum
      ('not_started', 'queued', 'submitting', 'submitted', 'verified', 'failed', 'blocked');
  end if;
end $$;

-- web2_platform: grow the existing enum (0018) rather than replace it - every
-- pre-existing row (platform = WordPress.com/Blogger/Tumblr/Medium) is untouched.
alter type public.web2_platform add value if not exists 'dev.to';
alter type public.web2_platform add value if not exists 'Write.as';
alter type public.web2_platform add value if not exists 'Telegra.ph';
alter type public.web2_platform add value if not exists 'Mataroa';
alter type public.web2_platform add value if not exists 'Ghost';
alter type public.web2_platform add value if not exists 'Mastodon';
alter type public.web2_platform add value if not exists 'GitHub Pages';
alter type public.web2_platform add value if not exists 'GitLab Pages';
alter type public.web2_platform add value if not exists 'Micro.blog';
alter type public.web2_platform add value if not exists 'Hashnode';
alter type public.web2_platform add value if not exists 'Hatena Blog';
alter type public.web2_platform add value if not exists 'LiveJournal';
alter type public.web2_platform add value if not exists 'Dreamwidth';

-- --- business_profiles: canonical NAP, multi-location ---------------------------
create table if not exists public.business_profiles (
  id             uuid primary key default gen_random_uuid(),
  client_id      uuid not null references public.clients (id) on delete cascade,
  client_name    text not null default '',
  label          text not null default 'Primary',    -- "Main - Bellevue" etc.
  business_name  text not null default '',
  address_line1  text not null default '',
  address_line2  text not null default '',
  city           text not null default '',
  region         text not null default '',            -- state/province/county
  postal_code    text not null default '',
  market         public.business_market not null default 'US',
  phone          text not null default '',
  website_url    text not null default '',
  categories     text[] not null default '{}',
  hours          jsonb not null default '{}'::jsonb,   -- {"mon": "9:00-17:00", ...}
  is_primary     boolean not null default true,
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists business_profiles_client_id_idx on public.business_profiles (client_id);

create trigger business_profiles_set_updated_at
  before update on public.business_profiles
  for each row execute function public.set_updated_at();

alter table public.business_profiles enable row level security;
alter table public.business_profiles force row level security;

create policy business_profiles_select on public.business_profiles
  for select using (public.is_staff());
create policy business_profiles_insert on public.business_profiles
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy business_profiles_update on public.business_profiles
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- directories: the citation-directory catalog (reference data) --------------
-- NOT client-scoped - every tenant shares the same catalog of "what sites exist
-- and how automatable are they". Still FORCE RLS (the gate has no allowlist): any
-- staff reads, only leads maintain the catalog (add/retire a directory).
create table if not exists public.directories (
  id              uuid primary key default gen_random_uuid(),
  name            text not null,
  url             text not null default '',
  market          public.business_market not null default 'US',
  tier            public.directory_tier not null,
  submit_method   text not null default '',   -- e.g. 'aggregator:data_axle', 'api:bing_places'
  link_rel        public.link_rel not null default 'unknown',
  price_note      text not null default '',
  automation_note text not null default '',
  active          boolean not null default true,
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now(),
  unique (name, market)
);

create index if not exists directories_market_idx on public.directories (market);
create index if not exists directories_tier_idx   on public.directories (tier);

create trigger directories_set_updated_at
  before update on public.directories
  for each row execute function public.set_updated_at();

alter table public.directories enable row level security;
alter table public.directories force row level security;

create policy directories_select on public.directories
  for select using (public.is_staff());
create policy directories_insert on public.directories
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy directories_update on public.directories
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- citations: additive submission-pipeline columns ----------------------------
-- Mirrors 0028's approach to web2_properties: the SAME table gains the columns a
-- write path needs, so a listing's monitoring state and its submission state are
-- one row, one story - never two ledgers that can silently disagree.
alter table public.citations
  add column if not exists directory_id        uuid references public.directories (id),
  add column if not exists business_profile_id uuid references public.business_profiles (id),
  add column if not exists submit_status public.citation_submit_status not null default 'not_started',
  -- 'api' | 'aggregator' | 'playwright' | 'apify' | 'manual' - which engine handled it.
  add column if not exists submit_method       text not null default '',
  add column if not exists proof_url           text not null default '',  -- screenshot/receipt
  add column if not exists external_ref        text,  -- a directory-side id, for an idempotent update
  add column if not exists cost                numeric(10, 4) not null default 0,
  add column if not exists error               text not null default '',
  add column if not exists submitted_at        timestamptz;

create index if not exists citations_submit_status_idx  on public.citations (submit_status);
create index if not exists citations_directory_id_idx   on public.citations (directory_id);
