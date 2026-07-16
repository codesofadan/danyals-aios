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

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_perm
from app.db.tasks_repo import TasksRepoDep
from app.schemas.identity import MemberResponse
from app.services.team_metrics import ZERO_METRICS, TeamMetricsDep

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
async def get_me(repo: TasksRepoDep, metrics: TeamMetricsDep, user: ViewReports) -> MemberResponse:
    """Return the caller's own team record with live counts + real metrics."""
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
