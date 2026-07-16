-- 0034_portal_milestones_views.sql - Part 8 (Client Portal): the client's own
-- engagement timeline, over the EXISTING 0021 Milestones tables (no new table).
--
-- The portal Milestones surface (frontend ClientProject + Stage in lib/milestones.ts)
-- is the SAME project timeline the admin manages in the Milestones module - the
-- client simply sees its OWN row. 0021 gives clients no base-table select policy
-- (they are excluded by is_staff()); these two security-barrier views are the
-- entire client-visible surface, each self-filtered to current_client_id() and
-- exposing only the columns ClientProjectResponse.from_rows / StageResponse.from_row
-- consume (the internal client_id never surfaces - init/accent are display snapshots).

-- portal_project: the caller's own client_projects row(s). Exposes the project's
-- OWN uuid (id) - never the tenant client_id - plus the display snapshots + health.
create or replace view public.portal_project
  with (security_barrier = true) as
  select
    id,
    client_name,
    site,
    init,
    accent,
    health
  from public.client_projects
  where client_id = public.current_client_id();

comment on view public.portal_project is
  'Client-safe view of the caller''s own public.client_projects (no client_id), '
  'self-filtered to current_client_id().';

-- portal_project_stages: the lifecycle stages of the caller's own project(s),
-- joined through client_projects so the tenant filter applies. project_id is the
-- parent project''s own uuid (already exposed as portal_project.id), used to group
-- stages under their project.
create or replace view public.portal_project_stages
  with (security_barrier = true) as
  select
    s.project_id,
    s.stage_key,
    s.status,
    s.auto_source,
    s.updated_at
  from public.project_stages s
  join public.client_projects p on p.id = s.project_id
  where p.client_id = public.current_client_id();

comment on view public.portal_project_stages is
  'Client-safe view of public.project_stages for the caller''s own project(s), '
  'self-filtered through client_projects.client_id = current_client_id().';

grant select on public.portal_project to authenticated, anon;
grant select on public.portal_project_stages to authenticated, anon;
