"""Part 5 Team Flow endpoints: the task queue, the workflow board, and the
content review checkpoint. Reads require any provisioned staff (``view_reports``,
which a portal client does NOT hold - so clients are 403'd out of this
namespace); creating/reassigning requires ``assign_tasks``; signing off the
review gate requires an owner/admin/manager (``CAN_REVIEW``).

Responses are the frontend ``Task`` shape (``id`` = the public ``J-####`` code).
The app-layer 403/409 here are clean UX; the real lifecycle boundary is the
``tasks_guard_update`` DB trigger (a non-lead cannot skip review even via a
direct PostgREST PATCH). Every mutation offloads the blocking supabase-py call
with ``asyncio.to_thread`` and appends an activity entry.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.pagination import PageDep
from app.db.clients_repo import ClientsRepoDep
from app.db.tasks_repo import TasksRepoDep
from app.schemas.activity import ActivityKind
from app.schemas.tasks import (
    TaskCreate,
    TaskResponse,
    TaskReviewRequest,
    TaskUpdate,
    needs_review,
    next_status,
    type_to_db,
)
from app.services.activity import record_activity

router = APIRouter(tags=["tasks"])

# All six staff roles hold view_reports; a portal client does NOT, confining
# clients out of the staff task namespace (mirrors audits.py / D10).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
AssignTasks = Annotated[CurrentUser, Depends(require_perm("assign_tasks"))]
# The content review gate = CAN_REVIEW (owner/admin/manager); owner auto-passes.
CanReview = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_LEAD_ROLES = frozenset({"owner", "admin", "manager"})

_TASK_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")


def _is_lead(user: CurrentUser) -> bool:
    """Whether the caller may assign/route/review (the assign_tasks holders)."""
    return user.role in _LEAD_ROLES


async def _require_staff_assignee(repo: TasksRepoDep, assignee_id: str) -> None:
    """Reject an assignee that is missing (404) or a portal client (400).

    Mirrors the DB guard (tasks_guard_insert/update): a task is never pointed at
    a client uid. Enforced here for a clean error and at the DB as the boundary.
    """
    row = await asyncio.to_thread(repo.get_user, assignee_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee not found")
    if row.get("role") == "client":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee must be a staff member"
        )


def _advance_action(new_status: str) -> str:
    """The activity verb for a lifecycle advance."""
    if new_status == "in_progress":
        return "started a task"
    if new_status == "review":
        return "submitted for review"
    return "delivered a task"  # done


@router.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(
    repo: TasksRepoDep,
    page: PageDep,
    _user: ViewReports,
    mine: Annotated[bool, Query()] = False,
    assignee: Annotated[str | None, Query()] = None,
) -> list[TaskResponse]:
    """List tasks (created_at desc). ``mine=true`` scopes to the caller; an
    explicit ``assignee`` scopes to that user; otherwise the whole board."""
    scope = _user.id if mine else assignee
    rows = await asyncio.to_thread(repo.list_tasks, scope, limit=page.limit, offset=page.offset)
    return [TaskResponse.from_row(r) for r in rows]


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    repo: TasksRepoDep,
    clients: ClientsRepoDep,
    actor: AssignTasks,
) -> TaskResponse:
    """Assign a new work item (status=todo). Validates the client + a staff
    assignee, snapshots the client name, and records activity."""
    client = await asyncio.to_thread(clients.get_client, body.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    await _require_staff_assignee(repo, body.assignee_id)

    row = await asyncio.to_thread(
        repo.insert_task,
        {
            "title": body.title,
            "client_id": body.client_id,
            "client_name": client.get("name", ""),
            "type": type_to_db(body.type),
            "assignee_id": body.assignee_id,
            "priority": body.priority,
            "status": "todo",
            "due_date": body.due.isoformat() if body.due else None,
            "created_by": actor.id,
        },
    )
    await record_activity(
        actor, kind="task", action="assigned a task", target=client.get("name", "")
    )
    return TaskResponse.from_row(row)


@router.post("/tasks/{code}/advance", response_model=TaskResponse)
async def advance_task(code: str, repo: TasksRepoDep, actor: ViewReports) -> TaskResponse:
    """Advance a task one legal step. The assignee OR a lead may act; a task in
    ``review``/``done`` (or with no next step) is 409 (review uses /review)."""
    task = await asyncio.to_thread(repo.get_task_by_code, code)
    if task is None:
        raise _TASK_NOT_FOUND
    if task.get("assignee_id") != actor.id and not _is_lead(actor):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Only the assignee or a lead may advance"
        )

    current = str(task.get("status"))
    type_canonical = str(task.get("type"))
    if current in {"review", "done"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Task is not advanceable from its current status",
        )
    nxt = next_status(type_canonical, current)
    if nxt is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="No further transition for this task"
        )

    updated = await asyncio.to_thread(
        repo.update_task_by_code, code, {"status": nxt}, current
    )
    if updated is None:
        # A racing transition already moved the row (optimistic concurrency).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task changed concurrently")

    kind: ActivityKind = "content" if needs_review(type_canonical) else "task"
    await record_activity(
        actor, kind=kind, action=_advance_action(nxt), target=task.get("client_name", "")
    )
    return TaskResponse.from_row(updated)


@router.post("/tasks/{code}/review", response_model=TaskResponse)
async def review_task(
    code: str, body: TaskReviewRequest, repo: TasksRepoDep, actor: CanReview
) -> TaskResponse:
    """Sign off (or reject) a task at the content review gate. Owner/admin/manager
    only. Approve -> done; reject -> in_progress. 409 unless status is review."""
    task = await asyncio.to_thread(repo.get_task_by_code, code)
    if task is None:
        raise _TASK_NOT_FOUND
    if task.get("status") != "review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Task is not awaiting review"
        )

    new_status = "done" if body.action == "approve" else "in_progress"
    updated = await asyncio.to_thread(
        repo.update_task_by_code, code, {"status": new_status}, "review"
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task changed concurrently")

    action = "approved for delivery" if body.action == "approve" else "sent back for changes"
    await record_activity(
        actor, kind="content", action=action, target=task.get("client_name", "")
    )
    return TaskResponse.from_row(updated)


@router.patch("/tasks/{code}", response_model=TaskResponse)
async def patch_task(
    code: str, body: TaskUpdate, repo: TasksRepoDep, actor: AssignTasks
) -> TaskResponse:
    """Reassign / repriority / redue a task (lead-only). Status is untouched here
    (it moves only via /advance and /review)."""
    task = await asyncio.to_thread(repo.get_task_by_code, code)
    if task is None:
        raise _TASK_NOT_FOUND

    provided = body.model_dump(exclude_unset=True)
    patch: dict[str, Any] = {}
    if "assignee_id" in provided and provided["assignee_id"] is not None:
        await _require_staff_assignee(repo, provided["assignee_id"])
        patch["assignee_id"] = provided["assignee_id"]
    if "priority" in provided and provided["priority"] is not None:
        patch["priority"] = provided["priority"]
    if "due" in provided:
        due = provided["due"]
        patch["due_date"] = due.isoformat() if due is not None else None

    if not patch:
        return TaskResponse.from_row(task)  # nothing to change

    updated = await asyncio.to_thread(repo.update_task_by_code, code, patch)
    if updated is None:
        raise _TASK_NOT_FOUND
    await record_activity(
        actor, kind="task", action="updated a task", target=task.get("client_name", "")
    )
    return TaskResponse.from_row(updated)
