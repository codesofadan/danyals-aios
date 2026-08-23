-- 0080_job_contract.sql - THE JOB CONTRACT. The single execution ledger every
-- background job writes to, plus its dead-letter queue.
--
-- WHY THIS EXISTS
-- ---------------
-- The platform runs 39 Celery tasks. Before this migration the job layer had:
--   * no idempotency key      -> the same unit of work could run twice and spend twice
--   * no retry accounting     -> a transient provider blip was a permanent failure
--   * no dead-letter queue    -> a failure left no replayable record anywhere
--   * no correlation id       -> a fan-out could not be reassembled after the fact
--   * no per-client cap       -> one client's 300-page bulk run starved every other
--   * no shared vocabulary    -> `audit_status` says 'done', `site_job_status` says
--                                'completed', `scheduled_job_status` says 'ok', and
--                                NONE of them can say 'degraded'. A publish that
--                                reached nobody's website reported success.
--
-- This table answers, for every job the platform has ever run: what ran, for whom,
-- what it cost, what it produced, whether it actually succeeded - and if it did not,
-- exactly why, in one vocabulary that every dashboard can key off.
--
-- WHAT IT IS NOT
-- --------------
-- It is not a replacement for the per-module lifecycle tables (`content_jobs`,
-- `audits`, `citation_submissions`, ...). Those keep their own domain state machine
-- and their own triggers. This is the EXECUTION record that sits underneath them:
-- one row per attempt-set of one logical unit of work, linked to the domain row by
-- (scope_type, scope_id). A module's own status answers "where is this content job
-- in its human workflow"; job_runs answers "did the machine that moves it actually
-- work, and what did it cost".
--
-- WRITTEN ONLY BY THE SERVER. Workers write on the service_role (BYPASSRLS)
-- connection, exactly like public_audits and scheduled_job_runs, so there is no
-- authenticated INSERT/UPDATE policy. Any provisioned staff member may READ; a
-- portal client is excluded by is_staff() (no select policy), so a client never
-- sees another tenant's execution history - or their own error strings.

-- --------------------------------------------------------------------------- --
-- 1 - THE ONE STATUS VOCABULARY
-- --------------------------------------------------------------------------- --
-- Seven values, four of them terminal-and-not-success. The distinction that
-- matters most is `completed` vs `degraded`:
--
--   completed  The outcome the job promised actually happened. The pages are live,
--              the report exists, the listing was submitted. This is the ONLY value
--              that may render as success anywhere in the product.
--   degraded   The job ran to the end and produced a PARTIAL outcome. Some of the
--              promise was not kept and the caller must be told which part. A
--              degraded run REQUIRES a reason (enforced below) and must never be
--              displayed as a success.
--   blocked    The job deliberately did not run its expensive part: a cost gate, a
--              missing credential, a suspended client, an automation ceiling, a
--              concurrency cap held too long. Nothing was spent. Not an error - a
--              refusal, and refusals are loud.
--   failed     The job hit an error it could not recover from within its retry
--              budget. Always accompanied by an error_type and a dead-letter row.
--   cancelled  A human asked for it to stop, and it stopped.
--
-- `queued` and `running` are the two non-terminal values.
do $$ begin
  if not exists (select 1 from pg_type where typname = 'job_status') then
    create type public.job_status as enum (
      'queued', 'running', 'completed', 'degraded', 'blocked', 'failed', 'cancelled'
    );
  end if;
end $$;

comment on type public.job_status is
  'The canonical execution vocabulary for every background job. Only `completed` '
  'may render as success; `degraded` is a partial outcome and always carries a reason.';

-- --------------------------------------------------------------------------- --
-- 2 - THE DURATION CLASS (which queue a job belongs to)
-- --------------------------------------------------------------------------- --
-- Four queues by DURATION, not by module. Mixing a 2-second webhook with a
-- 40-minute crawl on one queue means the crawl's prefetch blocks the webhook; and a
-- browser job needs its own worker image (Chromium + Playwright) with its own memory
-- envelope, which is why `browser` is separate from `long`.
--
--   interactive  < 30s   a user is waiting on it
--   standard     < 5m    the default; ordinary API-backed work
--   long         < 30m   audits, bulk content generation, imports
--   browser      < 2h    anything driving Chromium; runs on the browser worker only
do $$ begin
  if not exists (select 1 from pg_type where typname = 'job_queue') then
    create type public.job_queue as enum ('interactive', 'standard', 'long', 'browser');
  end if;
end $$;

