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
