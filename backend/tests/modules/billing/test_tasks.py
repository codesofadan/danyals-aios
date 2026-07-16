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


def test_the_celery_entry_point_never_re_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # The outer guard catches anything the core's own try/except could not - e.g. the
    # store factory or get_settings() itself failing.
    def _explode() -> Any:
        raise RuntimeError("no pool")

    monkeypatch.setattr("app.modules.billing.tasks.service_billing_store", _explode)
    assert mark_past_due() == {"state": "error", "flipped": 0}


def test_the_celery_entry_point_returns_the_core_result(
    monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FakeBillingStore([{"id": "a", "status": "open", "days_overdue": 3}])
    monkeypatch.setattr("app.modules.billing.tasks.service_billing_store", lambda: store)
    assert mark_past_due() == {"state": "ok", "flipped": 1}


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
