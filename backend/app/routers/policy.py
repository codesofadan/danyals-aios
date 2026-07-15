"""Policy Radar (Module 05) endpoints: the always-on SEO/algorithm intelligence brain.

Reads (the watched sources, detected changes, the KB, the recommendation queue)
require any provisioned staff (``view_reports`` - a portal client does NOT hold it,
so clients are 403'd out of this namespace). Driving a recommendation's status
(acknowledge / apply / dismiss) requires an owner/admin/manager (the leads), matching
the ``recommendations`` RLS so the app-layer 403 and the DB boundary agree.

Responses are the frontend ``policy.ts`` shapes. Every mutation offloads the blocking
psycopg call with ``asyncio.to_thread`` and records an activity entry.

DEFERRED (later chunks, by design): the change-detection WATCHER that fills sources /
changes / KB, and the CLOSED LOOP an 'applied' recommendation writes to (an audit /
content-guidance overlay). See the ``apply`` branch below - and the Part-3 HARD RULE:
the ``danyals-audit-system`` engine is NEVER mutated; the overlay is separate.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.pagination import PageDep
from app.db.policy_repo import PolicyRepoDep
from app.schemas.policy import (
    ChangeEventResponse,
    KBEntryResponse,
    RecommendationAction,
    RecommendationResponse,
    SourceResponse,
    action_to_status,
)
from app.services.activity import record_activity

router = APIRouter(tags=["policy"])

# All six staff roles hold view_reports; a portal client does NOT (mirrors tasks.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Driving a recommendation = the leads (owner/admin/manager); owner auto-passes.
ManageRecs = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

# The activity verb for each recommendation transition.
_ACTION_VERB: dict[str, str] = {
    "acknowledge": "acknowledged a policy update",
    "apply": "applied a policy recommendation",
    "dismiss": "dismissed a policy recommendation",
}


@router.get("/policy/sources", response_model=list[SourceResponse])
async def list_sources(repo: PolicyRepoDep, page: PageDep, _user: ViewReports) -> list[SourceResponse]:
    """List the watched sources (newest first). ``lastChecked`` is "never" until the
    watcher's first poll (deferred chunk)."""
    rows = await asyncio.to_thread(repo.list_sources, limit=page.limit, offset=page.offset)
    return [SourceResponse.from_row(r) for r in rows]


@router.get("/policy/changes", response_model=list[ChangeEventResponse])
async def list_changes(
    repo: PolicyRepoDep, page: PageDep, _user: ViewReports
) -> list[ChangeEventResponse]:
    """List detected change events (newest detection first)."""
    rows = await asyncio.to_thread(repo.list_changes, limit=page.limit, offset=page.offset)
    return [ChangeEventResponse.from_row(r) for r in rows]


@router.get("/policy/kb", response_model=list[KBEntryResponse])
async def list_kb(
    repo: PolicyRepoDep,
    page: PageDep,
    _user: ViewReports,
    severity: Annotated[str | None, Query()] = None,
    category: Annotated[str | None, Query()] = None,
    region: Annotated[str | None, Query()] = None,
) -> list[KBEntryResponse]:
    """List KB entries (newest first), optionally filtered on any of the 3 axes
    (severity / category / region)."""
    rows = await asyncio.to_thread(
        repo.list_kb,
        severity=severity,
        category=category,
        region=region,
        limit=page.limit,
        offset=page.offset,
    )
    return [KBEntryResponse.from_row(r) for r in rows]


@router.get("/policy/recommendations", response_model=list[RecommendationResponse])
async def list_recommendations(
    repo: PolicyRepoDep,
    page: PageDep,
    _user: ViewReports,
    rec_status: Annotated[str | None, Query(alias="status")] = None,
) -> list[RecommendationResponse]:
    """List recommendations - the DB rows merged with the evergreen baseline recs so
    the Command Center is never empty pre-live. An explicit ``status`` filter scopes
    to DB rows in that state (baseline recs are omitted then)."""
    rows = await asyncio.to_thread(
        repo.list_recommendations, status=rec_status, limit=page.limit, offset=page.offset
    )
    return [RecommendationResponse.from_row(r) for r in rows]


@router.post(
    "/policy/recommendations/{rec_id}/{action}", response_model=RecommendationResponse
)
async def transition_recommendation(
    rec_id: str,
    action: RecommendationAction,
    repo: PolicyRepoDep,
    actor: ManageRecs,
) -> RecommendationResponse:
    """Drive a recommendation's status (leads only). ``acknowledge`` -> acknowledged,
    ``apply`` -> applied, ``dismiss`` -> dismissed. A baseline rec is materialized into
    the DB on its first transition so the decision persists.

    R3 / TODO (LATER CHUNK): ``apply`` currently only sets status='applied' + records
    activity. The CLOSED LOOP - writing the recommendation into an ``audit_overlay`` /
    content-guidance overlay so the change actually reaches the modules - lands in a
    later chunk. Part-3 HARD RULE: that overlay is SEPARATE; the ``danyals-audit-system``
    engine is NEVER mutated.
    """
    new_status = action_to_status(action)
    updated = await asyncio.to_thread(repo.transition_recommendation, rec_id, new_status)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found"
        )
    await record_activity(
        actor,
        kind="content",
        action=_ACTION_VERB[action],
        target=updated.get("title", ""),
    )
    return RecommendationResponse.from_row(updated)
