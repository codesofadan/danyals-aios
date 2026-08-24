"""RBAC reference endpoints - the access model, served to the dashboard.

All are read-only reference data (from ``app.rbac.matrix``, the single source of
truth) and require only a valid, provisioned caller.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_staff
from app.rbac.matrix import (
    DEFAULT_ROLE_PERMS,
    FEATURES,
    PERMISSIONS,
    ROLE_META,
    TEMPLATES,
    FeatureDef,
    PermissionDef,
)
from app.schemas.identity import to_team_role
from app.schemas.rbac import RoleView, TemplateView

router = APIRouter(prefix="/rbac", tags=["rbac"])

# The agency's own access model. Every staff role may read it; a portal client may
# not - it is the agency's internal structure, and specification section 12.4 ("what
# must remain private from clients") covers it. Until 2026-08-24 these four routes
# carried only ``CurrentUserDep``, so any signed-in client received the full
# role/permission matrix, the feature catalogue and every role template's grants.
# These are in-process constants: no query runs, so RLS never gets a chance to stop it.
Staff = Annotated[CurrentUser, Depends(require_staff())]


@router.get("/features", response_model=list[FeatureDef])
async def list_features(_user: Staff) -> list[FeatureDef]:
    """The 11 access features the Add-Member screen switches on and off."""
    return list(FEATURES)


@router.get("/permissions", response_model=list[PermissionDef])
async def list_permissions(_user: Staff) -> list[PermissionDef]:
    """The 8 governance permissions the Team screen's access grid renders."""
    return list(PERMISSIONS)


@router.get("/roles", response_model=list[RoleView])
async def list_roles(_user: Staff) -> list[RoleView]:
    """The 6 governance roles + their default permission grants (Team screen)."""
    return [
        RoleView(
            role=to_team_role(rm.role),
            desc=rm.desc,
            permissions=sorted(DEFAULT_ROLE_PERMS[rm.role]),
        )
        for rm in ROLE_META
    ]


@router.get("/templates", response_model=list[TemplateView])
async def list_templates(_user: Staff) -> list[TemplateView]:
    """The 4 ready-made access templates the Add-Member screen offers."""
    return [
        TemplateView(
            key=t.key,
            label=t.label,
            tagline=t.tagline,
            icon=t.icon,
            role=to_team_role(t.role),
            grants=list(t.grants),
        )
        for t in TEMPLATES
    ]
