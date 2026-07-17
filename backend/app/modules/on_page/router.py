"""On-page optimizer endpoints (Part 8 Phase 2D): review + APPLY on-page fixes.

No ``frontend/lib/*.ts`` type mirrors this module - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape/enum tests). The
``GET /on-page/workspace`` adapter emits the ``lib/tools.ts`` ``on_page`` EXTRA shape
(KPIs + the recommendation table + the CTA), with table columns pinned to
``tests/test_tool_workspace_contract.py``.

Tables owned: ``onpage_analyses`` / ``page_recommendations`` (migration
``0038_on_page``). Cost-gate dial: ``on_page`` (the SERP pull that feeds the content
score's entity-coverage dimension; the analysis worker gates on it and DEGRADES to
deterministic-only scoring when blocked).

Access: every route requires the ``on_page`` FEATURE grant. Reads add ``view_reports``;
queueing an analysis adds ``run_audits`` (it only READS the client's page - it changes
nothing). **Everything that touches the live site - apply, apply-bulk, revert, and the
re-analyze re-arm - is LEAD-only** (owner/admin/manager), which lines up with the 0038
RLS policies + the ``onpage_guard_update`` trigger byte-for-byte: the database refuses
a recommendation write that is not lead-attributed, so the app gate and Postgres agree
and a caller can never pass one and be rejected by the other with an opaque error.

THE APPLY IS DELIBERATELY SYNCHRONOUS. It is a live-site write, and the lead who
clicked it must SEE what happened - the 409 when the page drifted under us, the
``held`` when the SEO-plugin bridge is missing. Fire-and-forget would hide exactly the
outcomes that matter. (``tasks.py`` still exposes lead-attributed Celery entry points
for a future batch surface.)

The internal ``client_id`` never leaks (``client`` is the snapshotted name); every
mutation offloads the blocking psycopg call with ``asyncio.to_thread`` and records an
activity entry (kind=content, entity=client) so on-page work keeps each client's
context fresh.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import Settings, get_settings
from app.core import security
from app.core.auth import CurrentUser, require_feature, require_perm, require_role
from app.core.pagination import PageDep
from app.core.security import PrivateAddressError
from app.modules.on_page.repo import OnPageRepo, OnPageRepoDep, get_on_page_repo
from app.modules.on_page.schemas import (
    AnalysisQueuedResponse,
    AnalysisResponse,
    AnalyzeRequest,
    ApplyBulkRequest,
    ApplyBulkResponse,
    ApplyRequest,
    ApplyResultResponse,
    Impact,
    OnPageStats,
    RecommendationDetail,
    RecommendationResponse,
    RecStatus,
)
from app.modules.on_page.service import MANUAL_FIX_KIND, build_workspace
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.activity import record_activity

if TYPE_CHECKING:  # the apply cores are imported LAZILY (see get_fix_applier)
    from app.modules.on_page.tasks import ApplyOutcome

router = APIRouter(tags=["on-page"])

# Every route requires the fine-grained on_page feature grant (owner is all-on). Reads
# add view_reports; queueing an analysis adds run_audits. Every LIVE-SITE action is
# Lead-only, mirroring the 0038 RLS write policies + the guard trigger exactly.
Feature = Annotated[CurrentUser, Depends(require_feature("on_page"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
RunAudits = Annotated[CurrentUser, Depends(require_perm("run_audits"))]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]
SettingsDep = Annotated[Settings, Depends(get_settings)]

_REC_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found")
_ANALYSIS_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Analysis not found")
_CLIENT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
_MANUAL_FIX = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="This fix is manual - a human must make this change; it cannot be applied automatically",
)
_ALREADY_QUEUED = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Analysis is already running"
)


def get_analysis_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the on-page analysis worker (overridable in tests).

    The Celery task is imported lazily so the API process never pulls in the task
    module just to import this router (mirrors ``get_research_enqueuer``)."""

    def _enqueue(code: str) -> None:
        from app.modules.on_page.tasks import analyze_page

        analyze_page.delay(code)

    return _enqueue


