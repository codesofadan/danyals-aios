"""FastAPI dependency providers: shared settings and the shared async HTTP client.

The shared ``httpx.AsyncClient`` is opened once in the app lifespan and lives on
``app.state`` so handlers reuse one connection pool instead of creating clients
per request.
"""

from __future__ import annotations

from typing import Annotated

import httpx
import redis.asyncio as redis_asyncio
from fastapi import Depends, Request

from app.config import Settings, get_settings

SettingsDep = Annotated[Settings, Depends(get_settings)]


def get_http_client(request: Request) -> httpx.AsyncClient:
    """Return the shared ``httpx.AsyncClient`` opened in the app lifespan."""
    client: httpx.AsyncClient = request.app.state.http_client
    return client


HttpClientDep = Annotated[httpx.AsyncClient, Depends(get_http_client)]


def get_redis(request: Request) -> redis_asyncio.Redis:
    """Return the shared ``redis.asyncio`` client opened in the app lifespan.

    Never close this client here - the lifespan owns it for the app's lifetime.
    """
    client: redis_asyncio.Redis = request.app.state.redis
    return client


RedisDep = Annotated[redis_asyncio.Redis, Depends(get_redis)]
