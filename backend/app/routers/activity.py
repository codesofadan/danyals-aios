"""Activity feed endpoint - the admin monitor. Any provisioned staff may read."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter

from app.core.auth import CurrentUserDep
from app.core.pagination import PageDep
from app.db.activity_repo import ActivityRepoDep
from app.schemas.activity import ActivityResponse

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=list[ActivityResponse])
async def list_activity(
    repo: ActivityRepoDep,
    page: PageDep,
    _user: CurrentUserDep,
) -> list[ActivityResponse]:
    """Most-recent activity first (newest at the top of the admin monitor)."""
    rows = await asyncio.to_thread(repo.list_activity, page.limit, page.offset)
    return [ActivityResponse.from_row(r) for r in rows]
