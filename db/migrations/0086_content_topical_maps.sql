-- 0086_content_topical_maps.sql - the plan of which pages exist and how they link.
--
-- WHAT THIS MAKES POSSIBLE that nothing currently can. Today every page is planned in
-- isolation: `content_generator` invents internal-link slugs like `/{slug(spoke)}`
-- that may point at nothing, and `content_qa._score_internal_linking` can only count
-- the links on the page in front of it. Both are structural consequences of having no
-- record of the OTHER pages.
--
-- With a map:
--   * a spoke can link to a hub that exists, because the hub is a row;
--   * cannibalisation is detectable, because two nodes targeting one primary keyword
--     is a query rather than a judgement call;
--   * `internal_link_edges` is the graph the ported `content_lint.links` auditor
--     needs - it checks orphans, silo boundaries and spoke->hub routing, none of
--     which a per-page check can see;
--   * breadcrumbs become derivable from the parent chain, which is why
--     `content_schema` has never emitted a BreadcrumbList.
--
-- The doctrine's rule is that a node becomes a PAGE only when it carries a real
-- first-party specific. `lint_report` stores the evidence-gate result, so an unbacked
-- promotion is recorded rather than argued about.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'topical_map_status') then
    create type public.topical_map_status as enum
      ('draft', 'linted', 'rejected', 'active', 'superseded');
  end if;
  if not exists (select 1 from pg_type where typname = 'map_node_status') then
    -- `index_only` is coverage the site has deliberately NOT spent a page on. It is
    -- a legitimate terminal state, not a backlog item - the doctrine's evidence gate
    -- exempts it precisely so a map is not padded with thin pages to look complete.
    create type public.map_node_status as enum
      ('planned', 'index_only', 'briefed', 'drafting', 'published', 'skipped');
  end if;
  if not exists (select 1 from pg_type where typname = 'map_node_role') then
    create type public.map_node_role as enum ('hub', 'spoke');
  end if;
end $$;

create table if not exists public.topical_maps (
  id            uuid primary key default gen_random_uuid(),
  engagement_id uuid not null references public.content_engagements (id) on delete cascade,
  -- The plan the map was built from. SET NULL rather than CASCADE: a map outlives the
  -- keyword pull that seeded it, and deleting a stale plan must not delete the
  -- strategy built on top of it.
  plan_id       uuid references public.keyword_plans (id) on delete set null,
  status        public.topical_map_status not null default 'draft',
  -- The evidence-gate result from `content_lint.topical_map`. Stored, not recomputed:
  -- it is the record of WHY a node was allowed to become a page.
  lint_report   jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

create index if not exists topical_maps_engagement_idx
  on public.topical_maps (engagement_id, created_at desc);

create trigger topical_maps_set_updated_at
  before update on public.topical_maps
  for each row execute function public.set_updated_at();

create table if not exists public.topical_map_nodes (
  id                uuid primary key default gen_random_uuid(),
  map_id            uuid not null references public.topical_maps (id) on delete cascade,
  -- Self-FK: the hub/spoke tree. This is what makes a BreadcrumbList derivable.
  parent_id         uuid references public.topical_map_nodes (id) on delete set null,
  role              public.map_node_role not null default 'spoke',
  silo              text not null default '',
  page_type         text not null default 'service',
  primary_keyword   text not null,
  secondary_keywords text[] not null default '{}',
  intent            text not null default '',
  target_city       text not null default '',
  priority          integer not null default 0,
  target_words      integer not null default 0,
  cluster_key       text not null default '',
  status            public.map_node_status not null default 'planned',
  -- The doctrine's promotion gate, kept as DATA so it can be queried and reported:
  -- a node may only reach `briefed` with a real first-party specific behind it.
  evidence          text not null default '',
  info_gain_thesis  text not null default '',
  -- SET NULL, not CASCADE: deleting a job must not delete the plan that called for
  -- the page. The node reverts to planned and can be re-run.
  content_job_id    uuid references public.content_jobs (id) on delete set null,
  published_url     text not null default '',
  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now()
);

create index if not exists topical_map_nodes_map_idx
  on public.topical_map_nodes (map_id, priority desc);
create index if not exists topical_map_nodes_status_idx
  on public.topical_map_nodes (map_id, status);
create index if not exists topical_map_nodes_job_idx
  on public.topical_map_nodes (content_job_id)
  where content_job_id is not null;
-- Cannibalisation becomes a UNIQUE CONSTRAINT rather than a report: two nodes in one
-- map cannot target the same primary keyword. Case-insensitive, because "AC Repair
-- Austin" and "ac repair austin" compete for exactly the same query.
create unique index if not exists topical_map_nodes_primary_unique_idx
  on public.topical_map_nodes (map_id, lower(primary_keyword));

create trigger topical_map_nodes_set_updated_at
  before update on public.topical_map_nodes
  for each row execute function public.set_updated_at();

create table if not exists public.internal_link_edges (
  id           uuid primary key default gen_random_uuid(),
  map_id       uuid not null references public.topical_maps (id) on delete cascade,
  from_node_id uuid not null references public.topical_map_nodes (id) on delete cascade,
  to_node_id   uuid not null references public.topical_map_nodes (id) on delete cascade,
  anchor_text  text not null default '',
  rationale    text not null default '',
  -- Whether the link actually made it into the published page. The gap between
  -- planned and placed is the internal-linking debt nobody can currently see.
  placed       boolean not null default false,
  created_at   timestamptz not null default now()
);

create index if not exists internal_link_edges_map_idx
  on public.internal_link_edges (map_id);
create index if not exists internal_link_edges_from_idx
  on public.internal_link_edges (from_node_id);
create index if not exists internal_link_edges_to_idx
  on public.internal_link_edges (to_node_id);
-- One edge per direction per pair: a page linking to another page twice with two
-- anchors is a duplicate, not a stronger signal.
create unique index if not exists internal_link_edges_unique_idx
  on public.internal_link_edges (from_node_id, to_node_id);

-- --- RLS ---------------------------------------------------------------------
alter table public.topical_maps enable row level security;
alter table public.topical_maps force row level security;
alter table public.topical_map_nodes enable row level security;
alter table public.topical_map_nodes force row level security;
alter table public.internal_link_edges enable row level security;
alter table public.internal_link_edges force row level security;

create policy topical_maps_select on public.topical_maps
  for select using (public.is_staff());
create policy topical_maps_write on public.topical_maps
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

-- Nodes are writable by any staff member: a specialist moves a node from planned to
-- briefed as ordinary production work. The MAP's shape stays lead-only above.
create policy topical_map_nodes_select on public.topical_map_nodes
  for select using (public.is_staff());
create policy topical_map_nodes_write on public.topical_map_nodes
  for all using (public.is_staff()) with check (public.is_staff());

create policy internal_link_edges_select on public.internal_link_edges
  for select using (public.is_staff());
create policy internal_link_edges_write on public.internal_link_edges
  for all using (public.is_staff()) with check (public.is_staff());