comment on type public.job_queue is
  'Duration class, which is also the Celery queue name. Browser jobs are isolated '
  'onto their own worker image so an audit cannot exhaust the API host.';

-- --------------------------------------------------------------------------- --
-- 3 - job_runs: one row per logical unit of work
-- --------------------------------------------------------------------------- --
create table if not exists public.job_runs (
  id                  uuid primary key default gen_random_uuid(),

  -- IDENTITY --------------------------------------------------------------
  -- job_name is the LOGICAL job ('content.publish'); task is the Celery task name
  -- that implements it. They are separate because a logical job may be re-homed to
  -- a different task without breaking every dashboard that groups by job_name.
  job_name            text not null,
  task                text not null default '',
  queue               public.job_queue not null default 'standard',

  -- IDEMPOTENCY -----------------------------------------------------------
  -- The caller-supplied key for "this exact unit of work". Enforced by a UNIQUE
  -- partial index below. A second enqueue with the same key does not create a
  -- second run: it finds this row, and if this row is already terminal the work is
  -- simply not done again. This is what makes an at-least-once broker safe to spend
  -- money on. NULL means the job opted out (a heartbeat sweep, a pure read).
  idempotency_key     text,

  -- CORRELATION -----------------------------------------------------------
  -- Every run carries a correlation_id. A fan-out (one sweep enqueuing 80 per-client
  -- jobs) shares one correlation_id across all 81 rows, so "what did that nightly
  -- sweep actually do" is one indexed query. parent_run_id gives the tree its edges.
  correlation_id      uuid not null default gen_random_uuid(),
  parent_run_id       uuid references public.job_runs (id) on delete set null,
  celery_task_id      text not null default '',

  -- WHO IT IS FOR ---------------------------------------------------------
  -- client_id drives the per-client concurrency cap and the per-client cost rollup.
  -- client_name is a display SNAPSHOT (the convention in every ledger here) so an
  -- operator surface never has to resolve - or leak - an internal client id.
  client_id           uuid references public.clients (id) on delete set null,
  client_name         text not null default '',

  -- WHAT DOMAIN ROW IT DRIVES ---------------------------------------------
  -- (scope_type, scope_id) links the execution record to the module row it moves:
  -- ('content_job', <uuid>), ('audit', <uuid>), ('citation_submission', <uuid>).
  -- Deliberately NOT a foreign key: this ledger outlives the rows it describes, and
  -- a job's post-mortem must survive the deletion of what it was working on.
  scope_type          text not null default '',
  scope_id            uuid,

  -- EXECUTION STATE -------------------------------------------------------
  status              public.job_status not null default 'queued',
  attempt             integer not null default 0,
  max_attempts        integer not null default 1,

  scheduled_for       timestamptz,      -- when a retry is next due (NULL = now)
  started_at          timestamptz,
  finished_at         timestamptz,
  -- A running job stamps this periodically. A run whose heartbeat has gone stale
  -- past its queue's time limit was killed without ACKing - the reaper marks it
  -- failed rather than leaving a permanently `running` row that blocks the cap.
  heartbeat_at        timestamptz,

  -- CANCELLATION ----------------------------------------------------------
  -- Cooperative, because a Celery task cannot be safely killed mid-write. A human
  -- sets cancel_requested_at; the runner refuses to start a queued run that carries
  -- it, and a running job that polls ctx.cancelled() stops at its next checkpoint.
  cancel_requested_at timestamptz,
  cancel_requested_by uuid references public.users (id) on delete set null,

  -- OUTCOME ---------------------------------------------------------------
  detail              text not null default '',   -- one human line, always safe to show
  -- REQUIRED for degraded and blocked (see the check constraint). This is the column
  -- that makes "the publish said done but nothing went live" impossible to repeat:
  -- a partial outcome cannot be recorded without saying which part was not kept.
  reason              text not null default '',
  -- The MACHINE-READABLE half of the same fact, and required alongside it.
  --
  -- `reason` is for a human; `reason_code` is what an operator surface filters on, a
  -- dashboard groups by, and an automation branches on. Prose alone means the only
  -- way to ask "how often does a publish block for missing credentials" is to grep
  -- free text that each call site phrases differently - which is how a recurring,
  -- fixable block stays invisible for months.
  --
  -- Deliberately NOT a Postgres enum. The closed vocabularies belong to the modules
  -- (R3B specifies fourteen `blocked_reason` values for content publishing alone) and
  -- do not exist yet; pinning them here would force a migration every time a module
  -- learns a new way to refuse. The format is constrained instead, so the values stay
  -- stable, greppable identifiers rather than sentences.
  reason_code         text not null default '',
  error_type          text not null default '',   -- exception class name, never the message alone
  error_message       text not null default '',   -- sanitized; never a secret, never a DSN

  -- The ACTUAL cost of this run, logged after the calls, never estimated. Six
  -- decimal places because a single Claude call can be worth $0.000180.
  cost_usd            numeric(12, 6) not null default 0,

  -- Small structured result (counts, ids, artifact keys). NOT a payload dump.
  result              jsonb,

  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now(),

  -- TRUTH CONSTRAINTS -----------------------------------------------------
  -- These are the point of the table. Each one makes a specific lie unrepresentable.

  -- A degraded or blocked run MUST say why, in BOTH registers. Without the prose,
  -- `degraded` silently becomes a second word for success; without the code, the
  -- prose is un-countable and the same block recurs unnoticed.
  constraint job_runs_reason_required_ck check (
    status not in ('degraded', 'blocked') or length(btrim(reason)) > 0
  ),
  constraint job_runs_reason_code_required_ck check (
    status not in ('degraded', 'blocked') or length(btrim(reason_code)) > 0
  ),
  -- A stable identifier, not a sentence: lower snake_case, so `reason_code` can be
  -- grouped, filtered and compared across modules and across time.
  constraint job_runs_reason_code_format_ck check (
    reason_code = '' or reason_code ~ '^[a-z][a-z0-9_]{2,63}$'
  ),
  -- A failed run MUST name its error class.
  constraint job_runs_error_required_ck check (
    status <> 'failed' or length(btrim(error_type)) > 0
  ),
  -- Terminal IF AND ONLY IF finished. A row cannot claim to be done without a
  -- finish time, and cannot carry a finish time while claiming to still be running.
  constraint job_runs_finished_ck check (
    (status in ('completed', 'degraded', 'blocked', 'failed', 'cancelled'))
    = (finished_at is not null)
  ),
  -- A run that has started has an attempt number, and vice versa.
  constraint job_runs_started_ck check (
    (started_at is null) = (attempt = 0)
  ),
  constraint job_runs_attempts_ck check (
    max_attempts >= 1 and attempt >= 0 and attempt <= max_attempts
  ),
  -- Cost is never negative. A refund is a separate ledger entry, not a negative run.
  constraint job_runs_cost_ck check (cost_usd >= 0)
);

