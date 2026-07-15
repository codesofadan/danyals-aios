"""Context / AI-memory response models (P6B-2).

Curated shapes over the canonical ``entity_context`` store + the freshness
signals the retrieval API (P6B-8) and ``/context/.../health`` (P6B-9) surface.
The internal callers (Content, audit-narrative, the assistant) read
``EntityContextResponse``; operators watch ``ContextHealth``; retrieval returns
ranked ``ContextChunk``s. Sensitive ledger columns (pinecone_id, checksum,
model, token internals) never appear on the wire.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

# The typed entities context is kept for (mirrors the public.context_entity enum).
ContextEntityType = Literal["client", "user", "site"]
# The lifecycle of a context row (mirrors the public.context_status enum).
ContextStatus = Literal["pending", "summarized", "degraded", "error"]

_ENTITY_TYPES: frozenset[str] = frozenset({"client", "user", "site"})
_STATUSES: frozenset[str] = frozenset({"pending", "summarized", "degraded", "error"})


class EntityContextResponse(BaseModel):
    """One entity's living context: the bounded summary + folded facts.

    The safe projection of ``entity_context`` for AI consumers - the LLM prose
    ``summary``, the structured ``facts`` (last-writer-wins by seq), the monotonic
    ``version``, the ``status``, and ``updated_at``. The vector ledger, watermark,
    checksum, model and token internals are deliberately omitted here.
    """

    id: str
    entity_type: ContextEntityType
    entity_id: str
    summary: str
    facts: dict[str, Any]
    version: int
    status: ContextStatus
    updated_at: datetime

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> EntityContextResponse:
        entity_type = row.get("entity_type")
        status = row.get("status")
        facts = row.get("facts")
        return cls(
            id=str(row["id"]),
            entity_type=entity_type if entity_type in _ENTITY_TYPES else "client",
            entity_id=str(row["entity_id"]),
            summary=row.get("summary", "") or "",
            facts=facts if isinstance(facts, dict) else {},
            version=int(row.get("version", 0) or 0),
            status=status if status in _STATUSES else "pending",
            updated_at=row["updated_at"],
        )


class ContextHealth(BaseModel):
    """Per-entity freshness signal - the concrete "how you check" surface.

    ``lag = latest_seq - event_watermark`` is the number of events not yet folded
    into the context; ``stale`` is ``lag > 0``. For ``status='summarized'`` the
    invariant ``event_watermark >= latest_seq`` holds, so ``lag <= 0`` and
    ``stale`` is false. A ``degraded`` row HOLDS its watermark, so lag stays
    visible until provider keys land and it catches up.
    """

    entity_type: ContextEntityType
    entity_id: str
    status: ContextStatus
    version: int
    event_watermark: int
    latest_seq: int
    lag: int
    stale: bool
    updated_at: datetime | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any], latest_seq: int) -> ContextHealth:
        """Build from an ``entity_context`` row + the entity's latest activity seq."""
        watermark = int(row.get("event_watermark", 0) or 0)
        lag = max(latest_seq - watermark, 0)
        entity_type = row.get("entity_type")
        status = row.get("status")
        return cls(
            entity_type=entity_type if entity_type in _ENTITY_TYPES else "client",
            entity_id=str(row["entity_id"]),
            status=status if status in _STATUSES else "pending",
            version=int(row.get("version", 0) or 0),
            event_watermark=watermark,
            latest_seq=latest_seq,
            lag=lag,
            stale=lag > 0,
            updated_at=row.get("updated_at"),
        )


class ContextChunk(BaseModel):
    """One ranked retrieval hit: a stable chunk id, its text, and a similarity
    score (higher = closer). Returned by the retrieval API (P6B-8).

    ``content_checksum`` is the sha256 of ``content``, stamped by the compaction
    engine (P6B-5) so the embed/upsert pipeline (P6B-6) can detect unchanged
    chunks and skip re-embedding. It is ``exclude``d from serialization - a
    checksum is a ledger detail and never rides the retrieval wire; retrieval hits
    leave it empty.
    """

    chunk_key: str
    content: str
    score: float = Field(default=0.0)
    content_checksum: str = Field(default="", exclude=True)
