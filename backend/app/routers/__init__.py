"""FastAPI routers -- one router per module.

``api_v1`` is the aggregator mounted under ``/api/v1`` in ``app.main``. Business
routers attach to it here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.admin_users import router as admin_users_router
from app.routers.rbac import router as rbac_router

api_v1 = APIRouter()
api_v1.include_router(rbac_router)
api_v1.include_router(admin_users_router)
