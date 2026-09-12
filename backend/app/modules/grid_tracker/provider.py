"""Geo-grid map-pack seam: ONE keyword, ONE business, MANY coordinates.

HOW THIS DIFFERS FROM ``app.modules.local_seo.provider``, AND WHY IT IS SEPARATE.
The local-SEO seam answers "where do we sit in the pack in this market" by naming a
market (``location_name``: a city string). This seam answers a different question -
"where does our visibility fall off, and in which direction" - which cannot be asked
with a place NAME at all. It needs the provider to run the search *from a specific
point on the earth*, so the request carries a COORDINATE.

THAT DISTINCTION IS THE WHOLE MODULE, AND GETTING IT WRONG IS SILENT.
The audit engine carries an earlier, never-wired attempt at this
(``danyals-audit-system/audit_engine/integrations/geo_grid.py``) which encodes each
point as ``location="lat,lng"`` against Serper's ``/search``. Serper's ``location``
expects a canonical location NAME - a Google Ads geo target such as "Karachi,
Pakistan". Handed "24.86,67.01" it does not error: it falls back to an unlocalised
or default-localised SERP. Every point in the grid then receives the SAME answer, and
the result is a perfectly smooth heat map that is entirely fictional. That file's own
comment admits it does not know whether the parameter works. It is retired, not
reused, and this docstring is the reason.

So the liveness rule here is NARROWER than the local-SEO module's on purpose:

    a Serper key is NOT sufficient for grid tracking.

DataForSEO's Maps endpoint takes a real ``location_coordinate`` ("lat,lng,zoom") and
is the only provider this deploy holds credentials for that can express a grid point
truthfully. With no DataForSEO credential the worker REFUSES (``JobBlocked``) rather
than degrading to something that would write 25 fabricated positions per run into an
append-only evidence table - see ``grid_provider_is_live``.

THE PROBE RESULT IS THREE-STATE, matching ``0138``'s ``grid_points.status``:

    ranked  - measured, found in the pack. ``rank`` is a real position.
    absent  - measured, NOT in the pack. An honest observation, rank is None.
    error   - NOT MEASURED. ``error`` says why; the caller records the point as
              unmeasured and must never let it read as an absence.

``LocalRankResult`` cannot express that third state (it folds "not found" and
"failed" into one nullable rank plus an error field, which is exactly why 0039's
worker writes nothing on error). A grid must keep its holes, so this seam returns its
own type.
"""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from app.config import Settings
from app.logging_setup import get_logger

# Deliberate reuse, not duplication: a grid probes the SAME Google local pack with the
# SAME "is this listing us" question as the single-locale check, so the matching rules
# and the DataForSEO envelope walk are imported rather than re-implemented. Two copies
# of "does this pack entry belong to our client" is how the two surfaces would come to
# disagree about whether a business is ranking.
from app.modules.local_seo.provider import (
    MAP_PACK_SIZE,
    _dfs_items,
    _match_index,
    _names,
)
from integrations.errors import ProviderNotConfiguredError
from integrations.http_client import HttpProviderClient

logger = get_logger("app.modules.grid_tracker.provider")

_DFS_BASE = "https://api.dataforseo.com"
_DFS_INSTALL_HINT = (
    "set DATAFORSEO_LOGIN + DATAFORSEO_PASSWORD to enable geo-grid tracking; it is "
    "the only configured provider that accepts a per-point coordinate"
)

#: Mean kilometres per degree of latitude (WGS84). Latitude spacing is very nearly
#: constant; longitude is not, which is what ``_km_per_deg_lng`` handles.
KM_PER_DEG_LAT = 111.32

#: The eight compass bearings of one ring, in degrees clockwise from north.
_BEARINGS: tuple[tuple[str, float], ...] = (
    ("N", 0.0), ("NE", 45.0), ("E", 90.0), ("SE", 135.0),
    ("S", 180.0), ("SW", 225.0), ("W", 270.0), ("NW", 315.0),
)

