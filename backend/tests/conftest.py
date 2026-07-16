"""Shared pytest fixtures.

The ``client`` fixture runs the app's lifespan (via ``asgi_lifespan``) so that
``app.state.http_client`` exists, then talks to the app in-process through
``httpx.ASGITransport``. ``raise_app_exceptions=False`` lets the error handlers'
500 response reach the test instead of re-raising into the test body.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
from asgi_lifespan import LifespanManager
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.main import create_app


def _dev_settings() -> Settings:
    """Deterministic dev settings, independent of the developer's shell env."""
    return Settings(_env_file=None, app_env="dev")


@pytest.fixture
def app() -> FastAPI:
    """A fresh app instance with settings pinned to dev via dependency override."""
    application = create_app()
    application.dependency_overrides[get_settings] = _dev_settings
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """An async HTTP client bound to ``app`` with its lifespan running."""
    async with LifespanManager(app):
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            yield ac
