"""Wave 6: the Reports "Scheduled jobs" catalogue - derived from the LIVE Celery beat
schedule and humanized. Proves interval + crontab cadences humanize correctly and that
the catalogue reflects the real ``beat_schedule`` (so the panel can never drift from
what actually runs).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from celery.schedules import crontab

from app.config import Settings
from app.services.scheduled_jobs import (
    _humanize_crontab,
    _humanize_interval,
    _humanize_schedule,
    scheduled_jobs,
)
from workers.celery_app import _BEAT_SCHEDULE_DISABLED as PARKED
from workers.celery_app import celery_app

pytestmark = pytest.mark.unit


def test_humanize_interval_coarsest_unit() -> None:
    assert _humanize_interval(30) == "Every 30 seconds"
    assert _humanize_interval(60) == "Every 1 minute"
    assert _humanize_interval(300) == "Every 5 minutes"
    assert _humanize_interval(21600) == "Every 6 hours"
    assert _humanize_interval(86400) == "Every 1 day"


def test_humanize_crontab_daily_and_weekly() -> None:
    assert _humanize_crontab(crontab(hour=3, minute=15)) == "Daily at 03:15 UTC"
    assert (
        _humanize_crontab(crontab(hour=4, minute=10, day_of_week=0))
        == "Weekly on Sunday at 04:10 UTC"
    )


def test_humanize_crontab_monthly() -> None:
    # A fixed day-of-month reads as a monthly cadence (not "Daily").
    assert (
        _humanize_crontab(crontab(day_of_month=1, hour=6, minute=0))
        == "Monthly on day 1 at 06:00 UTC"
    )


def test_humanize_schedule_dispatches_by_type() -> None:
    assert _humanize_schedule(crontab(hour=3, minute=15)) == "Daily at 03:15 UTC"
    assert _humanize_schedule(21600.0) == "Every 6 hours"
    assert _humanize_schedule(object()) == "On a schedule"


def test_scheduled_jobs_reflects_live_beat_schedule() -> None:
    jobs = scheduled_jobs(schedule=PARKED)
    assert jobs, "the preserved schedule should not be empty"
    names = {j.name for j in jobs}
    tasks = {j.task for j in jobs}
    # a beat-scheduled job that exists in workers/celery_app.py
    assert "dispatch-rank-checks" in names
    # Policy Radar now runs the Anthropic daily GENERATOR on the beat (the Google-scrape
    # watcher was moved off the schedule), so the generator task is the one present.
    assert "generate_policy_daily" in tasks
    assert "watch_policy_sources" not in tasks
    # every job carries a cadence + a plain-language description
    for j in jobs:
        assert j.cadence
        assert j.description
    # the nightly rank dispatch humanizes to a daily crontab
    rank = next(j for j in jobs if j.name == "dispatch-rank-checks")
    assert rank.cadence == "Daily at 03:15 UTC"
    assert rank.task == "dispatch_rank_checks"


def test_beat_schedule_includes_the_autonomous_report_jobs() -> None:
    jobs = scheduled_jobs(schedule=PARKED)
    names = {j.name for j in jobs}
    # the three new autonomous SEO/reporting jobs are actually registered
    assert {"refresh-client-audits", "generate-monthly-reports", "sweep-offpage-monitors"} <= names
    monthly = next(j for j in jobs if j.name == "generate-monthly-reports")
    assert monthly.task == "generate_monthly_reports"
    assert monthly.cadence.startswith("Monthly on day")
    # every entry now derives a next-run for an interval-scheduled job (no celery clock
    # needed): the context dispatcher runs on a plain interval.
    ctx = next(j for j in jobs if j.name == "dispatch-context")
    assert ctx.next_run is not None


def test_scheduled_jobs_surfaces_last_run_and_status() -> None:
    ran_at = datetime(2026, 7, 20, 3, 15, tzinfo=UTC)
    jobs = scheduled_jobs(
        schedule=PARKED,
        last_runs={"dispatch-rank-checks": {"status": "ok", "created_at": ran_at}},
    )
    rank = next(j for j in jobs if j.name == "dispatch-rank-checks")
    assert rank.last_status == "ok"
    assert rank.last_run == ran_at.isoformat()
    # a job with no ledger row carries no last-run
    ctx = next(j for j in jobs if j.name == "dispatch-context")
    assert ctx.last_run is None and ctx.last_status is None


def test_scheduled_jobs_flags_waiting_on_absent_provider_key() -> None:
    # A keyless dev Settings: no audit engine + no off-page provider configured.
    settings = Settings(_env_file=None)  # type: ignore[call-arg]
    jobs = scheduled_jobs(schedule=PARKED, settings=settings)
    audit = next(j for j in jobs if j.name == "refresh-client-audits")
    sweep = next(j for j in jobs if j.name == "sweep-offpage-monitors")
    monthly = next(j for j in jobs if j.name == "generate-monthly-reports")
    brief = next(j for j in jobs if j.name == "generate-policy-daily")
    assert audit.waiting_on and "audit engine" in audit.waiting_on
    assert sweep.waiting_on and "DataForSEO" in sweep.waiting_on
    # the daily Policy Radar brief is Anthropic-only, so keyless it waits on the key
    assert brief.waiting_on and "Anthropic" in brief.waiting_on
    # the monthly report reads only the platform's own data — it never waits on a key
    assert monthly.waiting_on is None


# --------------------------------------------------------------------------- #
# The policy these tests sit on top of
# --------------------------------------------------------------------------- #
class TestCronIsParkedOnPurpose:
    """The cron policy, recorded in one place - and CHANGED, deliberately, on
    2026-09-01 with the owner's approval.

    It was: nothing is scheduled at all. Beat was emptied on 2026-08-19 and the
    fourteen entries kept beside it as `_BEAT_SCHEDULE_DISABLED`. Wholesale was the
    only option available, because a static schedule is read at process start - so
    pausing one entry, re-timing one, or scoping one to particular clients each
    needed a developer and a deploy.

    It is now: the business jobs are ROWS (`public.automations`, 0118), every one of
    them seeded paused, each enabled and re-timed from the dashboard. Beat carries
    only the two things that are not anyone's business decision - the dispatcher that
    makes the editable schedule work, and the ledger reaper that must not be pausable
    from the surface it protects.

    So nothing recurring runs until an admin turns it on, which is what the original
    park was protecting, and turning one on is no longer a deploy.

    The behaviour of `scheduled_jobs()` is still tested against the preserved table
    above; the POLICY is asserted exactly once, here.
    """

    def test_beat_carries_only_the_two_infrastructure_entries(self) -> None:
        assert set(celery_app.conf.beat_schedule) == {
            "dispatch-automations",
            "reap-stale-job-runs",
        }, (
            "Business jobs belong in public.automations, where an admin can pause and "
            "re-time them. An entry added HERE is beyond the reach of the manager built "
            "to control it. If that is deliberate, update THIS test - it is the one "
            "place the policy is recorded."
        )

    def test_no_business_job_runs_without_somebody_enabling_it(self) -> None:
        """What the 2026-08-19 park was actually protecting: no recurring work fires
        on its own. Still true - every seeded automation starts disabled, and the
        dispatcher only claims rows where `enabled`."""
        from pathlib import Path

        sql = (
            Path(__file__).resolve().parents[2] / "db" / "migrations" / "0118_automations.sql"
        ).read_text(encoding="utf-8")
        seeded = sql.split("insert into public.automations", 1)[1].split(";")[0]
        assert " true" not in seeded.lower()

    def test_the_preserved_schedule_has_not_rotted_while_parked(self) -> None:
        """A parked schedule is dead weight the moment it names a task that no
        longer exists - and nothing would notice until someone switched it on."""
        celery_app.loader.import_default_modules()
        registered = set(celery_app.tasks)
        scheduled = {str(entry.get("task", "")) for entry in PARKED.values()}
        missing = sorted(t for t in scheduled if t and t not in registered)
        assert not missing, f"preserved schedule names unregistered tasks: {missing}"
