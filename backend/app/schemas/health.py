"""Health and readiness response models.

``DependencyStatus`` is declared here now (Chunk 3) so the readiness pings built
in Chunks 5-7 share one contract; ``ReadyResponse`` is added later in Chunk 7.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class HealthResponse(BaseModel):
    """Liveness payload for ``GET /health`` (touches no external service)."""

    status: str
    version: str
    env: str


class DependencyStatus(BaseModel):
    """One dependency's readiness state. ``detail`` is a short, sanitized reason."""

    name: str
    status: Literal["ok", "error", "timeout", "not_configured"]
    detail: str | None = None
