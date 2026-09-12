"""Wire shapes for the grid tracker. SERVER-AUTHORITATIVE - no ``frontend/lib`` type
mirrors this module (exactly like ``local_seo``), so this file owns the contract and
its own shape tests pin it.

THE SHAPES ENCODE THE THREE-STATE CONTRACT RATHER THAN FLATTENING IT.

The tempting wire shape for a heat-map point is ``{lat, lng, rank}`` with a nullable
rank. It is wrong for the same reason the database refuses it: the renderer then has
exactly two cases (a number, or nothing) for three different facts - ranked, measured
and absent, and never measured. Whatever colour "nothing" gets, one of the last two is
being misreported, and the one that suffers is always the honest gap.

So ``status`` travels on every point and is REQUIRED reading for the client: the
legend has an 'unmeasured' band, and it is not the worst one.

Likewise ``shareTop3`` and ``avgRank`` are nullable on the wire and mean "not
computable from what was measured" - never 0 and never 100. A UI that renders a null
as a zero re-introduces the fabrication at the last hop.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.modules.grid_tracker.service import coverage_band
from app.modules.local_seo.provider import MAP_PACK_SIZE

__all__ = [
    "MAP_PACK_SIZE",
    "GridDefinitionCreate",
    "GridDefinitionResponse",
    "GridDefinitionUpdate",
    "GridPointResponse",
    "GridRunDetail",
    "GridRunResponse",
    "RunQueuedResponse",
]

#: Mirrors ``0138``'s CHECK (rings between 1 and 5). Stated here so a bad request is
#: a 422 with a useful message rather than a 500 from a constraint violation.
MIN_RINGS, MAX_RINGS = 1, 5
MIN_SPACING_KM, MAX_SPACING_KM = 0.10, 50.00


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a psycopg ``Decimal`` / ``None`` numeric to a plain ``float``."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_f(value: Any) -> float | None:
    """Coerce to ``float``, PRESERVING ``None``.

    Deliberately not ``float(x or 0)``: a null ``avg_rank`` means "nothing ranked" and
    a null ``share_top3`` means "nothing was measured". Collapsing either to 0.0 turns
    an absence of evidence into a measured zero - which for ``avg_rank`` would read as
    a position better than #1.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]


def _iso(value: Any) -> str:
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else ""


class GridDefinitionCreate(BaseModel):
    """Create one standing grid.

    ``centerLat``/``centerLng`` are OPTIONAL: omitted, the server resolves the centre
    from the profile's Places anchor and records ``centerSource='places'``. Supplied,
    they are taken verbatim and recorded as ``'operator'``. There is no third path -
    the server never derives a coordinate from a postal address at probe time, because
    a silently mis-geocoded centre moves the whole grid without changing any number on
    the screen.
    """

    #: PICK A CLIENT AND THAT IS ALL. The platform already holds this business's
    #: canonical NAP (`business_profiles`), so the location label, business name,
    #: address and coordinates are all resolved server-side. Making an operator retype
    #: them asks for facts the system has - and every retype is a chance to enter a
    #: different address than the one the citations module is submitting, which is the
    #: NAP inconsistency the off-page module exists to remove.
    client_id: str | None = Field(default=None, alias="clientId")
    #: The explicit location, for a client with several. Omitted, the server uses (or
    #: creates) the one derived from the client's business profile.
    profile_id: str | None = Field(default=None, alias="profileId")
    keyword: str = Field(min_length=1, max_length=200)
    center_lat: float | None = Field(default=None, ge=-90, le=90, alias="centerLat")
    center_lng: float | None = Field(default=None, ge=-180, le=180, alias="centerLng")
    #: An N x N square is the market's shape and the default; `rings` is kept only so
    #: a pre-0143 grid can still be recreated exactly as it was probed.
    shape: str = Field(default="square", pattern="^(square|rings)$")
    #: N for an N x N grid. Odd only, so the centre cell sits on the business.
    grid_size: int = Field(default=5, ge=3, le=11, alias="gridSize")
    rings: int = Field(default=2, ge=MIN_RINGS, le=MAX_RINGS)
    ring_spacing_km: float = Field(
        default=1.5, ge=MIN_SPACING_KM, le=MAX_SPACING_KM, alias="ringSpacingKm"
    )

    model_config = {"populate_by_name": True, "extra": "ignore"}

    @property
    def point_count(self) -> int:
        """What this grid will cost per run, in probes. The SAME formula as 0143's
        generated column and ``build_grid`` - one definition, three places, and the
        tests hold them together."""
        if self.shape == "rings":
            return 1 + 8 * self.rings
        return self.grid_size * self.grid_size


