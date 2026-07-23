"""Policy Radar (Module 05) endpoints: the always-on SEO/algorithm intelligence brain.

Reads (the watched sources, detected changes, the KB, the recommendation queue)
require any provisioned staff (``view_reports`` - a portal client does NOT hold it,
so clients are 403'd out of this namespace). Driving a recommendation's status
(acknowledge / apply / dismiss) requires an owner/admin/manager (the leads), matching
the ``recommendations`` RLS so the app-layer 403 and the DB boundary agree.

Responses are the frontend ``policy.ts`` shapes. Every mutation offloads the blocking
psycopg call with ``asyncio.to_thread`` and records an activity entry.

R3 CLOSED LOOP (7C-3): an ``apply`` now writes the recommendation into an
``audit_overlay`` row (``app/services/policy_radar.py``) that the presentation layer
lays ON TOP of the untouched engine output. Part-3 HARD RULE: the
``danyals-audit-system`` engine is NEVER mutated; the overlay is SEPARATE. Staff can
read the active overlay via ``GET /policy/overlay``.

DEFERRED (later chunk, by design): the change-detection WATCHER that fills sources /
changes / KB.
"""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.db.policy_repo import PolicyRepoDep
from app.schemas.policy import (
    ChangeEventResponse,
    KBEntryResponse,
    OverlayResponse,
    PolicyAskRequest,
    PolicyAskResponse,
    RecommendationAction,
    RecommendationResponse,
    SourceResponse,
    action_to_status,
)
from app.services.activity import record_activity
from app.services.cost_gate import CostGate
from app.services.policy_ask import (
    build_ask_gate,
    build_ask_searcher,
    build_ask_summarizer,
    run_policy_ask,
)
from app.services.policy_radar import apply_recommendation
from app.services.policy_watch import PolicyFetcher, SsrfGuardedPolicyFetcher
from integrations.content_research import SerpResearcher
from integrations.llm import Summarizer

router = APIRouter(tags=["policy"])

# All six staff roles hold view_reports; a portal client does NOT (mirrors tasks.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Driving a recommendation = the leads (owner/admin/manager); owner auto-passes.
ManageRecs = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]


# --- on-demand lookup seams (injected so tests swap in fakes) ---------------- #
def get_ask_searcher(settings: SettingsDep) -> SerpResearcher | None:
    """Dependency: the key-gated Serper researcher (or ``None`` degraded). Overridable in tests."""
    return build_ask_searcher(settings)


def get_ask_summarizer(settings: SettingsDep) -> Summarizer | None:
    """Dependency: the key-gated Haiku summarizer (or ``None`` degraded). Overridable in tests."""
    return build_ask_summarizer(settings)


def get_ask_fetcher() -> PolicyFetcher:
    """Dependency: the SSRF-guarded page fetcher (re-validated every redirect hop)."""
    return SsrfGuardedPolicyFetcher()


def get_ask_gate() -> CostGate:
    """Dependency: the real cost gate over the Postgres store. Overridable in tests."""
    return build_ask_gate()


AskSearcherDep = Annotated[SerpResearcher | None, Depends(get_ask_searcher)]
AskSummarizerDep = Annotated[Summarizer | None, Depends(get_ask_summarizer)]
AskFetcherDep = Annotated[PolicyFetcher, Depends(get_ask_fetcher)]
AskGateDep = Annotated[CostGate, Depends(get_ask_gate)]

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


@router.post("/policy/ask", response_model=PolicyAskResponse)
async def policy_ask(
    body: PolicyAskRequest,
    _user: ViewReports,
    settings: SettingsDep,
    searcher: AskSearcherDep,
    summarizer: AskSummarizerDep,
    fetcher: AskFetcherDep,
    gate: AskGateDep,
) -> PolicyAskResponse:
    """On-demand policy lookup (staff-gated). Runs a live Serper search scoped to
    Google's official surfaces, SSRF-guarded-fetches the top authoritative result, and
    has Claude Haiku distil a structured answer (a concise answer, an urgency label, the
    key rules, and source URLs).

    Both paid calls (Serper + Haiku) are metered under the EXISTING ``policy`` money-dial;
    a missing key or a dial/budget block DEGRADES (200, ``status='degraded'``) rather than
    crashing, and the gate is never bypassed. The blocking search / fetch / summarize + the
    sync gate store run off the event loop via ``to_thread``."""

    def _run() -> PolicyAskResponse:
        result = run_policy_ask(
            body.topic,
            searcher=searcher,
            fetcher=fetcher,
            summarizer=summarizer,
            gate=gate,
            settings=settings,
        )
        return PolicyAskResponse(
            topic=result.topic,
            status=result.status,  # type: ignore[arg-type]
            answer=result.answer,
            urgency=result.urgency,  # type: ignore[arg-type]
            rules=result.rules,
            sources=result.sources,
            reason=result.reason,
        )

    return await asyncio.to_thread(_run)


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

    R3 CLOSED LOOP: an ``apply`` ALSO writes the (now-materialized) recommendation
    into an ``audit_overlay`` row via ``apply_recommendation`` - the change the
    presentation layer lays ON TOP of the untouched engine. Part-3 HARD RULE: that
    overlay is SEPARATE; the ``danyals-audit-system`` engine is NEVER mutated. The
    human CONFIRM is the ``require_role`` on this route (owner/admin/manager).
    """
    new_status = action_to_status(action)
    updated = await asyncio.to_thread(repo.transition_recommendation, rec_id, new_status)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Recommendation not found"
        )
    if action == "apply":
        # Close the loop: the applied rec becomes an overlay laid on top of the
        # UNTOUCHED engine (never a mutation of danyals-audit-system).
        await apply_recommendation(actor, updated, repo)
    await record_activity(
        actor,
        kind="content",
        action=_ACTION_VERB[action],
        target=updated.get("title", ""),
    )
    return RecommendationResponse.from_row(updated)


@router.get("/policy/overlay", response_model=list[OverlayResponse])
async def list_overlay(
    repo: PolicyRepoDep,
    page: PageDep,
    _user: ViewReports,
    target: Annotated[str | None, Query()] = None,
    audit_type: Annotated[str | None, Query(alias="auditType")] = None,
    region: Annotated[str | None, Query()] = None,
) -> list[OverlayResponse]:
    """The ACTIVE closed-loop overlay rows (newest first) - what an ``apply``
    produced, laid ON TOP of the untouched engine by the presentation layer.
    Optionally scoped to a target module / a keyed audit type / a region."""
    rows = await asyncio.to_thread(
        repo.list_active_overlay,
        target_module=target,
        audit_type=audit_type,
        region=region,
        limit=page.limit,
        offset=page.offset,
    )
    return [OverlayResponse.from_row(r) for r in rows]
