"""The job contract's proof: idempotency, retry, capping, cancellation, dead-lettering.

Every branch of ``app.jobs.runner.run_job`` is exercised here against an in-memory
store that behaves like the real one. That is the whole reason the runner is
Celery-free: these are the paths most likely to be subtly wrong (a double-spend, a
lost failure, a job that can never be stopped) and the hardest to provoke through a
broker, so they are tested as ordinary function calls with no Redis and no Postgres.

The two properties worth naming explicitly, because the rest of the platform now
depends on them:

  * A unit of work with an idempotency key that has already reached a terminal state
    is NOT executed again. That is what makes an at-least-once broker safe to spend
    money on.
  * A job's outcome is written exactly once, on every path, including the paths where
    the job body raised - and `degraded` is never recorded without a reason.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.jobs.contract import (
    JobBlocked,
    JobContext,
    JobOutcome,
    PermanentJobError,
    RetryableJobError,
    StartOutcome,
    StartResult,
)
from app.jobs.runner import (
    BLOCKED_CONCURRENCY_CAP,
    JobSpec,
    JobTarget,
    _sanitize,
    compute_backoff,
    run_job,
)
from app.jobs.status import JobQueue, JobStatus, is_success, needs_attention, terminal_for


# --------------------------------------------------------------------------- #
# A store that behaves like the real one
# --------------------------------------------------------------------------- #
class FakeStore:
    """In-memory ``JobRunStore``. Mirrors the real semantics, not just the signature.

    In particular ``claim`` resolves a duplicate key the way the partial unique index
    does (first writer wins, second gets the existing row), and ``start`` refuses to
    move anything that is not ``queued`` - which is what makes the duplicate-delivery
    tests meaningful rather than decorative.
    """

    def __init__(self) -> None:
        self.rows: dict[str, dict[str, Any]] = {}
        self.by_key: dict[str, str] = {}
        self.dead_letters: list[dict[str, Any]] = []
        self.defers: list[tuple[str, float, str]] = []
        self.heartbeats: list[str] = []
        # knobs
        self.force_start: StartOutcome | None = None
        self.in_flight = 0
        self.cancel_requested_flag = False
        self.finish_raises = False
        self.dead_letter_raises = False
        self.claim_raises = False

    # --- seam ---------------------------------------------------------------
    def claim(self, **kw: Any) -> tuple[dict[str, Any], bool]:
        if self.claim_raises:
            raise RuntimeError("database is down")
        key = kw["idempotency_key"]
        if key is not None and key in self.by_key:
            return dict(self.rows[self.by_key[key]]), False
        run_id = str(uuid.uuid4())
        row = {
            "id": run_id,
            "job_name": kw["job_name"],
            "task": kw["task"],
            "queue": kw["queue"],
            "idempotency_key": key,
            "correlation_id": kw["correlation_id"],
            "parent_run_id": kw["parent_run_id"],
            "celery_task_id": kw["celery_task_id"],
            "client_id": kw["client_id"],
            "client_name": kw["client_name"],
            "scope_type": kw["scope_type"],
            "scope_id": kw["scope_id"],
            "status": JobStatus.QUEUED.value,
            "attempt": 0,
            "max_attempts": kw["max_attempts"],
            "started_at": None,
            "finished_at": None,
            "cancel_requested_at": None,
            "detail": "",
            "reason": "",
            "reason_code": "",
            "error_type": "",
            "error_message": "",
            "cost_usd": Decimal("0"),
            "result": None,
            "created_at": datetime.now(UTC),
        }
        self.rows[run_id] = row
        if key is not None:
            self.by_key[key] = run_id
        return dict(row), True

    def start(
        self, run_id: str, *, celery_task_id: str, client_concurrency: int, max_attempts: int = 1
    ) -> StartResult:
        row = self.rows.get(run_id)
        if row is None:
            return StartResult(outcome=StartOutcome.NOT_CLAIMABLE)
        if self.force_start is not None and self.force_start is not StartOutcome.STARTED:
            return StartResult(outcome=self.force_start, row=dict(row), in_flight=self.in_flight)
        if row["cancel_requested_at"] is not None:
            return StartResult(outcome=StartOutcome.CANCELLED, row=dict(row))
        if row["status"] != JobStatus.QUEUED.value:
            return StartResult(outcome=StartOutcome.NOT_CLAIMABLE, row=dict(row))
        if row["client_id"] is not None and client_concurrency > 0 and self.in_flight >= client_concurrency:
            return StartResult(outcome=StartOutcome.CAPPED, row=dict(row), in_flight=self.in_flight)
        row["status"] = JobStatus.RUNNING.value
        row["attempt"] += 1
        row["started_at"] = row["started_at"] or datetime.now(UTC)
        row["celery_task_id"] = celery_task_id
        row["max_attempts"] = max_attempts
        return StartResult(outcome=StartOutcome.STARTED, row=dict(row))

    def heartbeat(self, run_id: str) -> None:
        self.heartbeats.append(run_id)

    def cancel_requested(self, run_id: str) -> bool:
        return self.cancel_requested_flag

    def finish(self, run_id: str, **kw: Any) -> dict[str, Any] | None:
        if self.finish_raises:
            raise RuntimeError("database is down")
        row = self.rows[run_id]
        row.update(kw)
        row["status"] = kw["status"]
        row["finished_at"] = datetime.now(UTC)
        return dict(row)

    def defer(self, run_id: str, *, scheduled_for_seconds: float, detail: str) -> None:
        self.defers.append((run_id, scheduled_for_seconds, detail))
        self.rows[run_id]["status"] = JobStatus.QUEUED.value

    def dead_letter(self, run_id: str, **kw: Any) -> str | None:
        if self.dead_letter_raises:
            raise RuntimeError("database is down")
        entry = {"run_id": run_id, **kw}
        self.dead_letters.append(entry)
        return str(uuid.uuid4())


def _spec(**over: Any) -> JobSpec:
    base: dict[str, Any] = {
        "job_name": "test.job",
        "task": "test_job",
        "queue": JobQueue.STANDARD,
        "max_attempts": 1,
        "retry_backoff": 10.0,
        "client_concurrency": 0,
        "scope_type": "test",
    }
    base.update(over)
    return JobSpec(**base)


_TARGET = JobTarget(idempotency_key="k:1", client_id="c-1", client_name="Acme", scope_id="s-1")


def _no_jitter(_: float) -> float:
    return 0.0


def _deps(now: datetime | None = None) -> Any:
    from app.jobs.runner import _RunnerDeps

    stamp = now or datetime.now(UTC)
    return _RunnerDeps(now=lambda: stamp, jitter=_no_jitter)


# --------------------------------------------------------------------------- #
# The vocabulary
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_only_completed_counts_as_success() -> None:
    """The single rule the whole product's honesty rests on."""
    assert is_success(JobStatus.COMPLETED)
    for status in (JobStatus.DEGRADED, JobStatus.BLOCKED, JobStatus.FAILED, JobStatus.CANCELLED):
        assert not is_success(status), f"{status} must never render as success"


