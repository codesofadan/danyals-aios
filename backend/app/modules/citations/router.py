"""Citation-builder module endpoints (7B-4): business profiles, the directory
catalog, and campaign dispatch.

Prefixed ``/citation-builder`` to avoid colliding with the EXISTING
``/offpage/citations`` monitoring surface (``app/routers/offpage.py``) - both read/
write the same ``citations`` table (0018, additively extended 0045); this router
owns the SUBMISSION half (queueing new work + browsing the catalog), offpage.py
keeps owning the read/reconcile half unchanged.

Reads require any provisioned staff (``view_reports``); writes (create/update a
business profile, dispatch a campaign) require a LEAD (owner/admin/manager) -
mirrors ``offpage.py``'s own permission split exactly. The `citations` money-dial's
paid pre-check happens per-row INSIDE the worker (``citation_submit_job``), not
here - dispatching a campaign only QUEUES rows; nothing is spent synchronously.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import get_settings
from app.core.auth import CurrentUser, require_perm, require_role
from app.modules.citations.repo import CitationsRepoDep, web2_credential_counts
from app.modules.citations.schemas import (
    AUTOMATABLE_TIERS,
    DEFAULT_CAMPAIGN_CAP,
    DEFAULT_MIN_AUTHORITY,
    BusinessProfileRequest,
    BusinessProfileResponse,
    CitationCampaignRequest,
    CitationCampaignResponse,
    CitationLiveUrl,
    DirectoryResponse,
    EngineStatusBoardResponse,
    EngineStatusResponse,
    GapAnalysisResponse,
    Web2PlatformStatusResponse,
    Web2StatusResponse,
)
from app.modules.citations.service import (
    automatable_directories,
    compute_citation_gap,
    estimate_campaign_cost,
    select_campaign_directories,
    submit_method_label,
)
from app.modules.citations.verticals import normalize_vertical
from app.services.activity import record_activity
from integrations.citation_status import citation_engine_board
from integrations.web2_status import web2_status_board

router = APIRouter(prefix="/citation-builder", tags=["citation-builder"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_PROFILE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Business profile not found"
)
_CLIENT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")


def get_citation_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the citation-submit worker (overridable in tests). The
    task module is imported lazily so the API process never pulls in Celery just to
    import this router (mirrors ``offpage.py``'s enqueuer dependencies)."""

    def _enqueue(citation_id: str) -> None:
        from app.modules.citations.tasks import citation_submit_job

        citation_submit_job.delay(citation_id)

    return _enqueue


CitationEnqueuerDep = Annotated[Callable[[str], None], Depends(get_citation_enqueuer)]


# --- business profiles ----------------------------------------------------------


