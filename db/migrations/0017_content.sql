-- 0017_content.sql - Part 7 Module 02 (Content): the content-job ledger.
--
-- A content job = a content type + topic pushed through an ~90% AUTOMATED
-- pipeline (queued -> drafting -> needs_review -> publishing -> done) with a
-- single HUMAN review gate (the "10%") off `needs_review` (approve -> publishing,
-- reject -> rejected, edit -> back to drafting). Shapes mirror
-- frontend/lib/content.ts (ContentJob): `code` is the PUBLIC CJ-#### badge (never
-- a UUID); client_name/color are display SNAPSHOTS so the client_id never leaks.
--
-- THREE ACTOR CLASSES touch this table - and the state machine CANNOT live only
-- in FastAPI (mirrors 0011's threat model: any authenticated principal could hit
-- the DB directly with a leaked credential):
--
--   * WORKER / SYSTEM (role service_role): the automated pipeline. It runs on the
--     PRIVILEGED pool, which sets no app.user_id, so `auth.uid()` IS NULL. It
--     advances the job along the pipeline and writes the rich draft columns.
--   * LEADS (owner/admin/manager): the humans who own the review gate - they make
--     the approve/reject/edit decisions and may make any other legal edit.
--   * NON-LEAD STAFF (the assignee, auth.uid() = assignee_id, not a lead): may NOT
--     drive the lifecycle at all (see the guard - path 3).
--
-- THE LOAD-BEARING REASONING (invariant #3): service_role bypasses POLICIES but
-- NOT TRIGGERS. So the RLS policies below gate the two HUMAN pools, while the
-- content_jobs_guard_update() BEFORE-UPDATE trigger is the ONE gate that binds ALL
-- THREE actors - including the worker. The pipeline's legal transitions therefore
-- live in the trigger, not (only) in the Celery task.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'content_page_type') then
    create type public.content_page_type as enum ('service', 'blog', 'local');
  end if;
  if not exists (select 1 from pg_type where typname = 'content_target') then
    create type public.content_target as enum ('WordPress', 'PDF/Markdown');
  end if;
  if not exists (select 1 from pg_type where typname = 'content_framework') then
    -- The 7 copywriting frameworks (content.ts Framework). Mind the SQL-escaped
    -- apostrophe in '4 U''s' and the literal spaces in '4 Ps' / '4 U''s'.
    create type public.content_framework as enum
      ('AIDA', 'PAS', 'BAB', 'FAB', '4 Ps', 'PASTOR', '4 U''s');
  end if;
  if not exists (select 1 from pg_type where typname = 'content_status') then
    create type public.content_status as enum
      ('queued', 'drafting', 'needs_review', 'publishing', 'done', 'failed', 'rejected');
  end if;
end $$;

-- Public job-code sequence. The frontend renders the code as a visible badge
-- (e.g. "CJ-4192"); it starts at 4200 to continue past the seed data.
create sequence if not exists public.content_code_seq start 4200;

