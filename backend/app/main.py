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
from app.core.middleware import RequestIDMiddleware
from app.core.observability import init_sentry
from app.core.redis import create_redis_client
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
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        # getattr guard: a partial startup may not have reached the redis line.
        redis_client = getattr(app.state, "redis", None)
        if redis_client is not None:
            await redis_client.aclose()


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
    app.add_middleware(RequestIDMiddleware)

    install_error_handlers(app)
    app.include_router(health_router)
    app.include_router(api_v1, prefix="/api/v1")
    return app


app = create_app()
