"""Assigning a work item — the one implementation, shared by both callers.

``POST /tasks`` creates a task from scratch. ``POST /tickets/{code}/convert-to-task``
creates one FROM a client's request, which is the loop that never existed: a client
raised a request, it landed in a 6-row widget on the Clients page, and nothing ever
turned it into work anybody was assigned.

Both need the same six things done in the same order — validate the client, validate
that the assignee is staff, snapshot the client name, insert, record activity, notify
the assignee — so they call this rather than each carrying a copy. Two copies of an
assignment path is how one of them quietly stops notifying.
"""

from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from fastapi import HTTPException, status

from app.core.auth import CurrentUser
from app.schemas.tasks import TaskPriority, TaskType, type_to_db
from app.services.activity import record_activity
from app.services.notifications import notify

_CLIENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
)
async def require_staff_assignee(repo: Any, assignee_id: str) -> None:
    """Reject an assignee that is missing (404) or a portal client (400).

    Mirrors the DB guard (tasks_guard_insert/update): a task is never pointed at a
    client uid. Enforced here for a clean error and at the DB as the boundary.

    The 404/400 split is deliberate and PRESERVED from the original in ``tasks.py``:
    "no such user" and "that user is a client" are different mistakes with different
    fixes, and the contract tests pin both.
    """
    row = await asyncio.to_thread(repo.get_user, assignee_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assignee not found")
    if row.get("role") == "client":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Assignee must be a staff member"
        )


async def assign_task(
    *,
    repo: Any,
    clients: Any,
    actor: CurrentUser,
    title: str,
    client_id: str,
    task_type: TaskType,
    assignee_id: str,
    priority: TaskPriority = "med",
    due: date | None = None,
    origin: str | None = None,
) -> dict[str, Any]:
    """Create one task and tell the assignee. Returns the persisted row.

    ``origin`` is an optional provenance note (e.g. a request code) that goes into the
    activity entry and the assignee's notification, so a task created FROM a client
    request says so instead of arriving with no explanation.
    """
    client = await asyncio.to_thread(clients.get_client, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    await require_staff_assignee(repo, assignee_id)

    client_name = str(client.get("name", "") or "")
    row: dict[str, Any] = await asyncio.to_thread(
        repo.insert_task,
        {
            "title": title,
            "client_id": client_id,
            "client_name": client_name,
            "type": type_to_db(task_type),
            "assignee_id": assignee_id,
            "priority": priority,
            "status": "todo",
            "due_date": due.isoformat() if due else None,
            "created_by": actor.id,
        },
    )

    await record_activity(
        actor,
        kind="task",
        action=f"converted {origin} into a task" if origin else "assigned a task",
        target=client_name,
        entity_type="client",
        entity_id=client_id,
    )
    # Best-effort: honours the assignee's notification_prefs and never blocks the
    # create. A task nobody is told about is a task nobody starts.
    await notify(
        assignee_id,
        kind="task_assigned",
        title=f"New task assigned: {title}",
        body=(
            f'You have been assigned "{title}" for {client_name or "a client"}. '
            f"Priority: {priority}."
            + (f" Due {due.isoformat()}." if due else "")
            + (f" Raised by the client as {origin}." if origin else "")
            + " Open your portal queue to get started."
        ),
    )
    return row
