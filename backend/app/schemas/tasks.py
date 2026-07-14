"""Task request/response models in the frontend shapes (``lib/data.ts`` ``Task``
+ ``lib/portal.ts`` lifecycle).

``TaskResponse`` mirrors ``Task`` EXACTLY - and ONLY those fields:
``{id, title, client, type, assignee, priority, status, due}``. ``id`` is the
short PUBLIC job code (``J-####``), never the UUID or any internal column
(client_id / created_by / audit_id / timestamps never leak).

The DB stores ``type`` canonical (``content_sprint``); the API surfaces the
display label (``Content Sprint``). ``next_status`` mirrors ``portal.ts``
``nextStatus`` byte-for-byte so the API and the board agree on the state machine.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# Display unions (verbatim from lib/data.ts). type is a DISPLAY string on the
# wire; priority/status are already canonical (same value front + back).
TaskType = Literal[
    "Technical Audit",
    "Actionable Audit",
    "Content Sprint",
    "Backlink Audit",
    "Local SEO",
    "Publishing",
]
TaskPriority = Literal["urgent", "high", "med", "low"]
TaskStatus = Literal["todo", "in_progress", "review", "done"]

# Canonical (DB enum) <-> display label. Kept as one source of truth.
TASK_TYPE_LABEL: dict[str, TaskType] = {
    "technical_audit": "Technical Audit",
    "actionable_audit": "Actionable Audit",
    "content_sprint": "Content Sprint",
    "backlink_audit": "Backlink Audit",
    "local_seo": "Local SEO",
    "publishing": "Publishing",
}
_LABEL_TO_DB: dict[TaskType, str] = {v: k for k, v in TASK_TYPE_LABEL.items()}

# Types that pass through the human review gate before `done` (portal.ts
# REVIEW_TYPES = ["Content Sprint"]). Everything else delivers straight to done.
REVIEW_TYPES: frozenset[str] = frozenset({"content_sprint"})

_STATUSES: frozenset[str] = frozenset({"todo", "in_progress", "review", "done"})
_PRIORITIES: frozenset[str] = frozenset({"urgent", "high", "med", "low"})


def type_to_db(task_type: TaskType) -> str:
    """Map the display ``TaskType`` to the canonical DB enum value."""
    return _LABEL_TO_DB[task_type]


def type_from_db(value: str | None) -> TaskType:
    """Map a stored ``task_type`` back to the display label (Content Sprint)."""
    return TASK_TYPE_LABEL.get(value or "", "Technical Audit")


def needs_review(type_canonical: str) -> bool:
    """Whether a task of this (canonical) type routes through the review gate."""
    return type_canonical in REVIEW_TYPES


def next_status(type_canonical: str, status: str) -> str | None:
    """The next lifecycle state, mirroring ``portal.ts`` ``nextStatus`` exactly.

    todo -> in_progress; in_progress -> review (content_sprint) else done;
    review -> done (reviewer sign-off only); done / unknown -> None.
    """
    if status == "todo":
        return "in_progress"
    if status == "in_progress":
        return "review" if needs_review(type_canonical) else "done"
    if status == "review":
        return "done"
    return None


def format_due(value: date | str | None) -> str:
    """Format a due date as the frontend's "Jul 12" ("%b %d"), else "" if unset."""
    if value is None:
        return ""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.strftime("%b %d")
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%b %d")
    except ValueError:
        return ""


class TaskCreate(BaseModel):
    """POST /tasks body: assign a new work item.

    ``type`` is the DISPLAY label (mapped to the canonical enum server-side);
    ``client_id``/``assignee_id`` are validated + snapshotted by the endpoint.
    ``due`` is an optional ISO date (``YYYY-MM-DD``) stored in ``due_date``.
    """

    title: str = Field(min_length=1)
    client_id: str = Field(min_length=1)
    type: TaskType
    assignee_id: str = Field(min_length=1)
    priority: TaskPriority = "med"
    due: date | None = None


class TaskUpdate(BaseModel):
    """PATCH /tasks/{code} body: reassign / repriority / redue (lead-only).

    Every field is optional; only those provided are changed. Status is NEVER
    patched here - it moves only through /advance and /review.
    """

    assignee_id: str | None = Field(default=None, min_length=1)
    priority: TaskPriority | None = None
    due: date | None = None


class TaskResponse(BaseModel):
    """One task in the frontend ``Task`` shape - and ONLY those fields.

    ``id`` is the public ``J-####`` code; ``client`` is the snapshotted name;
    ``assignee`` is the assignee's user id (``""`` if unassigned); ``type`` is the
    display label. No internal column (UUID id, client_id, created_by, audit_id,
    timestamps) is ever exposed.
    """

    id: str
    title: str
    client: str
    type: TaskType
    assignee: str
    priority: TaskPriority
    status: TaskStatus
    due: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TaskResponse:
        priority = row.get("priority")
        status = row.get("status")
        assignee = row.get("assignee_id")
        return cls(
            id=str(row["code"]),
            title=row.get("title", ""),
            client=row.get("client_name", ""),
            type=type_from_db(row.get("type")),
            assignee=str(assignee) if assignee else "",
            priority=priority if priority in _PRIORITIES else "med",
            status=status if status in _STATUSES else "todo",
            due=format_due(row.get("due_date")),
        )