-- --- Table -------------------------------------------------------------------
create table if not exists public.content_jobs (
  id           uuid primary key default gen_random_uuid(),   -- internal FK target
  -- The PUBLIC id rendered in the frontend badge (CJ-####); never a UUID.
  code         text not null unique
                 default ('CJ-' || to_char(nextval('public.content_code_seq'), 'FM0000')),
  -- Tenant linkage. ON DELETE SET NULL keeps the job ledger intact if a client is
  -- removed; client_name + color are snapshotted for display so client_id never
  -- has to be surfaced to the API.
  client_id    uuid references public.clients (id) on delete set null,
  client_name  text not null default '',
  color        text not null default '',
  page_type    public.content_page_type not null,
  topic        text not null,
  framework    public.content_framework not null,
  auto         boolean not null default false,   -- was the framework auto-selected
  target       public.content_target not null,
  status       public.content_status not null default 'queued',
  cost         numeric not null default 0,       -- per-page cost, ~$10-50
  words        integer not null default 0,       -- long-form draft length
  schema_type  text not null default '',         -- validated JSON-LD @type (contract key `schema`)
  images       integer not null default 0,       -- AI images generated (alt-tagged)
  stage        text not null default 'Queued',   -- current pipeline stage label
  -- --- Rich pipeline columns (server-only; never in the ContentJob contract) ---
  brief            text  not null default '',     -- the input brief / instructions
  source_pack      jsonb not null default '{}',   -- research: SERP + entities pack
  keyword_map      jsonb not null default '{}',   -- primary/secondary keyword plan
  outline          jsonb not null default '{}',   -- section outline
  entity_coverage  jsonb not null default '{}',   -- entity coverage scoring
  qa_score         jsonb not null default '{}',   -- QA / quality signals
  json_ld          jsonb not null default '{}',   -- assembled JSON-LD block
  internal_links   jsonb not null default '{}',   -- internal-link suggestions
  draft_md         text  not null default '',     -- the long-form draft (markdown)
  wp_post_id       text,                          -- WordPress post id once published
  artifact_dir     text,                          -- controlled artifact root
  pdf_path         text,                          -- PDF/Markdown target artifact
  md_path          text,
  assignee_id      uuid references public.users (id) on delete set null,  -- staff owner (guarded)
  created_by       uuid references public.users (id) on delete set null,
  context_watermark bigint not null default 0,    -- client-context freshness marker (Part 6B)
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists content_jobs_client_id_idx   on public.content_jobs (client_id);
create index if not exists content_jobs_status_idx       on public.content_jobs (status);
create index if not exists content_jobs_assignee_id_idx  on public.content_jobs (assignee_id);
create index if not exists content_jobs_created_at_idx   on public.content_jobs (created_at desc);

create trigger content_jobs_set_updated_at
  before update on public.content_jobs
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Clients are already excluded by is_staff() (redefined in 0010). Any staff may
-- READ; only assign_tasks holders (owner/admin/manager) may INSERT; a job's
-- assignee OR a lead may UPDATE (the actor guard) - the lifecycle is then enforced
-- by the trigger below. service_role (the worker pool) bypasses these policies but
-- NOT the trigger, so the worker's writes are governed by the trigger alone.
alter table public.content_jobs enable row level security;
alter table public.content_jobs force row level security;

create policy content_jobs_select on public.content_jobs
  for select using (public.is_staff());

create policy content_jobs_insert on public.content_jobs
  for insert
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy content_jobs_update on public.content_jobs
  for update
  using (assignee_id = auth.uid() or public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (assignee_id = auth.uid() or public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- DB-level lifecycle guard (the ONE gate binding all three actors) ---------
-- SECURITY DEFINER + empty search_path (schema-qualified everywhere) so it can
-- read public.users for the assignee-role check regardless of RLS, and never
-- recurses. Unlike the task guard, the content pipeline runs as service_role
-- (auth.uid() IS NULL) - and service_role bypasses POLICIES but NOT TRIGGERS
-- (invariant #3) - so THIS trigger is the pipeline's gate too, not just the humans'.
create or replace function public.content_jobs_guard_update()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_assignee_role public.app_role;
begin
  -- (0) The assignee must be a staff user, never a portal client - closes the
  -- "point a job at a client uid" hole on every path.
  if new.assignee_id is not null then
    select role into v_assignee_role from public.users where id = new.assignee_id;
    if v_assignee_role = 'client'::public.app_role then
      raise exception 'content job assignee must be a staff user, not a client';
    end if;
  end if;

  -- (1) WORKER / SYSTEM path (role service_role => auth.uid() IS NULL). The
  -- automated pipeline advances the job and writes the rich draft columns. It runs
  -- on the privileged pool which sets no app.user_id, so it is UNAMBIGUOUSLY this
  -- branch. Allow ONLY the system transitions - plus same-status writes (the worker
  -- streams cost/words/stage/draft_md into a job WITHOUT a status change) and any
  -- status -> failed (a crash can fail a job from anywhere). Everything else raises.
  if auth.uid() is null then
    if old.status = new.status
       or (old.status = 'queued'::public.content_status
           and new.status = 'drafting'::public.content_status)
       or (old.status = 'drafting'::public.content_status
           and new.status = 'needs_review'::public.content_status)
       or (old.status = 'publishing'::public.content_status
           and new.status = 'done'::public.content_status)
       or (new.status = 'failed'::public.content_status)
    then
      return new;
    end if;
    raise exception 'illegal system content transition % -> %', old.status, new.status;
  end if;

  -- (2) LEADS (owner/admin/manager) own the review gate. They make the review
  -- decisions - needs_review -> publishing (approve), needs_review -> rejected
  -- (reject), needs_review -> drafting (edit) - plus any other legal edit. Any
  -- legal edit -> return new.
  if public.current_app_role() in ('owner', 'admin', 'manager') then
    return new;
  end if;

  -- (3) NON-LEAD STAFF (the assignee, auth.uid() = assignee_id, not a lead). The
  -- content lifecycle is owned ENTIRELY by the automated pipeline (path 1) and the
  -- leads (path 2): the worker drafts/publishes, the leads approve/reject/edit. A
  -- non-lead assignee has NO manual lifecycle write here - not a status change, not
  -- a column edit. We forbid ALL non-lead writes outright (stricter than the task
  -- guard, whose non-lead assignee could advance their own status): here entering
  -- OR leaving `needs_review` is the review gate (lead-only), and no legal non-lead
  -- transition remains once the pipeline + leads own everything. Raise clearly.
  raise exception
    'a non-lead may not modify a content job (the pipeline and leads own the lifecycle)';
end;
$$;

drop trigger if exists content_jobs_guard_update_trg on public.content_jobs;
create trigger content_jobs_guard_update_trg
  before update on public.content_jobs
  for each row execute function public.content_jobs_guard_update();

-- Insert guard: reject a client-role assignee at creation time too (the RLS insert
-- policy already restricts WHO may insert; this restricts WHOM to). Mirrors
-- tasks_guard_insert.
create or replace function public.content_jobs_guard_insert()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_assignee_role public.app_role;
begin
  if new.assignee_id is not null then
    select role into v_assignee_role from public.users where id = new.assignee_id;
    if v_assignee_role = 'client'::public.app_role then
      raise exception 'content job assignee must be a staff user, not a client';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists content_jobs_guard_insert_trg on public.content_jobs;
create trigger content_jobs_guard_insert_trg
  before insert on public.content_jobs
  for each row execute function public.content_jobs_guard_insert();
