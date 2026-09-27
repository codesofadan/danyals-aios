"""Turn a pasted Google Maps link into a grid centre and a verified business identity.

THE PROBLEM THIS REPLACES. ``provider.resolve_center`` finds the client's listing by
TEXT SEARCH - business name plus address, top hit wins - and its own comments record
what that costs in practice: "Alligator Pools" plus a Karachi address resolved to Miami,
Florida; a client called "Brand Kit Test" returned Walgreens in Delaware and then Meijer
in Michigan. A shared-word guard now rejects the worst of those, but the failure mode is
structural. Places is being asked to GUESS which business we meant, and a wrong guess
centres a grid on a stranger's shop and then measures it honestly forever.

A pasted Maps URL ends the guessing. The operator has already found the business on
Google with their own eyes; the link they copied names that exact listing. So this path
searches for nothing - it reads an identifier and looks it up.

THE ORDER OF PREFERENCE, AND WHY EACH STEP EXISTS

1. ``place_id`` -> Places **Details**. One listing, by key. Nothing to disambiguate,
   and the coordinates come back from Google's own record of the place rather than from
   the URL text.
2. ``cid`` / pin coordinates with a name -> Places **searchText, biased to the pin**.
   The Places API has no by-CID endpoint, so a ``?cid=`` link cannot be looked up
   directly. Biasing a text search to a 50-metre circle around the pin is a different
   proposition from today's blind national search: the answer is constrained to the
   spot the operator pointed at.
3. Coordinates alone -> the centre, with **no identity claimed**. A dropped pin is a
   real, usable centre. It is not a business, and this reports it as exactly that
   rather than attaching the nearest listing to it.

DEGRADE, NEVER FABRICATE. Every provider failure returns the best VERIFIED subset with
``identity_verified=False`` and a machine-branchable ``reason``. A pin coordinate with
no NAP is still strictly better than what the operator has today; a NAP invented to
fill the gap would be worse than nothing, because the caller writes it to the client's
canonical record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.logging_setup import get_logger
from app.services.maps_url import parse_maps_url

logger = get_logger("grid_tracker.maps_center")

_PLACES_BASE = "https://places.googleapis.com"

#: Details field mask. ``location`` is the one the grid cannot work without;
#: ``addressComponents`` is what lets the NAP write-back fill city/region as separate
#: columns instead of shoving a formatted one-liner into every field.
_DETAILS_MASK = (
    "id,displayName,formattedAddress,addressComponents,"
    "nationalPhoneNumber,internationalPhoneNumber,websiteUri,location,googleMapsUri"
)
_SEARCH_MASK = "places." + ",places.".join(_DETAILS_MASK.split(","))

#: How tightly a CID/pin text search is biased. 50m is a building, not a block: the
#: operator pointed at a specific pin, so anything outside this is not what they
#: pointed at and a miss is more honest than a neighbour.
_BIAS_RADIUS_M = 50.0

#: How far the returned listing may sit from the pasted pin before the match is
#: REJECTED.
#:
#: MEASURED, not guessed, on the first live call this code ever made. `locationBias` is
#: a BIAS and nothing more: handed a 50m circle around a Karachi pin, Places answered
#: with a business 11 KILOMETRES away, and the resolver reported it `verified=True`.
#: That is the exact defect the whole feature exists to remove - a confident answer
#: about the wrong business - arriving through the code meant to prevent it.
#:
#: So the constraint is enforced HERE rather than asked of the vendor. A bias that the
#: provider is free to ignore cannot be a guarantee; a distance check on the answer can.
#: 150m is generous against the real source of drift (Google's rooftop coordinate vs the
#: URL's pin for the SAME listing, tens of metres) while excluding anything that is
#: plainly a different premises.
_MATCH_TOLERANCE_M = 150.0


@dataclass(frozen=True)
class MapsCenter:
    """A centre resolved from a Maps URL, plus whatever identity was VERIFIED.

    ``identity_verified`` is the field the caller must branch on before writing
    anything to the client's NAP: False means the coordinates are usable and the
    business details are not, and the two must not travel as one fact.
    """

    lat: float
    lng: float
    #: ``"places_details"`` | ``"places_biased"`` | ``"maps_pin"`` | ``"maps_viewport"``
    source: str
    place_id: str = ""
    cid: str = ""
    name: str = ""
    address: str = ""
    city: str = ""
    region: str = ""
    postal_code: str = ""
    phone: str = ""
    website: str = ""
    listing_url: str = ""
    identity_verified: bool = False
    #: Set when the identity could not be established; empty on a clean resolve.
    reason: str = ""

    @property
    def is_precise(self) -> bool:
        """Whether the coordinate came from Google's record or the listing's own pin -
        i.e. everything except the panned-camera fallback."""
        return self.source != "maps_viewport"


class MapsUrlError(ValueError):
    """The pasted string cannot yield a centre. Carries a stable ``code``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _metres_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres (haversine).

    Plain trigonometry rather than a geo dependency: this is one comparison against a
    150m threshold, where every projection agrees, and the module stays importable with
    nothing installed.
    """
    import math

    radius_m = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lng2 - lng1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * radius_m * math.asin(min(1.0, math.sqrt(a)))


def _places_key(settings: Settings) -> str:
    key = settings.google_places_api_key or settings.google_maps_api_key
    return key.get_secret_value() if key else ""


def _component(components: Any, *wanted: str) -> str:
    """Pull one address component by type from the Places ``addressComponents`` list.

    Returns the SHORT text for region/country style fields via the caller's choice of
    key ordering; an absent component is "", never a guess from the formatted string.
    """
    if not isinstance(components, list):
        return ""
    for comp in components:
        if not isinstance(comp, dict):
            continue
        types = comp.get("types")
        if isinstance(types, list) and any(t in wanted for t in types):
            return str(comp.get("longText") or comp.get("shortText") or "")
    return ""


def _center_from_place(place: dict[str, Any], *, source: str, cid: str = "") -> MapsCenter | None:
    """Build a :class:`MapsCenter` from one Places resource, or ``None`` if it has no
    coordinate - which is an unresolved place, never a centre of (0, 0)."""
    location = place.get("location")
    if not isinstance(location, dict):
        return None
    lat, lng = location.get("latitude"), location.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        return None
    if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lng) <= 180.0):
        return None

    display = place.get("displayName")
    name = str(display.get("text")) if isinstance(display, dict) else str(display or "")
    components = place.get("addressComponents")
    return MapsCenter(
        lat=float(lat),
        lng=float(lng),
        source=source,
        place_id=str(place.get("id") or ""),
        cid=cid,
        name=name,
        address=str(place.get("formattedAddress") or ""),
        city=_component(components, "locality", "postal_town"),
        region=_component(components, "administrative_area_level_1"),
        postal_code=_component(components, "postal_code"),
        phone=str(place.get("nationalPhoneNumber") or place.get("internationalPhoneNumber") or ""),
        website=str(place.get("websiteUri") or ""),
        listing_url=str(place.get("googleMapsUri") or ""),
        identity_verified=bool(name),
    )


def _fetch_details(api_key: str, place_id: str, *, timeout: float = 20.0) -> dict[str, Any] | None:
    """GET one place by id. ``None`` on any provider failure - never raises upward,
    because a failed lookup degrades to the URL's own pin rather than failing the paste."""
    from integrations.http_client import HttpProviderClient

    client = HttpProviderClient(
        base_url=_PLACES_BASE,
        headers={"X-Goog-Api-Key": api_key, "X-Goog-FieldMask": _DETAILS_MASK},
        timeout=timeout,
    )
    try:
        data = client.request_json("GET", f"/v1/places/{place_id}")
    except Exception:
        logger.info("maps_center_details_failed")
        return None
    return data if isinstance(data, dict) else None


