"""Chunk 7 gate: /health/ready is concurrent, bounded, and non-short-circuiting."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Iterator

import httpx
import pytest
from fastapi import FastAPI

import app.routers.health as health_module
from app.config import Settings, get_settings
from app.schemas.health import DependencyStatus


def _ok(name: str) -> DependencyStatus:
    return DependencyStatus(name=name, status="ok")


def _stub_supabase(status: DependencyStatus) -> None:
    async def _stub(*_args: object, **_kwargs: object) -> DependencyStatus:
        return status

    health_module.supabase_ping = _stub  # type: ignore[assignment]


def _stub_redis(status: DependencyStatus) -> None:
    async def _stub(*_args: object, **_kwargs: object) -> DependencyStatus:
        return status

    health_module.redis_ping = _stub  # type: ignore[assignment]


def _stub_db(status: DependencyStatus) -> None:
    async def _stub(*_args: object, **_kwargs: object) -> DependencyStatus:
        return status

    health_module.db_ping = _stub  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _restore_pings() -> Iterator[None]:
    """Restore the real ping functions after any test that stubs them.

    ``db_ping`` is default-stubbed to ``not_configured`` so these readiness tests
    stay hermetic: the app lifespan reads the real ``.env`` (which may carry a
    live DATABASE_URL), but a unit test must not depend on Postgres being up.
    """
    real_supabase = health_module.supabase_ping
    real_redis = health_module.redis_ping
    real_db = health_module.db_ping
    _stub_db(DependencyStatus(name="postgres", status="not_configured"))
    yield
    health_module.supabase_ping = real_supabase
    health_module.redis_ping = real_redis
    health_module.db_ping = real_db


@pytest.mark.unit
async def test_ready_ok_when_all_dependencies_ok(client: httpx.AsyncClient) -> None:
    _stub_supabase(_ok("supabase"))
    _stub_redis(_ok("redis"))
    _stub_db(_ok("postgres"))
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    statuses = {d["name"]: d["status"] for d in body["dependencies"]}
    assert statuses == {"supabase": "ok", "redis": "ok", "postgres": "ok"}


@pytest.mark.unit
async def test_ready_503_when_redis_down(client: httpx.AsyncClient) -> None:
    _stub_supabase(_ok("supabase"))
    _stub_redis(DependencyStatus(name="redis", status="error", detail="connection failed"))
    resp = await client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "not_ready"
    redis_dep = next(d for d in body["dependencies"] if d["name"] == "redis")
    assert redis_dep["status"] == "error"


@pytest.mark.unit
async def test_ready_not_configured_does_not_fail(client: httpx.AsyncClient) -> None:
    # decision D: a missing-config dependency is reported but does NOT block readiness
    _stub_supabase(DependencyStatus(name="supabase", status="not_configured"))
    _stub_redis(_ok("redis"))
    resp = await client.get("/health/ready")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    supabase_dep = next(d for d in body["dependencies"] if d["name"] == "supabase")
    assert supabase_dep["status"] == "not_configured"


@pytest.mark.unit
async def test_ready_maps_leaked_exception_to_error(client: httpx.AsyncClient) -> None:
    # defense-in-depth: a ping that violates its no-raise contract is caught
    async def _boom(*_args: object, **_kwargs: object) -> DependencyStatus:
        raise RuntimeError("should have been caught")

    health_module.supabase_ping = _boom  # type: ignore[assignment]
    _stub_redis(_ok("redis"))
    resp = await client.get("/health/ready")
    assert resp.status_code == 503
    body = resp.json()
    supabase_dep = next(d for d in body["dependencies"] if d["name"] == "supabase")
    assert supabase_dep["status"] == "error"
    assert "should have been caught" not in resp.text


class _SlowRedis:
    """A redis stand-in whose ping hangs far past the budget."""

    def __init__(self, delay: float):
        self._delay = delay

    async def ping(self) -> bool:
        await asyncio.sleep(self._delay)
        return True

    async def aclose(self) -> None:
        """No-op so the lifespan shutdown can close this stand-in."""


@pytest.mark.unit
async def test_ready_is_bounded_and_reports_sibling(app: FastAPI) -> None:
    """REQUIRED: a hung redis ping cannot hang the probe.

    Uses the REAL redis_ping (self-bounded via asyncio.wait_for) against a redis
    client that sleeps 5x the budget. The endpoint must return at ~budget, report
    redis as "timeout", and STILL return supabase's real "ok" result.
    """
    budget = 0.2

    def _small_budget_settings() -> Settings:
        return Settings(_env_file=None, app_env="dev", readiness_timeout_seconds=budget)

    app.dependency_overrides[get_settings] = _small_budget_settings
    _stub_supabase(_ok("supabase"))  # real redis_ping is left in place

    from asgi_lifespan import LifespanManager

    async with LifespanManager(app):
        app.state.redis = _SlowRedis(delay=budget * 5)
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
            start = time.monotonic()
            resp = await ac.get("/health/ready")
            elapsed = time.monotonic() - start

    # returned at ~budget, not at 5x budget
    assert elapsed < budget * 3
    assert resp.status_code == 503
    body = resp.json()
    deps = {d["name"]: d for d in body["dependencies"]}
    assert deps["redis"]["status"] == "timeout"
    assert deps["supabase"]["status"] == "ok"  # sibling result survived
    # sanitized: no redis URL/password leaked in the timeout detail
    assert "6379" not in resp.text
    assert "redis://" not in resp.text