AnalysisEnqueuerDep = Annotated[Callable[[str], None], Depends(get_analysis_enqueuer)]

# The apply/revert CORES, injected. Two reasons, both load-bearing:
#   * ``tasks.py`` imports the Celery app, so importing it at module scope would drag
#     Celery into the API process merely to import this router (the same reason
#     ``get_analysis_enqueuer`` imports its task lazily).
#   * It gives the router a seam, so its own job - the gates, the confirm contract,
#     the 409 mapping - is testable without a WordPress or a broker.
FixRunner = Callable[..., "ApplyOutcome"]


def get_fix_applier() -> FixRunner:
    """Dependency: the apply core (lazily imported; overridable in tests)."""
    from app.modules.on_page.tasks import execute_apply

    return execute_apply


def get_fix_reverter() -> FixRunner:
    """Dependency: the revert core (lazily imported; overridable in tests)."""
    from app.modules.on_page.tasks import execute_revert

    return execute_revert


FixApplierDep = Annotated[FixRunner, Depends(get_fix_applier)]
FixReverterDep = Annotated[FixRunner, Depends(get_fix_reverter)]


async def _guard_public_url(url: str) -> None:
    """SSRF pre-check at the EDGE, before anything is queued.

    ``validate_public_host`` BLOCKS on DNS (``socket.getaddrinfo``), so it is offloaded
    with ``asyncio.to_thread`` per its caller contract - never called on the event
    loop. Called through the ``security`` MODULE (not a bound name) so the guard is
    resolved per call.

    This is a fail-fast for the operator's benefit; it is NOT the security boundary (a
    host can be re-pointed between here and the fetch - the TOCTOU the guard's own
    caller contract warns about), so the worker re-validates EVERY hop of the real
    fetch regardless.
    """
    try:
        await asyncio.to_thread(security.validate_public_host, url)
    except PrivateAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unreachable page URL: {exc}"
        ) from exc


def _client_entity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    client_id = row.get("client_id")
    return ("client", str(client_id)) if client_id is not None else (None, None)


# --- reads --------------------------------------------------------------------


@router.get("/on-page/recommendations", response_model=list[RecommendationResponse])
async def list_recommendations(
    repo: OnPageRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    analysis: Annotated[str | None, Query()] = None,
    status_: Annotated[RecStatus | None, Query(alias="status")] = None,
    impact: Annotated[Impact | None, Query()] = None,
    issue_code: Annotated[str | None, Query(alias="issueCode")] = None,
    quick_win: Annotated[bool | None, Query(alias="quickWin")] = None,
) -> list[RecommendationResponse]:
    """The recommendation board (best Impact x Effort first). Filters narrow it by
    client, analysis (the OP-#### code), status, impact, issue, or quick-win."""
    rows = await asyncio.to_thread(
        repo.list_recommendations,
        client_id=client_id,
        analysis_code=analysis,
        status=status_,
        impact=impact,
        issue_code=issue_code,
        quick_win=quick_win,
        limit=page.limit,
        offset=page.offset,
    )
    return [RecommendationResponse.from_row(r) for r in rows]


