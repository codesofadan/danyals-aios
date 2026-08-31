"""A queued job is a ROW, not the absence of one.

THE DEFECT THIS PINS. ``job_runs`` rows used to be created by the runner's CLAIM,
which happens at the WORKER. So between accepting a job and a worker picking it up
there was no ledger row at all, and every caller had to infer "queued" from a missing
row. ``GET /replica/{job_id}`` did exactly that::

    row = repo.get_run_by_celery_task_id(job_id, job_name=_JOB_NAME)
    if row is None:
        return ReplicaJobResponse(job_id=job_id, status="queued")

Read that against a deployment whose worker consumed only the default queue - which
is what app.qanry.com was running - and it says "queued", with every field null,
forever, for a job no process would ever consume. The two states that matter most to
tell apart, "waiting its turn" and "nothing is listening", were byte-identical in the
API and absent from ``GET /jobs/runs`` entirely. `job_runs` on the live database had
never held a single row.

So the row is now written at SEND time and the worker ADOPTS it. The tests below are
about the three ways that can go wrong: the row not being written, the row being
written TWICE (once by the enqueue and again by the worker), and a ledger outage
turning a working enqueue into a failed request.
"""

from __future__ import annotations

from typing import Any

import pytest

import app.jobs.celery_task as celery_task
from app.jobs import JobOutcome, JobQueue, JobTarget
from app.jobs.celery_task import TASK_SPECS, aios_job, enqueue
from app.jobs.contract import JobContext
from app.jobs.status import JobStatus
from tests.test_job_contract import FakeStore

pytestmark = pytest.mark.unit


# Registered at import: Celery's registry is process-global.
@aios_job(
    name="_test_enqueue_keyed",
    job_name="test.enqueue.keyed",
    queue=JobQueue.LONG,
    scope_type="client",
    target=lambda client_id: JobTarget(
        idempotency_key=f"test.enqueue:{client_id}",
        client_id=client_id,
        client_name="Acme",
        scope_id=client_id,
    ),
)
def _keyed_job(ctx: JobContext, client_id: str) -> JobOutcome:
    return JobOutcome.completed(f"ran for {client_id}")


@aios_job(
    name="_test_enqueue_unkeyed",
    job_name="test.enqueue.unkeyed",
    queue=JobQueue.STANDARD,
)
def _unkeyed_job(ctx: JobContext) -> JobOutcome:
    return JobOutcome.completed("swept")


class _SentMessage:
    def __init__(self, task_id: str) -> None:
        self.id = task_id


