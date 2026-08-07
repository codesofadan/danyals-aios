"""Google Indexing seam: settings gating, the JWT-bearer publish flow, non-raising.

NO real network: the SA-JWT token exchange + the publish call both run against an
``httpx.MockTransport``. A throwaway RSA keypair is generated in-test so the real
``jwt.encode(RS256)`` path runs unstubbed (proving the assertion is actually signed).
"""

from __future__ import annotations

import json

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import SecretStr

from app.config import Settings
from integrations.google_indexing import (
    FakeGoogleIndexing,
    GoogleIndexingClient,
    GoogleIndexingResult,
    google_indexing_from_settings,
)

pytestmark = pytest.mark.unit

_TOKEN_HOST = "oauth2.googleapis.com"
_PUBLISH_HOST = "indexing.googleapis.com"


def _sa_json() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("ascii")
    return json.dumps(
        {
            "type": "service_account",
            "client_email": "sa@proj.iam.gserviceaccount.com",
            "private_key": pem,
            "token_uri": f"https://{_TOKEN_HOST}/token",
            "project_id": "proj",
        }
    )


def _transport(*, token_status: int = 200, publish_status: int = 200) -> httpx.MockTransport:
    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.host == _TOKEN_HOST:
            if token_status != 200:
                return httpx.Response(token_status, json={"error": "bad"})
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        if request.url.host == _PUBLISH_HOST:
            assert request.headers["Authorization"] == "Bearer tok-123"
            body = json.loads(request.content)
            assert body["type"] == "URL_UPDATED"
            return httpx.Response(publish_status, json={})
        raise AssertionError(f"unexpected host {request.url.host}")

    return httpx.MockTransport(_h)


async def test_publish_ok_signs_a_jwt_and_bearers_the_token() -> None:
    client = GoogleIndexingClient(credentials_json=_sa_json())
    async with httpx.AsyncClient(transport=_transport()) as http:
        result = await client.publish(http, url="https://acme.example/a")
    assert result.ok and "200" in result.detail


async def test_publish_403_is_error_not_crash() -> None:
    client = GoogleIndexingClient(credentials_json=_sa_json())
    async with httpx.AsyncClient(transport=_transport(publish_status=403)) as http:
        result = await client.publish(http, url="https://acme.example/a")
    assert result.ok is False and "403" in result.detail


async def test_token_failure_degrades_to_auth_failed() -> None:
    client = GoogleIndexingClient(credentials_json=_sa_json())
    async with httpx.AsyncClient(transport=_transport(token_status=401)) as http:
        result = await client.publish(http, url="https://acme.example/a")
    assert result.ok is False and result.detail == "auth failed"


async def test_token_is_cached_across_publishes() -> None:
    calls = {"token": 0}

    def _h(request: httpx.Request) -> httpx.Response:
        if request.url.host == _TOKEN_HOST:
            calls["token"] += 1
            return httpx.Response(200, json={"access_token": "tok-123", "expires_in": 3600})
        return httpx.Response(200, json={})

    client = GoogleIndexingClient(credentials_json=_sa_json())
    async with httpx.AsyncClient(transport=httpx.MockTransport(_h)) as http:
        await client.publish(http, url="https://acme.example/a")
        await client.publish(http, url="https://acme.example/b")
    assert calls["token"] == 1  # minted once, reused


async def test_fake_records_publishes() -> None:
    fake = FakeGoogleIndexing(result=GoogleIndexingResult(ok=True, detail="200 published"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))) as http:
        out = await fake.publish(http, url="https://acme.example/a")
    assert out.ok
    assert [p.url for p in fake.published] == ["https://acme.example/a"]
    assert fake.published[0].type_ == "URL_UPDATED"


def test_from_settings_gating() -> None:
    sa = _sa_json()
    # disabled -> None even with a valid credential
    off = Settings(_env_file=None, app_env="dev", google_sheets_sa_json=SecretStr(sa))
    assert google_indexing_from_settings(off) is None

    # enabled but no credential -> None
    no_cred = Settings(_env_file=None, app_env="dev", google_indexing_enabled=True)
    assert google_indexing_from_settings(no_cred) is None

    # enabled + malformed credential -> None (never raises)
    bad = Settings(
        _env_file=None, app_env="dev", google_indexing_enabled=True,
        google_sheets_sa_json=SecretStr("{not json"),
    )
    assert google_indexing_from_settings(bad) is None

    # enabled + valid credential -> a real client
    on = Settings(
        _env_file=None, app_env="dev", google_indexing_enabled=True,
        google_sheets_sa_json=SecretStr(sa),
    )
    assert isinstance(google_indexing_from_settings(on), GoogleIndexingClient)