@pytest.mark.unit
def test_degraded_blocked_and_failed_all_need_attention() -> None:
    assert needs_attention(JobStatus.DEGRADED)
    assert needs_attention(JobStatus.BLOCKED)
    assert needs_attention(JobStatus.FAILED)
    assert not needs_attention(JobStatus.COMPLETED)
    assert not needs_attention(JobStatus.CANCELLED)


@pytest.mark.unit
def test_a_partial_outcome_cannot_be_recorded_without_saying_what_failed() -> None:
    with pytest.raises(ValueError, match="requires a reason"):
        JobOutcome.degraded("some_code", "")
    with pytest.raises(ValueError, match="requires a reason"):
        JobOutcome.blocked("some_code", "   ")
    with pytest.raises(ValueError, match="requires an error_type"):
        JobOutcome(status=JobStatus.FAILED)


@pytest.mark.unit
def test_a_blocked_refusal_cannot_be_raised_without_a_reason() -> None:
    with pytest.raises(ValueError, match="cannot say why"):
        JobBlocked("some_code", "")


@pytest.mark.unit
def test_an_outcome_must_be_terminal() -> None:
    with pytest.raises(ValueError, match="must be terminal"):
        JobOutcome(status=JobStatus.RUNNING)


@pytest.mark.unit
def test_the_citation_submitted_state_maps_to_degraded_not_completed() -> None:
    """A listing that has been SENT is not a listing that is LIVE.

    This mapping is the difference between a citation count that is true and one
    that flatters the agency.
    """
    assert terminal_for("citation_submit_status", "submitted") is JobStatus.DEGRADED
    assert terminal_for("citation_submit_status", "verified") is JobStatus.COMPLETED
    # A non-terminal lifecycle word has no canonical equivalent, by design.
    assert terminal_for("content_status", "needs_review") is None


