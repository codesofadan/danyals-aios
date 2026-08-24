-- 0090_content_jobs_links.sql - link content_jobs to the planning layer, and retire
-- one dead column honestly.
--
-- ADDITIVE AND NULLABLE, every one. A job with no engagement behaves exactly as it
-- does today, so the existing pipeline, the existing rows, and the frontend contract
-- are all untouched. This is what makes the new layer opt-in rather than a migration
-- of live data.
--
-- WHY THIS IS THE ONE TO BE CAREFUL WITH. `content_jobs` carries
-- `content_jobs_guard_update`, a SECURITY DEFINER BEFORE-UPDATE trigger that binds
-- ALL THREE actors including the worker pool - service_role bypasses POLICIES but not
-- TRIGGERS. So a new column is only usable if the trigger's worker branch permits the
-- write that sets it.
--
-- VERIFIED, not assumed: the worker branch (auth.uid() IS NULL) returns NEW when
-- `old.status = new.status`, which is exactly the same-status streaming write the
-- pipeline uses for cost/words/stage/draft_md. So these columns are writable by the
-- worker without any trigger change, and no trigger change is made. Getting this
-- wrong would surface only at runtime, as `illegal system content transition`.

alter table public.content_jobs
  add column if not exists engagement_id uuid references public.content_engagements (id) on delete set null,
  add column if not exists brief_id uuid references public.content_briefs (id) on delete set null,
  add column if not exists node_id uuid references public.topical_map_nodes (id) on delete set null,
  add column if not exists brand_kit_id uuid references public.brand_kits (id) on delete set null,
  add column if not exists current_version_id uuid references public.content_versions (id) on delete set null,
  -- Denormalised from the latest QA run so the board can sort and filter on quality
  -- without joining every run. The authoritative history stays in content_qa_runs.
  add column if not exists qa_weighted_total numeric(6,2),
  -- How many Experience slots the page still lacks. Surfaced on the review screen so
  -- a reviewer sees WHY a draft is weak on E-E-A-T rather than only that it is.
  add column if not exists experience_slots_missing integer not null default 0;

create index if not exists content_jobs_engagement_idx
  on public.content_jobs (engagement_id, created_at desc)
  where engagement_id is not null;
create index if not exists content_jobs_node_idx
  on public.content_jobs (node_id) where node_id is not null;

-- --- Dead columns: documented, not dropped -----------------------------------
-- Dropping a column is destructive DDL on a table with FORCE RLS and a SECURITY
-- DEFINER guard, and these are harmless. Recording WHY each is dead turns silent
-- debt into a note the next reader can act on.
--
-- `artifact_dir` has never been written by any code path in git history - artifact
-- roots come from Settings.content_artifact_dir. It is the only genuinely dead one.
comment on column public.content_jobs.artifact_dir is
  'DEPRECATED - never written since 0017. Artifact roots come from '
  'Settings.content_artifact_dir. Do not start writing this; use pdf_path / md_path.';

-- These three were dead only because nothing set them. They are now wired rather
-- than retired, so the comments say what they mean rather than warning you off.
comment on column public.content_jobs.created_by is
  'The actor who created the job. Wired in P0; was previously never set even though '
  'the create path always had the actor to hand.';
comment on column public.content_jobs.assignee_id is
  'ATTRIBUTION ONLY, not permission. content_jobs_guard_update gives a non-lead '
  'assignee no write path at all, so this records who owns the work, never who may '
  'change it.';
comment on column public.content_jobs.brief is
  'The operator''s raw instruction text. The STRUCTURED brief lives in '
  'content_briefs, reached via brief_id.';
