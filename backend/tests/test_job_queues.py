"""Guards on the job contract's wiring: the queue invariant and the enum-drift check.

Two classes of bug are impossible to notice by reading, and both are silent and
expensive:

1. **The visibility-timeout invariant.** With ``task_acks_late=True`` on a Redis
   broker, a job that runs longer than ``visibility_timeout`` is redelivered to a
   SECOND worker and runs twice - double API spend, double publish. Adding a longer
   duration class without raising the window would do exactly that, and nothing would
   fail until a real 40-minute audit ran in production.

2. **Enum drift.** ``JobStatus`` in Python and ``public.job_status`` in Postgres are
   two copies of one vocabulary. If they diverge, the runner writes a value the
   database rejects - at the exact moment a job is trying to record that it failed.

Both are asserted here rather than trusted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from app.jobs.celery_task import TASK_QUEUES, route_task
from app.jobs.status import (
    BROKER_VISIBILITY_TIMEOUT,
    HEARTBEAT_GRACE_SECONDS,
    SOFT_TIME_LIMITS,
    TIME_LIMITS,
    JobQueue,
    JobStatus,
    stale_after_seconds,
)

_MIGRATION = Path(__file__).resolve().parents[2] / "db" / "migrations" / "0080_job_contract.sql"


def _enum_labels(sql: str, type_name: str) -> set[str]:
    """Pull the labels out of a ``create type ... as enum (...)`` block."""
    match = re.search(
        rf"create type public\.{type_name} as enum\s*\((?P<body>.*?)\)\s*;",
        sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert match is not None, f"{type_name} is not declared in {_MIGRATION.name}"
    return set(re.findall(r"'([a-z_]+)'", match.group("body")))


# --------------------------------------------------------------------------- #
# The invariant that stops a job running twice
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_visibility_timeout_covers_the_longest_time_limit() -> None:
    """The load-bearing Celery invariant, asserted against the LIVE app config."""
    from workers.celery_app import celery_app

    visibility = int(celery_app.conf.broker_transport_options["visibility_timeout"])
    longest = max(TIME_LIMITS.values())
    assert visibility >= longest, (
        f"visibility_timeout={visibility} is below the longest task_time_limit={longest}. "
        "A job that runs past the window is redelivered to a second worker and runs "
        "TWICE - double API spend, double publish."
    )
    assert visibility == BROKER_VISIBILITY_TIMEOUT, (
        "the broker window must be derived from TIME_LIMITS, not hardcoded, or the two "
        "will drift the next time a duration class changes"
    )


@pytest.mark.unit
def test_every_duration_class_has_a_time_limit_and_a_soft_limit() -> None:
    """A new queue cannot be added without declaring how long it may run."""
    for queue in JobQueue:
        assert queue in TIME_LIMITS, f"{queue} has no hard time limit"
        assert queue in SOFT_TIME_LIMITS, f"{queue} has no soft time limit"
        assert SOFT_TIME_LIMITS[queue] < TIME_LIMITS[queue], (
            f"{queue}'s soft limit must leave the job time to record an honest outcome "
            "before the hard kill"
        )
        assert SOFT_TIME_LIMITS[queue] > 0


@pytest.mark.unit
def test_the_duration_classes_are_ordered() -> None:
    """interactive < standard < long < browser. If this ever stops holding, the class
    names have stopped meaning anything to the person choosing one."""
    ordered = [
        TIME_LIMITS[JobQueue.INTERACTIVE],
        TIME_LIMITS[JobQueue.STANDARD],
        TIME_LIMITS[JobQueue.LONG],
        TIME_LIMITS[JobQueue.BROWSER],
    ]
    assert ordered == sorted(ordered)
    assert len(set(ordered)) == len(ordered)


@pytest.mark.unit
def test_the_reaper_waits_longer_than_the_job_is_allowed_to_run() -> None:
    """Otherwise the reaper kills healthy long jobs - the failure mode that makes an
    operator turn the reaper off, which is how stuck runs become permanent."""
    for queue in JobQueue:
        assert stale_after_seconds(queue) == TIME_LIMITS[queue] + HEARTBEAT_GRACE_SECONDS
        assert stale_after_seconds(queue) > TIME_LIMITS[queue]


# --------------------------------------------------------------------------- #
# Routing
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_the_default_queue_is_left_at_celerys_own_default() -> None:
    """Renaming the default queue is a live-deploy hazard, not a tidy-up.

    The 39 tasks that predate the contract publish to the DEFAULT queue. Renaming it
    strands every message already sitting on the old name at the moment of a deploy,
    and a worker started without ``-Q`` stops consuming them entirely. Legacy tasks
    keep `celery` until each is migrated to ``@aios_job``.
    """
    from workers.celery_app import celery_app

    assert celery_app.conf.task_default_queue == "celery"
    assert celery_app.conf.task_default_queue not in {q.value for q in JobQueue}


@pytest.mark.unit
def test_the_deployed_worker_consumes_every_queue_the_router_can_publish_to() -> None:
    """The failure this catches is silent and total.

    ``celery worker`` with no ``-Q`` consumes ONLY the default queue. If a duration
    class is added here but not to the systemd unit, every job routed to it sits in
    Redis with nothing reading it - and the platform looks IDLE rather than broken.
    Nothing else in the test suite can see that, because it is a deployment fact.
    """
    unit = (
        Path(__file__).resolve().parents[2] / "infra" / "systemd" / "aios-worker.service"
    ).read_text(encoding="utf-8")
    exec_line = next(
        line for line in unit.splitlines() if line.startswith("ExecStart=") and "worker" in line
    )
    match = re.search(r"-Q\s+([\w,]+)", exec_line)
    assert match is not None, "the worker unit must pass -Q, or it consumes only the default queue"
    _assert_consumes_every_queue(set(match.group(1).split(",")), "infra/systemd/aios-worker.service")


def _assert_consumes_every_queue(consumed: set[str], source: str) -> None:
    missing = {q.value for q in JobQueue} - consumed
    assert not missing, f"the worker in {source} never consumes: {sorted(missing)}"
    assert "celery" in consumed, f"the legacy default queue must still be consumed in {source}"


@pytest.mark.unit
def test_the_compose_worker_consumes_every_queue_the_router_can_publish_to() -> None:
    """The systemd unit was correct and the compose stack was not - and the compose
    stack is what app.qanry.com actually runs.

    The unit test above pinned ONE of the two deployment definitions, so the -Q that
    its own comment calls required was missing from the other for as long as both
    existed. Every @aios_job task in the deployed stack - the design replicator
    included - was published to a queue no process consumed, and the jobs sat
    "queued" indefinitely with the platform reporting no error at all.

    Parsed by regex rather than a YAML load because pyyaml is not a backend
    dependency, and the assert-before-use below fails loudly on a reformat instead
    of vacuously passing on a command it could not find.
    """
    compose = (Path(__file__).resolve().parents[2] / "docker-compose.yml").read_text(
        encoding="utf-8"
    )
    worker_commands = [
        line
        for line in compose.splitlines()
        if line.lstrip().startswith("command:") and '"celery"' in line and '"worker"' in line
    ]
    assert len(worker_commands) == 1, (
        "expected exactly one celery worker command in docker-compose.yml; "
        f"found {len(worker_commands)}. A second worker service must ALSO pass -Q "
        "for every queue, so extend this test rather than relaxing it."
    )

    match = re.search(r'"-Q",\s*"([\w,]+)"', worker_commands[0])
    assert match is not None, (
        "the compose worker must pass -Q, or it consumes only the default queue "
        "and every duration-class job sits unread"
    )
    _assert_consumes_every_queue(set(match.group(1).split(",")), "docker-compose.yml")


@pytest.mark.unit
def test_an_unregistered_task_falls_through_to_the_default_queue() -> None:
    """The 39 tasks that predate the contract must keep working while they migrate."""
    assert route_task("some_legacy_task", (), {}, {}) is None


@pytest.mark.unit
def test_a_declared_task_is_actually_routed_there_by_celery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Prove the WHOLE chain, not just the lookup.

    ``TASK_QUEUES`` -> ``route_task`` -> ``task_routes`` -> the queue Celery resolves.
    Asserting only that ``route_task`` returns the right dict would pass even if the
    router were never wired into the app config - which is the actual thing that would
    break, and would break silently.

    A probe entry rather than a real task, because ``TASK_QUEUES`` is populated at
    DECORATION time and no production task has been migrated to ``@aios_job`` yet: a
    loop over the live registry would pass vacuously today and keep passing.
    """
    from workers.celery_app import celery_app

    monkeypatch.setitem(TASK_QUEUES, "_probe_routing_task", JobQueue.LONG.value)
    routed = celery_app.amqp.router.route({}, "_probe_routing_task", [], {})
    assert routed["queue"].name == JobQueue.LONG.value


