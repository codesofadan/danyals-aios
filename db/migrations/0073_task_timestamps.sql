-- 0073_task_timestamps.sql - real START/COMPLETE timestamps on a task.
--
-- `public.tasks` (0011) had no per-transition timestamps, only the generic
-- `created_at`/`updated_at` (trigger-stamped) + `due_date`. The Task Timer feature
-- needs the REAL moment a task moved todo->in_progress ("started_at") and the
-- REAL moment it reached its terminal state ("completed_at" - in_progress->done for
-- a non-review type, or the review->done approval sign-off for a content_sprint).
-- This adds those two nullable columns (no backfill - only set going forward) and,
-- mirroring 0056_task_proof_url.sql EXACTLY, teaches the lifecycle guard about them.
--
-- THE BOUNDARY (unchanged threat model - 0011/0012/0056): staff hold the public
-- anon-equivalent DB credential + a verified identity and could PATCH the row
-- directly, so the state machine lives at the DB, not FastAPI. `tasks_guard_update()`
-- lets a NON-LEAD (the assignee) change ONLY `status` (+`proof_url`, 0056) along a
-- legal transition. This widens the non-lead column-lock by EXACTLY TWO more columns:
-- `started_at`/`completed_at` may now change ALONGSIDE a legal status move (the
-- assignee's own advance stamps the real moment it happened). Every other
-- restriction is preserved byte-for-byte: a non-lead still cannot touch any other
-- column, still cannot enter/leave `review`, and a timestamp change is still gated
-- behind a LEGAL status transition. A non-lead may also only ever SET each
-- timestamp ONCE, pinned to within 10s of the real edit time (clock-skew
-- tolerance) - never backdate, future-date, clear, or re-edit it once set, and
-- `completed_at` can never precede `started_at`. Leads keep full edit (e.g.
-- correcting a stamp).
--
-- `create or replace function` + `add column if not exists` are idempotent.

alter table public.tasks
  add column if not exists started_at   timestamptz,
  add column if not exists completed_at timestamptz;

-- Rebuilt guard: mirrors 0056 exactly, with `started_at`/`completed_at` ALSO
-- removed from the non-lead column-lock (so they may move with status) - nothing
-- else changes.
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
  -- and set/clear proof_url / started_at / completed_at on any task).
  if public.current_app_role() in ('owner', 'admin', 'manager') then
    return new;
  end if;

  -- (3) A non-lead (the assignee) may change ONLY status, proof_url, started_at
  -- and completed_at (updated_at is stamped by the set_updated_at trigger).
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
    raise exception 'a non-lead may change only the status, proof_url, started_at '
      'and completed_at columns';
  end if;

  -- (3b) SECURITY: a non-lead may only ever SET these once, pinned to the real
  -- moment of the edit - never backdate, future-date, clear, or re-edit them.
  -- Without this, the DB-layer state machine (the actual boundary, per THE
  -- BOUNDARY above) would let a non-lead misrepresent when their own work
  -- started/finished, even though the transition itself is legal.
  if old.started_at is not null and new.started_at is distinct from old.started_at then
    raise exception 'a non-lead may not modify an already-set started_at';
  end if;
  if old.completed_at is not null and new.completed_at is distinct from old.completed_at then
    raise exception 'a non-lead may not modify an already-set completed_at';
  end if;
  if new.started_at is not null and old.started_at is null
     and abs(extract(epoch from (new.started_at - clock_timestamp()))) > 10
  then
    raise exception 'started_at must be the real time of the edit, not a chosen value';
  end if;
  if new.completed_at is not null and old.completed_at is null
     and abs(extract(epoch from (new.completed_at - clock_timestamp()))) > 10
  then
    raise exception 'completed_at must be the real time of the edit, not a chosen value';
  end if;
  if new.completed_at is not null and new.started_at is not null
     and new.completed_at < new.started_at
  then
    raise exception 'completed_at cannot precede started_at';
  end if;

  -- ... and only along a legal transition. Forbids a non-lead from entering OR
  -- leaving `review` (the content review gate is lead-only) and from leaving
  -- `done`. Content Sprints route in_progress -> review; other types -> done. A
  -- proof_url/timestamp edit is gated behind one of these legal status moves.
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