@router.get("/business-profiles", response_model=list[BusinessProfileResponse])
async def list_business_profiles(
    repo: CitationsRepoDep,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[BusinessProfileResponse]:
    rows = await asyncio.to_thread(repo.list_business_profiles, client_id=client_id)
    return [BusinessProfileResponse.from_row(r) for r in rows]


@router.post(
    "/business-profiles",
    response_model=BusinessProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_business_profile(
    body: BusinessProfileRequest, repo: CitationsRepoDep, actor: Lead
) -> BusinessProfileResponse:
    """Add a canonical NAP location for a client (lead-only). 404s if the client is
    unknown/invisible; ``client_name`` is snapshotted so client_id never leaks."""
    name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    fields = body.model_dump(exclude={"client_id"})
    row = await asyncio.to_thread(
        repo.create_business_profile, client_id=body.client_id, client_name=name, fields=fields
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Could not create the profile"
        )
    await record_activity(
        actor, kind="content", action="added a business profile", target=name,
        entity_type="client", entity_id=body.client_id,
    )
    return BusinessProfileResponse.from_row(row)


@router.patch("/business-profiles/{profile_id}", response_model=BusinessProfileResponse)
async def update_business_profile(
    profile_id: str, body: BusinessProfileRequest, repo: CitationsRepoDep, actor: Lead
) -> BusinessProfileResponse:
    # Canonical-NAP lock guard: a locked profile rejects edits UNLESS the request
    # explicitly unlocks it (nap_locked=false in the same call). This stops the
    # name/address/phone every citation submits against from silently drifting.
    current = await asyncio.to_thread(repo.get_business_profile, profile_id)
    if current is None:
        raise _PROFILE_NOT_FOUND
    if current.get("nap_locked") and body.nap_locked:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This profile's NAP is locked. Unlock it (napLocked=false) before editing.",
        )
    changes = body.model_dump(exclude={"client_id"})
    row = await asyncio.to_thread(repo.update_business_profile, profile_id, changes)
    if row is None:
        raise _PROFILE_NOT_FOUND
    client_id = row.get("client_id")
    await record_activity(
        actor, kind="content", action="updated a business profile",
        target=row.get("client_name", ""), entity_type="client",
        entity_id=str(client_id) if client_id else None,
    )
    return BusinessProfileResponse.from_row(row)


@router.post(
    "/clients/{client_id}/ensure-profile",
    response_model=BusinessProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def ensure_business_profile(
    client_id: str, repo: CitationsRepoDep, actor: Lead
) -> BusinessProfileResponse:
    """Resolve a client's SUBMISSION profile, deriving one from the client's own NAP
    (captured at creation) when none exists yet (lead-only). This is what makes "No
    business profile yet for this client" self-heal: the citation-builder reuses the
    name/address the Add-Client wizard already collected instead of demanding a re-entry.
    404s if the client is unknown, or if it has no NAP at all to derive from."""
    name = await asyncio.to_thread(repo.client_name_for, client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    row = await asyncio.to_thread(repo.ensure_business_profile, client_id=client_id, client_name=name)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No NAP for this client yet - add its business profile first.",
        )
    return BusinessProfileResponse.from_row(row)


# --- directory catalog -----------------------------------------------------------


@router.get("/directories", response_model=list[DirectoryResponse])
async def list_directories(
    repo: CitationsRepoDep,
    _user: ViewReports,
    market: Annotated[list[str] | None, Query()] = None,
    tier: Annotated[list[str] | None, Query()] = None,
) -> list[DirectoryResponse]:
    """Browse the citation-directory catalog (0046's seed). ``market``/``tier``
    narrow the board; repeat the query param for multiple values."""
    rows = await asyncio.to_thread(repo.list_directories, markets=market, tiers=tier)
    return [DirectoryResponse.from_row(r) for r in rows]


# --- campaign dispatch ------------------------------------------------------------


@router.post(
    "/campaigns", response_model=CitationCampaignResponse, status_code=status.HTTP_201_CREATED
)
async def create_campaign(
    body: CitationCampaignRequest, repo: CitationsRepoDep, actor: Lead, enqueue: CitationEnqueuerDep
) -> CitationCampaignResponse:
    """Queue a citation campaign (lead-only): every automatable directory in the
    requested markets/tiers not already in flight for this client.

    Nothing SUBMITS synchronously here - each queued row is handed to the
    ``citation_submit_job`` worker, which cost-gates + dispatches it individually
    (so a client's budget cap still governs per row, not just this batch's own
    upfront estimate). 404s if the client or business profile is unknown/invisible.
    """
    client = await asyncio.to_thread(repo.client_meta_for, body.client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND
    name = str(client.get("name") or "")
    # Resolve the submission profile: an explicit id wins; otherwise DERIVE one from the
    # client's own NAP (0051) so a campaign is never blocked on "No business profile yet"
    # when the wizard already collected the name/address. A missing/invisible explicit id
    # falls back to the same auto-resolution rather than 404-ing outright.
    profile = None
    if body.business_profile_id:
        profile = await asyncio.to_thread(repo.get_business_profile, body.business_profile_id)
    if profile is None:
        profile = await asyncio.to_thread(
            repo.ensure_business_profile, client_id=body.client_id, client_name=name
        )
    if profile is None:
        raise _PROFILE_NOT_FOUND
    business_profile_id = str(profile["id"])

    # Resolve the client's vertical: an explicit override wins, else derive it from the
    # client's free-text industry. Unresolvable -> None -> general directories only.
    vertical = body.vertical or normalize_vertical(str(client.get("industry") or ""))
    cap = DEFAULT_CAMPAIGN_CAP if body.cap is None else body.cap
    min_authority = DEFAULT_MIN_AUTHORITY if body.min_authority is None else body.min_authority

    markets: list[str] = (
        [str(m) for m in body.markets] if body.markets else [str(profile.get("market", "US")), "GLOBAL"]
    )
    # Query the FULL market catalog ONCE (no tier filter) so the automatable
    # candidate set and the manual_only skip count are computed off the SAME rows -
    # filtering by `tiers` here first would silently exclude manual_only rows from
    # the very count meant to report how many were skipped.
    all_market_rows = await asyncio.to_thread(repo.list_directories, markets=markets, tiers=None)
    tiers = set(body.tiers) if body.tiers else set(AUTOMATABLE_TIERS)
    candidates = [r for r in automatable_directories(all_market_rows) if r.get("tier") in tiers]

    # Apply the reference-plan strategy (vertical match + spam-tail floor + marketplace
    # gate + build-order sort + cap). The selection is ORDERED, so queueing walks it in
    # build order (core -> tier1 -> tier2), and every exclusion is counted, never silent.
    selection = select_campaign_directories(
        candidates,
        vertical=vertical,
        cap=cap,
        min_authority=min_authority,
        include_marketplaces=body.include_marketplaces,
    )

    existing = await asyncio.to_thread(repo.existing_citation_directory_ids, body.client_id)
    requeueable = await asyncio.to_thread(repo.requeueable_citations, body.client_id)
    skipped_manual = sum(1 for r in all_market_rows if r.get("tier") == "manual_only")
    fresh = [d for d in selection.selected if str(d["id"]) not in existing]

    queued_ids: list[str] = []
    for directory in fresh:
        did = str(directory["id"])
        # A directory whose previous attempt ended blocked/failed is RE-QUEUED
        # (reset in place), not re-inserted and never silently skipped — a past
        # cost-gate hold must not permanently fence a directory off.
        stale_id = requeueable.get(did)
        if stale_id is not None:
            row = await asyncio.to_thread(repo.requeue_citation, stale_id)
        else:
            row = await asyncio.to_thread(
                repo.queue_citation,
                client_id=body.client_id,
                client_name=name,
                directory_id=did,
                directory_name=str(directory.get("name", "")),
                business_profile_id=business_profile_id,
                submit_method=submit_method_label(directory),
            )
        if row is None:
            continue
        queued_ids.append(str(row["id"]))
        enqueue(str(row["id"]))

    settings = get_settings()
    estimated_cost = estimate_campaign_cost(fresh, settings)
    await record_activity(
        actor, kind="content", action=f"queued a citation campaign ({len(queued_ids)} directories)",
        target=name, entity_type="client", entity_id=body.client_id,
    )
    return CitationCampaignResponse(
        queued=len(queued_ids),
        already_queued=len(selection.selected) - len(fresh),
        skipped_manual_only=skipped_manual,
        estimated_cost=estimated_cost,
        citation_ids=queued_ids,
        resolved_vertical=vertical,
        excluded_off_vertical=selection.excluded_off_vertical,
        excluded_low_authority=selection.excluded_low_authority,
        excluded_marketplace=selection.excluded_marketplace,
        capped=selection.capped,
    )


# --- gap analysis -----------------------------------------------------------------


@router.get("/gap-analysis", response_model=GapAnalysisResponse)
async def gap_analysis(
    repo: CitationsRepoDep,
    _user: ViewReports,
    client_id: Annotated[str, Query(alias="clientId", min_length=1)],
) -> GapAnalysisResponse:
    """Reconcile a client's citations against the automatable catalog: (a) analyse what
    exists (count + per-status tally + the live URLs earned), (b) compute which
    directories are still MISSING (the exact build target, in build order), and report
    the resolved NAP so the UI stops showing "No business profile yet" once one can be
    resolved from the client. Read-only - it never inserts a profile or queues work."""
    client = await asyncio.to_thread(repo.client_meta_for, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND

    # Resolve the NAP WITHOUT writing (this is a read endpoint, staff-wide): a submission
    # profile if one already exists, else the client's own NAP (which a lead-gated build
    # would DERIVE from). "none" is the honest answer when neither is present yet.
    profiles = await asyncio.to_thread(repo.list_business_profiles, client_id=client_id)
    profile = profiles[0] if profiles else None
    nap_source: Literal["submission_profile", "client_profile", "none"]
    if profile is not None:
        nap_source = "submission_profile"
        market = str(profile.get("market") or "US")
    else:
        client_nap = await asyncio.to_thread(repo.client_business_profile_for, client_id)
        if client_nap is not None and str(client_nap.get("business_name") or "").strip():
            nap_source = "client_profile"
            market = str(client_nap.get("market") or "US")
        else:
            nap_source = "none"
            market = "US"

    vertical = normalize_vertical(str(client.get("industry") or ""))
    markets = [market, "GLOBAL"]
    directories = await asyncio.to_thread(repo.list_directories, markets=markets, tiers=None)
    existing = await asyncio.to_thread(repo.list_citations_for_client, client_id)
    gap = compute_citation_gap(
        directories=directories, existing_citations=existing, vertical=vertical
    )
    return GapAnalysisResponse(
        client=str(client.get("name") or ""),
        has_nap=nap_source != "none",
        nap_source=nap_source,
        business_profile_id=str(profile["id"]) if profile is not None else None,
        resolved_vertical=vertical,
        existing_count=gap.existing_count,
        covered_count=gap.covered_count,
        missing_count=len(gap.missing),
        missing=[DirectoryResponse.from_row(d) for d in gap.missing],
        live_urls=[CitationLiveUrl(**u) for u in gap.live_urls],
        by_submit_status=gap.by_submit_status,
        by_nap_status=gap.by_nap_status,
    )


# --- API status boards (Wave 4) ---------------------------------------------------


@router.get("/web2-status", response_model=Web2StatusResponse)
async def web2_status(_user: ViewReports) -> Web2StatusResponse:
    """The Web 2.0 API status board: every platform CONNECTED (a per-client vault
    credential exists) vs MISSING, with the exact reason and the note that even a
    connected platform can be refused by the EXTERNAL API. Vault COUNTS only - no secret
    is read; an unconfigured DB degrades to an all-MISSING board rather than a 500."""
    counts = await asyncio.to_thread(web2_credential_counts)
    board = web2_status_board(counts)
    return Web2StatusResponse(
        connected_count=board.connected_count,
        live_count=board.live_count,
        total_count=board.total_count,
        platforms=[
            Web2PlatformStatusResponse(
                platform=p.platform,
                connected=p.connected,
                draft_only=p.draft_only,
                configured_count=p.configured_count,
                required_fields=list(p.required_fields),
                vault_provider=p.vault_provider,
                reason=p.reason,
                external_note=p.external_note,
            )
            for p in board.platforms
        ],
    )


@router.get("/engine-status", response_model=EngineStatusBoardResponse)
async def engine_status(_user: ViewReports) -> EngineStatusBoardResponse:
    """The citation-ENGINE status board: each submission engine (Bing/Foursquare direct
    API, the Apify fallback, the CAPTCHA solver, the self-hosted bot, the proxy)
    CONNECTED vs MISSING, with the reason and the external-API caveat. Derived from
    settings presence only - never a live probe, never a spend."""
    board = citation_engine_board(get_settings())
    return EngineStatusBoardResponse(
        connected_count=board.connected_count,
        total_count=board.total_count,
        engines=[
            EngineStatusResponse(
                key=e.key,
                label=e.label,
                connected=e.connected,
                reason=e.reason,
                required_config=list(e.required_config),
                external_note=e.external_note,
            )
            for e in board.engines
        ],
    )