# --------------------------------------------------------------------------- #
# Idempotency
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_work_already_completed_under_the_same_key_is_not_done_again() -> None:
    store = FakeStore()
    calls: list[int] = []

    def job(ctx: JobContext) -> JobOutcome:
        calls.append(1)
        return JobOutcome.completed("did the thing", cost_usd=Decimal("1.50"))

    first = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert first.action == "done"
    assert first.status == JobStatus.COMPLETED.value

    second = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert second.action == "skipped"
    assert second.status == JobStatus.COMPLETED.value
    assert "already completed" in second.detail
    assert calls == [1], "the body ran twice under one idempotency key - this is the double-spend"


@pytest.mark.unit
def test_a_duplicate_delivery_while_another_worker_runs_it_is_dropped() -> None:
    store = FakeStore()
    row, _ = store.claim(
        job_name="test.job",
        task="test_job",
        queue="standard",
        idempotency_key="k:1",
        correlation_id=str(uuid.uuid4()),
        parent_run_id=None,
        celery_task_id="worker-A",
        client_id="c-1",
        client_name="Acme",
        scope_type="test",
        scope_id="s-1",
        max_attempts=1,
    )
    store.rows[row["id"]]["status"] = JobStatus.RUNNING.value
    store.rows[row["id"]]["celery_task_id"] = "worker-A"

    ran: list[int] = []

    def job(ctx: JobContext) -> JobOutcome:
        ran.append(1)
        return JobOutcome.completed()

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, celery_task_id="worker-B", deps=_deps())
    assert disp.action == "skipped"
    assert "another worker" in disp.detail
    assert ran == []


@pytest.mark.unit
def test_a_job_with_no_key_always_runs() -> None:
    """Opting out of idempotency is legal - and is what a platform-wide sweep wants."""
    store = FakeStore()
    calls: list[int] = []

    def job(ctx: JobContext) -> JobOutcome:
        calls.append(1)
        return JobOutcome.completed()

    for _ in range(3):
        run_job(job, spec=_spec(), store=store, target=JobTarget(), deps=_deps())
    assert calls == [1, 1, 1]


# --------------------------------------------------------------------------- #
# Terminal states
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_a_completed_run_records_its_cost_and_result() -> None:
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        return JobOutcome.completed("10 pages live", cost_usd=Decimal("2.25"), result={"pages": 10})

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    row = store.rows[disp.run_id or ""]
    assert row["status"] == JobStatus.COMPLETED.value
    assert row["cost_usd"] == Decimal("2.25")
    assert row["result"] == {"pages": 10}
    assert disp.result == {"pages": 10}


@pytest.mark.unit
def test_a_degraded_run_is_recorded_as_degraded_with_its_reason() -> None:
    """The defect this contract exists to kill: a partial publish reporting success."""
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        return JobOutcome.degraded(
            "wp_rest_rejected", "published 2 of 10 pages; 8 rejected by the site's REST API"
        )

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    row = store.rows[disp.run_id or ""]
    assert row["status"] == JobStatus.DEGRADED.value
    assert "2 of 10" in row["reason"]
    assert not is_success(row["status"])