class _Sends:
    """Captures what would have gone to the broker."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, task_name: str, **kw: Any) -> _SentMessage:
        task_id = str(kw.get("task_id") or "generated-by-celery")
        self.calls.append({"task": task_name, **kw})
        return _SentMessage(task_id)


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr(celery_task, "job_runs_store", lambda: fake)
    return fake


@pytest.fixture
def sends(monkeypatch: pytest.MonkeyPatch) -> _Sends:
    from workers.celery_app import celery_app

    captured = _Sends()
    monkeypatch.setattr(celery_app, "send_task", captured)
    return captured


# --------------------------------------------------------------------------- #
# The row exists before any worker does
# --------------------------------------------------------------------------- #
def test_enqueue_writes_a_queued_row_with_no_worker_running(
    store: FakeStore, sends: _Sends
) -> None:
    """The whole point. Nothing consumes the queue in this test - the row is there
    anyway, which is what lets the dashboard say "queued" truthfully."""
    enqueue("_test_enqueue_keyed", "client-7")

    assert len(store.rows) == 1
    row = next(iter(store.rows.values()))
    assert row["status"] == JobStatus.QUEUED.value
    assert row["job_name"] == "test.enqueue.keyed"
    assert row["task"] == "_test_enqueue_keyed"
    assert row["queue"] == JobQueue.LONG.value
    assert row["idempotency_key"] == "test.enqueue:client-7"
    assert row["client_id"] == "client-7"
    assert row["client_name"] == "Acme"
    assert row["scope_id"] == "client-7"
    assert row["attempt"] == 0
    assert row["started_at"] is None


def test_the_row_carries_the_handle_the_caller_is_given(store: FakeStore, sends: _Sends) -> None:
    """``GET /replica/{job_id}`` looks the run up BY CELERY TASK ID. If the row were
    written with a different id than the caller holds, the lookup would miss and the
    route would fall straight back to synthesising "queued" - the defect intact,
    behind a row that exists but cannot be found."""
    returned = enqueue("_test_enqueue_keyed", "client-7")

    row = next(iter(store.rows.values()))
    assert row["celery_task_id"] == returned
    assert sends.calls[0]["task_id"] == returned


def test_a_second_enqueue_of_the_same_work_does_not_make_a_second_row(
    store: FakeStore, sends: _Sends
) -> None:
    """Pre-creating must not weaken idempotency: the double-click that used to be
    resolved at the worker is now resolved at the API, by the same unique index."""
    first = enqueue("_test_enqueue_keyed", "client-7")
    second = enqueue("_test_enqueue_keyed", "client-7")

    assert len(store.rows) == 1
    # Both sends still happen - the runner skips the duplicate on arrival, which is
    # where that decision has always been made.
    assert len(sends.calls) == 2
    assert first != second


# --------------------------------------------------------------------------- #
# Un-keyed jobs
# --------------------------------------------------------------------------- #
def test_an_unkeyed_job_gets_a_synthesised_key_the_worker_will_agree_on(
    store: FakeStore, sends: _Sends
) -> None:
    """A NULL idempotency key does not conflict, so the worker's own claim would
    INSERT A SECOND ROW instead of adopting this one - a job that shows up twice in
    Operations, once queued forever and once actually running. The synthesised key is
    unique per send (so "no key" still means "always runs") and travels in the payload
    as the override the task wrapper already knows how to apply."""
    enqueue("_test_enqueue_unkeyed")

    row = next(iter(store.rows.values()))
    key = row["idempotency_key"]
    assert key is not None and key.startswith("enq:")
    assert sends.calls[0]["kwargs"]["_aios_idempotency_key"] == key


def test_two_unkeyed_enqueues_are_two_separate_units_of_work(
    store: FakeStore, sends: _Sends
) -> None:
    """Opting out of idempotency must keep meaning what it meant."""
    enqueue("_test_enqueue_unkeyed")
    enqueue("_test_enqueue_unkeyed")

    assert len(store.rows) == 2


# --------------------------------------------------------------------------- #
# Adoption: the worker must reuse the row, not add one
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("task_name", "args"),
    [("_test_enqueue_keyed", ("client-7",)), ("_test_enqueue_unkeyed", ())],
    ids=["keyed", "unkeyed"],
)
def test_the_worker_adopts_the_queued_row_rather_than_creating_a_second(
    store: FakeStore, sends: _Sends, task_name: str, args: tuple[Any, ...]
) -> None:
    """The regression that would otherwise be invisible: every job in the system
    silently double-rowed, one of them stuck at "queued" for ever.

    This drives the REAL task body over the message the real enqueue produced, so it
    exercises the actual claim/start path rather than a re-description of it.
    """
    from workers.celery_app import celery_app

    enqueue(task_name, *args)
    sent = sends.calls[0]

    task = celery_app.tasks[task_name]
    task.apply(args=sent["args"], kwargs=sent["kwargs"], task_id=sent["task_id"]).get()

    assert len(store.rows) == 1, "the worker created a second row instead of adopting"
    row = next(iter(store.rows.values()))
    assert row["status"] == JobStatus.COMPLETED.value
    assert row["attempt"] == 1
    assert row["started_at"] is not None


# --------------------------------------------------------------------------- #
# Failure modes
# --------------------------------------------------------------------------- #
def test_a_legacy_task_is_sent_exactly_as_before(store: FakeStore, sends: _Sends) -> None:
    """~38 tasks predate the contract. They have no spec to build a row from, and
    must keep working untouched while they are migrated one at a time."""
    assert "ping" not in TASK_SPECS
    enqueue("ping")

    assert store.rows == {}
    assert len(sends.calls) == 1
    assert "_aios_idempotency_key" not in sends.calls[0]["kwargs"]


def test_a_ledger_outage_still_sends_the_job(store: FakeStore, sends: _Sends) -> None:
    """Enqueueing sits on the API's request path. Refusing to accept work because the
    ledger blinked is worse than briefly not being able to show it - and the worker
    still claims on arrival, so the job is not lost."""
    store.claim_raises = True

    returned = enqueue("_test_enqueue_keyed", "client-7")

    assert returned
    assert len(sends.calls) == 1
    assert store.rows == {}


def test_an_explicit_key_wins_over_the_targets_own(store: FakeStore, sends: _Sends) -> None:
    """Callers that derive a key themselves (a time-bucketed re-run, a replay) must
    still control it, and the worker must be told the same one."""
    enqueue("_test_enqueue_keyed", "client-7", idempotency_key="explicit:key:1")

    row = next(iter(store.rows.values()))
    assert row["idempotency_key"] == "explicit:key:1"
    assert sends.calls[0]["kwargs"]["_aios_idempotency_key"] == "explicit:key:1"


def test_enqueue_recognises_a_contract_task_the_caller_never_imported(
    store: FakeStore, sends: _Sends, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`TASK_SPECS` is populated at DECORATION time, so a process only knows a task is
    under the contract once it has imported that task's module.

    The API imports routers, not worker task modules - deliberately, so the edge does
    not drag Celery in at import time. Measured on a real API process: 2 of the ~15
    contract specs were present. So the run row was created only when the caller
    happened to have imported the module first (some routers do, via a lazy import in
    their enqueuer; others do not), which made "a queued job is a row" true by
    coincidence and silently false for every new caller.

    Simulated by hiding the spec and standing in for the module import that would
    register it - which is exactly what Celery's loader does for a real task.
    """
    import app.jobs.celery_task as ct
    from workers.celery_app import celery_app

    spec = ct.TASK_SPECS.pop("_test_enqueue_keyed")
    monkeypatch.setattr(ct, "_specs_loaded", False)

    imported: list[bool] = []

    def _fake_import() -> None:
        imported.append(True)
        ct.TASK_SPECS["_test_enqueue_keyed"] = spec

    monkeypatch.setattr(celery_app.loader, "import_default_modules", _fake_import)
    try:
        enqueue("_test_enqueue_keyed", "client-7")
    finally:
        ct.TASK_SPECS["_test_enqueue_keyed"] = spec

    assert imported, "enqueue did not try to load the task modules it had not seen"
    assert len(store.rows) == 1, "the task's module was never imported, so no row was written"
    assert next(iter(store.rows.values()))["job_name"] == "test.enqueue.keyed"


def test_a_legacy_task_is_still_legacy_after_the_modules_load(
    store: FakeStore, sends: _Sends, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Importing every task module must not accidentally make a pre-contract task
    look like a contract one - `ping` has no spec and must still write no row."""
    import app.jobs.celery_task as ct

    monkeypatch.setattr(ct, "_specs_loaded", False)
    enqueue("ping")

    assert store.rows == {}
    assert len(sends.calls) == 1
