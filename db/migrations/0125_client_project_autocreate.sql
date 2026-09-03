-- 0125_client_project_autocreate.sql - give every client the project row that
-- 0021 assumed would exist.
--
-- THE BUG: 0021 built the Milestones module (client_projects + exactly 5
-- project_stages per project) and the read paths for it - the admin
-- /milestones board, the portal /portal/milestones timeline, and the
-- `milestones` series in the client report pack. Nothing ever WROTE those rows.
-- app/db/milestones_repo.py exposes list_projects / list_stages /
-- recent_advances / advance_stage and no insert; there is no `insert into
-- client_projects` anywhere in app/ or db/. So the tables sat empty forever:
-- every client's portal 404'd on /portal/milestones ("Project not found"), the
-- admin board was permanently blank, and `advance_stage` - the auto-advance the
-- whole module is built around - had no row to advance.
--
-- THE FIX, in two halves, because either alone leaves a hole:
--   1. A TRIGGER on clients, so a project exists from the moment a client does.
--      A trigger rather than application code because clients are created from
--      several paths (the admin API, the onboarding flow, the data importer,
--      the CLI) and the invariant "a client has a project" must not depend on
--      which one ran.
--   2. A BACKFILL, because every client that already exists predates the
--      trigger and would otherwise stay broken forever.
--
-- Display columns are SNAPSHOTS (client_name / site / init / accent), matching
-- the convention 0021 set and content_jobs uses: the internal client_id never
-- leaks to the portal, so the project carries its own copy of the display
-- fields. `site` is read from business_profiles.website_url, which is where the
-- Add-client form actually writes the website today.
--
-- Idempotent throughout: re-running creates nothing twice.

-- --- initials helper: "Harbor Dental Group" -> "HD", "Spotino" -> "SP" -------
-- Two letters, matching the frontend's avatar convention. A single-word name
-- takes its first two characters; an empty name yields '' rather than NULL, so
-- the NOT NULL default on client_projects.init always holds.
create or replace function public.client_initials(p_name text)
returns text
language sql
immutable
as $$
  select coalesce(
    case
      when coalesce(trim(p_name), '') = '' then ''
      when array_length(string_to_array(trim(p_name), ' '), 1) >= 2 then
        upper(left(split_part(trim(p_name), ' ', 1), 1) ||
              left(split_part(trim(p_name), ' ', 2), 1))
      else upper(left(trim(p_name), 2))
    end, '');
$$;

-- --- the idempotent provisioner ---------------------------------------------
-- Creates the project and its five stages for one client, or does nothing if a
-- project is already there. Returns the project id either way so a caller can
-- chain off it. SECURITY DEFINER so the trigger works on the RLS-bound
-- `authenticated` pool as well as the privileged one - the client row that
-- fired it has already been authorized by the insert's own policy.
create or replace function public.ensure_client_project(p_client_id uuid)
returns uuid
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  v_project_id uuid;
  v_name       text;
  v_accent     text;
  v_site       text;
begin
  if p_client_id is null then
    return null;
  end if;

  select id into v_project_id
    from public.client_projects
   where client_id = p_client_id;
  if v_project_id is not null then
    return v_project_id;                       -- already provisioned
  end if;

  select c.name, coalesce(nullif(c.contact_color, ''), '#7B69EE')
    into v_name, v_accent
    from public.clients c
   where c.id = p_client_id;
  if not found then
    return null;                               -- client vanished mid-flight
  end if;

  -- The website is written to client_business_profiles by the Add-client form.
  -- A `sites` row only appears LATER (running an audit against the client's URL
  -- creates it), so the profile is the earlier and more reliable source and the
  -- site is the fallback. Absent both -> empty string, never NULL.
  select coalesce(
           (select nullif(bp.website_url, '')
              from public.client_business_profiles bp
             where bp.client_id = p_client_id
             limit 1),
           (select nullif(s.domain, '')
              from public.sites s
             where s.client_id = p_client_id
             order by s.created_at
             limit 1),
           ''
         )
    into v_site;

  insert into public.client_projects (client_id, client_name, site, init, accent, health)
  values (
    p_client_id,
    coalesce(v_name, ''),
    coalesce(v_site, ''),
    public.client_initials(v_name),
    v_accent,
    'on_track'
  )
  returning id into v_project_id;

  -- Exactly one row per stage_key, all 'upcoming' - the shape 0021 documents.
  -- Ordering comes from the enum's own definition order, so no explicit rank.
  insert into public.project_stages (project_id, stage_key, status, auto_source)
  select v_project_id, k, 'upcoming', ''
    from unnest(enum_range(null::public.stage_key)) as k
  on conflict do nothing;

  return v_project_id;
end;
$$;

-- --- trigger: a client always has a project ---------------------------------
create or replace function public.clients_autocreate_project()
returns trigger
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  perform public.ensure_client_project(new.id);
  return new;
end;
$$;

drop trigger if exists clients_autocreate_project_trg on public.clients;
create trigger clients_autocreate_project_trg
  after insert on public.clients
  for each row execute function public.clients_autocreate_project();

-- --- backfill every client that predates the trigger ------------------------
do $$
declare
  r record;
begin
  for r in
    select c.id
      from public.clients c
      left join public.client_projects p on p.client_id = c.id
     where p.id is null
  loop
    perform public.ensure_client_project(r.id);
  end loop;
end $$;

-- --- refresh the display snapshot on existing projects -----------------------
-- A project provisioned before its website was known (or by an earlier run of
-- this migration) carries an empty `site`. Fill it in from whichever source now
-- has it, without clobbering a value that is already set.
update public.client_projects p
   set site = coalesce(
         (select nullif(bp.website_url, '')
            from public.client_business_profiles bp
           where bp.client_id = p.client_id
           limit 1),
         (select nullif(s.domain, '')
            from public.sites s
           where s.client_id = p.client_id
           order by s.created_at
           limit 1),
         p.site
       )
 where coalesce(p.site, '') = '';

-- --- repair any project that is missing stages ------------------------------
-- A project created before this migration (or by a partial failure) can exist
-- with fewer than five stages; the read path assumes all five, so top them up
-- rather than leaving a half-rendered timeline.
insert into public.project_stages (project_id, stage_key, status, auto_source)
select p.id, k, 'upcoming', ''
  from public.client_projects p
  cross join unnest(enum_range(null::public.stage_key)) as k
 where not exists (
   select 1 from public.project_stages s
    where s.project_id = p.id and s.stage_key = k
 );
