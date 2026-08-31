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
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.config import get_settings
from app.core.auth import CurrentUser, require_perm, require_role
from app.core.security import is_public_url
from app.modules.citations.evidence import citation_evidence_store
from app.modules.citations.operator_auth import OperatorOrUserDep, require_operator_lead
from app.modules.citations.repo import (
    CitationQueueRepoDep,
    CitationsRepoDep,
    DirectorySpecsRepoDep,
    ServiceCitationsStore,
    service_citations_store,
    web2_credential_counts,
)
from app.modules.citations.schemas import (
    AUTOMATABLE_TIERS,
    DEFAULT_CAMPAIGN_CAP,
    DEFAULT_MIN_AUTHORITY,
    AuditPlanItem,
    AuditPlanResponse,
    BusinessProfileRequest,
    BusinessProfileResponse,
    CitationCampaignRequest,
    CitationCampaignResponse,
    CitationLiveUrl,
    CitationSkip,
    DirectoryResponse,
    DirectorySpecResponse,
    EngineStatusBoardResponse,
    EngineStatusResponse,
    GapAnalysisResponse,
    QueueBlockedRequest,
    QueueBoardResponse,
    QueueClaimRequest,
    QueueCompleteRequest,
    QueueCompleteResponse,
    QueueFieldValue,
    QueueHeartbeatRequest,
    QueueItemResponse,
    SpecBoardResponse,
    SpecCreateRequest,
    SpecDeactivateRequest,
    SpecFirstLiveRequest,
    SpecVerifyRequest,
    Web2PlatformStatusResponse,
    Web2StatusResponse,
)
from app.modules.citations.service import (
    automatable_directories,
    build_audit_plan,
    citations_needing_correction,
    compute_citation_gap,
    diff_nap_fields,
    estimate_campaign_cost,
    job_from_row,
    select_campaign_directories,
    submit_method_label,
)
from app.modules.citations.verticals import normalize_vertical
from app.services.activity import record_activity
from app.services.citation_liveness import http_liveness_probe, judge_liveness
from integrations.citation_bot import db_spec_loader
from integrations.citation_status import citation_engine_board
from integrations.web2_status import web2_status_board

