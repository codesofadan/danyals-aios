-- 0022_upsells.sql - Part 7 Module (Upsells): the Fiverr upsell catalogue.
--
-- Upsell cards deliberately link OUT to the agency's Fiverr gigs (not internal
-- services) to keep the agency's Fiverr-centered public brand front and center inside
-- the client portal. Admin CURATES them here; the active ones render as clickable
-- gig cards for every client. Shapes mirror frontend/lib/upsells.ts (Upsell).
--
-- AGENCY-GLOBAL: there is NO client_id - one shared catalogue for the whole
-- agency (unlike the tenant-scoped tables). Any staff may READ (the curation +
-- portal-render surface); only owner/admin MANAGE (create/edit/toggle/reorder).
-- Clients never touch this table (is_staff() excludes them, and there is no client
-- select policy); the portal renders the active cards through the server, not via
-- a client base-table read.

-- --- Table -------------------------------------------------------------------
create table if not exists public.upsells (
  id           uuid primary key default gen_random_uuid(),
  title        text not null,
  description  text not null default '',
  fiverr_url   text not null default '#',           -- real gig URL or "#" (contract key `fiverrUrl`)
  active       boolean not null default true,
  clicks30d    integer not null default 0,          -- portal clicks in the last 30 days (tracked)
  price        numeric not null default 0,          -- "starting at" USD on Fiverr
  rating       numeric not null default 0,          -- gig star rating
  reviews      integer not null default 0,          -- review count
  icon         text not null default '',            -- material symbol
  color        text not null default '',            -- accent for the card badge
  sort_order   integer not null default 0,          -- admin-curated display order
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

-- Curated display order, then insertion order as a stable tiebreaker.
create index if not exists upsells_sort_order_idx on public.upsells (sort_order, created_at);

create trigger upsells_set_updated_at
  before update on public.upsells
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
alter table public.upsells enable row level security;
alter table public.upsells force row level security;

create policy upsells_select on public.upsells
  for select using (public.is_staff());
create policy upsells_insert on public.upsells
  for insert with check (public.current_app_role() in ('owner', 'admin'));
create policy upsells_update on public.upsells
  for update
  using (public.current_app_role() in ('owner', 'admin'))
  with check (public.current_app_role() in ('owner', 'admin'));
