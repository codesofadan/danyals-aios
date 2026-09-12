-- 0139_seed_grid_automation.sql - register the geo-grid refresh as a PAUSED
-- automation row (0138's sweep), following 0118 / 0128 / 0134 exactly.
--
-- WHY A ROW AND NOT A BEAT ENTRY. `celery_app.conf.beat_schedule` holds exactly two
-- entries - the automations dispatcher and the stale-job reaper - and adding a
-- business job to that table would put it beyond the reach of the manager that exists
-- to control it (`tests/test_automations.py` holds the beat set at those two). Every
-- business schedule is a row here, dispatched every 60s by `dispatch_automations`.
--
-- IT SEEDS PAUSED (`enabled = false`), which is the same rule 0118/0128/0134 enforce
-- and, for this row, the one that matters most in the table: enabling it starts a
-- RECURRING, PER-CLIENT, MULTI-PROBE spend. One tick runs every active grid, and one
-- grid is `1 + 8*rings` PAID map-pack probes - 17 at the default geometry, 41 at the
-- ceiling. Ten active grids at the default is 170 probes per tick. No other automation
-- in this table multiplies its cost by a geometry, so no other one can be enabled as
-- casually.
--
-- The insert is idempotent on `kind` (an operator who has already re-timed or enabled
-- the row keeps their settings), and the WEEKLY default interval mirrors the
-- capability's `default_interval_seconds` in
-- `backend/app/jobs/automation_capabilities.py` - the two are read together by the
-- operator surface, so they must not disagree.
--
-- The sweep REFUSES BEFORE CLAIMING when no coordinate-capable provider is configured
-- (`grid_provider_is_live`), so enabling this with no DataForSEO credential parks the
-- grids as due rather than burning their slots. The capability declares that
-- dependency as `needs`, which the create form shows as "waiting on".

insert into public.automations (name, kind, schedule_kind, interval_seconds, cron_expr, enabled)
select v.name, v.kind, v.schedule_kind, v.interval_seconds, v.cron_expr, false
from (values
  ('Refresh local search grids', 'grid.dispatch_runs', 'interval', 604800, null)
) as v(name, kind, schedule_kind, interval_seconds, cron_expr)
where not exists (
  select 1 from public.automations a where a.kind = v.kind
);
