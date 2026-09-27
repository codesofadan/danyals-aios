"""Grid tracking API (0138): standing grids, runs, and the heat map behind them.

ACCESS mirrors ``local_seo``'s router byte-for-byte, and reuses its FEATURE GRANT
rather than minting a new one: the grid is the same product surface to the same
audience ("Google Business Profile, citations & local rankings"), so a staff member
who may see map-pack rank may see where it falls off. The COST DIAL is separate
(``grid_tracker``) because the two have different spend shapes - one probe versus up
to 41 - and an operator must be able to throttle the expensive one alone.

Reads require ``view_reports``; every mutation requires a LEAD role
(owner/admin/manager), mirroring the 0138 RLS insert/update policies exactly, so a
caller who passes the app gate is never rejected by Postgres with an opaque error.

THE RUN ENDPOINT IS A SPEND DOOR, and is gated four ways before it queues anything:
a lead role, a rate limit (bounds hammering), an in-flight check (409 rather than a
second bill for a double-click), and a live-provider check (a refusal that explains
itself instead of a queued job that can only fail). The money itself is bounded
separately and per-probe by the cost gate inside the worker.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_feature, require_perm, require_role
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.core.ratelimit import rate_limit
from app.logging_setup import get_logger
from app.modules.grid_tracker.maps_center import MapsCenter, MapsUrlError, resolve_maps_url
from app.modules.grid_tracker.provider import grid_provider_is_live, resolve_center
from app.modules.grid_tracker.repo import GridRepoDep
from app.modules.grid_tracker.schemas import (
    GridDefinitionCreate,
    GridDefinitionResponse,
    GridDefinitionUpdate,
    GridPointResponse,
    GridRunDetail,
    GridRunResponse,
    MapsUrlPreview,
    MapsUrlRequest,
    RunQueuedResponse,
)
from app.services.activity import record_activity

logger = get_logger("grid_tracker.router")
router = APIRouter(tags=["grid-tracker"])

# The grid rides the local_seo feature grant - see the module docstring.
Feature = Annotated[CurrentUser, Depends(require_feature("local_seo"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

# A manual run triggers up to 41 PAID probes, so it is rate-limited per user on top of
# the cost gate: the gate bounds the MONEY, this bounds the hammering.
RunLimit = Depends(rate_limit("grid_run", limit=10, per_seconds=3600))


def _enqueue_run(definition_id: str, *, force: bool) -> None:
    """Enqueue the Celery run. Imported lazily so the router module stays importable
    (and unit-testable) without a broker, exactly like the other module routers."""
    from app.modules.grid_tracker.tasks import run_grid

    run_grid.delay(definition_id, force)



async def _resolve_profile(
    repo: Any, body: GridDefinitionCreate, settings: Any
) -> dict[str, Any] | None:
    """The location this grid centres on, from a CLIENT alone where possible.

    Precedence:
      1. an explicit ``profileId`` - a client with several locations, named exactly;
      2. the client's existing location derived from its business profile's city;
      3. that location, CREATED from the business profile.

    Returns ``None`` only when the client has no business profile at all, which is the
    one case the platform genuinely cannot resolve - and the caller says so rather than
    inventing a location.

    The location is written into `0039`'s ledger, not a grid-local copy: one location
    is one row whichever surface created it.
    """
    if body.profile_id:
        found: dict[str, Any] | None = await asyncio.to_thread(repo.profile, body.profile_id)
        return found
    if not body.client_id:
        return None

    # The client must EXIST before anything is derived from it. Without this a bogus
    # id fell through to the location insert and surfaced as a 500 from a foreign-key
    # violation - an internal error where the honest answer is "no such client".
    client_name_check = await asyncio.to_thread(repo.client_name, body.client_id)
    if client_name_check is None:
        return None

    bp = await asyncio.to_thread(repo.business_profile, body.client_id)
    if bp is None:
        # NO BUSINESS PROFILE, and that is the common case rather than the exception:
        # on this deploy 108 clients have 4 profiles between them. Refusing here made
        # the feature unusable for almost every client, so fall back to what the
        # platform always has - the client's NAME - and let Places find the listing
        # from that. It is the same lookup, with one fewer clue.
        #
        # This is safe to do BECAUSE the matched listing is recorded and shown
        # (0142): a name-only search is likelier to match the wrong business, and the
        # operator sees exactly which one it found before any run is paid for. Without
        # that evidence this fallback would be guessing.
        bp = {}
    # The label is the city the business is in - the name an operator would give this
    # location themselves, taken from the record instead of asked for.
    label = (str(bp.get("city") or "").strip()
             or str(bp.get("market") or "").strip()
             or "Main location")
    existing: dict[str, Any] | None = await asyncio.to_thread(
        repo.profile_for_client, body.client_id, label=label
    )
    if existing is not None:
        return existing

    client_name = client_name_check
    address = ", ".join(
        part for part in (
            str(bp.get("address_line1") or "").strip(),
            str(bp.get("city") or "").strip(),
            str(bp.get("region") or "").strip(),
            str(bp.get("postal_code") or "").strip(),
        ) if part
    )

    # THE PLACE ID IS THE MATCH, and an earlier version resolved it and then stored "".
    # Every probe therefore fell back to comparing NAMES, and the listing's own name
    # ("PoolServ LLC d/b/a Alligator Pools") does not equal the pack entry's ("Alligator
    # Pools"). Fifty-one probes came back `absent` for a business that was ranking in
    # every one of them. The handle Places already gave us is what makes the match exact,
    # so it is resolved here and persisted onto the location.
    anchor = await asyncio.to_thread(
        resolve_center,
        settings,
        business_name=str(bp.get("business_name") or client_name),
        address=address,
    )
    created: dict[str, Any] | None = await asyncio.to_thread(
        repo.create_profile,
        client_id=body.client_id,
        client_name=client_name,
        label=label,
        # The LISTING's name when Places found one - that is what appears in a pack,
        # and matching against a legal entity name is how this failed before.
        nap_name=(anchor.matched_name if anchor and anchor.matched_name
                  else str(bp.get("business_name") or client_name)),
        nap_address=(anchor.matched_address if anchor and anchor.matched_address
                     else address),
        nap_phone=str(bp.get("phone") or ""),
        place_id=anchor.place_id if anchor else "",
        website=str(bp.get("website_url") or ""),
    )
    return created


@router.get("/grid/definitions", response_model=list[GridDefinitionResponse])
async def list_definitions(
    repo: GridRepoDep,
    page: PageDep,
    _feature: Feature,
    _user: ViewReports,
    client_id: str | None = Query(default=None, alias="clientId"),
) -> list[GridDefinitionResponse]:
    """Every standing grid, newest first. Optionally one client's."""
    rows = await asyncio.to_thread(
        repo.list_definitions, client_id=client_id, limit=page.limit, offset=page.offset
    )
    return [GridDefinitionResponse.from_row(r) for r in rows]


