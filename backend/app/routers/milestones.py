"""Milestones module endpoints: the client-facing project timeline (read-only for
the dashboard) and the recently-auto-advanced feed.

Reads require any provisioned staff (``view_reports``, which a portal client does
NOT hold - so clients are 403'd out of this namespace, mirroring tasks/audits).
Stages are AUTO-ADVANCED from delivery events (the ``advance_stage`` write path on
the repo, wired to job/audit/publish events in a later chunk) - there are NO manual
stage edits here. Responses are the frontend ``ClientProject`` / ``AutoAdvance``
shapes (``lib/milestones.ts``); the internal ``client_id`` never leaks.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_perm
from app.core.pagination import PageDep
from app.db.milestones_repo import MilestonesRepoDep
from app.schemas.milestones import (
    AutoAdvanceResponse,
    ClientProjectResponse,
)

router = APIRouter(tags=["milestones"])

# All six staff roles hold view_reports; a portal client does NOT (mirrors
# tasks.py / audits.py - clients are confined out of the staff namespace).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]


@router.get("/milestones", response_model=list[ClientProjectResponse])
async def list_milestones(
    repo: MilestonesRepoDep, page: PageDep, _user: ViewReports
) -> list[ClientProjectResponse]:
    """The client projects with their ordered 5-stage timelines (newest first).

    Loads the page of projects, then their stages in one query, and groups the
    stages under each project so every ``ClientProject`` carries its own stages."""
    projects = await asyncio.to_thread(repo.list_projects, limit=page.limit, offset=page.offset)
    project_ids = [str(p["id"]) for p in projects]
    stage_rows = await asyncio.to_thread(repo.list_stages, project_ids)

    by_project: dict[str, list[dict[str, Any]]] = {}
    for row in stage_rows:
        by_project.setdefault(str(row["project_id"]), []).append(row)

    return [
        ClientProjectResponse.from_rows(p, by_project.get(str(p["id"]), []))
        for p in projects
    ]


@router.get("/milestones/auto-advance", response_model=list[AutoAdvanceResponse])
async def list_auto_advances(
    repo: MilestonesRepoDep, page: PageDep, _user: ViewReports
) -> list[AutoAdvanceResponse]:
    """The recently-auto-advanced feed: the most-recently-touched stages (each has
    left ``upcoming``) mapped to the ``AutoAdvance`` shape, newest first."""
    rows = await asyncio.to_thread(repo.recent_advances, limit=page.limit, offset=page.offset)
    return [AutoAdvanceResponse.from_row(r) for r in rows]
