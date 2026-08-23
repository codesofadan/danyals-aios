"""The scheduled-publish dispatcher under the job contract.

One property carries this file: **a partial dispatch is degraded, not done.**

`execute_dispatch_scheduled_publishes` returns `claimed` and the `dispatched` list
separately, so when fewer publishes go out than rows were claimed, some client's
approved content is claimed and unsent. Reporting that as `completed` is precisely the
defect P0-4 removed from `_publish_artifact` — a job claiming success for work that
reached nobody — and returning `completed` unconditionally here would have quietly
reintroduced it one layer up.
"""

from __future__ import annotations

import psycopg
import pytest
from celery.exceptions import Retry

import workers.tasks.content as wk
from tests.test_job_contract import FakeStore
from workers.tasks.content import dispatch_scheduled_content_publishes

pytestmark = pytest.mark.unit


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    *,
    claimed: int,
    dispatched: list[str],
    claim_raises: BaseException | None = None,
) -> None:
    def _claim() -> list[str]:
        if claim_raises:
            raise claim_raises
        return [f"C-{i}" for i in range(claimed)]

    monkeypatch.setattr(wk, "_claim_due_scheduled_codes", _claim)
    monkeypatch.setattr(wk, "PrivilegedContentStore", lambda: object())
    monkeypatch.setattr(
        wk,
        "execute_dispatch_scheduled_publishes",
        lambda codes, **kw: {"claimed": claimed, "dispatched": dispatched},
    )


def test_a_full_dispatch_is_completed(
    monkeypatch: pytest.MonkeyPatch, _job_ledger: FakeStore
) -> None:
    _wire(monkeypatch, claimed=3, dispatched=["C-0", "C-1", "C-2"])
    disposition = dispatch_scheduled_content_publishes.run()
    assert disposition["status"] == "completed"
    assert "dispatched 3" in disposition["detail"]


def test_nothing_due_is_completed(
    monkeypatch: pytest.MonkeyPatch, _job_ledger: FakeStore
) -> None:
    """A quiet tick is a real outcome, and must be distinguishable from a broken one."""
    _wire(monkeypatch, claimed=0, dispatched=[])
    disposition = dispatch_scheduled_content_publishes.run()
    assert disposition["status"] == "completed"
    assert "nothing was due" in disposition["detail"]


def test_a_partial_dispatch_is_degraded_and_says_what_is_stuck(
    monkeypatch: pytest.MonkeyPatch, _job_ledger: FakeStore
) -> None:
    """The whole point of this file.

    Five claimed, two dispatched: three clients' approved posts are claimed and unsent.
    Under the old entry point this returned a result dict nobody read, and the board
    showed nothing wrong.
    """
    _wire(monkeypatch, claimed=5, dispatched=["C-0", "C-1"])
    disposition = dispatch_scheduled_content_publishes.run()

    assert disposition["status"] == "degraded"
    row = _job_ledger.rows[disposition["run_id"]]
    assert row["reason_code"] == "partial_dispatch"
    assert "3 approved item(s) are claimed and unsent" in row["reason"], (
        "the reason must name what is stuck, not just that something is"
    )


def test_a_database_outage_is_retried(
    monkeypatch: pytest.MonkeyPatch, _job_ledger: FakeStore
) -> None:
    _wire(
        monkeypatch, claimed=0, dispatched=[], claim_raises=psycopg.OperationalError("refused")
    )
    with pytest.raises(Retry):
        dispatch_scheduled_content_publishes.run()
    assert _job_ledger.defers
    assert not _job_ledger.dead_letters


def test_an_unclassified_error_is_dead_lettered_not_retried(
    monkeypatch: pytest.MonkeyPatch, _job_ledger: FakeStore
) -> None:
    """The blanket `except Exception: return {...}` this replaces meant a systematic
    failure looked identical to a quiet night, every night."""
    _wire(monkeypatch, claimed=0, dispatched=[], claim_raises=RuntimeError("bad state"))
    disposition = dispatch_scheduled_content_publishes.run()
    assert disposition["status"] == "failed"
    assert _job_ledger.dead_letters
    assert not _job_ledger.defers
