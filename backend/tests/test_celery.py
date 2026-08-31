"""Chunk 8 gate: Celery config invariants (broker-free, no worker needed)."""

from __future__ import annotations

import pytest

from workers.celery_app import celery_app


@pytest.mark.unit
def test_acks_late_and_prefetch_are_safe_for_long_jobs() -> None:
    assert celery_app.conf.task_acks_late is True
    assert celery_app.conf.worker_prefetch_multiplier == 1


@pytest.mark.unit
def test_json_only_serialization() -> None:
    assert celery_app.conf.task_serializer == "json"
    assert celery_app.conf.result_serializer == "json"
    assert celery_app.conf.accept_content == ["json"]


@pytest.mark.unit
def test_utc_timezone() -> None:
    assert celery_app.conf.timezone == "UTC"
    assert celery_app.conf.enable_utc is True


@pytest.mark.unit
def test_visibility_timeout_covers_hard_time_limit() -> None:
    # the double-execution guard: a redelivery window shorter than the hard time
    # limit would run an in-flight job twice under task_acks_late
    visibility_timeout = celery_app.conf.broker_transport_options["visibility_timeout"]
    assert visibility_timeout >= celery_app.conf.task_time_limit


@pytest.mark.unit
def test_ping_task_is_registered() -> None:
    # a worker imports the `include` modules at startup via import_default_modules;
    # do the same here so registration is proven without a running broker
    celery_app.loader.import_default_modules()
    assert "ping" in celery_app.tasks


@pytest.mark.unit
def test_context_worker_tasks_are_registered() -> None:
    celery_app.loader.import_default_modules()
    assert "dispatch_context" in celery_app.tasks
    assert "compact_context" in celery_app.tasks


@pytest.mark.unit
def test_context_dispatch_is_on_the_beat_schedule() -> None:
    # the debounced dispatcher runs every context_debounce_seconds (config only;
    # no beat process is started here)
    from workers.celery_app import _BEAT_SCHEDULE_DISABLED as PARKED

    # Cron is PARKED platform-wide (owner instruction 2026-08-19), so the LIVE
    # beat table is empty and this asserts the preserved one: the wiring must
    # survive the parking, or switching cron back on would silently skip this
    # job. The policy itself is asserted once, in tests/test_scheduled_jobs.py.
    entry = PARKED["dispatch-context"]
    assert entry["task"] == "dispatch_context"
    assert entry["schedule"] > 0


@pytest.mark.unit
def test_the_worker_validates_its_own_configuration() -> None:
    """The documented fail-fast on missing production secrets ran in the API's
    lifespan and NOWHERE ELSE, so the process that actually SPENDS MONEY started
    blind: a worker with no vault key or no provider key came up healthy, accepted
    jobs, and failed them one at a time at runtime instead of refusing to start."""
    import inspect

    import workers.celery_app as mod

    source = inspect.getsource(mod._init_worker_db_pools)
    assert "validate_settings" in source, (
        "the worker process init must validate config, or prod misconfiguration "
        "is only discovered one failed job at a time"
    )


# --------------------------------------------------------------------------- #
# The two maintenance sweeps that nothing was calling
# --------------------------------------------------------------------------- #
# NOTE for whoever adds the next beat entry: the "every task named in the preserved
# schedule is actually registered" gate already exists, once, as
# tests/test_scheduled_jobs.py::TestCronIsParkedOnPurpose::
# test_the_preserved_schedule_has_not_rotted_while_parked. Do not add a third copy of
# it here. The tests below assert something that one cannot: that these two ENTRIES
# exist at all, and that adding them did not un-park cron.
@pytest.mark.unit
def test_nightly_backup_is_scheduled_or_the_config_panel_promises_a_backup_nothing_takes() -> None:
    """`backup_config.nightly_enabled` defaults to true and the Backups panel renders
    "Nightly 02:00 UTC" with a next-backup countdown, but the only caller of the pg_dump
    service was POST /backups/run - a human. Found by grepping for a caller of
    `run_snapshot` outside the router and finding none: the platform was rendering a
    schedule it had no mechanism to keep."""
    from workers.celery_app import _BEAT_SCHEDULE_DISABLED as PARKED

    celery_app.loader.import_default_modules()
    entry = PARKED["nightly-backup"]
    assert entry["task"] == "run_nightly_backup"
    assert entry["task"] in celery_app.tasks, "the beat entry names a task no worker has"
    # 02:00 UTC, matching the nightly_time 0026 seeds and the panel renders.
    assert set(entry["schedule"].hour) == {2}
    assert set(entry["schedule"].minute) == {0}


@pytest.mark.unit
def test_stuck_run_reaper_is_scheduled_or_a_dead_worker_shrinks_a_client_cap_forever() -> None:
    """`reap_stale_job_runs` had existed and been registered since the job contract
    landed with NOTHING calling it - no beat entry, no endpoint, no caller. Until
    something called it, a run left `running` by an OOM kill permanently held a slot
    against `JobRunsStore.start`'s per-client concurrency cap.

    It is scheduled now (2026-09-01), and it is one of only two live beat entries: it
    repairs the job ledger, costs nothing, and must NOT be an automation an operator
    can pause - turning it off would make stuck runs permanent, which is exactly when
    it matters most."""
    celery_app.loader.import_default_modules()
    entry = celery_app.conf.beat_schedule["reap-stale-job-runs"]
    assert entry["task"] == "reap_stale_job_runs"
    assert entry["task"] in celery_app.tasks, "the beat entry names a task no worker has"


@pytest.mark.unit
def test_no_business_job_was_pasted_into_the_live_beat_table() -> None:
    """Beat carries the dispatcher and the ledger reaper, and nothing else.

    Business jobs are rows in `public.automations` (0118), seeded paused, enabled from
    the dashboard. The cheapest way to get this wrong is to paste an entry into the
    live `beat_schedule` instead - which would start firing pg_dump on a schedule
    nobody can pause without a deploy, the exact problem the automations table
    replaced."""
    assert set(celery_app.conf.beat_schedule) == {
        "dispatch-automations",
        "reap-stale-job-runs",
    }
    assert "nightly-backup" not in celery_app.conf.beat_schedule
