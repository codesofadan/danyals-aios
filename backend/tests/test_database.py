"""Unit tests for the psycopg seam that need no live database (P6A-3).

Covers the pure, no-network guarantees: UUID validation, the not-configured
paths (missing DSN -> None / clean raise), and the non-raising ``db_ping``
contract when no pool is configured.
"""

from __future__ import annotations

import uuid

import pytest

from app.db.database import (
    DatabaseNotConfiguredError,
    InvalidUserIdError,
    _validate_user_id,
    build_admin_pool,
    build_rls_pool,
    db_ping,
    get_admin_pool,
    get_rls_pool,
)

pytestmark = pytest.mark.unit


def test_validate_user_id_accepts_and_canonicalizes() -> None:
    u = uuid.uuid4()
    # Uppercased input is accepted and returned in canonical lowercase form.
    assert _validate_user_id(str(u).upper()) == str(u)


@pytest.mark.parametrize(
    "bad",
    ["", "not-a-uuid", "123", "'; select set_config('app.user_id','x',true); --", "  "],
)
def test_validate_user_id_rejects_non_uuid(bad: str) -> None:
    with pytest.raises(InvalidUserIdError):
        _validate_user_id(bad)


def test_build_pools_return_none_without_dsn() -> None:
    # A missing DSN is a clean "not configured", never a crash.
    assert build_rls_pool(None) is None
    assert build_rls_pool("") is None
    assert build_admin_pool(None) is None
    assert build_admin_pool("") is None


def test_get_pool_raises_when_unconfigured() -> None:
    # With no pools registered (default module state), the getters raise cleanly.
    with pytest.raises(DatabaseNotConfiguredError):
        get_rls_pool()
    with pytest.raises(DatabaseNotConfiguredError):
        get_admin_pool()


async def test_db_ping_not_configured_is_non_ready_safe() -> None:
    status = await db_ping(None, timeout=1.0)
    assert status.name == "postgres"
    assert status.status == "not_configured"
    assert status.detail is None
