"""Health endpoints: liveness (root) and readiness (dependency-checked).

``GET /health`` is a pure liveness probe - it touches no external service and
answers only "is this process up and serving?".

``GET /health/ready`` is readiness - it pings local Postgres and Redis
concurrently under a shared time budget and reports each dependency. It returns
503 (naming the down dependency) if any dependency is in error/timeout, and 200
otherwise; a ``not_configured`` dependency does NOT make the app not-ready
(decision D: a dev app without a DB DSN still serves).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Request, Response

from app import __version__
from app.core.deps import RedisDep, SettingsDep
from app.core.redis import ping as redis_ping
from app.db.database import db_ping
from app.schemas.health import DependencyStatus, HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])

# Dependency statuses that mean "not ready" (missing config does NOT - decision D).
_NOT_READY_STATUSES = frozenset({"error", "timeout"})


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """Liveness: return process status without touching any dependency."""
    return HealthResponse(status="ok", version=__version__, env=settings.app_env)


@router.get(
    "/health/ready",
    response_model=ReadyResponse,
    responses={503: {"model": ReadyResponse}},
)
async def health_ready(
    request: Request,
    response: Response,
    settings: SettingsDep,
    redis: RedisDep,
) -> ReadyResponse:
    """Readiness: ping local Postgres + Redis concurrently in one budget.

    The pings are already self-bounded and non-raising; ``return_exceptions=True``
    is defense-in-depth - any leaked exception is mapped to an ``error`` status so
    the probe still returns within its budget and never crashes. A pool whose DSN
    is unset reports ``not_configured``, which does NOT make the app not-ready
    (decision D).
    """
    budget = settings.readiness_timeout_seconds
    # Owned by the lifespan; getattr guard keeps the probe safe on a partial startup.
    rls_pool = getattr(request.app.state, "rls_pool", None)
    results = await asyncio.gather(
        db_ping(rls_pool, budget),
        redis_ping(redis, budget),
        return_exceptions=True,
    )

    names = ("postgres", "redis")
    dependencies: list[DependencyStatus] = []
    for name, result in zip(names, results, strict=True):
        if isinstance(result, DependencyStatus):
            dependencies.append(result)
        else:
            # A ping raised despite its contract; degrade gracefully.
            dependencies.append(
                DependencyStatus(name=name, status="error", detail="probe failed")
            )

    not_ready = any(dep.status in _NOT_READY_STATUSES for dep in dependencies)
    if not_ready:
        response.status_code = 503
    return ReadyResponse(
        status="not_ready" if not_ready else "ok",
        version=__version__,
        env=settings.app_env,
        dependencies=dependencies,
    )