comment on table public.job_runs is
  'The execution ledger: one row per logical unit of background work, in the single '
  'job_status vocabulary. Server-written only (service_role); staff-readable.';

-- IDEMPOTENCY. Partial UNIQUE so opting out (NULL) is free, but any key that is
-- supplied is globally unique. The runner inserts with ON CONFLICT DO NOTHING and
-- treats "no row returned" as "someone else owns this unit of work".
create unique index if not exists job_runs_idempotency_key_uq
  on public.job_runs (idempotency_key)
  where idempotency_key is not null;

-- The per-client concurrency cap's hot query: how many of this client's jobs are
-- in flight on this queue right now. Partial, so it indexes only the small
-- in-flight set rather than the whole history.
create index if not exists job_runs_inflight_idx
  on public.job_runs (client_id, queue)
  where status in ('queued', 'running');

-- "What did that fan-out do?" - the correlation tree.
create index if not exists job_runs_correlation_idx
  on public.job_runs (correlation_id, created_at);

-- The operator surface: newest runs of a given logical job.
create index if not exists job_runs_job_name_idx
  on public.job_runs (job_name, created_at desc);

-- The failure surface: everything that did not simply succeed, newest first.
create index if not exists job_runs_not_ok_idx
  on public.job_runs (created_at desc)
  where status in ('degraded', 'blocked', 'failed');

-- Group the not-OK surface by cause rather than by time.
create index if not exists job_runs_reason_code_idx
  on public.job_runs (reason_code, created_at desc)
  where reason_code <> '';

-- The stuck-job reaper's query: running rows whose heartbeat has gone quiet.
create index if not exists job_runs_heartbeat_idx
  on public.job_runs (heartbeat_at)
  where status = 'running';

-- The domain-row lookup: "show me every execution that touched this content job".
create index if not exists job_runs_scope_idx
  on public.job_runs (scope_type, scope_id, created_at desc)
  where scope_id is not null;

drop trigger if exists job_runs_set_updated_at on public.job_runs;
create trigger job_runs_set_updated_at
  before update on public.job_runs
  for each row execute function public.set_updated_at();