@pytest.mark.unit
def test_a_gate_refusal_is_blocked_and_is_never_retried() -> None:
    store = FakeStore()
    calls: list[int] = []

    def job(ctx: JobContext) -> JobOutcome:
        calls.append(1)
        raise JobBlocked("client_cap_exhausted", "the client's monthly cost cap is exhausted")

    disp = run_job(job, spec=_spec(max_attempts=5), store=store, target=_TARGET, deps=_deps())
    assert disp.action == "done"
    assert disp.status == JobStatus.BLOCKED.value
    assert store.rows[disp.run_id or ""]["reason"].startswith("the client's monthly cost cap")
    assert store.defers == [], "a refusal must not be retried - it will just refuse again"
    assert store.dead_letters == [], "a refusal is not a failure and does not belong in the DLQ"
    assert calls == [1]


@pytest.mark.unit
def test_a_job_that_does_not_return_an_outcome_fails_permanently() -> None:
    store = FakeStore()

    def job(ctx: JobContext) -> Any:
        return "done!"

    disp = run_job(job, spec=_spec(max_attempts=3), store=store, target=_TARGET, deps=_deps())
    assert disp.status == JobStatus.FAILED.value
    assert store.rows[disp.run_id or ""]["error_type"] == "PermanentJobError"
    assert store.defers == []


# --------------------------------------------------------------------------- #
# Retry and the dead letter
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_a_transient_error_is_retried_with_backoff_while_the_budget_lasts() -> None:
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        raise RetryableJobError("provider returned 503")

    disp = run_job(job, spec=_spec(max_attempts=3), store=store, target=_TARGET, deps=_deps())
    assert disp.action == "retry"
    assert disp.countdown == 10.0  # base * 2**0, no jitter
    assert store.defers and store.defers[0][1] == 10.0
    assert store.dead_letters == [], "a retryable failure with budget left must not be dead-lettered"
    assert store.rows[disp.run_id or ""]["finished_at"] is None


@pytest.mark.unit
def test_the_retry_budget_is_bounded_and_then_dead_lettered() -> None:
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        raise RetryableJobError("provider returned 503")

    spec = _spec(max_attempts=2)
    first = run_job(job, spec=spec, store=store, target=_TARGET, deps=_deps())
    assert first.action == "retry"

    second = run_job(job, spec=spec, store=store, target=_TARGET, deps=_deps())
    assert second.action == "done"
    assert second.status == JobStatus.FAILED.value
    assert len(store.dead_letters) == 1
    assert store.dead_letters[0]["error_type"] == "RetryableJobError"
    row = store.rows[second.run_id or ""]
    assert row["attempt"] == 2
    assert row["error_type"] == "RetryableJobError"


@pytest.mark.unit
def test_a_permanent_error_burns_no_retries() -> None:
    """Three attempts at a 400 is three times the delay before anyone sees the problem."""
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        raise PermanentJobError("the site has no REST API and never will")

    disp = run_job(job, spec=_spec(max_attempts=5), store=store, target=_TARGET, deps=_deps())
    assert disp.action == "done"
    assert disp.status == JobStatus.FAILED.value
    assert store.defers == []
    assert len(store.dead_letters) == 1


@pytest.mark.unit
def test_an_unclassified_exception_is_treated_as_permanent() -> None:
    """The conservative default: code nobody has reasoned about is not re-run against
    a paid provider."""
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        raise ValueError("something nobody anticipated")

    disp = run_job(job, spec=_spec(max_attempts=5), store=store, target=_TARGET, deps=_deps())
    assert disp.status == JobStatus.FAILED.value
    assert store.defers == []
    assert store.dead_letters[0]["error_type"] == "ValueError"


