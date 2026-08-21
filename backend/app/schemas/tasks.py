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
    """PATCH /tasks/{code} body: reassign / repriority / redue / set proof (lead-only).

    Every field is optional; only those provided are changed. Status is NEVER
    patched here - it moves only through /advance and /review. ``proof_url`` is the
    proof-of-completion link a lead may set/clear on any task (the assignee sets
    theirs via /advance).
    """

    assignee_id: str | None = Field(default=None, min_length=1)
    priority: TaskPriority | None = None
    due: date | None = None
    proof_url: str | None = Field(default=None, max_length=2000)


class TaskAdvanceRequest(BaseModel):
    """POST /tasks/{code}/advance body: advance one step, optionally attaching proof.

    ``proof_url`` lets the ASSIGNEE submit their proof-of-completion link (published
    URL / delivered report) as they advance to review/done. Optional: the body may be
    omitted entirely (a plain advance). The DB guard permits a non-lead to change
    {status, proof_url} together along a legal transition.
    """

    proof_url: str | None = Field(default=None, max_length=2000)


ReviewAction = Literal["approve", "reject"]


class TaskReviewRequest(BaseModel):
    """POST /tasks/{code}/review body: the reviewer's decision at the gate."""

    action: ReviewAction


class TaskResponse(BaseModel):
    """One task in the frontend ``Task`` shape - and ONLY those fields.

    ``id`` is the public ``J-####`` code; ``client`` is the snapshotted name;
    ``assignee`` is the assignee's user id (``""`` if unassigned); ``type`` is the
    display label; ``proofUrl`` is the proof-of-completion link (``""`` when unset).
    No internal column (UUID id, client_id, created_by, audit_id, timestamps) is ever
    exposed.
    """

    id: str
    title: str
    client: str
    type: TaskType
    assignee: str
    priority: TaskPriority
    status: TaskStatus
    due: str
    proof_url: str = Field(default="", serialization_alias="proofUrl")
    started_at: str | None = Field(default=None, serialization_alias="startedAt")
    completed_at: str | None = Field(default=None, serialization_alias="completedAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> TaskResponse:
        priority = row.get("priority")
        status = row.get("status")
        assignee = row.get("assignee_id")
        started_at = row.get("started_at")
        completed_at = row.get("completed_at")
        return cls(
            id=str(row["code"]),
            title=row.get("title", ""),
            client=row.get("client_name", ""),
            type=type_from_db(row.get("type")),
            assignee=str(assignee) if assignee else "",
            priority=priority if priority in _PRIORITIES else "med",
            status=status if status in _STATUSES else "todo",
            due=format_due(row.get("due_date")),
            proof_url=str(row.get("proof_url") or ""),
            started_at=started_at.isoformat() if isinstance(started_at, datetime) else started_at,
            completed_at=(
                completed_at.isoformat() if isinstance(completed_at, datetime) else completed_at
            ),
        )


# --------------------------------------------------------------------------- #
# Deadline-change-request workflow (`task_deadline_requests`, 0074)
# --------------------------------------------------------------------------- #
DeadlineRequestStatus = Literal["pending", "approved", "rejected"]
DeadlineDecideAction = Literal["approve", "reject"]

_DEADLINE_REQUEST_STATUSES: frozenset[str] = frozenset({"pending", "approved", "rejected"})


class DeadlineRequestCreate(BaseModel):
    """POST /tasks/{code}/deadline-requests body: the assignee's ask for a new due date."""

    requested_due_date: date
    reason: str | None = Field(default=None, max_length=2000)


class DeadlineRequestDecideRequest(BaseModel):
    """POST /tasks/{code}/deadline-requests/{id}/decide body: the lead's decision."""

    action: DeadlineDecideAction


class DeadlineRequestResponse(BaseModel):
    """One deadline-change request, camelCase on the wire."""

    id: str
    task_code: str = Field(serialization_alias="taskCode")
    requested_by: str = Field(serialization_alias="requestedBy")
    requested_due_date: str = Field(serialization_alias="requestedDueDate")
    reason: str = Field(default="")
    status: DeadlineRequestStatus
    decided_by: str = Field(default="", serialization_alias="decidedBy")
    decided_at: str = Field(default="", serialization_alias="decidedAt")
    created_at: str = Field(serialization_alias="createdAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DeadlineRequestResponse:
        status = row.get("status")
        requested_due_date = row.get("requested_due_date")
        decided_at = row.get("decided_at")
        created_at = row.get("created_at")
        decided_by = row.get("decided_by")
        return cls(
            id=str(row["id"]),
            task_code=str(row.get("task_code", "")),
            requested_by=str(row.get("requested_by", "")),
            requested_due_date=(
                requested_due_date.isoformat()
                if isinstance(requested_due_date, date)
                else str(requested_due_date or "")
            ),
            reason=str(row.get("reason") or ""),
            status=status if status in _DEADLINE_REQUEST_STATUSES else "pending",
            decided_by=str(decided_by) if decided_by else "",
            decided_at=decided_at.isoformat() if isinstance(decided_at, datetime) else (decided_at or ""),
            created_at=created_at.isoformat() if isinstance(created_at, datetime) else str(created_at or ""),
        )