-- --------------------------------------------------------------------------- --
-- 4 - job_dead_letters: the replayable record of everything that failed
-- --------------------------------------------------------------------------- --
-- A failed run is not an event that scrolls past in a log. It is a unit of work the
-- platform accepted and did not deliver, and someone has to decide what happens to
-- it. This table is that decision queue: it holds enough to RE-RUN the job exactly
-- (payload), enough to diagnose it (error + traceback), and the record of what a
-- human eventually did about it (replayed / resolved).
create table if not exists public.job_dead_letters (
  id                uuid primary key default gen_random_uuid(),

  -- The run that died. ON DELETE SET NULL: pruning old runs must never silently
  -- delete the evidence that work was lost.
  run_id            uuid references public.job_runs (id) on delete set null,

  job_name          text not null,
  task              text not null default '',
  queue             public.job_queue not null default 'standard',
  correlation_id    uuid,
  idempotency_key   text,

  client_id         uuid references public.clients (id) on delete set null,
  client_name       text not null default '',
  scope_type        text not null default '',
  scope_id          uuid,

  -- Everything needed to replay: {"args": [...], "kwargs": {...}}. Sanitized by the
  -- runner before it lands here - a payload never carries a secret, because a vault
  -- reference is passed to a job, never a credential.
  payload           jsonb not null default '{}'::jsonb,

  attempts          integer not null default 0,
  --  Carried from the run so the queue can be grouped by CAUSE, not just by job name.
  reason_code       text not null default '',
  error_type        text not null default '',
  error_message     text not null default '',
  traceback         text not null default '',

  first_failed_at   timestamptz,
  dead_lettered_at  timestamptz not null default now(),

  -- The human's decision. A dead letter is OPEN until one of these is set.
  replayed_at       timestamptz,
  replayed_run_id   uuid references public.job_runs (id) on delete set null,
  replayed_by       uuid references public.users (id) on delete set null,
  resolved_at       timestamptz,
  resolved_by       uuid references public.users (id) on delete set null,
  resolution        text not null default '',

  created_at        timestamptz not null default now(),
  updated_at        timestamptz not null default now(),

  -- A resolution must say what was decided. "Closed with no note" is how a queue
  -- becomes a graveyard.
  constraint job_dead_letters_resolution_ck check (
    resolved_at is null or length(btrim(resolution)) > 0
  )
);

comment on table public.job_dead_letters is
  'Dead-letter queue: every job the platform accepted and did not deliver, with '
  'enough payload to replay it and the record of what a human decided.';

-- The queue itself: everything still awaiting a decision, oldest first (the oldest
-- unresolved failure is the most urgent one).
create index if not exists job_dead_letters_open_idx
  on public.job_dead_letters (dead_lettered_at)
  where resolved_at is null and replayed_at is null;

create index if not exists job_dead_letters_job_name_idx
  on public.job_dead_letters (job_name, dead_lettered_at desc);

create index if not exists job_dead_letters_client_idx
  on public.job_dead_letters (client_id, dead_lettered_at desc);

-- "What is the most common reason work is being lost?" - the question a dead-letter
-- queue exists to answer, and the reason `reason_code` is a column rather than prose.
create index if not exists job_dead_letters_reason_code_idx
  on public.job_dead_letters (reason_code, dead_lettered_at desc)
  where reason_code <> '';

drop trigger if exists job_dead_letters_set_updated_at on public.job_dead_letters;
create trigger job_dead_letters_set_updated_at
  before update on public.job_dead_letters
  for each row execute function public.set_updated_at();

-- --------------------------------------------------------------------------- --
-- 5 - RLS
-- --------------------------------------------------------------------------- --
-- Both tables are SERVER-WRITTEN (workers on service_role, which is BYPASSRLS), so
-- neither carries an authenticated INSERT/UPDATE/DELETE policy. Staff read; a portal
-- client has no select policy at all and therefore sees nothing - which matters
-- because error_message and payload can carry operational detail that is ours, not
-- theirs. Cancellation and replay are performed by the API on the privileged
-- connection AFTER a permission check in the router, exactly like the audit worker's
-- status writes.
alter table public.job_runs enable row level security;
alter table public.job_runs force row level security;

drop policy if exists job_runs_select on public.job_runs;
create policy job_runs_select on public.job_runs
  for select using (public.is_staff());

alter table public.job_dead_letters enable row level security;
alter table public.job_dead_letters force row level security;

drop policy if exists job_dead_letters_select on public.job_dead_letters;
create policy job_dead_letters_select on public.job_dead_letters
  for select using (public.is_staff());
