"""P4-3 gate: client-login provisioning + the staff-roster filter.

Covers D9 (clients are excluded from ``/admin/users``) and the owner-only
``POST /clients/{id}/portal-users`` endpoint (RBAC, unknown-client 404, and the
happy path pinning role='client' + client_id from the path).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.clients_repo import get_clients_repo

pytestmark = pytest.mark.unit


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


# --- D9: the roster query filters out clients --------------------------------


class _RosterTable:
    """Records the query chain and applies a .neq filter over seeded rows."""

    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows
        self._excl: tuple[str, str] | None = None

    def select(self, *_cols: str) -> _RosterTable:
        return self

    def neq(self, key: str, value: str) -> _RosterTable:
        self._excl = (key, value)
        return self

    def order(self, _key: str) -> _RosterTable:
        return self

    def execute(self) -> Any:
        data = self._rows
        if self._excl:
            k, v = self._excl
            data = [r for r in data if str(r.get(k)) != v]
        return type("R", (), {"data": list(data)})()


def test_roster_excludes_client_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.routers import admin_users

    rows = [
        {"id": "s1", "role": "admin", "name": "Staffer"},
        {"id": "c1", "role": "client", "name": "Portal Login"},
    ]

    class _FakeClient:
        def table(self, _name: str) -> _RosterTable:
            return _RosterTable(rows)

    monkeypatch.setattr(admin_users, "client_for_user", lambda _t: _FakeClient())
    fetched = admin_users._fetch_all_users("tok")
    assert [r["id"] for r in fetched] == ["s1"]
    assert all(r["role"] != "client" for r in fetched)


# --- Owner-only portal-user endpoint -----------------------------------------


class _FakeClientsRepo:
    def __init__(self, exists: bool = True) -> None:
        self.exists = exists

    def get_client(self, client_id: str) -> dict[str, Any] | None:
        return {"id": client_id, "name": "Acme"} if self.exists else None


@pytest.fixture
def wire(app: FastAPI) -> Any:
    def _as(role: str, *, client_exists: bool = True) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)
        app.dependency_overrides[get_clients_repo] = lambda: _FakeClientsRepo(client_exists)

    return _as


async def test_portal_user_requires_owner(client: httpx.AsyncClient, wire: Any) -> None:
    wire("admin")  # manage_team but not owner
    resp = await client.post(
        "/api/v1/clients/cl-1/portal-users",
        json={"email": "p@acme.com", "name": "P", "password": "secret12"},
    )
    assert resp.status_code == 403


async def test_portal_user_unknown_client_404(client: httpx.AsyncClient, wire: Any) -> None:
    wire("owner", client_exists=False)
    resp = await client.post(
        "/api/v1/clients/nope/portal-users",
        json={"email": "p@acme.com", "name": "P", "password": "secret12"},
    )
    assert resp.status_code == 404


async def test_portal_user_happy_path_pins_tenant(
    client: httpx.AsyncClient, wire: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.routers import clients as clients_router

    calls: dict[str, Any] = {}

    def _fake_provision(_admin: Any, **kwargs: Any) -> dict[str, Any]:
        calls.update(kwargs)
        return {
            "id": "u-new", "email": kwargs["email"], "name": kwargs["name"],
            "role": "client", "status": "invited", "avatar_color": "#000",
            "client_id": kwargs["client_id"], "created_at": "2026-07-14T00:00:00Z",
        }

    monkeypatch.setattr(clients_router, "get_admin_client", lambda: object())
    monkeypatch.setattr(clients_router, "provision_user", _fake_provision)
    wire("owner")

    resp = await client.post(
        "/api/v1/clients/cl-acme/portal-users",
        json={"email": "p@acme.com", "name": "Portal", "password": "secret12"},
    )
    assert resp.status_code == 201, resp.text
    # Role is fixed to client and client_id is pinned from the PATH, not the body.
    assert calls["role"] == "client"
    assert calls["client_id"] == "cl-acme"
    body = resp.json()
    assert body["role"] == "Client"