class GridDefinitionUpdate(BaseModel):
    """The activate/deactivate flag - the only mutable field.

    Geometry is deliberately immutable: editing the centre or the rings of a grid that
    already has runs would make its history incomparable point-for-point while leaving
    every stored run looking like part of one series. Changing the shape means a new
    grid.
    """

    is_active: bool = Field(alias="isActive")

    model_config = {"populate_by_name": True, "extra": "ignore"}


class GridDefinitionResponse(BaseModel):
    """One standing grid, with its geometry and what a run of it costs."""

    id: str
    client: str
    location: str
    keyword: str
    center_lat: float = Field(serialization_alias="centerLat")
    center_lng: float = Field(serialization_alias="centerLng")
    center_source: str = Field(serialization_alias="centerSource")
    #: WHICH listing a `places` centre came from. Shown beside the coordinates so a
    #: centre resolved to the wrong city is obvious before a run is paid for - Places
    #: matches on business NAME and will cross a continent to do it.
    center_matched: str = Field(default="", serialization_alias="centerMatched")
    shape: str
    grid_size: int = Field(serialization_alias="gridSize")
    rings: int
    ring_spacing_km: float = Field(serialization_alias="ringSpacingKm")
    point_count: int = Field(serialization_alias="pointCount")
    is_active: bool = Field(serialization_alias="isActive")
    last_run_at: str = Field(serialization_alias="lastRunAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GridDefinitionResponse:
        return cls(
            id=str(row.get("id", "")),
            client=str(row.get("client_name", "") or ""),
            location=str(row.get("location_label", "") or ""),
            keyword=str(row.get("keyword", "") or ""),
            center_lat=_f(row.get("center_lat")),
            center_lng=_f(row.get("center_lng")),
            center_source=str(row.get("center_source", "") or ""),
            center_matched=", ".join(
                part for part in (
                    str(row.get("center_matched_name", "") or ""),
                    str(row.get("center_matched_address", "") or ""),
                ) if part
            ),
            shape=str(row.get("shape") or "square"),
            grid_size=int(row.get("grid_size", 0) or 0),
            rings=int(row.get("rings", 0) or 0),
            ring_spacing_km=_f(row.get("ring_spacing_km")),
            point_count=int(row.get("point_count", 0) or 0),
            is_active=bool(row.get("is_active", True)),
            last_run_at=_iso(row.get("last_run_at")),
        )


class GridRunResponse(BaseModel):
    """One execution, summarised.

    ``pointsMeasured`` is published as its own field rather than left for the client to
    add up, because it is the denominator of every ratio here and a client that
    recomputed it from ``pointsTotal`` would get the pessimistic number this module
    exists to avoid.
    """

    id: str
    definition_id: str = Field(serialization_alias="definitionId")
    status: str
    reason: str
    #: The geometry AS RUN, copied onto the run row at queue time. Published so the
    #: heat map labels its rings from what was ACTUALLY probed - a definition edited
    #: since would otherwise re-scale an old run's picture without changing its data.
    rings: int
    ring_spacing_km: float = Field(serialization_alias="ringSpacingKm")
    points_total: int = Field(serialization_alias="pointsTotal")
    points_measured: int = Field(serialization_alias="pointsMeasured")
    points_ranked: int = Field(serialization_alias="pointsRanked")
    points_absent: int = Field(serialization_alias="pointsAbsent")
    points_error: int = Field(serialization_alias="pointsError")
    #: None = nothing ranked. Never 0.
    avg_rank: float | None = Field(serialization_alias="avgRank")
    #: None = nothing measured. Never 0.
    share_top3: float | None = Field(serialization_alias="shareTop3")
    #: The legend band, derived server-side so every surface bands identically.
    coverage: str
    provider: str
    cost_usd: float = Field(serialization_alias="costUsd")
    started_at: str = Field(serialization_alias="startedAt")
    finished_at: str = Field(serialization_alias="finishedAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GridRunResponse:
        ranked = int(row.get("points_ranked", 0) or 0)
        absent = int(row.get("points_absent", 0) or 0)
        share = _opt_f(row.get("share_top3"))
        return cls(
            id=str(row.get("id", "")),
            definition_id=str(row.get("definition_id", "")),
            status=str(row.get("status", "") or ""),
            reason=str(row.get("reason", "") or ""),
            rings=int(row.get("rings", 0) or 0),
            ring_spacing_km=_f(row.get("ring_spacing_km")),
            points_total=int(row.get("points_total", 0) or 0),
            points_measured=ranked + absent,
            points_ranked=ranked,
            points_absent=absent,
            points_error=int(row.get("points_error", 0) or 0),
            avg_rank=_opt_f(row.get("avg_rank")),
            share_top3=share,
            coverage=coverage_band(share),
            provider=str(row.get("provider", "") or ""),
            cost_usd=_f(row.get("cost_usd")),
            started_at=_iso(row.get("started_at")),
            finished_at=_iso(row.get("finished_at")),
        )


class GridPointResponse(BaseModel):
    """One probe. ``status`` is the point of this shape - see the module docstring."""

    lat: float
    lng: float
    label: str
    ring: int
    #: 'ranked' | 'absent' | 'error'
    status: str
    #: Present only for 'ranked'. Null for BOTH 'absent' and 'error' - which is why
    #: the renderer must read `status`, not the nullability of this field.
    rank: int | None
    in_map_pack: bool = Field(serialization_alias="inMapPack")
    top_competitors: list[str] = Field(serialization_alias="topCompetitors")
    found_url: str = Field(serialization_alias="foundUrl")
    #: Present only for 'error'. A short sanitized reason, never a raw exception.
    error: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GridPointResponse:
        rank = _opt_int(row.get("rank"))
        status = str(row.get("status", "") or "")
        return cls(
            lat=_f(row.get("lat")),
            lng=_f(row.get("lng")),
            label=str(row.get("label", "") or ""),
            ring=int(row.get("ring", 0) or 0),
            status=status,
            rank=rank,
            in_map_pack=status == "ranked" and rank is not None and rank <= MAP_PACK_SIZE,
            top_competitors=_str_list(row.get("top_competitors")),
            found_url=str(row.get("found_url", "") or ""),
            error=str(row.get("error", "") or ""),
        )


class GridRunDetail(BaseModel):
    """A run plus its points: everything the heat map needs in one read."""

    run: GridRunResponse
    points: list[GridPointResponse]


class RunQueuedResponse(BaseModel):
    """The answer to "run this grid now".

    ``queued=False`` with ``held=True`` is a REFUSAL that is not an error: no live
    coordinate-capable provider, the dial is off, or a run is already in flight. The
    reason is a stable machine-readable token so the UI can explain it precisely
    instead of showing a spinner that never resolves.
    """

    definition_id: str = Field(serialization_alias="definitionId")
    queued: bool = False
    held: bool = False
    reason: str = ""
    #: What this run will cost if it proceeds, in probes - shown before confirming.
    point_count: int = Field(default=0, serialization_alias="pointCount")
