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


# --- GET /me/grants: self-serve, no access_control needed --------------------


async def test_my_grants_self_serve_no_access_control_permission_needed(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    # specialist holds view_reports but NOT access_control — GET /admin/users/{id}/grants
    # would 403 here; GET /me/grants must not (that was the whole bug being fixed).
    wire("specialist", "u-1")
    monkeypatch.setattr(
        "app.routers.admin_users._read_grant_overrides",
        lambda _caller, _target: {"rank_tracker": "view"},
    )
    resp = await client.get("/api/v1/me/grants")
    assert resp.status_code == 200
    grants = resp.json()["grants"]
    assert grants["rank_tracker"] == "view"
    assert grants["billing"] == "off"  # ungranted -> off


async def test_my_grants_scoped_to_caller_both_args(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, tuple[str, str]] = {}

    def _record(caller: str, target: str) -> dict[str, str]:
        seen["ids"] = (caller, target)
        return {}

    wire("analyst", "u-9")
    monkeypatch.setattr("app.routers.admin_users._read_grant_overrides", _record)
    await client.get("/api/v1/me/grants")
    # Never a path/query param — always the verified token's own id, both places.
    assert seen["ids"] == ("u-9", "u-9")


async def test_my_grants_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")
    assert (await client.get("/api/v1/me/grants")).status_code == 403


# --- PATCH /me: self-serve profile edit --------------------------------------


@pytest.fixture(autouse=True)
def _silence_me_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr("app.routers.me.record_activity", _noop)


async def test_update_me_writes_only_provided_fields(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.routers.me._update_own_profile",
        lambda uid, changes: calls.append((uid, changes)),
    )
    wire("specialist", "u-1")
    resp = await client.patch("/api/v1/me", json={"name": "New Name"})
    assert resp.status_code == 200
    assert calls == [("u-1", {"name": "New Name"})]  # title/email NOT included
    assert resp.json()["role"] == "Specialist"  # still the full MemberResponse shape


async def test_update_me_empty_body_writes_nothing(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr("app.routers.me._update_own_profile", lambda *a: calls.append(a))
    wire("specialist", "u-1")
    resp = await client.patch("/api/v1/me", json={})
    assert resp.status_code == 200
    assert calls == []  # no fields provided -> no write at all


async def test_update_me_never_accepts_role_or_id(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    monkeypatch.setattr(
        "app.routers.me._update_own_profile",
        lambda uid, changes: calls.append((uid, changes)),
    )
    wire("specialist", "u-1")
    # A role/id in the body is silently ignored (UpdateMeRequest has no such fields).
    resp = await client.patch("/api/v1/me", json={"name": "X", "role": "owner", "id": "u-owner"})
    assert resp.status_code == 200
    assert calls == [("u-1", {"name": "X"})]


async def test_update_me_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")
    assert (await client.patch("/api/v1/me", json={"name": "X"})).status_code == 403


# --- POST /me/password: self-serve password change ---------------------------


async def test_change_password_wrong_current_is_rejected(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.passwords import hash_password

    real_hash = hash_password("correct-horse-battery")
    monkeypatch.setattr("app.routers.me._lookup_own_password_hash", lambda _uid: real_hash)
    stored: list[str] = []
    monkeypatch.setattr(
        "app.routers.me._set_own_password", lambda _uid, new_hash: stored.append(new_hash)
    )
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "wrong-password", "new_password": "brand-new-pw123"},
    )
    assert resp.status_code == 400
    assert stored == []  # never wrote a new hash


async def test_change_password_success_stores_verifiable_argon2_hash(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.passwords import hash_password, verify_password

    real_hash = hash_password("correct-horse-battery")
    monkeypatch.setattr("app.routers.me._lookup_own_password_hash", lambda _uid: real_hash)
    stored: list[str] = []
    monkeypatch.setattr(
        "app.routers.me._set_own_password", lambda _uid, new_hash: stored.append(new_hash)
    )
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "correct-horse-battery", "new_password": "brand-new-pw123"},
    )
    assert resp.status_code == 204
    assert len(stored) == 1
    assert stored[0].startswith("$argon2id$")
    assert "brand-new-pw123" not in stored[0]  # never the plaintext
    assert verify_password(stored[0], "brand-new-pw123") is True


async def test_change_password_rejects_short_new_password(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "whatever", "new_password": "short"},
    )
    assert resp.status_code == 422  # min_length=8, rejected before any lookup


async def test_change_password_forbidden_for_client(
    client: httpx.AsyncClient, wire: Callable[..., None]
) -> None:
    wire("client")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "x", "new_password": "brand-new-pw123"},
    )
    assert resp.status_code == 403
