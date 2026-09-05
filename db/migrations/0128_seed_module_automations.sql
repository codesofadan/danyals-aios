-- 0128 - THE STANDING AUTOMATIONS, seeded rather than hand-built.
--
-- Operations shipped a free-form "New automation" builder: pick any capability, name
-- it, set an interval or a cron expression, save. The owner's decision is to remove
-- that form - an admin should not be composing scheduled work - and to ship a fixed
-- set of automations for the modules this platform actually has.
--
-- ONLY REAL KINDS ARE SEEDED. Every `kind` below exists in
-- app/jobs/automation_capabilities.py and has a worker behind it. In particular there
-- is deliberately NO Web 2.0 entry: the drip release is built and tested but parked by
-- owner instruction, and no capability is registered for it, so a "Web 2.0 articles"
-- row would be a schedule pointing at nothing - a switch in the UI that silently never
-- runs. That is worse than its absence.
--
-- EVERYTHING IS SEEDED PAUSED (`enabled = false`), which is the same rule the builder
-- enforced: a schedule that starts running the moment it appears is a schedule nobody
-- reviewed. Three of the five SPEND MONEY per run, and the admin turns those on
-- deliberately or not at all.
--
-- Idempotent on `kind`: a re-apply changes nothing, and an operator who has already
-- re-timed or enabled a row keeps their settings.

insert into public.automations (name, kind, schedule_kind, interval_seconds, cron_expr, enabled)
select v.name, v.kind, v.schedule_kind, v.interval_seconds, v.cron_expr, false
from (values
  -- CONTENT + WORDPRESS. One job covers both: scheduled content is what publishes to
  -- the client's WordPress site, so a separate "WordPress" schedule would be a second
  -- name for this same tick. Every minute, because a publish slot is a wall-clock time
  -- and a coarser tick would drift every publish later than the operator chose.
  ('Publish scheduled content to WordPress', 'content.publish_due', 'interval', 60, null),

  -- CITATIONS. Re-checks that listings are still live, which is a plain HTTP GET per
  -- row and costs nothing. Hourly: the per-row ladder (+3d, +14d, +60d) decides what is
  -- actually due, so this only has to wake up often enough not to delay one.
  ('Re-check citation listings are still live', 'citations.liveness_recheck', 'interval', 3600, null),

  -- AUDIT. Re-runs client audits. PAID, so 03:00 UTC daily rather than an interval:
  -- a recurring spend belongs at a predictable hour someone can reconcile against.
  ('Re-run client audits', 'audits.refresh', 'cron', null, '0 3 * * *'),

  -- OFF-PAGE. Sweeps backlinks and citations for every client. PAID. 04:00 UTC, after
  -- the audit refresh, so the two paid sweeps never contend for the same window.
  ('Sweep backlinks and citations', 'offpage.sweep', 'cron', null, '0 4 * * *'),

  -- REPORTING. Monthly client reports, 06:00 UTC on the 1st - after the overnight
  -- jobs above have landed, so a report is built on that morning's data and not on
  -- data the same night is still rewriting.
  ('Generate monthly client reports', 'reports.monthly', 'cron', null, '0 6 1 * *')
) as v(name, kind, schedule_kind, interval_seconds, cron_expr)
where not exists (
  select 1 from public.automations a where a.kind = v.kind
);
