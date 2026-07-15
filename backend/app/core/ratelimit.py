"""Rate limiting for expensive mutations (fail-OPEN).

A fixed-window Redis counter. Two keying strategies share one implementation:

* ``rate_limit(scope, ...)``    keys by ``(scope, user, window)`` - guards an
  AUTHENTICATED mutation that triggers real external work / spend (running an
  audit) from being hammered by one principal.
* ``rate_limit_ip(scope, ...)`` keys by ``(scope, client-ip, window)`` - the ONLY
  keying available for UNAUTHENTICATED routes (the public free-audit funnel and
  the login endpoint, where no user identity exists yet).

Fail-OPEN by design: if Redis is unreachable the request is ALLOWED and a warning
is logged. Availability beats throttling - the limiter must never be the reason a
legitimate request 500s (and it inherits the app's Redis-optional posture).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status

from app.core.auth import CurrentUser, get_current_user
from app.core.deps import RedisDep
from app.logging_setup import get_logger

logger = get_logger("app.ratelimit")


async def _enforce(redis: RedisDep, key: str, scope: str, limit: int, per_seconds: int) -> None:
    """Fixed-window count for ``key``; raise 429 past ``limit``, fail-open on error."""
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, per_seconds)
    except Exception as exc:  # fail-open: never let the limiter cause a 5xx
        logger.warning("rate_limit_unavailable", scope=scope, error=type(exc).__name__)
        return
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {scope}; retry shortly",
            headers={"Retry-After": str(per_seconds)},
        )


def rate_limit(scope: str, limit: int, per_seconds: int = 60) -> Callable[..., Awaitable[None]]:
    """Build a dependency that allows at most ``limit`` calls per ``per_seconds`` per user."""

    async def _dependency(
        user: Annotated[CurrentUser, Depends(get_current_user)], redis: RedisDep
    ) -> None:
        window = int(time.time()) // per_seconds
        await _enforce(redis, f"rl:{scope}:{user.id}:{window}", scope, limit, per_seconds)

    return _dependency


def rate_limit_ip(scope: str, limit: int, per_seconds: int = 60) -> Callable[..., Awaitable[None]]:
    """Build a dependency that allows at most ``limit`` calls per ``per_seconds`` per client IP.

    For UNAUTHENTICATED routes (public free-audit, login) where there is no user
    to key on. Keys on ``request.client.host`` - the direct peer, which cannot be
    spoofed at the app layer (unlike a client-supplied ``X-Forwarded-For``; trust
    XFF only behind a proxy that rewrites it). Fail-OPEN like ``rate_limit``.
    """

    async def _dependency(request: Request, redis: RedisDep) -> None:
        client_ip = request.client.host if request.client else "unknown"
        window = int(time.time()) // per_seconds
        await _enforce(redis, f"rl:ip:{scope}:{client_ip}:{window}", scope, limit, per_seconds)

    return _dependency
