"""Support-ticket request/response models in the frontend shape (``lib/data.ts``
``Ticket``).

``TicketResponse`` mirrors ``Ticket`` EXACTLY - the 7 keys ``{id, client, subject,
channel, priority, status, ago}`` and nothing else. ``id`` is the PUBLIC ``T-####``
code (never the UUID); ``client`` is the snapshotted client name; ``ago`` is the
humanized time since ``opened_at`` (derived here, never stored). No internal column
(UUID id, client_id, created_by, timestamps) is ever exposed.

The channel/priority/status ``Literal`` unions are pinned verbatim to the TS type
(§3 enum fidelity) and mirror the DB enums (``ticket_channel`` / ``ticket_priority``
/ ``ticket_status``) one-for-one.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.tasks import TaskPriority, TaskType
from app.util.timefmt import relative_ago

# Unions verbatim from lib/data.ts (Ticket). All three are already canonical
# (same value on the wire and in the DB enum), so no display mapping is needed.
TicketChannel = Literal["Email", "Portal", "Call", "Chat"]
TicketPriority = Literal["urgent", "high", "med", "low"]
TicketStatus = Literal["open", "pending", "resolved"]

_CHANNELS: frozenset[str] = frozenset({"Email", "Portal", "Call", "Chat"})
_PRIORITIES: frozenset[str] = frozenset({"urgent", "high", "med", "low"})
_STATUSES: frozenset[str] = frozenset({"open", "pending", "resolved"})


class TicketCreate(BaseModel):
    """POST /tickets body: log a support ticket (lead-only).

    ``client_id`` is validated + snapshotted by the endpoint (the client name is
    read from the clients table, never taken from the body). ``status`` always
    starts ``open`` - it is not client-supplied.
    """

    subject: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    channel: TicketChannel = "Portal"
    priority: TicketPriority = "med"


class TicketStatusUpdate(BaseModel):
    """PATCH /tickets/{code}/status body: triage a ticket to a new status."""

    status: TicketStatus


class TicketReplyRequest(BaseModel):
    """POST /tickets/{code}/reply body: an admin/lead's free-text reply."""

    message: str = Field(min_length=1, max_length=8000)


class TicketResponse(BaseModel):
    """One ticket in the frontend ``Ticket`` shape - and ONLY those 7 keys.

    ``id`` is the public ``T-####`` code; ``client`` is the snapshotted name;
    ``ago`` is the relative time since ``opened_at`` ("22m ago"). No internal column
    (UUID id, client_id, created_by, timestamps) is ever exposed.
    """

    id: str
    client: str
    subject: str
    channel: TicketChannel
    priority: TicketPriority
    status: TicketStatus
    ago: str
    # --- the work this request became (0117) ---
    # Still no internal identity on the wire: a task CODE is the public J-#### handle,
    # exactly as `id` is the public T-#### one. Null means not converted, which is what
    # the Convert control tests - so the same request cannot be converted twice.
    task_code: str | None = Field(default=None, serialization_alias="taskCode")
    task_status: str | None = Field(default=None, serialization_alias="taskStatus")
    task_assignee: str | None = Field(default=None, serialization_alias="taskAssignee")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TicketResponse:
        channel = row.get("channel")
        priority = row.get("priority")
        status = row.get("status")
        return cls(
            id=str(row["code"]),
            client=row.get("client_name", ""),
            subject=row.get("subject", ""),
            channel=channel if channel in _CHANNELS else "Portal",
            priority=priority if priority in _PRIORITIES else "med",
            status=status if status in _STATUSES else "open",
            ago=relative_ago(row.get("opened_at"), empty="just now"),
            task_code=(str(row["task_code"]) if row.get("task_code") else None),
            task_status=(str(row["task_status"]) if row.get("task_status") else None),
            task_assignee=(str(row["task_assignee"]) if row.get("task_assignee") else None),
        )


def to_response(row: dict[str, Any]) -> TicketResponse:
    """Map a ``support_tickets`` row to the frontend ``Ticket`` shape."""
    return TicketResponse.from_row(row)


class TicketToTaskRequest(BaseModel):
    """POST /tickets/{code}/convert-to-task body.

    ``title`` defaults to the ticket's own subject - the request already says what is
    needed, and retyping it is how the task and the request drift apart. ``client_id``
    is NOT a field: it is resolved from the ticket server-side, because a ticket
    deliberately never exposes its tenant to the wire.
    """

    assignee_id: str = Field(min_length=1)
    type: TaskType = "Technical Audit"
    priority: TaskPriority = "med"
    due: date | None = None
    title: str | None = Field(default=None, max_length=300)