@router.get("/grid/definitions/{definition_id}", response_model=GridDefinitionResponse)
async def get_definition(
    definition_id: str, repo: GridRepoDep, _feature: Feature, _user: ViewReports
) -> GridDefinitionResponse:
    row = await asyncio.to_thread(repo.get_definition, definition_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "grid not found")
    return GridDefinitionResponse.from_row(row)


def _preview_from_center(center: MapsCenter) -> MapsUrlPreview:
    """Project the resolver's result onto the wire shape. One mapping, one place."""
    return MapsUrlPreview(
        lat=center.lat,
        lng=center.lng,
        source=center.source,
        precise=center.is_precise,
        place_id=center.place_id,
        cid=center.cid,
        name=center.name,
        address=center.address,
        city=center.city,
        region=center.region,
        postal_code=center.postal_code,
        phone=center.phone,
        website=center.website,
        listing_url=center.listing_url,
        identity_verified=center.identity_verified,
        reason=center.reason,
    )


@router.post("/grid/maps-url/preview", response_model=MapsUrlPreview)
async def preview_maps_url(
    body: MapsUrlRequest,
    settings: SettingsDep,
    _user: ViewReports,
    _feature: Feature,
) -> MapsUrlPreview:
    """Resolve a pasted Google Maps link and SHOW what it found. Creates nothing.

    A read, not a write, and deliberately a separate call from ``create_definition``:
    the whole value of pasting a link is that a human can confirm the business before a
    grid is built on it. Resolving silently inside the create would put the confirmation
    after the commit, which is where 0142's evidence columns had to be retro-fitted.

    A 422 means the string cannot yield a centre at all, and its ``detail`` says what to
    paste instead. A resolvable link with an unverified identity is a 200 - the
    coordinates are real and the caller is told the business details are not.
    """
    try:
        center = await asyncio.to_thread(resolve_maps_url, settings, body.maps_url)
    except MapsUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _preview_from_center(center)


