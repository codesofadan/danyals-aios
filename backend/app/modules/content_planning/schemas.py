"""Typed models for the planning layer (migrations 0084-0092).

These mirror the tables rather than the API. The pipeline reads and writes them
directly, and the router shapes its own response models on top, so a schema change
here never silently alters a frontend contract.

Frozen dataclasses rather than pydantic: nothing here is parsed from untrusted input -
every instance comes from a database row this service just wrote, or from a stage that
constructed it - so validation would cost per-row overhead on the pipeline's hot path
to re-check what the schema already enforces.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Literal

EngagementShape = Literal[
    "single_page", "page_set", "full_site", "continue_existing", "retainer"
]
EngagementStatus = Literal[
    "draft", "planning", "awaiting_sme", "ready", "producing", "paused",
    "completed", "cancelled",
]
MetricSource = Literal["dataforseo", "serp_derived", "operator", "audit"]
DossierStatus = Literal["empty", "partial", "complete"]
SlotSource = Literal["client", "operator", "transcript", "client_site"]
NodeStatus = Literal[
    "planned", "index_only", "briefed", "drafting", "published", "skipped"
]
NodeRole = Literal["hub", "spoke"]


@dataclass(frozen=True)
class Engagement:
    id: str
    shape: EngagementShape
    status: EngagementStatus
    client_id: str | None = None
    client_name: str = ""
    name: str = ""
    scope: dict[str, Any] = field(default_factory=dict)
    budget_cap: float | None = None
    page_target: int = 0
    source_audit_id: str | None = None
    owner_id: str | None = None
    created_at: datetime | None = None

    @property
    def blocks_drafting(self) -> bool:
        """The hard halt, as a property rather than a convention.

        `awaiting_sme` means the client's first-party facts have not been collected.
        The owner's standing decision is that no page drafts until they are, because
        a model asked for Experience it does not have will invent it fluently.
        """
        return self.status in ("draft", "planning", "awaiting_sme", "paused", "cancelled")


@dataclass(frozen=True)
class KeywordTerm:
    keyword: str
    source: MetricSource
    estimated: bool
    volume: int | None = None
    difficulty: float | None = None
    cpc: float | None = None
    competition: float | None = None
    intent: str = ""
    relevance: float | None = None
    opportunity: float | None = None
    cluster_key: str = ""

    @property
    def is_measured(self) -> bool:
        """True only when a provider supplied the numbers.

        The distinction the whole table exists for: a derived figure is allowed to
        exist, but callers that report demand to a client must be able to exclude it.
        """
        return not self.estimated and self.source == "dataforseo"


@dataclass(frozen=True)
class MapNode:
    id: str
    map_id: str
    primary_keyword: str
    status: NodeStatus = "planned"
    role: NodeRole = "spoke"
    parent_id: str | None = None
    silo: str = ""
    page_type: str = "service"
    secondary_keywords: tuple[str, ...] = ()
    intent: str = ""
    target_city: str = ""
    priority: int = 0
    target_words: int = 0
    cluster_key: str = ""
    evidence: str = ""
    info_gain_thesis: str = ""
    content_job_id: str | None = None
    published_url: str = ""


@dataclass(frozen=True)
class SmeSlot:
    slot_key: str
    question: str = ""
    answer: str = ""
    artifact_url: str = ""
    artifact_date: date | None = None
    source: SlotSource = "operator"
    confidence: float = 1.0

    @property
    def answered(self) -> bool:
        """An artifact alone counts: a dated photo or a licence document IS the
        answer, and demanding prose alongside it would reject real evidence."""
        return bool(self.answer.strip() or self.artifact_url.strip())


@dataclass(frozen=True)
class SmeDossier:
    id: str
    engagement_id: str
    cluster_key: str = ""
    status: DossierStatus = "empty"
    slots: tuple[SmeSlot, ...] = ()

    @property
    def answered(self) -> tuple[SmeSlot, ...]:
        return tuple(s for s in self.slots if s.answered)

    @property
    def unanswered(self) -> tuple[SmeSlot, ...]:
        return tuple(s for s in self.slots if not s.answered)

    @property
    def complete(self) -> bool:
        """Complete means EVERY slot is answered, and an empty dossier is NOT complete.

        The empty case matters: a dossier with no slots has had no questions asked, and
        treating that as "nothing missing" would let the hard halt pass exactly the
        engagements it exists to stop.
        """
        return bool(self.slots) and not self.unanswered

    def proof_signals(self) -> frozenset[str]:
        """Proof categories the client can back, for `content_lint.experience`.

        Only ANSWERED slots count. An unanswered slot is a question, not a signal, and
        counting it would let a page claim what nobody has confirmed.
        """
        return frozenset(s.slot_key for s in self.answered)


@dataclass(frozen=True)
class ShingleOverlap:
    """One prior page whose outline overlaps a candidate's."""

    job_id: str | None
    node_id: str | None
    shared: int
    total: int

    @property
    def jaccard(self) -> float:
        return self.shared / self.total if self.total else 0.0
