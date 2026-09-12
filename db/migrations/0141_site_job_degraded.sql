-- 0141_site_job_degraded.sql - a terminal state for "published, but not a match".
--
-- WHY. `0069` gave site-generation jobs `correcting` but nothing consumed it: visual QA
-- set the status and the pipeline stopped there, so a page that rendered wrong was
-- measured, the measurement was stored, and the job sat in a non-terminal state
-- forever. `app/services/correcting.py` was written and unit-tested to close that loop
-- and was never imported. Wiring it in needs somewhere honest to land when two rounds
-- have not resolved the diff.
--
-- The two states that already exist are both wrong for that outcome:
--   * `completed` claims the rendered page matches the design. It does not - that is
--     exactly what the diff measured.
--   * `failed` says the pipeline produced nothing. It produced a live, editable page
--     that is imperfect, which is a different and much better thing.
--
-- `degraded` is the word the job contract already uses platform-wide for precisely
-- this shape (`is_success()` is true for `completed` and nothing else), so an operator
-- reads one vocabulary across both surfaces.
--
-- ADDING A LABEL ONLY. Postgres forbids USING a new enum label in the transaction that
-- adds it (55P04), so this migration adds it and nothing else - no table here refers to
-- it. The only writer is Python at runtime, which is a different transaction by
-- construction. `if not exists` keeps a re-apply idempotent.

do $$
begin
  if not exists (
    select 1
    from pg_enum e
    join pg_type t on t.oid = e.enumtypid
    where t.typname = 'site_job_status' and e.enumlabel = 'degraded'
  ) then
    alter type public.site_job_status add value 'degraded';
  end if;
end $$;

comment on type public.site_job_status is
  'Site-generation job lifecycle. Terminal states: completed (the rendered page '
  'matches the design), degraded (it published but the visual diff was not resolved '
  'within the correction rounds - the page is live and imperfect), failed (nothing '
  'usable was produced). Mirrors the platform job contract, where only completed is '
  'success.';
