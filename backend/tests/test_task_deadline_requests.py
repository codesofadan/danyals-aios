"""Deadline-change-request workflow (0074): an assignee may ask for a new due
date only within 12h of their task's start (fallback: assignment); a lead
approves (due_date actually moves) or rejects (it doesn't). Repo is faked (no
Postgres) - the RLS/trigger boundary itself belongs in an integration suite,
mirroring how test_tasks_endpoints.py treats the base tasks lifecycle."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.tasks_repo import get_tasks_repo

pytestmark = pytest.mark.unit


class FakeDeadlineTasksRepo:
    """Fakes just enough of TasksRepo for the deadline-request endpoints."""

    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.requests: dict[str, dict[str, Any]] = {}
        self._seq = 0

    def seed_task(self, **over: Any) -> dict[str, Any]:
        self._seq += 1
        code = over.pop("code", f"J-{self._seq}")
        row: dict[str, Any] = {
            "id": f"uuid-{self._seq}",
            "code": code,
            "title": "Task",
            "client_id": "cl-1",
            "client_name": "Verde Cafe",
            "type": "technical_audit",
            "assignee_id": "u-1",
            "priority": "med",
            "status": "in_progress",
            "due_date": "2026-08-01",
            "created_at": datetime.now(UTC).isoformat(),
            "started_at": None,
        }
        row.update(over)
        self.tasks[code] = row
        return row

    # -- tasks -------------------------------------------------------------
    def get_task_by_code(self, code: str) -> dict[str, Any] | None:
        return self.tasks.get(code)

    def update_task_by_code(
        self, code: str, patch: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        row = self.tasks.get(code)
        if row is None:
            return None
        row.update(patch)
        return row

    # -- deadline requests ---------------------------------------------------
    def insert_deadline_request(self, row: dict[str, Any]) -> dict[str, Any]:
        rid = f"req-{len(self.requests) + 1}"
        rec = {
            "id": rid,
            "status": "pending",
            "decided_by": None,
            "decided_at": None,
            "created_at": datetime.now(UTC).isoformat(),
            **row,
        }
        self.requests[rid] = rec
        return rec

    def list_deadline_requests(self, task_id: str) -> list[dict[str, Any]]:
        return [r for r in self.requests.values() if r["task_id"] == task_id]

    def get_pending_deadline_request(self, task_id: str) -> dict[str, Any] | None:
        for r in self.requests.values():
            if r["task_id"] == task_id and r["status"] == "pending":
                return r
        return None

    def get_deadline_request(self, request_id: str) -> dict[str, Any] | None:
        return self.requests.get(request_id)

    def decide_deadline_request(
        self, request_id: str, patch: dict[str, Any]
    ) -> dict[str, Any] | None:
        row = self.requests.get(request_id)
        if row is None or row["status"] != "pending":
            return None
        row.update(patch)
        return row


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeDeadlineTasksRepo:
    return FakeDeadlineTasksRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeDeadlineTasksRepo) -> Callable[..., None]:
    app.dependency_overrides[get_tasks_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


# --- happy path -----------------------------------------------------------

async def test_request_within_window_succeeds(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_notify_leads(*, kind: str, **_k: Any) -> None:
        calls.append(kind)

    monkeypatch.setattr("app.routers.tasks.notify_leads", _fake_notify_leads)
    repo.seed_task(code="J-1", assignee_id="u-1", started_at=datetime.now(UTC).isoformat())
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/tasks/J-1/deadline-requests",
        json={"requested_due_date": "2026-09-01", "reason": "scope grew"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "pending"
    assert body["requestedDueDate"] == "2026-09-01"
    assert body["taskCode"] == "J-1"
    assert calls == ["deadline_requested"]


async def test_request_falls_back_to_created_at_when_not_started(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    repo.seed_task(
        code="J-1", assignee_id="u-1", started_at=None,
        created_at=datetime.now(UTC).isoformat(),
    )
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/tasks/J-1/deadline-requests", json={"requested_due_date": "2026-09-01"}
    )
    assert resp.status_code == 201


# --- 12h window enforcement -------------------------------------------------

async def test_request_past_window_is_rejected(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    stale = (datetime.now(UTC) - timedelta(hours=13)).isoformat()
    repo.seed_task(code="J-1", assignee_id="u-1", started_at=stale)
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/tasks/J-1/deadline-requests", json={"requested_due_date": "2026-09-01"}
    )
    assert resp.status_code == 409
    assert repo.requests == {}  # nothing was written


async def test_request_right_at_window_edge_is_allowed(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    just_inside = (datetime.now(UTC) - timedelta(hours=11, minutes=59)).isoformat()
    repo.seed_task(code="J-1", assignee_id="u-1", started_at=just_inside)
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/tasks/J-1/deadline-requests", json={"requested_due_date": "2026-09-01"}
    )
    assert resp.status_code == 201


# --- other guards -----------------------------------------------------------

async def test_non_assignee_forbidden(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    repo.seed_task(code="J-1", assignee_id="u-1", started_at=datetime.now(UTC).isoformat())
    wire("specialist", "u-2")  # not the assignee
    resp = await client.post(
        "/api/v1/tasks/J-1/deadline-requests", json={"requested_due_date": "2026-09-01"}
    )
    assert resp.status_code == 403


async def test_duplicate_pending_request_is_rejected(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    task = repo.seed_task(code="J-1", assignee_id="u-1", started_at=datetime.now(UTC).isoformat())
    repo.insert_deadline_request(
        {"task_id": task["id"], "task_code": "J-1", "requested_by": "u-1",
         "requested_due_date": "2026-09-01", "reason": None}
    )
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/tasks/J-1/deadline-requests", json={"requested_due_date": "2026-09-05"}
    )
    assert resp.status_code == 409


async def test_request_missing_task_404(
    client: httpx.AsyncClient, wire: Callable[..., None],
) -> None:
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/tasks/J-nope/deadline-requests", json={"requested_due_date": "2026-09-01"}
    )
    assert resp.status_code == 404


# --- decide (approve/reject) ------------------------------------------------

async def test_lead_approve_moves_due_date_and_notifies_assignee(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str]] = []

    async def _fake_notify(user_id: str, *, kind: str, **_k: Any) -> None:
        calls.append((user_id, kind))

    monkeypatch.setattr("app.routers.tasks.notify", _fake_notify)
    task = repo.seed_task(code="J-1", assignee_id="u-1", due_date="2026-08-01")
    req = repo.insert_deadline_request(
        {"task_id": task["id"], "task_code": "J-1", "requested_by": "u-1",
         "requested_due_date": "2026-09-01", "reason": None}
    )
    wire("manager", "u-lead")
    resp = await client.post(
        f"/api/v1/tasks/J-1/deadline-requests/{req['id']}/decide", json={"action": "approve"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "approved"
    assert repo.tasks["J-1"]["due_date"] == "2026-09-01"  # actually moved
    assert calls == [("u-1", "deadline_decided")]


async def test_lead_reject_leaves_due_date_untouched(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    task = repo.seed_task(code="J-1", assignee_id="u-1", due_date="2026-08-01")
    req = repo.insert_deadline_request(
        {"task_id": task["id"], "task_code": "J-1", "requested_by": "u-1",
         "requested_due_date": "2026-09-01", "reason": None}
    )
    wire("manager", "u-lead")
    resp = await client.post(
        f"/api/v1/tasks/J-1/deadline-requests/{req['id']}/decide", json={"action": "reject"}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "rejected"
    assert repo.tasks["J-1"]["due_date"] == "2026-08-01"  # unchanged


async def test_decide_requires_assign_tasks(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    task = repo.seed_task(code="J-1", assignee_id="u-1")
    req = repo.insert_deadline_request(
        {"task_id": task["id"], "task_code": "J-1", "requested_by": "u-1",
         "requested_due_date": "2026-09-01", "reason": None}
    )
    wire("specialist", "u-1")  # the requester themselves, not a lead
    resp = await client.post(
        f"/api/v1/tasks/J-1/deadline-requests/{req['id']}/decide", json={"action": "approve"}
    )
    assert resp.status_code == 403


async def test_decide_non_pending_is_409(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    task = repo.seed_task(code="J-1", assignee_id="u-1")
    req = repo.insert_deadline_request(
        {"task_id": task["id"], "task_code": "J-1", "requested_by": "u-1",
         "requested_due_date": "2026-09-01", "reason": None}
    )
    req["status"] = "approved"  # already decided
    wire("manager", "u-lead")
    resp = await client.post(
        f"/api/v1/tasks/J-1/deadline-requests/{req['id']}/decide", json={"action": "reject"}
    )
    assert resp.status_code == 409


# --- list --------------------------------------------------------------------

async def test_list_deadline_requests(
    client: httpx.AsyncClient, repo: FakeDeadlineTasksRepo, wire: Callable[..., None],
) -> None:
    task = repo.seed_task(code="J-1", assignee_id="u-1")
    repo.insert_deadline_request(
        {"task_id": task["id"], "task_code": "J-1", "requested_by": "u-1",
         "requested_due_date": "2026-09-01", "reason": None}
    )
    wire("viewer")
    resp = await client.get("/api/v1/tasks/J-1/deadline-requests")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
