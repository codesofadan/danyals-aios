"""P4-3 gate: client-login provisioning + the staff-roster filter.

Covers D9 (clients are excluded from ``/admin/users``) and the owner-only
``POST /clients/{id}/portal-users`` endpoint (RBAC, unknown-client 404, and the
happy path pinning role='client' + client_id from the path).
"""

from __future__ import annotations

import contextlib
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


def test_roster_query_excludes_clients(monkeypatch: pytest.MonkeyPatch) -> None:
    """The roster read issues the ``role <> 'client'`` filter in SQL (not in Python)
    and returns the cursor's rows unchanged.

    The exclusion is now enforced by the DB query itself; that it truly filters
    is proven live in ``tests/integration/test_repo_sql_parity.py``. Here we lock
    the seam: ``_fetch_all_users`` binds the caller as the RLS identity and runs
    the staff-only, client-excluding, created_at-ordered query.
    """
    from app.routers import admin_users

    captured: dict[str, Any] = {}
    staff_rows = [{"id": "s1", "role": "admin", "name": "Staffer"}]

    class _FakeCur:
        def execute(self, query: Any, params: Any = None) -> None:
            captured["query"] = str(query)
            captured["params"] = params

        def fetchall(self) -> list[dict[str, Any]]:
            return staff_rows

    @contextlib.contextmanager
    def _fake_conn(user_id: str) -> Any:
        captured["user_id"] = user_id
        yield _FakeCur()

    monkeypatch.setattr(admin_users, "rls_connection", _fake_conn)
    fetched = admin_users._fetch_all_users("u-1")

    assert fetched == staff_rows  # passthrough; no Python-side filtering
    assert captured["user_id"] == "u-1"  # caller bound as the RLS identity
    assert "role <> 'client'" in captured["query"]
    assert "order by created_at" in captured["query"]


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
