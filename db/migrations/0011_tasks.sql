-- 0011_tasks.sql - Part 5 Team Flow: the task / workflow-board ledger.
--
-- One row per team work item. A signed-in staff member sees their queue and
-- advances a task through the lifecycle (todo -> in_progress -> [review] ->
-- done); leads (owner/admin/manager = the assign_tasks holders) assign/route
-- work and sign off the content review gate. Shapes mirror frontend/lib/data.ts
-- (Task) + portal.ts (the lifecycle state machine). A task MAY later link an
-- audit/content job (audit_id, forward-link, unused in v1).
--
-- THE THREAT MODEL (mirrors 0010's header): any authenticated principal can hit
-- Supabase PostgREST DIRECTLY with the public anon key + its JWT, bypassing
-- FastAPI - so RLS is the only real boundary. Staff hold that same kind of JWT.
-- Therefore the lifecycle + the review checkpoint CANNOT live only in FastAPI: a
-- specialist could PATCH /rest/v1/tasks?id=eq.<mine> {"status":"done"} to skip
-- review. The state machine is enforced HERE, at the DB, by the
-- tasks_guard_update BEFORE UPDATE trigger: a non-lead may change ONLY the
-- status column and ONLY along a legal transition; entering/leaving `review`
-- (and every other column) is lead-only. The app-layer 403/409 in the router are
-- UX on top of this boundary, not the boundary itself.

-- --- Enums (idempotent guards; enums have no "create ... if not exists") ------
do $$ begin
  if not exists (select 1 from pg_type where typname = 'task_type') then
    create type public.task_type as enum
      ('technical_audit', 'actionable_audit', 'content_sprint',
       'backlink_audit', 'local_seo', 'publishing');
  end if;
  if not exists (select 1 from pg_type where typname = 'task_priority') then
    create type public.task_priority as enum ('urgent', 'high', 'med', 'low');
  end if;
  if not exists (select 1 from pg_type where typname = 'task_status') then
    create type public.task_status as enum ('todo', 'in_progress', 'review', 'done');
  end if;
end $$;

-- Public job-code sequence. The frontend renders the code as a visible badge
-- (e.g. "J-2041"); it starts at 2042 to continue past the seed data.
create sequence if not exists public.tasks_code_seq start 2042;

-- --- Table -------------------------------------------------------------------
create table if not exists public.tasks (
  id           uuid primary key default gen_random_uuid(),   -- internal FK target
  -- The PUBLIC id rendered in the frontend badge (J-####); never a UUID.
  code         text not null unique
                 default ('J-' || to_char(nextval('public.tasks_code_seq'), 'FM0000')),
  title        text not null,
  -- Tenant linkage. ON DELETE SET NULL keeps the task ledger intact if a client
  -- is removed; client_name is snapshotted for display.
  client_id    uuid references public.clients (id) on delete set null,
  client_name  text not null default '',
  type         public.task_type not null,
  -- The staff member the task is assigned to (never a client - guarded below).
  assignee_id  uuid references public.users (id) on delete set null,
  priority     public.task_priority not null default 'med',
  status       public.task_status not null default 'todo',
  due_date     date,
  -- Forward-link to a future audit/content job (nullable, unused in v1).
  audit_id     uuid references public.audits (id) on delete set null,
  created_by   uuid references public.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists tasks_assignee_id_idx on public.tasks (assignee_id);
create index if not exists tasks_status_idx on public.tasks (status);
create index if not exists tasks_created_at_idx on public.tasks (created_at desc);
create index if not exists tasks_client_id_idx on public.tasks (client_id);

create trigger tasks_set_updated_at
  before update on public.tasks
  for each row execute function public.set_updated_at();

-- --- RLS ---------------------------------------------------------------------
-- Clients are already excluded by is_staff() (redefined in 0010). run/assign
-- semantics: any staff may READ; only assign_tasks holders (owner/admin/manager)
-- may INSERT; a task's assignee OR a lead may UPDATE (actor guard) - the
-- lifecycle itself is then enforced by the trigger below. No delete in v1.
alter table public.tasks enable row level security;
alter table public.tasks force row level security;

create policy tasks_select on public.tasks
  for select using (public.is_staff());

create policy tasks_insert on public.tasks
  for insert
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));

create policy tasks_update on public.tasks
  for update
  using (assignee_id = auth.uid() or public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (assignee_id = auth.uid() or public.current_app_role() in ('owner', 'admin', 'manager'));

-- --- BLOCKER FIX: DB-level lifecycle guard -----------------------------------
-- SECURITY DEFINER + empty search_path (schema-qualified everywhere) so it can
-- read public.users for the assignee-role check regardless of RLS, and never
-- recurses. NOTE service_role does NOT bypass triggers - but Part 5 only mutates
-- tasks through the user-JWT client, so this always runs with a real auth.uid().
create or replace function public.tasks_guard_update()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_assignee_role public.app_role;
begin
  -- (1) The assignee must be a staff user, never a portal client - closes the
  -- "a lead (or non-lead) points a task at a client uid" hole on every path.
  if new.assignee_id is not null then
    select role into v_assignee_role from public.users where id = new.assignee_id;
    if v_assignee_role = 'client'::public.app_role then
      raise exception 'task assignee must be a staff user, not a client';
    end if;
  end if;

  -- (2) Leads may make any legal edit (assign, repriority, review sign-off/reject).
  if public.current_app_role() in ('owner', 'admin', 'manager') then
    return new;
  end if;

  -- (3) A non-lead (the assignee) may change ONLY status (updated_at is stamped
  -- by the set_updated_at trigger). Every other column must be unchanged.
  if new.title       is distinct from old.title
     or new.client_id   is distinct from old.client_id
     or new.client_name is distinct from old.client_name
     or new.type        is distinct from old.type
     or new.assignee_id is distinct from old.assignee_id
     or new.priority    is distinct from old.priority
     or new.due_date    is distinct from old.due_date
     or new.audit_id    is distinct from old.audit_id
     or new.created_by  is distinct from old.created_by
     or new.code        is distinct from old.code
  then
    raise exception 'a non-lead may change only the status column';
  end if;

  -- ... and only along a legal transition. This forbids a non-lead from entering
  -- OR leaving `review` (the content review gate is lead-only) and from leaving
  -- `done`. Content Sprints route in_progress -> review; all other types
  -- in_progress -> done.
  if old.status = 'todo'::public.task_status
     and new.status = 'in_progress'::public.task_status then
    return new;
  elsif old.status = 'in_progress'::public.task_status
        and new.status = 'review'::public.task_status
        and old.type = 'content_sprint'::public.task_type then
    return new;
  elsif old.status = 'in_progress'::public.task_status
        and new.status = 'done'::public.task_status
        and old.type <> 'content_sprint'::public.task_type then
    return new;
  end if;

  raise exception 'illegal task status transition % -> % for a non-lead',
    old.status, new.status;
end;
$$;

drop trigger if exists tasks_guard_update_trg on public.tasks;
create trigger tasks_guard_update_trg
  before update on public.tasks
  for each row execute function public.tasks_guard_update();

-- Insert guard: reject a client-role assignee at creation time too (the RLS
-- insert policy already restricts WHO may insert; this restricts WHOM to).
create or replace function public.tasks_guard_insert()
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
      raise exception 'task assignee must be a staff user, not a client';
    end if;
  end if;
  return new;
end;
$$;

drop trigger if exists tasks_guard_insert_trg on public.tasks;
create trigger tasks_guard_insert_trg
  before insert on public.tasks
  for each row execute function public.tasks_guard_insert();
