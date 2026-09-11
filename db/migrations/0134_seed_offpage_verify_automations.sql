-- 0134_seed_offpage_verify_automations.sql - the two off-page VERIFICATION sweeps,
-- seeded as standing automations (0128 pattern; off-page redesign Phase 5, plan §7).
--
-- ONLY REAL KINDS ARE SEEDED. Both kinds below are registered in
-- app/jobs/automation_capabilities.py and each names a worker that exists
-- (workers/tasks/offpage.py: `verify_backlinks` / `recheck_web2_links`).
-- tests/test_automations.py fails the build if either task is not registered with
-- Celery, so a typo here cannot ship as a schedule pointing at nothing.
--
-- BOTH ARE FREE. Each sweep is plain HTTP GETs against pages we already know about -
-- no provider call, no metered spend - which is why `paid=False` in the registry.
-- They still seed PAUSED (`enabled = false`), the same rule 0118/0128 enforce: a
-- schedule that starts running the moment it appears is a schedule nobody reviewed,
-- and un-pausing is the owner's deliberate action (plan §10 step 18).
--
-- Daily (86400s): the per-row ladder (live -> +30d, missing -> +7d confirm) decides
-- what is actually due, so the tick only has to wake often enough not to delay one.
--
-- Idempotent on `kind`: a re-apply changes nothing, and an operator who has already
-- re-timed or enabled a row keeps their settings. Celery beat stays off - these rows
-- are consumed by the existing automations dispatcher, not by a new beat entry.

insert into public.automations (name, kind, schedule_kind, interval_seconds, cron_expr, enabled)
select v.name, v.kind, v.schedule_kind, v.interval_seconds, v.cron_expr, false
from (values
  -- BACKLINKS. Fetches each due referring page and looks for the client's link
  -- itself, so 'live' is an observation rather than a provider's claim.
  ('Verify backlinks are really live', 'offpage.verify_backlinks', 'interval', 86400, null),

  -- WEB 2.0. Re-fetches published properties and confirms the placed link is still
  -- on the page - a 404''d post or a stripped link demotes honestly, never silently.
  ('Re-check Web 2.0 links are still live', 'web2.link_recheck', 'interval', 86400, null)
) as v(name, kind, schedule_kind, interval_seconds, cron_expr)
where not exists (
  select 1 from public.automations a where a.kind = v.kind
);
