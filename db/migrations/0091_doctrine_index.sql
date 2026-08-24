-- 0091_doctrine_index.sql - the provenance ledger: which doctrine governed which page.
--
-- WHAT THIS ANSWERS that nothing currently can. `content_generator` and `content_qa`
-- have always CITED the doctrine as the justification for their thresholds. Now the
-- doctrine actually reaches the model, and the honest follow-up question is: which
-- part of it, on which page, at what cost?
--
-- Six months from now the questions that will be asked are "why does this page say
-- that?", "what changed between March and June?", and "what did we spend on this
-- client?". `doctrine_usage` is the only place those are answerable, and only if the
-- rows are written as the calls happen - reconstructing it later is impossible
-- because the routing table will have moved on.
--
-- This is also what makes the deliverable's "Method & Sources" tab a RECORD rather
-- than a description. A method report generated from a template says what we intended
-- to do; one generated from these rows says what happened.
--
-- `doctrine_chunks` mirrors the on-disk index so a usage row can be JOINED to a
-- readable heading and path, rather than leaving a bare id nobody can resolve once
-- the corpus has been edited.

create table if not exists public.doctrine_chunks (
  -- The corpus-relative id, e.g. "knowledge/quality-gates/gates.md#run-order".
  -- TEXT primary key on purpose: it is stable, human-readable and greppable back to
  -- a file, which a surrogate uuid would not be.
  id             text primary key,
  path           text not null,
  heading        text not null default '',
  level          integer not null default 0,
  token_estimate integer not null default 0,
  -- Content hash. A usage row points at an id; this says WHICH VERSION of that
  -- chunk was in force, so an edited doctrine is detectable rather than silent.
  sha256         text not null default '',
  tags           text[] not null default '{}',
  created_at     timestamptz not null default now(),
  updated_at     timestamptz not null default now()
);

create index if not exists doctrine_chunks_path_idx on public.doctrine_chunks (path);

create trigger doctrine_chunks_set_updated_at
  before update on public.doctrine_chunks
  for each row execute function public.set_updated_at();

create table if not exists public.doctrine_usage (
  id            uuid primary key default gen_random_uuid(),
  job_id        uuid references public.content_jobs (id) on delete cascade,
  version_id    uuid references public.content_versions (id) on delete cascade,
  engagement_id uuid references public.content_engagements (id) on delete set null,
  stage         text not null default '',
  model         text not null default '',
  -- Deliberately a text[] of ids rather than a join table. A call sends 150-200
  -- chunks, so a join table would add ~200 rows per LLM call - millions per site -
  -- to support a query nobody runs. The array answers "what governed this call"
  -- directly, and doctrine_chunks resolves the ids when a human needs to read them.
  chunk_ids     text[] not null default '{}',
  -- Chunks the route WANTED but that did not fit the block ceiling. Recorded because
  -- a call that silently saw less doctrine than intended produces a quietly worse
  -- page and is otherwise undetectable.
  dropped_chunk_ids text[] not null default '{}',
  input_tokens        integer not null default 0,
  output_tokens       integer not null default 0,
  -- Cache accounting, straight from the API's usage block. This is what turns the
  -- cache economics from a model into a measurement - the estimate was 30% low.
  cache_write_tokens  integer not null default 0,
  cache_read_tokens   integer not null default 0,
  cost          numeric(12,4) not null default 0,
  created_at    timestamptz not null default now()
);

create index if not exists doctrine_usage_job_idx
  on public.doctrine_usage (job_id, created_at) where job_id is not null;
create index if not exists doctrine_usage_engagement_idx
  on public.doctrine_usage (engagement_id, created_at) where engagement_id is not null;
create index if not exists doctrine_usage_stage_idx on public.doctrine_usage (stage);

-- --- RLS ---------------------------------------------------------------------
alter table public.doctrine_chunks enable row level security;
alter table public.doctrine_chunks force row level security;
alter table public.doctrine_usage enable row level security;
alter table public.doctrine_usage force row level security;

create policy doctrine_chunks_select on public.doctrine_chunks
  for select using (public.is_staff());
create policy doctrine_chunks_write on public.doctrine_chunks
  for all using (public.is_staff()) with check (public.is_staff());

-- Usage rows are an APPEND-ONLY audit trail in intent. There is no UPDATE or DELETE
-- policy, so no staff session can rewrite history through the API. Note honestly
-- what that does and does not mean: service_role (the worker that writes them)
-- bypasses policies entirely, so this is an app-tier convention enforced at the
-- policy layer, NOT a database guarantee of immutability.
create policy doctrine_usage_select on public.doctrine_usage
  for select using (public.is_staff());
create policy doctrine_usage_insert on public.doctrine_usage
  for insert with check (public.is_staff());
