"""P6A-6 gate: Key Vault - app-layer AES-256-GCM sealing + owner-only reveal.

Secrets are sealed with AESGCM under a master key held only in env. A masked list
never carries a secret; only the super-admin reveal opens one. These unit tests
exercise the crypto core with an injected master key (no DB) + the router with the
service functions faked; the SQL round-trip is proven in the integration suite.
"""

from __future__ import annotations

import base64
import logging
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from app.core.auth import CurrentUser, get_current_user
from app.db.vault_repo import get_vault_repo
from app.schemas.vault import compute_status
from app.services import vault as vault_svc
from app.services.vault import (
    VaultNotConfiguredError,
    VaultSecretError,
    _open,
    _seal,
    mask_secret,
)

pytestmark = pytest.mark.unit

_REAL = "serper-live-9f2a4c7b8e1d3f0b"


def _b64_key() -> str:
    return base64.b64encode(os.urandom(32)).decode()


class _Settings:
    """Minimal stand-in for ``get_settings()`` carrying just the master key."""

    def __init__(self, master_key: str | None) -> None:
        self.vault_master_key = SecretStr(master_key) if master_key is not None else None


@pytest.fixture
def master_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """Pin a fresh, valid 32-byte master key onto the vault service's settings."""
    key = _b64_key()
    monkeypatch.setattr(vault_svc, "get_settings", lambda: _Settings(key))
    return key


# --- mask + status -----------------------------------------------------------


def test_mask_secret_matches_frontend() -> None:
    assert mask_secret(_REAL) == "serper••••••••3f0b"
    assert mask_secret("short") == "sh••••••••hort"
    assert mask_secret("  ") == ""


def test_compute_status_thresholds() -> None:
    now = datetime.now(UTC)
    assert compute_status(now.isoformat()) == "active"
    assert compute_status(now.replace(year=now.year - 1).isoformat()) == "rotate"


# --- seal / open crypto core -------------------------------------------------


def test_seal_open_round_trips(master_key: str) -> None:
    sealed = _seal(_REAL)
    assert isinstance(sealed, bytes)
    assert sealed[:12] != sealed[12:24]  # a random nonce leads the blob
    assert _REAL.encode() not in sealed  # plaintext is not present in the ciphertext
    assert _open(sealed) == _REAL


def test_seal_uses_a_fresh_nonce_each_time(master_key: str) -> None:
    a, b = _seal(_REAL), _seal(_REAL)
    assert a != b  # distinct random nonces -> distinct ciphertexts for the same input
    assert _open(a) == _open(b) == _REAL


def test_tampered_ciphertext_raises_no_leak(master_key: str) -> None:
    sealed = bytearray(_seal(_REAL))
    sealed[-1] ^= 0x01  # flip a bit in the GCM tag
    with pytest.raises(VaultSecretError):
        _open(bytes(sealed))


def test_short_blob_raises(master_key: str) -> None:
    with pytest.raises(VaultSecretError):
        _open(b"tooshort")


def test_wrong_master_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_svc, "get_settings", lambda: _Settings(_b64_key()))
    sealed = _seal(_REAL)
    monkeypatch.setattr(vault_svc, "get_settings", lambda: _Settings(_b64_key()))  # different key
    with pytest.raises(VaultSecretError):
        _open(sealed)


def test_unset_master_key_raises_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(vault_svc, "get_settings", lambda: _Settings(None))
    with pytest.raises(VaultNotConfiguredError):
        _seal(_REAL)


def test_malformed_master_key_raises_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    # valid base64 but the wrong length (16 bytes, not 32) -> not configured, not a crash
    monkeypatch.setattr(
        vault_svc, "get_settings", lambda: _Settings(base64.b64encode(os.urandom(16)).decode())
    )
    with pytest.raises(VaultNotConfiguredError):
        _seal(_REAL)


