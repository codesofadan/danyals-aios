-- 0021_milestones.sql - Part 7 Module (Milestones): the client-facing project
-- timeline / engagement lifecycle.
--
-- Every client project moves through a FIXED 5-stage SEO-engagement lifecycle
-- (onboarding -> baseline -> content -> authority -> reporting). Stages are
-- AUTO-ADVANCED from job/audit/publish/payment events - never edited by a client.
-- Admin watches & manages them; the "recently auto-advanced" feed is derived from
-- the most-recently-touched stages. Shapes mirror frontend/lib/milestones.ts
-- (ClientProject + Stage + AutoAdvance); the internal client_id never leaks
-- (client_name/init/accent are display SNAPSHOTS, like content_jobs).
--
-- SHAPE: a parent client_projects row + exactly 5 project_stages children (one per
-- stage_key, unique per project). This serializes cleanly to a ClientProject with
-- its ordered stages, and makes the auto-advance write path a single-row UPDATE.
-- The lifecycle order is the stage_key ENUM order (Postgres sorts enums by their
-- definition order), so `order by stage_key` yields the timeline order.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
-- NOTE (§3 enum fidelity): project_health is SEPARATE from stage_status - they
-- share the label 'completed' but are DISTINCT types and must never be merged.
do $$ begin
  if not exists (select 1 from pg_type where typname = 'stage_key') then
    create type public.stage_key as enum
      ('onboarding', 'baseline', 'content', 'authority', 'reporting');
  end if;
  if not exists (select 1 from pg_type where typname = 'stage_status') then
    create type public.stage_status as enum
      ('completed', 'in_progress', 'upcoming', 'blocked');
  end if;
  if not exists (select 1 from pg_type where typname = 'project_health') then
    create type public.project_health as enum ('on_track', 'at_risk', 'completed');
  end if;
end $$;

-- --- Parent: one project per client engagement -------------------------------
create table if not exists public.client_projects (
  id           uuid primary key default gen_random_uuid(),
  -- Tenant linkage. ON DELETE CASCADE removes the project timeline with its
  -- client; client_name/init/accent are display SNAPSHOTS so client_id never has
  -- to be surfaced to the API.
  client_id    uuid references public.clients (id) on delete cascade,
  client_name  text not null default '',           -- display snapshot (ClientProject.client)
  site         text not null default '',           -- primary domain (ClientProject.site)
  init         text not null default '',           -- avatar initials (ClientProject.init)
  accent       text not null default '',           -- avatar accent slot (contract key `c`)
  health       public.project_health not null default 'on_track',
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists client_projects_client_id_idx  on public.client_projects (client_id);
create index if not exists client_projects_created_at_idx on public.client_projects (created_at desc);

create trigger client_projects_set_updated_at
  before update on public.client_projects
  for each row execute function public.set_updated_at();

-- --- Child: the 5 ordered lifecycle stages of a project ----------------------
create table if not exists public.project_stages (
  id           uuid primary key default gen_random_uuid(),
  project_id   uuid not null references public.client_projects (id) on delete cascade,
  stage_key    public.stage_key not null,
  status       public.stage_status not null default 'upcoming',
  auto_source  text not null default '',           -- what job/audit advances (or blocks) this stage
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  -- One row per stage per project; the 5 lifecycle stages are always present.
  unique (project_id, stage_key)
);

create index if not exists project_stages_project_id_idx on public.project_stages (project_id);
-- Newest-touched first: the auto-advance feed reads by this.
create index if not exists project_stages_updated_at_idx on public.project_stages (updated_at desc);

create trigger project_stages_set_updated_at
  before update on public.project_stages
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Clients are already excluded by is_staff() (redefined in 0010) - they never get
-- a base-table select policy here, so a portal client can NOT read/edit stages
-- (mirrors 0011/0017). Any staff may READ; only leads (owner/admin/manager) may
-- INSERT/UPDATE - there are NO manual stage edits from clients. The system/worker
-- auto-advance path runs on service_role (BYPASSRLS), so an event can advance a
-- stage regardless of these policies. No delete policy/endpoint in v1.
alter table public.client_projects enable row level security;
alter table public.client_projects force row level security;
alter table public.project_stages enable row level security;
alter table public.project_stages force row level security;

create policy client_projects_select on public.client_projects
  for select using (public.is_staff());
create policy client_projects_insert on public.client_projects
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy client_projects_update on public.client_projects
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy project_stages_select on public.project_stages
  for select using (public.is_staff());
create policy project_stages_insert on public.project_stages
  for insert with check (public.current_app_role() in ('owner', 'admin', 'manager'));
create policy project_stages_update on public.project_stages
  for update
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
