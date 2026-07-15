"""FastAPI routers -- one router per module.

``api_v1`` is the aggregator mounted under ``/api/v1`` in ``app.main``. Business
routers attach to it here.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.routers.activity import router as activity_router
from app.routers.admin_users import router as admin_users_router
from app.routers.audits import router as audits_router
from app.routers.auth import router as auth_router
from app.routers.clients import router as clients_router
from app.routers.context import router as context_router
from app.routers.cost import router as cost_router
from app.routers.me import router as me_router
from app.routers.milestones import router as milestones_router
from app.routers.offpage import router as offpage_router
from app.routers.policy import router as policy_router
from app.routers.portal import router as portal_router
from app.routers.public import router as public_router
from app.routers.rbac import router as rbac_router
from app.routers.settings import router as settings_router
from app.routers.tasks import router as tasks_router
from app.routers.tickets import router as tickets_router
from app.routers.tiers import router as tiers_router
from app.routers.upsells import router as upsells_router
from app.routers.vault import router as vault_router

api_v1 = APIRouter()
api_v1.include_router(auth_router)
api_v1.include_router(rbac_router)
api_v1.include_router(admin_users_router)
api_v1.include_router(clients_router)
api_v1.include_router(vault_router)
api_v1.include_router(activity_router)
api_v1.include_router(cost_router)
api_v1.include_router(tiers_router)
api_v1.include_router(audits_router)
api_v1.include_router(tasks_router)
api_v1.include_router(milestones_router)
api_v1.include_router(offpage_router)
api_v1.include_router(policy_router)
api_v1.include_router(upsells_router)
api_v1.include_router(tickets_router)
api_v1.include_router(settings_router)
api_v1.include_router(me_router)
api_v1.include_router(portal_router)
api_v1.include_router(context_router)
# The public free-audit funnel: the ONLY unauthenticated routes. Its endpoints
# declare NO auth dependency (the aggregator itself carries none), so mounting it
# here yields /api/v1/public/* as unauthenticated - see app/routers/public.py.
api_v1.include_router(public_router)
