"""Local-SEO request/response models - SERVER-AUTHORITATIVE.

No ``frontend/lib/*.ts`` type mirrors this module, so these shapes are owned here
(unlike the contract-locked Part-2/7 responses). The module's own unit tests freeze
the emitted key set, so a drift is still caught - the server-authoritative
equivalent of the contract lock.

Python attributes stay snake_case; a multi-word wire key re-aliases to camelCase via
``serialization_alias`` (ruff N815 forbids a raw camelCase attribute).

Two secrets-shaped fields are structurally impossible to leak here, and each is
pinned by its own test:

* ``client_id`` NEVER leaks - ``client`` is the snapshotted display name.
* ``oauth_vault_ref`` NEVER leaks - ``GbpProfileResponse`` has no such field at all
  (not an excluded one). It is a pointer to a vault-sealed refresh token; the only
  thing the wire says about it is the boolean ``oauthConnected``.

``rank`` is ``int | None`` all the way to the wire: NULL means "checked, not in the
local pack" - an honest absence that must never be rendered as a fabricated number.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# The local pack is a 3-pack (re-exported from the provider so the tone threshold and
# the provider's in_map_pack flag can never drift apart).
from app.modules.local_seo.provider import MAP_PACK_SIZE

__all__ = [
    "MAP_PACK_SIZE",
    "GbpProfileResponse",
    "LocalRankHistoryPoint",
    "LocalRankingCreate",
    "LocalRankingResponse",
    "LocalRankingUpdate",
    "LocalStats",
    "NapAlignmentReport",
    "NapDirectoryFinding",
    "ProfileAuditReport",
    "ProfileUpsert",
    "RefreshQueuedResponse",
]


def _f(value: Any, default: float = 0.0) -> float:
    """Coerce a psycopg ``Decimal`` / ``None`` numeric to a plain ``float``."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _opt_int(value: Any) -> int | None:
    """Coerce to ``int``, PRESERVING ``None``.

    Deliberately not ``int(x or 0)``: a NULL rank means "not in the pack" and must
    stay NULL on the wire. Collapsing it to 0 would invent a rank better than #1.
    """
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _str_list(value: Any) -> list[str]:
    """Coerce a jsonb array column to ``list[str]`` (anything else -> empty)."""
    if not isinstance(value, list):
        return []
    return [str(v) for v in value if v is not None]


