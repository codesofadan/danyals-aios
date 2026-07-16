"""Keyword-research request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module, so these shapes are owned here
(unlike the contract-locked Part-2/7 responses). The module's own unit tests freeze
the emitted key set + the ``search_intent`` enum tuple, so a drift is still caught -
this is the server-authoritative equivalent of the contract lock.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute). The internal
``client_id`` NEVER leaks: ``client`` is the snapshotted display name. The capitalised
``SearchIntent`` labels ARE the display cell the tool workspace renders verbatim.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# The five search-intent labels - capitalised = the exact display cell + the DB
# search_intent enum. Pinned verbatim (a module unit test asserts the tuple).
SearchIntent = Literal["Informational", "Commercial", "Transactional", "Navigational", "Local"]

_INTENTS: frozenset[str] = frozenset(
    {"Informational", "Commercial", "Transactional", "Navigational", "Local"}
)


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a psycopg ``Decimal`` / ``None`` numeric to a plain ``float``."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class KeywordResponse(BaseModel):
    """One keyword in the bank - a clean, server-authoritative field set. ``client``
    is the snapshotted display name (the internal ``client_id`` never leaks);
    ``cluster`` is the joined cluster name (``""`` when unclustered)."""

    code: str
    keyword: str
    client: str
    volume: int
    difficulty: float
    cpc: float
    intent: str
    cluster: str
    opportunity: float
    winnable: bool
    target_url: str = Field(serialization_alias="targetUrl")
    geo: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> KeywordResponse:
        intent = row.get("intent")
        return cls(
            code=str(row.get("code", "")),
            keyword=str(row.get("keyword", "")),
            client=str(row.get("client_name", "") or ""),
            volume=int(row.get("volume", 0) or 0),
            difficulty=round(_f(row.get("difficulty")), 2),
            cpc=round(_f(row.get("cpc")), 2),
            intent=intent if intent in _INTENTS else "",
            cluster=str(row.get("cluster_name", "") or ""),
            opportunity=round(_f(row.get("opportunity")), 2),
            winnable=bool(row.get("winnable")),
            target_url=str(row.get("target_url", "") or ""),
            geo=str(row.get("geo", "") or ""),
        )


class KeywordStats(BaseModel):
    """The keyword-bank summary tiles: how many keywords are saved, how many distinct
    clusters they fall into, and the average difficulty across the bank."""

    saved: int
    clusters: int
    avg_difficulty: float = Field(serialization_alias="avgDifficulty")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> KeywordStats:
        return cls(
            saved=int(row.get("saved", 0) or 0),
            clusters=int(row.get("clusters", 0) or 0),
            avg_difficulty=round(_f(row.get("avg_difficulty")), 1),
        )


class ClusterResponse(BaseModel):
    """One topical cluster (pillar + spokes) with its aggregates. ``client`` is the
    snapshot display name; ``intent`` is the dominant intent (``""`` if none)."""

    name: str
    pillar: str
    intent: str
    size: int
    volume: int
    avg_difficulty: float = Field(serialization_alias="avgDifficulty")
    client: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ClusterResponse:
        intent = row.get("dominant_intent")
        return cls(
            name=str(row.get("name", "") or ""),
            pillar=str(row.get("pillar_keyword", "") or ""),
            intent=intent if intent in _INTENTS else "",
            size=int(row.get("size", 0) or 0),
            volume=int(row.get("total_volume", 0) or 0),
            avg_difficulty=round(_f(row.get("avg_difficulty")), 1),
            client=str(row.get("client_name", "") or ""),
        )


# --- Request models -----------------------------------------------------------


class KeywordCreate(BaseModel):
    """POST /keyword-research/keywords body: bulk-add keywords to the bank.

    ``keywords`` are added to the (optional) client's book at the (optional) geo with
    ``source='manual'`` and default metrics (a later research run enriches them). The
    internal ``client_id`` is server-resolved to a display snapshot; a duplicate
    (client, keyword, geo) is skipped, not errored."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str | None = Field(default=None, alias="clientId")
    geo: str | None = None
    keywords: list[str] = Field(min_length=1, max_length=500)


class KeywordUpdate(BaseModel):
    """PATCH /keyword-research/keywords/{code} body: assign / edit ONE keyword.

    Every field is optional; only the provided ones change. ``client_id`` reassigns
    the keyword to a client (its display name is re-snapshotted server-side);
    ``target_url`` sets the intended landing page; ``intent`` overrides the
    classification (``intent_source`` becomes ``manual``); ``tags`` replaces the tag
    set."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str | None = Field(default=None, alias="clientId")
    target_url: str | None = Field(default=None, alias="targetUrl")
    intent: SearchIntent | None = None
    tags: list[str] | None = None


class KeywordResearchRequest(BaseModel):
    """POST /keyword-research/research body: kick off a keyword research run.

    The worker fetches ``seed``'s ideas + related terms (cost-gated), classifies
    intent, scores opportunity + winnability, clusters them, and upserts the bank -
    optionally scoped to ``client_id`` at ``geo``."""

    model_config = ConfigDict(populate_by_name=True)

    seed: str = Field(min_length=1, max_length=200)
    geo: str | None = None
    client_id: str | None = Field(default=None, alias="clientId")


class ResearchQueuedResponse(BaseModel):
    """The accepted-for-research acknowledgement: the seed + that it was queued."""

    seed: str
    queued: bool


class CannibalizationConflict(BaseModel):
    """One cannibalization conflict: a landing URL claimed by more than one intent
    (two pages competing for the same URL). ``keywords`` are the offending terms."""

    target_url: str = Field(serialization_alias="targetUrl")
    intents: list[str]
    keywords: list[str]
