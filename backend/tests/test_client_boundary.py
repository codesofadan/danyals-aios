"""P4-2 gate: the client trust boundary in RBAC + auth.

A ``client`` is outside the governance matrix: it holds NO staff permission and
no feature access, and ``get_current_client`` admits ONLY a client that carries a
``client_id`` (staff and client_id-less callers are 403).
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.core.auth import CurrentClient, CurrentUser, get_current_client
from app.rbac import (
    PERM_KEYS,
    STAFF_ROLES,
    feature_allows,
    is_staff_role,
    perms_for_role,
    role_has_perm,
)

pytestmark = pytest.mark.unit

_STAFF_ROLES = ("owner", "admin", "manager", "specialist", "analyst", "viewer")


def _user(role: str, *, client_id: str | None = None) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="x@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="X", title="", avatar_color="#000", phone="", two_fa=False,
        client_id=client_id,
    )


def test_client_holds_no_permission() -> None:
    assert perms_for_role("client") == frozenset()
    for perm in PERM_KEYS:
        assert role_has_perm("client", perm) is False


def test_client_has_no_feature_access() -> None:
    # No grants + not owner => every feature resolves to off.
    for level in ("full", "view"):
        assert feature_allows("client", {}, "reporting", level) is False  # type: ignore[arg-type]


def test_staff_roles_exclude_client() -> None:
    assert "client" not in STAFF_ROLES
    assert set(STAFF_ROLES) == set(_STAFF_ROLES)
    assert is_staff_role("client") is False
    assert all(is_staff_role(r) for r in _STAFF_ROLES)


def test_staff_permissions_unchanged() -> None:
    # Regression guard: the client early-return must not alter staff perms.
    assert role_has_perm("owner", "access_control") is True
    assert role_has_perm("viewer", "view_reports") is True
    assert role_has_perm("viewer", "run_audits") is False
    assert perms_for_role("analyst") == frozenset({"run_audits", "view_reports"})


async def test_get_current_client_admits_scoped_client() -> None:
    scoped = await get_current_client(_user("client", client_id="cl-1"))
    assert isinstance(scoped, CurrentClient)
    assert scoped.client_id == "cl-1"
    assert scoped.user.role == "client"


async def test_get_current_client_rejects_client_without_tenant() -> None:
    with pytest.raises(HTTPException) as exc:
        await get_current_client(_user("client", client_id=None))
    assert exc.value.status_code == 403


@pytest.mark.parametrize("role", _STAFF_ROLES)
async def test_get_current_client_rejects_staff(role: str) -> None:
    with pytest.raises(HTTPException) as exc:
        await get_current_client(_user(role, client_id=None))
    assert exc.value.status_code == 403
