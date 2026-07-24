-- 0056_task_proof_url.sql - attach a PROOF-OF-COMPLETION link to a task.
--
-- The admin Task Manager shows every team member's work with a PROOF LINK: the URL
-- of the published content / delivered report the assignee did as proof of
-- completion. This adds `public.tasks.proof_url` (never null - defaults to '', the
-- "no proof yet" state) and, critically, TEACHES THE LIFECYCLE GUARD ABOUT IT.
--
-- THE BOUNDARY (unchanged threat model - 0011/0012): staff hold the public anon
-- key + a JWT and can PATCH PostgREST directly, so the state machine lives at the
-- DB, not FastAPI. 0012's tasks_guard_update() lets a NON-LEAD (the assignee)
-- change ONLY `status`, and only along a legal transition. But an assignee must be
-- able to ATTACH THEIR PROOF when they submit/complete a task - so this widens the
-- non-lead column-lock by EXACTLY ONE column: `proof_url` may now change ALONGSIDE
-- a legal status move (the assignee submits proof as they advance to review/done).
-- Every other restriction is preserved byte-for-byte: a non-lead still cannot
-- touch any other column, still cannot enter/leave `review`, and a proof_url change
-- is still gated behind a LEGAL status transition (an assignee cannot edit proof on
-- a task parked in review/done - that stays lead-only). Leads keep full edit.
--
-- `create or replace function` + `add column if not exists` are idempotent.

alter table public.tasks
  add column if not exists proof_url text not null default '';

-- Rebuilt guard: mirrors 0012 exactly, with `proof_url` REMOVED from the non-lead
-- column-lock (so it may move with status) - nothing else changes.
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

  -- (2) Leads may make any legal edit (assign, repriority, review sign-off/reject,
  -- and set/clear proof_url on any task).
  if public.current_app_role() in ('owner', 'admin', 'manager') then
    return new;
  end if;

  -- (3) A non-lead (the assignee) may change ONLY status AND proof_url (updated_at
  -- is stamped by the set_updated_at trigger). proof_url is DELIBERATELY absent from
  -- this lock: an assignee attaches their proof-of-completion link as they advance.
  -- Every other column - including the immutable id and created_at - must be
  -- unchanged.
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
    raise exception 'a non-lead may change only the status and proof_url columns';
  end if;

  -- ... and only along a legal transition. Forbids a non-lead from entering OR
  -- leaving `review` (the content review gate is lead-only) and from leaving
  -- `done`. Content Sprints route in_progress -> review; other types -> done. A
  -- proof_url edit is gated behind one of these legal status moves.
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