@pytest.mark.unit
def test_an_undeclared_task_is_routed_to_the_default_queue_by_celery() -> None:
    """The other half: the 39 legacy tasks must keep landing where they always did."""
    from workers.celery_app import celery_app

    routed = celery_app.amqp.router.route({}, "some_legacy_task", [], {})
    assert routed["queue"].name == "celery"


@pytest.mark.unit
def test_every_registered_task_routes_to_a_real_duration_class() -> None:
    """A consistency sweep over whatever HAS been migrated. Empty until the first
    task moves, which is why the two tests above carry the real proof."""
    valid = {q.value for q in JobQueue}
    for task_name, queue in TASK_QUEUES.items():
        assert queue in valid, f"{task_name} is routed to unknown queue {queue!r}"
        assert route_task(task_name, (), {}, {}) == {"queue": queue}


# --------------------------------------------------------------------------- #
# Python <-> Postgres vocabulary
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_the_python_and_postgres_status_vocabularies_are_identical() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8")
    assert _enum_labels(sql, "job_status") == {s.value for s in JobStatus}


@pytest.mark.unit
def test_the_python_and_postgres_queue_vocabularies_are_identical() -> None:
    sql = _MIGRATION.read_text(encoding="utf-8")
    assert _enum_labels(sql, "job_queue") == {q.value for q in JobQueue}


@pytest.mark.unit
def test_the_migration_enforces_a_reason_on_a_partial_outcome() -> None:
    """The check constraint is the backstop for the whole 'no fake success' rule -
    it must survive anyone bypassing the Python layer."""
    sql = _MIGRATION.read_text(encoding="utf-8").lower()
    assert "job_runs_reason_required_ck" in sql
    assert "status not in ('degraded', 'blocked') or length(btrim(reason)) > 0" in sql
    assert "job_runs_error_required_ck" in sql
    assert "job_runs_finished_ck" in sql


@pytest.mark.unit
def test_both_job_tables_are_rls_protected() -> None:
    """The repo-wide rule: no public table without ENABLE + FORCE RLS and a policy."""
    sql = _MIGRATION.read_text(encoding="utf-8").lower()
    for table in ("job_runs", "job_dead_letters"):
        assert f"alter table public.{table} enable row level security;" in sql
        assert f"alter table public.{table} force row level security;" in sql
        assert f"create policy {table}_select on public.{table}" in sql
