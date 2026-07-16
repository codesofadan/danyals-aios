"""P6A-7 gate: local EdDSA JWT verification + the require_* guards.

Tokens are minted with a throwaway Ed25519 keypair and verified against the
matching public key, so nothing here touches a network or a database. The
negative-security cases are the point of this file: a forged token, an expired
token, the wrong issuer/audience, and (critically) the alg-confusion / ``none``
attacks must ALL be rejected by the fixed ``["EdDSA"]`` allow-list.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

from app.core.auth import (
    CurrentUser,
    decode_and_validate,
    require_feature,
    require_owner,
    require_perm,
    require_role,
)

_ISSUER = "aios"
_AUD = "authenticated"


def _keypair() -> tuple[str, str]:
    """Return (private_pem, public_pem) for a fresh Ed25519 keypair."""
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


def _token(priv_pem: str, **over: Any) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "aud": _AUD,
        "iss": _ISSUER,
        "role": "viewer",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(over)
    return jwt.encode(payload, priv_pem, algorithm="EdDSA")


def _user(role: str = "viewer") -> CurrentUser:
    return CurrentUser(
        id="u1", email="u@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="U", title="", avatar_color="#000", phone="", two_fa=False,
    )


# --- decode_and_validate: happy path -----------------------------------------


@pytest.mark.unit
def test_valid_token_decodes() -> None:
    priv, pub = _keypair()
    claims = decode_and_validate(_token(priv), pub, audience=_AUD, issuer=_ISSUER)
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["role"] == "viewer"


@pytest.mark.unit
def test_issue_then_verify_round_trip() -> None:
    """A token minted by app.services.tokens verifies under the same public key."""
    from app.config import Settings
    from app.services.tokens import issue_access_token

    priv, pub = _keypair()
    settings = Settings(
        _env_file=None,
        jwt_private_key=priv.replace("\n", "\\n"),
        jwt_public_key=pub.replace("\n", "\\n"),
    )
    token = issue_access_token("22222222-2222-2222-2222-222222222222", "admin", settings=settings)
    claims = decode_and_validate(
        token, settings.jwt_public_key_pem, audience=_AUD, issuer=_ISSUER
    )
    assert claims["sub"] == "22222222-2222-2222-2222-222222222222"
    assert claims["role"] == "admin"


# --- decode_and_validate: negative security ----------------------------------


@pytest.mark.unit
def test_wrong_audience_rejected() -> None:
    priv, pub = _keypair()
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(_token(priv, aud="other"), pub, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_wrong_issuer_rejected() -> None:
    priv, pub = _keypair()
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(_token(priv, iss="evil"), pub, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_expired_token_rejected() -> None:
    priv, pub = _keypair()
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(
            _token(priv, exp=int(time.time()) - 10), pub, audience=_AUD, issuer=_ISSUER
        )


@pytest.mark.unit
def test_forged_token_signed_with_other_key_rejected() -> None:
    """A token signed by a DIFFERENT private key must fail signature verification."""
    priv, _ = _keypair()
    _, other_pub = _keypair()  # verify against a key that did NOT sign it
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(_token(priv), other_pub, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_missing_required_claim_rejected() -> None:
    priv, pub = _keypair()
    now = int(time.time())
    # No exp -> the options={"require":["exp",...]} check fails.
    token = jwt.encode(
        {"sub": "x", "aud": _AUD, "iss": _ISSUER, "iat": now}, priv, algorithm="EdDSA"
    )
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(token, pub, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_alg_none_rejected() -> None:
    """An unsigned ``alg=none`` token must be rejected by the allow-list."""
    now = int(time.time())
    payload = {"sub": "x", "aud": _AUD, "iss": _ISSUER, "exp": now + 3600, "iat": now}
    # PyJWT emits an unsigned token when key is None + algorithm="none".
    none_token = jwt.encode(payload, None, algorithm="none")  # type: ignore[arg-type]
    _, pub = _keypair()
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(none_token, pub, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_alg_confusion_hs256_with_public_key_rejected() -> None:
    """The classic attack: sign HS256 using the PUBLIC key BYTES as the HMAC secret.

    A verifier that allowed HS256 would accept it (it "knows" the public key). We
    hand-craft the token (PyJWT's own encode refuses a PEM as an HMAC secret), so
    the token really IS validly HS256-signed - and our fixed ["EdDSA"] allow-list
    still rejects it on its ``alg`` before any key material is used.
    """
    import base64
    import hashlib
    import hmac
    import json

    _priv, pub = _keypair()
    now = int(time.time())
    payload = {"sub": "x", "aud": _AUD, "iss": _ISSUER, "exp": now + 3600, "iat": now}

    def _b64(raw: bytes) -> bytes:
        return base64.urlsafe_b64encode(raw).rstrip(b"=")

    header = _b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    body = _b64(json.dumps(payload).encode())
    signing_input = header + b"." + body
    sig = _b64(hmac.new(pub.encode(), signing_input, hashlib.sha256).digest())
    forged = (signing_input + b"." + sig).decode()

    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(forged, pub, audience=_AUD, issuer=_ISSUER)


# --- require_* guards --------------------------------------------------------


@pytest.mark.unit
async def test_require_perm_allows_and_denies() -> None:
    dep = require_perm("manage_vault")
    assert (await dep(_user("owner"))).is_owner
    with pytest.raises(HTTPException) as exc:
        await dep(_user("viewer"))
    assert exc.value.status_code == 403


@pytest.mark.unit
async def test_require_role_owner_always_passes() -> None:
    dep = require_role("admin", "manager")
    assert await dep(_user("owner"))  # owner bypasses
    assert await dep(_user("manager"))
    with pytest.raises(HTTPException):
        await dep(_user("viewer"))


@pytest.mark.unit
async def test_require_owner() -> None:
    dep = require_owner()
    assert await dep(_user("owner"))
    with pytest.raises(HTTPException):
        await dep(_user("admin"))


@pytest.mark.unit
async def test_require_feature_owner_short_circuits() -> None:
    dep = require_feature("billing")
    req = SimpleNamespace(state=SimpleNamespace(access_token="tok"))
    assert await dep(req, _user("owner"))  # type: ignore[arg-type]


@pytest.mark.unit
async def test_require_feature_consults_grants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda uid: {"technical_audit": "full"}
    )
    dep = require_feature("technical_audit")
    req = SimpleNamespace(state=SimpleNamespace(access_token="tok"))
    assert await dep(req, _user("specialist"))  # type: ignore[arg-type]

    dep2 = require_feature("billing")  # not granted -> 403
    with pytest.raises(HTTPException):
        await dep2(req, _user("specialist"))  # type: ignore[arg-type]
