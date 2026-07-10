"""Chunk 3 gate: liveness, request-id propagation, and the 500 error envelope."""

from __future__ import annotations

import httpx
import pytest
from asgi_lifespan import LifespanManager

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
