"""RBAC reference endpoints - the access model, served to the dashboard.

All are read-only reference data (from ``app.rbac.matrix``, the single source of
truth) and require only a valid, provisioned caller.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.auth import CurrentUserDep
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


@router.get("/features", response_model=list[FeatureDef])
async def list_features(_user: CurrentUserDep) -> list[FeatureDef]:
    """The 11 access features the Add-Member screen switches on and off."""
    return list(FEATURES)


@router.get("/permissions", response_model=list[PermissionDef])
async def list_permissions(_user: CurrentUserDep) -> list[PermissionDef]:
    """The 8 governance permissions the Team screen's access grid renders."""
    return list(PERMISSIONS)


@router.get("/roles", response_model=list[RoleView])
async def list_roles(_user: CurrentUserDep) -> list[RoleView]:
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
async def list_templates(_user: CurrentUserDep) -> list[TemplateView]:
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
