"""Competitor-intel module endpoints (Part 8 Phase 2C): the competitive set + gaps.

No ``frontend/lib/*.ts`` type mirrors this module - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape/enum tests). The
``GET /competitor-intel/workspace`` adapter emits the ``lib/tools.ts``
``competitor_intel`` EXTRA shape (KPIs + the gap-analysis table + the CTA), with table
columns pinned to ``tests/test_tool_workspace_contract.py``.

Tables owned: ``competitors`` / ``keyword_gaps`` (migration ``0037_competitor_intel``),
plus the ``backlinks.competitor_id`` dimension that migration adds to the EXISTING 0018
ledger. Cost-gate dial: ``competitor_intel`` - its OWN money dial, so ops can throttle
competitive research without touching audits, content or rank tracking.

Access: every route requires the ``competitor_intel`` FEATURE grant. Reads add
``view_reports``; every mutation (each of which either creates or triggers CLIENT spend)
adds the ``run_research`` MODULE perm - held by the leads (owner/admin/manager), and
ONLY them - which lines up with the 0037 RLS insert/update policies byte-for-byte.

The internal ``client_id`` never leaks (``client`` is the snapshotted name); every
mutation offloads the blocking psycopg call with ``asyncio.to_thread`` and records an
activity entry (kind=client, entity=client) so the competitive work keeps each client's
context fresh.

THE REUSE THIS MODULE EXISTS TO MAKE (Phase 2C's whole premise): a gap's
``clientPosition`` is read FREE from the Rank Tracker's ``tracked_keywords`` (0036) -
never re-bought from a provider. The client already pays for that position nightly, so
the only thing this module buys is the RIVAL's side of the comparison.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_feature, require_module_perm, require_perm
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.core.ratelimit import rate_limit
from app.modules.competitor_intel.repo import CompetitorRepoDep
from app.modules.competitor_intel.schemas import (
    AnalysisQueued,
    BacklinkGapResponse,
    CompetitorCreate,
    CompetitorResponse,
    CompetitorStats,
    CompetitorUpdate,
    DiscoverRequest,
    DiscoveryQueued,
    GapPromoted,
    GapType,
    KeywordGapResponse,
    ShareOfVoiceEntry,
    ShareOfVoiceResponse,
)
from app.modules.competitor_intel.service import (
    build_workspace,
    normalize_domain,
    share_of_voice,
    visibility_score,
)
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.activity import record_activity

router = APIRouter(tags=["competitor-intel"])

# Every tool route requires the fine-grained competitor_intel feature grant (owner is
# all-on). Reads additionally require view_reports; every mutation requires the
# run_research MODULE perm - held by the leads (owner/admin/manager), mirroring the
# 0037 RLS insert/update policies exactly. ``run_research`` is a ModulePermKey, so it
# goes through require_module_perm; require_perm would deny every non-owner role
# (a module perm is not in DEFAULT_ROLE_PERMS - see app/core/auth.py).
Feature = Annotated[CurrentUser, Depends(require_feature("competitor_intel"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
RunResearch = Annotated[CurrentUser, Depends(require_module_perm("run_research"))]

# Discovery is a PAID, client-billed SWEEP (one SERP per sampled keyword) fired straight
# from a button, so it carries a per-user rate limit on top of the cost gate. The limit
# is tighter than the rank-tracker's single-check equivalent because one press here is
# N provider calls, not one.
DiscoverLimit = Annotated[None, Depends(rate_limit("competitor_discover", limit=6, per_seconds=60))]
AnalyzeLimit = Annotated[None, Depends(rate_limit("competitor_analyze", limit=30, per_seconds=60))]

_COMPETITOR_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Competitor not found"
)
_GAP_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Gap not found")
_CLIENT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
_NOTHING_TO_UPDATE = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
)
_BAD_DOMAIN = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="A valid competitor domain is required"
)


def get_analysis_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the gap-analysis worker (overridable in tests).

    The Celery task is imported lazily so the API process never pulls in the task
    module - and therefore never imports ``celery_app`` - just to import this router.
    """

    def _enqueue(competitor_id: str) -> None:
        from app.modules.competitor_intel.tasks import run_gap_analysis

        run_gap_analysis.delay(competitor_id)

    return _enqueue


