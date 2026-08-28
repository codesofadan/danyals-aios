"""The signed-in member's own record (frontend ``TeamMemberRecord`` shape).

``GET /me`` returns the caller as a ``MemberResponse`` with LIVE performance
metrics overlaid, all RLS-scoped to the caller: ``activeTasks`` / ``completed``
(from the ``tasks`` ledger) plus the real ``onTime`` / ``utilization`` / ``quality``
percentages (7F-3), computed by :mod:`app.services.team_metrics` from the tasks +
activity ledgers. See that module for each formula.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm
from app.db.database import DatabaseNotConfiguredError, privileged_connection
from app.db.tasks_repo import TasksRepoDep
from app.schemas.identity import (
    ChangePasswordRequest,
    MemberResponse,
    UpdateMeRequest,
    UserGrantsResponse,
)
from app.services.activity import record_activity
from app.services.passwords import hash_password, verify_password
from app.services.team_metrics import ZERO_METRICS, TeamMetricsDep

router = APIRouter(tags=["me"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]

_DB_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
)


def _row_from_user(user: CurrentUser) -> dict[str, Any]:
    """A MemberResponse-shaped row synthesized from the token (no created_at)."""
    return {
        "id": user.id,
        "name": user.name,
        "avatar_color": user.avatar_color,
        "title": user.title,
        "email": user.email,
        "role": user.role,
        "status": user.status,
        "created_at": None,
    }


async def _member_response(repo: TasksRepoDep, metrics: TeamMetricsDep, user: CurrentUser) -> MemberResponse:
    """The caller's own record with LIVE counts + real metrics overlaid (shared by
    every ``/me`` route that returns a member, so a profile edit reflects the same
    shape a plain read would)."""
    row = await asyncio.to_thread(repo.get_user, user.id)
    member = MemberResponse.from_row(row if row is not None else _row_from_user(user))

    scored = await asyncio.to_thread(metrics.member_metrics, [user.id])
    m = scored.get(user.id, ZERO_METRICS)
    return member.model_copy(
        update={
            "active_tasks": m.active_tasks,
            "completed": m.completed,
            "on_time": m.on_time,
            "utilization": m.utilization,
            "quality": m.quality,
        }
    )


def _update_own_profile(user_id: str, changes: dict[str, Any]) -> None:
    """Update ONLY the provided profile fields for ``user_id`` (never any other row).

    Runs on ``privileged_connection`` (service_role) with the target PINNED to the
    caller's verified id, never a body/path value: the ``users_modify`` RLS policy
    only allows owner/admin to write ANY row via ``rls_connection``, so a non-admin
    member editing their OWN profile would silently affect 0 rows there. This mirrors
    ``admin_users._write_grant_overrides``'s same justification for the same
    privileged-but-self-scoped shape. Column names are fixed (never built from the
    request), so there is no dynamic-SQL surface.
    """
    with privileged_connection() as cur:
        cur.execute(
            """
            update public.users
            set name = coalesce(%(name)s, name),
                title = coalesce(%(title)s, title),
                email = coalesce(%(email)s, email)
            where id = %(id)s
            """,
            {"name": changes.get("name"), "title": changes.get("title"),
             "email": changes.get("email"), "id": user_id},
        )


def _lookup_own_password_hash(user_id: str) -> str | None:
    """The caller's own argon2id hash (``auth.users`` is service_role-only)."""
    with privileged_connection() as cur:
        cur.execute("select password_hash from auth.users where id = %s limit 1", (user_id,))
        row = cur.fetchone()
        return row["password_hash"] if row else None


def _set_own_password(user_id: str, new_hash: str) -> None:
    with privileged_connection() as cur:
        cur.execute("update auth.users set password_hash = %s where id = %s", (new_hash, user_id))


@router.get("/me", response_model=MemberResponse)
async def get_me(repo: TasksRepoDep, metrics: TeamMetricsDep, user: ViewReports) -> MemberResponse:
    """Return the caller's own team record with live counts + real metrics."""
    return await _member_response(repo, metrics, user)


@router.patch("/me", response_model=MemberResponse)
async def update_me(
    body: UpdateMeRequest, repo: TasksRepoDep, metrics: TeamMetricsDep, user: ViewReports
) -> MemberResponse:
    """Edit the caller's own name/title/email. Every field optional; only those
    provided change. Never accepts role/id, so self-service can't escalate."""
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if changes:
        try:
            await asyncio.to_thread(_update_own_profile, user.id, changes)
        except DatabaseNotConfiguredError as exc:
            raise _DB_NOT_CONFIGURED from exc
        await record_activity(user, kind="member", action="updated own profile", target=user.name)
    return await _member_response(repo, metrics, user)


@router.post("/me/password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(body: ChangePasswordRequest, user: ViewReports) -> None:
    """Change the caller's own password. The current password is verified
    server-side first (never trusted from a prior screen); a mismatch is a 400, not
    a 401 (this is an authenticated self-service action, not a login attempt, so
    there is no user-enumeration concern to hide behind a generic status)."""
    try:
        stored_hash = await asyncio.to_thread(_lookup_own_password_hash, user.id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if stored_hash is None or not verify_password(stored_hash, body.current_password.get_secret_value()):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    new_hash = hash_password(body.new_password.get_secret_value())
    await asyncio.to_thread(_set_own_password, user.id, new_hash)
    await record_activity(user, kind="access", action="changed own password", target=user.name)


@router.get("/me/grants", response_model=UserGrantsResponse)
async def get_my_grants(user: ViewReports) -> UserGrantsResponse:
    """The caller's OWN effective access level for all 17 features - self-serve, no
    ``access_control`` permission required (unlike ``GET /admin/users/{id}/grants``,
    which is owner-only). Always scoped to the verified token's ``user.id``, never a
    path/query param, so there is no escalation surface. ``ViewReports`` already
    excludes portal clients (they hold no feature grants), so no role check is needed
    here (contrast the admin route, which must guard against a client target id).

    Lazily imports the admin_users read helpers rather than duplicating them - the
    same cross-module pattern ``tool_workspaces/router.py`` uses for the roster reader.
    """
    from app.routers.admin_users import _read_grant_overrides, _resolve_grants

    try:
        overrides = await asyncio.to_thread(_read_grant_overrides, user.id, user.id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    return UserGrantsResponse(grants=_resolve_grants(user.role, overrides))
