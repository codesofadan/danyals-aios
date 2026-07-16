"""Settings module endpoints: the net-new persistence behind the admin control
panel's Workspace / Security / Notifications tabs (the rest of the screen reuses
users / vault / rbac).

Auth mirrors the 0025 RLS boundary:

* Workspace + Security are agency-global - GET/PUT are owner/admin only
  (``require_role``), matching the singleton manage policy.
* Notification prefs are PER-USER - any provisioned staff manages their OWN toggles
  (``view_reports``, which a portal client lacks); RLS pins every row to the caller.
* The danger zone (reset settings / purge the activity log) is OWNER-ONLY.

Responses are the frontend ``WorkspaceSettingsData`` / ``SecurityPolicy`` /
``NotifPref`` shapes (``lib/data.ts``). Every mutation records an ``access`` activity.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, status

from app.core.auth import CurrentUser, require_owner, require_perm, require_role
from app.db.settings_repo import SettingsRepoDep
from app.schemas.settings import (
    SECURITY_DEFAULTS,
    WORKSPACE_DEFAULTS,
    NotifPrefResponse,
    NotifPrefUpdate,
    SecurityPolicyResponse,
    SecurityPolicyUpdate,
    WorkspaceSettingsResponse,
    WorkspaceSettingsUpdate,
    is_notif_key,
)
from app.services.activity import record_activity

router = APIRouter(tags=["settings"])

# Agency-global stores: owner/admin only (mirrors the singleton manage policy).
ManageSettings = Annotated[CurrentUser, Depends(require_role("owner", "admin"))]
# Per-user notif prefs: any staff (a portal client lacks view_reports); RLS scopes
# every row to the caller, so a staff member only ever touches their OWN toggles.
OwnPrefs = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# The danger zone is owner-only.
OwnerOnly = Annotated[CurrentUser, Depends(require_owner())]


def _overrides(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Map the caller's stored notif rows to ``event_key -> {email, in_app}``."""
    return {
        str(r["event_key"]): {"email": r.get("email"), "in_app": r.get("in_app")}
        for r in rows
    }


# --- Workspace settings ------------------------------------------------------
@router.get("/settings/workspace", response_model=WorkspaceSettingsResponse)
async def get_workspace(repo: SettingsRepoDep, _user: ManageSettings) -> WorkspaceSettingsResponse:
    """The agency workspace settings (owner/admin). Falls back to the defaults if the
    singleton has never been saved."""
    row = await asyncio.to_thread(repo.get_workspace)
    return WorkspaceSettingsResponse.from_row(row)


@router.put("/settings/workspace", response_model=WorkspaceSettingsResponse)
async def put_workspace(
    body: WorkspaceSettingsUpdate, repo: SettingsRepoDep, actor: ManageSettings
) -> WorkspaceSettingsResponse:
    """Save the workspace settings (owner/admin). Only the provided fields change."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        row = await asyncio.to_thread(repo.get_workspace)
        return WorkspaceSettingsResponse.from_row(row)
    updated = await asyncio.to_thread(repo.update_workspace, changes)
    await record_activity(
        actor, kind="access", action="updated workspace settings", target="Workspace"
    )
    return WorkspaceSettingsResponse.from_row(updated)


# --- Security policy ---------------------------------------------------------
@router.get("/settings/security", response_model=SecurityPolicyResponse)
async def get_security(repo: SettingsRepoDep, _user: ManageSettings) -> SecurityPolicyResponse:
    """The agency security policy (owner/admin). Falls back to the defaults if the
    singleton has never been saved."""
    row = await asyncio.to_thread(repo.get_security)
    return SecurityPolicyResponse.from_row(row)


@router.put("/settings/security", response_model=SecurityPolicyResponse)
async def put_security(
    body: SecurityPolicyUpdate, repo: SettingsRepoDep, actor: ManageSettings
) -> SecurityPolicyResponse:
    """Save the security policy (owner/admin). Only the provided fields change."""
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        row = await asyncio.to_thread(repo.get_security)
        return SecurityPolicyResponse.from_row(row)
    updated = await asyncio.to_thread(repo.update_security, changes)
    await record_activity(
        actor, kind="access", action="updated the security policy", target="Security"
    )
    return SecurityPolicyResponse.from_row(updated)


# --- Notification preferences (per-user) -------------------------------------
@router.get("/settings/notifications", response_model=list[NotifPrefResponse])
async def get_notifications(
    repo: SettingsRepoDep, _user: OwnPrefs
) -> list[NotifPrefResponse]:
    """The caller's 7 notification events, each merged with their stored toggles."""
    rows = await asyncio.to_thread(repo.list_notif_prefs)
    return NotifPrefResponse.merged(_overrides(rows))


@router.put("/settings/notifications", response_model=list[NotifPrefResponse])
async def put_notifications(
    body: NotifPrefUpdate, repo: SettingsRepoDep, actor: OwnPrefs
) -> list[NotifPrefResponse]:
    """Save the caller's notification toggles (per-user). Unknown event keys are
    ignored so a stale client can never write junk rows."""
    for item in body.prefs:
        if is_notif_key(item.key):
            await asyncio.to_thread(
                repo.upsert_notif_pref, item.key, email=item.email, in_app=item.in_app
            )
    await record_activity(
        actor, kind="access", action="updated notification preferences",
        target="Notifications",
    )
    rows = await asyncio.to_thread(repo.list_notif_prefs)
    return NotifPrefResponse.merged(_overrides(rows))


# --- Danger zone (owner-only) ------------------------------------------------
@router.post("/settings/danger/reset")
async def reset_settings(repo: SettingsRepoDep, actor: OwnerOnly) -> dict[str, Any]:
    """Reset the workspace + security settings to their defaults (owner-only)."""
    ws = await asyncio.to_thread(repo.update_workspace, dict(WORKSPACE_DEFAULTS))
    sec = await asyncio.to_thread(repo.update_security, dict(SECURITY_DEFAULTS))
    await record_activity(
        actor, kind="access", action="reset workspace & security settings",
        target="Settings",
    )
    return {
        "workspace": WorkspaceSettingsResponse.from_row(ws).model_dump(by_alias=True),
        "security": SecurityPolicyResponse.from_row(sec).model_dump(by_alias=True),
    }


@router.post("/settings/danger/purge-activity", status_code=status.HTTP_200_OK)
async def purge_activity(repo: SettingsRepoDep, actor: OwnerOnly) -> dict[str, int]:
    """Hard-delete every activity-log entry (owner-only). The purge itself is then
    recorded as the first entry of the fresh log."""
    removed = await asyncio.to_thread(repo.purge_activity)
    await record_activity(
        actor, kind="access", action="purged the activity log", target="Activity log"
    )
    return {"purged": removed}
