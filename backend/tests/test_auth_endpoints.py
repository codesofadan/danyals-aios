"""P2-3 gate: auth-gated endpoints (RBAC reference + user provisioning).

``get_current_user`` is overridden so these exercise routing + RBAC guards +
response shapes without a real Supabase or token.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user

pytestmark = pytest.mark.unit


def _user(role: str = "owner") -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op Erator", title="Founder", avatar_color="#7B69EE", phone="", two_fa=True,
    )


@pytest.fixture
def as_role(app: FastAPI) -> Callable[[str], None]:
    """Override the current user to a given role for this app instance."""

    def _set(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _set


# --- auth requirement --------------------------------------------------------


async def test_rbac_requires_auth(client: httpx.AsyncClient) -> None:
    # No override, no bearer token -> 401.
    resp = await client.get("/api/v1/rbac/features")
    assert resp.status_code == 401


# --- RBAC reference shapes ---------------------------------------------------


async def test_features_shape(client: httpx.AsyncClient, as_role: Callable[[str], None]) -> None:
    as_role("viewer")
    resp = await client.get("/api/v1/rbac/features")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 17
    assert {"key", "label", "short", "icon", "group", "desc"} <= body[0].keys()
    assert {f["group"] for f in body} == {"Analytics", "Content", "Delivery", "Admin"}


async def test_permissions_shape(client: httpx.AsyncClient, as_role: Callable[[str], None]) -> None:
    as_role("viewer")
    resp = await client.get("/api/v1/rbac/permissions")
    assert resp.status_code == 200
    assert len(resp.json()) == 8


async def test_roles_shape(client: httpx.AsyncClient, as_role: Callable[[str], None]) -> None:
    as_role("viewer")
    resp = await client.get("/api/v1/rbac/roles")
    assert resp.status_code == 200
    roles = resp.json()
    assert [r["role"] for r in roles] == ["Owner", "Admin", "Manager", "Specialist", "Analyst", "Viewer"]
    owner = next(r for r in roles if r["role"] == "Owner")
    assert len(owner["permissions"]) == 8


async def test_templates_shape(client: httpx.AsyncClient, as_role: Callable[[str], None]) -> None:
    as_role("viewer")
    resp = await client.get("/api/v1/rbac/templates")
    assert resp.status_code == 200
    tpls = {t["key"]: t for t in resp.json()}
    assert set(tpls) == {"seo", "content", "va", "super"}
    assert len(tpls["super"]["grants"]) == 17
    assert tpls["super"]["role"] == "Owner"


# --- provisioning ------------------------------------------------------------

_CANNED_ROW = {
    "id": "uid-9",
    "email": "new@x.com",
    "name": "New Person",
    "role": "viewer",
    "status": "invited",
    "title": "",
    "avatar_color": "#7B69EE",
    "created_at": "2026-07-11T00:00:00+00:00",
}


def _stub_provisioning(monkeypatch: pytest.MonkeyPatch, row: dict[str, Any] | None = None) -> None:
    monkeypatch.setattr("app.routers.admin_users.get_admin_client", lambda: object())
    monkeypatch.setattr(
        "app.routers.admin_users.provision_user", lambda *a, **k: dict(row or _CANNED_ROW)
    )


async def test_provision_as_owner_returns_member_shape(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("owner")
    _stub_provisioning(monkeypatch)
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": "new@x.com", "name": "New Person", "password": "secret12", "role": "viewer"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["role"] == "Viewer"  # capitalized TeamRole
    assert body["init"] == "NP"
    assert body["activeTasks"] == 0  # camelCase serialization alias
    assert body["status"] == "invited"


async def test_provision_requires_manage_team(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("viewer")  # no manage_team
    _stub_provisioning(monkeypatch)
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": "new@x.com", "name": "New Person", "password": "secret12", "role": "viewer"},
    )
    assert resp.status_code == 403


async def test_non_owner_cannot_create_elevated_role(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("admin")  # admin has manage_team but is not owner
    _stub_provisioning(monkeypatch)
    resp = await client.post(
        "/api/v1/admin/users",
        json={"email": "boss@x.com", "name": "Big Boss", "password": "secret12", "role": "admin"},
    )
    assert resp.status_code == 403


async def test_list_users_as_owner(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("owner")
    monkeypatch.setattr(
        "app.routers.admin_users._fetch_all_users",
        lambda token, **_kw: [dict(_CANNED_ROW)],
    )
    resp = await client.get("/api/v1/admin/users")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["role"] == "Viewer"
