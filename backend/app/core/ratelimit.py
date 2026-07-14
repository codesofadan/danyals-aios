"""Per-user rate limiting for expensive mutations (fail-OPEN).

A fixed-window Redis counter keyed by ``(scope, user, window)``. It guards the
mutations that trigger real external work / spend (running an audit) from being
hammered by one authenticated principal.

Fail-OPEN by design: if Redis is unreachable the request is ALLOWED and a warning
is logged. Availability beats throttling - the limiter must never be the reason a
legitimate request 500s (and it inherits the app's Redis-optional posture).
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, HTTPException, status

from app.core.auth import CurrentUser, get_current_user
from app.core.deps import RedisDep
from app.logging_setup import get_logger

logger = get_logger("app.ratelimit")


def rate_limit(scope: str, limit: int, per_seconds: int = 60) -> Callable[..., Awaitable[None]]:
    """Build a dependency that allows at most ``limit`` calls per ``per_seconds`` per user."""

    async def _dependency(
        user: Annotated[CurrentUser, Depends(get_current_user)], redis: RedisDep
    ) -> None:
        window = int(time.time()) // per_seconds
        key = f"rl:{scope}:{user.id}:{window}"
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

    return _dependency
