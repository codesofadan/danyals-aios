"""The signed-in member's own record (frontend ``TeamMemberRecord`` shape).

``GET /me`` returns the caller as a ``MemberResponse`` with LIVE task counts
overlaid: ``activeTasks`` = my tasks not yet ``done``, ``completed`` = my ``done``
tasks (both from the ``tasks`` ledger, RLS-scoped to the caller). The remaining
metrics (onTime/utilization/quality) need historical job data and stay at their
defaults until Part 6.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_perm
from app.db.tasks_repo import TasksRepoDep
from app.schemas.identity import MemberResponse

router = APIRouter(tags=["me"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]


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


@router.get("/me", response_model=MemberResponse)
async def get_me(repo: TasksRepoDep, user: ViewReports) -> MemberResponse:
    """Return the caller's own team record with live active/completed counts."""
    row = await asyncio.to_thread(repo.get_user, user.id)
    member = MemberResponse.from_row(row if row is not None else _row_from_user(user))

    tasks = await asyncio.to_thread(repo.list_tasks, user.id)
    active = sum(1 for t in tasks if t.get("status") != "done")
    completed = sum(1 for t in tasks if t.get("status") == "done")
    return member.model_copy(update={"active_tasks": active, "completed": completed})