@pytest.mark.unit
def test_a_declared_transient_type_is_retried() -> None:
    store = FakeStore()

    class ProviderTimeoutError(Exception):
        pass

    def job(ctx: JobContext) -> JobOutcome:
        raise ProviderTimeoutError("read timed out")

    disp = run_job(
        job,
        spec=_spec(max_attempts=3, retry_on=(ProviderTimeoutError,)),
        store=store,
        target=_TARGET,
        deps=_deps(),
    )
    assert disp.action == "retry"


@pytest.mark.unit
def test_retry_after_overrides_the_computed_backoff() -> None:
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        raise RetryableJobError("rate limited", retry_after=42.0)

    disp = run_job(job, spec=_spec(max_attempts=3), store=store, target=_TARGET, deps=_deps())
    assert disp.countdown == 42.0


@pytest.mark.unit
def test_the_dead_letter_carries_the_payload_needed_to_replay() -> None:
    store = FakeStore()

    def job(ctx: JobContext, client_id: str, *, pages: int) -> JobOutcome:
        raise PermanentJobError("nope")

    run_job(
        job,
        spec=_spec(),
        store=store,
        target=_TARGET,
        args=("c-1",),
        kwargs={"pages": 10},
        deps=_deps(),
    )
    payload = store.dead_letters[0]["payload"]
    assert payload == {"args": ["c-1"], "kwargs": {"pages": 10}}
    assert store.dead_letters[0]["traceback"]


@pytest.mark.unit
def test_backoff_is_exponential_and_capped() -> None:
    assert compute_backoff(1, base=30, maximum=600, jitter=_no_jitter) == 30
    assert compute_backoff(2, base=30, maximum=600, jitter=_no_jitter) == 60
    assert compute_backoff(3, base=30, maximum=600, jitter=_no_jitter) == 120
    assert compute_backoff(10, base=30, maximum=600, jitter=_no_jitter) == 600


# --------------------------------------------------------------------------- #
# Cancellation
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_a_run_cancelled_before_it_starts_never_runs() -> None:
    store = FakeStore()
    store.force_start = StartOutcome.CANCELLED
    ran: list[int] = []

    def job(ctx: JobContext) -> JobOutcome:
        ran.append(1)
        return JobOutcome.completed()

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert disp.status == JobStatus.CANCELLED.value
    assert ran == []


@pytest.mark.unit
def test_a_running_job_stops_at_its_next_checkpoint() -> None:
    """Cancellation is cooperative: a job that never checks can never be stopped,
    which is why anything that loops must call checkpoint()."""
    store = FakeStore()
    store.cancel_requested_flag = True
    done: list[int] = []

    def job(ctx: JobContext) -> JobOutcome:
        for i in range(10):
            ctx.checkpoint()
            done.append(i)
        return JobOutcome.completed()

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert disp.status == JobStatus.CANCELLED.value
    assert done == [], "the first checkpoint should have stopped it"
    assert store.dead_letters == [], "a cancellation is not a failure"


@pytest.mark.unit
def test_cancellation_polling_is_throttled_and_latches() -> None:
    ticks = iter([0.0, 1.0, 2.0, 100.0])
    store = FakeStore()
    ctx = JobContext(
        run_id="r",
        correlation_id="c",
        job_name="j",
        task="t",
        queue=JobQueue.STANDARD,
        attempt=1,
        max_attempts=1,
        _store=store,
        _clock=lambda: next(ticks),
        _cancel_poll_every=10.0,
    )
    assert ctx.cancelled() is False  # first poll at t=0
    assert ctx.cancelled() is False  # t=1, throttled - no store hit
    store.cancel_requested_flag = True
    assert ctx.cancelled() is False  # t=2, still throttled
    assert ctx.cancelled() is True  # t=100, polls and sees it
    assert ctx.cancelled() is True  # latched


@pytest.mark.unit
def test_heartbeat_is_throttled() -> None:
    ticks = iter([0.0, 5.0, 40.0])
    store = FakeStore()
    ctx = JobContext(
        run_id="r",
        correlation_id="c",
        job_name="j",
        task="t",
        queue=JobQueue.STANDARD,
        attempt=1,
        max_attempts=1,
        _store=store,
        _clock=lambda: next(ticks),
        _heartbeat_every=30.0,
    )
    ctx.heartbeat()
    ctx.heartbeat()
    ctx.heartbeat()
    assert len(store.heartbeats) == 2, "the middle beat was inside the throttle window"


