-- 0035_keyword_research.sql - Part 8 Phase 2A (Keyword Research): the staff-only
-- keyword BANK + its clusters + saved lists.
--
-- The keyword_research tool is a ranking-grade keyword intelligence surface: a
-- staff analyst RESEARCHes a seed (DataForSEO metrics + the Part-7 content engine's
-- intent / clustering / winnability functions), and the fetched opportunity
-- keywords land in `keywords` - deduped per (client, keyword, geo), grouped into
-- `keyword_clusters`, optionally organised into saved `keyword_lists`.
--
--   * keywords         - one row per (client?, keyword, geo). client_id is NULLABLE:
--     an unassigned "bank" keyword belongs to no client yet (an analyst assigns it
--     later). client_name is a display SNAPSHOT so client_id never has to be
--     surfaced. volume/difficulty/cpc/competition are the provider metrics;
--     intent + intent_source + intent_confidence record the classification cascade
--     (provider -> serp_heuristic -> llm -> manual); opportunity is the derived
--     0-100 score; winnable is the difficulty-vs-authority verdict; source records
--     how the row entered the bank; metrics_confidence flags a low-confidence pull.
--   * keyword_clusters - a pillar + its supporting spokes (reuses cluster_terms).
--     dominant_intent + size + total_volume + avg_difficulty are aggregates;
--     serp_signature is a reserved jsonb slot for SERP-overlap fingerprints.
--   * keyword_lists / keyword_list_members - saved sets an analyst curates (a
--     content sprint, a client hand-off), a simple many-to-many over keywords.
--
-- Shapes are SERVER-AUTHORITATIVE (no frontend/lib type mirrors this module); the
-- module's schemas.py owns the wire shape and its own shape/enum unit tests. The
-- capitalised search_intent labels ('Informational' ...) ARE the display cell the
-- tool workspace renders verbatim.
--
-- RLS mirrors 0018_offpage exactly: any STAFF may READ (is_staff()); only LEADS
-- (owner/admin/manager) may INSERT/UPDATE. Clients get NO select policy, so the
-- whole keyword bank is staff-only - AND because is_staff() never references
-- client_id, a NULL-client bank row is correctly visible to staff yet invisible to
-- clients (who have no policy at all). The provider ingest (the research worker)
-- writes on service_role (BYPASSRLS) via ServiceKeywordStore. No delete policy in v1.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'search_intent') then
    -- Capitalised = the EXACT display cell the tool workspace renders.
    create type public.search_intent as enum
      ('Informational', 'Commercial', 'Transactional', 'Navigational', 'Local');
  end if;
  if not exists (select 1 from pg_type where typname = 'intent_source') then
    create type public.intent_source as enum
      ('provider', 'serp_heuristic', 'llm', 'manual');
  end if;
  if not exists (select 1 from pg_type where typname = 'keyword_source') then
    create type public.keyword_source as enum
      ('manual', 'research', 'import', 'gap', 'content');
  end if;
  if not exists (select 1 from pg_type where typname = 'metrics_confidence') then
    create type public.metrics_confidence as enum ('high', 'low');
  end if;
end $$;

-- Human-friendly stable code (KW-00001 ...), like the other module code sequences.
create sequence if not exists public.keyword_code_seq;