#: Below this |latitude| cosine, longitude spacing explodes (the meridians converge at
#: the poles). Clamping keeps a polar grid finite instead of producing infinities; no
#: local business sits here, so the clamp is a safety rail, not a modelling choice.
_MIN_COS_LAT = 0.01


@dataclass(frozen=True)
class GridPoint:
    """One probe location, derived from the definition's geometry."""

    lat: float
    lng: float
    #: 'center', or '<direction>-<ring>' e.g. 'NE-2'. Unique within a grid, which is
    #: what ``0138``'s ``unique (run_id, label)`` relies on.
    label: str
    ring: int


@dataclass(frozen=True)
class GridProbeResult:
    """What one probe at one point saw. See the module docstring's three states."""

    status: str  # 'ranked' | 'absent' | 'error'
    rank: int | None = None
    found_url: str = ""
    top_competitors: list[str] = field(default_factory=list)
    error: str = ""
    provider: str = ""

    @property
    def measured(self) -> bool:
        """Whether the provider actually answered. Every derived percentage divides by
        the count of measured points, never by the total."""
        return self.status in {"ranked", "absent"}

    @property
    def in_map_pack(self) -> bool:
        return self.status == "ranked" and self.rank is not None and self.rank <= MAP_PACK_SIZE


def _km_per_deg_lng(lat: float) -> float:
    """Kilometres per degree of longitude AT THIS LATITUDE.

    A degree of longitude is ~111 km at the equator and shrinks with cos(latitude) -
    at Karachi (24.9N) it is ~101 km, at Edinburgh (55.9N) ~62 km. Using the latitude
    constant for both axes (the obvious shortcut) would stretch every grid
    east-west by that factor: a "1 km" ring would be 1 km north but 1.8 km east in
    Edinburgh, and the heat map would describe a service area the business does not
    have.
    """
    cos_lat = math.cos(math.radians(lat))
    return KM_PER_DEG_LAT * max(abs(cos_lat), _MIN_COS_LAT)


def make_ring_grid(
    *, center_lat: float, center_lng: float, rings: int, spacing_km: float
) -> list[GridPoint]:
    """The centre plus ``rings`` concentric 8-point rings at ``spacing_km`` intervals.

    Point count is ``1 + 8 * rings``, which is exactly what ``0138``'s generated
    ``point_count`` column computes - the two are the same formula so an estimate can
    never disagree with what is probed.

    Coordinates are rounded to 6 decimal places (~0.1 m), which is far finer than any
    map-pack boundary and keeps the label/coordinate pair stable across runs so two
    runs of the same grid are comparable point-for-point.
    """
    points: list[GridPoint] = [
        GridPoint(lat=round(center_lat, 6), lng=round(center_lng, 6), label="center", ring=0)
    ]
    km_lng = _km_per_deg_lng(center_lat)
    for ring in range(1, rings + 1):
        distance = spacing_km * ring
        for name, bearing_deg in _BEARINGS:
            bearing = math.radians(bearing_deg)
            dlat = (distance / KM_PER_DEG_LAT) * math.cos(bearing)
            dlng = (distance / km_lng) * math.sin(bearing)
            points.append(
                GridPoint(
                    # Clamped / wrapped so a grid near a pole or the antimeridian
                    # yields coordinates a provider will accept rather than 91.4 or
                    # -181.2, which DataForSEO rejects for the whole task.
                    lat=round(max(-90.0, min(90.0, center_lat + dlat)), 6),
                    lng=round(_wrap_lng(center_lng + dlng), 6),
                    label=f"{name}-{ring}",
                    ring=ring,
                )
            )
    return points


def _wrap_lng(lng: float) -> float:
    """Wrap longitude into [-180, 180]. A grid centred at 179.8E crosses the
    antimeridian; wrapping keeps its eastern points valid instead of 180.4."""
    return ((lng + 180.0) % 360.0) - 180.0



