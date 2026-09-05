"""Team roster endpoint - the eligible-assignee source for the /tasks assign flow.

``GET /team/members`` returns the FULL agency staff roster (frontend
``TeamMemberRecord`` shape) with live performance metrics overlaid: the exact list
the Assign-Tasks picker chooses an assignee from.

WHY THIS EXISTS (the assignee bug): the picker used to source its members from the
``manage_team``-only admin roster AND then hide every member whose status was still
``invited``. A freshly added member starts ``invited`` and only flips to ``active``
on their first sign-in, so newly-added staff never appeared in the dropdown even
though the /tasks guard happily accepts them. This endpoint returns EVERY eligible
staff member (any of the 6 governance roles, ANY status) and is gated on
``assign_tasks`` (owner/admin/manager) - the permission that actually governs who
assigns work - so a manager who lacks ``manage_team`` can still load the picker.

Reads are RLS-scoped (staff see the whole roster); portal clients are excluded in
SQL and, lacking ``assign_tasks``, are 403'd out of this namespace anyway. The
metric overlay reuses the admin roster's helper so the two roster shapes never
drift.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.core.ratelimit import rate_limit
from app.db.database import DatabaseNotConfiguredError, rls_connection
from app.db.team_repo import TeamRepoDep
from app.routers.admin_users import _overlay_metrics
from app.schemas.identity import MemberResponse
from app.services.team_metrics import TeamMetricsDep
from app.services.team_requests import create_team_request

router = APIRouter(prefix="/team", tags=["team"])

# Assigning/routing work is the assign_tasks permission (owner/admin/manager); this
# is the roster THAT flow reads, so it shares that gate rather than manage_team.
AssignTasks = Annotated[CurrentUser, Depends(require_perm("assign_tasks"))]

_DB_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
)


@router.get("/members", response_model=list[MemberResponse])
async def list_team_members(
    repo: TeamRepoDep, page: PageDep, metrics: TeamMetricsDep, _user: AssignTasks
) -> list[MemberResponse]:
    """The eligible-assignee staff roster with live performance metrics.

    Every non-client staff member, INCLUDING invited-but-not-yet-signed-in members
    (they are valid assignees), so the assign picker shows all eligible staff.
    """
    try:
        rows = await asyncio.to_thread(repo.list_staff, limit=page.limit, offset=page.offset)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    members = [MemberResponse.from_row(r) for r in rows]
    return await _overlay_metrics(metrics, members)


# --------------------------------------------------------------------------- #
# Team requests (0127) - a member asking the leads for something
# --------------------------------------------------------------------------- #
# Gated on `view_own_tasks`, NOT on `assign_tasks` like the roster above. Raising a
# request is the one thing in this namespace EVERY staff member must be able to do;
# gating it on the lead-only permission would leave exactly the people who need to ask
# unable to. Reads go through the `team_requests` view, which is filtered to
# `auth.uid()` in SQL, so a member can only ever see their own.
class TeamRequestCreate(BaseModel):
    """POST /team/requests body. `client_id` and `created_by` are never accepted here -
    both are pinned server-side (see services/team_requests)."""

    subject: str = Field(min_length=3, max_length=200)
    detail: str = Field(default="", max_length=4000)
    kind: Literal["Report", "Access", "Support", "Feature", "Billing"] = "Support"


class TeamRequestResponse(BaseModel):
    """One of the caller's own team requests."""

    code: str
    subject: str
    detail: str = ""
    kind: str = "Support"
    status: str = "open"
    priority: str = "med"
    opened_at: str | None = None
    reply: str = ""
    replied_at: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TeamRequestResponse:
        def _iso(v: Any) -> str | None:
            return v.isoformat() if isinstance(v, datetime) else (str(v) if v else None)

        return cls(
            code=str(row.get("code") or ""),
            subject=str(row.get("subject") or ""),
            detail=str(row.get("detail") or ""),
            kind=str(row.get("kind") or "Support"),
            status=str(row.get("status") or "open"),
            priority=str(row.get("priority") or "med"),
            opened_at=_iso(row.get("opened_at") or row.get("created_at")),
            reply=str(row.get("reply") or ""),
            replied_at=_iso(row.get("replied_at")),
        )


ViewOwnTasks = Annotated[CurrentUser, Depends(require_perm("view_own_tasks"))]


@router.get("/requests", response_model=list[TeamRequestResponse])
async def list_team_requests(user: ViewOwnTasks, page: PageDep) -> list[TeamRequestResponse]:
    """The caller's OWN team requests, newest first."""

    def _read() -> list[dict[str, Any]]:
        with rls_connection(user.id) as cur:
            cur.execute(
                "select * from public.team_requests order by opened_at desc limit %s offset %s",
                (page.limit, page.offset),
            )
            return list(cur.fetchall())

    try:
        rows = await asyncio.to_thread(_read)
    except DatabaseNotConfiguredError:
        raise _DB_NOT_CONFIGURED from None
    return [TeamRequestResponse.from_row(r) for r in rows]


@router.post(
    "/requests",
    response_model=TeamRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("team_request_create", 30))],
)
async def create_team_request_route(
    body: TeamRequestCreate, user: ViewOwnTasks
) -> TeamRequestResponse:
    """Raise a request to the leads (status `open`) and alert them by email + in-app."""
    row = await create_team_request(
        user=user, subject=body.subject, detail=body.detail, kind=body.kind
    )
    return TeamRequestResponse.from_row(row)
