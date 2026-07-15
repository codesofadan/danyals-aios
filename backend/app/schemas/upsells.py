"""Upsells module request/response models in the frontend shape (``lib/upsells.ts``).

``UpsellResponse`` mirrors ``Upsell`` EXACTLY - the 11 keys ``{id, title,
description, fiverrUrl, active, clicks30d, price, rating, reviews, icon, color}``
and nothing else. ``id`` is the row uuid (a string). ``fiverr_url`` is the Python
attribute re-aliased to the wire key ``fiverrUrl`` (ruff N815 forbids a raw camelCase
attr); ``clicks30d`` is already all-lowercase so it stays a plain attribute.

``CONVERSION_RATE`` mirrors ``upsells.ts`` (the est-conversions tile ratio), kept as
one source of truth server-side.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# Ballpark portal click -> Fiverr order rate (upsells.ts CONVERSION_RATE).
CONVERSION_RATE = 0.062


class UpsellCreate(BaseModel):
    """POST /upsells body: add a Fiverr upsell card (owner/admin).

    ``clicks30d`` is portal-tracked (starts at 0), never client-supplied.
    ``fiverrUrl`` accepts the camelCase wire key or the snake attribute name.
    """

    model_config = ConfigDict(populate_by_name=True)

    title: str = Field(min_length=1)
    description: str = ""
    fiverr_url: str = Field(default="#", alias="fiverrUrl")
    active: bool = True
    price: float = 0.0
    rating: float = 0.0
    reviews: int = 0
    icon: str = ""
    color: str = ""
    sort_order: int = 0


class UpsellUpdate(BaseModel):
    """PATCH /upsells/{id} body: edit an upsell (owner/admin). Every field is
    optional; only those provided are changed. ``clicks30d`` is not editable."""

    model_config = ConfigDict(populate_by_name=True)

    title: str | None = Field(default=None, min_length=1)
    description: str | None = None
    fiverr_url: str | None = Field(default=None, alias="fiverrUrl")
    active: bool | None = None
    price: float | None = None
    rating: float | None = None
    reviews: int | None = None
    icon: str | None = None
    color: str | None = None
    sort_order: int | None = None


class UpsellReorder(BaseModel):
    """POST /upsells/reorder body: the upsell ids in the new display order. Each
    id's ``sort_order`` is set to its index in the list."""

    ids: list[str]


class UpsellResponse(BaseModel):
    """One upsell in the frontend ``Upsell`` shape - and ONLY those 11 keys. ``id``
    is the row uuid; ``fiverrUrl`` is the outbound gig link; ``clicks30d`` is the
    portal-tracked click count."""

    id: str
    title: str
    description: str
    fiverr_url: str = Field(serialization_alias="fiverrUrl")
    active: bool
    clicks30d: int
    price: float
    rating: float
    reviews: int
    icon: str
    color: str

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> UpsellResponse:
        return cls(
            id=str(row["id"]),
            title=row.get("title", ""),
            description=row.get("description", ""),
            fiverr_url=row.get("fiverr_url", ""),
            active=bool(row.get("active", False)),
            clicks30d=int(row.get("clicks30d", 0) or 0),
            price=float(row.get("price", 0) or 0),
            rating=float(row.get("rating", 0) or 0),
            reviews=int(row.get("reviews", 0) or 0),
            icon=row.get("icon", ""),
            color=row.get("color", ""),
        )


def to_response(row: dict[str, Any]) -> UpsellResponse:
    """Map an ``upsells`` row to the frontend ``Upsell`` shape."""
    return UpsellResponse.from_row(row)
