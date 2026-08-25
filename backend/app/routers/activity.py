"""Activity feed endpoint - the admin monitor. Any provisioned staff may read.

Staff-only at the APP tier, not merely at the database: the feed is the agency's own
operational record. ``activity_log_select`` already restricts it to ``is_staff()``, so
the outcome was correct - but the route granted nothing itself, and a single policy
regression would have opened it silently.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_staff
from app.core.pagination import PageDep
from app.db.activity_repo import ActivityRepoDep
from app.schemas.activity import ActivityResponse

Staff = Annotated[CurrentUser, Depends(require_staff())]

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=list[ActivityResponse])
async def list_activity(
    repo: ActivityRepoDep,
    page: PageDep,
    _user: Staff,
) -> list[ActivityResponse]:
    """Most-recent activity first (newest at the top of the admin monitor)."""
    rows = await asyncio.to_thread(repo.list_activity, page.limit, page.offset)
    return [ActivityResponse.from_row(r) for r in rows]