-- --- Clusters: the pillar + spokes topical map --------------------------------
-- Declared BEFORE keywords so keywords.cluster_id can reference it inline.
create table if not exists public.keyword_clusters (
  id              uuid primary key default gen_random_uuid(),
  -- NULLABLE tenant linkage (a cluster of un-assigned bank keywords has no client).
  client_id       uuid references public.clients (id) on delete set null,
  client_name     text not null default '',
  name            text not null,
  pillar_keyword  text not null default '',
  dominant_intent public.search_intent,
  size            integer not null default 0,
  total_volume    integer not null default 0,
  avg_difficulty  numeric(5,2) not null default 0,
  serp_signature  jsonb not null default '[]',
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists keyword_clusters_client_id_idx
  on public.keyword_clusters (client_id);

create trigger keyword_clusters_set_updated_at
  before update on public.keyword_clusters
  for each row execute function public.set_updated_at();

-- --- Keywords: the bank -------------------------------------------------------
create table if not exists public.keywords (
  id                uuid primary key default gen_random_uuid(),
  code              text not null unique
                    default 'KW-' || to_char(nextval('public.keyword_code_seq'), 'FM00000'),
  -- NULLABLE: an unassigned bank keyword belongs to no client yet. ON DELETE SET
  -- NULL returns a client's keywords to the bank (not delete them) if the client
  -- is removed. client_name is a display SNAPSHOT so client_id never leaks.
  client_id         uuid references public.clients (id) on delete set null,
  client_name       text not null default '',
  site_id           uuid references public.sites (id) on delete set null,
  keyword           text not null,
  geo               text,
  volume            integer not null default 0,
  difficulty        numeric(5,2) not null default 0 check (difficulty between 0 and 100),
  cpc               numeric(10,2) not null default 0,
  competition       numeric(4,3) not null default 0 check (competition between 0 and 1),
  intent            public.search_intent,
  intent_source     public.intent_source,
  intent_confidence numeric(4,3) not null default 0,
  cluster_id        uuid references public.keyword_clusters (id) on delete set null,
  target_url        text not null default '',
  opportunity       numeric(5,2) not null default 0,
  winnable          boolean,
  source            public.keyword_source not null default 'manual',
  metrics_confidence public.metrics_confidence not null default 'high',
  provider          text not null default '',
  tags              text[] not null default '{}',
  fetched_at        timestamptz,
  created_by        uuid references public.users (id) on delete set null,
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),
  -- One row per (client, keyword, geo) - for BANK rows too. NULLS NOT DISTINCT
  -- (PG15+) makes NULL = NULL for uniqueness, so an unassigned bank row
  -- (client_id NULL) or a geo-less row dedupes exactly like a client-scoped one.
  -- Default SQL NULL semantics would treat every NULL as distinct and silently
  -- admit duplicate bank rows on a re-add, which `on conflict (client_id, keyword,
  -- geo) do nothing` could never catch.
  unique nulls not distinct (client_id, keyword, geo)
);

create index if not exists keywords_client_id_idx  on public.keywords (client_id);
create index if not exists keywords_cluster_id_idx  on public.keywords (cluster_id);
create index if not exists keywords_intent_idx      on public.keywords (intent);

create trigger keywords_set_updated_at
  before update on public.keywords
  for each row execute function public.set_updated_at();

-- --- Saved lists (a many-to-many over keywords) -------------------------------
create table if not exists public.keyword_lists (
  id          uuid primary key default gen_random_uuid(),
  client_id   uuid references public.clients (id) on delete set null,
  name        text not null,
  created_by  uuid references public.users (id) on delete set null,
  created_at  timestamptz not null default now()
);

create index if not exists keyword_lists_client_id_idx on public.keyword_lists (client_id);

create table if not exists public.keyword_list_members (
  list_id     uuid not null references public.keyword_lists (id) on delete cascade,
  keyword_id  uuid not null references public.keywords (id) on delete cascade,
  created_at  timestamptz not null default now(),
  primary key (list_id, keyword_id)
);

create index if not exists keyword_list_members_keyword_idx
  on public.keyword_list_members (keyword_id);

-- --- RLS ---------------------------------------------------------------------
-- Clients are excluded by is_staff() (they get NO base-table select policy), so a
-- portal client can NOT read the keyword bank. Any staff may READ; only leads
-- (owner/admin/manager) may INSERT/UPDATE. is_staff() never references client_id,
-- so a NULL-client bank row is visible to staff yet invisible to clients. The
-- research worker ingest runs on service_role (BYPASSRLS). No delete policy in v1.
alter table public.keyword_clusters enable row level security;
alter table public.keyword_clusters force row level security;
alter table public.keywords enable row level security;
alter table public.keywords force row level security;
alter table public.keyword_lists enable row level security;
alter table public.keyword_lists force row level security;
alter table public.keyword_list_members enable row level security;
alter table public.keyword_list_members force row level security;

create policy keyword_clusters_select on public.keyword_clusters
  for select using (public.is_staff());
create policy keyword_clusters_insert on public.keyword_clusters
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy keyword_clusters_update on public.keyword_clusters
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy keywords_select on public.keywords
  for select using (public.is_staff());
create policy keywords_insert on public.keywords
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy keywords_update on public.keywords
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy keyword_lists_select on public.keyword_lists
  for select using (public.is_staff());
create policy keyword_lists_insert on public.keyword_lists
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy keyword_lists_update on public.keyword_lists
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy keyword_list_members_select on public.keyword_list_members
  for select using (public.is_staff());
create policy keyword_list_members_insert on public.keyword_list_members
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy keyword_list_members_update on public.keyword_list_members
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
