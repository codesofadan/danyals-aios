"""Shared pytest fixtures.

The ``client`` fixture runs the app's lifespan (via ``asgi_lifespan``) so that
``app.state.http_client`` exists, then talks to the app in-process through
``httpx.ASGITransport``. ``raise_app_exceptions=False`` lets the error handlers'
500 response reach the test instead of re-raising into the test body.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

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


@pytest.fixture(autouse=True)
def _job_ledger(request: pytest.FixtureRequest) -> Any:
    """Give every UNIT test an in-memory job ledger.

    Any task migrated to ``@aios_job`` claims a `job_runs` row before its body runs, so
    without this a unit test of such a task reaches for a Postgres pool that a unit test
    is not allowed to have — and fails with a `DatabaseNotConfiguredError` surfacing as
    an unrelated Celery retry, which is a genuinely confusing way to learn you forgot a
    fixture.

    Autouse, because "a unit test must not touch the database" is a property of the
    whole unit suite rather than of individual tests, and 39 tasks are migrating onto
    the contract. Integration tests are exempt: they have a real pool and their whole
    purpose is to exercise the real store.

    A test that wants to ASSERT on the ledger just requests the fake by name.
    """
    if request.node.get_closest_marker("integration"):
        yield None
        return
    from tests.test_job_contract import FakeStore

    fake = FakeStore()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("app.jobs.celery_task.job_runs_store", lambda: fake)
    try:
        yield fake
    finally:
        monkeypatch.undo()
