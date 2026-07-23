"""Wave 6: GET /team/members - the eligible-assignee roster (the assignee-picker fix).

Proves the endpoint returns EVERY staff member including invited-but-not-yet-signed-in
ones (the exact case the old picker hid), overlays live metrics, is gated on
``assign_tasks`` (so a manager who lacks ``manage_team`` can still load the picker),
and excludes portal clients. The repo + metrics are faked (no DB). The team router is
mounted onto the test app here because it is registered centrally in a RESERVED file.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.team_repo import get_team_repo
from app.routers import team
from app.services.team_metrics import MemberMetrics, get_team_metrics

pytestmark = pytest.mark.unit

_MEMBER_FIELDS = {
    "id", "name", "init", "c", "title", "email", "role", "status",
    "activeTasks", "completed", "onTime", "utilization", "quality", "joined",
}


class FakeTeamRepo:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[int | None, int]] = []

    def list_staff(self, *, limit: int | None = None, offset: int = 0) -> list[dict[str, Any]]:
        self.calls.append((limit, offset))
        return self.rows


class FakeMetrics:
    def member_metrics(self, member_ids: Any = None) -> dict[str, MemberMetrics]:
        return {
            mid: MemberMetrics(active_tasks=3, completed=5, on_time=90, utilization=40, quality=100)
            for mid in (member_ids or [])
        }


def _row(uid: str, *, role: str = "specialist", status: str = "active", name: str = "Sam Doe") -> dict[str, Any]:
    return {
        "id": uid, "name": name, "role": role, "status": status, "title": "SEO",
        "email": f"{uid}@x.com", "avatar_color": "#000", "created_at": datetime.now(UTC),
    }


def _user(role: str, uid: str = "u-lead") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture(autouse=True)
def _mount(app: FastAPI) -> None:
    # The team router is attached centrally in a RESERVED aggregator; mount it here so
    # the endpoint is reachable through the real app + dep graph in this suite.
    app.include_router(team.router, prefix="/api/v1")


@pytest.fixture
def wire(app: FastAPI) -> Callable[..., None]:
    def _as(role: str, rows: list[dict[str, Any]]) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_team_repo] = lambda: FakeTeamRepo(rows)
        app.dependency_overrides[get_team_metrics] = lambda: FakeMetrics()

    return _as


async def test_members_include_invited_with_live_metrics(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", [_row("u-1"), _row("u-2", status="invited", name="New Hire")])
    resp = await client.get("/api/v1/team/members")
    assert resp.status_code == 200
    body = resp.json()
    assert {m["id"] for m in body} == {"u-1", "u-2"}  # invited member IS present
    invited = next(m for m in body if m["id"] == "u-2")
    assert invited["status"] == "invited"
    assert invited["activeTasks"] == 3  # live metrics overlaid
    assert set(body[0]) == _MEMBER_FIELDS


async def test_members_manager_can_load(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    # A manager holds assign_tasks (but NOT manage_team) - it must still load the picker.
    wire("manager", [_row("u-1")])
    assert (await client.get("/api/v1/team/members")).status_code == 200


async def test_members_forbidden_for_non_assigner(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("specialist", [_row("u-1")])  # holds view_reports but NOT assign_tasks
    assert (await client.get("/api/v1/team/members")).status_code == 403


async def test_members_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client", [])
    assert (await client.get("/api/v1/team/members")).status_code == 403


async def test_members_require_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/team/members")).status_code == 401
