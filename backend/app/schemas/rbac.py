"""RBAC reference response models in the exact frontend shapes.

These endpoints let the dashboard fetch the same reference data it currently
hard-codes (``accessFeatures``, ``permissions``, ``ROLE_META`` +
``defaultRolePerms``, ``roleTemplates``). ``role`` is emitted capitalized to
match the frontend ``TeamRole``.
"""

from __future__ import annotations

from pydantic import BaseModel


class RoleView(BaseModel):
    """A governance role with its default permission grants (Team screen)."""

    role: str  # capitalized TeamRole
    desc: str
    color: str
    permissions: list[str]


class TemplateView(BaseModel):
    """A role template in the frontend ``roleTemplates`` shape (Add-Member screen)."""

    key: str
    label: str
    tagline: str
    icon: str
    role: str  # capitalized TeamRole
    color: str
    grants: list[str]
