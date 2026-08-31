"""Wire shapes for the automations manager."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.jobs.automation_capabilities import CAPABILITIES
from app.jobs.automation_schedule import MIN_INTERVAL_SECONDS, humanize


class CapabilityResponse(BaseModel):
    """One thing an automation can be set to do.

    `paid` is why this endpoint exists rather than a hardcoded list in the UI: an
    automation that spends metered budget every night is a different decision from one
    that sends a reminder, and the operator has to be able to see which is which
    BEFORE enabling it.
    """

    kind: str
    label: str
    description: str
    scope: str
    paid: bool
    default_interval_seconds: int = Field(serialization_alias="defaultIntervalSeconds")
    needs: list[str] = Field(default_factory=list)


class AutomationResponse(BaseModel):
    id: str
    name: str
    kind: str
    #: The capability's label, so a row is readable without a second request.
    kind_label: str = Field(serialization_alias="kindLabel")
    scope: str
    paid: bool
    params: dict[str, Any] = Field(default_factory=dict)
    schedule_kind: str = Field(serialization_alias="scheduleKind")
    interval_seconds: int | None = Field(default=None, serialization_alias="intervalSeconds")
    cron_expr: str | None = Field(default=None, serialization_alias="cronExpr")
    #: "every 30 minutes" / "cron: 0 2 * * *" - the cadence in one readable phrase.
    cadence: str
    enabled: bool
    notify_on_failure: bool = Field(serialization_alias="notifyOnFailure")
    notify_channels: dict[str, Any] = Field(
        default_factory=dict, serialization_alias="notifyChannels"
    )
    next_due_at: str | None = Field(default=None, serialization_alias="nextDueAt")
    last_fired_at: str | None = Field(default=None, serialization_alias="lastFiredAt")
    #: The outcome of the most recent run. Null before it has ever fired - which is a
    #: different thing from a run that failed, and must not render as one.
    last_run_id: str | None = Field(default=None, serialization_alias="lastRunId")
    last_status: str | None = Field(default=None, serialization_alias="lastStatus")
    last_finished_at: str | None = Field(default=None, serialization_alias="lastFinishedAt")
    last_detail: str = Field(default="", serialization_alias="lastDetail")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> AutomationResponse:
        cap = CAPABILITIES.get(str(row["kind"]))
        def _iso(key: str) -> str | None:
            value = row.get(key)
            return value.isoformat() if value is not None else None

        return cls(
            id=str(row["id"]),
            name=str(row["name"]),
            kind=str(row["kind"]),
            # An automation whose capability was removed must still be READABLE, or a
            # broken row becomes invisible instead of fixable.
            kind_label=cap.label if cap else f"{row['kind']} (no longer available)",
            scope=cap.scope if cap else "platform",
            paid=bool(cap.paid) if cap else False,
            params=dict(row.get("params") or {}),
            schedule_kind=str(row["schedule_kind"]),
            interval_seconds=row.get("interval_seconds"),
            cron_expr=row.get("cron_expr"),
            cadence=humanize(
                str(row["schedule_kind"]), row.get("interval_seconds"), row.get("cron_expr")
            ),
            enabled=bool(row["enabled"]),
            notify_on_failure=bool(row["notify_on_failure"]),
            notify_channels=dict(row.get("notify_channels") or {}),
            next_due_at=_iso("next_due_at"),
            last_fired_at=_iso("last_fired_at"),
            last_run_id=(str(row["last_run_id"]) if row.get("last_run_id") else None),
            last_status=(str(row["last_status"]) if row.get("last_status") else None),
            last_finished_at=_iso("last_finished_at"),
            last_detail=str(row.get("last_reason") or row.get("last_error") or ""),
        )


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    kind: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    schedule_kind: Literal["interval", "cron"] = Field(alias="scheduleKind")
    interval_seconds: int | None = Field(
        default=None, alias="intervalSeconds", ge=MIN_INTERVAL_SECONDS
    )
    cron_expr: str | None = Field(default=None, alias="cronExpr", max_length=120)
    #: Created PAUSED unless someone deliberately asks otherwise. A schedule that
    #: starts running the moment it is saved is a schedule nobody reviewed.
    enabled: bool = False
    notify_on_failure: bool = Field(default=True, alias="notifyOnFailure")
    notify_channels: dict[str, Any] = Field(
        default_factory=lambda: {"inApp": True, "email": False}, alias="notifyChannels"
    )

    model_config = {"populate_by_name": True}


class AutomationUpdate(BaseModel):
    """A partial edit. Every field optional; only what is sent is changed."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    params: dict[str, Any] | None = None
    schedule_kind: Literal["interval", "cron"] | None = Field(default=None, alias="scheduleKind")
    interval_seconds: int | None = Field(
        default=None, alias="intervalSeconds", ge=MIN_INTERVAL_SECONDS
    )
    cron_expr: str | None = Field(default=None, alias="cronExpr", max_length=120)
    enabled: bool | None = None
    notify_on_failure: bool | None = Field(default=None, alias="notifyOnFailure")
    notify_channels: dict[str, Any] | None = Field(default=None, alias="notifyChannels")

    model_config = {"populate_by_name": True}


class AutomationRunNowResponse(BaseModel):
    automation_id: str = Field(serialization_alias="automationId")
    #: Null only if the ledger could not be read back; the work is queued regardless.
    run_id: str | None = Field(default=None, serialization_alias="runId")
    dispatched: int


__all__ = [
    "AutomationCreate",
    "AutomationResponse",
    "AutomationRunNowResponse",
    "AutomationUpdate",
    "CapabilityResponse",
]
