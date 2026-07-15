"""FastAPI application factory and module-level ASGI app.

Boot order is settings -> logging -> validate -> Sentry. The lifespan owns the
shared async ``httpx`` client (and, from Chunk 6, the redis pool). Middleware is
added TrustedHost -> CORS -> RequestID; because Starlette applies middleware LIFO
the last-added ``RequestIDMiddleware`` becomes the outermost user middleware, so
every response (including CORS preflights and 500s) carries a request-id.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app import __version__
from app.config import get_settings, validate_settings
from app.core.auth import JWKSCache
from app.core.errors import install_error_handlers
from app.core.metrics import MetricsMiddleware, metrics_response
from app.core.middleware import RequestIDMiddleware
from app.core.observability import init_sentry
from app.core.redis import create_redis_client
from app.db.database import build_admin_pool, build_rls_pool, clear_pools, set_pools
from app.logging_setup import configure_logging, get_logger
from app.routers import api_v1
from app.routers.health import router as health_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own process-wide async resources for the app's lifetime."""
    settings = get_settings()
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    # Construct only (no ping) so liveness stays independent of Redis being up.
    app.state.redis = create_redis_client(settings)
    # JWKS verifier for Supabase access tokens; None until Supabase is configured
    # (keys are fetched lazily on the first authenticated request).
    app.state.jwks_cache = JWKSCache.from_settings(settings)
    # Local-Postgres pools (P6A-3), one per trust level. Constructed None when the
    # DSN is absent (dual-config window) and OPENED non-blocking so liveness stays
    # independent of the DB being reachable. ``set_pools`` also registers them as
    # the process-wide singletons the RLS/privileged seams reach through.
    app.state.rls_pool = build_rls_pool(settings.database_url)
    app.state.admin_pool = build_admin_pool(settings.database_admin_url)
    if app.state.rls_pool is not None:
        app.state.rls_pool.open()
    if app.state.admin_pool is not None:
        app.state.admin_pool.open()
    set_pools(app.state.rls_pool, app.state.admin_pool)
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        # getattr guard: a partial startup may not have reached the redis line.
        redis_client = getattr(app.state, "redis", None)
        if redis_client is not None:
            await redis_client.aclose()
        # Close both DB pools behind getattr guards (partial startup may not have
        # reached the pool lines), then clear the module singletons.
        for _attr in ("rls_pool", "admin_pool"):
            pool = getattr(app.state, _attr, None)
            if pool is not None:
                pool.close()
        clear_pools()


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()
    configure_logging(settings)
    validate_settings(settings)
    init_sentry(settings)

    get_logger("app.main").info(
        "app_configured", env=settings.app_env, docs_enabled=settings.docs_enabled
    )

    app = FastAPI(
        title="AIOS Backend",
        version=__version__,
        lifespan=lifespan,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    # LIFO: added last => outermost. RequestID wraps CORS + TrustedHost so every
    # response -- including preflights and unhandled-error 500s -- carries a request-id.
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Added before RequestID so RequestID stays the OUTERMOST middleware (every
    # response keeps its id) while metrics still wrap routing + the handler.
    app.add_middleware(MetricsMiddleware)
    app.add_middleware(RequestIDMiddleware)

    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_v1, prefix="/api/v1")

    # Prometheus scrape endpoint (no auth; restrict to the scrape network at the
    # edge). Excluded from the OpenAPI schema - it is ops surface, not API.
    app.add_api_route("/metrics", lambda: metrics_response(), include_in_schema=False)
    return app


app = create_app()
