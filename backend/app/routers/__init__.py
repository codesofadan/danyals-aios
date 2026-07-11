"""FastAPI routers -- one router per module.

``api_v1`` is the aggregator mounted under ``/api/v1`` in ``app.main``. Business
routers attach to it here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.activity import router as activity_router
from app.routers.admin_users import router as admin_users_router
from app.routers.clients import router as clients_router
from app.routers.cost import router as cost_router
from app.routers.rbac import router as rbac_router
from app.routers.vault import router as vault_router

api_v1 = APIRouter()
api_v1.include_router(rbac_router)
api_v1.include_router(admin_users_router)
api_v1.include_router(clients_router)
api_v1.include_router(vault_router)
api_v1.include_router(activity_router)
api_v1.include_router(cost_router)
