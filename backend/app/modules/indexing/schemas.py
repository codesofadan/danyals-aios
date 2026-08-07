"""Indexing request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module, so these shapes are owned here
(like ``site_analytics``); the module's own unit tests freeze the emitted key set.
Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# The three fan-out mechanisms an operator can target. ``sitemap`` is always available
# (keyless); ``indexnow`` / ``google`` degrade to a ``skipped`` row when unconfigured.
Engine = Literal["indexnow", "google", "sitemap"]


class SubmitRequest(BaseModel):
    """Submit one or more URLs for (re)indexing across the chosen engines.

    ``engines`` omitted -> all three are attempted (each degrades if not configured).
    ``client_id`` is optional: an ad-hoc submission may not be tied to a client.
    """

    urls: list[str] = Field(min_length=1)
    engines: list[Engine] | None = None
    client_id: str | None = Field(default=None, alias="clientId")

    model_config = {"populate_by_name": True}


class SubmissionResponse(BaseModel):
    """One ``index_submissions`` row - a single (url, engine) attempt + how it went."""

    id: str
    client_id: str | None = Field(serialization_alias="clientId")
    url: str
    engine: str
    status: str
    detail: str
    created_at: str = Field(serialization_alias="createdAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SubmissionResponse:
        created = row.get("created_at")
        cid = row.get("client_id")
        return cls(
            id=str(row.get("id", "")),
            client_id=str(cid) if cid else None,
            url=str(row.get("url", "") or ""),
            engine=str(row.get("engine", "") or ""),
            status=str(row.get("status", "") or ""),
            detail=str(row.get("detail", "") or ""),
            created_at=created.isoformat() if created else "",
        )


class SubmitResponse(BaseModel):
    """The result of a submit fan-out: the rows recorded + a small tally."""

    submitted: int
    ok: int
    skipped: int
    errors: int
    results: list[SubmissionResponse]
