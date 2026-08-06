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
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.config import get_settings
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
    PolicyGenerateResponse,
    PolicyResetResponse,
    RecommendationAction,
    RecommendationResponse,
    SourceResponse,
    action_to_status,
)
from app.services.activity import record_activity
from app.services.cost_gate import CostGate
from app.services.policy_ask import (
    build_ask_gate,
    build_ask_summarizer,
    run_policy_ask,
)
from app.services.policy_radar import apply_recommendation
from integrations.llm import SystemSummarizer

router = APIRouter(tags=["policy"])

# All six staff roles hold view_reports; a portal client does NOT (mirrors tasks.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Driving a recommendation = the leads (owner/admin/manager); owner auto-passes.
ManageRecs = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]


# --- on-demand lookup seams (injected so tests swap in fakes) ---------------- #
def get_ask_summarizer() -> SystemSummarizer | None:
    """Dependency: the key-gated pure-generation summarizer (or ``None`` degraded). Overridable in tests."""
    return build_ask_summarizer(get_settings())


def get_ask_gate() -> CostGate:
    """Dependency: the real cost gate over the Postgres store. Overridable in tests."""
    return build_ask_gate()


AskSummarizerDep = Annotated[SystemSummarizer | None, Depends(get_ask_summarizer)]
AskGateDep = Annotated[CostGate, Depends(get_ask_gate)]


# --- daily-generator seams (injected so tests swap in fakes) ----------------- #
def get_policy_generator() -> Callable[[bool], None]:
    """Dependency: enqueue the daily-brief generator task (``force=True`` for a manual run
    past the once-per-day guard). Imports the Celery task LAZILY so the API process never
    pulls the worker module in just to enqueue. Overridable in tests."""

    def _enqueue(force: bool) -> None:
        from workers.tasks.policy import generate_policy_daily

        generate_policy_daily.delay(force=force)

    return _enqueue


def get_policy_reset() -> Callable[[], dict[str, int]]:
    """Dependency: the privileged Policy-Radar feed reset (clears the retired scrape data),
    returning the per-table row counts. Overridable in tests."""

    def _reset() -> dict[str, int]:
        from app.db.policy_watch_repo import service_policy_watch_repo

        return service_policy_watch_repo().clear_policy_feed()

    return _reset


PolicyGeneratorDep = Annotated[Callable[[bool], None], Depends(get_policy_generator)]
PolicyResetDep = Annotated[Callable[[], dict[str, int]], Depends(get_policy_reset)]

# Manual generation spends on a paid provider, so it is a lead action (owner/admin/manager);
# the destructive feed reset is owner-only.
ManageGenerate = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]
OwnerOnly = Annotated[CurrentUser, Depends(require_role("owner"))]

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
    summarizer: AskSummarizerDep,
    gate: AskGateDep,
) -> PolicyAskResponse:
    """On-demand policy lookup (staff-gated). Claude answers the topic with PURE Cloud-API
    generation (the Anthropic Messages API, NO web search) from its OWN current expert
    knowledge, returning a structured answer (a concise answer, an urgency label, the key
    rules, and any authoritative source URLs it can cite from knowledge).

    The single paid call is metered under the EXISTING ``policy`` money-dial (the committed
    spend is the Anthropic token cost ONLY - no web-search cost); a missing key, a dial/budget
    block, or a generation failure DEGRADES (200, ``status='degraded'``) rather than crashing,
    and the gate is never bypassed. The blocking Anthropic call + the sync gate store run off
    the event loop via ``to_thread``."""

    def _run() -> PolicyAskResponse:
        result = run_policy_ask(
            body.topic,
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


@router.post("/policy/generate", response_model=PolicyGenerateResponse)
async def generate_policy_brief(
    actor: ManageGenerate, enqueue: PolicyGeneratorDep
) -> PolicyGenerateResponse:
    """Trigger the Anthropic daily-brief generator NOW (leads only). Enqueues the SAME task
    the daily beat runs, forcing a fresh run past the once-per-day guard, so an operator can
    refresh the day's policies on demand. Returns immediately - the items land async in the
    KB / change-events / recommendations the panels already read."""
    await asyncio.to_thread(enqueue, True)
    await record_activity(
        actor, kind="content", action="generated the daily policy brief", target="Policy Radar"
    )
    return PolicyGenerateResponse(queued=True)


@router.post("/policy/reset", response_model=PolicyResetResponse)
async def reset_policy_feed(actor: OwnerOnly, reset: PolicyResetDep) -> PolicyResetResponse:
    """Clear the retired Google-scrape Policy-Radar data (owner only): every change event,
    KB entry, and NON-baseline recommendation. The evergreen baseline recs survive. Run once
    when switching the feed onto the Anthropic generator, or to start the brief clean."""
    counts = await asyncio.to_thread(reset)
    await record_activity(
        actor, kind="content", action="reset the Policy Radar feed", target="Policy Radar"
    )
    return PolicyResetResponse(
        change_events=counts.get("change_events", 0),
        kb_entries=counts.get("kb_entries", 0),
        recommendations=counts.get("recommendations", 0),
    )


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
