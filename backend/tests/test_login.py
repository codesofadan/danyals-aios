"""P6A-7 gate: the local login endpoint + argon2 + token issuance.

Drives ``POST /api/v1/auth/login`` through the real app with a test keypair and a
faked credential lookup (no DB), asserting: role -> portal is server-authoritative,
a good password yields a verifiable EdDSA token, and BOTH an unknown username and
a wrong password return the same generic 401 (no user enumeration).
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.core.auth import decode_and_validate
from app.routers import auth as auth_router
from app.routers.auth import _PORTAL_BY_ROLE
from app.services.passwords import hash_password, verify_password
from app.services.tokens import TokenSigningNotConfiguredError, issue_access_token

pytestmark = pytest.mark.unit


def _keypair() -> tuple[str, str]:
    priv = Ed25519PrivateKey.generate()
    priv_pem = priv.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()
    pub_pem = (
        priv.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return priv_pem, pub_pem


@pytest.fixture
def keyed(app: FastAPI) -> tuple[FastAPI, Settings]:
    """The app with a live test keypair wired into settings (login can sign)."""
    priv, pub = _keypair()
    settings = Settings(
        _env_file=None,
        app_env="dev",
        jwt_private_key=priv.replace("\n", "\\n"),
        jwt_public_key=pub.replace("\n", "\\n"),
    )
    app.dependency_overrides[get_settings] = lambda: settings
    return app, settings


# --- argon2 password hashing --------------------------------------------------


def test_argon2_hash_and_verify_round_trip() -> None:
    h = hash_password("correct horse battery staple")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "correct horse battery staple") is True
    assert verify_password(h, "wrong password") is False


def test_verify_password_never_raises_on_garbage_hash() -> None:
    assert verify_password("not-a-hash", "whatever") is False
    assert verify_password("", "whatever") is False


# --- token issuance -----------------------------------------------------------


def test_issue_access_token_without_key_raises() -> None:
    settings = Settings(_env_file=None, app_env="dev")  # no JWT_PRIVATE_KEY
    with pytest.raises(TokenSigningNotConfiguredError):
        issue_access_token(str(uuid4()), "owner", settings=settings)


# --- role -> portal mapping (server-authoritative) ----------------------------


@pytest.mark.parametrize(
    ("role", "portal"),
    [
        ("owner", "admin"),
        ("admin", "admin"),
        ("manager", "team"),
        ("specialist", "team"),
        ("analyst", "team"),
        ("viewer", "team"),
        ("client", "client"),
    ],
)
def test_role_maps_to_portal(role: str, portal: str) -> None:
    assert _PORTAL_BY_ROLE[role] == portal


# --- login endpoint -----------------------------------------------------------


def _wire_lookup(monkeypatch: pytest.MonkeyPatch, row: dict[str, Any] | None) -> None:
    monkeypatch.setattr(auth_router, "_lookup_credentials", lambda username: row)


async def test_login_success_returns_verifiable_token(
    keyed: tuple[FastAPI, Settings], client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _app, settings = keyed
    uid = str(uuid4())
    _wire_lookup(
        monkeypatch,
        {"id": uid, "role": "manager", "password_hash": hash_password("s3cret-pw")},
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "MgrUser", "password": "s3cret-pw"}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "manager"
    assert body["portal"] == "team"  # server-decided from the role
    claims = decode_and_validate(
        body["access_token"],
        settings.jwt_public_key_pem,
        audience=settings.jwt_audience,
        issuer=settings.local_jwt_issuer,
    )
    assert claims["sub"] == uid
    assert claims["role"] == "manager"


async def test_login_client_role_routes_to_client_portal(
    keyed: tuple[FastAPI, Settings], client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_lookup(
        monkeypatch,
        {"id": str(uuid4()), "role": "client", "password_hash": hash_password("pw12345")},
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "acme", "password": "pw12345"}
    )
    assert resp.status_code == 200
    assert resp.json()["portal"] == "client"


async def test_unknown_username_generic_401(
    keyed: tuple[FastAPI, Settings], client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_lookup(monkeypatch, None)  # no such user
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "ghost", "password": "whatever1"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Invalid credentials"


async def test_wrong_password_generic_401(
    keyed: tuple[FastAPI, Settings], client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _wire_lookup(
        monkeypatch,
        {"id": str(uuid4()), "role": "owner", "password_hash": hash_password("right-pw")},
    )
    resp = await client.post(
        "/api/v1/auth/login", json={"username": "owner", "password": "wrong-pw"}
    )
    assert resp.status_code == 401
    assert resp.json()["error"]["message"] == "Invalid credentials"
