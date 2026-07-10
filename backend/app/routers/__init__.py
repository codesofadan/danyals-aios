"""FastAPI routers -- one router per module.

``api_v1`` is the aggregator mounted under ``/api/v1`` in ``app.main``. It has no
routes yet; business routers attach to it in later parts.
"""

from __future__ import annotations

from fastapi import APIRouter

api_v1 = APIRouter()