router = APIRouter(prefix="/citation-builder", tags=["citation-builder"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# The QUEUE routes only. These accept a dashboard bearer token OR the extension's
# `X-Operator-Token`, resolving both to the same CurrentUser - so there is ONE
# implementation of "a completion is checked by fetching the URL", not two.
#
# `OperatorOrUserLead` additionally requires a lead role, exactly as the bearer-only
# version did: an operator token inherits its holder's role and grants nothing extra.
# A non-lead paired extension is refused the write endpoints for the same reason a
# non-lead session is.
OperatorOrUser = OperatorOrUserDep
OperatorOrUserLead = Annotated[CurrentUser, Depends(require_operator_lead)]
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


def get_audit_enqueuer() -> Callable[[str, str, str], None]:
    """Dependency: enqueue the citation-AUDIT sweep (overridable in tests).

    Reuses the built off-page monitor worker (``monitor_offpage``): it pulls the
    business's directory listings from the configured citation tracker, diffs vs the
    ledger, and writes real ``nap_status`` rows (consistent / inconsistent / missing)
    - i.e. discovers where the business is already listed vs where it is not. Lazily
    imported so the API process never pulls in Celery just to import this router."""

    def _enqueue(client_id: str, domain: str, business: str) -> None:
        from workers.tasks.offpage import monitor_offpage_job

        monitor_offpage_job.delay(client_id, domain, business)

    return _enqueue


AuditEnqueuerDep = Annotated[Callable[[str, str, str], None], Depends(get_audit_enqueuer)]


def get_service_citations_store() -> ServiceCitationsStore:
    """Dependency: the privileged citations store (service_role) for the delete path.

    ``citations`` has FORCE RLS with no delete policy, so clearing rows must run on
    the service_role connection - exactly like the submit worker's writes."""
    return service_citations_store()


ServiceCitationsStoreDep = Annotated[ServiceCitationsStore, Depends(get_service_citations_store)]


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

    # THE FAN-OUT (0107). Every listing already built carries the values in `current`.
    # The moment this profile is saved they all disagree with canonical - not gradually,
    # immediately - and an inconsistent citation is worse than no citation, because it
    # splits the local signal instead of reinforcing it. So the canonical fields that
    # actually moved are diffed BEFORE the write, and every live listing built from this
    # profile is flagged for correction in the same breath as the edit.
    nap_events = diff_nap_fields(current, changes)

    row = await asyncio.to_thread(repo.update_business_profile, profile_id, changes)
    if row is None:
        raise _PROFILE_NOT_FOUND
    client_id = row.get("client_id")

    flagged = 0
    if nap_events and client_id:
        affected = await asyncio.to_thread(repo.citations_for_profile, profile_id)
        flagged = await asyncio.to_thread(
            repo.record_nap_change,
            client_id=str(client_id),
            profile_id=profile_id,
            events=nap_events,
            citation_ids=citations_needing_correction(affected),
        )

    await record_activity(
        actor, kind="content", action="updated a business profile",
        target=row.get("client_name", ""), entity_type="client",
        entity_id=str(client_id) if client_id else None,
        meta=(
            f"canonical NAP changed ({', '.join(e['field'] for e in nap_events)}); "
            f"{flagged} live listing(s) flagged for correction"
        )
        if nap_events
        else None,
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


# --- citation audit (discover) + clear ------------------------------------------


@router.post("/clients/{client_id}/audit", status_code=status.HTTP_202_ACCEPTED)
async def run_citation_audit(
    client_id: str, repo: CitationsRepoDep, actor: Lead, enqueue: AuditEnqueuerDep
) -> dict[str, Any]:
    """AUDIT a client's citations (lead-only): discover which directories ALREADY list
    this business (and whether the NAP is consistent) vs which are MISSING - the
    audit-first step before any build.

    Requires the client's NAP (business profile); enqueues the citation-tracker sweep
    (``monitor_offpage``), which pulls the business's directory listings, diffs vs the
    ledger, and writes the discovered ``nap_status`` rows the board + gap-analysis then
    read. Build then targets only the MISSING directories the audit surfaces. 404s on an
    unknown/invisible client; 400s when the client has no NAP to audit against. With no
    citation tracker configured the sweep degrades honestly (no rows) rather than
    inventing listings."""
    name = await asyncio.to_thread(repo.client_name_for, client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    profile = await asyncio.to_thread(
        repo.ensure_business_profile, client_id=client_id, client_name=name
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Add this client's NAP (business profile) before running a citation audit.",
        )
    business = str(profile.get("business_name") or name)
    # domain is only used by the sibling backlink monitor; a citation audit keys off
    # the business name, so "" is fine here.
    enqueue(client_id, "", business)
    await record_activity(
        actor, kind="content", action="ran a citation audit", target=name,
        entity_type="client", entity_id=client_id,
    )
    return {
        "status": "queued",
        "clientId": client_id,
        "business": business,
        "detail": "Citation audit queued - discovering existing vs missing listings.",
    }


@router.delete("/clients/{client_id}/citations")
async def clear_client_citations(
    client_id: str, repo: CitationsRepoDep, store: ServiceCitationsStoreDep, actor: Lead
) -> dict[str, Any]:
    """Clear ALL citation rows for a client (lead-only) so it can be re-audited from a
    clean slate. Validates the client is visible to the caller (RLS ``client_name_for``)
    BEFORE the privileged delete, so a lead can only clear a tenant it can see."""
    name = await asyncio.to_thread(repo.client_name_for, client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    removed = await asyncio.to_thread(store.clear_citations, client_id)
    await record_activity(
        actor, kind="content", action=f"cleared {removed} citation row(s)", target=name,
        entity_type="client", entity_id=client_id,
    )
    return {"clientId": client_id, "removed": removed}


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
    if body.directory_ids:
        # Audit-first "build only these": the operator ticked specific MISSING
        # directories, so build exactly those (still automatable + in-market) and
        # bypass the strategy filters/cap - an explicit choice is not second-guessed.
        wanted = {str(d) for d in body.directory_ids}
        picked = [r for r in candidates if str(r.get("id")) in wanted]
        selection = select_campaign_directories(
            picked, vertical=vertical, cap=0, min_authority=0, include_marketplaces=True
        )
    else:
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
        skipped=[CitationSkip(**s) for s in gap.skipped],
        by_submit_status=gap.by_submit_status,
        by_nap_status=gap.by_nap_status,
    )


# --- audit plan (generic -> country -> niche) -------------------------------------


@router.get("/clients/{client_id}/audit-plan", response_model=AuditPlanResponse)
async def audit_plan(
    client_id: str, repo: CitationsRepoDep, _user: ViewReports
) -> AuditPlanResponse:
    """The geo/niche/generic citation audit for a client, PRIORITIZED Generic -> Country
    -> Niche, each directory tagged built|missing (staff read).

    Reuses the SAME selection + gap logic a campaign uses (``build_audit_plan`` over
    ``select_campaign_directories`` + ``compute_citation_gap``) - no re-ranking. Read-only:
    resolves the client's market from an existing submission profile, else its own NAP,
    else US; derives built-vs-missing from the existing citation records (all ``missing``
    when none exist yet). Degrade-safe - never inserts a profile or queues work. 404s on an
    unknown/invisible client."""
    client = await asyncio.to_thread(repo.client_meta_for, client_id)
    if client is None:
        raise _CLIENT_NOT_FOUND

    # Resolve the market WITHOUT writing (mirrors gap_analysis): a submission profile's
    # market if one exists, else the client's own NAP market, else US.
    profiles = await asyncio.to_thread(repo.list_business_profiles, client_id=client_id)
    if profiles:
        market = str(profiles[0].get("market") or "US")
    else:
        client_nap = await asyncio.to_thread(repo.client_business_profile_for, client_id)
        market = str(client_nap.get("market") or "US") if client_nap else "US"

    vertical = normalize_vertical(str(client.get("industry") or ""))
    directories = await asyncio.to_thread(repo.list_directories, markets=[market, "GLOBAL"], tiers=None)
    existing = await asyncio.to_thread(repo.list_citations_for_client, client_id)
    plan = build_audit_plan(directories=directories, existing_citations=existing, vertical=vertical)

    def _items(rows: list[dict[str, Any]]) -> list[AuditPlanItem]:
        return [AuditPlanItem.from_directory(r, status=r["_status"]) for r in rows]

    # Any-typed so the runtime-validated market (always one of the five) binds to the
    # response's BusinessMarket Literal field without a static-typing narrowing dance.
    resolved_market: Any = market if market in {"US", "UK", "CA", "AU", "GLOBAL"} else "US"
    return AuditPlanResponse(
        client=str(client.get("name") or ""),
        resolved_vertical=vertical,
        market=resolved_market,
        generic=_items(plan.generic),
        country=_items(plan.country),
        niche=_items(plan.niche),
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
    API, the CAPTCHA solver, the self-hosted bot, the proxy)
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


# --- proof screenshot download ----------------------------------------------------


@router.get("/citations/{citation_id}/proof")
async def download_citation_proof(
    citation_id: str,
    _user: ViewReports,
    repo: CitationsRepoDep,
) -> FileResponse:
    """Serve a citation's proof SCREENSHOT.

    A screenshot is evidence that a submission happened. It is NOT the listing, it is
    not a live URL, and it is served from a separate route for exactly that reason -
    `proof_url` and `live_url` are different facts and conflating them is the defect
    0106 exists to remove.

    `proof_url` holds a relative key, never a path. The key is resolved inside a fixed
    root and the resolved path is never returned to the caller - only the bytes."""
    row = await asyncio.to_thread(repo.get_citation, citation_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found")

    store = citation_evidence_store(get_settings())
    if store is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No citation artifact root is configured, so no proof was captured",
        )

    path = await asyncio.to_thread(store.resolve, str(row.get("proof_url") or ""))
    if path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No proof on file")
    return FileResponse(path, media_type="image/png", filename=f"citation-{citation_id}.png")


# --- the human work queue (0110) ---------------------------------------------------
#
# Route C - a human working a directory by hand - is ~200 of the 226 catalogue rows and,
# measured, 56% of the loaded cost per live citation. It was previously a desktop script
# that printed one shared password for a whole campaign and recorded nothing. These
# endpoints are the product that replaces it.
#
# All of them are ordinary staff-authenticated routes. The Chrome extension (Phase 3)
# will reach the same queue through a separate scoped credential; keeping the surfaces
# apart means the dashboard's auth never has to loosen to accommodate a browser
# extension living next to hostile page JS.

# How long a claim is held before it returns to the pool. A LEASE, not a lock: an
# operator who closes their laptop must not strand an item forever. Twenty minutes is
# comfortably longer than the ~4 minutes a prepared item should take, and short enough
# that a stranded item is back in the queue within one coffee break.
_QUEUE_LEASE_SECONDS = 20 * 60

_QUEUE_BLOCK_LABELS: dict[str, str] = {
    "captcha_wall": "a CAPTCHA the operator could not clear",
    "account_required": "the directory demands an account we do not hold",
    "paid_only": "listing requires payment",
    "form_changed": "the add-listing form is not what we expected",
    "duplicate_listing": "the business is already listed",
    "directory_dead": "the directory no longer accepts listings",
    "phone_verification": "verification by phone call to the business",
    "postcard_verification": "verification by posted card to the business",
    "other": "see the operator's note",
}


def _spec_selectors(row: dict[str, Any]) -> dict[str, str]:
    """`{value_key: selector}` from this directory's ACTIVE spec, or empty.

    Empty is the normal case and must stay honest: the whitelist starts empty, and a
    directory with no earned spec has no selectors to offer. The panel then shows
    copy-buttons instead of a Fill action, which is a smaller feature rather than a
    broken one."""
    spec_loader = db_spec_loader
    try:
        job = job_from_row(row)
        spec = spec_loader(job)
    except Exception:
        return {}
    if spec is None:
        return {}
    return {f.value_key: f.selector for f in spec.fields}


def _queue_fields(row: dict[str, Any]) -> list[QueueFieldValue]:
    """Every value the operator needs, pre-computed and labelled.

    Empty values are DROPPED rather than shown blank. A form asks for what it asks for;
    presenting an operator with eight empty boxes to puzzle over is exactly the friction
    the queue exists to remove, and a blank field is better discovered on the directory's
    own form than in our panel."""
    pairs: list[tuple[str, str, Any]] = [
        ("business_name", "Business name", row.get("bp_business_name")),
        ("address_line1", "Address", row.get("bp_address_line1")),
        ("address_line2", "Address line 2", row.get("bp_address_line2")),
        ("city", "City", row.get("bp_city")),
        ("region", "State / region", row.get("bp_region")),
        ("postal_code", "Postcode", row.get("bp_postal_code")),
        ("phone", "Phone", row.get("bp_phone")),
        ("website_url", "Website", row.get("bp_website_url")),
        ("email", "Email", row.get("bp_email")),
        ("description", "Description", row.get("bp_description")),
    ]
    selectors = _spec_selectors(row)
    out = [
        QueueFieldValue(key=k, label=label, value=str(v).strip(), selector=selectors.get(k, ""))
        for k, label, v in pairs
        if str(v or "").strip()
    ]
    categories = row.get("bp_categories") or []
    if categories:
        out.append(
            QueueFieldValue(
                key="categories", label="Categories", value=", ".join(categories),
                selector=selectors.get("categories", ""),
            )
        )
    return out


def _queue_item(row: dict[str, Any]) -> QueueItemResponse:
    expires = row.get("claim_expires_at")
    prohibited = ""
    if str(row.get("directory_route") or "").upper() == "F":
        # This should be unreachable - a route-F row can never be queued - so if it is
        # ever seen, say so loudly rather than letting an operator submit against terms
        # that forbid it under the client's own identity.
        prohibited = (
            "This directory's terms forbid automated submission and it should not be in "
            f"the queue. Do not submit. {row.get('directory_tos_source_url') or ''}"
        ).strip()
    return QueueItemResponse(
        citation_id=str(row.get("id")),
        client=str(row.get("client_name") or ""),
        directory=str(row.get("directory_name") or row.get("directory") or ""),
        directory_url=str(row.get("directory_url") or ""),
        add_url=str(row.get("directory_add_url") or ""),
        fields=_queue_fields(row),
        queued_because=str(row.get("blocked_reason") or "") or "prepared for a human to finish",
        claim_expires_at=expires.isoformat() if expires else None,
        human_attempts=int(row.get("human_attempts") or 0),
        worked_seconds=int(row.get("worked_seconds") or 0),
        prohibited_warning=prohibited,
    )


@router.get("/queue", response_model=QueueBoardResponse)
async def citation_queue_board(queue: CitationQueueRepoDep, _user: OperatorOrUser) -> QueueBoardResponse:
    """The queue at a glance, plus the median minutes per finished item."""
    stats = await asyncio.to_thread(queue.queue_stats)
    median = stats.get("median_seconds")
    return QueueBoardResponse(
        waiting=int(stats.get("waiting") or 0),
        in_progress=int(stats.get("in_progress") or 0),
        median_seconds=int(median) if median is not None else None,
    )


@router.post("/queue/claim", response_model=QueueItemResponse | None)
async def claim_queue_item(
    body: QueueClaimRequest, queue: CitationQueueRepoDep, actor: OperatorOrUserLead
) -> QueueItemResponse | None:
    """Take the next available item. Returns ``null`` when the queue is empty."""
    claimed = await asyncio.to_thread(
        queue.claim_next, lease_seconds=_QUEUE_LEASE_SECONDS, client_id=body.client_id
    )
    if claimed is None:
        return None
    # Re-read through held_item so the response carries the joined directory + NAP the
    # operator actually needs; the claim UPDATE can only return citations.* .
    row = await asyncio.to_thread(queue.held_item, str(claimed["id"]))
    if row is None:
        return None
    await record_activity(
        actor, kind="task", action="claimed a citation queue item",
        target=str(row.get("directory_name") or row.get("directory") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id")) if row.get("client_id") else None,
    )
    return _queue_item(row)


@router.get("/queue/{citation_id}", response_model=QueueItemResponse)
async def get_queue_item(
    citation_id: str, queue: CitationQueueRepoDep, _user: OperatorOrUser
) -> QueueItemResponse:
    """The item this operator currently holds. 404s once the claim lapses, so a stale
    browser tab cannot keep working an item somebody else now owns."""
    row = await asyncio.to_thread(queue.held_item, citation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You do not hold this item, or the claim has expired.",
        )
    return _queue_item(row)


@router.post("/queue/{citation_id}/heartbeat")
async def heartbeat_queue_item(
    citation_id: str, body: QueueHeartbeatRequest, queue: CitationQueueRepoDep, _user: OperatorOrUser
) -> dict[str, Any]:
    """Extend the lease and bank the time worked. Time ACCUMULATES, so a crash costs at
    most one heartbeat of measurement rather than the whole session."""
    ok = await asyncio.to_thread(
        queue.extend_claim,
        citation_id,
        lease_seconds=_QUEUE_LEASE_SECONDS,
        worked_seconds=body.worked_seconds,
    )
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Your claim on this item has expired - claim it again before continuing.",
        )
    return {"ok": True, "leaseSeconds": _QUEUE_LEASE_SECONDS}


@router.post("/queue/{citation_id}/release", status_code=status.HTTP_204_NO_CONTENT)
async def release_queue_item(
    citation_id: str, body: QueueHeartbeatRequest, queue: CitationQueueRepoDep, _user: OperatorOrUser
) -> None:
    """Hand the item back without finishing it. The attempt still counts."""
    await asyncio.to_thread(queue.release_claim, citation_id, worked_seconds=body.worked_seconds)


@router.post("/queue/{citation_id}/complete", response_model=QueueCompleteResponse)
async def complete_queue_item(
    citation_id: str, body: QueueCompleteRequest, queue: CitationQueueRepoDep, actor: OperatorOrUserLead
) -> QueueCompleteResponse:
    """Close an item with the public URL of the listing that was created.

    THE COMPLETION IS CHECKED, NOT ASSERTED. The operator supplies a URL; the same
    liveness probe the scheduled re-check uses fetches it and looks for the business's
    name and its phone or address. If it is not there, the completion is REFUSED and the
    item stays claimed - the operator finds out while the tab is still open, instead of
    at a re-check three days later when the context is gone.

    That refusal is a normal response, not an error. The commonest cause is not
    dishonesty, it is a directory that has accepted the submission into a moderation
    queue and not published it yet - in which case the honest answer really is 'not live
    yet', and the operator should release the item rather than close it."""
    row = await asyncio.to_thread(queue.held_item, citation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You do not hold this item, or the claim has expired.",
        )

    live_url = body.live_url.strip()
    # SSRF: the URL is operator-supplied and this fetch runs server-side.
    if not await asyncio.to_thread(is_public_url, live_url):
        return QueueCompleteResponse(
            accepted=False,
            submit_status=str(row.get("submit_status") or ""),
            live_url=live_url,
            reason="That is not a reachable public URL.",
        )

    probe = await asyncio.to_thread(http_liveness_probe, live_url)
    verdict = judge_liveness(
        probe,
        business_name=str(row.get("bp_business_name") or ""),
        phone=str(row.get("bp_phone") or ""),
        address_line1=str(row.get("bp_address_line1") or ""),
    )
    if not verdict.is_live:
        return QueueCompleteResponse(
            accepted=False,
            submit_status=str(row.get("submit_status") or ""),
            live_url=live_url,
            reason=str(verdict.evidence.get("reason") or "the business was not found on that page"),
            matched_fields=list(verdict.evidence.get("matched_fields") or []),
        )

    updated = await asyncio.to_thread(
        queue.complete_item,
        citation_id,
        live_url=live_url,
        submit_status=verdict.status,
        evidence=verdict.evidence,
        worked_seconds=body.worked_seconds,
        note=body.note,
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Your claim on this item expired."
        )
    await record_activity(
        actor, kind="task", action="completed a citation listing",
        target=str(row.get("directory_name") or row.get("directory") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id")) if row.get("client_id") else None,
        meta=f"live at {live_url}",
    )
    return QueueCompleteResponse(
        accepted=True,
        submit_status=verdict.status,
        live_url=live_url,
        matched_fields=list(verdict.evidence.get("matched_fields") or []),
    )


@router.post("/queue/{citation_id}/blocked", status_code=status.HTTP_204_NO_CONTENT)
async def block_queue_item(
    citation_id: str, body: QueueBlockedRequest, queue: CitationQueueRepoDep, actor: OperatorOrUserLead
) -> None:
    """Close an item as NOT done, with a machine-readable reason.

    This is the outcome operators will reach for most often and it must cost them
    nothing to report. The reasons are a closed vocabulary so the board can answer
    'which directories are wasting our time?' - which is what eventually removes a row
    from the offer list."""
    row = await asyncio.to_thread(queue.held_item, citation_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You do not hold this item, or the claim has expired.",
        )
    detail = body.detail.strip() or _QUEUE_BLOCK_LABELS.get(body.reason, body.reason)
    await asyncio.to_thread(
        queue.block_item,
        citation_id,
        reason=body.reason,
        detail=detail,
        worked_seconds=body.worked_seconds,
    )
    await record_activity(
        actor, kind="task", action="reported a citation as blocked",
        target=str(row.get("directory_name") or row.get("directory") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id")) if row.get("client_id") else None,
        meta=f"{body.reason}: {detail}",
    )


@router.post("/recheck", status_code=status.HTTP_202_ACCEPTED)
async def trigger_liveness_recheck(actor: Lead, limit: int = 200) -> dict[str, Any]:
    """Re-verify every citation whose re-check has come due, now.

    WHY THIS EXISTS AS AN ENDPOINT. The sweep is designed to run on a schedule, but
    Celery beat is switched OFF across this platform by an owner instruction - so a
    scheduled-only re-check would be a feature that never runs, and `live` would quietly
    go back to meaning "was live once". Rather than reverse someone else's decision about
    cron, the same task is reachable on demand here; the beat entry sits ready in
    ``_BEAT_SCHEDULE_DISABLED`` for whenever that decision changes.

    Costs nothing metered: plain HTTP GETs against listing URLs, no provider call, so it
    does not pass through the money dial. Runs inline rather than via Celery so the
    operator gets the counts back instead of a job id they would have to chase."""
    from app.modules.citations.tasks import execute_liveness_recheck
    from app.services.citation_liveness import http_liveness_probe

    result = await asyncio.to_thread(
        execute_liveness_recheck,
        service_citations_store(),
        fetch=http_liveness_probe,
        limit=max(1, min(limit, 500)),
    )
    await record_activity(
        actor, kind="task", action="ran a citation liveness re-check",
        target=f"{result.get('checked', 0)} listing(s)",
        meta=f"{result.get('changed', 0)} changed state",
    )
    return result


# --- the earned spec whitelist (0111) ----------------------------------------------
#
# A directory reaches the automated route only after (a) a dated human live-DOM check and
# (b) one submission that produced a public listing URL. The whitelist starts EMPTY, and
# that is the true state rather than a regression: the 50 in-code specs were never
# verified, and 29 of their URLs answer 403.
#
# Every rule here is enforced in the DATABASE - a CHECK for the earned contract, triggers
# for immutability and for binding a spec's URL to its own directory's host. These routes
# are a thin caller; they deliberately do not re-implement any of it, so there is exactly
# one place each rule can be wrong. A constraint violation surfaces as a 409 with the
# database's own message, which is more accurate than anything restated here.


def _spec_conflict(exc: Exception) -> HTTPException:
    """Turn a database refusal into a 409 carrying the reason the database gave.

    Restating these in Python would mean maintaining a second copy of every rule, and the
    copy would drift. The database's message names the exact constraint, which is what an
    operator needs."""
    # psycopg exposes the server's own message on `.diag`; anything else falls back to
    # str(exc). Read defensively so a non-psycopg error still produces a usable 409
    # rather than raising a second exception inside the handler.
    diag = getattr(exc, "diag", None)
    primary = getattr(diag, "message_primary", None) if diag is not None else None
    detail = str(primary or exc)
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=detail[:400])


@router.get("/specs", response_model=SpecBoardResponse)
async def list_directory_specs(
    specs: DirectorySpecsRepoDep,
    _user: ViewReports,
    directory_id: Annotated[str | None, Query(alias="directoryId")] = None,
) -> SpecBoardResponse:
    """The whitelist, and how much each spec has earned."""
    rows = await asyncio.to_thread(specs.list_specs, directory_id=directory_id)
    out = [DirectorySpecResponse.from_row(r) for r in rows]
    return SpecBoardResponse(
        active=sum(1 for s in out if s.active),
        verified_not_live=sum(1 for s in out if s.verified and not s.has_first_live_url),
        unverified=sum(1 for s in out if not s.verified),
        drifted=sum(1 for s in out if s.drifted),
        specs=out,
    )


@router.post("/specs", response_model=DirectorySpecResponse, status_code=status.HTTP_201_CREATED)
async def create_directory_spec(
    body: SpecCreateRequest, specs: DirectorySpecsRepoDep, actor: Lead
) -> DirectorySpecResponse:
    """Record a NEW spec revision, always inactive.

    The spec's URL must belong to its own directory's host - enforced by a trigger,
    because that URL is a browser navigation target. Without it a lead could point our
    headless browser at an internal address and read the response back as a screenshot."""
    payload = {
        "url": body.url,
        "fields": [{"selector": f.selector, "value_key": f.value_key} for f in body.fields],
        "submit_selector": body.submit_selector,
        "success_indicator": body.success_indicator,
    }
    try:
        row = await asyncio.to_thread(
            specs.create_spec, directory_id=body.directory_id, spec=payload
        )
    except Exception as exc:
        raise _spec_conflict(exc) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Could not create the spec")
    await record_activity(
        actor, kind="content", action="recorded a directory form spec",
        target=body.directory_id,
    )
    full = await asyncio.to_thread(specs.get_spec, str(row["id"]))
    return DirectorySpecResponse.from_row(full or row)


@router.post("/specs/{spec_id}/verify", response_model=DirectorySpecResponse)
async def verify_directory_spec(
    spec_id: str, body: SpecVerifyRequest, specs: DirectorySpecsRepoDep, actor: Lead
) -> DirectorySpecResponse:
    """Half (a): sign that a human diffed these selectors against the live form.

    Write-once. A stale verification cannot be quietly refreshed to make an old spec look
    recently checked - that would turn the date, which is the whole value, into
    decoration."""
    evidence = {
        "checked_at": datetime.now(UTC).isoformat(),
        "selectors": body.selectors,
        "notes": body.notes[:1000],
    }
    row = await asyncio.to_thread(
        specs.record_verification, spec_id, verified_by=actor.id, evidence=evidence
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Not found, or already verified - a verification is written once.",
        )
    await record_activity(
        actor, kind="content", action="verified a directory form spec against the live DOM",
        target=str(row.get("directory_id") or ""),
    )
    full = await asyncio.to_thread(specs.get_spec, spec_id)
    return DirectorySpecResponse.from_row(full or row)


@router.post("/specs/{spec_id}/first-live", response_model=DirectorySpecResponse)
async def record_spec_first_live(
    spec_id: str, body: SpecFirstLiveRequest, specs: DirectorySpecsRepoDep, actor: Lead
) -> DirectorySpecResponse:
    """Half (b): the first public listing URL this exact spec produced.

    CHECKED, not asserted - the same probe the queue and the re-check use fetches the URL
    and looks for nothing in particular except that it answers. A spec is not permitted to
    earn its way onto the whitelist on a URL nobody could load."""
    live_url = body.live_url.strip()
    if not await asyncio.to_thread(is_public_url, live_url):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="That is not a reachable public URL.",
        )
    probe = await asyncio.to_thread(http_liveness_probe, live_url)
    if probe.status_code is None or not (200 <= probe.status_code < 300):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"That URL did not answer (status: {probe.status_code}). A spec earns the "
                "whitelist on a listing that exists, not on a URL that was typed."
            ),
        )
    try:
        row = await asyncio.to_thread(specs.record_first_live, spec_id, live_url=live_url)
    except Exception as exc:
        raise _spec_conflict(exc) from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Not found, or a first live URL is already on file (write-once).",
        )
    await record_activity(
        actor, kind="content", action="recorded a spec's first live listing",
        target=str(row.get("directory_id") or ""), meta=live_url,
    )
    full = await asyncio.to_thread(specs.get_spec, spec_id)
    return DirectorySpecResponse.from_row(full or row)


@router.post("/specs/{spec_id}/activate", response_model=DirectorySpecResponse)
async def activate_directory_spec(
    spec_id: str, specs: DirectorySpecsRepoDep, actor: Lead
) -> DirectorySpecResponse:
    """Turn the spec on, and promote its directory to route B in the same transaction.

    The route move is the point, not bookkeeping: gating the loader on `route = 'B'` while
    nothing could ever SET route B produced a whitelist that could never have a member.
    Activation IS the evidence the directory earned route B.

    The refusal comes from the `active_is_earned` CHECK, so an unverified spec cannot be
    activated however the request is shaped."""
    try:
        row = await asyncio.to_thread(specs.activate, spec_id)
    except Exception as exc:
        raise _spec_conflict(exc) from exc
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spec not found")
    await record_activity(
        actor, kind="content", action="activated a directory form spec",
        target=str(row.get("directory_id") or ""),
    )
    full = await asyncio.to_thread(specs.get_spec, spec_id)
    return DirectorySpecResponse.from_row(full or row)


@router.post("/specs/{spec_id}/deactivate", response_model=DirectorySpecResponse)
async def deactivate_directory_spec(
    spec_id: str, body: SpecDeactivateRequest, specs: DirectorySpecsRepoDep, actor: Lead
) -> DirectorySpecResponse:
    """Turn a spec off, with a reason that reaches the client report."""
    row = await asyncio.to_thread(specs.deactivate, spec_id, reason=body.reason)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Spec not found")
    await record_activity(
        actor, kind="content", action="deactivated a directory form spec",
        target=str(row.get("directory_id") or ""), meta=body.reason,
    )
    full = await asyncio.to_thread(specs.get_spec, spec_id)
    return DirectorySpecResponse.from_row(full or row)