class LocalRankingResponse(BaseModel):
    """One tracked map-pack ranking - the CURRENT state for (location, keyword, geo).

    ``location`` is the profile's ``location_label`` and ``client`` is the snapshotted
    display name (the internal ``client_id`` never leaks) - together they are the
    workspace's ``[Location]`` + ``[Client]`` cells. ``rank`` is ``None`` when the
    business is not in the pack; ``change`` is the movement since the previous check
    (positive = improved, i.e. moved toward #1).
    """

    id: str
    location: str
    client: str
    keyword: str
    geo: str
    rank: int | None
    previous_rank: int | None = Field(serialization_alias="previousRank")
    change: int
    in_map_pack: bool = Field(serialization_alias="inMapPack")
    found_url: str = Field(serialization_alias="foundUrl")
    top_competitors: list[str] = Field(serialization_alias="topCompetitors")
    provider: str
    is_active: bool = Field(serialization_alias="isActive")
    last_checked_at: str = Field(serialization_alias="lastCheckedAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> LocalRankingResponse:
        checked = row.get("last_checked_at")
        return cls(
            id=str(row.get("id", "")),
            # location_label arrives via the profile join; client_name is the snapshot.
            location=str(row.get("location_label", "") or ""),
            client=str(row.get("client_name", "") or ""),
            keyword=str(row.get("keyword", "") or ""),
            geo=str(row.get("geo", "") or ""),
            rank=_opt_int(row.get("rank")),
            previous_rank=_opt_int(row.get("previous_rank")),
            change=int(row.get("rank_change", 0) or 0),
            in_map_pack=bool(row.get("in_map_pack")),
            found_url=str(row.get("found_url", "") or ""),
            top_competitors=_str_list(row.get("top_competitors")),
            provider=str(row.get("provider", "") or ""),
            is_active=bool(row.get("is_active", True)),
            last_checked_at=checked.isoformat() if checked is not None else "",
        )


class LocalRankHistoryPoint(BaseModel):
    """One append-only point on a ranking's timeline. ``rank`` stays nullable: a check
    that found nothing is a real, chartable observation ("out of the pack"), not a gap
    - and never a failed check (failures are never appended)."""

    rank: int | None
    in_map_pack: bool = Field(serialization_alias="inMapPack")
    provider: str
    checked_at: str = Field(serialization_alias="checkedAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> LocalRankHistoryPoint:
        checked = row.get("checked_at")
        return cls(
            rank=_opt_int(row.get("rank")),
            in_map_pack=bool(row.get("in_map_pack")),
            provider=str(row.get("provider", "") or ""),
            checked_at=checked.isoformat() if checked is not None else "",
        )


class LocalStats(BaseModel):
    """The local-SEO summary tiles, in ``lib/tools.ts`` KPI order.

    ``gbp_profiles`` counts tracked locations; ``avg_map_rank`` is the mean position
    across RANKED, ACTIVE rows only (see ``service.average_map_rank`` for why);
    ``citations`` is read from the EXISTING 0018 ``citations`` ledger - this module
    does not own a citations table.
    """

    gbp_profiles: int = Field(serialization_alias="gbpProfiles")
    avg_map_rank: float = Field(serialization_alias="avgMapRank")
    citations: int

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> LocalStats:
        return cls(
            gbp_profiles=int(row.get("gbp_profiles", 0) or 0),
            avg_map_rank=round(_f(row.get("avg_map_rank")), 1),
            citations=int(row.get("citations", 0) or 0),
        )


class GbpProfileResponse(BaseModel):
    """One GBP location profile - PROFILE MANAGEMENT + NAP, read-only.

    Scope guard: there is no posting and no review-reply surface anywhere in this
    module, so this model carries no such fields by construction.

    ``oauth_vault_ref`` is ABSENT (not excluded): the wire says only WHETHER a token
    is connected, never where it is sealed. ``client`` is the snapshot display name.
    """

    id: str
    client: str
    location: str
    place_id: str = Field(serialization_alias="placeId")
    primary_category: str = Field(serialization_alias="primaryCategory")
    secondary_categories: list[str] = Field(serialization_alias="secondaryCategories")
    nap_name: str = Field(serialization_alias="napName")
    nap_address: str = Field(serialization_alias="napAddress")
    nap_phone: str = Field(serialization_alias="napPhone")
    website: str
    hours: dict[str, Any]
    review_count: int = Field(serialization_alias="reviewCount")
    avg_rating: float | None = Field(serialization_alias="avgRating")
    completeness: int
    oauth_connected: bool = Field(serialization_alias="oauthConnected")
    last_synced_at: str = Field(serialization_alias="lastSyncedAt")

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> GbpProfileResponse:
        synced = row.get("last_synced_at")
        rating = row.get("avg_rating")
        hours = row.get("regular_hours")
        cats = row.get("secondary_categories")
        return cls(
            id=str(row.get("id", "")),
            client=str(row.get("client_name", "") or ""),
            location=str(row.get("location_label", "") or ""),
            place_id=str(row.get("place_id", "") or ""),
            primary_category=str(row.get("primary_category", "") or ""),
            secondary_categories=[str(c) for c in cats] if isinstance(cats, list) else [],
            nap_name=str(row.get("nap_name", "") or ""),
            nap_address=str(row.get("nap_address", "") or ""),
            nap_phone=str(row.get("nap_phone", "") or ""),
            website=str(row.get("website_uri", "") or ""),
            hours=hours if isinstance(hours, dict) else {},
            review_count=int(row.get("review_count", 0) or 0),
            # An un-synced profile has NO rating - 0.0 would read as "rated 0 stars".
            avg_rating=round(_f(rating), 1) if rating is not None else None,
            completeness=int(row.get("completeness_score", 0) or 0),
            oauth_connected=bool(row.get("oauth_connected")),
            last_synced_at=synced.isoformat() if synced is not None else "",
        )


class ProfileAuditReport(BaseModel):
    """A profile's completeness audit: the 0-100 score + the per-field findings.

    ``findings`` maps a checklist field to ``ok``/``missing``/``thin``; ``missing``
    lists the fields to fix, so the surface is actionable rather than a bare number.
    """

    id: str
    location: str
    client: str
    completeness: int
    primary_category: str = Field(serialization_alias="primaryCategory")
    secondary_categories: list[str] = Field(serialization_alias="secondaryCategories")
    findings: dict[str, str]
    missing: list[str]


class NapDirectoryFinding(BaseModel):
    """One directory's NAP verdict from the EXISTING 0018 citations ledger.

    ``status`` is the ledger's ``nap_status`` AFTER normalization review;
    ``cosmetic_only`` marks a row the ledger flagged ``inconsistent`` whose observed
    value NORMALIZES equal to the profile's canonical NAP ("123 Main St." vs "123
    Main Street") - real formatting variance, not a real listing error.
    """

    directory: str
    status: str
    note: str
    cosmetic_only: bool = Field(serialization_alias="cosmeticOnly")


class NapAlignmentReport(BaseModel):
    """A profile's NAP alignment across its citation directories.

    The GBP profile is the CANONICAL NAP; the 0018 ``citations`` ledger holds each
    directory's verdict against it. ``inconsistent`` counts REAL drift only - rows
    whose observed value merely reformats the canonical one are counted in
    ``cosmetic_only`` instead, so an operator's fix-list is not padded with
    "St. vs Street" noise. ``aligned`` is true when the canonical NAP is complete and
    no directory carries real drift or a missing listing.
    """

    id: str
    location: str
    client: str
    nap_name: str = Field(serialization_alias="napName")
    nap_address: str = Field(serialization_alias="napAddress")
    nap_phone: str = Field(serialization_alias="napPhone")
    directories: list[NapDirectoryFinding]
    consistent: int
    inconsistent: int
    missing: int
    cosmetic_only: int = Field(serialization_alias="cosmeticOnly")
    aligned: bool


# --- Request models -----------------------------------------------------------


class LocalRankingCreate(BaseModel):
    """POST /local-seo/rankings body: track a keyword's map-pack position for ONE
    GBP profile.

    ``profile_id`` names the location; ``geo`` is the SINGLE representative locale to
    check at (omitted -> the profile's default market). There is no grid, no radius
    and no point count by design. The client + its display snapshot are resolved
    SERVER-SIDE from the profile, so a caller can never mis-attribute a ranking.
    """

    model_config = ConfigDict(populate_by_name=True)

    profile_id: str = Field(alias="profileId")
    keyword: str = Field(min_length=1, max_length=200)
    geo: str | None = Field(default=None, max_length=200)


class LocalRankingUpdate(BaseModel):
    """PATCH /local-seo/rankings/{id} body: activate / deactivate ONE tracked row.

    Deactivating retires a keyword from the refresh beat (it stops costing money)
    while KEEPING its history - the reason this is a flag and not a delete.
    """

    model_config = ConfigDict(populate_by_name=True)

    is_active: bool = Field(alias="isActive")


class ProfileUpsert(BaseModel):
    """POST/PATCH /local-seo/profiles body: create or edit ONE GBP location profile.

    On POST, ``client_id`` + ``location_label`` are required (the client's display
    name is snapshotted server-side); on PATCH every field is optional and only the
    provided ones change. ``completeness_score``/``audit`` are DERIVED server-side
    from these fields and are deliberately not settable.
    """

    model_config = ConfigDict(populate_by_name=True)

    client_id: str | None = Field(default=None, alias="clientId")
    location_label: str | None = Field(default=None, alias="locationLabel", max_length=200)
    google_location_id: str | None = Field(default=None, alias="googleLocationId")
    place_id: str | None = Field(default=None, alias="placeId")
    primary_category: str | None = Field(default=None, alias="primaryCategory")
    secondary_categories: list[str] | None = Field(default=None, alias="secondaryCategories")
    nap_name: str | None = Field(default=None, alias="napName")
    nap_address: str | None = Field(default=None, alias="napAddress")
    nap_phone: str | None = Field(default=None, alias="napPhone")
    website_uri: str | None = Field(default=None, alias="websiteUri")
    regular_hours: dict[str, Any] | None = Field(default=None, alias="regularHours")


class RefreshQueuedResponse(BaseModel):
    """The accepted-for-refresh acknowledgement: what was queued, and that it was.

    ``held`` is the honest degraded answer for a GBP sync that cannot run yet (no
    key / no OAuth token): the request was understood and NOT queued, rather than
    silently dropped or crashed. ``reason`` names why.
    """

    id: str
    queued: bool
    held: bool = False
    reason: str = ""
