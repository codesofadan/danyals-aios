"""Competitor-intel request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module, so these shapes are owned here
(unlike the contract-locked Part-2/7 responses). The module's own unit tests freeze the
emitted key set + the enum tuples, so a drift is still caught - this is the
server-authoritative equivalent of the contract lock.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute). The internal
``client_id`` NEVER leaks: ``client`` is the snapshotted display name.

Two shapes carry real semantics worth reading before changing them:

* ``clientPosition`` is ``int | None`` and the ``None`` is LOAD-BEARING - it means the
  client does NOT rank for the term at all (a PURE gap), NOT "position 0" and NOT "we
  failed to look". It arrives from the Rank Tracker's ``latest_position``, where NULL
  already carries the same meaning.
* ``shareOfVoice`` is PROVISIONAL - a CTR-curve-derived estimate, not a measurement.
  ``provisional`` rides along on the response so the reader knows it (mirroring the
  content-QA score's own ``provisional`` flag).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.util.timefmt import relative_ago

# The DB enums, pinned verbatim (module unit tests assert each tuple against the
# migration's ``create type``). These ARE the wire values.
DiscoverySource = Literal["manual", "serp_auto"]
GapType = Literal["missing", "weak", "shared", "untapped"]

DISCOVERY_SOURCES: tuple[str, ...] = ("manual", "serp_auto")
GAP_TYPES: tuple[str, ...] = ("missing", "weak", "shared", "untapped")

# REUSED from 0035 (public.search_intent) - NOT re-declared. The module's schema test
# asserts this tuple against the keyword_data seam's INTENT_LABELS, so the two can
# never drift: a gap promoted into the bank casts straight onto that enum.
SEARCH_INTENTS: tuple[str, ...] = (
    "Informational", "Commercial", "Transactional", "Navigational", "Local",
)


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a psycopg ``Decimal`` / ``None`` numeric to a plain ``float``."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_int(value: Any) -> int | None:
    """Coerce to ``int``, preserving a MEANINGFUL ``None`` (the client does not rank).

    An ``or 0`` here would be a silent lie: it would turn "does not rank" into
    "position 0", i.e. better than #1.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class CompetitorResponse(BaseModel):
    """One tracked competitor - a clean, server-authoritative field set.

    ``client`` is the snapshotted display name (the internal ``client_id`` never
    leaks). ``overlap``/``shareOfVoice``/``keywordGaps``/``commonKeywords`` are the
    denormalised read model the analysis worker rolls forward; ``analyzed`` is a
    relative freshness stamp ("never" until the first analysis lands, so an un-analysed
    competitor reads as exactly that rather than as a zero-gap rival).
    """

    code: str
    domain: str
    client: str
    label: str
    source: str
    tracked: bool
    overlap: float
    keyword_gaps: int = Field(serialization_alias="keywordGaps")
    common_keywords: int = Field(serialization_alias="commonKeywords")
    share_of_voice: float = Field(serialization_alias="shareOfVoice")
    analyzed: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CompetitorResponse:
        return cls(
            code=str(row.get("code", "") or ""),
            domain=str(row.get("domain", "") or ""),
            client=str(row.get("client_name", "") or ""),
            label=str(row.get("label", "") or ""),
            source=str(row.get("discovery_source", "") or ""),
            tracked=bool(row.get("tracked", True)),
            overlap=round(_f(row.get("overlap_pct")), 2),
            keyword_gaps=int(row.get("keyword_gaps_count", 0) or 0),
            common_keywords=int(row.get("common_keywords", 0) or 0),
            share_of_voice=round(_f(row.get("share_of_voice")), 2),
            analyzed=relative_ago(row.get("last_analyzed_at"), empty="never"),
        )


class KeywordGapResponse(BaseModel):
    """One analysed keyword gap.

    ``clientPosition`` is ``null`` when the client does not rank for the term at all -
    the PURE gap, and the most valuable row here. ``promoted`` reports whether the gap
    has already been pushed into the keyword bank, so the board can offer the action
    once rather than banking a term twice.
    """

    id: str
    keyword: str
    volume: int
    difficulty: float
    intent: str | None
    competitor_position: int | None = Field(serialization_alias="competitorPosition")
    client_position: int | None = Field(serialization_alias="clientPosition")
    gap_type: str = Field(serialization_alias="gapType")
    opportunity: float
    promoted: bool

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> KeywordGapResponse:
        return cls(
            id=str(row.get("id", "") or ""),
            keyword=str(row.get("keyword", "") or ""),
            volume=int(row.get("volume", 0) or 0),
            difficulty=round(_f(row.get("difficulty")), 2),
            intent=(str(row["intent"]) if row.get("intent") else None),
            competitor_position=_opt_int(row.get("competitor_position")),
            client_position=_opt_int(row.get("client_position")),
            gap_type=str(row.get("gap_type", "") or ""),
            opportunity=round(_f(row.get("opportunity")), 2),
            promoted=row.get("keyword_id") is not None,
        )