def make_square_grid(
    *, center_lat: float, center_lng: float, size: int, spacing_km: float
) -> list[GridPoint]:
    """An ``size`` x ``size`` lattice centred on the business - the market's shape.

    WHY A SQUARE RATHER THAN RINGS. Every tool an operator has already used presents an
    N x N block of pins over a map, so a rosette has to be mentally translated before it
    can be compared with a report they know how to read. A square also samples EVENLY:
    eight points per ring means the outer ring covers a far longer circumference at the
    same point count, so the edge of a large service area - which is exactly where
    visibility falls off and where the operator is looking - was measured most thinly.

    Labels are spreadsheet-style (``A1`` … ``E5``), row-major from the north-west, so a
    point's name says where it is on the map without a legend. The centre cell of an odd
    grid sits exactly on the business, which is why ``0143`` constrains ``size`` to odd.

    Spacing is the distance between ADJACENT cells, so a 5x5 at 1.5 km spans 6 km
    edge-to-edge. Longitude is converted at the centre's latitude for the same reason
    ``make_ring_grid`` does it - using the latitude constant for both axes stretches the
    lattice east-west by 1/cos(lat) and describes an area the business does not have.
    """
    points: list[GridPoint] = []
    half = size // 2
    km_lng = _km_per_deg_lng(center_lat)
    for row in range(size):
        for col in range(size):
            # Row 0 is the NORTHERNMOST, so reading order matches the map.
            north_offset = (half - row) * spacing_km
            east_offset = (col - half) * spacing_km
            lat = center_lat + north_offset / KM_PER_DEG_LAT
            lng = center_lng + east_offset / km_lng
            points.append(
                GridPoint(
                    lat=round(max(-90.0, min(90.0, lat)), 6),
                    lng=round(_wrap_lng(lng), 6),
                    label=f"{chr(ord('A') + row)}{col + 1}",
                    # `ring` becomes the Chebyshev distance from the centre - how many
                    # cells out this point sits. It keeps the column meaningful for a
                    # square (0 at the centre, 1 for the inner ring of cells, …) so
                    # ordering and any ring-based read still work.
                    ring=max(abs(half - row), abs(col - half)),
                )
            )
    return points


def build_grid(
    *, center_lat: float, center_lng: float, shape: str, size: int, rings: int,
    spacing_km: float,
) -> list[GridPoint]:
    """The probe points for a definition, by its stored shape.

    One door, so the worker never has to know which geometry a row uses - and a
    pre-0143 row keeps being probed as the rings it was actually measured with.
    """
    if shape == "rings":
        return make_ring_grid(
            center_lat=center_lat, center_lng=center_lng, rings=rings,
            spacing_km=spacing_km,
        )
    return make_square_grid(
        center_lat=center_lat, center_lng=center_lng, size=size, spacing_km=spacing_km,
    )



@runtime_checkable
class GridProvider(Protocol):
    """Probe ONE keyword for ONE business AT ONE COORDINATE.

    Impls MUST return an ``error``-status result rather than raising for a
    provider-side failure: one bad point must cost one point, never the run.
    """

    provider: str
    enabled: bool

    def probe(
        self, *, keyword: str, lat: float, lng: float, place_id: str | None, business_name: str
    ) -> GridProbeResult: ...

    def estimated_cost(self) -> float: ...



def _loose_match_index(entries: list[dict[str, Any]], business_name: str) -> int | None:
    """A CONTAINMENT fallback for a listing whose name is not byte-identical to ours.

    WHY THIS EXISTS, measured. The shared ``_match_index`` requires an exact normalised
    name match after the place-id check. A client's stored name is often its legal
    entity - "PoolServ LLC d/b/a Alligator Pools" - while the map pack shows the trading
    name, "Alligator Pools". Exact equality fails, and 51 probes recorded `absent` for a
    business ranking at every single point.

    So: if either name CONTAINS the other after normalisation, it is the same business.
    Containment, not token overlap - "Miami Pools" and "Naples Pools" share a word and
    are different companies, while "Alligator Pools" is wholly inside "PoolServ LLC
    d/b/a Alligator Pools" and is not.

    Deliberately LOCAL to the grid rather than pushed into the shared matcher: widening
    that would change what ``local_seo`` records as a ranking, and its single-locale
    history was built under the strict rule. A grid is a new series with no history to
    invalidate.

    A short name is refused outright - a three-letter business name is contained in half
    the pack by accident.
    """
    ours = " ".join(business_name.lower().split())
    if len(ours) < 6:
        return None
    for index, entry in enumerate(entries):
        title = " ".join(str(entry.get("title") or entry.get("name") or "").lower().split())
        if not title or len(title) < 6:
            continue
        if ours in title or title in ours:
            return index
    return None


