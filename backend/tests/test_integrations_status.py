"""Wave 6: API-Management integration status (the real connected/missing catalogue).

Proves the status is computed from REAL config + vault presence (never a hard-coded
checkmark): keyless -> everything missing; a set key -> connected; a two-part
credential needs BOTH halves; a vault-kind is connected only when its provider slug is
present. Also the endpoint's manage_vault gate. The integrations router is mounted onto
the test app here (it is registered centrally in a RESERVED file).
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.routers import integrations
from app.services.integrations_status import integration_statuses

pytestmark = pytest.mark.unit

_STATUS_FIELDS = {"id", "name", "category", "connected", "source", "detail"}


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


# --- pure catalogue ------------------------------------------------------------
def test_all_missing_when_keyless() -> None:
    out = {i.id: i for i in integration_statuses(_settings(), [])}
    assert out["serper"].connected is False
    assert out["resend"].connected is False
    assert out["anthropic"].connected is False
    assert out["wordpress"].connected is False
    assert out["wordpress"].source == "vault"
    assert out["serper"].source == "config"
    # every entry carries a non-secret "how to connect" detail
    assert all(i.detail for i in out.values())


def test_connected_from_config_key() -> None:
    out = {i.id: i for i in integration_statuses(_settings(serper_api_key="k", resend_api_key="k"), [])}
    assert out["serper"].connected is True
    assert out["resend"].connected is True
    assert out["anthropic"].connected is False  # still unset


def test_two_part_credential_needs_both_halves() -> None:
    only_login = {i.id: i for i in integration_statuses(_settings(dataforseo_login="u"), [])}
    assert only_login["dataforseo"].connected is False
    both = {
        i.id: i
        for i in integration_statuses(_settings(dataforseo_login="u", dataforseo_password="p"), [])
    }
    assert both["dataforseo"].connected is True


def test_vault_presence_drives_client_kinds() -> None:
    out = {i.id: i for i in integration_statuses(_settings(), ["wordpress", "gbp"])}
    assert out["wordpress"].connected is True
    assert out["gbp"].connected is True
    assert out["analytics"].connected is False  # not in the vault set


# --- endpoint (manage_vault) ---------------------------------------------------
def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture(autouse=True)
def _mount(app: FastAPI) -> None:
    app.include_router(integrations.router, prefix="/api/v1")


async def test_endpoint_owner_ok_shape(client: httpx.AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_current_user] = lambda: _user("owner")
    resp = await client.get("/api/v1/integrations")
    assert resp.status_code == 200
    body = resp.json()
    assert any(i["id"] == "resend" for i in body)
    assert all(set(i) == _STATUS_FIELDS for i in body)


async def test_endpoint_forbidden_for_non_manager(client: httpx.AsyncClient, app: FastAPI) -> None:
    app.dependency_overrides[get_current_user] = lambda: _user("specialist")  # no manage_vault
    assert (await client.get("/api/v1/integrations")).status_code == 403


async def test_endpoint_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/integrations")).status_code == 401