def get_discovery_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the auto-discovery worker (overridable in tests)."""

    def _enqueue(client_id: str) -> None:
        from app.modules.competitor_intel.tasks import discover_competitors

        discover_competitors.delay(client_id)

    return _enqueue


AnalysisEnqueuerDep = Annotated[Callable[[str], None], Depends(get_analysis_enqueuer)]
DiscoveryEnqueuerDep = Annotated[Callable[[str], None], Depends(get_discovery_enqueuer)]


def _share_of_voice_for(repo: Any, settings: Any, *, client_id: str, client_name: str) -> ShareOfVoiceResponse:
    """The client's + their tracked competitors' share of the measured market. Blocking.

    Every input is already on hand: the client's positions come from the Rank Tracker
    (0036) and each competitor's from their last stored analysis, so this endpoint
    makes NO provider call and costs nothing. It is therefore only as fresh as those
    two, which each row's own ``analyzed`` stamp reports honestly.
    """
    curve = tuple(settings.competitor_intel_ctr_curve_list)
    client_positions = repo.client_positions(client_id)
    client_volumes = repo.client_keyword_volumes(client_id)
    visibilities: dict[str, float] = {
        client_name or "client": visibility_score(client_positions, client_volumes, curve=curve)
    }

    competitors = repo.list_competitors(client_id=client_id, tracked=True)
    labels: dict[str, str] = {}
    for row in competitors:
        domain = str(row.get("domain") or "")
        positions, volumes = repo.competitor_gap_positions(str(row["id"]))
        visibilities[domain] = visibility_score(positions, volumes, curve=curve)
        labels[domain] = str(row.get("label") or "")

    shares = share_of_voice(visibilities)
    client_key = client_name or "client"
    entries = [
        ShareOfVoiceEntry(
            domain=domain,
            label=labels.get(domain, "") if domain != client_key else client_name,
            is_client=(domain == client_key),
            visibility=visibility,
            share=shares.get(domain, 0.0),
        )
        for domain, visibility in visibilities.items()
    ]
    # The client first, then the biggest rival: the reader's question is "where do we
    # stand", and the answer should not have to be hunted for in a sorted list.
    entries.sort(key=lambda e: (not e.is_client, -e.share, e.domain))
    return ShareOfVoiceResponse(
        client=client_name, entries=entries, curve=list(curve), provisional=True
    )


# --- reads --------------------------------------------------------------------


@router.get("/competitor-intel/competitors", response_model=list[CompetitorResponse])
async def list_competitors(
    repo: CompetitorRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    source: Annotated[str | None, Query()] = None,
    tracked: Annotated[bool | None, Query()] = None,
) -> list[CompetitorResponse]:
    """The competitor board, most-competitive first. Filters narrow it by client,
    discovery source (``manual``/``serp_auto``) or tracked state."""
    rows = await asyncio.to_thread(
        repo.list_competitors,
        client_id=client_id,
        source=source,
        tracked=tracked,
        limit=page.limit,
        offset=page.offset,
    )
    return [CompetitorResponse.from_row(r) for r in rows]


@router.get("/competitor-intel/stats", response_model=CompetitorStats)
async def competitor_stats(
    repo: CompetitorRepoDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> CompetitorStats:
    """The board summary tiles: competitors tracked, open keyword gaps, and the
    client's share of the measured voice (PROVISIONAL - a CTR-curve estimate)."""
    row = await asyncio.to_thread(repo.competitor_stats, client_id=client_id)
    return CompetitorStats.from_row(row)


@router.get("/competitor-intel/workspace", response_model=ToolExtraResponse)
async def competitor_workspace(
    repo: CompetitorRepoDep, _feat: Feature, _user: ViewReports
) -> ToolExtraResponse:
    """The tool workspace (``lib/tools.ts`` ``competitor_intel`` shape): KPI tiles, the
    gap-analysis table (cols ``Competitor|Client|Keyword gaps|Overlap``), and the CTA."""
    stats_row = await asyncio.to_thread(repo.competitor_stats)
    top = await asyncio.to_thread(repo.list_competitors, limit=8, offset=0)
    return build_workspace(CompetitorStats.from_row(stats_row), top)


@router.get(
    "/competitor-intel/competitors/{code}/gaps", response_model=list[KeywordGapResponse]
)
async def competitor_gaps(
    code: str,
    repo: CompetitorRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    gap_type: Annotated[GapType | None, Query(alias="gapType")] = None,
) -> list[KeywordGapResponse]:
    """One competitor's analysed keyword gaps, best opportunity first.

    A ``clientPosition`` of ``null`` is the PURE gap - the client does not rank for the
    term at all - and is the most valuable row here, never "position 0".
    """
    existing = await asyncio.to_thread(repo.get_by_code, code)
    if existing is None:
        raise _COMPETITOR_NOT_FOUND
    rows = await asyncio.to_thread(
        repo.list_gaps,
        str(existing["id"]),
        gap_type=gap_type,
        limit=page.limit,
        offset=page.offset,
    )
    return [KeywordGapResponse.from_row(r) for r in rows]


