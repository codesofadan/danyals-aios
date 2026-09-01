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
from app.core.deps import get_redis
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
        lambda _caller, _target: {"technical_audit": "view"},
    )
    resp = await client.get("/api/v1/me/grants")
    assert resp.status_code == 200
    grants = resp.json()["grants"]
    assert grants["technical_audit"] == "view"
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
#
# The route must go through `login_credentials.set_password` — the ONE writer that
# moves the argon2id hash and the sealed reveal copy together — and must then end
# the sessions the old password opened. It previously did neither: a private
# `update auth.users set password_hash` left Team Management showing the PREVIOUS
# password, and the bearer token that the compromised password had already minted
# kept working for its full multi-day life. Both admin-driven rotations already
# behaved correctly, so the self-service path was the odd one out.
#
# `set_password` is faked here to keep this a unit test; that it really writes both
# facts is pinned at the source in tests/test_login_credentials.py.


class FakeRedis:
    """Records the revocation epoch `revoke_all_for_user` writes."""

    def __init__(self) -> None:
        self.sets: list[tuple[str, str, int | None]] = []

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.sets.append((key, value, ex))


@pytest.fixture
def redis(app: FastAPI) -> FakeRedis:
    fake = FakeRedis()
    app.dependency_overrides[get_redis] = lambda: fake
    return fake


@pytest.fixture
def set_pw(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """Capture (user_id, plaintext) reaching the shared credential writer."""
    seen: list[tuple[str, str]] = []

    def _set(uid: str, plaintext: str) -> bool:
        seen.append((uid, plaintext))
        return True

    monkeypatch.setattr("app.routers.me.set_password", _set)
    return seen


def _pin_current_password(monkeypatch: pytest.MonkeyPatch, plaintext: str) -> None:
    from app.services.passwords import hash_password

    real_hash = hash_password(plaintext)
    monkeypatch.setattr("app.routers.me._lookup_own_password_hash", lambda _uid: real_hash)


async def test_change_password_wrong_current_is_rejected(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
    set_pw: list[tuple[str, str]], redis: FakeRedis,
) -> None:
    _pin_current_password(monkeypatch, "correct-horse-battery")
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "wrong-password", "new_password": "brand-new-pw123"},
    )
    assert resp.status_code == 400
    assert set_pw == []  # never wrote a new password
    assert redis.sets == []  # and never ended anyone's sessions


async def test_change_password_writes_through_the_shared_credential_writer(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
    set_pw: list[tuple[str, str]], redis: FakeRedis,
) -> None:
    """The PLAINTEXT must reach `set_password`, not a hash computed here.

    Hashing in the router is exactly how the two facts drifted apart: only
    `set_password` can also re-seal the recoverable copy, and it needs the
    plaintext to do it.
    """
    _pin_current_password(monkeypatch, "correct-horse-battery")
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "correct-horse-battery", "new_password": "brand-new-pw123"},
    )
    assert resp.status_code == 204
    assert set_pw == [("u-1", "brand-new-pw123")]


async def test_changing_your_own_password_ends_every_session(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
    set_pw: list[tuple[str, str]], redis: FakeRedis,
) -> None:
    """Someone changing a password BECAUSE it was stolen must not leave the thief
    signed in. A bearer token never re-checks the password, so only the per-user
    revocation epoch closes those sessions."""
    _pin_current_password(monkeypatch, "correct-horse-battery")
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "correct-horse-battery", "new_password": "brand-new-pw123"},
    )
    assert resp.status_code == 204
    assert len(redis.sets) == 1
    key, _epoch, ttl = redis.sets[0]
    assert "u-1" in key
    assert ttl is not None and ttl > 0


async def test_password_change_survives_an_unreachable_redis(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
    app: FastAPI, set_pw: list[tuple[str, str]],
) -> None:
    """Best-effort by contract, as in both admin rotations: the password has ALREADY
    changed in Postgres, so a 5xx here would tell the caller it had not."""

    class BrokenRedis:
        async def set(self, *_a: object, **_k: object) -> None:
            raise ConnectionError("redis down")

    app.dependency_overrides[get_redis] = lambda: BrokenRedis()
    _pin_current_password(monkeypatch, "correct-horse-battery")
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "correct-horse-battery", "new_password": "brand-new-pw123"},
    )
    assert resp.status_code == 204
    assert set_pw == [("u-1", "brand-new-pw123")]


async def test_change_password_404s_when_the_account_vanished(
    client: httpx.AsyncClient, wire: Callable[..., None], monkeypatch: pytest.MonkeyPatch,
    redis: FakeRedis,
) -> None:
    """`set_password` returning False means no `auth.users` row. Report it rather
    than 204-ing a change that did not land."""
    _pin_current_password(monkeypatch, "correct-horse-battery")
    monkeypatch.setattr("app.routers.me.set_password", lambda _uid, _pw: False)
    wire("specialist", "u-1")
    resp = await client.post(
        "/api/v1/me/password",
        json={"current_password": "correct-horse-battery", "new_password": "brand-new-pw123"},
    )
    assert resp.status_code == 404
    assert redis.sets == []


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
