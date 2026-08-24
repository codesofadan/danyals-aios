"""RBAC reference data + enforcement helpers.

The canonical access model lives in :mod:`app.rbac.matrix` as versioned Python
reference data - **the single source of truth**, not a mirror of the dashboard - and
not in database tables: roles, permissions, features and role/template defaults are
static and change with a code deploy, so keeping them in code lets ``require_perm``
decide without a database round-trip.

The dashboard reads this model over ``GET /rbac/*`` rather than keeping a copy. See
:mod:`app.rbac.matrix` for what happened the last time it kept one, and
``tests/test_rbac_single_source.py`` for the gate that now prevents it.
"""

from __future__ import annotations

from app.rbac.matrix import (
    ACCESS_LEVELS,
    DEFAULT_ROLE_PERMS,
    FEATURE_KEYS,
    FEATURES,
    MODULE_PERM_ROLES,
    PERM_KEYS,
    PERMISSIONS,
    ROLE_META,
    ROLE_ORDER,
    STAFF_ROLES,
    TEMPLATES,
    AccessLevel,
    AppRole,
    FeatureDef,
    ModulePermKey,
    PermissionDef,
    PermKey,
    RoleMetaDef,
    RoleTemplateDef,
    UserRole,
    effective_feature_level,
    feature_allows,
    is_staff_role,
    level_satisfies,
    perms_for_role,
    role_has_module_perm,
    role_has_perm,
)

__all__ = [
    "ACCESS_LEVELS",
    "DEFAULT_ROLE_PERMS",
    "FEATURES",
    "FEATURE_KEYS",
    "MODULE_PERM_ROLES",
    "PERMISSIONS",
    "PERM_KEYS",
    "ROLE_META",
    "ROLE_ORDER",
    "STAFF_ROLES",
    "TEMPLATES",
    "AccessLevel",
    "AppRole",
    "FeatureDef",
    "ModulePermKey",
    "PermKey",
    "PermissionDef",
    "RoleMetaDef",
    "RoleTemplateDef",
    "UserRole",
    "effective_feature_level",
    "feature_allows",
    "is_staff_role",
    "level_satisfies",
    "perms_for_role",
    "role_has_module_perm",
    "role_has_perm",
]
