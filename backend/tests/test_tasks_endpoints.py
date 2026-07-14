"""P5-3 gate: /tasks endpoints - shapes, RBAC, the lifecycle, the review gate,
optimistic concurrency, and staff-assignee validation. Repo + clients are faked
(no Supabase). The DB-trigger boundary itself is proven in P5-5 integration."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.clients_repo import get_clients_repo
from app.db.tasks_repo import get_tasks_repo

pytestmark = pytest.mark.unit

_TASK_FIELDS = {"id", "title", "client", "type", "assignee", "priority", "status", "due"}


class FakeTasksRepo:
    def __init__(self) -> None:
        self.tasks: dict[str, dict[str, Any]] = {}
        self.users: dict[str, str] = {"u-1": "specialist", "u-2": "specialist", "u-lead": "manager"}
        self.force_race = False
        self.listed_scope: str | None = "UNSET"
        self._seq = 2040

    def seed(self, **over: Any) -> dict[str, Any]:
        self._seq += 1
        code = over.get("code", f"J-{self._seq}")
        row: dict[str, Any] = {
            "id": f"uuid-{self._seq}", "code": code, "title": "Task",
            "client_id": "cl-1", "client_name": "Verde Cafe", "type": "technical_audit",
            "assignee_id": "u-1", "priority": "med", "status": "todo", "due_date": None,
            "audit_id": None, "created_by": "u-lead",
            "created_at": datetime.now(UTC).isoformat(),
        }
        row.update(over)
        self.tasks[code] = row
        return row

    def list_tasks(
        self, assignee_id: str | None = None, *, limit: int | None = None, offset: int = 0
    ) -> list[dict[str, Any]]:
        self.listed_scope = assignee_id
        rows = list(self.tasks.values())
        if assignee_id is not None:
            rows = [r for r in rows if r.get("assignee_id") == assignee_id]
        return rows

    def get_task_by_code(self, code: str) -> dict[str, Any] | None:
        return self.tasks.get(code)

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        role = self.users.get(user_id)
        return {"id": user_id, "role": role} if role else None

    def insert_task(self, row: dict[str, Any]) -> dict[str, Any]:
        self._seq += 1
        code = f"J-{self._seq}"
        rec = {"id": f"uuid-{self._seq}", "code": code,
               "created_at": datetime.now(UTC).isoformat(), **row}
        self.tasks[code] = rec
        return rec

    def update_task_by_code(
        self, code: str, patch: dict[str, Any], expect_status: str | None = None
    ) -> dict[str, Any] | None:
        row = self.tasks.get(code)
        if row is None:
            return None
        if expect_status is not None and (self.force_race or row.get("status") != expect_status):
            return None  # optimistic-concurrency miss -> 0 rows
        row.update(patch)
        return row


class FakeClientsRepo:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return {"id": client_id, "name": "Verde Cafe"} if self.exists else None


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeTasksRepo:
    return FakeTasksRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeTasksRepo) -> Callable[..., None]:
    app.dependency_overrides[get_tasks_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1", *, client_exists: bool = True) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)
        app.dependency_overrides[get_clients_repo] = lambda: FakeClientsRepo(client_exists)

    return _as


# --- reads / RBAC -------------------------------------------------------------

async def test_client_forbidden_from_reads(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # portal client lacks view_reports
    assert (await client.get("/api/v1/tasks")).status_code == 403


async def test_mine_scopes_to_caller(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(assignee_id="u-1")
    repo.seed(assignee_id="u-2")
    wire("specialist", "u-1")
    resp = await client.get("/api/v1/tasks", params={"mine": "true"})
    assert resp.status_code == 200
    assert repo.listed_scope == "u-1"  # scoped to the caller
    assert all(t["assignee"] == "u-1" for t in resp.json())


async def test_explicit_assignee_scope(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(assignee_id="u-2")
    wire("manager", "u-lead")
    resp = await client.get("/api/v1/tasks", params={"assignee": "u-2"})
    assert resp.status_code == 200
    assert repo.listed_scope == "u-2"


async def test_list_shape_only_task_fields(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-2041", type="content_sprint", due_date="2026-07-12")
    wire("viewer")
    body = (await client.get("/api/v1/tasks")).json()
    assert set(body[0]) == _TASK_FIELDS
    assert body[0]["id"] == "J-2041"  # public code, not a UUID
    assert body[0]["type"] == "Content Sprint"
    assert body[0]["due"] == "Jul 12"


# --- create -------------------------------------------------------------------

async def test_create_requires_assign_tasks(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("specialist")  # holds view_reports but NOT assign_tasks
    resp = await client.post(
        "/api/v1/tasks",
        json={"title": "x", "client_id": "cl-1", "type": "Technical Audit", "assignee_id": "u-1"},
    )
    assert resp.status_code == 403


async def test_create_happy_path(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/tasks",
        json={"title": "Sprint", "client_id": "cl-1", "type": "Content Sprint",
              "assignee_id": "u-1", "priority": "high", "due": "2026-07-14"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert set(body) == _TASK_FIELDS
    assert body["status"] == "todo"
    assert body["type"] == "Content Sprint"
    assert body["client"] == "Verde Cafe"
    assert body["due"] == "Jul 14"


async def test_create_unknown_client_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead", client_exists=False)
    resp = await client.post(
        "/api/v1/tasks",
        json={"title": "x", "client_id": "cl-x", "type": "Local SEO", "assignee_id": "u-1"},
    )
    assert resp.status_code == 404


async def test_create_rejects_client_assignee(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.users["u-portal"] = "client"
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/tasks",
        json={"title": "x", "client_id": "cl-1", "type": "Local SEO", "assignee_id": "u-portal"},
    )
    assert resp.status_code == 400


async def test_create_unknown_assignee_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")
    resp = await client.post(
        "/api/v1/tasks",
        json={"title": "x", "client_id": "cl-1", "type": "Local SEO", "assignee_id": "ghost"},
    )
    assert resp.status_code == 404


# --- advance ------------------------------------------------------------------

async def test_advance_todo_to_in_progress(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="todo", type="technical_audit", assignee_id="u-1")
    wire("specialist", "u-1")
    resp = await client.post("/api/v1/tasks/J-1/advance")
    assert resp.status_code == 200
    assert resp.json()["status"] == "in_progress"


async def test_advance_content_sprint_goes_to_review(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="in_progress", type="content_sprint", assignee_id="u-1")
    wire("specialist", "u-1")
    resp = await client.post("/api/v1/tasks/J-1/advance")
    assert resp.json()["status"] == "review"


async def test_advance_non_content_goes_to_done(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="in_progress", type="technical_audit", assignee_id="u-1")
    wire("specialist", "u-1")
    resp = await client.post("/api/v1/tasks/J-1/advance")
    assert resp.json()["status"] == "done"


async def test_advance_forbidden_for_non_assignee_non_lead(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="todo", assignee_id="u-1")
    wire("specialist", "u-2")  # a different specialist, not the assignee, not a lead
    resp = await client.post("/api/v1/tasks/J-1/advance")
    assert resp.status_code == 403


async def test_lead_may_advance_others_task(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="todo", assignee_id="u-1")
    wire("manager", "u-lead")
    assert (await client.post("/api/v1/tasks/J-1/advance")).status_code == 200


async def test_advance_from_review_is_409(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="review", type="content_sprint", assignee_id="u-1")
    wire("specialist", "u-1")
    resp = await client.post("/api/v1/tasks/J-1/advance")
    assert resp.status_code == 409


async def test_advance_from_done_is_409(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="done", assignee_id="u-1")
    wire("manager", "u-lead")
    assert (await client.post("/api/v1/tasks/J-1/advance")).status_code == 409


async def test_advance_optimistic_conflict_409(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="todo", assignee_id="u-1")
    repo.force_race = True  # a racing transition already moved the row
    wire("specialist", "u-1")
    assert (await client.post("/api/v1/tasks/J-1/advance")).status_code == 409


async def test_advance_missing_task_404(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")
    assert (await client.post("/api/v1/tasks/J-nope/advance")).status_code == 404


# --- review -------------------------------------------------------------------

async def test_review_role_gated_for_specialist(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="review", type="content_sprint", assignee_id="u-1")
    wire("specialist", "u-1")  # not CAN_REVIEW
    resp = await client.post("/api/v1/tasks/J-1/review", json={"action": "approve"})
    assert resp.status_code == 403


async def test_review_approve_to_done(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="review", type="content_sprint", assignee_id="u-1")
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/tasks/J-1/review", json={"action": "approve"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "done"


async def test_review_reject_to_in_progress(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="review", type="content_sprint", assignee_id="u-1")
    wire("admin", "u-admin")
    resp = await client.post("/api/v1/tasks/J-1/review", json={"action": "reject"})
    assert resp.json()["status"] == "in_progress"


async def test_review_non_review_status_409(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", status="in_progress", type="content_sprint", assignee_id="u-1")
    wire("manager", "u-lead")
    resp = await client.post("/api/v1/tasks/J-1/review", json={"action": "approve"})
    assert resp.status_code == 409


# --- patch --------------------------------------------------------------------

async def test_patch_requires_assign_tasks(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1")
    wire("specialist", "u-1")
    resp = await client.patch("/api/v1/tasks/J-1", json={"priority": "urgent"})
    assert resp.status_code == 403


async def test_patch_reassign_and_repriority(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1", assignee_id="u-1", priority="low")
    wire("manager", "u-lead")
    resp = await client.patch(
        "/api/v1/tasks/J-1", json={"assignee_id": "u-2", "priority": "urgent"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["assignee"] == "u-2"
    assert body["priority"] == "urgent"


async def test_patch_rejects_client_assignee(
    client: httpx.AsyncClient, repo: FakeTasksRepo, wire: Callable[..., None]
) -> None:
    repo.seed(code="J-1")
    repo.users["u-portal"] = "client"
    wire("manager", "u-lead")
    resp = await client.patch("/api/v1/tasks/J-1", json={"assignee_id": "u-portal"})
    assert resp.status_code == 400
