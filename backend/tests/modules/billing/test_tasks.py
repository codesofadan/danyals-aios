"""Billing worker: the never-re-raise / idempotent contract of the past-due sweep.

NO DB, NO network, NO broker: the store is in-memory and the Celery task is invoked as
a plain function - ``.delay`` is never called, so no broker is needed.

Two properties are pinned:

1. **Never re-raise.** ``task_acks_late=True`` means a raised exception REDELIVERS the
   job. This task moves invoice STATUS, so a redelivery storm against a flapping DB
   must not become an infinite retry loop - every failure comes back as a result dict.
2. **Idempotent, and only ``open`` is touched.** The flip is keyed on
   ``status = 'open'``, so a re-run finds nothing left to flip and can never drag a
   paid/void invoice back to past_due.

There is no cost-gate test here (unlike the keyword worker): this module calls no paid
provider - there is no payment gateway in v1 and nothing external to spend money on.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.billing.tasks import execute_mark_past_due, mark_past_due

pytestmark = pytest.mark.unit


class FakeBillingStore:
    """In-memory stand-in for the privileged ServiceBillingStore.

    ``invoices`` mirrors the real predicate's inputs (status + due_date), so "did the
    sweep touch something it shouldn't?" is answerable by inspecting the dict.
    """

    def __init__(self, invoices: list[dict[str, Any]] | None = None) -> None:
        self.invoices = invoices if invoices is not None else []
        self.calls: list[int] = []
        self.explode: BaseException | None = None

    def flip_overdue_open_invoices(self, *, grace_days: int = 0) -> int:
        self.calls.append(grace_days)
        if self.explode is not None:
            raise self.explode
        flipped = 0
        for invoice in self.invoices:
            # The real SQL predicate, in Python: only OPEN + overdue rows move.
            if invoice["status"] == "open" and invoice["days_overdue"] > grace_days:
                invoice["status"] = "past_due"
                flipped += 1
        return flipped


def _settings(grace_days: int = 0) -> Settings:
    """Deterministic settings, independent of the developer's shell env (``_env_file``
    is pinned off, mirroring ``tests/conftest._dev_settings``)."""
    return Settings(_env_file=None, app_env="dev", billing_past_due_grace_days=grace_days)


# --------------------------------------------------------------------------- #
# 1. The happy path.
# --------------------------------------------------------------------------- #
def test_the_sweep_flips_overdue_open_invoices() -> None:
    store = FakeBillingStore([
        {"id": "a", "status": "open", "days_overdue": 3},
        {"id": "b", "status": "open", "days_overdue": 1},
    ])
    assert execute_mark_past_due(store, _settings()) == {"state": "ok", "flipped": 2}
    assert [i["status"] for i in store.invoices] == ["past_due", "past_due"]


def test_the_sweep_leaves_a_not_yet_due_invoice_alone() -> None:
    store = FakeBillingStore([{"id": "a", "status": "open", "days_overdue": 0}])
    assert execute_mark_past_due(store, _settings())["flipped"] == 0
    assert store.invoices[0]["status"] == "open"


def test_an_empty_ledger_is_a_clean_no_op() -> None:
    assert execute_mark_past_due(FakeBillingStore([]), _settings()) == {
        "state": "ok", "flipped": 0
    }


# --------------------------------------------------------------------------- #
# 2. ONLY `open` is touched.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", ["draft", "paid", "past_due", "void", "refunded"])
def test_the_sweep_never_touches_a_non_open_invoice(status: str) -> None:
    """The predicate is ``status = 'open'`` and nothing else.

    Each of these would be a real incident if it flipped: a paid invoice dragged back
    to past_due would show the client as delinquent for money they already sent; a
    voided or refunded one is TERMINAL and 0043's trigger would reject the write
    outright (an exception in a beat task, every night, forever).
    """
    store = FakeBillingStore([{"id": "a", "status": status, "days_overdue": 99}])
    result = execute_mark_past_due(store, _settings())
    assert result == {"state": "ok", "flipped": 0}
    assert store.invoices[0]["status"] == status  # untouched


def test_the_sweep_flips_only_the_open_rows_in_a_mixed_ledger() -> None:
    store = FakeBillingStore([
        {"id": "draft", "status": "draft", "days_overdue": 99},
        {"id": "open", "status": "open", "days_overdue": 5},
        {"id": "paid", "status": "paid", "days_overdue": 99},
        {"id": "void", "status": "void", "days_overdue": 99},
    ])
    assert execute_mark_past_due(store, _settings())["flipped"] == 1
    assert [i["status"] for i in store.invoices] == ["draft", "past_due", "paid", "void"]


# --------------------------------------------------------------------------- #
# 3. Idempotency: a redelivery is a no-op.
# --------------------------------------------------------------------------- #
def test_a_second_run_flips_nothing_more() -> None:
    """acks_late + a raised exception = a redelivered job. The sweep must therefore be
    safe to run twice: the first run flips, the second finds no `open` rows left."""
    store = FakeBillingStore([{"id": "a", "status": "open", "days_overdue": 3}])
    first = execute_mark_past_due(store, _settings())
    second = execute_mark_past_due(store, _settings())
    assert first["flipped"] == 1
    assert second["flipped"] == 0  # the re-run is a no-op, not a double-transition
    assert store.invoices[0]["status"] == "past_due"


def test_the_grace_window_comes_from_settings() -> None:
    store = FakeBillingStore([{"id": "a", "status": "open", "days_overdue": 2}])
    # A 3-day grace buys the invoice more time...
    assert execute_mark_past_due(store, _settings(grace_days=3))["flipped"] == 0
    assert store.calls == [3]
    # ... and a 0-day grace flips it the morning after it is due.
    assert execute_mark_past_due(store, _settings(grace_days=0))["flipped"] == 1
    assert store.calls == [3, 0]


# --------------------------------------------------------------------------- #
# 4. Never re-raise.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "boom",
    [RuntimeError("db is down"), ValueError("bad state"), OSError("connection refused")],
)
def test_the_pure_core_never_re_raises(boom: BaseException) -> None:
    """A DB failure must come back as an ``error`` result, not an exception.

    With acks_late, raising here redelivers the job - and a persistently unreachable
    database would turn a nightly sweep into an endless redelivery loop.
    """
    store = FakeBillingStore()
    store.explode = boom
    assert execute_mark_past_due(store, _settings()) == {"state": "error", "flipped": 0}


# The entry point now runs under the JOB CONTRACT (@aios_job), which replaces the old
# "never re-raise, return an error dict" template. The guarantee is strictly stronger:
# a transient failure is RETRIED with backoff and then DEAD-LETTERED, instead of being
# returned to a result backend that expires in an hour and telling nobody.
@pytest.fixture
def job_store(monkeypatch: pytest.MonkeyPatch) -> Any:
    from tests.test_job_contract import FakeStore

    fake = FakeStore()
    monkeypatch.setattr("app.jobs.celery_task.job_runs_store", lambda: fake)
    return fake


def test_a_successful_sweep_records_a_completed_run(
    monkeypatch: pytest.MonkeyPatch, job_store: Any
) -> None:
    store = FakeBillingStore([{"id": "a", "status": "open", "days_overdue": 3}])
    monkeypatch.setattr("app.modules.billing.tasks.service_billing_store", lambda: store)

    disposition = mark_past_due.run()
    assert disposition["status"] == "completed"
    assert disposition["result"] == {"flipped": 1}

    row = job_store.rows[disposition["run_id"]]
    assert row["job_name"] == "billing.past_due_sweep"
    assert row["client_id"] is None, "a platform-wide sweep must not consume a tenant's slots"


def test_a_clean_sweep_still_records_a_run(
    monkeypatch: pytest.MonkeyPatch, job_store: Any
) -> None:
    """Finding nothing to do is a successful outcome, not a silent no-op. Before the
    contract, a quiet night and a broken worker were indistinguishable."""
    monkeypatch.setattr(
        "app.modules.billing.tasks.service_billing_store", lambda: FakeBillingStore([])
    )
    disposition = mark_past_due.run()
    assert disposition["status"] == "completed"
    assert disposition["result"] == {"flipped": 0}
    assert "no overdue invoices" in disposition["detail"]


def test_an_unreachable_store_is_retried_rather_than_swallowed(
    monkeypatch: pytest.MonkeyPatch, job_store: Any
) -> None:
    """The behaviour change worth having.

    This used to return ``{"state": "error", "flipped": 0}`` - a value nothing acted
    on. Now it is a bounded retry, and after the budget a dead letter an operator can
    see and replay.
    """
    from celery.exceptions import Retry

    store = FakeBillingStore()
    store.explode = RuntimeError("db is down")
    monkeypatch.setattr("app.modules.billing.tasks.service_billing_store", lambda: store)

    with pytest.raises(Retry):
        mark_past_due.run()
    assert job_store.defers, "the run should have been deferred for a retry"
    assert not job_store.dead_letters, "not dead-lettered while the attempt budget remains"


def test_the_sweep_is_deliberately_not_keyed(
    monkeypatch: pytest.MonkeyPatch, job_store: Any
) -> None:
    """A per-day idempotency key would suppress a legitimate re-run.

    An invoice can fall due at 14:00; the 02:00 sweep is not the same unit of work as
    a 14:00 one. The task is internally idempotent and spends nothing, which is the
    case the contract documents as safe to leave un-keyed.
    """
    monkeypatch.setattr(
        "app.modules.billing.tasks.service_billing_store",
        lambda: FakeBillingStore([{"id": "a", "status": "open", "days_overdue": 3}]),
    )
    first = mark_past_due.run()
    second = mark_past_due.run()
    assert first["run_id"] != second["run_id"], "a second sweep must actually run"
    assert job_store.rows[first["run_id"]]["idempotency_key"] is None


# --------------------------------------------------------------------------- #
# 5. Registration: the task is name-pinned and on the beat schedule.
# --------------------------------------------------------------------------- #
def test_the_task_is_explicitly_name_pinned() -> None:
    # The beat schedule refers to the task BY NAME, so an auto-derived name (which
    # follows the module path) would silently break the schedule on any refactor.
    assert mark_past_due.name == "mark_past_due"


def test_the_beat_schedule_wires_the_sweep() -> None:
    from workers.celery_app import celery_app

    entry = celery_app.conf.beat_schedule.get("mark-past-due-invoices")
    assert entry is not None, "the past-due sweep is not on the beat schedule"
    assert entry["task"] == "mark_past_due"
    assert entry["schedule"] > 0


def test_the_module_is_in_the_celery_include_list() -> None:
    # include=[...] is deterministic registration (autodiscover would find nothing);
    # a task module missing from it is never registered and the beat entry no-ops.
    from workers.celery_app import celery_app

    assert "app.modules.billing.tasks" in celery_app.conf.include
