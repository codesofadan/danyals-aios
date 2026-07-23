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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.db.database import DatabaseNotConfiguredError
from app.db.team_repo import TeamRepoDep
from app.routers.admin_users import _overlay_metrics
from app.schemas.identity import MemberResponse
from app.services.team_metrics import TeamMetricsDep

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
