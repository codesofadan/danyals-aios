"""P2-5 gate: Key Vault - masking, service ops, and owner-only reveal.

A masked list never carries a secret; only the super-admin reveal returns one.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.core.auth import CurrentUser, get_current_user
from app.db.vault_repo import get_vault_repo
from app.schemas.vault import compute_status
from app.services.vault import add_key, mask_secret, reveal_secret, rotate_key

pytestmark = pytest.mark.unit

_REAL = "serper-live-9f2a4c7b8e1d3f0b"


# --- fakes -------------------------------------------------------------------


class _Exec:
    def __init__(self, data: Any) -> None:
        self.data = data


class _RPC:
    """supabase-py .rpc(...) returns a builder; .execute() yields the result."""

    def __init__(self, data: Any) -> None:
        self._data = data

    def execute(self) -> _Exec:
        return _Exec(self._data)


class _Table:
    def __init__(self, store: dict[str, list[dict[str, Any]]], name: str) -> None:
        self._rows = store.setdefault(name, [])
        self._name = name
        self._mode: str | None = None
        self._payload: Any = None
        self._filter: tuple[str, str] | None = None

    def insert(self, rows: Any) -> _Table:
        self._mode = "insert"
        self._payload = rows if isinstance(rows, list) else [rows]
        return self

    def update(self, row: dict[str, Any]) -> _Table:
        self._mode = "update"
        self._payload = row
        return self

    def select(self, *_c: str) -> _Table:
        self._mode = "select"
        return self

    def eq(self, key: str, value: str) -> _Table:
        self._filter = (key, str(value))
        return self

    def limit(self, _n: int) -> _Table:
        return self

    def order(self, _k: str) -> _Table:
        return self

    def _match(self, r: dict[str, Any]) -> bool:
        if not self._filter:
            return True
        key, value = self._filter
        return str(r.get(key)) == value

    def execute(self) -> _Exec:
        if self._mode == "insert":
            out = []
            for row in self._payload:
                rec = dict(row)
                rec.setdefault("id", f"{self._name}-{len(self._rows) + 1}")
                self._rows.append(rec)
                out.append(rec)
            return _Exec(out)
        if self._mode == "select":
            return _Exec([r for r in self._rows if self._match(r)])
        if self._mode == "update":
            hit = [r for r in self._rows if self._match(r)]
            for r in hit:
                r.update(self._payload)
            return _Exec(hit)
        return _Exec([])


class _FakeAdmin:
    def __init__(self) -> None:
        self.store: dict[str, list[dict[str, Any]]] = {}
        self.secrets: dict[str, str] = {}

    def rpc(self, name: str, params: dict[str, Any]) -> _RPC:
        if name == "vault_create_secret":
            sid = f"sec-{len(self.secrets) + 1}"
            self.secrets[sid] = params["p_secret"]
            return _RPC(sid)
        if name == "vault_update_secret":
            self.secrets[params["p_id"]] = params["p_secret"]
            return _RPC(None)
        if name == "vault_reveal_secret":
            return _RPC(self.secrets.get(params["p_id"]))
        return _RPC(None)

    def table(self, name: str) -> _Table:
        return _Table(self.store, name)


# --- mask + status -----------------------------------------------------------


@pytest.mark.unit
def test_mask_secret_matches_frontend() -> None:
    assert mask_secret(_REAL) == "serper••••••••3f0b"
    assert mask_secret("short") == "sh••••••••hort"
    assert mask_secret("  ") == ""


@pytest.mark.unit
def test_compute_status_thresholds() -> None:
    now = datetime.now(UTC)
    assert compute_status(now.isoformat()) == "active"
    assert compute_status(now.replace(year=now.year - 1).isoformat()) == "rotate"


# --- service -----------------------------------------------------------------


@pytest.mark.unit
def test_add_stores_secret_in_vault_not_metadata() -> None:
    admin = _FakeAdmin()
    row = add_key(admin, provider="serper", label="Prod", secret=_REAL)  # type: ignore[arg-type]
    assert row["masked"] == "serper••••••••3f0b"
    assert admin.secrets[row["secret_id"]] == _REAL  # raw only in the vault
    assert _REAL not in str(row)  # never in the metadata row


@pytest.mark.unit
def test_rotate_replaces_secret_and_mask() -> None:
    admin = _FakeAdmin()
    row = add_key(admin, provider="serper", label="Prod", secret=_REAL)  # type: ignore[arg-type]
    new = "serper-live-ROTATED0000abcd"
    updated = rotate_key(admin, row["id"], new)
    assert updated is not None
    assert updated["masked"] == mask_secret(new)
    assert admin.secrets[row["secret_id"]] == new
    assert rotate_key(admin, "missing", new) is None


@pytest.mark.unit
def test_reveal_returns_secret_or_none() -> None:
    admin = _FakeAdmin()
    row = add_key(admin, provider="serper", label="Prod", secret=_REAL)  # type: ignore[arg-type]
    assert reveal_secret(admin, row["id"]) == _REAL
    assert reveal_secret(admin, "missing") is None


# --- endpoints ---------------------------------------------------------------


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


class _FakeRepo:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def list_keys(self) -> list[dict[str, Any]]:
        return self._rows


@pytest.fixture
def as_role(app: FastAPI) -> Callable[[str], None]:
    def _set(role: str) -> None:
        app.dependency_overrides[get_current_user] = lambda: _user(role)

    return _set


async def test_list_masked_never_has_secret(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    row = {
        "id": "k1", "provider": "serper", "label": "Prod", "masked": "serper••••••••3f0b",
        "scope": "Agency-global", "site": None, "rotated_at": datetime.now(UTC).isoformat(),
    }
    app.dependency_overrides[get_vault_repo] = lambda: _FakeRepo([row])
    as_role("admin")  # admin has manage_vault
    resp = await client.get("/api/v1/vault/keys")
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["masked"] == "serper••••••••3f0b"
    assert body["secret"] == ""  # masked list never carries a secret
    assert body["status"] == "active"


async def test_list_requires_manage_vault(
    client: httpx.AsyncClient, app: FastAPI, as_role: Callable[[str], None]
) -> None:
    app.dependency_overrides[get_vault_repo] = lambda: _FakeRepo([])
    as_role("manager")  # manager lacks manage_vault
    resp = await client.get("/api/v1/vault/keys")
    assert resp.status_code == 403


async def test_add_key_does_not_echo_secret(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    meta = {
        "id": "k9", "provider": "serper", "label": "Prod", "masked": "serper••••••••3f0b",
        "scope": "Agency-global", "site": None, "secret_id": "sec-1",
        "rotated_at": datetime.now(UTC).isoformat(),
    }
    monkeypatch.setattr("app.routers.vault.get_admin_client", lambda: object())
    monkeypatch.setattr("app.routers.vault.add_key", lambda *a, **k: dict(meta))
    as_role("admin")
    resp = await client.post(
        "/api/v1/vault/keys",
        json={"provider": "serper", "label": "Prod", "secret": _REAL},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["secret"] == ""
    assert _REAL not in resp.text


async def test_reveal_is_owner_only(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.routers.vault.get_admin_client", lambda: object())
    monkeypatch.setattr("app.routers.vault.reveal_secret", lambda *a, **k: _REAL)
    # admin has manage_vault but is NOT owner -> forbidden
    as_role("admin")
    denied = await client.get("/api/v1/vault/keys/k1/reveal")
    assert denied.status_code == 403
    # owner may reveal
    as_role("owner")
    ok = await client.get("/api/v1/vault/keys/k1/reveal")
    assert ok.status_code == 200
    assert ok.json()["secret"] == _REAL


async def test_reveal_404_when_missing(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.routers.vault.get_admin_client", lambda: object())
    monkeypatch.setattr("app.routers.vault.reveal_secret", lambda *a, **k: None)
    as_role("owner")
    resp = await client.get("/api/v1/vault/keys/missing/reveal")
    assert resp.status_code == 404
