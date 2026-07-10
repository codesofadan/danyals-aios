"""P2-3 gate: JWT verification (JWKS/ES256) + the require_* guards.

Tokens are minted with a throwaway EC key and verified against the matching
public JWK, so nothing here touches a network or a database.
"""

from __future__ import annotations

import json
import time
from types import SimpleNamespace
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from jwt import PyJWK
from jwt.algorithms import ECAlgorithm

from app.core.auth import (
    AuthError,
    CurrentUser,
    JWKSCache,
    decode_and_validate,
    require_feature,
    require_owner,
    require_perm,
    require_role,
)

_ISSUER = "https://proj.supabase.co/auth/v1"
_AUD = "authenticated"
_KID = "test-kid-1"


def _keypair() -> tuple[ec.EllipticCurvePrivateKey, dict[str, Any]]:
    priv = ec.generate_private_key(ec.SECP256R1())
    pub_jwk: dict[str, Any] = json.loads(ECAlgorithm.to_jwk(priv.public_key()))
    pub_jwk.update({"kid": _KID, "alg": "ES256", "use": "sig"})
    return priv, pub_jwk


def _token(priv: ec.EllipticCurvePrivateKey, **over: Any) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": "11111111-1111-1111-1111-111111111111",
        "aud": _AUD,
        "iss": _ISSUER,
        "email": "u@x.com",
        "iat": now,
        "exp": now + 3600,
    }
    payload.update(over)
    return jwt.encode(payload, priv, algorithm="ES256", headers={"kid": _KID})


def _user(role: str = "viewer") -> CurrentUser:
    return CurrentUser(
        id="u1", email="u@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="U", title="", avatar_color="#000", phone="", two_fa=False,
    )


# --- decode_and_validate (pure crypto) ---------------------------------------


@pytest.mark.unit
def test_valid_token_decodes() -> None:
    priv, pub = _keypair()
    key = PyJWK.from_dict(pub).key
    claims = decode_and_validate(_token(priv), key, audience=_AUD, issuer=_ISSUER)
    assert claims["sub"] == "11111111-1111-1111-1111-111111111111"
    assert claims["email"] == "u@x.com"


@pytest.mark.unit
def test_wrong_audience_rejected() -> None:
    priv, pub = _keypair()
    key = PyJWK.from_dict(pub).key
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(_token(priv, aud="other"), key, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_wrong_issuer_rejected() -> None:
    priv, pub = _keypair()
    key = PyJWK.from_dict(pub).key
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(_token(priv, iss="https://evil/"), key, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_expired_token_rejected() -> None:
    priv, pub = _keypair()
    key = PyJWK.from_dict(pub).key
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(_token(priv, exp=int(time.time()) - 10), key, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_signature_from_other_key_rejected() -> None:
    priv, _ = _keypair()
    _, other_pub = _keypair()  # different key
    other_key = PyJWK.from_dict(other_pub).key
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(_token(priv), other_key, audience=_AUD, issuer=_ISSUER)


@pytest.mark.unit
def test_missing_required_claim_rejected() -> None:
    priv, pub = _keypair()
    key = PyJWK.from_dict(pub).key
    # a token without exp fails the require=[...] check
    now = int(time.time())
    token = jwt.encode(
        {"sub": "x", "aud": _AUD, "iss": _ISSUER, "iat": now}, priv, algorithm="ES256", headers={"kid": _KID}
    )
    with pytest.raises(jwt.PyJWTError):
        decode_and_validate(token, key, audience=_AUD, issuer=_ISSUER)


# --- JWKSCache (kid resolution + lazy refresh) -------------------------------


class _FakeResp:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._data


class _FakeHttp:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self.calls = 0

    async def get(self, url: str, timeout: float | None = None) -> _FakeResp:
        self.calls += 1
        return _FakeResp(self._data)


@pytest.mark.unit
async def test_cache_returns_preloaded_key_without_network() -> None:
    priv, pub = _keypair()
    cache = JWKSCache(_ISSUER)
    cache.load_keys({_KID: PyJWK.from_dict(pub)})
    http = _FakeHttp({"keys": []})
    key = await cache.signing_key(_token(priv), http)  # type: ignore[arg-type]
    assert key.key_id == _KID
    assert http.calls == 0  # no refresh needed


@pytest.mark.unit
async def test_cache_refreshes_on_unknown_kid() -> None:
    priv, pub = _keypair()
    cache = JWKSCache(_ISSUER)  # empty; must fetch
    http = _FakeHttp({"keys": [pub]})
    key = await cache.signing_key(_token(priv), http)  # type: ignore[arg-type]
    assert key.key_id == _KID
    assert http.calls == 1


@pytest.mark.unit
async def test_cache_raises_when_kid_absent_after_refresh() -> None:
    priv, _ = _keypair()
    cache = JWKSCache(_ISSUER)
    http = _FakeHttp({"keys": []})  # refresh yields nothing
    with pytest.raises(AuthError):
        await cache.signing_key(_token(priv), http)  # type: ignore[arg-type]


@pytest.mark.unit
async def test_cache_rejects_token_without_kid() -> None:
    priv, _ = _keypair()
    cache = JWKSCache(_ISSUER)
    token = jwt.encode({"sub": "x"}, priv, algorithm="ES256")  # no kid header
    with pytest.raises(AuthError):
        await cache.signing_key(token, _FakeHttp({"keys": []}))  # type: ignore[arg-type]


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
    # owner never touches the DB loader
    assert await dep(req, _user("owner"))  # type: ignore[arg-type]


@pytest.mark.unit
async def test_require_feature_consults_grants(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.core.auth._load_feature_grants", lambda uid, tok: {"technical_audit": "full"}
    )
    dep = require_feature("technical_audit")
    req = SimpleNamespace(state=SimpleNamespace(access_token="tok"))
    assert await dep(req, _user("specialist"))  # type: ignore[arg-type]

    dep2 = require_feature("billing")  # not granted -> 403
    with pytest.raises(HTTPException):
        await dep2(req, _user("specialist"))  # type: ignore[arg-type]
