-- 0089_client_brand_kits.sql - the client's design identity, persisted and versioned.
--
-- WHAT ALREADY WORKS, so this is not rebuilding it. `integrations/site_analyzer.py`
-- measures a real site with Playwright at three viewports (typography, colours,
-- layout, logo, image assets, screenshots), and `services/site_design.py` interprets
-- one with Claude vision. Both are good, and both are AMNESIAC: the result is used
-- once and discarded.
--
-- WHY THAT BREAKS THE ACTUAL REQUIREMENT. "Generate 50 more pages that look like the
-- same developer built them" is not a per-page question. Re-analysing per page is
-- expensive, and worse, it is NON-DETERMINISTIC - the vision path can read the same
-- site slightly differently on two runs, so page 12 and page 40 drift apart while
-- each looks individually correct. A persisted kit makes the design a fixed input.
--
-- VERSIONED, because client sites change. A page published in March was built to the
-- kit as it was in March, and "why does this page look different?" must be answerable
-- rather than mysterious. The partial unique index enforces exactly one ACTIVE kit
-- per client while keeping every prior version readable.
--
-- `brand_assets` closes a gap the analyzer leaves: it captures the logo and image
-- URLs and never FETCHES them. A URL on a client's server is not an asset we can put
-- on a page - it can move, 404, or hotlink-block - so the bytes are stored and
-- content-hashed, and `wp_media_id` records where they landed once the plugin
-- sideloaded them into the client's own media library.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'brand_kit_source') then
    -- `analyzer` is MEASURED (computed CSS at three viewports); `vision` is
    -- INTERPRETED (a model reading a screenshot). Measured wins for tokens,
    -- interpreted wins for blueprint - keeping the distinction means a later reader
    -- knows how much to trust a given field.
    create type public.brand_kit_source as enum ('analyzer', 'vision', 'manual');
  end if;
  if not exists (select 1 from pg_type where typname = 'brand_asset_kind') then
    create type public.brand_asset_kind as enum ('logo', 'photo', 'icon', 'favicon');
  end if;
end $$;

create table if not exists public.brand_kits (
  id           uuid primary key default gen_random_uuid(),
  client_id    uuid not null references public.clients (id) on delete cascade,
  source_url   text not null default '',
  source       public.brand_kit_source not null default 'analyzer',
  version      integer not null default 1,
  palette      jsonb not null default '{}'::jsonb,
  typography   jsonb not null default '{}'::jsonb,
  spacing      jsonb not null default '{}'::jsonb,
  components   jsonb not null default '{}'::jsonb,
  -- The ordered section blueprint the Elementor/Gutenberg renderers consume.
  blueprint    jsonb not null default '[]'::jsonb,
  -- The raw multi-viewport measurements behind the derived values above. Kept so a
  -- disputed token can be traced to what was actually observed.
  raw_measurements jsonb not null default '{}'::jsonb,
  captured_at  timestamptz not null default now(),
  active       boolean not null default true,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create unique index if not exists brand_kits_active_per_client_idx
  on public.brand_kits (client_id) where active;
create index if not exists brand_kits_client_version_idx
  on public.brand_kits (client_id, version desc);

create trigger brand_kits_set_updated_at
  before update on public.brand_kits
  for each row execute function public.set_updated_at();

create table if not exists public.brand_assets (
  id          uuid primary key default gen_random_uuid(),
  kit_id      uuid not null references public.brand_kits (id) on delete cascade,
  kind        public.brand_asset_kind not null,
  source_url  text not null default '',
  -- Where OUR copy lives. The point of the table: a client-hosted URL is not an
  -- asset we can rely on.
  stored_key  text not null default '',
  sha256      text not null default '',
  width       integer,
  height      integer,
  -- Set once the WordPress plugin has sideloaded it into the client's own media
  -- library, so a republish reuses the upload instead of duplicating it.
  wp_media_id text not null default '',
  created_at  timestamptz not null default now()
);

create index if not exists brand_assets_kit_idx on public.brand_assets (kit_id, kind);
-- Content-addressed dedup: the same bytes fetched twice are one asset.
create unique index if not exists brand_assets_kit_sha_idx
  on public.brand_assets (kit_id, sha256) where sha256 <> '';

-- --- RLS ---------------------------------------------------------------------
alter table public.brand_kits enable row level security;
alter table public.brand_kits force row level security;
alter table public.brand_assets enable row level security;
alter table public.brand_assets force row level security;

create policy brand_kits_select on public.brand_kits
  for select using (public.is_staff());
create policy brand_kits_write on public.brand_kits
  for all using (public.is_staff()) with check (public.is_staff());

create policy brand_assets_select on public.brand_assets
  for select using (public.is_staff());
create policy brand_assets_write on public.brand_assets
  for all using (public.is_staff()) with check (public.is_staff());
