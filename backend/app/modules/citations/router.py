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
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import get_settings
from app.core.auth import CurrentUser, require_perm, require_role
from app.modules.citations.repo import CitationsRepoDep
from app.modules.citations.schemas import (
    AUTOMATABLE_TIERS,
    BusinessProfileRequest,
    BusinessProfileResponse,
    CitationCampaignRequest,
    CitationCampaignResponse,
    DirectoryResponse,
)
from app.modules.citations.service import (
    automatable_directories,
    estimate_campaign_cost,
    submit_method_label,
)
from app.services.activity import record_activity

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
    row = await asyncio.to_thread(repo.create_business_profile, client_name=name, fields=fields)
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
    name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    profile = await asyncio.to_thread(repo.get_business_profile, body.business_profile_id)
    if profile is None:
        raise _PROFILE_NOT_FOUND

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

    existing = await asyncio.to_thread(repo.existing_citation_directory_ids, body.client_id)
    skipped_manual = sum(1 for r in all_market_rows if r.get("tier") == "manual_only")
    fresh = [d for d in candidates if str(d["id"]) not in existing]

    queued_ids: list[str] = []
    for directory in fresh:
        row = await asyncio.to_thread(
            repo.queue_citation,
            client_id=body.client_id,
            client_name=name,
            directory_id=str(directory["id"]),
            directory_name=str(directory.get("name", "")),
            business_profile_id=body.business_profile_id,
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
        already_queued=len(candidates) - len(fresh),
        skipped_manual_only=skipped_manual,
        estimated_cost=estimated_cost,
        citation_ids=queued_ids,
    )
