"""User administration: the roster, provisioning, feature-grant editing.

There is no public signup. ``POST /admin/users`` (explicit password) and
``POST /admin/users/invite`` (server-generated one-time credentials) are the only
ways an account is created; both require ``manage_team`` and only an owner may
mint owner/admin accounts (privilege-escalation guard). ``GET``/``PUT
/admin/users/{id}/grants`` read and edit a user's per-feature access and require
``access_control`` (owner-only by the default matrix); an owner is all-on and
locked, so their grants can never be edited.

The roster (``GET /admin/users`` and ``GET /me``) is overlaid with real
performance metrics from :mod:`app.services.team_metrics` (7F-3).
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.db.database import (
    DatabaseNotConfiguredError,
    privileged_connection,
    rls_connection,
)
from app.logging_setup import get_logger
from app.rbac import FEATURE_KEYS, AccessLevel, effective_feature_level
from app.schemas.identity import (
    InviteMemberRequest,
    MemberInviteResponse,
    MemberResponse,
    ProvisionUserRequest,
    UpdateGrantsRequest,
    UserGrantsResponse,
)
from app.services.activity import record_activity
from app.services.credentials import generate_password, generate_username
from app.services.provisioning import provision_user
from app.services.team_metrics import ZERO_METRICS, TeamMetricsDep

router = APIRouter(prefix="/admin/users", tags=["admin"])
logger = get_logger("app.admin_users")

_ELEVATED_ROLES = frozenset({"owner", "admin"})

ManageTeam = Annotated[CurrentUser, Depends(require_perm("manage_team"))]
# Editing feature access is the access_control permission (owner-only by default).
AccessControl = Annotated[CurrentUser, Depends(require_perm("access_control"))]

_DB_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
)
_USER_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")


def _fetch_all_users(
    user_id: str, *, limit: int | None = None, offset: int = 0
) -> list[dict[str, Any]]:
    """Read the STAFF roster via the RLS-scoped ``rls_connection`` (staff sees all).

    Portal clients (role='client') are excluded in SQL (``role <> 'client'``):
    they are tenant logins, not agency team members, and must never appear in the
    Team screen. Blocking; the caller offloads with ``to_thread``.
    """
    query = "select * from public.users where role <> 'client' order by created_at"
    params: list[Any] = []
    if limit is not None:
        query += " limit %s offset %s"
        params += [limit, offset]
    with rls_connection(user_id) as cur:
        cur.execute(query, params)
        return cur.fetchall()


def _load_user_min(caller_id: str, target_id: str) -> dict[str, Any] | None:
    """Load ``{id, role}`` for ``target_id`` via the RLS-scoped path (staff reads roster)."""
    with rls_connection(caller_id) as cur:
        cur.execute("select id, role from public.users where id = %s limit 1", (target_id,))
        return cur.fetchone()


def _read_grant_overrides(caller_id: str, target_id: str) -> dict[str, AccessLevel]:
    """Read a user's stored per-feature overrides (RLS-scoped; staff may read any)."""
    with rls_connection(caller_id) as cur:
        cur.execute(
            "select feature_key, level from public.user_feature_grants where user_id = %s",
            (target_id,),
        )
        return {r["feature_key"]: r["level"] for r in cur.fetchall()}


def _write_grant_overrides(target_id: str, grants: Mapping[str, str]) -> None:
    """Upsert per-feature levels via the PRIVILEGED (service_role) connection.

    Editing another user's grants is a privileged system operation - the RLS
    ``user_feature_grants_modify`` policy is keyed to ``auth.uid()``'s app role,
    which the privileged pool does not set - so it runs on service_role like
    provisioning. The ``updated_at`` trigger stamps the change automatically.
    """
    with privileged_connection() as cur:
        cur.executemany(
            "insert into public.user_feature_grants (user_id, feature_key, level) "
            "values (%s, %s, %s) "
            "on conflict (user_id, feature_key) do update set level = excluded.level",
            [(target_id, key, level) for key, level in grants.items()],
        )


def _resolve_grants(role: str, overrides: dict[str, AccessLevel]) -> dict[str, AccessLevel]:
    """Effective level for all 17 features (owner = all full; else override or off)."""
    return {
        key: effective_feature_level(cast("Any", role), overrides, key) for key in FEATURE_KEYS
    }


async def _overlay_metrics(
    metrics: TeamMetricsDep, members: list[MemberResponse]
) -> list[MemberResponse]:
    """Overlay real performance metrics onto roster rows (best-effort).

    If the metrics aggregation is unavailable (e.g. the DB is not configured on
    this path) the roster still renders with zeroed metrics rather than failing.
    """
    if not members:
        return members
    try:
        scored = await asyncio.to_thread(metrics.member_metrics, [m.id for m in members])
    except DatabaseNotConfiguredError:
        logger.warning("roster_metrics_unavailable")
        return members
    out: list[MemberResponse] = []
    for m in members:
        s = scored.get(m.id, ZERO_METRICS)
        out.append(
            m.model_copy(
                update={
                    "active_tasks": s.active_tasks,
                    "completed": s.completed,
                    "on_time": s.on_time,
                    "utilization": s.utilization,
                    "quality": s.quality,
                }
            )
        )
    return out