@router.get(
    "/competitor-intel/competitors/{code}/backlink-gaps",
    response_model=list[BacklinkGapResponse],
)
async def backlink_gaps(
    code: str,
    repo: CompetitorRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
) -> list[BacklinkGapResponse]:
    """Referring domains that link to this client's tracked competitors but not to the
    client, ranked by how many of those rivals they link to.

    ZERO provider cost: this reads the EXISTING 0018 ``backlinks`` ledger (which 0037
    gave the competitor dimension it lacked) and makes no external call at all.

    Returns an empty set until a competitor-side backlink ingest exists - see
    ``repo.backlink_gaps``, which documents exactly why that empty answer is the honest
    one rather than a stand-in built from other clients' link profiles.
    """
    existing = await asyncio.to_thread(repo.get_by_code, code)
    if existing is None:
        raise _COMPETITOR_NOT_FOUND
    rows = await asyncio.to_thread(
        repo.backlink_gaps, str(existing["client_id"]), limit=page.limit
    )
    return [
        BacklinkGapResponse(
            ref_domain=str(r.get("ref_domain", "") or ""),
            competitors=int(r.get("competitors", 0) or 0),
            authority=int(r.get("authority", 0) or 0),
            spam=int(r.get("spam", 0) or 0),
        )
        for r in rows
    ]


