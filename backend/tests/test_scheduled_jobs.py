"""Wave 6: the Reports "Scheduled jobs" catalogue - derived from the LIVE Celery beat
schedule and humanized. Proves interval + crontab cadences humanize correctly and that
the catalogue reflects the real ``beat_schedule`` (so the panel can never drift from
what actually runs).
"""

from __future__ import annotations

import pytest
from celery.schedules import crontab

from app.services.scheduled_jobs import (
    _humanize_crontab,
    _humanize_interval,
    _humanize_schedule,
    scheduled_jobs,
)

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


def test_humanize_schedule_dispatches_by_type() -> None:
    assert _humanize_schedule(crontab(hour=3, minute=15)) == "Daily at 03:15 UTC"
    assert _humanize_schedule(21600.0) == "Every 6 hours"
    assert _humanize_schedule(object()) == "On a schedule"


def test_scheduled_jobs_reflects_live_beat_schedule() -> None:
    jobs = scheduled_jobs()
    assert jobs, "the beat schedule should not be empty"
    names = {j.name for j in jobs}
    tasks = {j.task for j in jobs}
    # a beat-scheduled job that exists in workers/celery_app.py
    assert "dispatch-rank-checks" in names
    assert "watch_policy_sources" in tasks
    # every job carries a cadence + a plain-language description
    for j in jobs:
        assert j.cadence
        assert j.description
    # the nightly rank dispatch humanizes to a daily crontab
    rank = next(j for j in jobs if j.name == "dispatch-rank-checks")
    assert rank.cadence == "Daily at 03:15 UTC"
    assert rank.task == "dispatch_rank_checks"
