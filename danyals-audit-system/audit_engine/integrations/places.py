"""Google Places API (New) client.

Free tier for the audit use case:
- Text Search (Find Place): identify a business by name + address
- Place Details: pull profile fields (rating, user_ratings_total, opening_hours,
  formatted_address, formatted_phone_number, website, types, photos count)

Endpoint base: https://places.googleapis.com/v1
Auth: X-Goog-Api-Key header.

Graceful degrade if no GOOGLE_API_KEY.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from audit_engine.integrations.base import BaseClient
from audit_engine.logging_setup import get_logger

log = get_logger(__name__)

PLACES_BASE = "https://places.googleapis.com/v1"

# Field mask we request. Stays inside the included tier where possible.
PLACE_FIELDS = ",".join(
    [
        "id",
        "displayName",
        "formattedAddress",
        "addressComponents",
        "internationalPhoneNumber",
        "nationalPhoneNumber",
        "websiteUri",
        "primaryType",
        "primaryTypeDisplayName",
        "types",
        "businessStatus",
        "rating",
        "userRatingCount",
        "regularOpeningHours",
        "googleMapsUri",
        "photos.name",
        "reviews",
        "location",
    ]
)


@dataclass
class Place:
    place_id: str
    name: str
    formatted_address: str | None
    phone: str | None
    website: str | None
    primary_type: str | None
    types: list[str] = field(default_factory=list)
    business_status: str | None = None
    rating: float | None = None
    rating_count: int | None = None
    opening_hours: dict[str, Any] | None = None
    photos_count: int = 0
    reviews_sample: list[dict[str, Any]] = field(default_factory=list)
    latitude: float | None = None
    longitude: float | None = None
    error: str | None = None


class PlacesClient(BaseClient):
    provider_name = "google_places"
    base_url = PLACES_BASE

    def __init__(self, *, api_key: str | None = None, timeout: float = 15.0) -> None:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["X-Goog-Api-Key"] = api_key
            headers["X-Goog-FieldMask"] = PLACE_FIELDS
            self._enabled = True
        else:
            self._enabled = False
        super().__init__(timeout=timeout, max_retries=2, headers=headers)

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def find_place(self, query: str) -> Place | None:
        """Text-search the Places API. Returns the top result or None."""
        if not self._enabled:
            return Place(
                place_id="",
                name=query,
                formatted_address=None,
                phone=None,
                website=None,
                primary_type=None,
                error="GOOGLE_API_KEY not set",
            )
        try:
            resp = await self.post(
                "places:searchText",
                json_body={"textQuery": query, "maxResultCount": 1},
                headers={"X-Goog-FieldMask": f"places.{PLACE_FIELDS.replace(',', ',places.')}"},
            )
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.error("places_search_failed", query=query, error=type(e).__name__)
            return Place(
                place_id="",
                name=query,
                formatted_address=None,
                phone=None,
                website=None,
                primary_type=None,
                error=f"{type(e).__name__}: {e}",
            )
        results = data.get("places") or []
        if not results:
            return None
        return _parse_place(results[0])

    async def place_details(self, place_id: str) -> Place:
        if not self._enabled:
            return Place(
                place_id=place_id,
                name="",
                formatted_address=None,
                phone=None,
                website=None,
                primary_type=None,
                error="GOOGLE_API_KEY not set",
            )
        try:
            resp = await self.get(f"places/{place_id}")
            data = resp.json()
        except Exception as e:  # noqa: BLE001
            log.error("places_details_failed", place_id=place_id, error=type(e).__name__)
            return Place(
                place_id=place_id,
                name="",
                formatted_address=None,
                phone=None,
                website=None,
                primary_type=None,
                error=f"{type(e).__name__}: {e}",
            )
        return _parse_place(data)


def _parse_place(data: dict[str, Any]) -> Place:
    display = data.get("displayName") or {}
    name = display.get("text", "") if isinstance(display, dict) else str(display)
    loc = data.get("location") or {}
    return Place(
        place_id=data.get("id", ""),
        name=name,
        formatted_address=data.get("formattedAddress"),
        phone=data.get("nationalPhoneNumber") or data.get("internationalPhoneNumber"),
        website=data.get("websiteUri"),
        primary_type=data.get("primaryType"),
        types=data.get("types") or [],
        business_status=data.get("businessStatus"),
        rating=data.get("rating"),
        rating_count=data.get("userRatingCount"),
        opening_hours=data.get("regularOpeningHours"),
        photos_count=len(data.get("photos") or []),
        reviews_sample=list(data.get("reviews") or [])[:5],
        latitude=loc.get("latitude") if isinstance(loc, dict) else None,
        longitude=loc.get("longitude") if isinstance(loc, dict) else None,
    )