@router.get("/on-page/analyses", response_model=list[AnalysisResponse])
async def list_analyses(
    repo: OnPageRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[AnalysisResponse]:
    """The analysed pages (newest first) with their open/applied tallies."""
    rows = await asyncio.to_thread(
        repo.list_analyses,
        client_id=client_id, status=status_, limit=page.limit, offset=page.offset,
    )
    return [AnalysisResponse.from_row(r) for r in rows]


@router.get("/on-page/stats", response_model=OnPageStats)
async def on_page_stats(repo: OnPageRepoDep, _feat: Feature, _user: ViewReports) -> OnPageStats:
    """The board summary tiles: pages analysed, open suggestions, applied."""
    row = await asyncio.to_thread(repo.stats)
    return OnPageStats.from_row(row)


@router.get("/on-page/workspace", response_model=ToolExtraResponse)
async def on_page_workspace(
    repo: OnPageRepoDep, _feat: Feature, _user: ViewReports
) -> ToolExtraResponse:
    """The tool workspace (``lib/tools.ts`` ``on_page`` shape): KPI tiles, the top
    recommendation table (cols ``Page|Issue|Impact|Status``), and the CTA."""
    stats_row = await asyncio.to_thread(repo.stats)
    top = await asyncio.to_thread(repo.list_recommendations, limit=8, offset=0)
    return build_workspace(OnPageStats.from_row(stats_row), top)


@router.get("/on-page/recommendations/{rec_id}", response_model=RecommendationDetail)
async def get_recommendation(
    rec_id: str, repo: OnPageRepoDep, _feat: Feature, _user: ViewReports
) -> RecommendationDetail:
    """The preview/diff for ONE recommendation: ``current`` (the value live on the
    page when we analysed it) vs ``proposed`` (what an apply would write), plus the
    detector's evidence. This is what a lead reads BEFORE authorising a live write."""
    row = await asyncio.to_thread(repo.get_recommendation, rec_id)
    if row is None:
        raise _REC_NOT_FOUND
    return RecommendationDetail.from_row(row)


# --- analysis -----------------------------------------------------------------


@router.post(
    "/on-page/analyze",
    response_model=AnalysisQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze(
    body: AnalyzeRequest,
    repo: OnPageRepoDep,
    _feat: Feature,
    actor: RunAudits,
    enqueue: AnalysisEnqueuerDep,
) -> AnalysisQueuedResponse:
    """Queue ONE page for analysis (run_audits - this only READS the page).

    Validates the client (404 if unknown/invisible) and SSRF-checks the URL off the
    event loop before anything is queued, snapshots the client name, inserts the
    queued analysis, and hands off to the worker."""
    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND
    await _guard_public_url(body.page_url)

    row = await asyncio.to_thread(
        repo.create_analysis,
        client_id=body.client_id,
        client_name=client_name,
        site_id=body.site_id,
        page_url=body.page_url,
        target_keyword=body.target_keyword,
        source_audit_id=body.source_audit_id,
        created_by=actor.id,
    )
    if row is None:  # pragma: no cover - `returning *` always yields the row
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Analysis could not be created"
        )
    code = str(row["code"])
    enqueue(code)
    await record_activity(
        actor, kind="content", action=f"queued an on-page analysis of {body.page_url}",
        target=client_name, entity_type="client", entity_id=body.client_id,
    )
    return AnalysisQueuedResponse(code=code, queued=True)


@router.post(
    "/on-page/analyze/{code}/re-analyze",
    response_model=AnalysisQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def re_analyze(
    code: str, repo: OnPageRepoDep, _feat: Feature, actor: Lead, enqueue: AnalysisEnqueuerDep
) -> AnalysisQueuedResponse:
    """Re-arm an analysis and run it again (LEAD-only).

    Lead-only because it is a WRITE to the analysis lifecycle, and the 0038 guard
    gives no non-lead any legal transition there - gating it on ``run_audits`` would
    let a specialist pass the app gate only to hit an opaque database error.

    409 unless the analysis has settled (done/failed/held) - the optimistic
    ``expect_status`` also makes a double-click a clean 409 rather than two workers
    racing on one page. Still-``open`` recommendations are rebuilt by the worker;
    applied/dismissed ones are the record of what a human decided and are preserved.
    """
    existing = await asyncio.to_thread(repo.get_analysis_by_code, code)
    if existing is None:
        raise _ANALYSIS_NOT_FOUND
    current = str(existing.get("status") or "")
    if current not in ("done", "failed", "held"):
        raise _ALREADY_QUEUED

    updated = await asyncio.to_thread(
        repo.update_analysis, code, {"status": "queued", "error": None}, current
    )
    if updated is None:
        # A racing transition already moved the row (optimistic concurrency), or the
        # DB guard rejected it (defence in depth) - either way it is no longer ours.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Analysis changed concurrently"
        )
    enqueue(code)
    ent_type, ent_id = _client_entity(existing)
    await record_activity(
        actor, kind="content", action=f"re-ran the on-page analysis {code}",
        target=str(existing.get("client_name", "") or ""),
        entity_type=ent_type, entity_id=ent_id,
    )
    return AnalysisQueuedResponse(code=code, queued=True)


# --- the live-site mutations (LEAD-only) --------------------------------------


@router.post("/on-page/recommendations/{rec_id}/apply", response_model=ApplyResultResponse)
async def apply_recommendation(
    rec_id: str,
    body: ApplyRequest,
    repo: OnPageRepoDep,
    settings: SettingsDep,
    run_apply: FixApplierDep,
    _feat: Feature,
    actor: Lead,
) -> ApplyResultResponse:
    """APPLY one recommendation TO THE CLIENT'S LIVE SITE (LEAD-only).

    ``{"confirm": true}`` is mandatory - ``ApplyRequest.confirm`` is ``Literal[True]``,
    so a body without it is a 422 from Pydantic before this function runs. A ``manual``
    fix is a 422 (a human must make that change). A page that DRIFTED since the
    analysis is a **409**: applying would overwrite whoever hand-edited it, so we
    refuse unless the lead passes ``force``. An already-applied recommendation is a
    no-op, not a second write.

    Runs synchronously on the acting lead's RLS identity: the 0038 guard requires a
    live-site write to be lead-attributed, and the caller needs to see the verdict.
    """
    row = await asyncio.to_thread(repo.get_recommendation, rec_id)
    if row is None:
        raise _REC_NOT_FOUND
    if str(row.get("fix_kind")) == MANUAL_FIX_KIND:
        raise _MANUAL_FIX

    outcome = await asyncio.to_thread(
        run_apply, repo, rec_id,
        actor_id=actor.id, settings=settings, force=body.force,
    )
    if outcome.state == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=outcome.reason)

    updated = await asyncio.to_thread(repo.get_recommendation, rec_id)
    if outcome.state == "applied":
        ent_type, ent_id = _client_entity(row)
        await record_activity(
            actor, kind="content",
            action=f"applied an on-page fix ({row.get('issue_code')}) to {row.get('page_url')}",
            target=str(row.get("client_name", "") or ""),
            entity_type=ent_type, entity_id=ent_id,
        )
    return ApplyResultResponse(
        id=rec_id, state=outcome.state, reason=outcome.reason,
        recommendation=RecommendationResponse.from_row(updated) if updated else None,
    )


