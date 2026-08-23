"""Wire models for the job-contract operator surface.

These answer the three questions the master plan's target state asks of the job
layer - **what ran, what failed, what it cost** - in the one canonical vocabulary.

Two deliberate choices worth stating, because both are the point rather than detail:

``succeeded`` is computed by ``app.jobs.status.is_success``, which returns True for
``completed`` and nothing else. The flag is on the wire so a UI cannot re-derive
success from a status string and get it wrong - there is exactly one definition, and
``degraded`` is not it.

``reason`` is never empty on a ``degraded`` or ``blocked`` run: the database's CHECK
constraint refuses to store one that is. So a client rendering a degraded run always
has something true to display, and "partially succeeded" with no explanation is not a
state this API can emit.

Python attributes are snake_case with a ``serialization_alias`` (ruff N815 forbids a
raw camelCase attribute), so the emitted JSON is camelCase like every other module
here and a future ``frontend/lib/jobs.ts`` lines up one-for-one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.jobs.status import JobStatus, is_success, needs_attention


def _iso(value: Any) -> str | None:
    return value.isoformat() if isinstance(value, datetime) else None


def _duration_seconds(started: Any, finished: Any) -> float | None:
    if isinstance(started, datetime) and isinstance(finished, datetime):
        return round((finished - started).total_seconds(), 3)
    return None


class JobRunResponse(BaseModel):
    """One execution of one logical unit of background work."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    job_name: str = Field(serialization_alias="jobName")
    task: str
    queue: str
    status: JobStatus

    #: The ONE definition of success, computed server-side. See the module docstring.
    succeeded: bool
    #: True for degraded / blocked / failed - the three an operator must act on.
    needs_attention: bool = Field(serialization_alias="needsAttention")

    client_id: str | None = Field(default=None, serialization_alias="clientId")
    client_name: str = Field(default="", serialization_alias="clientName")
    scope_type: str = Field(default="", serialization_alias="scopeType")
    scope_id: str | None = Field(default=None, serialization_alias="scopeId")

    attempt: int
    max_attempts: int = Field(serialization_alias="maxAttempts")

    detail: str = ""
    #: Guaranteed non-empty when status is degraded or blocked (DB check constraint).
    reason: str = ""
    #: The machine-readable half of `reason`: a stable snake_case identifier an
    #: operator surface groups by. Also guaranteed non-empty for degraded/blocked.
    reason_code: str = Field(default="", serialization_alias="reasonCode")
    error_type: str = Field(default="", serialization_alias="errorType")
    error_message: str = Field(default="", serialization_alias="errorMessage")

    cost_usd: float = Field(default=0.0, serialization_alias="costUsd")

    correlation_id: str = Field(serialization_alias="correlationId")
    parent_run_id: str | None = Field(default=None, serialization_alias="parentRunId")
    idempotency_key: str | None = Field(default=None, serialization_alias="idempotencyKey")

    created_at: str | None = Field(default=None, serialization_alias="createdAt")
    started_at: str | None = Field(default=None, serialization_alias="startedAt")
    finished_at: str | None = Field(default=None, serialization_alias="finishedAt")
    heartbeat_at: str | None = Field(default=None, serialization_alias="heartbeatAt")
    scheduled_for: str | None = Field(default=None, serialization_alias="scheduledFor")
    cancel_requested: bool = Field(default=False, serialization_alias="cancelRequested")
    duration_seconds: float | None = Field(default=None, serialization_alias="durationSeconds")

    result: dict[str, Any] | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> JobRunResponse:
        status = str(row["status"])
        return cls(
            id=str(row["id"]),
            job_name=str(row["job_name"]),
            task=str(row.get("task") or ""),
            queue=str(row["queue"]),
            status=JobStatus(status),
            succeeded=is_success(status),
            needs_attention=needs_attention(status),
            client_id=str(row["client_id"]) if row.get("client_id") else None,
            client_name=str(row.get("client_name") or ""),
            scope_type=str(row.get("scope_type") or ""),
            scope_id=str(row["scope_id"]) if row.get("scope_id") else None,
            attempt=int(row.get("attempt") or 0),
            max_attempts=int(row.get("max_attempts") or 1),
            detail=str(row.get("detail") or ""),
            reason=str(row.get("reason") or ""),
            reason_code=str(row.get("reason_code") or ""),
            error_type=str(row.get("error_type") or ""),
            error_message=str(row.get("error_message") or ""),
            cost_usd=float(row.get("cost_usd") or 0),
            correlation_id=str(row["correlation_id"]),
            parent_run_id=str(row["parent_run_id"]) if row.get("parent_run_id") else None,
            idempotency_key=row.get("idempotency_key"),
            created_at=_iso(row.get("created_at")),
            started_at=_iso(row.get("started_at")),
            finished_at=_iso(row.get("finished_at")),
            heartbeat_at=_iso(row.get("heartbeat_at")),
            scheduled_for=_iso(row.get("scheduled_for")),
            cancel_requested=row.get("cancel_requested_at") is not None,
            duration_seconds=_duration_seconds(row.get("started_at"), row.get("finished_at")),
            result=row.get("result"),
        )


