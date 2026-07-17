"""Rank-tracker request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module, so these shapes are owned here
(unlike the contract-locked Part-2/7 responses). The module's own unit tests freeze the
emitted key set + the enum tuples, so a drift is still caught - this is the
server-authoritative equivalent of the contract lock.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute). The internal
``client_id`` NEVER leaks: ``client`` is the snapshotted display name.

Two shapes carry real semantics worth reading before changing them:

* ``position`` is ``int | None`` and the ``None`` is LOAD-BEARING - it means
  "successfully checked, not in the top-N" (unranked), NOT "the check failed". A
  failed check writes nothing at all, so it can never surface here.
* ``change`` follows the frontend's ``{delta, dir}`` KPI convention: ``value`` is the
  magnitude (or the word ``new``/``lost``) and ``direction`` carries the sign, so the
  renderer picks the arrow + tone rather than parsing a signed string.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.util.timefmt import format_date, relative_ago

# The DB enums, pinned verbatim (module unit tests assert each tuple against the
# migration's ``create type``). These ARE the wire values.
RankEngine = Literal["google", "bing"]
RankDevice = Literal["desktop", "mobile", "tablet"]
RankStatus = Literal["active", "paused"]
RankCadence = Literal["daily", "weekly"]

ENGINES: tuple[str, ...] = ("google", "bing")
DEVICES: tuple[str, ...] = ("desktop", "mobile", "tablet")
STATUSES: tuple[str, ...] = ("active", "paused")
CADENCES: tuple[str, ...] = ("daily", "weekly")

# The movement directions. ``up`` = the position IMPROVED (a smaller number is better,
# so an improvement is a DECREASE - the single most inverted thing in rank tracking);
# ``new`` = first time it ranked; ``lost`` = it fell out of the tracked window.
RankDirection = Literal["up", "down", "flat", "new", "lost"]
DIRECTIONS: tuple[str, ...] = ("up", "down", "flat", "new", "lost")


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a psycopg ``Decimal`` / ``None`` numeric to a plain ``float``."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_int(value: Any) -> int | None:
    """Coerce to ``int``, preserving a MEANINGFUL ``None`` (unranked / never checked).

    A ``or 0`` here would be a silent lie: it would turn "unranked" into "position 0",
    i.e. better than #1.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class RankChange(BaseModel):
    """One keyword's movement since the previous check.

    Mirrors the frontend's KPI ``{delta, dir}`` convention: ``value`` is the display
    magnitude, ``direction`` carries the meaning. ``up``/``down`` pair with a numeric
    magnitude; ``new``/``lost`` repeat the word in ``value`` because there is no
    magnitude to show (there was no previous / there is no current position).
    """

    value: str
    direction: RankDirection


class RankKeywordResponse(BaseModel):
    """One tracked keyword - a clean, server-authoritative field set.

    ``client`` is the snapshotted display name (the internal ``client_id`` never
    leaks). ``position``/``bestPosition`` are ``null`` when unranked. ``stale`` flags a
    subscription whose nightly check has not landed within its cadence window (a
    blocked money-dial, a vendor outage), so a stalled tracker is VISIBLE rather than
    silently showing yesterday's number as if it were today's.
    """

    code: str
    keyword: str
    client: str
    position: int | None
    change: RankChange
    best_position: int | None = Field(serialization_alias="bestPosition")
    url: str
    target_url: str = Field(serialization_alias="targetUrl")
    tags: list[str]
    engine: str
    device: str
    location: str
    cadence: str
    status: str
    features: list[str]
    checked: str
    stale: bool

    @classmethod
    def from_row(cls, row: dict[str, Any], *, change: RankChange, stale: bool) -> RankKeywordResponse:
        """Project a ``tracked_keywords`` row (+ the service's computed movement and
        staleness verdict) onto the wire shape."""
        return cls(
            code=str(row.get("code", "") or ""),
            keyword=str(row.get("keyword", "") or ""),
            client=str(row.get("client_name", "") or ""),
            position=_opt_int(row.get("latest_position")),
            change=change,
            best_position=_opt_int(row.get("best_position")),
            url=str(row.get("latest_url", "") or ""),
            target_url=str(row.get("target_url", "") or ""),
            tags=list(row.get("tags") or []),
            engine=str(row.get("engine", "") or ""),
            device=str(row.get("device", "") or ""),
            location=str(row.get("location", "") or ""),
            cadence=str(row.get("cadence", "") or ""),
            status=str(row.get("status", "") or ""),
            features=list(row.get("latest_features") or []),
            checked=relative_ago(row.get("latest_checked_at"), empty="never"),
            stale=stale,
        )


