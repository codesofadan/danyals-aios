-- 0119 · When a run was SUPPOSED to happen, so "was it late?" is answerable.
--
-- §25 asks that each execution record its scheduled time alongside its actual start.
-- An automation's intended fire time survived only inside the idempotency key's text
-- (automation:{id}:{YYYY-MM-DDTHH:MM}) - parseable, but not a column anything can
-- query, sort or display.
--
-- WHY NOT REUSE `scheduled_for`. It already means something else, and the overload
-- would destroy data on exactly the runs that matter most:
--   * `defer()` writes it when a run is put back for a retry or a concurrency wait.
--     A run that retried - the one most likely to have been late - would have its
--     scheduled time overwritten by the retry's due time, silently.
--   * `start()` and `finish()` null it, because a running row is not waiting for
--     anything. To survive, it would have to stop being cleared, which would leave a
--     finished run displaying a stale future "scheduled for" in the job drawer.
-- Two facts, two columns.
--
-- NULL for everything that is not scheduled work. A job someone started by hand has
-- no scheduled time, and inventing one (created_at, say) would make every manual run
-- look punctual and turn the "late?" question into noise.

alter table public.job_runs
  add column if not exists scheduled_at timestamptz;

comment on column public.job_runs.scheduled_at is
  'When this run was DUE, for scheduled work (0119). Set once at claim from the '
  'automation''s next_due_at; never rewritten. NULL for a run nobody scheduled. '
  'Distinct from scheduled_for, which is the retry/deferral due time and is cleared '
  'when the run starts.';

-- Answering "what ran late, and by how much" without a scan. Partial: the column is
-- NULL for every hand-started run, which is most of the table.
create index if not exists job_runs_scheduled_at_idx
  on public.job_runs (scheduled_at)
  where scheduled_at is not null;