# --------------------------------------------------------------------------- #
# The per-client concurrency cap
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_a_capped_run_waits_rather_than_starting() -> None:
    store = FakeStore()
    store.force_start = StartOutcome.CAPPED
    store.in_flight = 4
    ran: list[int] = []

    def job(ctx: JobContext) -> JobOutcome:
        ran.append(1)
        return JobOutcome.completed()

    disp = run_job(
        job,
        spec=_spec(client_concurrency=4, max_queue_seconds=3600),
        store=store,
        target=_TARGET,
        deps=_deps(),
    )
    assert disp.action == "retry"
    assert ran == []
    assert store.defers, "a capped run must be put back with a due time"
    assert "in flight" in disp.detail


@pytest.mark.unit
def test_a_run_that_waits_too_long_for_a_slot_is_blocked_not_deferred_forever() -> None:
    """An hour of silent waiting is indistinguishable from a lost job, so the wait is
    bounded and ends in an explained refusal."""
    store = FakeStore()
    store.force_start = StartOutcome.CAPPED
    store.in_flight = 4

    def job(ctx: JobContext) -> JobOutcome:
        return JobOutcome.completed()

    # First call creates the row (created_at = now); then look at it two hours later.
    spec = _spec(client_concurrency=4, max_queue_seconds=3600)
    run_job(job, spec=spec, store=store, target=_TARGET, deps=_deps())
    later = datetime.now(UTC) + timedelta(hours=2)
    disp = run_job(job, spec=spec, store=store, target=_TARGET, deps=_deps(now=later))

    assert disp.action == "done"
    assert disp.status == JobStatus.BLOCKED.value
    assert "4-job limit" in disp.detail
    row = store.rows[disp.run_id or ""]
    assert row["reason"], "a blocked run must always carry its reason"


@pytest.mark.unit
def test_a_deferral_does_not_consume_the_retry_budget() -> None:
    """Being held off by a cap is not an attempt. Conflating the two lets a busy
    client's jobs exhaust their retries without ever running."""
    store = FakeStore()
    store.force_start = StartOutcome.CAPPED
    store.in_flight = 1

    def job(ctx: JobContext) -> JobOutcome:
        return JobOutcome.completed()

    spec = _spec(client_concurrency=1, max_attempts=2)
    for _ in range(5):
        run_job(job, spec=spec, store=store, target=_TARGET, deps=_deps())
    run_id = store.by_key["k:1"]
    assert store.rows[run_id]["attempt"] == 0


# --------------------------------------------------------------------------- #
# Failure of the ledger itself
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_a_failed_ledger_write_after_the_work_never_causes_a_re_run() -> None:
    """The one place where losing the record beats retrying: the pages are already
    published and the provider is already billed."""
    store = FakeStore()
    store.finish_raises = True

    def job(ctx: JobContext) -> JobOutcome:
        return JobOutcome.completed("published 10 pages")

    disp = run_job(job, spec=_spec(max_attempts=3), store=store, target=_TARGET, deps=_deps())
    assert disp.action == "done", "a ledger outage must never redeliver work that already ran"
    assert store.defers == []


@pytest.mark.unit
def test_a_failed_dead_letter_write_does_not_mask_the_failure() -> None:
    store = FakeStore()
    store.dead_letter_raises = True

    def job(ctx: JobContext) -> JobOutcome:
        raise PermanentJobError("boom")

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert disp.status == JobStatus.FAILED.value


@pytest.mark.unit
def test_a_claim_failure_propagates_so_the_caller_can_redeliver() -> None:
    """Nothing has run yet, so redelivering IS the right answer - which is why this
    one is allowed out of the runner."""
    store = FakeStore()
    store.claim_raises = True

    def job(ctx: JobContext) -> JobOutcome:
        return JobOutcome.completed()

    with pytest.raises(RuntimeError):
        run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())


