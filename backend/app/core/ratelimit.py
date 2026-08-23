"""Rate limiting for expensive mutations.

A fixed-window Redis counter. Two keying strategies share one implementation:

* ``rate_limit(scope, ...)``    keys by ``(scope, user, window)`` - guards an
  AUTHENTICATED mutation that triggers real external work / spend (running an
  audit) from being hammered by one principal.
* ``rate_limit_ip(scope, ...)`` keys by ``(scope, client-ip, window)`` - the ONLY
  keying available for UNAUTHENTICATED routes (the public free-audit funnel and
  the login endpoint, where no user identity exists yet).

**Failure posture is a per-call decision, and it is not the same everywhere.**

``fail_closed=False`` (the default) allows the request when Redis is unreachable.
This is right where the limiter guards an AUTHENTICATED principal who is already
bounded by permissions, budget caps and the spend halt: throttling is a
convenience there, and the limiter must not become the reason a legitimate,
already-authorised request 500s. It is also right for ``auth_login`` - failing
closed there would lock every user out of the platform the moment the cache blips,
turning a cache outage into a total outage.

``fail_closed=True`` REFUSES the request when the limiter cannot be consulted. Use
it wherever the limiter is the ONLY thing standing between an anonymous caller and
real work - the public free-audit funnel. There, a fail-open limiter means a Redis
outage silently removes the sole abuse control on an unauthenticated endpoint that
launches crawls (`P0-2`, `MT-005`, `ADM-026`). Refusing a lead-magnet request for
the duration of a cache outage is a far smaller loss than an unmetered crawl fleet.
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


_UNAVAILABLE = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
    detail="This service is temporarily unavailable; please try again shortly.",
    headers={"Retry-After": "60"},
)


async def _enforce(
    redis: RedisDep,
    key: str,
    scope: str,
    limit: int,
    per_seconds: int,
    *,
    fail_closed: bool,
) -> None:
    """Fixed-window count for ``key``; 429 past ``limit``.

    On a limiter failure the posture is the caller's choice: allow (default) or
    refuse with a 503. See the module docstring for why it differs per route.
    """
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, per_seconds)
    except Exception as exc:
        if fail_closed:
            # The limiter is this route's only abuse control. Unable to count means
            # unable to bound, so refuse - loudly, at error level, because an
            # unreachable limiter on a spend-causing public route is an incident.
            logger.error(
                "rate_limit_unavailable_failing_closed",
                scope=scope,
                error=type(exc).__name__,
            )
            raise _UNAVAILABLE from exc
        logger.warning("rate_limit_unavailable", scope=scope, error=type(exc).__name__)
        return
    if count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for {scope}; retry shortly",
            headers={"Retry-After": str(per_seconds)},
        )


def rate_limit(
    scope: str, limit: int, per_seconds: int = 60, *, fail_closed: bool = False
) -> Callable[..., Awaitable[None]]:
    """Build a dependency that allows at most ``limit`` calls per ``per_seconds`` per user."""

    async def _dependency(
        user: Annotated[CurrentUser, Depends(get_current_user)], redis: RedisDep
    ) -> None:
        window = int(time.time()) // per_seconds
        await _enforce(
            redis, f"rl:{scope}:{user.id}:{window}", scope, limit, per_seconds,
            fail_closed=fail_closed,
        )

    return _dependency


def rate_limit_ip(
    scope: str, limit: int, per_seconds: int = 60, *, fail_closed: bool = False
) -> Callable[..., Awaitable[None]]:
    """Build a dependency that allows at most ``limit`` calls per ``per_seconds`` per client IP.

    For UNAUTHENTICATED routes (public free-audit, login) where there is no user
    to key on. Keys on ``request.client.host`` - the direct peer, which cannot be
    spoofed at the app layer (unlike a client-supplied ``X-Forwarded-For``; trust
    XFF only behind a proxy that rewrites it).

    Pass ``fail_closed=True`` on any route where this limiter is the only control
    on an anonymous caller's ability to cause real work.
    """

    async def _dependency(request: Request, redis: RedisDep) -> None:
        client_ip = request.client.host if request.client else "unknown"
        window = int(time.time()) // per_seconds
        await _enforce(
            redis, f"rl:ip:{scope}:{client_ip}:{window}", scope, limit, per_seconds,
            fail_closed=fail_closed,
        )

    return _dependency