def _search_biased(
    api_key: str, query: str, lat: float, lng: float, *, timeout: float = 20.0
) -> dict[str, Any] | None:
    """Text search pinned to a 50m circle around the operator's pin."""
    from integrations.http_client import HttpProviderClient

    client = HttpProviderClient(
        base_url=_PLACES_BASE,
        headers={
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": _SEARCH_MASK,
            "Content-Type": "application/json",
        },
        timeout=timeout,
    )
    body = {
        "textQuery": query,
        "maxResultCount": 1,
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": _BIAS_RADIUS_M,
            }
        },
    }
    try:
        data = client.request_json("POST", "/v1/places:searchText", json_body=body)
    except Exception:
        logger.info("maps_center_biased_search_failed")
        return None
    places = [p for p in (data.get("places") or []) if isinstance(p, dict)] if isinstance(data, dict) else []
    return places[0] if places else None


def _follow_short_link(url: str, *, max_redirects: int = 5) -> str:
    """Resolve a ``maps.app.goo.gl`` link to the URL it points at. ``""`` on failure.

    REDIRECTS ARE FOLLOWED MANUALLY AND EVERY HOP IS RE-VALIDATED, the contract
    ``web2_placement.fetch_placement_page`` documents: ``follow_redirects=True`` would
    issue the request to a redirect target BEFORE any check ran, so a public shortener
    pointing at an internal address would be fetched server-side and only refused
    afterwards. Refusing the hop before the request is the only ordering that holds.

    The BODY is never read. All we want is the ``Location`` header, so this issues HEAD
    and treats the final URL as the answer - there is no page here worth parsing, and
    not reading a body removes a whole class of thing that could go wrong.
    """
    import httpx

    from app.core.security import is_public_url

    current = url
    for _hop in range(max_redirects + 1):
        if not is_public_url(current):
            return ""
        try:
            with httpx.Client(
                timeout=15.0,
                follow_redirects=False,
                headers={"User-Agent": "AIOSGridBot/1.0"},
            ) as client:
                resp = client.head(current)
                # Some shorteners answer HEAD with 405; fall back to GET for the header.
                if resp.status_code == 405:
                    resp = client.get(current)
        except Exception:
            return ""
        location = resp.headers.get("location", "")
        if resp.status_code in (301, 302, 303, 307, 308) and location:
            current = str(httpx.URL(current).join(location))
            continue
        return current
    return ""


