"""Activity feed endpoint - the admin monitor. Any provisioned staff may read."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Query

from app.core.auth import CurrentUserDep
from app.db.activity_repo import ActivityRepoDep
from app.schemas.activity import ActivityResponse

router = APIRouter(prefix="/activity", tags=["activity"])


@router.get("", response_model=list[ActivityResponse])
async def list_activity(
    repo: ActivityRepoDep,
    _user: CurrentUserDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[ActivityResponse]:
    """Most-recent activity first (newest at the top of the admin monitor)."""
    rows = await asyncio.to_thread(repo.list_activity, limit)
    return [ActivityResponse.from_row(r) for r in rows]
