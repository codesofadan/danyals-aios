-- 0072_content_schedule.sql - scheduled publishing (spec section 46: Generate,
-- Review, Draft, Schedule, Publish, Update, Republish).
--
-- Purely ADDITIVE: one nullable column, NO changes to content_jobs_guard_update()
-- (0017). Deliberately so: that trigger's LEAD branch already allows a lead to make
-- "any other legal edit" unconditionally - including writing this new column AND
-- (for republish) the done -> publishing transition itself. So scheduling and
-- republish are both already legal under the EXISTING trigger; this migration only
-- gives the app layer a place to record "publish later" instead of "publish now".
--
-- How scheduling actually works (app layer, not this migration): the lead's
-- approve action still moves needs_review -> publishing immediately (unchanged -
-- a human still approves before anything is queued for real, preserving the
-- existing human-gate invariant). If `publish_at` is in the future, the router
-- skips the immediate Celery enqueue; a (currently DISABLED, see celery_app.py)
-- beat sweep later claims due rows still sitting in `publishing` with a past-due
-- `publish_at`, clears it (a same-status write - already legal for the WORKER
-- branch too), and enqueues the publish task then.
--
-- Republish (done -> publishing) reuses the SAME already-legal lead transition;
-- no schema change was needed for it at all - only a new router endpoint.

alter table public.content_jobs add column if not exists publish_at timestamptz;

create index if not exists content_jobs_publish_at_idx
  on public.content_jobs (publish_at)
  where publish_at is not null;

comment on column public.content_jobs.publish_at is
  'When set + in the future, defers the publish worker enqueue to this time '
  '(scheduled publishing); NULL means publish immediately (the existing behaviour).';
