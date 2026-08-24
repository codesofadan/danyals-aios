-- 0088_content_versions.sql - diffable drafts, recorded QA, and the cross-page
-- uniqueness index.
--
-- THREE TABLES, all fixing "the system cannot see its own history".
--
-- 1. `content_versions`. `content_jobs.draft_md` is OVERWRITTEN on every redraft, so a
--    guided edit destroys what it replaced. Nobody can answer "what did the reviewer's
--    note actually change?", and a regression is invisible. Versions make a redraft an
--    INSERT, and carry `model_mix` / `stage_costs` so the cost of a specific draft is
--    attributable rather than averaged.
--
-- 2. `content_qa_runs`. The score is currently stored as jsonb on the job and
--    overwritten with it, so QA has no trend either. `provisional` is carried
--    explicitly because `content_qa.PROVISIONAL` is True and the 85 threshold is
--    self-declared uncalibrated - a stored score that hides that would read as settled
--    fact a year from now.
--
-- 3. `content_outline_shingles` - THE CROSS-PAGE UNIQUENESS INDEX, and the reason this
--    migration matters most.
--
--    `content_generator._FRAMEWORK_MOVES` is a fixed heading table, so two competing
--    clients in two cities receive heading skeletons identical but for the city token.
--    That is the scaled-content-abuse fingerprint, manufactured by us.
--    `content_qa`'s originality dimension compares a page only against ITSELF and is
--    structurally blind to it.
--
--    MEASURED FINDING, and it dictates the column. Shingling the raw headings does NOT
--    catch the template: Austin vs Round Rock scored 58% at w=3 and 28% at w=5, both
--    UNDER the 70% ceiling, and it gets WORSE as the window grows, because the varying
--    city token sits inside most shingles and hides the duplication. Masking the target
--    entity first scores 100%. So `shingle_hash` MUST be computed over
--    ENTITY-MASKED text - `masked` records that it was, because an index quietly
--    filled with unmasked hashes would look full and catch nothing.
--
--    Hashes rather than text: comparing a new outline against every prior page in a
--    vertical cannot hold all shingle sets in memory, so the comparison is a SQL
--    intersection over an indexed bigint.

create table if not exists public.content_versions (
  id            uuid primary key default gen_random_uuid(),
  job_id        uuid not null references public.content_jobs (id) on delete cascade,
  node_id       uuid references public.topical_map_nodes (id) on delete set null,
  version       integer not null,
  draft_md      text not null default '',
  title         text not null default '',
  meta_description text not null default '',
  json_ld       jsonb not null default '{}'::jsonb,
  page_model    jsonb not null default '{}'::jsonb,
  qa_score      jsonb not null default '{}'::jsonb,
  -- Per-stage spend and which model ran each stage. Without these the only cost
  -- signal is one number on the job, which cannot say whether the money went on
  -- drafting or on a repair loop.
  stage_costs   jsonb not null default '{}'::jsonb,
  model_mix     jsonb not null default '{}'::jsonb,
  created_by    uuid references public.users (id) on delete set null,
  created_at    timestamptz not null default now()
);

create unique index if not exists content_versions_job_version_idx
  on public.content_versions (job_id, version);
create index if not exists content_versions_job_recent_idx
  on public.content_versions (job_id, created_at desc);

create table if not exists public.content_qa_runs (
  id             uuid primary key default gen_random_uuid(),
  version_id     uuid not null references public.content_versions (id) on delete cascade,
  weighted_total numeric(6,2) not null default 0,
  passed         boolean not null default false,
  -- True while the thresholds and weight vector remain uncalibrated. Stored per run
  -- so a future reader can tell which scores were produced under a guessed bar.
  provisional    boolean not null default true,
  dimensions     jsonb not null default '{}'::jsonb,
  blocking       text[] not null default '{}',
  -- Output of the ported deterministic validators (content_lint), kept separately
  -- from the judge's view so a disagreement between them stays visible.
  lint_reports   jsonb not null default '{}'::jsonb,
  judge_used     boolean not null default false,
  created_at     timestamptz not null default now()
);

create index if not exists content_qa_runs_version_idx
  on public.content_qa_runs (version_id, created_at desc);

create table if not exists public.content_outline_shingles (
  id           uuid primary key default gen_random_uuid(),
  job_id       uuid references public.content_jobs (id) on delete cascade,
  node_id      uuid references public.topical_map_nodes (id) on delete set null,
  client_id    uuid references public.clients (id) on delete set null,
  vertical     text not null default '',
  -- Signed 64-bit blake2b of one entity-masked shingle. NOT Python's builtin hash():
  -- PYTHONHASHSEED randomises it per process, so two workers would disagree and the
  -- index would silently stop matching.
  shingle_hash bigint not null,
  -- False means the hash was computed over raw text and CANNOT be trusted to catch a
  -- template (see the measurement above). Present so a bad backfill is detectable
  -- rather than merely ineffective.
  masked       boolean not null default true,
  created_at   timestamptz not null default now()
);

-- The two comparisons the uniqueness gate makes: against this client's own pages, and
-- against every page in the same vertical across all clients. Both filtered to masked
-- hashes, because an unmasked one is noise in this index.
create index if not exists content_outline_shingles_vertical_idx
  on public.content_outline_shingles (vertical, shingle_hash)
  where masked = true;
create index if not exists content_outline_shingles_client_idx
  on public.content_outline_shingles (client_id, shingle_hash)
  where masked = true;
create index if not exists content_outline_shingles_job_idx
  on public.content_outline_shingles (job_id) where job_id is not null;

-- --- RLS ---------------------------------------------------------------------
alter table public.content_versions enable row level security;
alter table public.content_versions force row level security;
alter table public.content_qa_runs enable row level security;
alter table public.content_qa_runs force row level security;
alter table public.content_outline_shingles enable row level security;
alter table public.content_outline_shingles force row level security;

create policy content_versions_select on public.content_versions
  for select using (public.is_staff());
create policy content_versions_write on public.content_versions
  for all using (public.is_staff()) with check (public.is_staff());

create policy content_qa_runs_select on public.content_qa_runs
  for select using (public.is_staff());
create policy content_qa_runs_write on public.content_qa_runs
  for all using (public.is_staff()) with check (public.is_staff());

create policy content_outline_shingles_select on public.content_outline_shingles
  for select using (public.is_staff());
create policy content_outline_shingles_write on public.content_outline_shingles
  for all using (public.is_staff()) with check (public.is_staff());
