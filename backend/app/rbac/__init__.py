"""RBAC reference data + enforcement helpers.

The canonical access model lives in :mod:`app.rbac.matrix` as versioned Python
reference data (mirrored from ``frontend/lib/data.ts``), not in database tables:
roles, permissions, features, and role/template defaults are static and change
with a code deploy, so keeping them in code lets ``require_perm`` decide without
a database round-trip and keeps a single source of truth.
"""

from __future__ import annotations

from app.rbac.matrix import (
    ACCESS_LEVELS,
    DEFAULT_ROLE_PERMS,
    FEATURE_KEYS,
    FEATURES,
    PERM_KEYS,
    PERMISSIONS,
    ROLE_META,
    ROLE_ORDER,
    TEMPLATES,
    AccessLevel,
    AppRole,
    FeatureDef,
    PermissionDef,
    PermKey,
    RoleMetaDef,
    RoleTemplateDef,
    effective_feature_level,
    feature_allows,
    level_satisfies,
    perms_for_role,
    role_has_perm,
)

__all__ = [
    "ACCESS_LEVELS",
    "DEFAULT_ROLE_PERMS",
    "FEATURES",
    "FEATURE_KEYS",
    "PERMISSIONS",
    "PERM_KEYS",
    "ROLE_META",
    "ROLE_ORDER",
    "TEMPLATES",
    "AccessLevel",
    "AppRole",
    "FeatureDef",
    "PermKey",
    "PermissionDef",
    "RoleMetaDef",
    "RoleTemplateDef",
    "effective_feature_level",
    "feature_allows",
    "level_satisfies",
    "perms_for_role",
    "role_has_perm",
]