class DeadLetterResponse(BaseModel):
    """A unit of work the platform accepted and did not deliver."""

    model_config = ConfigDict(populate_by_name=True)

    id: str
    run_id: str | None = Field(default=None, serialization_alias="runId")
    job_name: str = Field(serialization_alias="jobName")
    task: str = ""
    queue: str
    client_id: str | None = Field(default=None, serialization_alias="clientId")
    client_name: str = Field(default="", serialization_alias="clientName")
    scope_type: str = Field(default="", serialization_alias="scopeType")
    scope_id: str | None = Field(default=None, serialization_alias="scopeId")
    correlation_id: str | None = Field(default=None, serialization_alias="correlationId")
    idempotency_key: str | None = Field(default=None, serialization_alias="idempotencyKey")

    attempts: int = 0
    #: Carried from the run so the queue can be grouped by CAUSE, not just by job name.
    reason_code: str = Field(default="", serialization_alias="reasonCode")
    error_type: str = Field(default="", serialization_alias="errorType")
    error_message: str = Field(default="", serialization_alias="errorMessage")
    #: The sanitized traceback. Staff-only; secrets are redacted before it is stored.
    traceback: str = ""
    #: Everything needed to replay: {"args": [...], "kwargs": {...}}.
    payload: dict[str, Any] = Field(default_factory=dict)

    dead_lettered_at: str | None = Field(default=None, serialization_alias="deadLetteredAt")
    first_failed_at: str | None = Field(default=None, serialization_alias="firstFailedAt")
    replayed_at: str | None = Field(default=None, serialization_alias="replayedAt")
    replayed_run_id: str | None = Field(default=None, serialization_alias="replayedRunId")
    resolved_at: str | None = Field(default=None, serialization_alias="resolvedAt")
    resolution: str = ""
    #: Still awaiting a human decision - the actual queue.
    open: bool = True

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DeadLetterResponse:
        return cls(
            id=str(row["id"]),
            run_id=str(row["run_id"]) if row.get("run_id") else None,
            job_name=str(row["job_name"]),
            task=str(row.get("task") or ""),
            queue=str(row["queue"]),
            client_id=str(row["client_id"]) if row.get("client_id") else None,
            client_name=str(row.get("client_name") or ""),
            scope_type=str(row.get("scope_type") or ""),
            scope_id=str(row["scope_id"]) if row.get("scope_id") else None,
            correlation_id=str(row["correlation_id"]) if row.get("correlation_id") else None,
            idempotency_key=row.get("idempotency_key"),
            attempts=int(row.get("attempts") or 0),
            reason_code=str(row.get("reason_code") or ""),
            error_type=str(row.get("error_type") or ""),
            error_message=str(row.get("error_message") or ""),
            traceback=str(row.get("traceback") or ""),
            payload=dict(row.get("payload") or {}),
            dead_lettered_at=_iso(row.get("dead_lettered_at")),
            first_failed_at=_iso(row.get("first_failed_at")),
            replayed_at=_iso(row.get("replayed_at")),
            replayed_run_id=str(row["replayed_run_id"]) if row.get("replayed_run_id") else None,
            resolved_at=_iso(row.get("resolved_at")),
            resolution=str(row.get("resolution") or ""),
            open=row.get("resolved_at") is None and row.get("replayed_at") is None,
        )


