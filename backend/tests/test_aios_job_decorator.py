"""The Celery binding: that ``@aios_job`` wires a real task to the real contract.

``tests/test_job_contract.py`` proves the runner's decisions. This file proves the
much thinner layer that connects those decisions to Celery, and it is thin on
purpose - but the four things it does are each a silent failure if wrong:

  * the task is REGISTERED under its pinned name (a typo here means the enqueue
    succeeds and nothing ever runs it);
  * it is ROUTED to its duration class and carries that class's time limits (a job on
    the wrong queue either blocks short work or gets killed part-way);
  * the reserved ``_aios_*`` kwargs are STRIPPED before the job body sees them (a
    leaked kwarg is a TypeError at the worker, on every call);
  * a ``retry`` disposition becomes an actual Celery ``Retry`` (without this the
    retry ladder is decorative - the runner defers the row and nothing redelivers it).
"""

from __future__ import annotations

from typing import Any

import pytest
from celery.exceptions import Retry

import app.jobs.celery_task as celery_task
from app.jobs import JobOutcome, JobQueue, JobTarget, RetryableJobError
from app.jobs.celery_task import TASK_QUEUES, aios_job, enqueue_child
from app.jobs.contract import JobContext
from app.jobs.status import SOFT_TIME_LIMITS, TIME_LIMITS
from tests.test_job_contract import FakeStore


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    """Point the decorator's store lookup at an in-memory double."""
    fake = FakeStore()
    monkeypatch.setattr(celery_task, "job_runs_store", lambda: fake)
    return fake


# Registered once at import - Celery's registry is process-global, so declaring these
# inside a test would re-register on every run.
@aios_job(
    name="_test_contract_ok",
    job_name="test.ok",
    queue=JobQueue.LONG,
    scope_type="test",
    target=lambda x: JobTarget(idempotency_key=f"test.ok:{x}", client_id="c-1", client_name="Acme"),
)
def _ok_job(ctx: JobContext, x: int) -> JobOutcome:
    return JobOutcome.completed(f"x={x}", result={"x": x})


@aios_job(
    name="_test_contract_flaky",
    job_name="test.flaky",
    queue=JobQueue.STANDARD,
    max_attempts=3,
    retry_backoff=5.0,
    target=lambda: JobTarget(idempotency_key="test.flaky:1"),
)
def _flaky_job(ctx: JobContext) -> JobOutcome:
    raise RetryableJobError("provider returned 503")


@aios_job(name="_test_contract_bare", job_name="test.bare", queue=JobQueue.INTERACTIVE)
def _bare_job(ctx: JobContext, **kwargs: Any) -> JobOutcome:
    return JobOutcome.completed(detail=repr(sorted(kwargs)))


# --------------------------------------------------------------------------- #
# Registration + routing
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_the_task_is_registered_under_its_pinned_name() -> None:
    from workers.celery_app import celery_app

    assert "_test_contract_ok" in celery_app.tasks


@pytest.mark.unit
def test_the_task_carries_its_duration_class_and_that_class_time_limits() -> None:
    assert TASK_QUEUES["_test_contract_ok"] == JobQueue.LONG.value
    assert _ok_job.queue == JobQueue.LONG.value
    assert _ok_job.time_limit == TIME_LIMITS[JobQueue.LONG]
    assert _ok_job.soft_time_limit == SOFT_TIME_LIMITS[JobQueue.LONG]

    assert _bare_job.time_limit == TIME_LIMITS[JobQueue.INTERACTIVE]
    assert _bare_job.soft_time_limit == SOFT_TIME_LIMITS[JobQueue.INTERACTIVE]


# --------------------------------------------------------------------------- #
# The contract, through the Celery layer
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_a_job_runs_and_records_a_terminal_state(store: FakeStore) -> None:
    result = _ok_job.run(7)
    assert result["action"] == "done"
    assert result["status"] == "completed"
    assert result["result"] == {"x": 7}
    row = store.rows[result["run_id"]]
    assert row["job_name"] == "test.ok"
    assert row["queue"] == JobQueue.LONG.value
    assert row["client_id"] == "c-1"
    assert row["scope_type"] == "test"


@pytest.mark.unit
def test_the_same_work_is_not_done_twice(store: FakeStore) -> None:
    first = _ok_job.run(7)
    second = _ok_job.run(7)
    assert first["run_id"] == second["run_id"]
    assert second["action"] == "skipped"
    assert len(store.rows) == 1


@pytest.mark.unit
def test_a_retry_disposition_becomes_a_real_celery_retry(store: FakeStore) -> None:
    """Without this the whole retry ladder is decorative: the runner would defer the
    row and no message would ever come back to pick it up."""
    with pytest.raises(Retry):
        _flaky_job.run()
    assert store.defers, "the run should also have been deferred in the ledger"


@pytest.mark.unit
def test_the_reserved_kwargs_never_reach_the_job_body(store: FakeStore) -> None:
    """A leaked `_aios_*` kwarg is a TypeError at the worker, on every single call."""
    result = _bare_job.run(
        _aios_correlation_id="corr-1",
        _aios_parent_run_id="parent-1",
        _aios_idempotency_key="explicit-key",
        real_kwarg=1,
    )
    assert result["status"] == "completed"
    assert result["detail"] == repr(["real_kwarg"])
    row = store.rows[result["run_id"]]
    assert row["correlation_id"] == "corr-1"
    assert row["parent_run_id"] == "parent-1"
    assert row["idempotency_key"] == "explicit-key", "an explicit key must override the target's"


@pytest.mark.unit
def test_a_ledger_outage_before_the_work_redelivers_rather_than_losing_it(
    store: FakeStore,
) -> None:
    """Nothing has run yet, so a redelivery is safe - and is the right answer to a
    transient database problem.

    Celery's ``Task.retry(exc=...)`` re-raises ``exc`` when the task is called
    DIRECTLY (as here) and raises ``Retry`` when it is called by a worker. Passing
    ``exc`` is deliberate: when the ten retries are exhausted in a real worker, the
    underlying database error surfaces instead of an opaque ``MaxRetriesExceeded``.
    So this asserts the pair - one of the two, never a silent success.
    """
    store.claim_raises = True
    with pytest.raises((Retry, RuntimeError)):
        _ok_job.run(99)
    assert store.rows == {}, "no run row may exist when the claim itself failed"


# --------------------------------------------------------------------------- #
# Fan-out
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_a_child_inherits_the_correlation_id_and_a_derived_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fan-out that does not carry the correlation id cannot be reassembled later,
    which is the difference between 'what did that sweep do' being one indexed query
    and being a timestamp-range guess."""
    sent: list[dict[str, Any]] = []

    def fake_enqueue(task_name: str, *args: Any, **kwargs: Any) -> str:
        sent.append({"task": task_name, "args": args, **kwargs})
        return "msg-1"

    monkeypatch.setattr(celery_task, "enqueue", fake_enqueue)

    ctx = JobContext(
        run_id="run-1",
        correlation_id="corr-1",
        job_name="sweep",
        task="sweep",
        queue=JobQueue.STANDARD,
        attempt=1,
        max_attempts=1,
        idempotency_key="sweep:2026-08-23",
    )
    enqueue_child(ctx, "child_task", "client-7", key_suffix="client-7")

    assert sent[0]["task"] == "child_task"
    assert sent[0]["correlation_id"] == "corr-1"
    assert sent[0]["parent_run_id"] == "run-1"
    assert sent[0]["idempotency_key"] == "sweep:2026-08-23:client-7"