@router.post("/on-page/recommendations/apply-bulk", response_model=ApplyBulkResponse)
async def apply_bulk(
    body: ApplyBulkRequest,
    repo: OnPageRepoDep,
    settings: SettingsDep,
    run_apply: FixApplierDep,
    _feat: Feature,
    actor: Lead,
) -> ApplyBulkResponse:
    """Apply MANY recommendations to live sites in one call (LEAD-only).

    Same mandatory ``{"confirm": true}`` contract as the single apply. Unlike it, a
    ``manual`` fix or a drifted page does NOT abort the batch: each id gets its own
    honest verdict (``skipped`` / ``blocked`` / ``held``) and the rest still apply -
    one un-appliable id must not strand the other nineteen. Unknown ids come back as
    ``failed`` rather than 404-ing the whole request.
    """
    results: list[ApplyResultResponse] = []
    applied = 0
    for rec_id in body.ids:
        row = await asyncio.to_thread(repo.get_recommendation, rec_id)
        if row is None:
            results.append(ApplyResultResponse(id=rec_id, state="failed", reason="not found"))
            continue
        if str(row.get("fix_kind")) == MANUAL_FIX_KIND:
            results.append(
                ApplyResultResponse(
                    id=rec_id, state="skipped",
                    reason="manual fixes must be made by a human",
                )
            )
            continue
        outcome = await asyncio.to_thread(
            run_apply, repo, rec_id,
            actor_id=actor.id, settings=settings, force=body.force,
        )
        if outcome.state == "applied":
            applied += 1
        results.append(
            ApplyResultResponse(id=rec_id, state=outcome.state, reason=outcome.reason)
        )
    if applied:
        await record_activity(
            actor, kind="content", action=f"applied {applied} on-page fixes",
            target="", entity_type=None, entity_id=None,
        )
    return ApplyBulkResponse(
        applied=applied, skipped=len(results) - applied, results=results
    )