@router.get("", response_model=list[MemberResponse])
async def list_users(
    page: PageDep,
    metrics: TeamMetricsDep,
    user: ManageTeam,
) -> list[MemberResponse]:
    """List the agency roster (frontend ``TeamMemberRecord`` shape) with live metrics."""
    try:
        rows = await asyncio.to_thread(
            _fetch_all_users, user.id, limit=page.limit, offset=page.offset
        )
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    members = [MemberResponse.from_row(r) for r in rows]
    return await _overlay_metrics(metrics, members)


@router.post("", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: ProvisionUserRequest,
    current: ManageTeam,
) -> MemberResponse:
    """Provision a local credential + identity row (owner-only for owner/admin)."""
    if body.role in _ELEVATED_ROLES and not current.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can create owner/admin users",
        )
    try:
        row = await asyncio.to_thread(
            provision_user,
            email=str(body.email),
            password=body.password.get_secret_value(),
            name=body.name,
            role=body.role,
            username=body.username,
            title=body.title,
            avatar_color=body.avatar_color,
            template_key=body.template,
        )
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    except Exception as exc:
        # Duplicate email / auth rejection / write failure. Log server-side (no
        # secret in the payload) and return a generic client error, never a 500.
        logger.warning("provision_user_failed", actor=current.id, error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create user (email may already exist)",
        ) from exc

    await record_activity(
        current, kind="member", action="provisioned member", target=body.name, meta=body.role,
        entity_type="user", entity_id=str(row["id"]),
    )
    return MemberResponse.from_row(row)


@router.post("/invite", response_model=MemberInviteResponse, status_code=status.HTTP_201_CREATED)
async def invite_member(
    body: InviteMemberRequest,
    current: ManageTeam,
) -> MemberInviteResponse:
    """Add a team member with GENERATED one-time credentials (mirrors the wizard).

    Picks a role template (or an explicit feature list) to seed ``user_feature_grants``,
    generates a username + strong temp password, provisions with reset-on-first-login
    + 2FA-on-first-login flags, and returns ``{username, tempPassword}`` ONCE (only the
    argon2id hash is stored). Owner-only for owner/admin roles (escalation guard).
    """
    if body.role in _ELEVATED_ROLES and not current.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can create owner/admin users",
        )
    username = generate_username(body.name)
    temp_password = generate_password()
    # Explicit custom toggles win over a template; each granted feature is 'full'.
    feature_grants: dict[str, AccessLevel] | None = (
        cast("dict[str, AccessLevel]", dict.fromkeys(body.features, "full"))
        if body.features is not None
        else None
    )
    try:
        row = await asyncio.to_thread(
            provision_user,
            email=str(body.email),
            password=temp_password,
            name=body.name,
            role=body.role,
            username=username,
            title=body.title,
            avatar_color=body.avatar_color,
            template_key=body.template,
            feature_grants=feature_grants,
            must_reset=True,
            must_setup_2fa=True,
        )
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    except Exception as exc:
        logger.warning("invite_member_failed", actor=current.id, error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create user (email or username may already exist)",
        ) from exc

    await record_activity(
        current, kind="member", action="invited member", target=body.name, meta=body.role,
        entity_type="user", entity_id=str(row["id"]),
    )
    return MemberInviteResponse(
        member=MemberResponse.from_row(row), username=username, temp_password=temp_password
    )


@router.get("/{user_id}/grants", response_model=UserGrantsResponse)
async def get_grants(user_id: str, current: AccessControl) -> UserGrantsResponse:
    """Read a user's effective access level for all 17 features (access_control)."""
    try:
        target = await asyncio.to_thread(_load_user_min, current.id, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if target is None:
        raise _USER_NOT_FOUND
    role = str(target["role"])
    if role == "client":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Clients have no feature grants"
        )
    overrides = await asyncio.to_thread(_read_grant_overrides, current.id, user_id)
    return UserGrantsResponse(grants=_resolve_grants(role, overrides))


@router.put("/{user_id}/grants", response_model=UserGrantsResponse)
async def set_grants(
    user_id: str, body: UpdateGrantsRequest, current: AccessControl
) -> UserGrantsResponse:
    """Set a user's per-feature access levels (access_control). Owner is locked all-on."""
    try:
        target = await asyncio.to_thread(_load_user_min, current.id, user_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    if target is None:
        raise _USER_NOT_FOUND
    role = str(target["role"])
    if role == "owner":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Owner access is all-on and cannot be edited",
        )
    if role == "client":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Clients have no feature grants"
        )

    if body.grants:
        await asyncio.to_thread(_write_grant_overrides, user_id, body.grants)
        await record_activity(
            current, kind="access", action="updated feature access", target=role,
            entity_type="user", entity_id=user_id,
        )

    overrides = await asyncio.to_thread(_read_grant_overrides, current.id, user_id)
    return UserGrantsResponse(grants=_resolve_grants(role, overrides))
