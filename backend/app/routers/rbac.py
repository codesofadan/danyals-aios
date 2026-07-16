"""RBAC reference endpoints - the access model in the frontend's own shapes.

All are read-only reference data (from ``app.rbac.matrix``) and require only a
valid, provisioned caller.
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
    """The 17 access features (frontend ``accessFeatures``)."""
    return list(FEATURES)


@router.get("/permissions", response_model=list[PermissionDef])
async def list_permissions(_user: CurrentUserDep) -> list[PermissionDef]:
    """The 8 permission toggles (frontend ``permissions``)."""
    return list(PERMISSIONS)


@router.get("/roles", response_model=list[RoleView])
async def list_roles(_user: CurrentUserDep) -> list[RoleView]:
    """The 6 governance roles + their default permission grants (Team screen)."""
    return [
        RoleView(
            role=to_team_role(rm.role),
            desc=rm.desc,
            color=rm.color,
            permissions=sorted(DEFAULT_ROLE_PERMS[rm.role]),
        )
        for rm in ROLE_META
    ]


@router.get("/templates", response_model=list[TemplateView])
async def list_templates(_user: CurrentUserDep) -> list[TemplateView]:
    """The 4 role templates (frontend ``roleTemplates``)."""
    return [
        TemplateView(
            key=t.key,
            label=t.label,
            tagline=t.tagline,
            icon=t.icon,
            role=to_team_role(t.role),
            color=t.color,
            grants=list(t.grants),
        )
        for t in TEMPLATES
    ]
