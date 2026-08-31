-- 0118 · Automations: scheduled work an admin can see, change and switch off.
--
-- THE STATE THIS REPLACES. `celery_app.conf.beat_schedule` was emptied on 2026-08-19
-- by request, with the fourteen entries kept verbatim beside it as
-- `_BEAT_SCHEDULE_DISABLED`. So nothing recurring ran at all: no nightly backup, no
-- content publishing at its scheduled time, no citation liveness re-check, no monthly
-- reports. The Operations panel that lists scheduled jobs reads the live beat config,
-- so it honestly rendered zero rows - the platform was not lying about it, it simply
-- had nothing to say.
--
-- Restoring the static table would bring back all fourteen at once, which is exactly
-- what the owner did not want, and would still leave every schedule editable only by
-- a developer with a deploy.
--
-- WHY A TABLE AND NOT A RESTORED beat_schedule. Beat reads its schedule at process
-- start. Editing a cadence, adding an automation, choosing which clients it covers, or
-- pausing one would each need a restart - so the admin UI the brief asks for cannot be
-- built on it. A single beat entry that ticks and reads due rows from Postgres is the
-- pattern this codebase already uses twice (`dispatch_context` claims due rows from
-- `context_dirty`; `dispatch_rank_checks` claims due subscriptions FOR UPDATE SKIP
-- LOCKED). This is that pattern, with the schedule made editable.
--
-- WHAT DOES NOT LIVE HERE. Execution history: every fire is enqueued under the job
-- contract with `correlation_id = automation.id`, so `job_runs` already answers "what
-- has this automation done, when, and with what outcome" through an indexed query.
-- A second history table would be a second version of the truth.
--
-- EVERYTHING SEEDS PAUSED. `enabled` defaults false and every seeded row below is
-- false. Re-enabling beat therefore changes nothing on its own: an admin turns on the
-- automations they actually want, one at a time, having seen which ones spend money.

create table if not exists public.automations (
  id                    uuid primary key default gen_random_uuid(),
  -- The operator's own name for it, and the handle the UI de-duplicates on.
  name                  text not null,
  -- WHAT it does. A closed vocabulary validated in code against
  -- app/jobs/automation_capabilities.py, deliberately NOT an enum: capabilities are
  -- added as the platform grows them, and a migration per capability would make that
  -- a deploy-shaped decision. A row whose kind no longer exists is refused at
  -- dispatch and shown as broken, rather than firing into nothing.
  kind                  text not null,
  -- Per-capability arguments. For a client-scoped kind: {"clientIds": [...]}.
  params                jsonb not null default '{}'::jsonb,

  schedule_kind         text not null check (schedule_kind in ('interval', 'cron')),
  interval_seconds      integer,
  cron_expr             text,
  -- Exactly one of the two, matching schedule_kind. Without this a row can carry a
  -- cron string AND an interval, and which one wins becomes a code detail rather
  -- than a stated fact.
  constraint automations_interval_iff_interval
    check ((schedule_kind = 'interval') = (interval_seconds is not null)),
  constraint automations_cron_iff_cron
    check ((schedule_kind = 'cron') = (cron_expr is not null)),
  -- The dispatcher ticks once a minute; a shorter interval is a promise the platform
  -- cannot keep.
  constraint automations_interval_floor
    check (interval_seconds is null or interval_seconds >= 60),

  enabled               boolean not null default false,
  -- Tell someone when an automation fails. Off would make a broken automation
  -- indistinguishable from one that had nothing to do.
  notify_on_failure     boolean not null default true,
  notify_channels       jsonb not null default '{"inApp": true, "email": false}'::jsonb,

  -- When it is next due. NULL while disabled: a paused automation has no next run,
  -- and storing one would make "paused" look like "about to fire".
  next_due_at           timestamptz,
  last_fired_at         timestamptz,
  -- The most recent run, for the row's status. ON DELETE SET NULL because a pruned
  -- ledger row must not delete the automation that produced it.
  last_run_id           uuid references public.job_runs (id) on delete set null,
  -- The run a failure notice has already been sent for, so a failing automation
  -- notifies once rather than every minute until someone fixes it.
  last_notified_run_id  uuid,

  created_by            uuid references public.users (id) on delete set null,
  created_at            timestamptz not null default now(),
  updated_at            timestamptz not null default now(),

  constraint automations_name_unique unique (name)
);

-- The dispatcher's only query: enabled and due. Partial, because a paused automation
-- is never a candidate and there is no reason to carry it in the index.
create index if not exists automations_due_idx
  on public.automations (next_due_at)
  where enabled;

drop trigger if exists automations_set_updated_at on public.automations;
create trigger automations_set_updated_at
  before update on public.automations
  for each row execute function public.set_updated_at();

alter table public.automations enable row level security;
alter table public.automations force row level security;

-- Staff read. There is NO write policy for `authenticated`: every mutation runs on
-- the privileged connection behind a lead-only route, the same shape `job_runs` uses.
-- A client holds no policy here at all and `is_staff()` excludes them, so the table
-- is closed to them twice over.
drop policy if exists automations_read on public.automations;
create policy automations_read on public.automations
  for select using (public.is_staff());

comment on table public.automations is
  'Scheduled work an admin can create, edit, pause and audit (0118). One beat entry '
  '(dispatch_automations) reads due rows from here, so a cadence change needs no '
  'deploy. Execution history lives in job_runs, correlated by automation id.';

-- ---------------------------------------------------------------------------
-- The fourteen parked entries, as automations. ALL PAUSED.
--
-- Two of the fourteen are deliberately absent:
--   * reap-stale-job-runs   - it repairs the job ledger and must not be pausable from
--                             the surface it protects. It stays a static beat entry.
--   * watch_policy_sources  - superseded by the daily generator; not scheduled anywhere.
--
-- The cadences are the ones the parked table used, so switching one on restores the
-- behaviour that was there before rather than a new guess at it.
-- ---------------------------------------------------------------------------
insert into public.automations (name, kind, schedule_kind, interval_seconds, cron_expr, enabled)
values
  ('Publish scheduled content',          'content.publish_due',        'interval', 300,     null, false),
  ('Re-check citation listings',         'citations.liveness_recheck', 'interval', 3600,    null, false),
  ('Keep client context up to date',     'context.compact',            'interval', 1800,    null, false),
  ('Repair the context index',           'context.reconcile',          'interval', 3600,    null, false),
  ('Mark overdue invoices past due',     'billing.mark_past_due',      'interval', 86400,   null, false),
  ('Nightly backup',                     'backups.nightly',            'cron',     null, '0 2 * * *', false),
  ('Daily policy brief',                 'policy.daily_brief',         'cron',     null, '0 6 * * *', false),
  ('Generate monthly client reports',    'reports.monthly',            'cron',     null, '0 6 1 * *', false),
  ('Re-run client audits',               'audits.refresh',             'interval', 604800,  null, false),
  ('Sweep backlinks and citations',      'offpage.sweep',              'interval', 604800,  null, false),
  ('Refresh local map-pack ranks',       'ranks.refresh_local',        'interval', 86400,   null, false),
  ('Check tracked keyword rankings',     'ranks.dispatch_checks',      'cron',     null, '15 3 * * *', false),
  ('Roll up ranking history',            'ranks.rollup_history',       'cron',     null, '10 4 * * 0', false)
on conflict (name) do nothing;
