"""The three autonomous report sweeps, now that they run under the job contract.

These entry points had no direct tests before: `test_reports.py` and
`test_scheduled_jobs.py` cover the pure cores and the operator surface, but nothing
exercised the Celery layer itself. That was survivable while the layer was four lines
of try/except; it is not now that the layer decides whether a failure is retried,
dead-lettered or lost.

What these pin:

  * a successful sweep records a `completed` run with its counts;
  * an unreachable store is RETRIED and then dead-lettered, rather than swallowed into
    a `{"state": "error"}` dict that nothing reads;
  * the sweeps are deliberately UN-KEYED, so a second run in the same period genuinely
    runs (the cores are internally idempotent; a period key would suppress the run that
    catches a client onboarded mid-period);
  * the fan-outs still use `.delay()` rather than `enqueue_child`, because their
    children are not migrated yet and would receive an unexpected reserved kwarg.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from celery.exceptions import Retry

from tests.test_job_contract import FakeStore
from workers.tasks.reports import (
    generate_monthly_reports,
    refresh_client_audits,
    sweep_offpage_monitors,
)

pytestmark = pytest.mark.unit


class FakeReportStore:
    """Enough of `ServiceReportsStore` for the three cores. Raises if `explode` is set."""

    def __init__(self, clients: list[dict[str, Any]] | None = None) -> None:
        self.clients = clients or []
        self.explode: BaseException | None = None
        self.runs: list[dict[str, Any]] = []
        self.reports: list[dict[str, Any]] = []

    def list_active_clients(self, *, limit: int) -> list[dict[str, Any]]:
        if self.explode:
            raise self.explode
        return self.clients[:limit]

    def recent_audit_exists(self, client_id: str, *, since: Any) -> bool:
        return False

    def insert_audit(self, *, client_id: str, client_name: str, url: str, tier: str) -> str:
        return f"audit-{client_id}"

    def report_exists(self, *, client_id: str, period: str, title: str) -> bool:
        return False

    def monthly_metrics(self, client_id: str) -> dict[str, Any]:
        return {"audits": 1}

    def record_run(self, **kw: Any) -> str:
        self.runs.append(kw)
        return "run-1"

    def insert_report(self, **kw: Any) -> str:
        self.reports.append(kw)
        return "report-1"


@pytest.fixture
def job_store(monkeypatch: pytest.MonkeyPatch) -> FakeStore:
    fake = FakeStore()
    monkeypatch.setattr("app.jobs.celery_task.job_runs_store", lambda: fake)
    return fake


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeReportStore:
    fake = FakeReportStore(
        [{"client_id": "c-1", "client_name": "Acme", "domain": "acme.test"}]
    )
    monkeypatch.setattr("workers.tasks.reports.service_reports_store", lambda: fake)
    return fake


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, tuple[Any, ...]]]:
    """Capture the fan-out without a broker."""
    calls: list[tuple[str, tuple[Any, ...]]] = []

    class _Task:
        def __init__(self, name: str) -> None:
            self.name = name

        def delay(self, *args: Any) -> None:
            calls.append((self.name, args))

    import workers.tasks.audit as audit_mod
    import workers.tasks.offpage as offpage_mod

    monkeypatch.setattr(audit_mod, "run_audit_job", _Task("run_audit_job"), raising=False)
    monkeypatch.setattr(
        offpage_mod, "monitor_offpage_job", _Task("monitor_offpage_job"), raising=False
    )
    return calls


_JOBS = [
    (refresh_client_audits, "reports.audit_refresh"),
    (generate_monthly_reports, "reports.monthly"),
    (sweep_offpage_monitors, "offpage.monitor_sweep"),
]


# --------------------------------------------------------------------------- #
# The happy path
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("task", "job_name"), _JOBS)
def test_a_sweep_records_a_completed_run(
    task: Any, job_name: str, store: FakeReportStore, job_store: FakeStore, sent: Any
) -> None:
    disposition = task.run()
    assert disposition["status"] == "completed"
    row = job_store.rows[disposition["run_id"]]
    assert row["job_name"] == job_name
    assert row["client_id"] is None, "a platform-wide sweep must not consume a tenant's slots"


@pytest.mark.parametrize(("task", "_job_name"), _JOBS)
def test_a_sweep_reports_what_it_actually_did(
    task: Any, _job_name: str, store: FakeReportStore, job_store: FakeStore, sent: Any
) -> None:
    """The counts reach the run row, so "what did last night do" is answerable without
    reading a worker log."""
    disposition = task.run()
    assert disposition["result"], "the run must record its counts, not just its status"
    assert disposition["detail"], "and a line a human can read"


# --------------------------------------------------------------------------- #
# The failure path - the behaviour change worth having
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("task", "_job_name"), _JOBS)
def test_an_unreachable_store_is_retried_not_swallowed(
    task: Any, _job_name: str, store: FakeReportStore, job_store: FakeStore, sent: Any
) -> None:
    """These used to return `{"state": "error"}` to a result backend that expires in an
    hour. A sweep could fail every night and look identical to a quiet night."""
    store.explode = psycopg.OperationalError("connection refused")

    with pytest.raises(Retry):
        task.run()
    assert job_store.defers, "the run should have been deferred for a retry"
    assert not job_store.dead_letters, "not dead-lettered while the attempt budget remains"


@pytest.mark.parametrize(("task", "_job_name"), _JOBS)
def test_a_bug_is_dead_lettered_immediately_rather_than_retried(
    task: Any, _job_name: str, store: FakeReportStore, job_store: FakeStore, sent: Any
) -> None:
    """The conservative default, kept intact.

    Only `psycopg.OperationalError` - the availability class - is declared transient.
    A ProgrammingError or any other exception will fail identically on every attempt,
    so burning the retry budget on it only delays an operator seeing it.
    """
    store.explode = psycopg.ProgrammingError("column does not exist")

    disposition = task.run()
    assert disposition["status"] == "failed"
    assert job_store.dead_letters, "a bug belongs in the dead-letter queue immediately"
    assert not job_store.defers, "and must not consume the retry budget"


# --------------------------------------------------------------------------- #
# The design decisions, asserted so they are not "helpfully" undone
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(("task", "_job_name"), _JOBS)
def test_the_sweeps_are_deliberately_un_keyed(
    task: Any, _job_name: str, store: FakeReportStore, job_store: FakeStore, sent: Any
) -> None:
    """A per-period key looks right and would suppress the re-run that catches a client
    onboarded mid-period. The cores are internally idempotent; that is the idempotency
    that matters here."""
    first = task.run()
    second = task.run()
    assert first["run_id"] != second["run_id"]
    assert job_store.rows[first["run_id"]]["idempotency_key"] is None


def test_the_fan_outs_do_not_send_reserved_kwargs_to_unmigrated_children(
    store: FakeReportStore, job_store: FakeStore, sent: list[tuple[str, tuple[Any, ...]]]
) -> None:
    """The trap this ordering avoids.

    `enqueue_child` propagates the correlation id by injecting a reserved
    `_aios_correlation_id` kwarg, which `@aios_job` strips before calling the body. A
    child that is NOT migrated has no such stripping and would fail at the worker with
    an unexpected keyword argument. So the fan-out stays `.delay()` with positional
    args until the children move - children before parents.
    """
    refresh_client_audits.run()
    sweep_offpage_monitors.run()

    assert sent, "the fan-out should still have enqueued its children"
    for name, args in sent:
        assert all(not str(a).startswith("_aios_") for a in args), (
            f"{name} received a reserved contract kwarg but is not migrated"
        )


def test_a_sweep_that_skipped_everything_still_says_so(
    store: FakeReportStore, job_store: FakeStore, sent: Any
) -> None:
    """A known conflation, pinned so it is not mistaken for a clean run.

    `dispatch_audit_refresh` counts two different things as `skipped`: a client
    legitimately audited recently, and a client it could NOT audit (no domain, or an
    insert that raised inside its per-client try/except). The core cannot tell them
    apart, so this job reports `completed` either way and puts the count in `detail`.

    That means a systematic failure - every client skipped - currently reads as a
    successful run that did nothing. Distinguishing the two is a change to the CORE's
    return shape, not to this wrapper, and it is recorded in KNOWN_LIMITATIONS rather
    than guessed at here. This test exists so the count is at least always visible.
    """
    store.clients = [{"client_id": "c-1", "client_name": "Acme", "domain": ""}]
    disposition = refresh_client_audits.run()
    assert disposition["status"] == "completed"
    assert disposition["result"]["skipped"] == 1
    assert "skipped 1" in disposition["detail"], "the skip count must always be visible"
