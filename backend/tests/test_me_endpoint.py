"""P5-4 / 7F-3 gate: GET /me returns the caller's TeamMemberRecord with LIVE
metrics overlaid (activeTasks/completed + real onTime/utilization/quality from
:mod:`app.services.team_metrics`), RLS-scoped to the caller."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.tasks_repo import get_tasks_repo
from app.services.team_metrics import MemberMetrics, get_team_metrics

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

    def get_user(self, user_id: str) -> dict[str, Any] | None:
        return self.user_row


class FakeMetrics:
    """Stub metrics reader recording the ids it was asked to score."""

    def __init__(self) -> None:
        self.scored: dict[str, MemberMetrics] = {}
        self.asked: Sequence[str] | None = None

    def member_metrics(self, member_ids: Sequence[str] | None = None) -> dict[str, MemberMetrics]:
        self.asked = member_ids
        return self.scored


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
def metrics() -> FakeMetrics:
    return FakeMetrics()


@pytest.fixture
def wire(app: FastAPI, repo: FakeMeRepo, metrics: FakeMetrics) -> Callable[..., None]:
    app.dependency_overrides[get_tasks_repo] = lambda: repo
    app.dependency_overrides[get_team_metrics] = lambda: metrics

    def _as(role: str = "specialist", uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


async def test_me_shape_and_live_metrics(
    client: httpx.AsyncClient, metrics: FakeMetrics, wire: Callable[..., None]
) -> None:
    metrics.scored = {
        "u-1": MemberMetrics(
            active_tasks=3, completed=2, on_time=94, utilization=75, quality=88
        )
    }
    wire("specialist", "u-1")
    resp = await client.get("/api/v1/me")
    assert resp.status_code == 200
    body = resp.json()
    assert set(body) == _MEMBER_FIELDS
    assert list(metrics.asked or []) == ["u-1"]  # scoped to the caller
    assert body["activeTasks"] == 3
    assert body["completed"] == 2
    assert body["onTime"] == 94
    assert body["utilization"] == 75
    assert body["quality"] == 88
    assert body["role"] == "Specialist"  # capitalized TeamRole
    assert body["joined"] == "May 2023"


async def test_me_zero_when_no_metrics(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-lead")  # metrics.scored empty -> ZERO_METRICS fallback
    body = (await client.get("/api/v1/me")).json()
    assert body["activeTasks"] == 0
    assert body["completed"] == 0
    assert body["onTime"] == 0 and body["utilization"] == 0 and body["quality"] == 0


async def test_me_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")  # portal client lacks view_reports
    assert (await client.get("/api/v1/me")).status_code == 403
