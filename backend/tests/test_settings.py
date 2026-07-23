"""Unit tests for the Settings module: the three response shapes (WorkspaceSettings
/ SecurityPolicy / NotifPref keys + aliases), the defaults fallback, the per-event
merge, and the /settings endpoints with a faked repo - owner/admin gate on the
agency singletons, per-user notif prefs, and the OWNER-ONLY danger zone. No DB.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.settings_repo import get_settings_repo
from app.schemas.settings import (
    NOTIF_EVENTS,
    NotifPrefResponse,
    SecurityPolicyResponse,
    WorkspaceSettingsResponse,
    is_notif_key,
)

pytestmark = pytest.mark.unit

_REPO_ROOT = Path(__file__).resolve().parents[2]

_WORKSPACE_KEYS = {
    "agencyName", "supportEmail", "timezone", "language",
    "weekStart", "defaultTier", "brandColor",
}
_SECURITY_KEYS = {
    "enforce2FA", "strongPasswords", "minPassLength", "rotationDays",
    "sessionTimeout", "singleSession", "ipAllowlist", "auditLogging",
}
_NOTIF_KEYS = {"key", "label", "desc", "icon", "email", "inApp"}


def _emitted(model: type) -> set[str]:
    return {
        f.serialization_alias or f.alias or name
        for name, f in model.model_fields.items()
    }


# --- schema shape -------------------------------------------------------------

def test_workspace_emits_exactly_the_contract_keys() -> None:
    assert _emitted(WorkspaceSettingsResponse) == _WORKSPACE_KEYS


def test_security_emits_exactly_the_contract_keys() -> None:
    assert _emitted(SecurityPolicyResponse) == _SECURITY_KEYS


def test_notifpref_emits_exactly_the_contract_keys() -> None:
    # NotifPref is a SINGLE-LINE union-free object in data.ts (the shared contract
    # lock only parses multi-line types), so pin it here directly.
    assert _emitted(NotifPrefResponse) == _NOTIF_KEYS


def test_notifpref_matches_frontend_type_keys() -> None:
    src = (_REPO_ROOT / "frontend/lib/data.ts").read_text(encoding="utf-8")
    match = re.search(r"export type NotifPref\s*=\s*\{(.*?)\};", src, re.DOTALL)
    assert match
    ts_keys = set(re.findall(r"(\w+)\s*:", match.group(1)))
    assert ts_keys == _NOTIF_KEYS


def test_workspace_from_row_falls_back_to_defaults() -> None:
    resp = WorkspaceSettingsResponse.from_row(None).model_dump(by_alias=True)
    assert set(resp) == _WORKSPACE_KEYS
    assert resp["agencyName"] == "Xegents AI"
    assert resp["weekStart"] == "Monday"
    assert resp["defaultTier"] == "Growth"
    assert resp["brandColor"] == "#7B69EE"


def test_workspace_from_row_rejects_bad_enum_values() -> None:
    resp = WorkspaceSettingsResponse.from_row({"week_start": "Tuesday", "default_tier": "Mega"})
    assert resp.week_start == "Monday"
    assert resp.default_tier == "Growth"


def test_security_from_row_falls_back_to_defaults() -> None:
    resp = SecurityPolicyResponse.from_row(None).model_dump(by_alias=True)
    assert set(resp) == _SECURITY_KEYS
    assert resp["enforce2FA"] is True
    assert resp["minPassLength"] == 12
    assert resp["rotationDays"] == 90
    assert resp["singleSession"] is False


def test_security_from_row_reads_stored_values() -> None:
    resp = SecurityPolicyResponse.from_row(
        {"enforce_2fa": False, "min_pass_length": 16, "single_session": True}
    )
    assert resp.enforce_2fa is False
    assert resp.min_pass_length == 16
    assert resp.single_session is True
    assert resp.audit_logging is True  # unspecified -> default


def test_notif_merge_returns_all_events_with_defaults() -> None:
    prefs = NotifPrefResponse.merged({})
    assert len(prefs) == len(NOTIF_EVENTS)
    by_key = {p.key: p for p in prefs}
    # The assignment/onboarding events email by default (wired into task/member/
    # portal provisioning) so an assignee is actually told work landed.
    assert by_key["task_assigned"].email is True
    assert by_key["member_welcome"].email is True
    assert by_key["portal_ready"].email is True
    # past_due default is email on, in-app off (data.ts notificationDefaults).
    assert by_key["past_due"].email is True
    assert by_key["past_due"].in_app is False
    # member_login default is email off, in-app on.
    assert by_key["member_login"].email is False
    assert by_key["member_login"].in_app is True


def test_notif_merge_applies_user_overrides() -> None:
    prefs = NotifPrefResponse.merged({"audit_done": {"email": False, "in_app": False}})
    audit = next(p for p in prefs if p.key == "audit_done")
    assert audit.email is False and audit.in_app is False


def test_is_notif_key_guards_unknown_events() -> None:
    assert is_notif_key("audit_done")
    assert not is_notif_key("not_a_real_event")


# --- endpoints (faked repo) ---------------------------------------------------

class FakeSettingsRepo:
    def __init__(self) -> None:
        self.workspace: dict[str, Any] = {"id": 1}
        self.security: dict[str, Any] = {"id": 1}
        self.notif: dict[str, dict[str, Any]] = {}
        self.upserts: list[tuple[str, bool, bool]] = []
        self.purged = False

    def get_workspace(self) -> dict[str, Any]:
        return self.workspace

    def get_security(self) -> dict[str, Any]:
        return self.security

    def update_workspace(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.workspace.update(changes)
        return self.workspace

    def update_security(self, changes: dict[str, Any]) -> dict[str, Any]:
        self.security.update(changes)
        return self.security

    def list_notif_prefs(self) -> list[dict[str, Any]]:
        return [{"event_key": k, **v} for k, v in self.notif.items()]

    def upsert_notif_pref(self, event_key: str, *, email: bool, in_app: bool) -> dict[str, Any]:
        self.notif[event_key] = {"email": email, "in_app": in_app}
        self.upserts.append((event_key, email, in_app))
        return {"event_key": event_key, "email": email, "in_app": in_app}

    def purge_activity(self) -> int:
        self.purged = True
        return 42


def _user(role: str, uid: str = "u-1") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


@pytest.fixture
def repo() -> FakeSettingsRepo:
    return FakeSettingsRepo()


@pytest.fixture
def wire(app: FastAPI, repo: FakeSettingsRepo) -> Callable[..., None]:
    app.dependency_overrides[get_settings_repo] = lambda: repo

    def _as(role: str, uid: str = "u-1") -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role, uid)

    return _as


# workspace + security: owner/admin only

async def test_workspace_get_forbidden_for_manager(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("manager", "u-mgr")
    assert (await client.get("/api/v1/settings/workspace")).status_code == 403


async def test_workspace_get_ok_for_admin(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    resp = await client.get("/api/v1/settings/workspace")
    assert resp.status_code == 200
    assert set(resp.json()) == _WORKSPACE_KEYS


async def test_workspace_put_updates_provided_fields(
    client: httpx.AsyncClient, repo: FakeSettingsRepo, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    resp = await client.put(
        "/api/v1/settings/workspace",
        json={"agencyName": "New Co", "defaultTier": "Scale"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["agencyName"] == "New Co"
    assert body["defaultTier"] == "Scale"
    # snake_case DB columns are what reach the repo (alias resolved server-side).
    assert repo.workspace["agency_name"] == "New Co"
    assert repo.workspace["default_tier"] == "Scale"


async def test_security_put_forbidden_for_viewer(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer", "u-v")
    resp = await client.put("/api/v1/settings/security", json={"enforce2FA": False})
    assert resp.status_code == 403


async def test_security_put_updates(
    client: httpx.AsyncClient, repo: FakeSettingsRepo, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    resp = await client.put(
        "/api/v1/settings/security", json={"minPassLength": 16, "singleSession": True}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["minPassLength"] == 16
    assert body["singleSession"] is True
    assert repo.security["min_pass_length"] == 16


async def test_security_put_rejects_out_of_range_length(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    resp = await client.put("/api/v1/settings/security", json={"minPassLength": 4})
    assert resp.status_code == 422


# notification prefs: per-user (any staff), client excluded

async def test_notifications_client_forbidden(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")
    assert (await client.get("/api/v1/settings/notifications")).status_code == 403


async def test_notifications_get_returns_all_events(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("viewer", "u-v")  # any staff manages their OWN prefs
    body = (await client.get("/api/v1/settings/notifications")).json()
    assert len(body) == len(NOTIF_EVENTS)
    assert set(body[0]) == _NOTIF_KEYS


async def test_notifications_put_upserts_known_ignores_unknown(
    client: httpx.AsyncClient, repo: FakeSettingsRepo, wire: Callable[..., None]
) -> None:
    wire("specialist", "u-spec")
    resp = await client.put(
        "/api/v1/settings/notifications",
        json={"prefs": [
            {"key": "audit_done", "email": False, "inApp": True},
            {"key": "bogus_event", "email": True, "inApp": True},  # ignored
        ]},
    )
    assert resp.status_code == 200
    assert [u[0] for u in repo.upserts] == ["audit_done"]  # unknown key skipped
    audit = next(p for p in resp.json() if p["key"] == "audit_done")
    assert audit["email"] is False and audit["inApp"] is True


# danger zone: owner-only

async def test_reset_forbidden_for_admin(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")  # danger zone is owner-only, admin is not enough
    assert (await client.post("/api/v1/settings/danger/reset")).status_code == 403


async def test_reset_restores_defaults_for_owner(
    client: httpx.AsyncClient, repo: FakeSettingsRepo, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    resp = await client.post("/api/v1/settings/danger/reset")
    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace"]["agencyName"] == "Xegents AI"
    assert body["security"]["minPassLength"] == 12
    assert repo.workspace["agency_name"] == "Xegents AI"


async def test_purge_activity_forbidden_for_admin(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("admin", "u-admin")
    assert (await client.post("/api/v1/settings/danger/purge-activity")).status_code == 403


async def test_purge_activity_owner_only(
    client: httpx.AsyncClient, repo: FakeSettingsRepo, wire: Callable[..., None]
) -> None:
    wire("owner", "u-owner")
    resp = await client.post("/api/v1/settings/danger/purge-activity")
    assert resp.status_code == 200
    assert resp.json()["purged"] == 42
    assert repo.purged is True
