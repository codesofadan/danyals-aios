"""P5-4 gate: GET /me returns the caller's TeamMemberRecord with LIVE task
counts (activeTasks = not-done, completed = done), RLS-scoped to the caller."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.tasks_repo import get_tasks_repo

pytestmark = pytest.mark.unit

_MEMBER_FIELDS = {
    "id", "name", "init", "c", "title", "email", "role", "status",
    "activeTasks", "completed", "onTime", "utilization", "quality", "joined",
}


class FakeMeRepo:
    def __init__(self) -> None:
        self.user_row: dict[str, Any] | None = {
            "id": "u-1", "name": "Bilal Anwar", "avatar_color": "#4D8DF0",
            "title": "SEO Specialist", "email": "bilal@x.com", "role": "specialist",
            "status": "active", "created_at": "2023-05-01T00:00:00Z",
        }
        self.tasks: list[dict[str, Any]] = []
        self.scoped: str | None = None

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.user_row

    def list_tasks(self, assignee_id: str | None = None) -> list[dict[str, Any]]:
        self.scoped = assignee_id
        return self.tasks


def _user(role: str = "specialist", uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="bilal@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Bilal Anwar", title="SEO Specialist", avatar_color="#4D8DF0",
        phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeMeRepo:
    return FakeMeRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeMeRepo) -> Callable[..., None]:
    app.dependency_overrides[get_tasks_repo] = lambda: repo

    def _as(role: str = "specialist", uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


async def test_me_shape_and_live_counts(
    client: httpx.AsyncClient, repo: FakeMeRepo, wire: Callable[..., None]
) -> None:
    repo.tasks = [
        {"status": "todo"}, {"status": "in_progress"}, {"status": "review"},
        {"status": "done"}, {"status": "done"},
    ]
    wire("specialist", "u-1")
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == _MEMBER_FIELDS
    assert repo.scoped == "u-1"  # counts are scoped to the caller
    assert body["activeTasks"] == 3  # todo + in_progress + review
    assert body["completed"] == 2
    assert body["role"] == "Specialist"  # capitalized TeamRole
    assert body["joined"] == "May 2023"
    # deferred metrics stay at defaults
    assert body["onTime"] == 0 and body["utilization"] == 0 and body["quality"] == 0


async def test_me_zero_when_no_tasks(
    client: httpx.AsyncClient, repo: FakeMeRepo, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")
    body = (await client.get("/api/v1/me")).json()
    assert body["activeTasks"] == 0
    assert body["completed"] == 0


async def test_me_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # portal client lacks view_reports
    assert (await client.get("/api/v1/me")).status_code == 403
