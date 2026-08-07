"""IndexNow seam: stable per-domain key, key-location, non-raising submit, gating.

NO real network: ``indexnow_submit`` runs against an ``httpx.MockTransport``.
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from integrations.indexnow import (
    FakeIndexNow,
    IndexNowClient,
    IndexNowResult,
    indexnow_from_settings,
    indexnow_key_for_host,
    indexnow_submit,
    key_location,
)

pytestmark = pytest.mark.unit


def test_key_is_stable_per_host_and_differs_across_hosts() -> None:
    a1 = indexnow_key_for_host("acme.example", salt="s")
    a2 = indexnow_key_for_host("ACME.example", salt="s")  # case-insensitive
    b = indexnow_key_for_host("other.example", salt="s")
    assert a1 == a2  # deterministic + case-normalised -> the hosted <key>.txt stays valid
    assert a1 != b  # unique per host
    assert len(a1) == 64 and all(c in "0123456789abcdef" for c in a1)


def test_key_depends_on_salt() -> None:
    assert indexnow_key_for_host("acme.example", salt="s1") != indexnow_key_for_host(
        "acme.example", salt="s2"
    )


def test_key_location_is_domain_root_txt() -> None:
    key = indexnow_key_for_host("acme.example", salt="s")
    assert key_location("acme.example", key) == f"https://acme.example/{key}.txt"


def _client(handler: httpx.MockTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler)


@pytest.mark.parametrize("status", [200, 202])
async def test_submit_ok_on_accepted(status: int) -> None:
    seen: dict[str, object] = {}

    def _h(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = request.content
        return httpx.Response(status)

    async with _client(httpx.MockTransport(_h)) as http:
        result = await indexnow_submit(
            http, host="acme.example", key="k", key_location="https://acme.example/k.txt",
            urls=["https://acme.example/a"],
        )
    assert result.ok and str(status) in result.detail
    assert "api.indexnow.org" in str(seen["url"])
    assert b"urlList" in seen["body"]  # the key rides in the body, not a URL


async def test_submit_error_on_4xx_never_raises() -> None:
    async with _client(httpx.MockTransport(lambda r: httpx.Response(403))) as http:
        result = await indexnow_submit(
            http, host="acme.example", key="k", key_location="x", urls=["https://acme.example/a"]
        )
    assert result.ok is False and "403" in result.detail


async def test_submit_degrades_on_transport_error() -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    async with _client(httpx.MockTransport(_boom)) as http:
        result = await indexnow_submit(
            http, host="acme.example", key="k", key_location="x", urls=["u"]
        )
    assert result.ok is False and "transport" in result.detail


async def test_fake_records_submissions() -> None:
    fake = FakeIndexNow(result=IndexNowResult(ok=True, detail="202 accepted"))
    async with _client(httpx.MockTransport(lambda r: httpx.Response(200))) as http:
        out = await fake.submit(
            http, host="acme.example", key="k", key_location="l", urls=["u1", "u2"]
        )
    assert out.ok
    assert len(fake.submissions) == 1
    assert fake.submissions[0].urls == ["u1", "u2"]


def test_from_settings_gating() -> None:
    off = Settings(_env_file=None, app_env="dev")  # indexnow_enabled defaults False
    assert indexnow_from_settings(off) is None

    on = Settings(_env_file=None, app_env="dev", indexnow_enabled=True, indexnow_key_salt=SecretStr("s"))
    client = indexnow_from_settings(on)
    assert isinstance(client, IndexNowClient)