def resolve_maps_url(settings: Settings, url: str) -> MapsCenter:
    """Resolve a pasted Google Maps link to a centre plus a verified identity.

    Raises :class:`MapsUrlError` only when the string cannot yield a centre at all -
    not a Maps link, an unresolvable short link, or a link naming no location. Every
    other shortfall comes back on the result as ``identity_verified=False`` + ``reason``.
    """
    parsed = parse_maps_url(url)
    if parsed is None:
        raise MapsUrlError(
            "not_a_maps_url",
            "that does not look like a Google Maps link - open the business on Google "
            "Maps, press Share, and paste the link it gives you",
        )

    if parsed.needs_resolution:
        expanded = _follow_short_link(parsed.url)
        reparsed = parse_maps_url(expanded) if expanded else None
        if reparsed is None or reparsed.needs_resolution:
            raise MapsUrlError(
                "short_link_unresolved",
                "that short link could not be expanded - open it in a browser and paste "
                "the full google.com/maps/place/... URL instead",
            )
        parsed = reparsed

    api_key = _places_key(settings)

    # 1. A place_id is exact. Look it up and prefer Google's own coordinate.
    if parsed.place_id and api_key:
        data = _fetch_details(api_key, parsed.place_id)
        if data is not None:
            center = _center_from_place(data, source="places_details", cid=parsed.cid)
            if center is not None:
                return center

    # 2. A CID or a named pin: search biased to the pin, then CHECK THE ANSWER LANDED
    #    THERE. The bias is a hint to the provider; the distance test is the guarantee.
    if parsed.has_coords and api_key and (parsed.cid or parsed.name_hint):
        assert parsed.lat is not None and parsed.lng is not None  # has_coords
        query = parsed.name_hint or "business"
        hit = _search_biased(api_key, query, parsed.lat, parsed.lng)
        if hit is not None:
            center = _center_from_place(hit, source="places_biased", cid=parsed.cid)
            if center is not None:
                drift_m = _metres_between(parsed.lat, parsed.lng, center.lat, center.lng)
                if drift_m <= _MATCH_TOLERANCE_M:
                    return center
                # A different premises. Keep the operator's pin, drop the identity, and
                # say so - reporting this business would be the wrong-business failure
                # this whole path exists to prevent.
                logger.info(
                    "maps_center_match_rejected",
                    drift_m=round(drift_m),
                    tolerance_m=_MATCH_TOLERANCE_M,
                )
                return MapsCenter(
                    lat=parsed.lat,
                    lng=parsed.lng,
                    source="maps_pin" if parsed.is_precise else "maps_viewport",
                    place_id=parsed.place_id,
                    cid=parsed.cid,
                    identity_verified=False,
                    reason="match_too_far",
                )

    # 3. Coordinates with no verified identity. Usable, and honest about what it is not.
    if parsed.has_coords:
        assert parsed.lat is not None and parsed.lng is not None
        reason = "no_places_key" if not api_key else "identity_lookup_failed"
        return MapsCenter(
            lat=parsed.lat,
            lng=parsed.lng,
            source="maps_pin" if parsed.is_precise else "maps_viewport",
            place_id=parsed.place_id,
            cid=parsed.cid,
            # The URL slug is a DISPLAY hint only and never a verified name, so it does
            # not populate `name` - which the caller may write to the client's NAP.
            identity_verified=False,
            reason=reason,
        )

    raise MapsUrlError(
        "no_location_in_url",
        "that Maps link does not carry a location - open the business itself on Google "
        "Maps (not a search results page) and share that link",
    )