# --------------------------------------------------------------------------- #
# Correlation + secret hygiene
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_the_correlation_id_is_carried_onto_the_disposition() -> None:
    store = FakeStore()
    correlation = str(uuid.uuid4())

    def job(ctx: JobContext) -> JobOutcome:
        assert ctx.correlation_id == correlation
        return JobOutcome.completed()

    disp = run_job(
        job, spec=_spec(), store=store, target=_TARGET, correlation_id=correlation, deps=_deps()
    )
    assert disp.correlation_id == correlation


@pytest.mark.unit
def test_a_child_key_is_derived_from_the_parent_and_only_when_there_is_one() -> None:
    ctx = JobContext(
        run_id="r",
        correlation_id="c",
        job_name="j",
        task="t",
        queue=JobQueue.STANDARD,
        attempt=1,
        max_attempts=1,
        idempotency_key="sweep:2026-08-23",
    )
    assert ctx.child_key("client-7") == "sweep:2026-08-23:client-7"
    unkeyed = JobContext(
        run_id="r",
        correlation_id="c",
        job_name="j",
        task="t",
        queue=JobQueue.STANDARD,
        attempt=1,
        max_attempts=1,
    )
    assert unkeyed.child_key("client-7") is None


@pytest.mark.unit
def test_an_error_message_never_carries_a_credential() -> None:
    """Exception text is the classic leak path, and these columns are staff-readable."""
    dirty = (
        "connection failed: postgresql://aios:hunter2@10.0.0.4:5432/aios "
        "and api_key=sk-live-abcdef123456 was rejected"
    )
    clean = _sanitize(dirty)
    assert "hunter2" not in clean
    assert "sk-live-abcdef123456" not in clean
    assert "[redacted]" in clean


@pytest.mark.unit
def test_a_failed_run_stores_a_sanitized_error_message() -> None:
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        raise PermanentJobError("could not reach postgresql://aios:hunter2@db:5432/aios")

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert "hunter2" not in store.rows[disp.run_id or ""]["error_message"]
    assert "hunter2" not in store.dead_letters[0]["error_message"]


# --------------------------------------------------------------------------- #
# The machine-readable half of a refusal
# --------------------------------------------------------------------------- #
@pytest.mark.unit
def test_a_partial_outcome_needs_a_code_as_well_as_prose() -> None:
    """Prose alone is un-countable.

    Every call site phrases "no WordPress credentials" differently, so with only a
    sentence the sole way to ask how often that block happens is to grep free text -
    which is how a recurring, fixable refusal stays invisible for months.
    """
    with pytest.raises(ValueError, match="lower snake_case"):
        JobOutcome.degraded("", "published 2 of 10 pages")
    with pytest.raises(ValueError, match="lower snake_case"):
        JobOutcome.blocked("", "the cost cap is exhausted")


@pytest.mark.unit
@pytest.mark.parametrize(
    "bad",
    [
        "No WordPress credentials",  # a sentence
        "wpCredentialsMissing",  # camelCase
        "wp-credentials-missing",  # kebab
        "WP_CREDENTIALS",  # shouting
        "ab",  # too short to mean anything
        "9lives",  # must start with a letter
        "x" * 65,  # too long
    ],
)
def test_a_reason_code_must_be_a_stable_identifier_not_a_sentence(bad: str) -> None:
    with pytest.raises(ValueError, match="lower snake_case"):
        JobOutcome.blocked(bad, "some reason")


@pytest.mark.unit
def test_a_valid_reason_code_is_carried_to_the_ledger() -> None:
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        return JobOutcome.degraded("wp_rest_rejected", "published 2 of 10 pages")

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    row = store.rows[disp.run_id or ""]
    assert row["reason_code"] == "wp_rest_rejected"
    assert row["reason"] == "published 2 of 10 pages"


