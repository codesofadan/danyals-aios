"""Chunk 5 gate: Supabase seams + async readiness ping (no network for unit tests)."""

from __future__ import annotations

import os

import httpx
import pytest

from app.db import supabase as sb

_URL = "https://project.supabase.co"


class _FakeClient:
    """Minimal stand-in for httpx.AsyncClient.get used by ``ping``."""

    def __init__(self, *, response: httpx.Response | None = None, exc: Exception | None = None):
        self._response = response
        self._exc = exc
        self.last_url: str | None = None
        self.last_headers: dict[str, str] | None = None

    async def get(
        self, url: str, headers: dict[str, str] | None = None, timeout: float | None = None
    ) -> httpx.Response:
        self.last_url = url
        self.last_headers = headers
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


@pytest.mark.unit
async def test_ping_not_configured_when_url_missing() -> None:
    client = _FakeClient()
    status = await sb.ping(client, None, timeout=1.0)  # type: ignore[arg-type]
    assert status.name == "supabase"
    assert status.status == "not_configured"
    assert client.last_url is None  # never touched the network


@pytest.mark.unit
async def test_ping_ok_on_2xx() -> None:
    response = httpx.Response(200, request=httpx.Request("GET", f"{_URL}/auth/v1/health"))
    client = _FakeClient(response=response)
    status = await sb.ping(client, _URL, timeout=1.0)  # type: ignore[arg-type]
    assert status.status == "ok"


@pytest.mark.unit
async def test_ping_sends_anon_apikey_header(monkeypatch: pytest.MonkeyPatch) -> None:
    # Supabase gates /auth/v1/health behind the anon apikey; the ping must send it,
    # or a healthy project returns 401 and readiness falsely reports it down.
    from pydantic import SecretStr

    class _S:
        supabase_anon_key = SecretStr("anon-xyz")

    monkeypatch.setattr(sb, "get_settings", lambda: _S())
    response = httpx.Response(200, request=httpx.Request("GET", f"{_URL}/auth/v1/health"))
    client = _FakeClient(response=response)
    status = await sb.ping(client, _URL, timeout=1.0)  # type: ignore[arg-type]
    assert status.status == "ok"
    assert client.last_headers is not None
    assert client.last_headers.get("apikey") == "anon-xyz"


@pytest.mark.unit
async def test_ping_error_on_connect_error() -> None:
    client = _FakeClient(exc=httpx.ConnectError("connection refused"))
    status = await sb.ping(client, _URL, timeout=1.0)  # type: ignore[arg-type]
    assert status.status == "error"
    # sanitized: the raw exception text and the url must not leak into detail
    assert status.detail is not None
    assert _URL not in status.detail
    assert "connection refused" not in status.detail


@pytest.mark.unit
async def test_ping_timeout_maps_to_timeout() -> None:
    client = _FakeClient(exc=httpx.TimeoutException("timed out"))
    status = await sb.ping(client, _URL, timeout=1.0)  # type: ignore[arg-type]
    assert status.status == "timeout"
    assert status.detail is not None
    assert _URL not in status.detail


@pytest.mark.unit
async def test_ping_error_on_non_2xx() -> None:
    response = httpx.Response(503, request=httpx.Request("GET", f"{_URL}/auth/v1/health"))
    client = _FakeClient(response=response)
    status = await sb.ping(client, _URL, timeout=1.0)  # type: ignore[arg-type]
    assert status.status == "error"
    assert status.detail is not None
    assert _URL not in status.detail


@pytest.mark.unit
def test_client_for_user_is_not_cached() -> None:
    # a per-JWT client must never be memoized (would leak authorization across users)
    assert not hasattr(sb.client_for_user, "cache_info")


@pytest.mark.integration
async def test_ping_real_supabase() -> None:
    url = os.environ.get("SUPABASE_URL")
    if not url:
        pytest.skip("SUPABASE_URL not set")
    async with httpx.AsyncClient() as client:
        status = await sb.ping(client, url, timeout=5.0)
    assert status.status == "ok"
