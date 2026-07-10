"""Liveness endpoint.

``GET /health`` is a pure liveness probe: it touches no external service and does
not read ``app.state``. It answers only "is this process up and serving?".
"""

from __future__ import annotations

from fastapi import APIRouter

from app import __version__
from app.core.deps import SettingsDep
from app.schemas.health import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(settings: SettingsDep) -> HealthResponse:
    """Liveness: return process status without touching any dependency."""
    return HealthResponse(status="ok", version=__version__, env=settings.app_env)
