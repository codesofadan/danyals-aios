"""The shared async Redis client + its readiness ping.

One long-lived ``redis.asyncio`` client (with a bounded connection pool) is
opened once in the app lifespan and stored on ``app.state.redis``. Handlers reuse
it via the ``get_redis`` dependency; they must never close it - the lifespan owns
its whole life.

``decode_responses=False`` (bytes in, bytes out): this app uses Redis for a
cache/write-buffer that stores opaque bytes (JSON blobs, msgpack), so decoding
every reply to ``str`` would be wrong for binary values and wasteful for the rest.
Callers decode explicitly where they know the value is text.
"""

from __future__ import annotations

import asyncio

import redis.asyncio as redis_asyncio
from redis.exceptions import RedisError

from app.config import Settings
from app.schemas.health import DependencyStatus

_DEPENDENCY_NAME = "redis"

# Bounded pool so a burst of concurrent handlers cannot open unbounded sockets.
_MAX_CONNECTIONS = 20


def create_redis_client(settings: Settings) -> redis_asyncio.Redis:
    """Construct (do NOT connect) the shared async Redis client.

    Called from the lifespan STARTUP. Construction is lazy - no socket is opened
    until the first command - which keeps liveness (``GET /health``) independent
    of whether Redis is actually up.
    """
    client: redis_asyncio.Redis = redis_asyncio.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
        max_connections=_MAX_CONNECTIONS,
        health_check_interval=30,
        decode_responses=False,
    )
    return client


async def ping(client: redis_asyncio.Redis, timeout: float) -> DependencyStatus:
    """Readiness ping for Redis. Never raises; bounded by ``timeout``.

    Maps a timeout to status ``timeout`` and any connection/protocol error to
    ``error``, with a short sanitized detail that never leaks the Redis URL,
    password, or raw exception text.
    """
    try:
        await asyncio.wait_for(client.ping(), timeout)
    except TimeoutError:
        # asyncio.TimeoutError is an alias of the builtin TimeoutError on 3.11+.
        return DependencyStatus(name=_DEPENDENCY_NAME, status="timeout", detail="ping timed out")
    except (RedisError, OSError):
        return DependencyStatus(name=_DEPENDENCY_NAME, status="error", detail="connection failed")
    return DependencyStatus(name=_DEPENDENCY_NAME, status="ok")
