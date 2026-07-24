-- 0055_scheduled_job_runs.sql - Reports/cron visibility: the durable ledger of the
-- platform's AUTONOMOUS Celery-beat runs, and of the downloadable reports those runs
-- produce.
--
-- The admin Reports tab shows the LIVE beat schedule (derived from
-- workers/celery_app.py). This table adds the two facts the schedule alone cannot
-- carry: (1) WHEN each scheduled job last ran and HOW it went (last_run / last_status),
-- and (2) the actual REPORTS the report-producing jobs generate - a per-client monthly
-- SEO summary, stored as a downloadable jsonb `report` payload.
--
-- ONE table serves BOTH surfaces on purpose:
--   * "Scheduled jobs" panel  -> latest row per job_name (any row).
--   * "Reports library"       -> rows where `report is not null` (produced artifacts).
-- A pure heartbeat run (audit-refresh sweep, off-page sweep) writes a row with
-- report = NULL; the monthly-report job writes one row per client WITH a report payload.
--
-- WRITTEN ONLY BY THE SERVER: the beat workers append rows on the service_role
-- (BYPASSRLS) connection - exactly like public_audits / the audit worker's status
-- writes - so there is no authenticated INSERT/UPDATE policy. Any provisioned staff may
-- READ (mirrors 0020_reports); a portal client is excluded by is_staff() (no select
-- policy), so the operator's autonomous-jobs view never leaks to a client. No delete in v1.

do $$ begin
  if not exists (select 1 from pg_type where typname = 'scheduled_job_status') then
    create type public.scheduled_job_status as enum (
      'ok', 'error', 'degraded', 'blocked', 'skipped'
    );
  end if;
end $$;

create table if not exists public.scheduled_job_runs (
  id           uuid primary key default gen_random_uuid(),
  -- The beat entry key (a stable slug, e.g. 'generate-monthly-reports') + the Celery
  -- task name it ran. job_name is what the "Scheduled jobs" panel joins on.
  job_name     text not null,
  task         text not null default '',
  status       public.scheduled_job_status not null default 'ok',
  -- A short human line ("queued 4 audits, skipped 1 recent").
  detail       text not null default '',
  -- Produced-report linkage (NULL for a pure heartbeat run). client_name is a display
  -- SNAPSHOT so the internal client_id never has to be surfaced (like every ledger).
  client_id    uuid references public.clients (id) on delete set null,
  client_name  text not null default '',
  title        text not null default '',
  period       text not null default '',      -- e.g. 'July 2026'
  -- The downloadable report summary. Its PRESENCE is what makes a row a produced report
  -- (audit-score trend, ranks, content shipped, backlinks/citations delta). NULL = none.
  report       jsonb,
  created_at   timestamptz not null default now()
);

-- Latest-run-per-job lookup (the schedule panel's distinct-on) + newest-first.
create index if not exists scheduled_job_runs_job_name_idx
  on public.scheduled_job_runs (job_name, created_at desc);
-- The produced-reports library: only rows that carry a report payload, newest first.
create index if not exists scheduled_job_runs_report_idx
  on public.scheduled_job_runs (created_at desc)
  where report is not null;

-- --- RLS ----------------------------------------------------------------------
-- Written ONLY by the server (service_role, BYPASSRLS) - so no authenticated
-- INSERT/UPDATE policy (mirrors public_audits). Any staff may READ; clients are
-- excluded by is_staff() (no select policy for them).
alter table public.scheduled_job_runs enable row level security;
alter table public.scheduled_job_runs force row level security;

create policy scheduled_job_runs_select on public.scheduled_job_runs
  for select using (public.is_staff());