class DataForSeoGridProvider(HttpProviderClient):
    """The ONLY live grid provider: DataForSEO Maps, addressed by coordinate.

    ``location_coordinate`` is "latitude,longitude,zoom". The zoom matters: it is the
    map scale the search is run at, and it decides how wide a net the pack is drawn
    from. It is a setting rather than a constant because the right value differs
    between a dense city grid and a rural service area.

    Credentials go to httpx per request as HTTP Basic (the house DataForSEO pattern),
    so they never sit in a persistent header dict and never reach a log line.
    """

    provider = "dataforseo_maps_grid"
    enabled = True

    def __init__(
        self,
        *,
        login: str,
        password: str,
        zoom: int = 14,
        timeout: float = 30.0,
        cost: float = 0.003,
    ) -> None:
        if not login or not password:
            raise ProviderNotConfiguredError(f"DataForSEO grid unavailable: {_DFS_INSTALL_HINT}")
        self._cost = cost
        self._zoom = zoom
        super().__init__(
            base_url=_DFS_BASE,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        self._auth = (login, password)

    def estimated_cost(self) -> float:
        return self._cost

    def probe(
        self, *, keyword: str, lat: float, lng: float, place_id: str | None, business_name: str
    ) -> GridProbeResult:
        task: dict[str, Any] = {
            "keyword": keyword,
            "language_code": "en",
            # THE LINE THE MODULE EXISTS FOR. A name here instead of a coordinate is
            # the defect described at the top of this file.
            "location_coordinate": f"{lat},{lng},{self._zoom}",
        }
        try:
            data = self.request_json(
                "POST", "/v3/serp/google/maps/live/advanced", json_body=[task], auth=self._auth
            )
        except Exception as exc:
            # One point, one failure. The run continues and records this point as
            # unmeasured - never as "not in the pack".
            logger.warning(
                "grid_probe_failed", provider=self.provider, error=type(exc).__name__
            )
            return GridProbeResult(
                status="error", error=type(exc).__name__, provider=self.provider
            )

        status_code = _task_status_code(data)
        if status_code is not None and status_code >= 40000:
            # DataForSEO reports task-level failures INSIDE a 200 response. Treating
            # that envelope as an empty pack would record a clean "absent" for a task
            # that never ran - the fabrication this module is built to refuse.
            return GridProbeResult(
                status="error",
                error=f"provider_task_{status_code}",
                provider=self.provider,
            )

        entries = _dfs_items(data)
        index = _match_index(entries, place_id=place_id, business_name=business_name)
        if index is None:
            index = _loose_match_index(entries, business_name)
        if index is None:
            return GridProbeResult(
                status="absent", top_competitors=_names(entries), provider=self.provider
            )
        entry = entries[index]
        return GridProbeResult(
            status="ranked",
            rank=index + 1,
            found_url=str(entry.get("website") or entry.get("url") or ""),
            top_competitors=_names(entries),
            provider=self.provider,
        )


def _task_status_code(data: dict[str, Any]) -> int | None:
    """The first task's ``status_code`` from a DataForSEO envelope, if present.

    DataForSEO answers 200 OK for a task that failed and puts the real outcome in
    ``tasks[0].status_code`` (20000 = ok; 40000+ = an error). Every hop is guarded
    because a thin envelope may omit any level.
    """
    tasks = data.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return None
    first = tasks[0]
    if not isinstance(first, dict):
        return None
    code = first.get("status_code")
    return int(code) if isinstance(code, int) else None


class FakeGridProvider:
    """Deterministic, offline ``GridProvider`` - sha256(keyword|lat|lng|business).

    TEST-ONLY. ``grid_provider_from_settings`` never returns this, and the worker
    refuses to run at all without a live provider (``grid_provider_is_live``), so a
    fabricated position cannot reach ``grid_points``. It exists so the geometry, the
    summary maths and the worker's state machine are unit-testable with no network and
    no credential.

    Ranking decays with distance from the centre of the test grid, which makes the
    fixture exercise a realistic heat map rather than a uniform one, and roughly one
    point in six comes back ``absent`` so the three-state contract is covered.
    """

    provider = "fake"
    enabled = True

    def estimated_cost(self) -> float:
        return 0.0

    def probe(
        self, *, keyword: str, lat: float, lng: float, place_id: str | None, business_name: str
    ) -> GridProbeResult:
        seed = f"{keyword}|{lat:.4f}|{lng:.4f}|{business_name}".encode()
        bucket = int(hashlib.sha256(seed).hexdigest()[:8], 16) % 12
        if bucket >= 10:
            return GridProbeResult(status="absent", provider=self.provider)
        return GridProbeResult(
            status="ranked",
            rank=bucket + 1,
            top_competitors=["A Competitor", "B Competitor"],
            provider=self.provider,
        )


@dataclass(frozen=True)
class ResolvedCenter:
    """A grid centre resolved from the client's own Google listing."""

    lat: float
    lng: float
    place_id: str = ""
    #: The matched listing's OWN name and address. Carried because a coordinate alone
    #: cannot be judged: Places matches on business name and will happily return a
    #: same-named business on another continent while ignoring the address it was given.
    #: Measured: "Alligator Pools" + a Karachi address resolved to Miami, Florida.
    matched_name: str = ""
    matched_address: str = ""



#: Corporate-suffix noise only. An earlier version also listed "brand", "kit" and
#: "test" - words taken from the ONE client that exposed this bug, which emptied that
#: client's token set entirely and sent it down the unjudgeable branch. Stopwords must
#: describe language, not the sample that happened to fail.
_MATCH_STOPWORDS = frozenset({
    "the", "and", "for", "inc", "llc", "ltd", "limited", "corp", "corporation",
    "co", "company", "group", "holdings", "pvt", "plc", "gmbh",
})


def _plausible_match(searched: str, matched: str) -> bool:
    """Whether ``matched`` could be the business named by ``searched``.

    One shared MEANINGFUL word is enough. That is a low bar deliberately: real listings
    differ from client records in ways a stricter test rejects ("Acme Dental" vs "Acme
    Dental Clinic (Main St)", a trading name, a franchise suffix). What it reliably
    catches is a match with NOTHING in common - which is the failure that actually
    happens. Measured: a client called "Brand Kit Test" resolved to Walgreens in
    Delaware, then to Meijer in Michigan.

    UNJUDGEABLE MEANS REFUSE, not accept. If a name was given but yields no comparable
    token, this returns False: the result decides where a paid, append-only measurement
    is taken, so "I cannot tell" must fall the safe way. Only a genuinely EMPTY searched
    name passes - there the caller made no claim to check, and other clues carry it.
    """
    def tokens(value: str) -> set[str]:
        raw = re.split(r"[^a-z0-9]+", value.lower())
        return {t for t in raw if len(t) > 2 and t not in _MATCH_STOPWORDS}

    if not searched.strip():
        return True
    want = tokens(searched)
    if not want:
        return False
    return bool(want & tokens(matched))


def resolve_center(
    settings: Settings, *, business_name: str, address: str, timeout: float = 20.0
) -> ResolvedCenter | None:
    """Find the client's listing on the map and return ITS coordinates, or ``None``.

    WHY THIS IS HERE RATHER THAN IN ``integrations.citation_discovery``. That module's
    Places anchor already resolves a business to a canonical NAP, but its
    ``CanonicalNAP`` carries no coordinates and is consumed by the citations module's
    contract tests. Widening a shared type for one new consumer is how two modules come
    to disagree about what a "canonical" business record is - so this reads the same
    endpoint for the one extra fact the grid needs, and changes nothing that works.

    ``None`` means "could not resolve", and the caller must then REQUIRE explicit
    coordinates from the operator. It must never fall back to geocoding the postal
    address on its own: a mis-geocoded centre silently relocates the entire grid, and
    every number on the resulting heat map still looks completely normal.
    """
    api_key = settings.serper_api_key
    key = api_key.get_secret_value() if api_key else ""
    if not key:
        logger.info("grid_center_unresolved", reason="no_serper_key")
        return None

    query = " ".join(part for part in (business_name.strip(), address.strip()) if part)
    if not query:
        return None

    client = HttpProviderClient(
        base_url="https://google.serper.dev",
        headers={"X-API-KEY": key, "Content-Type": "application/json"},
        timeout=timeout,
    )
    try:
        data = client.request_json("POST", "/places", json_body={"q": query})
    except Exception:
        logger.info("grid_center_unresolved", reason="places_lookup_failed")
        return None

    places = [p for p in (data.get("places") or []) if isinstance(p, dict)]
    if not places:
        return None
    top = places[0]
    lat, lng = top.get("latitude"), top.get("longitude")
    if not isinstance(lat, (int, float)) or not isinstance(lng, (int, float)):
        # The endpoint answered but without coordinates. That is an unresolved centre,
        # not a centre of (0, 0) - which is in the Atlantic.
        logger.info("grid_center_unresolved", reason="no_coordinates_in_response")
        return None
    if not (-90.0 <= float(lat) <= 90.0 and -180.0 <= float(lng) <= 180.0):
        logger.info("grid_center_unresolved", reason="coordinates_out_of_range")
        return None

    # THE MATCH MUST PLAUSIBLY BE THE BUSINESS WE ASKED ABOUT.
    #
    # Places always answers. Asked about a client called "Brand Kit Test" it returned
    # Walgreens in Delaware, and then Meijer in Michigan - measured, on the first real
    # use of this path. Accepting those would have centred two grids on unrelated US
    # retailers and then honestly measured them, forever.
    #
    # A shared word is a low bar deliberately: real listings differ from client records
    # in ways a stricter test rejects ("Acme Dental" vs "Acme Dental Clinic", a trading
    # name, a franchise suffix). What it reliably catches is a match with NOTHING in
    # common, which is the failure that actually happens.
    matched_title = str(top.get("title") or "")
    if not _plausible_match(business_name, matched_title):
        logger.info(
            "grid_center_unresolved", reason="matched_a_different_business",
            matched=matched_title[:60],
        )
        return None
    return ResolvedCenter(
        lat=round(float(lat), 6),
        lng=round(float(lng), 6),
        place_id=str(top.get("placeId") or ""),
        matched_name=str(top.get("title") or "")[:200],
        matched_address=str(top.get("address") or "")[:300],
    )


def grid_provider_is_live(settings: Settings) -> bool:
    """Whether a provider that accepts a COORDINATE is configured.

    Deliberately stricter than ``local_pack_provider_is_live``: that one accepts a
    Serper key, because a single-locale check can be asked with a place name. A grid
    cannot. Returning True on a Serper-only deploy would let the worker run and write
    a full grid of positions that were all measured at the same unlocalised SERP.
    """
    password = settings.dataforseo_password
    return bool(settings.dataforseo_login and password and password.get_secret_value())


def grid_provider_from_settings(settings: Settings) -> GridProvider | None:
    """The live grid provider, or ``None`` when no coordinate-capable vendor is keyed.

    Returns ``None`` rather than a fake ON PURPOSE. Every other provider factory in
    this codebase degrades to a deterministic fake so its module stays usable offline;
    this one must not, because its output lands in an append-only evidence table that
    a client sees as measured performance. The caller's job is to refuse, not to
    substitute - the rule ``tests/test_no_synthetic_providers_in_production.py``
    exists to enforce.
    """
    if not grid_provider_is_live(settings):
        logger.info("grid_provider_absent", reason="no_dataforseo_credential")
        return None
    password = settings.dataforseo_password
    return DataForSeoGridProvider(
        login=str(settings.dataforseo_login),
        password=password.get_secret_value() if password else "",
        zoom=int(settings.grid_probe_zoom),
        cost=float(settings.grid_point_cost_estimate),
    )
