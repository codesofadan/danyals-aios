"""User administration: list the roster + provision new users (super-admin).

There is no public signup. ``POST /admin/users`` is the only way an account is
created; it requires ``manage_team``, and only an owner may mint owner/admin
accounts (privilege-escalation guard).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.db.database import DatabaseNotConfiguredError, rls_connection
from app.db.supabase import SupabaseNotConfiguredError, get_admin_client
from app.logging_setup import get_logger
from app.schemas.identity import MemberResponse, ProvisionUserRequest
from app.services.activity import record_activity
from app.services.provisioning import provision_user

router = APIRouter(prefix="/admin/users", tags=["admin"])
logger = get_logger("app.admin_users")

_ELEVATED_ROLES = frozenset({"owner", "admin"})


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


@router.get("", response_model=list[MemberResponse])
async def list_users(
    page: PageDep,
    user: Annotated[CurrentUser, Depends(require_perm("manage_team"))],
) -> list[MemberResponse]:
    """List the agency roster in the frontend ``TeamMemberRecord`` shape."""
    try:
        rows = await asyncio.to_thread(
            _fetch_all_users, user.id, limit=page.limit, offset=page.offset
        )
    except DatabaseNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
        ) from exc
    return [MemberResponse.from_row(r) for r in rows]


@router.post("", response_model=MemberResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: ProvisionUserRequest,
    current: Annotated[CurrentUser, Depends(require_perm("manage_team"))],
) -> MemberResponse:
    """Provision a Supabase Auth user + identity row (owner-only for owner/admin)."""
    if body.role in _ELEVATED_ROLES and not current.is_owner:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a super-admin can create owner/admin users",
        )
    try:
        admin = get_admin_client()
    except SupabaseNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
        ) from exc

    try:
        row = await asyncio.to_thread(
            provision_user,
            admin,
            email=str(body.email),
            password=body.password.get_secret_value(),
            name=body.name,
            role=body.role,
            title=body.title,
            avatar_color=body.avatar_color,
            template_key=body.template,
        )
    except Exception as exc:
        # Duplicate email / auth rejection / write failure. Log server-side (no
        # secret in the payload) and return a generic client error, never a 500.
        logger.warning("provision_user_failed", actor=current.id, error_type=type(exc).__name__)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Could not create user (email may already exist)",
        ) from exc

    await record_activity(
        current, kind="member", action="provisioned member", target=body.name, meta=body.role
    )
    return MemberResponse.from_row(row)
