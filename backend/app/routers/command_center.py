"""Command Center (admin-home) aggregate endpoint - 7C-4.

ONE read, ``GET /command-center`` (``require_perm("view_reports")`` - all six staff
roles hold it, a portal client does NOT, so clients are 403'd out), returning the
whole admin-home payload: KPI stat tiles + the four chart series (audits / traffic /
team / clients) + the Policy-Radar digest (top OPEN recs) + the spend snapshot.

It REUSES the existing RLS-scoped repos (audits / clients / tasks(me) / cost /
policy) - no new tenant table beyond the R3 overlay - and hands their rows to the
PURE builders in ``app/schemas/command_center.py``. Every blocking psycopg call is
offloaded with ``asyncio.to_thread``. The ``traffic`` series is an explicit
audit-derived PLACEHOLDER (flagged ``placeholder: true``): audits are URL-only, so
the platform has no live organic-traffic signal yet (N8).
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.core.auth import CurrentUser, require_perm
from app.db.audits_repo import AuditsRepoDep
from app.db.clients_repo import ClientsRepoDep
from app.db.cost_repo import CostRepoDep
from app.db.policy_repo import PolicyRepoDep
from app.db.tasks_repo import TasksRepo, TasksRepoDep
from app.schemas.command_center import CommandCenterResponse, build_command_center

router = APIRouter(tags=["command-center"])

# All six staff roles hold view_reports; a portal client does NOT (mirrors the rest
# of the staff namespace), so a client is 403'd before any repo read runs.
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]


def _resolve_assignees(
    tasks_repo: TasksRepo, tasks: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Resolve each distinct task assignee to its user row (name/color for the team
    chart). Runs the per-user reads on ONE worker thread (the caller offloads it)."""
    ids = {str(t["assignee_id"]) for t in tasks if t.get("assignee_id") is not None}
    resolved: dict[str, dict[str, Any]] = {}
    for uid in ids:
        user = tasks_repo.get_user(uid)
        if user is not None:
            resolved[uid] = user
    return resolved


@router.get("/command-center", response_model=CommandCenterResponse)
async def command_center(
    audits_repo: AuditsRepoDep,
    clients_repo: ClientsRepoDep,
    tasks_repo: TasksRepoDep,
    cost_repo: CostRepoDep,
    policy_repo: PolicyRepoDep,
    _user: ViewReports,
) -> CommandCenterResponse:
    """The admin-home aggregate (staff-only). Reuses the module repos + pure builders;
    aggregation reads are unbounded (a dashboard rollup, like /audits/stats)."""
    audits = await asyncio.to_thread(audits_repo.list_audits)
    clients = await asyncio.to_thread(clients_repo.list_clients)
    tasks = await asyncio.to_thread(tasks_repo.list_tasks)
    budgets = await asyncio.to_thread(cost_repo.list_budgets)
    settings = await asyncio.to_thread(cost_repo.get_settings)
    rec_rows = await asyncio.to_thread(policy_repo.list_recommendations)
    users_by_id = await asyncio.to_thread(_resolve_assignees, tasks_repo, tasks)

    return build_command_center(
        audits=audits,
        clients=clients,
        tasks=tasks,
        users_by_id=users_by_id,
        budgets=budgets,
        settings=settings,
        rec_rows=rec_rows,
    )
