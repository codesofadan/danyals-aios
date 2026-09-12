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
from app.modules.grid_tracker.provider import grid_provider_is_live, resolve_center
from app.modules.grid_tracker.repo import GridRepoDep
from app.modules.grid_tracker.schemas import (
    GridDefinitionCreate,
    GridDefinitionResponse,
    GridDefinitionUpdate,
    GridPointResponse,
    GridRunDetail,
    GridRunResponse,
    RunQueuedResponse,
)
from app.services.activity import record_activity

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
    return GridDefinitionResponse.from_row({**row, **_profile_labels(profile)})


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
