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


@pytest.fixture(scope="session", autouse=True)
def _ignore_developer_dotenv() -> None:
    """The unit suite must never read ``backend/.env``.

    Prevented defect (found 2026-08-24, latent since the settings module shipped):
    the suite passed only because no developer had configured the app locally. The
    moment a real `.env` existed, 1,626 tests failed at once.

    `_dev_settings` below already pins settings for FastAPI's dependency injection,
    but that override applies to ROUTE resolution only. `create_app` reads
    `get_settings()` directly at CONSTRUCTION time (app/main.py:36, :72) and bakes
    `trusted_hosts_list` into TrustedHostMiddleware (:92), long before any override
    exists. With a production `TRUSTED_HOSTS` in `.env`, every request in the suite
    was rejected with 400 by middleware - which surfaces as thousands of unrelated
    assertion failures and points nowhere near the cause.

    So the file is disabled for the whole session at the class level, which is the
    only place that reaches every construction path. Integration tests take their
    real configuration from the environment (DATABASE_URL etc), not from this file,
    so they are unaffected.
    """
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()


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
