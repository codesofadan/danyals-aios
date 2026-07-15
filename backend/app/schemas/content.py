"""Content-job request/response models in the frontend shape (``lib/content.ts``).

``ContentJobResponse`` mirrors ``ContentJob`` EXACTLY - the 15 camelCase keys
``{id, client, color, pageType, topic, framework, auto, target, status, cost,
words, schema, images, stage, ago}`` and nothing else. ``id`` is the short PUBLIC
job code (``CJ-####``), never the UUID; ``client``/``color`` are display SNAPSHOTS
so the internal ``client_id`` never leaks.

THE ``schema`` GOTCHA: ``schema`` is a reserved attribute on Pydantic's
``BaseModel`` (the JSON-schema builder), so the Python attribute is named
``schema_type`` and re-aliased to the wire key ``schema`` via
``serialization_alias`` - which the contract-lock test verifies is emitted.

The two server rules the router will reuse live here as pure helpers:
``auto_framework(page_type)`` (service->AIDA, local->BAB, blog->PAS) and
``schema_for(page_type)`` (service->Service, local->LocalBusiness, blog->Article).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.util.timefmt import relative_ago

# Unions verbatim from content.ts (note the spaces / apostrophes in the
# frameworks). These are the SAME values front + back - no display remapping.
PageType = Literal["service", "blog", "local"]
PublishTarget = Literal["WordPress", "PDF/Markdown"]
Framework = Literal["AIDA", "PAS", "BAB", "FAB", "4 Ps", "PASTOR", "4 U's"]
JobStatus = Literal[
    "queued", "drafting", "needs_review", "publishing", "done", "failed", "rejected"
]

_PAGE_TYPES: frozenset[str] = frozenset({"service", "blog", "local"})
_TARGETS: frozenset[str] = frozenset({"WordPress", "PDF/Markdown"})
_FRAMEWORKS: frozenset[str] = frozenset(
    {"AIDA", "PAS", "BAB", "FAB", "4 Ps", "PASTOR", "4 U's"}
)
_STATUSES: frozenset[str] = frozenset(
    {"queued", "drafting", "needs_review", "publishing", "done", "failed", "rejected"}
)

# Server rule: content type -> the framework "Auto" resolves to.
_AUTO_FRAMEWORK: dict[str, Framework] = {
    "service": "AIDA",
    "local": "BAB",
    "blog": "PAS",
}
# Server rule: content type -> the JSON-LD @type (the schema the page validates as).
_SCHEMA_FOR: dict[str, str] = {
    "service": "Service",
    "local": "LocalBusiness",
    "blog": "Article",
}


def auto_framework(page_type: str) -> Framework:
    """The framework "Auto" resolves to for a page type (service->AIDA,
    local->BAB, blog->PAS). Falls back to AIDA for an unknown type."""
    return _AUTO_FRAMEWORK.get(page_type, "AIDA")


def schema_for(page_type: str) -> str:
    """The JSON-LD @type for a page type (service->Service, local->LocalBusiness,
    blog->Article). Falls back to Article for an unknown type."""
    return _SCHEMA_FOR.get(page_type, "Article")


class ContentJobCreate(BaseModel):
    """POST /content body: queue a new content job.

    ``framework`` accepts the sentinel ``"Auto"`` -> the endpoint resolves it via
    ``auto_framework(pageType)`` and flags ``auto=true``. ``client_id`` is validated
    + snapshotted (name/color) by the endpoint; ``pageType``/``target`` are the same
    values front + back.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(min_length=1)
    page_type: PageType = Field(alias="pageType")
    topic: str = Field(min_length=1)
    framework: Framework | Literal["Auto"] = "Auto"
    target: PublishTarget = "WordPress"


ReviewAction = Literal["approve", "edit", "reject"]


class ContentReviewRequest(BaseModel):
    """POST /content/{code}/review body: the reviewer's decision at the gate.

    ``approve`` -> publishing, ``reject`` -> rejected, ``edit`` -> back to drafting.
    """

    action: ReviewAction


class ContentJobResponse(BaseModel):
    """One content job in the frontend ``ContentJob`` shape - and ONLY those 15
    keys. ``id`` is the public ``CJ-####`` code; ``client``/``color`` are the
    snapshotted display fields. No internal column (UUID id, client_id, assignee_id,
    created_by, the rich pipeline columns, timestamps) is ever exposed.

    ``schema_type`` is emitted as the wire key ``schema`` (the attribute is renamed
    to dodge Pydantic's reserved ``BaseModel.schema``).
    """

    id: str
    client: str
    color: str
    page_type: PageType = Field(serialization_alias="pageType")
    topic: str
    framework: Framework
    auto: bool
    target: PublishTarget
    status: JobStatus
    cost: float
    words: int
    schema_type: str = Field(serialization_alias="schema")
    images: int
    stage: str
    ago: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ContentJobResponse:
        page_type = row.get("page_type")
        framework = row.get("framework")
        target = row.get("target")
        status = row.get("status")
        return cls(
            id=str(row["code"]),
            client=row.get("client_name", ""),
            color=row.get("color", ""),
            page_type=page_type if page_type in _PAGE_TYPES else "service",
            topic=row.get("topic", ""),
            framework=framework if framework in _FRAMEWORKS else "AIDA",
            auto=bool(row.get("auto", False)),
            target=target if target in _TARGETS else "WordPress",
            status=status if status in _STATUSES else "queued",
            cost=float(row.get("cost", 0) or 0),
            words=int(row.get("words", 0) or 0),
            schema_type=row.get("schema_type", ""),
            images=int(row.get("images", 0) or 0),
            stage=row.get("stage", ""),
            ago=relative_ago(row.get("created_at"), empty="just now"),
        )


def to_response(row: dict[str, Any]) -> ContentJobResponse:
    """Map a ``content_jobs`` row to the frontend ``ContentJob`` shape."""
    return ContentJobResponse.from_row(row)
