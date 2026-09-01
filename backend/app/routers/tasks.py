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
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.pagination import PageDep
from app.db.clients_repo import ClientsRepoDep
from app.db.tasks_repo import TasksRepoDep
from app.schemas.activity import ActivityKind
from app.schemas.tasks import (
    DeadlineRequestCreate,
    DeadlineRequestDecideRequest,
    DeadlineRequestResponse,
    TaskAdvanceRequest,
    TaskCreate,
    TaskResponse,
    TaskReviewRequest,
    TaskUpdate,
    needs_review,
    next_status,
    type_from_db,
)
from app.services.activity import record_activity
from app.services.notifications import notify, notify_leads
from app.services.task_assignment import assign_task, require_staff_assignee

# The assignee may request a due-date change only within this window of the
# task's start (or, if not yet started, its assignment). Server-enforced here;
# the frontend mirrors it client-side purely as a UX nicety.
_DEADLINE_REQUEST_WINDOW = timedelta(hours=12)

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


# Moved to `services.task_assignment` so the ticket-conversion path enforces the same
# rule; re-exported under the original private name because three call sites below use
# it. The 404-vs-400 split is preserved exactly.
_require_staff_assignee = require_staff_assignee


def _task_entity(task: dict[str, Any]) -> tuple[str | None, str | None]:
    """The context entity a task mutation should track. A task's work lands on a
    CLIENT's world, so prefer the client_id; a client-less task (client removed)
    falls back to the assignee (a user entity) so the event is still linked."""
    client_id = task.get("client_id")
    if client_id is not None:
        return "client", str(client_id)
    assignee_id = task.get("assignee_id")
    if assignee_id is not None:
        return "user", str(assignee_id)
    return None, None


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
    explicit ``assignee`` scopes to that user; otherwise the whole board.

    ONLY A LEAD SEES THE WHOLE BOARD. `view_reports` is held by all six staff
    roles, so gating on it alone let any team member list every task for every
    client - which is the visibility rule the brief asks to be enforced
    server-side rather than by hiding frontend components. A non-lead is pinned
    to their own queue here, in the route, so the pin holds for any caller: the
    dashboard, a script, curl with a valid token.

    A non-lead asking for someone else's queue is REFUSED rather than silently
    re-scoped to their own - a silent narrowing would show them an empty board
    and let them conclude that person has no work.
    """
    lead = _is_lead(_user)
    if not lead and assignee and assignee != _user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only see your own tasks.",
        )
    scope = _user.id if (mine or not lead) else assignee
    rows = await asyncio.to_thread(repo.list_tasks, scope, limit=page.limit, offset=page.offset)
    return [TaskResponse.from_row(r) for r in rows]


@router.post("/tasks", response_model=TaskResponse, status_code=status.HTTP_201_CREATED)
async def create_task(
    body: TaskCreate,
    repo: TasksRepoDep,
    clients: ClientsRepoDep,
    actor: AssignTasks,
) -> TaskResponse:
    """Assign a new work item (status=todo).

    The work is done by `services.task_assignment.assign_task`, shared with
    `POST /tickets/{code}/convert-to-task` so the two ways a task can come into being
    validate, snapshot, log and notify identically. Two copies of an assignment path
    is how one of them quietly stops notifying its assignee.
    """
    row = await assign_task(
        repo=repo,
        clients=clients,
        actor=actor,
        title=body.title,
        client_id=body.client_id,
        task_type=body.type,
        assignee_id=body.assignee_id,
        priority=body.priority,
        due=body.due,
    )
    return TaskResponse.from_row(row)


@router.post("/tasks/{code}/advance", response_model=TaskResponse)
async def advance_task(
    code: str, repo: TasksRepoDep, actor: ViewReports, body: TaskAdvanceRequest | None = None
) -> TaskResponse:
    """Advance a task one legal step. The assignee OR a lead may act; a task in
    ``review``/``done`` (or with no next step) is 409 (review uses /review).

    An optional ``proof_url`` in the body is the assignee's proof-of-completion link,
    persisted ALONGSIDE the status move (the DB guard allows a non-lead to change
    {status, proof_url} together along a legal transition)."""
    task = await asyncio.to_thread(repo.get_task_by_code, code)
    if task is None:
        raise _TASK_NOT_FOUND
    # assignee_id comes back from psycopg as a uuid.UUID; actor.id is a str -> compare
    # as strings so the assignee is correctly recognised (a raw != would always differ).
    assignee_id = task.get("assignee_id")
    if (str(assignee_id) if assignee_id is not None else None) != actor.id and not _is_lead(actor):
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

    patch: dict[str, Any] = {"status": nxt}
    if body is not None and body.proof_url is not None:
        patch["proof_url"] = body.proof_url
    now = datetime.now(UTC).isoformat()
    # todo -> in_progress is the real "work started" moment; stamp it once (never
    # overwritten if somehow already set).
    if current == "todo" and nxt == "in_progress" and task.get("started_at") is None:
        patch["started_at"] = now
    # A task with NO review gate reaches its terminal state HERE (in_progress ->
    # done); content_sprint's terminal stamp happens on the /review approve path
    # instead (below), never both.
    if nxt == "done":
        patch["completed_at"] = now
    updated = await asyncio.to_thread(repo.update_task_by_code, code, patch, current)
    if updated is None:
        # A racing transition already moved the row (optimistic concurrency).
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task changed concurrently")

    kind: ActivityKind = "content" if needs_review(type_canonical) else "task"
    ent_type, ent_id = _task_entity(task)
    await record_activity(
        actor, kind=kind, action=_advance_action(nxt), target=task.get("client_name", ""),
        entity_type=ent_type, entity_id=ent_id,
    )
    # A content task entering the review gate needs a reviewer: email + in-app the
    # leads who own the sign-off (best-effort; honours each lead's notification_prefs,
    # never blocks the advance). content_review is a NOTIF_EVENTS key (email default
    # on), so this fires through Resend when RESEND_API_KEY is present, else in-app only.
    if nxt == "review":
        await notify_leads(
            kind="content_review",
            title=f"Content ready for review: {task.get('title', '')}",
            body=(
                f'"{task.get("title", "A draft")}" for '
                f'{task.get("client_name", "a client")} has been submitted for review. '
                "Approve it or send it back from the review queue."
            ),
        )
    # A task type with NO review gate (everything except content_sprint) delivers
    # straight todo->in_progress->done via THIS endpoint, so admin/leads otherwise
    # never hear about it (content_sprint's completion is already covered above via
    # the review gate, and again on the /review approve path - never double-notify
    # it here). Fire the same lead fan-out on that direct-to-done transition.
    elif nxt == "done":
        assignee_label = str(assignee_id) if assignee_id is not None else "unassigned"
        await notify_leads(
            kind="task_completed",
            title=f"Task completed: {task.get('title', '')} ({code})",
            body=(
                f'"{task.get("title", "A task")}" ({code}, {type_from_db(type_canonical)}) for '
                f'{task.get("client_name", "a client")} was completed by {assignee_label}.'
            ),
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
    review_patch: dict[str, Any] = {"status": new_status}
    if body.action == "approve":
        review_patch["completed_at"] = datetime.now(UTC).isoformat()
    updated = await asyncio.to_thread(
        repo.update_task_by_code, code, review_patch, "review"
    )
    if updated is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task changed concurrently")

    action = "approved for delivery" if body.action == "approve" else "sent back for changes"
    ent_type, ent_id = _task_entity(task)
    await record_activity(
        actor, kind="content", action=action, target=task.get("client_name", ""),
        entity_type=ent_type, entity_id=ent_id,
    )
    # LEAD -> TEAM: tell the assignee their submitted work was approved or sent back
    # (best-effort; honours their notification_prefs, never blocks the decision).
    # work_reviewed is a NOTIF_EVENTS key (email default on).
    assignee_id = task.get("assignee_id")
    if assignee_id is not None:
        approved = body.action == "approve"
        title = task.get("title", "your task")
        client = task.get("client_name", "a client")
        await notify(
            str(assignee_id),
            kind="work_reviewed",
            title=(f"Work approved: {title}" if approved else f"Changes requested: {title}"),
            body=(
                f'Your work on "{title}" for {client} was '
                + (
                    "approved and marked done."
                    if approved
                    else "sent back for changes. Open your queue to revise and resubmit."
                )
            ),
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
    if "proof_url" in provided:
        # A lead may set OR clear the proof link; the column is NOT NULL, so a
        # cleared value normalizes to "".
        patch["proof_url"] = provided["proof_url"] or ""

    if not patch:
        return TaskResponse.from_row(task)  # nothing to change

    updated = await asyncio.to_thread(repo.update_task_by_code, code, patch)
    if updated is None:
        raise _TASK_NOT_FOUND
    ent_type, ent_id = _task_entity(task)
    await record_activity(
        actor, kind="task", action="updated a task", target=task.get("client_name", ""),
        entity_type=ent_type, entity_id=ent_id,
    )
    # If the task was handed to a NEW assignee, email + in-app them (best-effort).
    # Compare as strings: the stored id is a psycopg uuid, the patch value a str.
    prev_assignee = task.get("assignee_id")
    new_assignee = patch.get("assignee_id")
    if new_assignee and (str(prev_assignee) if prev_assignee is not None else None) != new_assignee:
        await notify(
            new_assignee,
            kind="task_assigned",
            title=f"Task reassigned to you: {task.get('title', '')}",
            body=(
                f'"{task.get("title", "A task")}" for {task.get("client_name", "a client")} '
                "is now assigned to you. Open your portal queue to pick it up."
            ),
        )
    return TaskResponse.from_row(updated)


# --------------------------------------------------------------------------- #
# Deadline-change-request workflow (0074): the assignee asks for a new due date
# within 12h of starting (or being assigned, if not yet started); a lead approves
# (due_date actually moves) or rejects (it never does). due_date NEVER changes
# automatically - only a lead's explicit decision writes it.
# --------------------------------------------------------------------------- #
def _deadline_request_anchor(task: dict[str, Any]) -> datetime | None:
    """The moment the 12h deadline-request window starts counting from:
    ``started_at`` if the assignee has begun work, else ``created_at`` (assignment
    time) - so a request is possible even before the assignee clicks Start."""
    raw = task.get("started_at") or task.get("created_at")
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo is not None else raw.replace(tzinfo=UTC)
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


@router.post(
    "/tasks/{code}/deadline-requests",
    response_model=DeadlineRequestResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_deadline_request(
    code: str, body: DeadlineRequestCreate, repo: TasksRepoDep, actor: ViewReports
) -> DeadlineRequestResponse:
    """The task's OWN assignee asks for a new due date, only within 12h of the
    task's start (fallback: its assignment). 403 if the caller isn't the
    assignee; 409 if the window has closed or a request is already pending."""
    task = await asyncio.to_thread(repo.get_task_by_code, code)
    if task is None:
        raise _TASK_NOT_FOUND
    assignee_id = task.get("assignee_id")
    if (str(assignee_id) if assignee_id is not None else None) != actor.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the task's assignee may request a deadline change",
        )

    anchor = _deadline_request_anchor(task)
    if anchor is None or datetime.now(UTC) - anchor > _DEADLINE_REQUEST_WINDOW:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The 12-hour deadline-change request window has closed",
        )

    existing = await asyncio.to_thread(repo.get_pending_deadline_request, str(task["id"]))
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A deadline-change request is already pending for this task",
        )

    row = await asyncio.to_thread(
        repo.insert_deadline_request,
        {
            "task_id": task["id"],
            "task_code": code,
            "requested_by": actor.id,
            "requested_due_date": body.requested_due_date.isoformat(),
            "reason": body.reason,
        },
    )
    await notify_leads(
        kind="deadline_requested",
        title=f"Deadline change requested: {task.get('title', '')} ({code})",
        body=(
            f'The assignee is requesting a new due date '
            f'({body.requested_due_date.isoformat()}) for "{task.get("title", "a task")}" '
            f'({code}) — {task.get("client_name", "a client")}.'
            + (f' Reason: {body.reason}' if body.reason else "")
        ),
    )
    return DeadlineRequestResponse.from_row(row)


@router.get("/tasks/{code}/deadline-requests", response_model=list[DeadlineRequestResponse])
async def list_deadline_requests(
    code: str, repo: TasksRepoDep, _actor: ViewReports
) -> list[DeadlineRequestResponse]:
    """List deadline-change requests for a task (any staff may read)."""
    task = await asyncio.to_thread(repo.get_task_by_code, code)
    if task is None:
        raise _TASK_NOT_FOUND
    rows = await asyncio.to_thread(repo.list_deadline_requests, str(task["id"]))
    return [DeadlineRequestResponse.from_row(r) for r in rows]


@router.post(
    "/tasks/{code}/deadline-requests/{request_id}/decide",
    response_model=DeadlineRequestResponse,
)
async def decide_deadline_request(
    code: str,
    request_id: str,
    body: DeadlineRequestDecideRequest,
    repo: TasksRepoDep,
    actor: AssignTasks,
) -> DeadlineRequestResponse:
    """A lead approves (due_date actually moves) or rejects (it doesn't) a
    pending deadline-change request. 404 if the request/task doesn't match; 409
    if it's no longer pending."""
    task = await asyncio.to_thread(repo.get_task_by_code, code)
    if task is None:
        raise _TASK_NOT_FOUND
    request = await asyncio.to_thread(repo.get_deadline_request, request_id)
    if request is None or str(request.get("task_id")) != str(task["id"]):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")

    approved = body.action == "approve"
    decision_patch: dict[str, Any] = {
        "status": "approved" if approved else "rejected",
        "decided_by": actor.id,
        "decided_at": datetime.now(UTC).isoformat(),
    }
    updated = await asyncio.to_thread(
        repo.decide_deadline_request, request_id, decision_patch
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Request is no longer pending"
        )

    if approved:
        # due_date changes ONLY here, on explicit lead approval - never automatic.
        await asyncio.to_thread(
            repo.update_task_by_code, code, {"due_date": updated["requested_due_date"]}
        )

    requested_by = request.get("requested_by")
    if requested_by is not None:
        title = task.get("title", "your task")
        await notify(
            str(requested_by),
            kind="deadline_decided",
            title=(
                f"Deadline change approved: {title}"
                if approved
                else f"Deadline change rejected: {title}"
            ),
            body=(
                f'Your requested due date for "{title}" ({code}) was '
                + (
                    f'approved — due date is now {updated["requested_due_date"]}.'
                    if approved
                    else "rejected. The original due date stands."
                )
            ),
        )
    return DeadlineRequestResponse.from_row(updated)