@pytest.mark.unit
def test_a_raised_block_carries_its_code_through() -> None:
    store = FakeStore()

    def job(ctx: JobContext) -> JobOutcome:
        raise JobBlocked("client_cap_exhausted", "the client's monthly cost cap is exhausted")

    disp = run_job(job, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert store.rows[disp.run_id or ""]["reason_code"] == "client_cap_exhausted"


@pytest.mark.unit
def test_the_runners_own_blocks_carry_named_codes() -> None:
    """The two refusals that come from the contract rather than from a job's logic
    are named constants, so an operator can filter on them without a magic string."""
    store = FakeStore()
    store.force_start = StartOutcome.CAPPED
    store.in_flight = 4

    def job(ctx: JobContext) -> JobOutcome:
        return JobOutcome.completed()

    spec = _spec(client_concurrency=4, max_queue_seconds=3600)
    run_job(job, spec=spec, store=store, target=_TARGET, deps=_deps())
    later = datetime.now(UTC) + timedelta(hours=2)
    disp = run_job(job, spec=spec, store=store, target=_TARGET, deps=_deps(now=later))
    assert store.rows[disp.run_id or ""]["reason_code"] == BLOCKED_CONCURRENCY_CAP


@pytest.mark.unit
def test_the_dead_letter_distinguishes_an_exhausted_retry_from_a_permanent_error() -> None:
    """Different problems with different fixes, so the queue can be grouped by which."""
    store = FakeStore()

    def permanent(ctx: JobContext) -> JobOutcome:
        raise PermanentJobError("the site has no REST API")

    def transient(ctx: JobContext) -> JobOutcome:
        raise RetryableJobError("provider 503")

    run_job(permanent, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert store.dead_letters[0]["reason_code"] == "permanent_error"

    other = JobTarget(idempotency_key="k:2", client_id="c-1")
    spec = _spec(max_attempts=1)
    run_job(transient, spec=spec, store=store, target=other, deps=_deps())
    assert store.dead_letters[1]["reason_code"] == "retries_exhausted"


@pytest.mark.unit
def test_the_python_validator_matches_the_database_constraint() -> None:
    """Two copies of one rule. If they drift, a code the Python layer accepts becomes
    a constraint violation at the moment a job is recording why it refused to spend."""
    from pathlib import Path

    sql = (
        Path(__file__).resolve().parents[2] / "db" / "migrations" / "0080_job_contract.sql"
    ).read_text(encoding="utf-8")
    assert "reason_code ~ '^[a-z][a-z0-9_]{2,63}$'" in sql, (
        "the DB check constraint's pattern must match app.jobs.contract._REASON_CODE_RE"
    )
    assert "job_runs_reason_code_required_ck" in sql


@pytest.mark.unit
def test_a_returned_failure_is_dead_lettered_like_a_raised_one() -> None:
    """Failing politely must not make a job LESS visible than failing loudly.

    A job can fail by raising, or by returning `JobOutcome.failed(...)` because it knows
    exactly what went wrong. Both are the same thing to an operator - work the platform
    accepted and did not deliver - so both belong in the dead-letter queue. Found while
    migrating `compact_context`, whose core never raises and reports its own errors.
    """
    store = FakeStore()

    def polite(ctx: JobContext) -> JobOutcome:
        return JobOutcome.failed("CompactionError", "the fold could not be applied")

    disp = run_job(polite, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert disp.status == JobStatus.FAILED.value
    assert store.dead_letters, "a returned failure must be replayable, exactly like a raised one"
    assert store.dead_letters[0]["error_type"] == "CompactionError"


@pytest.mark.unit
def test_a_degraded_outcome_is_not_dead_lettered() -> None:
    """The boundary of the rule above. A degraded run DID deliver something and is not
    lost work - dead-lettering it would invite a replay that redoes what already
    succeeded."""
    store = FakeStore()

    def partial(ctx: JobContext) -> JobOutcome:
        return JobOutcome.degraded("wp_rest_rejected", "published 2 of 10 pages")

    run_job(partial, spec=_spec(), store=store, target=_TARGET, deps=_deps())
    assert not store.dead_letters
