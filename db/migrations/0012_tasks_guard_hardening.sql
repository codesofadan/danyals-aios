-- 0012_tasks_guard_hardening.sql - close a column-lock gap in the task guard.
--
-- 0011's tasks_guard_update() lets the assignee (a non-lead) change ONLY the
-- status column during a legal transition, but its "every other column must be
-- unchanged" check omitted `id` and `created_at`. During an otherwise-legal
-- advance a non-lead could therefore smuggle a changed id/created_at via direct
-- PostgREST (low impact - id is never exposed and only board ordering keys off
-- created_at - but it must not be writable by a non-lead). This adds both to the
-- lock. `create or replace function` is idempotent; re-running is safe.
create or replace function public.tasks_guard_update()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
  v_assignee_role public.app_role;
begin
  -- (1) The assignee must be a staff user, never a portal client.
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
  -- by the set_updated_at trigger). Every other column - including the immutable
  -- id and created_at - must be unchanged.
  if new.id          is distinct from old.id
     or new.created_at  is distinct from old.created_at
     or new.title       is distinct from old.title
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

  -- ... and only along a legal transition. Forbids a non-lead from entering OR
  -- leaving `review` (the content review gate is lead-only) and from leaving
  -- `done`. Content Sprints route in_progress -> review; other types -> done.
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