class CompetitorStats(BaseModel):
    """The competitor-intel summary tiles: how many competitors are tracked, how many
    open keyword gaps they expose, and the client's share of the measured voice.

    ``shareOfVoice`` here is the aggregate across the board (or the filtered client);
    it is PROVISIONAL for the same reason every SoV number in this module is.
    """

    tracked: int
    keyword_gaps: int = Field(serialization_alias="keywordGaps")
    share_of_voice: float = Field(serialization_alias="shareOfVoice")
    provisional: bool = True

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CompetitorStats:
        return cls(
            tracked=int(row.get("tracked", 0) or 0),
            keyword_gaps=int(row.get("keyword_gaps", 0) or 0),
            share_of_voice=round(_f(row.get("share_of_voice")), 2),
        )


class ShareOfVoiceEntry(BaseModel):
    """One domain's slice of the measured market.

    ``isClient`` marks the client's own row so the renderer can highlight it without
    string-matching a domain. ``visibility`` is the raw estimated monthly clicks the
    share is computed from - exposed so the number is auditable rather than a bare
    percentage the reader has to take on faith.
    """

    domain: str
    label: str
    is_client: bool = Field(serialization_alias="isClient")
    visibility: float
    share: float


class ShareOfVoiceResponse(BaseModel):
    """The share-of-voice split across the client + their TRACKED competitors.

    ``provisional`` is always True and is not decoration: the split is derived from a
    modelled CTR curve (``service.DEFAULT_CTR_CURVE``), not from measured clicks. It
    is comparable BETWEEN the domains here - which is the claim it supports - and it is
    not a traffic figure. ``curve`` echoes the curve actually used so a number can be
    reproduced after ops re-fits it.
    """

    client: str
    entries: list[ShareOfVoiceEntry]
    curve: list[float]
    provisional: bool = True


class BacklinkGapResponse(BaseModel):
    """One referring domain that links to the client's competitors but not the client.

    ``competitors`` is how many of the client's tracked rivals that domain links to -
    the ranking signal, because a domain linking to four rivals is demonstrably
    willing to link in this niche.
    """

    ref_domain: str = Field(serialization_alias="refDomain")
    competitors: int
    authority: int
    spam: int


class DiscoveryQueued(BaseModel):
    """The accepted-for-discovery acknowledgement.

    ``queued`` is False with a ``reason`` when there was nothing to discover FROM (the
    client tracks no keywords yet) - discovery mines the client's tracked SERPs, so an
    empty tracking book makes it a no-op rather than an error.
    """

    client: str
    queued: bool
    reason: str = ""


class AnalysisQueued(BaseModel):
    """The accepted-for-analysis acknowledgement: the competitor code + that it was
    queued. The paid pull is cost-gated in the WORKER, never at this edge."""

    code: str
    queued: bool
    reason: str = ""


class GapPromoted(BaseModel):
    """The result of promoting a gap into the keyword bank.

    ``created`` is False when the gap was ALREADY promoted (or the term already sat in
    the bank): the bank's ``(client, keyword, geo)`` key makes the promote idempotent,
    so a double-click banks one keyword, not two.
    """

    keyword: str
    code: str
    created: bool


# --- Request models -----------------------------------------------------------


class CompetitorCreate(BaseModel):
    """POST /competitor-intel/competitors body: track ONE competitor for ONE client.

    ``client_id`` is REQUIRED (like 0036's tracked keyword, unlike 0035's keyword
    bank): a competitor is always somebody's competitor. ``domain`` is normalised
    server-side before it is stored, so the caller may pass a URL or a bare host and
    still get exactly one competitor row.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(alias="clientId")
    domain: str = Field(min_length=1, max_length=253)
    label: str = ""


class CompetitorUpdate(BaseModel):
    """PATCH /competitor-intel/competitors/{code} body.

    Every field is optional; only the provided ones change. ``tracked`` parks a
    competitor without deleting its analysis - and takes it out of the share-of-voice
    denominator, which is the point: a rival the client does not actually compete with
    should not dilute the split.

    The ``domain`` is deliberately NOT editable: it is half the uniqueness key and the
    subject of every gap row already analysed. Re-pointing it would silently re-label
    another business's ranking data as this one's. Track the other domain instead.
    """

    model_config = ConfigDict(populate_by_name=True)

    label: str | None = None
    tracked: bool | None = None


class DiscoverRequest(BaseModel):
    """POST /competitor-intel/discover body: propose competitors for ONE client from
    their tracked-keyword SERPs."""

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(alias="clientId")