class RankStats(BaseModel):
    """The rank-tracker summary tiles: how many keywords are tracked, the average
    position across the RANKED ones, and how many sit in the top 3."""

    tracked: int
    avg_position: float = Field(serialization_alias="avgPosition")
    top_three: int = Field(serialization_alias="topThree")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RankStats:
        return cls(
            tracked=int(row.get("tracked", 0) or 0),
            avg_position=round(_f(row.get("avg_position")), 1),
            top_three=int(row.get("top_three", 0) or 0),
        )


class RankHistoryPoint(BaseModel):
    """One day's snapshot in a keyword's history.

    ``position`` is ``null`` for a day the keyword was checked and found unranked. A
    day the check FAILED has no point at all - the series simply has a gap, which is
    honest, where a null-position point would read as a lost ranking.
    """

    date: str
    position: int | None
    url: str
    features: list[str]
    delta: int | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> RankHistoryPoint:
        return cls(
            date=format_date(row.get("checked_on")),
            position=_opt_int(row.get("position")),
            url=str(row.get("ranking_url", "") or ""),
            features=list(row.get("serp_features") or []),
            delta=_opt_int(row.get("delta")),
        )


class RankCostProjection(BaseModel):
    """The N-A subscription-time cost commitment for ONE client.

    Rank tracking is the platform's first STANDING per-client cost, and the CLIENT
    pays. Gating only each individual check would let the agency sign a client up to a
    runaway monthly bill one keyword at a time, so the COMMITMENT is priced and
    checked here, at configuration time.

    ``monthlyCost`` = SUM over the client's ACTIVE keywords of
    ``checksPerMonth(cadence) x provider.estimated_cost(depth)``. ``withinBudget`` is
    False when that commitment exceeds what is left of the client's monthly cap; the
    bulk-add REJECTS in that case and ``message`` says so in plain words.
    """

    client: str
    tracked: int
    daily: int
    weekly: int
    checks_per_month: float = Field(serialization_alias="checksPerMonth")
    cost_per_check: float = Field(serialization_alias="costPerCheck")
    monthly_cost: float = Field(serialization_alias="monthlyCost")
    budget_cap: float = Field(serialization_alias="budgetCap")
    budget_spent: float = Field(serialization_alias="budgetSpent")
    budget_remaining: float = Field(serialization_alias="budgetRemaining")
    within_budget: bool = Field(serialization_alias="withinBudget")
    provider: str
    live: bool
    message: str


class RankKeywordsAdded(BaseModel):
    """The bulk-add result: the created subscriptions AND the monthly commitment they
    now carry, so the caller sees the standing bill it just signed the client up to in
    the same response - not a month later on the invoice."""

    keywords: list[RankKeywordResponse]
    projection: RankCostProjection


# --- Request models -----------------------------------------------------------


class RankKeywordCreate(BaseModel):
    """POST /rank-tracker/keywords body: bulk-subscribe keywords for ONE client.

    ``client_id`` is REQUIRED (unlike the 0035 keyword bank): a tracked keyword is a
    standing per-client cost, so there is no un-owned tracking. Every keyword in the
    batch shares one engine/device/locale/cadence - that tuple plus the keyword IS the
    uniqueness key, so a duplicate subscription is skipped rather than double-billed.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str = Field(alias="clientId")
    site_id: str | None = Field(default=None, alias="siteId")
    keywords: list[str] = Field(min_length=1, max_length=500)
    target_url: str | None = Field(default=None, alias="targetUrl")
    engine: RankEngine = "google"
    device: RankDevice = "desktop"
    location: str = ""
    location_code: int | None = Field(default=None, alias="locationCode")
    language: str = "en"
    country: str = "us"
    tags: list[str] | None = None
    cadence: RankCadence = "weekly"


class RankKeywordUpdate(BaseModel):
    """PATCH /rank-tracker/keywords/{code} body: re-configure ONE subscription.

    Every field is optional; only the provided ones change. ``status`` pauses/resumes
    the nightly spend WITHOUT discarding the history; ``cadence`` re-prices the
    standing commitment; ``tags`` replaces the tag set; ``target_url`` re-points the
    page the keyword is meant to land.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: RankStatus | None = None
    cadence: RankCadence | None = None
    tags: list[str] | None = None
    target_url: str | None = Field(default=None, alias="targetUrl")


class RankCheckQueued(BaseModel):
    """The accepted-for-check acknowledgement: the keyword code + that it was queued.

    ``queued`` is False when the keyword was ALREADY checked today and ``force`` was
    not set - the on-demand check is deduped to one paid pull per day, so a user
    hammering the button cannot re-bill the client.
    """

    code: str
    queued: bool
    reason: str = ""