def test_nothing_secret_in_logs(master_key: str, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        sealed = _seal(_REAL)
        assert _open(sealed) == _REAL
    assert _REAL not in caplog.text
    assert master_key not in caplog.text


def test_error_repr_carries_no_plaintext(master_key: str) -> None:
    sealed = bytearray(_seal(_REAL))
    sealed[-1] ^= 0x01
    try:
        _open(bytes(sealed))
    except VaultSecretError as exc:
        assert _REAL not in str(exc) and _REAL not in repr(exc)


# --- service add/rotate/reveal over a fake privileged_connection -------------


class _Cur:
    """A tiny cursor fake covering vault.py's INSERT ... returning path (add_key)."""

    def __init__(self, store: dict[str, dict[str, Any]]) -> None:
        self._store = store
        self._row: dict[str, Any] | None = None

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        assert sql.strip().lower().startswith("insert")  # add_key is the only unit path
        provider, label, masked, sealed, key_version, created_by = params
        key_id = f"vk-{len(self._store) + 1}"
        self._store[key_id] = {
            "id": key_id, "provider": provider, "label": label, "masked": masked,
            "secret_sealed": bytes(sealed), "key_version": key_version,
            "created_by": created_by, "created_at": datetime.now(UTC),
        }
        self._row = {
            k: self._store[key_id][k] for k in ("id", "provider", "label", "masked", "created_at")
        }

    def fetchone(self) -> dict[str, Any] | None:
        return self._row


@pytest.fixture
def fake_conn(monkeypatch: pytest.MonkeyPatch, master_key: str) -> Iterator[dict[str, dict[str, Any]]]:
    store: dict[str, dict[str, Any]] = {}

    class _Ctx:
        def __enter__(self) -> _Cur:
            return _Cur(store)

        def __exit__(self, *_a: Any) -> None:
            return None

    monkeypatch.setattr(vault_svc, "privileged_connection", lambda: _Ctx())
    yield store


def test_add_seals_secret_not_plaintext(fake_conn: dict[str, dict[str, Any]]) -> None:
    row = vault_svc.add_key(provider="serper", label="Prod", secret=_REAL, created_by=None)
    assert row["masked"] == "serper••••••••3f0b"
    assert _REAL not in str(row)  # response is masked metadata only
    stored = next(iter(fake_conn.values()))
    assert stored["secret_sealed"] != _REAL.encode()  # column holds sealed bytes, not plaintext
    assert _open(stored["secret_sealed"]) == _REAL  # ... which decrypt back to the original


# --- endpoints ---------------------------------------------------------------


def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="00000000-0000-0000-0000-000000000001", email="op@x.com", role=role,  # type: ignore[arg-type]
        status="active", name="Op", title="", avatar_color="#000", phone="", two_fa=False,
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
        "created_at": datetime.now(UTC).isoformat(),
    }
    app.dependency_overrides[get_vault_repo] = lambda: _FakeRepo([row])
    as_role("admin")  # admin has manage_vault
    resp = await client.get("/api/v1/vault/keys")
    assert resp.status_code == 200
    body = resp.json()[0]
    assert body["masked"] == "serper••••••••3f0b"
    assert body["secret"] == ""  # masked list never carries a secret


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
        "created_at": datetime.now(UTC).isoformat(),
    }
    monkeypatch.setattr("app.routers.vault.add_key", lambda **k: dict(meta))
    as_role("admin")
    resp = await client.post(
        "/api/v1/vault/keys",
        json={"provider": "serper", "label": "Prod", "secret": _REAL},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["secret"] == ""
    assert _REAL not in resp.text


async def test_add_key_503_when_vault_unconfigured(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
    def _boom(**_k: Any) -> dict[str, Any]:
        raise VaultNotConfiguredError("VAULT_MASTER_KEY is not configured")

    monkeypatch.setattr("app.routers.vault.add_key", _boom)
    as_role("admin")
    resp = await client.post(
        "/api/v1/vault/keys", json={"provider": "serper", "label": "Prod", "secret": _REAL}
    )
    assert resp.status_code == 503


async def test_reveal_is_owner_only(
    client: httpx.AsyncClient, as_role: Callable[[str], None], monkeypatch: pytest.MonkeyPatch
) -> None:
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
    monkeypatch.setattr("app.routers.vault.reveal_secret", lambda *a, **k: None)
    as_role("owner")
    resp = await client.get("/api/v1/vault/keys/missing/reveal")
    assert resp.status_code == 404
