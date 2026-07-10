"""Chunk 6 gate: the async Redis ping is bounded and non-raising."""

from __future__ import annotations

import asyncio
import os

import pytest
import redis.asyncio as redis_asyncio
from redis.exceptions import ConnectionError as RedisConnectionError

from app.config import Settings
from app.core.redis import create_redis_client, ping


class _FakePing:
    """Stand-in exposing only the async ``ping`` used by the readiness check."""

    def __init__(self, *, result: bool = True, exc: Exception | None = None, delay: float = 0.0):
        self._result = result
        self._exc = exc
        self._delay = delay

    async def ping(self) -> bool:
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._exc is not None:
            raise self._exc
        return self._result


@pytest.mark.unit
async def test_ping_ok() -> None:
    status = await ping(_FakePing(), timeout=1.0)  # type: ignore[arg-type]
    assert status.name == "redis"
    assert status.status == "ok"
    assert status.detail is None


@pytest.mark.unit
async def test_ping_error_on_connection_error() -> None:
    client = _FakePing(exc=RedisConnectionError("Connection refused: 127.0.0.1:6379"))
    status = await ping(client, timeout=1.0)  # type: ignore[arg-type]
    assert status.status == "error"
    # sanitized: no host/port/raw exception text in detail
    assert status.detail is not None
    assert "6379" not in status.detail
    assert "Connection refused" not in status.detail


@pytest.mark.unit
async def test_ping_error_on_os_error() -> None:
    status = await ping(_FakePing(exc=OSError("boom")), timeout=1.0)  # type: ignore[arg-type]
    assert status.status == "error"


@pytest.mark.unit
async def test_ping_is_bounded_by_timeout() -> None:
    # a hung ping must not hang the probe: it returns ~timeout as "timeout"
    slow = _FakePing(delay=5.0)
    status = await asyncio.wait_for(ping(slow, timeout=0.05), timeout=1.0)  # type: ignore[arg-type]
    assert status.status == "timeout"
    assert status.detail is not None


@pytest.mark.unit
def test_create_redis_client_does_not_connect() -> None:
    # construction must be lazy - no socket opened, so liveness never depends on redis
    settings = Settings(_env_file=None, redis_url="redis://localhost:6379/0")
    client = create_redis_client(settings)
    assert isinstance(client, redis_asyncio.Redis)


@pytest.mark.integration
async def test_ping_real_redis() -> None:
    url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    client = redis_asyncio.Redis.from_url(url, socket_connect_timeout=2, socket_timeout=2)
    try:
        status = await ping(client, timeout=3.0)
    finally:
        await client.aclose()
    assert status.status == "ok"
