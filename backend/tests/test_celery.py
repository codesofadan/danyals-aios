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
    entry = celery_app.conf.beat_schedule["dispatch-context"]
    assert entry["task"] == "dispatch_context"
    assert entry["schedule"] > 0
