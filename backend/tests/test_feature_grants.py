"""7F-4 gate: feature-grant editing (RBAC + owner lock + validation) and the
Add-Member credential-generation invite flow.

``get_current_user`` is overridden per-role; the grant read/write helpers and
``provision_user`` are monkeypatched so these exercise routing + guards + shapes
without a database. The argon2-in-DB assertion runs the REAL ``provision_user``
against a recording cursor so the stored credential is inspected end to end.
"""

from __future__ import annotations

import contextlib
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.rbac import FEATURE_KEYS
from app.services import provisioning
from app.services.passwords import verify_password

pytestmark = pytest.mark.unit


def _user(role: str = "owner", uid: str = "u-owner") -> CurrentUser:
    return CurrentUser(
        id=uid, email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op Erator", title="Founder", avatar_color="#7B69EE", phone="", two_fa=True,
    )


@pytest.fixture
def as_role(app: FastAPI) -> Callable[[str], None]:
    def _set(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _set


@pytest.fixture(autouse=True)
def _silence_activity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _noop(*_a: Any, **_k: Any) -> None:
        return None

    monkeypatch.setattr("app.routers.admin_users.record_activity", _noop)


# --- GET grants --------------------------------------------------------------


async def test_get_grants_resolves_all_17_for_specialist(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("owner")
    monkeypatch.setattr(
        "app.routers.admin_users._load_user_min",
        lambda _caller, uid: {"id": uid, "role": "specialist"},
    )
    monkeypatch.setattr(
        "app.routers.admin_users._read_grant_overrides",
        lambda _caller, _uid: {"rank_tracker": "view"},
    )
    resp = await client.get("/api/v1/admin/users/u-2/grants")
    assert resp.status_code == 200
    grants = resp.json()["grants"]
    assert len(grants) == len(FEATURE_KEYS)  # all 17 keys resolved
    assert grants["rank_tracker"] == "view"
    assert grants["billing"] == "off"  # ungranted -> off


async def test_get_grants_owner_is_all_full(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("owner")
    monkeypatch.setattr(
        "app.routers.admin_users._load_user_min",
        lambda _caller, uid: {"id": uid, "role": "owner"},
    )
    monkeypatch.setattr(
        "app.routers.admin_users._read_grant_overrides", lambda _caller, _uid: {}
    )
    grants = (await client.get("/api/v1/admin/users/u-owner/grants")).json()["grants"]
    assert set(grants.values()) == {"full"}  # owner all-on and locked


async def test_get_grants_404_when_missing(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("owner")
    monkeypatch.setattr(
        "app.routers.admin_users._load_user_min", lambda _caller, _uid: None
    )
    assert (await client.get("/api/v1/admin/users/nope/grants")).status_code == 404


# --- PUT grants: RBAC + owner lock + validation ------------------------------


async def test_put_grants_requires_access_control(
    client: httpx.AsyncClient, as_role: Callable[[str], None]
) -> None:
    # admin holds manage_team but NOT access_control (owner-only by the matrix).
    as_role("admin")
    resp = await client.put(
        "/api/v1/admin/users/u-2/grants", json={"grants": {"rank_tracker": "full"}}
    )
    assert resp.status_code == 403


async def test_put_grants_owner_target_is_locked(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("owner")
    monkeypatch.setattr(
        "app.routers.admin_users._load_user_min",
        lambda _caller, uid: {"id": uid, "role": "owner"},
    )
    resp = await client.put(
        "/api/v1/admin/users/u-owner/grants", json={"grants": {"rank_tracker": "off"}}
    )
    assert resp.status_code == 400
    assert "all-on" in resp.json()["error"]["message"]  # {"error": {...}} envelope


async def test_put_grants_rejects_unknown_feature_key(
    client: httpx.AsyncClient, as_role: Callable[[str], None]
) -> None:
    as_role("owner")
    resp = await client.put(
        "/api/v1/admin/users/u-2/grants", json={"grants": {"not_a_feature": "full"}}
    )
    assert resp.status_code == 422  # schema validator rejects before any write


async def test_put_grants_writes_and_reads_back(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    as_role("owner")
    store: dict[str, str] = {}
    monkeypatch.setattr(
        "app.routers.admin_users._load_user_min",
        lambda _caller, uid: {"id": uid, "role": "specialist"},
    )
    monkeypatch.setattr(
        "app.routers.admin_users._write_grant_overrides",
        lambda _uid, grants: store.update(grants),
    )
    monkeypatch.setattr(
        "app.routers.admin_users._read_grant_overrides", lambda _caller, _uid: dict(store)
    )
    resp = await client.put(
        "/api/v1/admin/users/u-2/grants",
        json={"grants": {"rank_tracker": "full", "reporting": "view"}},
    )
    assert resp.status_code == 200
    assert store == {"rank_tracker": "full", "reporting": "view"}
    grants = resp.json()["grants"]
    assert grants["rank_tracker"] == "full" and grants["reporting"] == "view"
    assert grants["billing"] == "off"


# --- Add-Member invite: credential generation --------------------------------


class _RecordingCursor:
    """Captures execute/executemany and serves the read-back row (see provisioning)."""

    def __init__(self) -> None:
        self.executes: list[tuple[str, Any]] = []
        self.many: list[tuple[str, list[Any]]] = []
        self._row: dict[str, Any] | None = None

    def execute(self, query: Any, params: Any = None) -> None:
        q = str(query)
        self.executes.append((q, params))
        if "insert into public.users" in q:
            uid, email, username, name, role, title, color, must_reset, must_2fa, client_id = params
            self._row = {
                "id": uid, "email": email, "username": username, "name": name,
                "role": role, "title": title, "avatar_color": color, "status": "invited",
                "must_reset": must_reset, "must_setup_2fa": must_2fa, "client_id": client_id,
            }

    def executemany(self, query: Any, seq: Any) -> None:
        self.many.append((str(query), list(seq)))

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


@pytest.fixture
def rec_cursor(monkeypatch: pytest.MonkeyPatch) -> _RecordingCursor:
    recorder = _RecordingCursor()

    @contextlib.contextmanager
    def _fake_priv() -> Any:
        yield recorder

    # Patch where provision_user looks it up so the REAL provisioning runs.
    monkeypatch.setattr(provisioning, "privileged_connection", _fake_priv)
    return recorder


async def test_invite_generates_credentials_and_argon2_hash(
    client: httpx.AsyncClient,
    as_role: Callable[[str], None],
    rec_cursor: _RecordingCursor,
) -> None:
    as_role("owner")
    resp = await client.post(
        "/api/v1/admin/users/invite",
        json={"email": "ali@x.com", "name": "Ali Hassan", "role": "specialist",
              "template": "content"},
    )
    assert resp.status_code == 201
    body = resp.json()
    # Credentials returned ONCE: a derived username + the plaintext temp password.
    assert body["username"] == "ali.hassan"
    temp = body["tempPassword"]
    assert temp and isinstance(temp, str)
    assert body["member"]["role"] == "Specialist"

    # The stored credential is an argon2id hash of the plaintext (never plaintext).
    auth_insert = next(e for e in rec_cursor.executes if "insert into auth.users" in e[0])
    _uid, email, password_hash = auth_insert[1]
    assert email == "ali@x.com"
    assert password_hash.startswith("$argon2id$")
    assert temp not in password_hash
    assert verify_password(password_hash, temp) is True

    # First-login onboarding flags are stamped on the identity row.
    users_insert = next(e for e in rec_cursor.executes if "insert into public.users" in e[0])
    *_, must_reset, must_2fa, _client = users_insert[1]
    assert must_reset is True and must_2fa is True

    # The "content" template seeded that template's feature grants.
    assert rec_cursor.many, "expected template feature grants to be seeded"
    assert len(rec_cursor.many[0][1]) == 9  # Content Creator template = 9 features


async def test_invite_custom_features_seed_explicit_grants(
    client: httpx.AsyncClient,
    as_role: Callable[[str], None],
    rec_cursor: _RecordingCursor,
) -> None:
    as_role("owner")
    resp = await client.post(
        "/api/v1/admin/users/invite",
        json={"email": "sam@x.com", "name": "Sam Vale", "role": "analyst",
              "features": ["rank_tracker", "reporting"]},
    )
    assert resp.status_code == 201
    seeded = {(k, lvl) for _uid, k, lvl in rec_cursor.many[0][1]}
    assert seeded == {("rank_tracker", "full"), ("reporting", "full")}


async def test_invite_requires_manage_team(
    client: httpx.AsyncClient, as_role: Callable[[str], None]
) -> None:
    as_role("viewer")  # no manage_team
    resp = await client.post(
        "/api/v1/admin/users/invite", json={"email": "x@x.com", "name": "No One"}
    )
    assert resp.status_code == 403


async def test_invite_non_owner_cannot_mint_admin(
    client: httpx.AsyncClient, as_role: Callable[[str], None]
) -> None:
    as_role("admin")  # has manage_team but is not owner
    resp = await client.post(
        "/api/v1/admin/users/invite",
        json={"email": "boss@x.com", "name": "Big Boss", "role": "admin"},
    )
    assert resp.status_code == 403


async def test_invite_rejects_unknown_template(
    client: httpx.AsyncClient, as_role: Callable[[str], None]
) -> None:
    as_role("owner")
    resp = await client.post(
        "/api/v1/admin/users/invite",
        json={"email": "x@x.com", "name": "Who", "template": "wizard"},
    )
    assert resp.status_code == 422
