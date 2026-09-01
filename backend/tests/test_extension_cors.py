"""CORS truth for the extension origin — the 2026-09-01 pairing outage, in test form.

That night the extension's preflight (`OPTIONS` with `Access-Control-Request-Headers:
x-operator-token`) came back 400 with no allow-origin header, which Chrome reports as
exactly "Failed to fetch", and the token's `last_used_at` stayed NULL forever. The cause
was configuration (`EXTENSION_ORIGINS` unset), but the *mechanism* is code: `create_app`
must splice `extension_origins` into the CORS allowlist and permit the custom header.
These tests pin the mechanism; they go red if the splice in
`Settings.cors_origins_list` (config.py) is reverted or the middleware stops allowing
arbitrary request headers.

CORS is baked into middleware at CONSTRUCTION time, so these tests set env and rebuild
the app rather than using dependency overrides (which only reach route resolution).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from app.config import get_settings
from app.main import create_app

pytestmark = pytest.mark.unit

EXT_ORIGIN = "chrome-extension://" + "a" * 32


@pytest.fixture
def build_app(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Build a real app against a chosen EXTENSION_ORIGINS value, and always leave the
    settings cache clean for the next test."""

    def build(extension_origins: str) -> FastAPI:
        monkeypatch.setenv("EXTENSION_ORIGINS", extension_origins)
        get_settings.cache_clear()
        return create_app()

    yield build
    get_settings.cache_clear()


async def _preflight(app: FastAPI) -> httpx.Response:
    """The exact request Chrome sends before the extension's credentialed GET."""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        return await ac.options(
            "/api/v1/citation-builder/queue",
            headers={
                "Origin": EXT_ORIGIN,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Headers": "x-operator-token",
            },
        )


async def test_preflight_passes_when_the_extension_origin_is_allow_listed(
    build_app: Callable[[str], FastAPI],
) -> None:
    res = await _preflight(build_app(EXT_ORIGIN))
    assert res.status_code == 200
    assert res.headers.get("access-control-allow-origin") == EXT_ORIGIN
    assert "x-operator-token" in res.headers.get("access-control-allow-headers", "").lower()


async def test_preflight_refuses_an_unlisted_extension_origin(
    build_app: Callable[[str], FastAPI],
) -> None:
    """The refusal itself is correct behavior — the defect was only that nothing ever
    SAID so. This pins the shape the diagnostic keys off: 400, no allow-origin."""
    res = await _preflight(build_app(""))
    assert res.status_code == 400
    assert "access-control-allow-origin" not in res.headers