@router.post(
    "/grid/definitions",
    response_model=GridDefinitionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_definition(
    body: GridDefinitionCreate,
    repo: GridRepoDep,
    settings: SettingsDep,
    user: Lead,
    _feature: Feature,
) -> GridDefinitionResponse:
    """Create one standing grid, centred on an existing client LOCATION.

    The centre is resolved ONCE, here, and then frozen on the row - so a run next March
    probes the same physical points as one today and the two are comparable. Two
    sources, and no third: the operator's explicit coordinates, or the client's own
    Google listing. A postal address is never geocoded at probe time, because a
    mis-geocoded centre moves the whole grid while every number on it still looks
    entirely normal.
    """
    profile = await _resolve_profile(repo, body, settings)
    if profile is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "this client could not be resolved to a location - either no such client, "
            "or its business listing could not be found. Pass an explicit profileId, "
            "or enter the centre coordinates.",
        )

    client_id = str(profile["client_id"])
    center_source = "operator"
    matched_name = matched_address = ""
    lat, lng = body.center_lat, body.center_lng
    resolved_maps: MapsCenter | None = None

    # A PASTED LINK OUTRANKS TYPED COORDINATES, and that order is the point of the
    # feature. Both are "the operator said so", but one was copied from the listing
    # itself and the other was read off a screen and retyped - and a retyped coordinate
    # is where a digit goes missing without anything downstream being able to tell.
    if body.maps_url:
        try:
            resolved_maps = await asyncio.to_thread(resolve_maps_url, settings, body.maps_url)
        except MapsUrlError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        lat, lng = resolved_maps.lat, resolved_maps.lng
        center_source = "maps_url"
        # The 0142 evidence columns, filled from the listing the operator actually
        # pointed at rather than from a name match. Empty when the identity could not
        # be verified - an unverified centre must not display as a confirmed business.
        matched_name, matched_address = resolved_maps.name, resolved_maps.address

    if lat is None or lng is None:
        resolved = await asyncio.to_thread(
            resolve_center,
            settings,
            business_name=str(profile.get("nap_name") or profile.get("client_name") or ""),
            address=str(profile.get("nap_address") or ""),
        )
        if resolved is None:
            # An honest refusal beats a guessed centre. The operator can read the
            # coordinates off Google Maps and pass them explicitly.
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "this location's coordinates could not be resolved from its Google "
                "listing; supply centerLat and centerLng explicitly",
            )
        lat, lng, center_source = resolved.lat, resolved.lng, "places"
        matched_name, matched_address = resolved.matched_name, resolved.matched_address

    client_name = await asyncio.to_thread(repo.client_name, client_id) or ""
    row = await asyncio.to_thread(
        repo.create_definition,
        client_id=client_id,
        client_name=client_name,
        profile_id=str(profile["id"]),
        keyword=body.keyword,
        center_lat=lat,
        center_lng=lng,
        center_source=center_source,
        rings=body.rings,
        ring_spacing_km=body.ring_spacing_km,
        shape=body.shape,
        grid_size=body.grid_size,
        matched_name=matched_name,
        matched_address=matched_address,
    )
    if row is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "this location already tracks that keyword")

    await record_activity(
        user, kind="client",
        action=(
            f"created a {body.point_count}-point grid for '{body.keyword}' "
            f"(centre from {center_source})"
        ),
        target=client_name, entity_type="client", entity_id=client_id,
    )

    if body.sync_nap and resolved_maps is not None:
        await _sync_nap_from_maps(user, client_id, client_name, resolved_maps)

    return GridDefinitionResponse.from_row({**row, **_profile_labels(profile)})


async def _sync_nap_from_maps(
    user: CurrentUser, client_id: str, client_name: str, center: MapsCenter
) -> None:
    """Copy the resolved Google listing onto the client's canonical NAP.

    WHY THIS IS OPT-IN AND GUARDED TWICE. ``client_business_profiles`` is the record the
    citations module derives its directory submissions from - the whole point of that
    table's docstring. A wrong value here does not stay here; it is submitted to
    directories under the client's name, and unpicking a bad NAP across a live citation
    campaign is far more work than pasting the right link in the first place. So it
    happens only when the operator explicitly asked (``syncNap``) AND the lookup
    actually verified an identity.

    ONLY NON-EMPTY FIELDS ARE WRITTEN. A Places response legitimately omits a phone
    number or a postcode, and letting those omissions through as empty strings would
    have this feature ERASE good data the operator entered by hand - a sync that
    quietly deletes is not a sync. Writing only what was measured means the worst case
    is an unchanged field.

    Never fatal: the grid is created either way. A NAP sync that fails must not roll
    back a definition that was made correctly, so the failure is logged and reported
    through the activity trail rather than raised at the operator.
    """
    if not center.identity_verified:
        return

    candidates = {
        "business_name": center.name,
        "address_line1": center.address,
        "city": center.city,
        "region": center.region,
        "postal_code": center.postal_code,
        "phone": center.phone,
        "website_url": center.website,
    }
    fields = {key: value.strip() for key, value in candidates.items() if value.strip()}
    if not fields:
        return

    from app.db.clients_repo import ClientsRepo

    try:
        await asyncio.to_thread(
            ClientsRepo(user.id).upsert_business_profile,
            client_id=client_id,
            client_name=client_name,
            fields=fields,
        )
    except Exception:
        logger.warning("grid_maps_nap_sync_failed", client_id=client_id)
        return

    await record_activity(
        user, kind="client",
        action=(
            f"updated the NAP from a Google Maps listing ({', '.join(sorted(fields))})"
        ),
        target=client_name, entity_type="client", entity_id=client_id,
    )


