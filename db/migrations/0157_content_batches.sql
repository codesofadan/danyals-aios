-- 0157_content_batches.sql - a bulk build is one thing, so it gets one row.
--
-- WHAT WAS WRONG. `POST /content/research/generate` fans a set of chosen pages out into
-- independent jobs and returns their codes. That is the right execution model - each page
-- is separately cost-gated, and one failure cannot take the others down - but nothing
-- recorded that the jobs belonged together. Three consequences, all of them felt on a
-- first real batch:
--
--   1. NO PROGRESS VIEW. Thirty jobs land in a board of every job the agency has ever
--      run, mixed with other clients', with no way to ask "how is Tuesday's batch doing".
--   2. NO SPEND CEILING FOR THE BATCH. The per-client monthly cap and the global halt both
--      apply, but neither can express "this batch may cost twenty dollars" - so the way to
--      bound a thirty-page run was to watch it.
--   3. NO RESUME. A job held on budget or on an absent key holds at `drafting` with an
--      honest marker (the worker's degrade path), and the only way to pick it up again was
--      to know its code and re-enqueue it by hand, one at a time.
--
-- THE SHAPE. A batch is a small header row plus a nullable `batch_id` on the job. Nullable
-- because every job that already exists has no batch and single-job creation still does
-- not - a batch is something a fan-out has, not something a job requires. ON DELETE SET
-- NULL for the same reason the client link is: deleting the header must not delete the
-- work, it must only stop grouping it.
--
-- `cost_ceiling` is nullable and means "no batch ceiling" when null, which is exactly what
-- every pre-existing fan-out had. Spend is NOT stored here: it is summed from the jobs'
-- own `cost` column, so the ceiling is always checked against what was actually committed
-- rather than against a second running total that could drift from it.
--
-- RLS mirrors `content_jobs` (0017): any staff may read, and the same leads who may create
-- content may create a batch. It carries no secret and no credential - it is a label, a
-- ceiling and a pointer - so there is nothing here that needs a narrower door than the
-- jobs it groups.

create table if not exists public.content_batches (
  id           uuid primary key default gen_random_uuid(),
  -- Tenant linkage, snapshotted display name: the same convention content_jobs uses so a
  -- batch never has to surface a client_id to the API.
  client_id    uuid references public.clients (id) on delete set null,
  client_name  text not null default '',
  -- What the operator called this run ("March service pages"). Free text, shown as-is.
  label        text not null default '',
  -- The research/content type the set came from ("service_location"), for display only.
  content_type text not null default '',
  -- The batch's own spend bound in USD. NULL = unbounded (the historical behaviour).
  -- Checked before each job starts, against the sum of the batch's committed costs.
  cost_ceiling numeric(10,2),
  created_by   uuid references public.users (id) on delete set null,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now()
);

create index if not exists content_batches_client_idx
  on public.content_batches (client_id, created_at desc);

create trigger content_batches_set_updated_at
  before update on public.content_batches
  for each row execute function public.set_updated_at();

alter table public.content_jobs
  add column if not exists batch_id uuid references public.content_batches (id) on delete set null;

create index if not exists content_jobs_batch_idx
  on public.content_jobs (batch_id) where batch_id is not null;

comment on table public.content_batches is
  'One bulk content build: the header a fan-out of jobs hangs off. Carries the operator''s '
  'label and an optional USD ceiling for the whole batch; spend is summed from the jobs '
  'themselves so the ceiling can never be checked against a stale second total.';

comment on column public.content_batches.cost_ceiling is
  'USD bound for the whole batch, or NULL for unbounded. The worker checks the sum of the '
  'batch''s committed job costs against this BEFORE spending on the next job, and holds '
  'the job (never fails it) when the next job would breach it.';

comment on column public.content_jobs.batch_id is
  'The bulk build this job came from, or NULL for a single-job create. ON DELETE SET NULL: '
  'removing the header stops the grouping, it never removes the work.';

-- --- RLS: mirrors content_jobs (0017) ---------------------------------------
alter table public.content_batches enable row level security;
alter table public.content_batches force row level security;

create policy content_batches_select on public.content_batches
  for select using (public.is_staff());

-- Creating a batch is creating content, so it is the same door the jobs use: the leads the
-- content lifecycle already trusts to start and approve work. Spelled out as the role list
-- rather than through a helper, because that is what 0017 does two tables over and one
-- convention beats a new abstraction here.
create policy content_batches_write on public.content_batches
  for all
  using (public.current_app_role() in ('owner', 'admin', 'manager'))
  with check (public.current_app_role() in ('owner', 'admin', 'manager'));
