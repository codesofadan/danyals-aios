"""RBAC reference response models, in the shapes the dashboard renders.

These endpoints are how the dashboard gets the access model. They replace the
hard-coded copies in ``frontend/lib/data.ts`` (``accessFeatures``, ``permissions``,
``ROLE_META`` + ``defaultRolePerms``, ``roleTemplates``) - which had already drifted
from the backend in fourteen fields before anything compared them.

``role`` is emitted capitalized to match the frontend ``TeamRole``.

**No ``color`` field.** Accent colour is a theme token owned by the frontend
(``SERIES``); it was served here and discarded by every caller, and it was where nine
of those fourteen drifts lived. ``tests/test_rbac_single_source.py`` is the gate.
"""

from __future__ import annotations

from pydantic import BaseModel


class RoleView(BaseModel):
    """A governance role with its default permission grants (Team screen)."""

    role: str  # capitalized TeamRole
    desc: str
    permissions: list[str]


class TemplateView(BaseModel):
    """A role template in the frontend ``roleTemplates`` shape (Add-Member screen)."""

    key: str
    label: str
    tagline: str
    icon: str
    role: str  # capitalized TeamRole
    grants: list[str]
