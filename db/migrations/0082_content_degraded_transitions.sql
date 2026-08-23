-- 0082_content_degraded_transitions.sql - let the worker land a job on 'degraded'.
--
-- Depends on 0081 having been applied AND COMMITTED (see the 55P04 note there).
--
-- The content lifecycle is enforced by the `content_jobs_guard_update` BEFORE-UPDATE
-- trigger, NOT by FastAPI - deliberately, because `service_role` bypasses RLS
-- policies but NOT triggers, so the state machine holds even for a caller on the
-- privileged pool. That means adding a status the worker is allowed to write is a
-- TRIGGER change; adding the enum label alone would leave every attempt raising
-- 'illegal system content transition publishing -> degraded'.
--
-- This re-states the function verbatim from 0017_content.sql with ONE addition on
-- the worker path: `publishing -> degraded`. Everything else - the assignee guard,
-- the lead branch, the non-lead refusal - is byte-for-byte unchanged, and the
-- original comments are preserved so the two can be diffed.
--
-- Why the worker and not a lead: reaching `degraded` is a machine observation
-- ("no transport could reach the site"), not a human decision. A lead retains the
-- blanket lead branch, so a lead can still move a degraded job onward once the
-- credential lands - which is the intended recovery path.
--
-- Note `drafting -> degraded` is NOT added. A research/spend degradation during
-- drafting already HOLDS the job at `drafting` with an honest stage marker and is
-- designed to be re-run when keys or budget arrive; it is a pause, not an outcome.
-- `degraded` is reserved for a job that has finished and will not advance itself.

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
       -- P0-4: a publish that produced an artifact but reached no live site lands
       -- HERE, not on 'done'. See 0081 for why this label exists.
       or (old.status = 'publishing'::public.content_status
           and new.status = 'degraded'::public.content_status)
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