class JobStatusCount(BaseModel):
    """One row of the summary: how many runs landed in a state, and what they cost."""

    model_config = ConfigDict(populate_by_name=True)

    status: JobStatus
    runs: int
    cost_usd: float = Field(serialization_alias="costUsd")
    succeeded: bool


class JobSummaryResponse(BaseModel):
    """The operator headline over a window.

    ``degraded`` is its own line, never folded into a success count - which is the
    entire reason the vocabulary distinguishes them.
    """

    model_config = ConfigDict(populate_by_name=True)

    window_hours: int = Field(serialization_alias="windowHours")
    by_status: list[JobStatusCount] = Field(serialization_alias="byStatus")
    total_runs: int = Field(serialization_alias="totalRuns")
    #: completed only.
    succeeded_runs: int = Field(serialization_alias="succeededRuns")
    #: degraded + blocked + failed.
    needs_attention_runs: int = Field(serialization_alias="needsAttentionRuns")
    total_cost_usd: float = Field(serialization_alias="totalCostUsd")
    open_dead_letters: int = Field(serialization_alias="openDeadLetters")

    @classmethod
    def from_rows(cls, rows: list[dict[str, Any]], *, window_hours: int, open_dlq: int) -> JobSummaryResponse:
        counts = [
            JobStatusCount(
                status=JobStatus(str(r["status"])),
                runs=int(r["runs"]),
                cost_usd=float(r.get("cost_usd") or 0),
                succeeded=is_success(str(r["status"])),
            )
            for r in rows
        ]
        return cls(
            window_hours=window_hours,
            by_status=counts,
            total_runs=sum(c.runs for c in counts),
            succeeded_runs=sum(c.runs for c in counts if c.succeeded),
            needs_attention_runs=sum(c.runs for c in counts if needs_attention(c.status)),
            total_cost_usd=round(sum(c.cost_usd for c in counts), 6),
            open_dead_letters=open_dlq,
        )


class InFlightResponse(BaseModel):
    """What the per-client concurrency cap is currently acting on."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str | None = Field(default=None, serialization_alias="clientId")
    client_name: str = Field(default="", serialization_alias="clientName")
    queue: str
    running: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> InFlightResponse:
        return cls(
            client_id=str(row["client_id"]) if row.get("client_id") else None,
            client_name=str(row.get("client_name") or ""),
            queue=str(row["queue"]),
            running=int(row["running"]),
        )


class CancelRequest(BaseModel):
    """Why an operator stopped a run. Recorded on the activity log, not the run row -
    the run row records that it was cancelled; the log records who and why."""

    model_config = ConfigDict(populate_by_name=True)

    reason: str = Field(default="", max_length=500)


class ResolveRequest(BaseModel):
    """Closing a dead letter requires saying what was decided.

    Enforced here AND by a CHECK constraint. A queue closed with no reasons written is
    a graveyard: the next person cannot tell "we fixed the underlying bug" from "we
    gave up on this one".
    """

    model_config = ConfigDict(populate_by_name=True)

    resolution: str = Field(min_length=1, max_length=1000)

    @field_validator("resolution")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("resolution cannot be blank")
        return value.strip()


class ReplayResponse(BaseModel):
    """The result of re-running a dead letter."""

    model_config = ConfigDict(populate_by_name=True)

    dead_letter_id: str = Field(serialization_alias="deadLetterId")
    run_id: str = Field(serialization_alias="runId")
    message_id: str = Field(serialization_alias="messageId")
    idempotency_key: str = Field(serialization_alias="idempotencyKey")
