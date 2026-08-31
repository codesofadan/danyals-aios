"""Wire models for the Design Replication routes.

These pin the two-sided contract the frontend codes against, and the contract's
keys are snake_case (``job_id``, ``preview_url``, ``owner_confirmed_source``) - so,
unlike the camelCase-aliased module schemas, these serialize their attribute names
verbatim. Deviating here to match the house alias style would break the other side.

The status vocabulary is the job contract's own (``app/jobs/status.py``): the
ledger row IS the status surface, so there is nothing to translate and no second
vocabulary to drift.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, cast
from uuid import UUID

from pydantic import BaseModel, Field

ReplicaJobStatus = Literal[
    "queued", "running", "completed", "degraded", "blocked", "failed", "cancelled"
]


class ReplicaCreateRequest(BaseModel):
    """POST /replica body. ``owner_confirmed_source`` is the copyright gate: the
    rebuild carries the source page's own copy and imagery, so the caller must
    assert the client owns the source. The route 400s when it is false."""

    client_id: UUID
    url: str = Field(min_length=1, max_length=2000)
    owner_confirmed_source: bool
    title: str | None = Field(default=None, max_length=300)
    slug: str | None = Field(default=None, max_length=200)


class ReplicaQueuedResponse(BaseModel):
    """202: the job was accepted. ``job_id`` is the handle GET /replica/{job_id} reads."""

    job_id: str
    status: Literal["queued"] = "queued"


class ReplicaJobResponse(BaseModel):
    """GET /replica/{job_id}: the ledger row mapped onto the contract shape.

    The nullable ints are null until the run reaches a terminal state that carried
    a payload; ``notes`` always includes the ``reason`` of a degraded/blocked run,
    so a caller rendering only ``notes`` still shows why the promise wasn't kept.
    """

    job_id: str
    status: ReplicaJobStatus
    preview_url: str | None = None
    post_id: int | None = None
    sections: int | None = None
    widgets: int | None = None
    notes: list[str] = Field(default_factory=list)
    # The design the run MEASURED, in the content pipeline's profile shape. Null until
    # the run completes (and on a degraded run that never got as far as extracting one),
    # so a caller must treat its absence as "fall back to measuring the site yourself".
    design_profile: dict[str, Any] | None = None

    @classmethod
    def from_run(cls, job_id: str, row: Mapping[str, Any]) -> ReplicaJobResponse:
        """Map one ``job_runs`` row (the worker's result payload + the contract's
        reason/error fields) into the wire shape."""
        result = dict(row.get("result") or {})
        notes = [str(n) for n in (result.get("notes") or [])]
        reason = str(row.get("reason") or "")
        if reason and reason not in notes:
            notes.append(reason)
        error_message = str(row.get("error_message") or "")
        if str(row.get("status")) == "failed" and error_message:
            notes.append(f"{row.get('error_type') or 'error'}: {error_message}")
        post_id = result.get("post_id")
        sections = result.get("sections")
        widgets = result.get("widgets")
        return cls(
            job_id=job_id,
            status=cast(ReplicaJobStatus, str(row.get("status"))),
            preview_url=(str(result["preview_url"]) if result.get("preview_url") else None),
            post_id=int(post_id) if post_id is not None else None,
            sections=int(sections) if sections is not None else None,
            widgets=int(widgets) if widgets is not None else None,
            notes=notes,
            design_profile=(
                dict(result["design_profile"])
                if isinstance(result.get("design_profile"), dict)
                else None
            ),
        )
