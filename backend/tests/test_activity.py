"""P2-6 gate: activity logging service + feed endpoint.

Covers: log_activity writes a snapshotted row, record_activity is best-effort
(never raises), and the feed returns the frontend ``Activity`` shape.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.activity_repo import get_activity_repo
from app.services.activity import log_activity, record_activity

pytestmark = pytest.mark.unit


class _FakeCursor:
    """Captures the (query, params) of each ``execute`` so a test can assert on
    the snapshotted row without a real privileged connection."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, Any]] = []

    def execute(self, query: Any, params: Any = None) -> None:
        self.calls.append((query, params))


@contextmanager
def _fake_privileged(cur: _FakeCursor) -> Iterator[_FakeCursor]:
    """Stand-in for ``privileged_connection()`` that yields a capturing cursor."""
    yield cur


def _user(role: str = "owner") -> CurrentUser:
    return CurrentUser(
        id="u-danyal", email="d@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Danyal Ahmed", title="Founder", avatar_color="#7B69EE", phone="", two_fa=True,
    )


@pytest.mark.unit
def test_log_activity_snapshots_actor(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor()
    monkeypatch.setattr(
        "app.services.activity.privileged_connection", lambda: _fake_privileged(cur)
    )
    log_activity(
        actor_id="u-danyal", actor_name="Danyal Ahmed", actor_color="#7B69EE",
        kind="client", action="created client", target="Verde Cafe",
    )
    _query, params = cur.calls[0]
    assert params["actor_init"] == "DA"  # derived initials
    assert params["kind"] == "client"
    assert params["target"] == "Verde Cafe"


@pytest.mark.unit
async def test_record_activity_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    # An unreachable/unconfigured privileged pool raises, and it must be swallowed
    # (logging can't break the mutation it records).
    def _boom() -> Any:
        raise RuntimeError("no privileged pool")

    monkeypatch.setattr("app.services.activity.privileged_connection", _boom)
    await record_activity(_user(), kind="client", action="created client", target="X")  # no raise


@pytest.mark.unit
async def test_record_activity_writes_via_privileged(monkeypatch: pytest.MonkeyPatch) -> None:
    cur = _FakeCursor()
    monkeypatch.setattr(
        "app.services.activity.privileged_connection", lambda: _fake_privileged(cur)
    )
    await record_activity(_user(), kind="member", action="provisioned member", target="New Hire", meta="viewer")
    _query, params = cur.calls[0]
    assert params["action"] == "provisioned member"
    assert params["meta"] == "viewer"


@pytest.mark.unit
async def test_record_activity_threads_entity_link(monkeypatch: pytest.MonkeyPatch) -> None:
    # A linked event carries entity_type/entity_id into the INSERT (the trigger
    # then coalesces it into context_dirty). The enum is cast in SQL.
    cur = _FakeCursor()
    monkeypatch.setattr(
        "app.services.activity.privileged_connection", lambda: _fake_privileged(cur)
    )
    await record_activity(
        _user(), kind="client", action="created client", target="Verde Cafe",
        entity_type="client", entity_id="c-123",
    )
    query, params = cur.calls[0]
    assert "entity_type" in query and "entity_id" in query
    assert "::public.context_entity" in query  # enum cast so a text bind assigns
    assert params["entity_type"] == "client"
    assert params["entity_id"] == "c-123"


@pytest.mark.unit
async def test_record_activity_unlinked_event_passes_nulls(monkeypatch: pytest.MonkeyPatch) -> None:
    # An unlinked event (no concrete entity) still writes, with NULL entity cols;
    # the trigger ignores it. The params are present and None (never omitted).
    cur = _FakeCursor()
    monkeypatch.setattr(
        "app.services.activity.privileged_connection", lambda: _fake_privileged(cur)
    )
    await record_activity(_user(), kind="access", action="changed the cost dial", target="context")
    _query, params = cur.calls[0]
    assert params["entity_type"] is None
    assert params["entity_id"] is None


@pytest.mark.unit
async def test_record_activity_never_raises_with_entity(monkeypatch: pytest.MonkeyPatch) -> None:
    # Passing entity params must not change the never-raises contract when the
    # privileged pool is unreachable (a bad/unknown entity can't break a mutation).
    def _boom() -> Any:
        raise RuntimeError("no privileged pool")

    monkeypatch.setattr("app.services.activity.privileged_connection", _boom)
    await record_activity(
        _user(), kind="client", action="created client", target="X",
        entity_type="client", entity_id="not-a-real-uuid",
    )  # no raise


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
