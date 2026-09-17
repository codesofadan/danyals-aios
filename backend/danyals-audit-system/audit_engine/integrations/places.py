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
    # Whether this Place was matched to the AUDITED business rather than merely
    # being the top text-search hit. True only when the Place's website domain
    # matches the audited domain. False means every GBP-derived finding must be
    # LOW-confidence: the profile being scored may belong to someone else.
    identity_verified: bool = False


def _bare_host(url: str) -> str:
    """Lowercased bare host of a URL or bare domain (``www.`` stripped)."""
    from urllib.parse import urlsplit

    text = (url or "").strip().lower()
    if not text:
        return ""
    if "//" not in text:
        text = f"//{text}"
    try:
        host = urlsplit(text).hostname or ""
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


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

    async def find_place(self, query: str, *, expected_domain: str | None = None) -> Place | None:
        """Text-search the Places API for the AUDITED business.

        Blindly accepting the top text-search hit scored whichever business Google
        thought the query meant - for an ambiguous name that is routinely a
        different company, and every GBP finding downstream then described someone
        else's profile as the client's. So up to five candidates are fetched and
        the FIRST whose website domain matches ``expected_domain`` wins with
        ``identity_verified=True``. With no domain match (or no expected domain),
        the top hit is still returned - a candidate is more useful than nothing -
        but ``identity_verified`` stays False and the caller must treat every
        profile-derived verdict as low-confidence.
        """
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
                json_body={"textQuery": query, "maxResultCount": 5},
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
        want = _bare_host(expected_domain) if expected_domain else ""
        if want:
            for raw in results:
                candidate = _parse_place(raw)
                if candidate.website and _bare_host(candidate.website) == want:
                    candidate.identity_verified = True
                    return candidate
            log.warning(
                "places_identity_unverified",
                query=query,
                expected_domain=want,
                candidates=len(results),
            )
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