@router.get("/competitor-intel/share-of-voice", response_model=ShareOfVoiceResponse)
async def share_of_voice_report(
    repo: CompetitorRepoDep,
    settings: SettingsDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str, Query(alias="clientId")],
) -> ShareOfVoiceResponse:
    """The client's share of voice against their TRACKED competitors.

    PROVISIONAL by construction: the split is modelled from a positional CTR curve
    (``service.DEFAULT_CTR_CURVE``, config-overridable), not measured from clicks. It
    is comparable BETWEEN the domains here - which is the claim it supports - and it is
    not a traffic estimate. The response carries the curve it used, so any number can
    be reproduced after ops re-fits it.
    """
    client_name = await asyncio.to_thread(repo.client_name_for, client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND
    return await asyncio.to_thread(
        _share_of_voice_for, repo, settings, client_id=client_id, client_name=client_name
    )


# --- mutations ----------------------------------------------------------------


@router.post(
    "/competitor-intel/competitors",
    response_model=CompetitorResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_competitor(
    body: CompetitorCreate,
    repo: CompetitorRepoDep,
    _feat: Feature,
    actor: RunResearch,
) -> CompetitorResponse:
    """Track ONE competitor for ONE client (run_research).

    The domain is NORMALISED before it is stored, so "BrightSmile.com",
    "www.brightsmile.com" and "https://brightsmile.com/x" all resolve to one row - and
    therefore one paid analysis. 404 if the client is unknown/invisible; 409 if this
    client already tracks the domain (the duplicate is refused rather than silently
    creating a second analysis of the same rival).
    """
    domain = normalize_domain(body.domain)
    if not domain:
        raise _BAD_DOMAIN

    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND

    row = await asyncio.to_thread(
        repo.add_competitor,
        client_id=body.client_id,
        client_name=client_name,
        domain=domain,
        label=body.label or "",
        source="manual",
        created_by=actor.id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"{client_name} already tracks {domain}",
        )

    await record_activity(
        actor,
        kind="client",
        action=f"started tracking competitor {domain}",
        target=client_name,
        entity_type="client",
        entity_id=body.client_id,
    )
    return CompetitorResponse.from_row(row)


@router.post(
    "/competitor-intel/discover",
    response_model=DiscoveryQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def discover(
    body: DiscoverRequest,
    repo: CompetitorRepoDep,
    _feat: Feature,
    actor: RunResearch,
    _limit: DiscoverLimit,
    enqueue: DiscoveryEnqueuerDep,
) -> DiscoveryQueued:
    """Propose competitors for ONE client from their tracked-keyword SERPs (run_research).

    ENQUEUED, not inline: one press is N paid SERP pulls (one per sampled keyword), and
    N blocking provider calls inside a request is exactly what the worker tier exists to
    absorb - the same reason the rank-tracker's on-demand check enqueues even its single
    call. The sweep is cost-gated in the worker as ONE priced unit, so a client near
    their cap is refused the whole sweep rather than walked past it one SERP at a time.

    404 if the client is unknown/invisible. Discovered rows land with
    ``discovery_source='serp_auto'`` and appear on the board.
    """
    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND

    enqueue(body.client_id)
    await record_activity(
        actor,
        kind="client",
        action="ran competitor discovery",
        target=client_name,
        entity_type="client",
        entity_id=body.client_id,
    )
    return DiscoveryQueued(client=client_name, queued=True)


@router.post(
    "/competitor-intel/competitors/{code}/analyze",
    response_model=AnalysisQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_competitor(
    code: str,
    repo: CompetitorRepoDep,
    _feat: Feature,
    actor: RunResearch,
    _limit: AnalyzeLimit,
    enqueue: AnalysisEnqueuerDep,
) -> AnalysisQueued:
    """Fire a gap analysis for ONE competitor (run_research).

    The paid ``ranked_keywords`` pull is cost-gated in the WORKER, not here - this edge
    only enqueues. The client's own positions cost nothing (they come from the Rank
    Tracker), so the only thing this run buys is the rival's side.
    """
    row = await asyncio.to_thread(repo.get_by_code, code)
    if row is None:
        raise _COMPETITOR_NOT_FOUND

    enqueue(str(row["id"]))
    await record_activity(
        actor,
        kind="client",
        action=f"ran a gap analysis against {row.get('domain', '')}",
        target=str(row.get("client_name", "") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id") or "") or None,
    )
    return AnalysisQueued(code=code, queued=True)


@router.post(
    "/competitor-intel/competitors/{code}/gaps/{gap_id}/promote",
    response_model=GapPromoted,
    status_code=status.HTTP_201_CREATED,
)
async def promote_gap(
    code: str,
    gap_id: str,
    repo: CompetitorRepoDep,
    _feat: Feature,
    actor: RunResearch,
) -> GapPromoted:
    """Push ONE gap into the 0035 keyword bank with ``source='gap'`` (run_research).

    Idempotent: the bank's ``(client, keyword, geo)`` key absorbs a re-promote and the
    gap's ``keyword_id`` is stamped, so a double-click banks one keyword and reports
    ``created=false`` rather than creating a second row. 404 if the competitor or the
    gap (under THIS competitor) is unknown.
    """
    competitor = await asyncio.to_thread(repo.get_by_code, code)
    if competitor is None:
        raise _COMPETITOR_NOT_FOUND
    gap = await asyncio.to_thread(repo.get_gap, str(competitor["id"]), gap_id)
    if gap is None:
        raise _GAP_NOT_FOUND

    result = await asyncio.to_thread(
        repo.promote_gap,
        gap_id,
        client_id=str(competitor["client_id"]),
        client_name=str(competitor.get("client_name", "") or ""),
    )
    if result is None:
        raise _GAP_NOT_FOUND
    keyword, keyword_code, created = result

    await record_activity(
        actor,
        kind="client",
        action=f"promoted the gap '{keyword}' into the keyword bank",
        target=str(competitor.get("client_name", "") or ""),
        entity_type="client",
        entity_id=str(competitor.get("client_id") or "") or None,
    )
    return GapPromoted(keyword=keyword, code=keyword_code, created=created)


@router.patch("/competitor-intel/competitors/{code}", response_model=CompetitorResponse)
async def update_competitor(
    code: str,
    body: CompetitorUpdate,
    repo: CompetitorRepoDep,
    _feat: Feature,
    actor: RunResearch,
) -> CompetitorResponse:
    """Re-configure ONE competitor (run_research): re-label it, or park/resume it.

    Parking (``tracked=false``) keeps the analysis that was already paid for but takes
    the rival OUT of the share-of-voice denominator - which is the point: a domain the
    client does not actually compete with should not dilute the split. The DOMAIN is
    deliberately not editable (see ``CompetitorUpdate``). 404 if the code is unknown;
    400 if nothing was provided.
    """
    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise _NOTHING_TO_UPDATE

    changes: dict[str, Any] = {}
    if "label" in provided and body.label is not None:
        changes["label"] = body.label
    if "tracked" in provided and body.tracked is not None:
        changes["tracked"] = body.tracked
    if not changes:
        raise _NOTHING_TO_UPDATE

    row = await asyncio.to_thread(repo.update_competitor, code, changes)
    if row is None:
        raise _COMPETITOR_NOT_FOUND

    await record_activity(
        actor,
        kind="client",
        action=f"updated competitor {row.get('domain', '')}",
        target=str(row.get("client_name", "") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id") or "") or None,
    )
    return CompetitorResponse.from_row(row)


@router.delete(
    "/competitor-intel/competitors/{code}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_competitor(
    code: str,
    repo: CompetitorRepoDep,
    _feat: Feature,
    actor: RunResearch,
) -> None:
    """Stop tracking a competitor entirely - its gaps cascade (run_research).

    NOTE: 0037 declares NO delete policy (v1 mirrors 0035/0036), so RLS refuses this
    for every app role and the call surfaces the database's refusal rather than
    pretending to have deleted anything. Parking with ``PATCH {tracked: false}`` is the
    supported way to retire a rival, and it keeps the analysis the client paid for.
    """
    row = await asyncio.to_thread(repo.get_by_code, code)
    if row is None:
        raise _COMPETITOR_NOT_FOUND

    deleted = await asyncio.to_thread(repo.delete_competitor, code)
    if not deleted:
        raise _COMPETITOR_NOT_FOUND

    await record_activity(
        actor,
        kind="client",
        action=f"stopped tracking competitor {row.get('domain', '')}",
        target=str(row.get("client_name", "") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id") or "") or None,
    )