def _profile_labels(profile: dict[str, Any]) -> dict[str, Any]:
    """The joined display columns the create INSERT does not return on its own."""
    return {"location_label": profile.get("location_label", "")}


@router.patch("/grid/definitions/{definition_id}", response_model=GridDefinitionResponse)
async def update_definition(
    definition_id: str,
    body: GridDefinitionUpdate,
    repo: GridRepoDep,
    user: Lead,
    _feature: Feature,
) -> GridDefinitionResponse:
    """Activate or deactivate a grid. Geometry is immutable by design - see the schema."""
    row = await asyncio.to_thread(repo.set_active, definition_id, is_active=body.is_active)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "grid not found")
    verb = "resumed" if body.is_active else "paused"
    await record_activity(
        user, kind="client",
        action=f"{verb} grid tracking for '{row.get('keyword', '')}'",
        target=str(row.get("client_name", "") or ""),
        entity_type="client", entity_id=str(row["client_id"]),
    )
    full = await asyncio.to_thread(repo.get_definition, definition_id)
    return GridDefinitionResponse.from_row(full or row)


@router.post(
    "/grid/definitions/{definition_id}/run",
    response_model=RunQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[RunLimit],
)
async def run_now(
    definition_id: str,
    repo: GridRepoDep,
    settings: SettingsDep,
    user: Lead,
    _feature: Feature,
) -> RunQueuedResponse:
    """Queue one run of this grid now.

    Every refusal below is an HONEST HOLD (202 with ``queued=false`` and a stable
    machine-readable reason), not an error and not a silent success: the caller gets a
    sentence it can show, rather than a spinner that never resolves.
    """
    row = await asyncio.to_thread(repo.get_definition, definition_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "grid not found")

    points = int(row.get("point_count", 0) or 0)

    if not row.get("is_active", True):
        return RunQueuedResponse(
            definition_id=definition_id, held=True, reason="grid_paused", point_count=points
        )

    if not grid_provider_is_live(settings):
        # Refuse HERE as well as in the worker. Queuing a job that can only raise
        # JobBlocked spends a worker slot to tell the operator something this request
        # already knows.
        return RunQueuedResponse(
            definition_id=definition_id,
            held=True,
            reason="no_coordinate_provider",
            point_count=points,
        )

    if await asyncio.to_thread(repo.has_open_run, definition_id):
        # A run is already queued or running. Each run is up to 41 paid probes, so a
        # double-click must not become a double bill.
        raise HTTPException(
            status.HTTP_409_CONFLICT, "a run for this grid is already in progress"
        )

    await asyncio.to_thread(_enqueue_run, definition_id, force=False)
    await record_activity(
        user, kind="client",
        action=f"queued a {points}-point grid run for '{row.get('keyword', '')}'",
        target=str(row.get("client_name", "") or ""),
        entity_type="client", entity_id=str(row["client_id"]),
    )
    return RunQueuedResponse(definition_id=definition_id, queued=True, point_count=points)


@router.get("/grid/definitions/{definition_id}/runs", response_model=list[GridRunResponse])
async def list_runs(
    definition_id: str,
    repo: GridRepoDep,
    page: PageDep,
    _feature: Feature,
    _user: ViewReports,
) -> list[GridRunResponse]:
    """This grid's run history, newest first - the trend behind the current heat map."""
    rows = await asyncio.to_thread(
        repo.list_runs, definition_id, limit=page.limit, offset=page.offset
    )
    return [GridRunResponse.from_row(r) for r in rows]


@router.get("/grid/runs/{run_id}", response_model=GridRunDetail)
async def get_run(
    run_id: str, repo: GridRepoDep, _feature: Feature, _user: ViewReports
) -> GridRunDetail:
    """One run and every probe in it: the heat map, in a single read."""
    run = await asyncio.to_thread(repo.get_run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    points = await asyncio.to_thread(repo.points, run_id)
    return GridRunDetail(
        run=GridRunResponse.from_row(run),
        points=[GridPointResponse.from_row(p) for p in points],
    )


@router.get("/grid/definitions/{definition_id}/latest", response_model=GridRunDetail)
async def latest_run(
    definition_id: str, repo: GridRepoDep, _feature: Feature, _user: ViewReports
) -> GridRunDetail:
    """The most recent run of this grid, with its points.

    404 when the grid has never run. A grid with no runs has no heat map, and
    answering with an empty one would render as a business that ranks nowhere.
    """
    run = await asyncio.to_thread(repo.latest_run, definition_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "this grid has not run yet")
    points = await asyncio.to_thread(repo.points, str(run["id"]))
    return GridRunDetail(
        run=GridRunResponse.from_row(run),
        points=[GridPointResponse.from_row(p) for p in points],
    )
