"""7F-3 gate: team-performance metric formulas are deterministic on fixed counts.

:func:`compute_metrics` is pure arithmetic over :class:`MemberCounts` (the raw
aggregates the two ledgers produce), so the onTime / utilization / quality
formulas are pinned here with no database. :func:`fetch_member_counts` is exercised
against a fake ``rls_connection`` cursor to prove the tasks+activity merge.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pytest

from app.services import team_metrics
from app.services.team_metrics import (
    CAPACITY,
    MemberCounts,
    MemberMetrics,
    compute_metrics,
    fetch_member_counts,
)

pytestmark = pytest.mark.unit


def test_no_tasks_reports_all_zero() -> None:
    # A fresh/invited member with no tasks has no record yet -> all zero (not 100).
    assert compute_metrics(MemberCounts()) == MemberMetrics()


def test_on_time_is_on_time_over_dated_deliveries() -> None:
    m = compute_metrics(
        MemberCounts(active=0, completed=4, done_with_due=4, on_time_done=3)
    )
    assert m.on_time == 75  # 3 of 4 dated deliveries were on time


def test_on_time_defaults_100_when_no_dated_deliveries() -> None:
    # Completed work but nothing carried a due date -> nothing was late.
    m = compute_metrics(MemberCounts(completed=5, done_with_due=0))
    assert m.on_time == 100


def test_utilization_is_load_vs_capacity_capped() -> None:
    # active/CAPACITY as a percentage, capped at 100.
    half = compute_metrics(MemberCounts(active=CAPACITY // 2))
    assert half.utilization == 50
    over = compute_metrics(MemberCounts(active=CAPACITY * 3))
    assert over.utilization == 100  # capped


def test_quality_is_approvals_over_resolved_attempts() -> None:
    # submissions=2 gate trips, 0 pending in review => 2 resolved; 1 approved (done).
    m = compute_metrics(
        MemberCounts(active=1, completed=1, content_done=1, content_review=0, submissions=2)
    )
    assert m.quality == 50  # one approve, one reject


def test_quality_excludes_pending_reviews() -> None:
    # 3 submissions, 1 still pending in review => 2 resolved; 2 approved -> 100%.
    m = compute_metrics(
        MemberCounts(active=1, completed=2, content_done=2, content_review=1, submissions=3)
    )
    assert m.quality == 100


def test_quality_defaults_100_when_nothing_resolved() -> None:
    # A content task submitted and still in review: no resolved attempt yet.
    m = compute_metrics(
        MemberCounts(active=1, completed=0, content_done=0, content_review=1, submissions=1)
    )
    assert m.quality == 100


def test_quality_clamped_to_100_when_submissions_undercount() -> None:
    # A lead may have submitted on the member's behalf (actor != member), so
    # content_done can exceed counted submissions -> clamp instead of >100.
    m = compute_metrics(
        MemberCounts(active=0, completed=3, content_done=3, content_review=0, submissions=1)
    )
    assert m.quality == 100


def test_active_and_completed_pass_through() -> None:
    m = compute_metrics(MemberCounts(active=4, completed=9))
    assert m.active_tasks == 4 and m.completed == 9


# --- fetch_member_counts merge (fake cursor) ---------------------------------


class _FakeCursor:
    """Returns task-agg rows or activity-agg rows depending on the last query."""

    def __init__(self, task_rows: list[dict[str, Any]], act_rows: list[dict[str, Any]]) -> None:
        self._task_rows = task_rows
        self._act_rows = act_rows
        self._mode = "tasks"

    def execute(self, query: Any, params: Any = None) -> None:
        self._mode = "tasks" if "public.tasks" in str(query) else "activity"

    def fetchall(self) -> list[dict[str, Any]]:
        return self._task_rows if self._mode == "tasks" else self._act_rows


def test_fetch_member_counts_merges_tasks_and_activity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_rows = [
        {
            "member_id": "u-1", "active": 2, "completed": 5, "done_with_due": 4,
            "on_time_done": 3, "content_done": 1, "content_review": 1,
        },
        {
            "member_id": "u-2", "active": 0, "completed": 0, "done_with_due": 0,
            "on_time_done": 0, "content_done": 0, "content_review": 0,
        },
    ]
    act_rows = [
        {"member_id": "u-1", "submissions": 3},
        {"member_id": "u-3", "submissions": 1},  # activity-only member
    ]

    @contextlib.contextmanager
    def _fake_rls(_caller_id: str, **_kw: Any) -> Any:
        yield _FakeCursor(task_rows, act_rows)

    monkeypatch.setattr(team_metrics, "rls_connection", _fake_rls)

    counts = fetch_member_counts("u-caller")
    assert counts["u-1"] == MemberCounts(
        active=2, completed=5, done_with_due=4, on_time_done=3,
        content_done=1, content_review=1, submissions=3,
    )
    # A member with only activity (no task row) still appears, tasks default 0.
    assert counts["u-3"] == MemberCounts(submissions=1)
    # A member with only tasks and no submissions defaults submissions=0.
    assert counts["u-2"].submissions == 0
