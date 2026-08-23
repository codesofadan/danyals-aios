"""Chunk 3 gate: liveness, request-id propagation, and the 500 error envelope."""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from app.main import create_app


@pytest.mark.unit
async def test_health_liveness_ok(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"]
    assert body["env"]
    assert resp.headers.get("X-Request-ID")


@pytest.mark.unit
async def test_request_id_header_is_echoed(client: httpx.AsyncClient) -> None:
    resp = await client.get("/health", headers={"X-Request-ID": "fixed-request-id-123"})
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID") == "fixed-request-id-123"


@pytest.mark.unit
async def test_unhandled_error_returns_envelope_with_request_id() -> None:
    """A route that raises must yield the generic 500 envelope + a surviving request-id."""
    app = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("kaboom - internal detail that must never leak")

    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            resp = await ac.get("/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["error"]["type"] == "internal_error"
    assert body["error"]["message"] == "Internal Server Error"
    # request-id survived the 500 path (read from request.state, not contextvars)
    assert body["error"]["request_id"]
    assert resp.headers.get("X-Request-ID")
    # no internals leaked to the client
    assert "kaboom" not in resp.text
    assert "RuntimeError" not in resp.text


# --------------------------------------------------------------------------- #
# The error envelope must preserve PROTOCOL headers
# --------------------------------------------------------------------------- #
# `_error_response` used to build a fresh header dict containing only
# X-Request-ID, discarding whatever the raiser attached to its HTTPException.
# Two live consequences: every 401 the platform emitted was missing the
# `WWW-Authenticate` field RFC 9110 requires, and every 429 from the rate limiter
# was missing its `Retry-After` — so a throttled client had nothing to back off
# on, which is precisely the retry storm the limiter exists to prevent.


@pytest.mark.unit
async def test_a_401_carries_www_authenticate_through_the_envelope(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/v1/clients")
    assert resp.status_code in (401, 403)
    if resp.status_code == 401:
        assert resp.headers.get("WWW-Authenticate") == "Bearer"
    # The envelope shape is unchanged.
    assert set(resp.json()["error"]) >= {"type", "message", "request_id"}


@pytest.mark.unit
async def test_the_envelope_preserves_raiser_headers_and_keeps_its_own_request_id(
    app: FastAPI, client: httpx.AsyncClient
) -> None:
    from fastapi import HTTPException

    from app.core.errors import REQUEST_ID_HEADER

    @app.get("/api/v1/_test_headers")
    async def _raise() -> None:
        raise HTTPException(
            status_code=503,
            detail="nope",
            # A raiser must not be able to hijack the request's correlation id.
            headers={"Retry-After": "42", REQUEST_ID_HEADER: "attacker-supplied"},
        )

    resp = await client.get("/api/v1/_test_headers")
    assert resp.status_code == 503
    assert resp.headers["Retry-After"] == "42"
    assert resp.headers[REQUEST_ID_HEADER] != "attacker-supplied"