@router.post("/on-page/recommendations/{rec_id}/revert", response_model=ApplyResultResponse)
async def revert_recommendation(
    rec_id: str,
    body: ApplyRequest,
    repo: OnPageRepoDep,
    settings: SettingsDep,
    run_revert: FixReverterDep,
    _feat: Feature,
    actor: Lead,
) -> ApplyResultResponse:
    """REVERT one applied recommendation ON THE LIVE SITE (LEAD-only).

    Same mandatory ``{"confirm": true}`` contract - a rollback is a live write too.
    Drift-guarded in its own right: if the page changed AFTER we applied, restoring
    our snapshot would clobber that later edit, so it 409s unless forced.
    """
    row = await asyncio.to_thread(repo.get_recommendation, rec_id)
    if row is None:
        raise _REC_NOT_FOUND

    outcome = await asyncio.to_thread(
        run_revert, repo, rec_id,
        actor_id=actor.id, settings=settings, force=body.force,
    )
    if outcome.state == "blocked":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=outcome.reason)

    updated = await asyncio.to_thread(repo.get_recommendation, rec_id)
    if outcome.state == "reverted":
        ent_type, ent_id = _client_entity(row)
        await record_activity(
            actor, kind="content",
            action=f"reverted an on-page fix ({row.get('issue_code')}) on {row.get('page_url')}",
            target=str(row.get("client_name", "") or ""),
            entity_type=ent_type, entity_id=ent_id,
        )
    return ApplyResultResponse(
        id=rec_id, state=outcome.state, reason=outcome.reason,
        recommendation=RecommendationResponse.from_row(updated) if updated else None,
    )


@router.post("/on-page/recommendations/{rec_id}/dismiss", response_model=RecommendationResponse)
async def dismiss_recommendation(
    rec_id: str, repo: OnPageRepoDep, _feat: Feature, actor: Lead
) -> RecommendationResponse:
    """Dismiss a recommendation (LEAD-only): we are deliberately not doing this one.

    Touches nothing on the live site. 409 unless it is still ``open`` (optimistic
    ``expect_status``), so dismissing something a colleague just applied is a clean
    conflict rather than a silent overwrite of their decision.
    """
    from datetime import UTC, datetime

    row = await asyncio.to_thread(repo.get_recommendation, rec_id)
    if row is None:
        raise _REC_NOT_FOUND

    updated = await asyncio.to_thread(
        repo.update_recommendation,
        rec_id,
        {"status": "dismissed", "dismissed_at": datetime.now(UTC), "dismissed_by": actor.id},
        "open",
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Recommendation changed concurrently"
        )
    ent_type, ent_id = _client_entity(row)
    await record_activity(
        actor, kind="content",
        action=f"dismissed an on-page recommendation ({row.get('issue_code')})",
        target=str(row.get("client_name", "") or ""),
        entity_type=ent_type, entity_id=ent_id,
    )
    return RecommendationResponse.from_row(updated)


__all__ = [
    "OnPageRepo",
    "get_analysis_enqueuer",
    "get_fix_applier",
    "get_fix_reverter",
    "get_on_page_repo",
    "router",
]
