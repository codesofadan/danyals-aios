"""P2-6 gate: activity logging service + feed endpoint.

Covers: log_activity writes a snapshotted row, record_activity is best-effort
(never raises), and the feed returns the frontend ``Activity`` shape.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.activity_repo import get_activity_repo
from app.services.activity import log_activity, record_activity

pytestmark = pytest.mark.unit


class _Exec:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Table:
    def __init__(self, store: list[dict[str, Any]]) -> None:
        self._store = store
        self._payload: Any = None

    def insert(self, row: dict[str, Any]) -> _Table:
        self._payload = row
        return self

    def execute(self) -> _Exec:
        self._store.append(self._payload)
        return _Exec([self._payload])


class _FakeAdmin:
    def __init__(self) -> None:
        self.rows: list[dict[str, Any]] = []

    def table(self, _name: str) -> _Table:
        return _Table(self.rows)


def _user(role: str = "owner") -> CurrentUser:
    return CurrentUser(
        id="u-danyal", email="d@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Danyal Ahmed", title="Founder", avatar_color="#7B69EE", phone="", two_fa=True,
    )


@pytest.mark.unit
def test_log_activity_snapshots_actor() -> None:
    admin = _FakeAdmin()
    log_activity(
        admin,  # type: ignore[arg-type]
        actor_id="u-danyal", actor_name="Danyal Ahmed", actor_color="#7B69EE",
        kind="client", action="created client", target="Verde Cafe",
    )
    row = admin.rows[0]
    assert row["actor_init"] == "DA"  # derived initials
    assert row["kind"] == "client"
    assert row["target"] == "Verde Cafe"


@pytest.mark.unit
async def test_record_activity_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # get_admin_client raising must be swallowed (logging can't break a mutation).
    def _boom() -> Any:
        raise RuntimeError("no supabase")

    monkeypatch.setattr("app.services.activity.get_admin_client", _boom)
    await record_activity(_user(), kind="client", action="created client", target="X")  # no raise


@pytest.mark.unit
async def test_record_activity_writes_via_admin(monkeypatch: pytest.MonkeyPatch) -> None:
    admin = _FakeAdmin()
    monkeypatch.setattr("app.services.activity.get_admin_client", lambda: admin)
    await record_activity(_user(), kind="member", action="provisioned member", target="New Hire", meta="viewer")
    assert admin.rows[0]["action"] == "provisioned member"
    assert admin.rows[0]["meta"] == "viewer"


class _FakeRepo:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self.last_page: tuple[int | None, int] | None = None

    def list_activity(self, limit: int | None = 50, offset: int = 0) -> list[dict[str, Any]]:
        self.last_page = (limit, offset)
        start = offset
        end = None if limit is None else offset + limit
        return self._rows[start:end]


@pytest.fixture
def as_role(app: FastAPI) -> Callable[[str], None]:
    def _set(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _set


async def test_feed_shape(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    row = {
        "id": "a-1", "kind": "audit", "actor_name": "Bilal Anwar", "actor_init": "BA",
        "actor_color": "#1FA890", "action": "started a technical audit", "target": "J-2041",
        "meta": "NorthPeak Dental", "created_at": datetime.now(UTC).isoformat(),
    }
    app.dependency_overrides[get_activity_repo] = lambda: _FakeRepo([row])
    as_role("viewer")
    resp = await client.get("/api/v1/activity")
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["actorName"] == "Bilal Anwar"
    assert body["actorInit"] == "BA"
    assert body["actorColor"] == "#1FA890"
    assert body["kind"] == "audit"
    assert body["meta"] == "NorthPeak Dental"


async def test_feed_requires_auth(client: httpx.AsyncClient) -> None:
    resp = await client.get("/api/v1/activity")
    assert resp.status_code == 401


async def test_feed_default_pagination(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    repo = _FakeRepo([])
    app.dependency_overrides[get_activity_repo] = lambda: repo
    as_role("viewer")
    resp = await client.get("/api/v1/activity")
    assert resp.status_code == 200
    assert repo.last_page == (50, 0)  # hard-cap defaults


async def test_feed_explicit_pagination(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    repo = _FakeRepo([])
    app.dependency_overrides[get_activity_repo] = lambda: repo
    as_role("viewer")
    resp = await client.get("/api/v1/activity", params={"limit": 5, "offset": 10})
    assert resp.status_code == 200
    assert repo.last_page == (5, 10)


async def test_feed_cap_enforcement(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    app.dependency_overrides[get_activity_repo] = lambda: _FakeRepo([])
    as_role("viewer")
    assert (await client.get("/api/v1/activity", params={"limit": 0})).status_code == 422
    assert (await client.get("/api/v1/activity", params={"limit": 201})).status_code == 422
