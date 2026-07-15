-- 0018_offpage.sql - Part 7 Module 03 (Off-page): backlink + citation MONITORING
-- and the Web 2.0 property ledger.
--
-- Three read-mostly monitoring ledgers, one row per signal, all client-scoped:
--   * backlinks   - the live referring-domain profile. status new|lost|toxic is a
--     MONITORING verdict (new = freshly discovered, lost = dropped since the last
--     crawl, toxic = high spam-score link flagged for a disavow review). authority
--     + spam are 0-100 scores (DataForSEO / a CSV export populate them in a later
--     chunk; the CSV path needs no key).
--   * citations   - local directory / NAP listings. nap_status consistent|
--     inconsistent|missing drives the action Submit (missing -> create a listing) vs
--     Update (drifted/verify an existing one); `note` records what drifted.
--   * web2_properties - branded Web 2.0 posts (the PUBLISH pipeline lands in a later
--     chunk; this table + its read endpoints exist NOW to match the frontend). Every
--     placement is human-approved authority work, never link spam.
--
-- Shapes mirror frontend/lib/offpage.ts (Backlink / Citation / Web2Property). The
-- internal client_id NEVER leaks - client_name is a display SNAPSHOT (like
-- content_jobs / client_projects). §3 enum fidelity: web2_platform MUST include
-- 'Medium' (the full set is WordPress.com|Blogger|Tumblr|Medium).
--
-- RLS mirrors 0021_milestones exactly: any staff may READ; only leads (owner/admin/
-- manager) may INSERT/UPDATE. Clients are excluded by is_staff() (no base-table
-- select policy). The PAID-TIER gate (off-page is a paid deliverable) is enforced at
-- the SERVICE layer, not in RLS. The monitoring write path (DataForSEO/BrightLocal
-- ingest) runs on service_role (BYPASSRLS) in a later chunk. No delete policy in v1.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'backlink_status') then
    create type public.backlink_status as enum ('new', 'lost', 'toxic');
  end if;
  if not exists (select 1 from pg_type where typname = 'nap_status') then
    create type public.nap_status as enum ('consistent', 'inconsistent', 'missing');
  end if;
  if not exists (select 1 from pg_type where typname = 'citation_action') then
    -- Verbatim from offpage.ts CitationAction (capitalised, they are UI verbs).
    create type public.citation_action as enum ('Submit', 'Update');
  end if;
  if not exists (select 1 from pg_type where typname = 'web2_platform') then
    -- §3: MUST include 'Medium' - the full offpage.ts Web2Platform set.
    create type public.web2_platform as enum
      ('WordPress.com', 'Blogger', 'Tumblr', 'Medium');
  end if;
  if not exists (select 1 from pg_type where typname = 'web2_verified') then
    create type public.web2_verified as enum ('verified', 'pending');
  end if;
end $$;

-- --- Backlinks: the referring-domain monitoring ledger ------------------------
create table if not exists public.backlinks (
  id           uuid primary key default gen_random_uuid(),
  -- Tenant linkage. ON DELETE CASCADE drops a client's monitoring rows with it;
  -- client_name is a display SNAPSHOT so client_id never has to be surfaced.
  client_id    uuid references public.clients (id) on delete cascade,
  client_name  text not null default '',
  ref_domain   text not null,                       -- referring domain
  anchor       text not null default '',            -- anchor text
  authority    integer not null default 0 check (authority between 0 and 100),
  spam         integer not null default 0 check (spam between 0 and 100),
  first_seen   date,                                -- discovery date
  status       public.backlink_status not null default 'new',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists backlinks_client_id_idx on public.backlinks (client_id);
create index if not exists backlinks_status_idx     on public.backlinks (status);

create trigger backlinks_set_updated_at
  before update on public.backlinks
  for each row execute function public.set_updated_at();

-- --- Citations: the local directory / NAP ledger -----------------------------
create table if not exists public.citations (
  id           uuid primary key default gen_random_uuid(),
  client_id    uuid references public.clients (id) on delete cascade,
  client_name  text not null default '',
  directory    text not null,                       -- the directory / data aggregator
  nap_status   public.nap_status not null default 'missing',
  action       public.citation_action not null default 'Submit',
  note         text not null default '',            -- what drifted / listing detail
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists citations_client_id_idx  on public.citations (client_id);
create index if not exists citations_nap_status_idx  on public.citations (nap_status);

create trigger citations_set_updated_at
  before update on public.citations
  for each row execute function public.set_updated_at();

-- --- Web 2.0 properties: the branded-post ledger (read endpoints now) ---------
create table if not exists public.web2_properties (
  id           uuid primary key default gen_random_uuid(),
  client_id    uuid references public.clients (id) on delete cascade,
  client_name  text not null default '',
  platform     public.web2_platform not null,
  post_url     text not null default '',
  anchor       text not null default '',
  verified     public.web2_verified not null default 'pending',
  published_at date,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists web2_properties_client_id_idx on public.web2_properties (client_id);
create index if not exists web2_properties_platform_idx   on public.web2_properties (platform);

create trigger web2_properties_set_updated_at
  before update on public.web2_properties
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Clients are already excluded by is_staff() (redefined in 0010) - they never get
-- a base-table select policy here, so a portal client can NOT read the off-page
-- ledgers (mirrors 0011/0017/0021). Any staff may READ; only leads (owner/admin/
-- manager) may INSERT/UPDATE - the paid-tier gate lives at the service layer, and
-- the monitoring ingest path runs on service_role (BYPASSRLS). No delete in v1.
alter table public.backlinks enable row level security;
alter table public.backlinks force row level security;
alter table public.citations enable row level security;
alter table public.citations force row level security;
alter table public.web2_properties enable row level security;
alter table public.web2_properties force row level security;

create policy backlinks_select on public.backlinks
  for select using (public.is_staff());
create policy backlinks_insert on public.backlinks
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy backlinks_update on public.backlinks
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy citations_select on public.citations
  for select using (public.is_staff());
create policy citations_insert on public.citations
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy citations_update on public.citations
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy web2_properties_select on public.web2_properties
  for select using (public.is_staff());
create policy web2_properties_insert on public.web2_properties
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy web2_properties_update on public.web2_properties
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
