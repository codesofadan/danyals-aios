"""Rank-tracker module endpoints (Part 8 Phase 2B): the tracked-keyword board.

No ``frontend/lib/*.ts`` type mirrors this module - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape/enum tests). The
``GET /rank-tracker/workspace`` adapter emits the ``lib/tools.ts`` ``rank_tracker``
EXTRA shape (KPIs + the movements table + the CTA), with table columns pinned to
``tests/test_tool_workspace_contract.py``.

Tables owned: ``tracked_keywords`` / ``keyword_rankings`` (migration
``0036_rank_tracker``). Cost-gate dial: ``rank_tracker`` - its OWN money dial, because
this is the platform's first STANDING per-client spend and ops must be able to throttle
recurring rank checks without touching audits or content.

Access: every route requires the ``rank_tracker`` FEATURE grant. Reads add
``view_reports``; every mutation (each of which either creates or triggers CLIENT spend)
adds the ``run_research`` MODULE perm - held by the leads (owner/admin/manager), and
ONLY them - which lines up with the 0036 RLS insert/update policies byte-for-byte.

The internal ``client_id`` never leaks (``client`` is the snapshotted name); every
mutation offloads the blocking psycopg call with ``asyncio.to_thread`` and records an
activity entry (kind=client, entity=client) so the rank work keeps each client's
context fresh.

N-A (the contract requirement this router exists to enforce): rank tracking is a
STANDING per-client cost and the CLIENT pays, so the COMMITMENT is gated, not just each
run. ``POST /keywords`` prices the client's whole active book AS IT WOULD BE after the
add and REFUSES (402) one that would breach their remaining budget - and returns the
projection either way, so the caller sees the monthly bill it is signing up to before
the first night's checks ever run.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_feature, require_module_perm, require_perm
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.core.ratelimit import rate_limit
from app.modules.rank_tracker.provider import rank_pricing_from_settings
from app.modules.rank_tracker.repo import RankRepoDep
from app.modules.rank_tracker.schemas import (
    RankCheckQueued,
    RankCostProjection,
    RankDevice,
    RankEngine,
    RankHistoryPoint,
    RankKeywordCreate,
    RankKeywordResponse,
    RankKeywordsAdded,
    RankKeywordUpdate,
    RankStats,
)
from app.modules.rank_tracker.service import (
    apply_subscription_change,
    build_workspace,
    evaluate_projection,
    merge_cadence_counts,
    normalize_keyword,
    to_response,
)
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.activity import record_activity

router = APIRouter(tags=["rank-tracker"])

# Every tool route requires the fine-grained rank_tracker feature grant (owner is
# all-on). Reads additionally require view_reports; every mutation requires the
# run_research MODULE perm - held by the leads (owner/admin/manager), mirroring the
# 0036 RLS insert/update policies exactly. ``run_research`` is a ModulePermKey, so it
# goes through require_module_perm; require_perm would deny every non-owner role.
Feature = Annotated[CurrentUser, Depends(require_feature("rank_tracker"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
RunResearch = Annotated[CurrentUser, Depends(require_module_perm("run_research"))]

# An on-demand check is a PAID, client-billed provider call fired straight from a
# button, so it is the one route that also carries a per-user rate limit. The daily
# dedupe already stops a repeat from re-billing; this stops the hammering itself.
CheckLimit = Annotated[None, Depends(rate_limit("rank_check", limit=30, per_seconds=60))]

_KEYWORD_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Tracked keyword not found"
)
_CLIENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
)
_NOTHING_TO_UPDATE = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
)


def get_check_enqueuer() -> Callable[[str, bool], None]:
    """Dependency: enqueue the rank-check worker (overridable in tests).

    The Celery task is imported lazily so the API process never pulls in the task
    module just to import this router (mirrors ``get_research_enqueuer``)."""

    def _enqueue(keyword_id: str, force: bool) -> None:
        from app.modules.rank_tracker.tasks import check_keyword_rank

        check_keyword_rank.delay(keyword_id, force)

    return _enqueue


CheckEnqueuerDep = Annotated[Callable[[str, bool], None], Depends(get_check_enqueuer)]


def _projection_for(
    repo: Any, settings: Any, *, client_id: str, client_name: str, adding: dict[str, int] | None = None
) -> RankCostProjection:
    """Price a client's active book (optionally as it WOULD be after ``adding``).

    Blocking; the callers offload it. The per-check price comes from the CONFIGURED
    vendor, so a vendor swap re-prices the commitment automatically - and a degraded
    (keyless) deploy honestly projects $0 and says so rather than quoting a real bill
    off simulated data.

    Uses the PRICE-ONLY door: building a real provider here would open (and leak) an
    HTTP client on every add and every projection read, purely to look up a number.
    """
    pricing = rank_pricing_from_settings(settings, depth=int(settings.rank_tracker_depth))
    counts = repo.active_cadence_counts(client_id)
    if adding:
        counts = merge_cadence_counts(counts, adding)
    return evaluate_projection(
        client_name=client_name,
        cadence_counts=counts,
        cost_per_check=pricing.cost_per_check,
        budget=repo.client_budget(client_id),
        provider=pricing.provider,
        live=pricing.live,
    )


def _projection_after_change(
    repo: Any, settings: Any, existing: dict[str, Any], changes: dict[str, Any]
) -> tuple[RankCostProjection, RankCostProjection]:
    """The client's commitment BEFORE and AFTER this subscription change. Blocking."""
    client_id = str(existing.get("client_id") or "")
    client_name = str(existing.get("client_name") or "")
    pricing = rank_pricing_from_settings(settings, depth=int(settings.rank_tracker_depth))
    budget = repo.client_budget(client_id)
    before_counts = repo.active_cadence_counts(client_id)
    after_counts = apply_subscription_change(
        before_counts,
        before=(str(existing.get("status") or ""), str(existing.get("cadence") or "")),
        after=(
            str(changes.get("status", existing.get("status")) or ""),
            str(changes.get("cadence", existing.get("cadence")) or ""),
        ),
    )

    def _price(counts: dict[str, int]) -> RankCostProjection:
        return evaluate_projection(
            client_name=client_name,
            cadence_counts=counts,
            cost_per_check=pricing.cost_per_check,
            budget=budget,
            provider=pricing.provider,
            live=pricing.live,
        )

    return _price(before_counts), _price(after_counts)


async def _guard_commitment_change(
    repo: Any, settings: Any, existing: dict[str, Any], changes: dict[str, Any]
) -> None:
    """Refuse a re-configuration that would push the client's standing bill past their
    remaining budget (402).

    Only an INCREASE is refused. A client already over their cap (because ops lowered
    it, say) must still be able to pause or slow their tracking - refusing that would
    trap them over the cap with no way down, which is the opposite of a cost control.
    """
    before, after = await asyncio.to_thread(
        _projection_after_change, repo, settings, existing, changes
    )
    if not after.within_budget and after.monthly_cost > before.monthly_cost:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=after.message
        )


# --- reads --------------------------------------------------------------------


@router.get("/rank-tracker/keywords", response_model=list[RankKeywordResponse])
async def list_keywords(
    repo: RankRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    keyword_status: Annotated[str | None, Query(alias="status")] = None,
    engine: Annotated[RankEngine | None, Query()] = None,
    device: Annotated[RankDevice | None, Query()] = None,
    tag: Annotated[str | None, Query()] = None,
) -> list[RankKeywordResponse]:
    """The tracked board (best positions first, unranked last). Filters narrow it by
    client, status, engine, device or tag. Each row carries its movement since the last
    check and a ``stale`` flag when its nightly check has stalled."""
    rows = await asyncio.to_thread(
        repo.list_keywords,
        client_id=client_id,
        status=keyword_status,
        engine=engine,
        device=device,
        tag=tag,
        limit=page.limit,
        offset=page.offset,
    )
    now = datetime.now(UTC)
    return [to_response(r, now=now) for r in rows]


@router.get("/rank-tracker/stats", response_model=RankStats)
async def rank_stats(
    repo: RankRepoDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> RankStats:
    """The board summary tiles: tracked keywords, average position across the RANKED
    ones, and how many sit in the top 3."""
    row = await asyncio.to_thread(repo.rank_stats, client_id=client_id)
    return RankStats.from_row(row)


@router.get("/rank-tracker/workspace", response_model=ToolExtraResponse)
async def rank_workspace(repo: RankRepoDep, _feat: Feature, _user: ViewReports) -> ToolExtraResponse:
    """The tool workspace (``lib/tools.ts`` ``rank_tracker`` shape): KPI tiles, the
    movements table (cols ``Keyword|Client|Position|Change``), and the CTA."""
    stats_row = await asyncio.to_thread(repo.rank_stats)
    top = await asyncio.to_thread(repo.list_keywords, limit=8, offset=0)
    return build_workspace(RankStats.from_row(stats_row), top)


@router.get("/rank-tracker/keywords/{code}/history", response_model=list[RankHistoryPoint])
async def keyword_history(
    code: str,
    repo: RankRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
) -> list[RankHistoryPoint]:
    """One keyword's daily ranking history, newest first.

    A day whose check FAILED has no point at all - the series has an honest gap rather
    than a fabricated unranked reading."""
    existing = await asyncio.to_thread(repo.get_by_code, code)
    if existing is None:
        raise _KEYWORD_NOT_FOUND
    rows = await asyncio.to_thread(repo.history, str(existing["id"]), limit=page.limit)
    return [RankHistoryPoint.from_row(r) for r in rows]


@router.get("/rank-tracker/cost-projection", response_model=RankCostProjection)
async def cost_projection(
    repo: RankRepoDep,
    settings: SettingsDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str, Query(alias="clientId")],
) -> RankCostProjection:
    """The N-A monthly COMMITMENT this client's active tracking carries.

    Rank tracking is the platform's first standing per-client cost and the client pays,
    so the recurring bill is a first-class, inspectable number - not something anyone
    has to reverse-engineer from the cost log a month later."""
    client_name = await asyncio.to_thread(repo.client_name_for, client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND
    return await asyncio.to_thread(
        _projection_for, repo, settings, client_id=client_id, client_name=client_name
    )


# --- mutations ----------------------------------------------------------------


@router.post(
    "/rank-tracker/keywords",
    response_model=RankKeywordsAdded,
    status_code=status.HTTP_201_CREATED,
)
async def add_keywords(
    body: RankKeywordCreate,
    repo: RankRepoDep,
    settings: SettingsDep,
    _feat: Feature,
    actor: RunResearch,
) -> RankKeywordsAdded:
    """Bulk-subscribe keywords for one client (run_research).

    N-A - the commitment gate. This does NOT just add rows: it prices the client's
    whole active book as it WOULD be after the add and REFUSES with 402 if that
    monthly commitment exceeds their remaining budget. Gating each nightly check alone
    would let the agency walk a client into a runaway bill one batch at a time and only
    find out on the invoice; the refusal belongs here, at configuration time, where a
    human is present to lower the cadence or raise the cap.

    404 if the client is unknown/invisible. Duplicates (client, keyword, engine, device,
    location, language) are skipped, not double-billed. The response carries the
    resulting projection so the standing bill is visible in the same breath as the add.
    """
    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND

    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for raw in body.keywords:
        normalized = normalize_keyword(raw)
        if not normalized or normalized in seen:
            continue  # fold in-batch duplicates before they reach the DB
        seen.add(normalized)
        pairs.append((raw.strip(), normalized))
    if not pairs:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="No usable keywords in the batch"
        )

    projection = await asyncio.to_thread(
        _projection_for,
        repo, settings,
        client_id=body.client_id,
        client_name=client_name,
        adding={body.cadence: len(pairs)},
    )
    if not projection.within_budget:
        # 402 Payment Required: the add is refused on BUDGET grounds, which is neither
        # an auth failure (403) nor a malformed request (400). The message names both
        # numbers so the caller can act without opening the cost screen.
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED, detail=projection.message
        )

    rows = await asyncio.to_thread(
        repo.add_keywords,
        client_id=body.client_id,
        client_name=client_name,
        site_id=body.site_id,
        keywords=pairs,
        target_url=body.target_url or "",
        engine=body.engine,
        device=body.device,
        location=body.location,
        location_code=body.location_code,
        language=body.language,
        country=body.country,
        tags=body.tags or [],
        cadence=body.cadence,
        # Due immediately: a new subscription should not wait a week for its first
        # reading. The dispatcher's claim then puts it on its cadence.
        next_check_on=datetime.now(UTC).date(),
    )
    await record_activity(
        actor,
        kind="client",
        action=f"started tracking {len(rows)} keyword(s)",
        target=client_name,
        entity_type="client",
        entity_id=body.client_id,
    )
    now = datetime.now(UTC)
    return RankKeywordsAdded(
        keywords=[to_response(r, now=now) for r in rows], projection=projection
    )


@router.post(
    "/rank-tracker/keywords/{code}/check",
    response_model=RankCheckQueued,
    status_code=status.HTTP_202_ACCEPTED,
)
async def check_keyword(
    code: str,
    repo: RankRepoDep,
    _feat: Feature,
    actor: RunResearch,
    _limit: CheckLimit,
    enqueue: CheckEnqueuerDep,
    force: Annotated[bool, Query()] = False,
) -> RankCheckQueued:
    """Fire an on-demand rank check for ONE keyword (run_research).

    Deduped to today unless ``force``: the worker re-checks the day guard before it
    spends anything, but refusing here too keeps a button-masher from queueing work
    that is only going to no-op. The paid pull is cost-gated in the worker, not here.
    """
    row = await asyncio.to_thread(repo.get_by_code, code)
    if row is None:
        raise _KEYWORD_NOT_FOUND

    checked_at = row.get("latest_checked_at")
    already_today = (
        isinstance(checked_at, datetime) and checked_at.date() == datetime.now(UTC).date()
    )
    if already_today and not force:
        return RankCheckQueued(code=code, queued=False, reason="already checked today")

    enqueue(str(row["id"]), force)
    await record_activity(
        actor,
        kind="client",
        action=f"ran a rank check for '{row.get('keyword', '')}'",
        target=str(row.get("client_name", "") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id") or "") or None,
    )
    return RankCheckQueued(code=code, queued=True)


@router.patch("/rank-tracker/keywords/{code}", response_model=RankKeywordResponse)
async def update_keyword(
    code: str,
    body: RankKeywordUpdate,
    repo: RankRepoDep,
    settings: SettingsDep,
    _feat: Feature,
    actor: RunResearch,
) -> RankKeywordResponse:
    """Re-configure ONE subscription (run_research): pause/resume it, change its
    cadence, replace its tags, or re-point its target URL.

    Pausing stops the standing spend WITHOUT discarding the history; resuming makes it
    due immediately so the board is not left showing a stale position from the pause.
    404 if the code is unknown; 400 if nothing was provided.

    N-A also applies HERE, not only on the add: a cadence flip (weekly -> daily is 7x
    the monthly cost) or a resume raises the client's standing bill just as surely as a
    new keyword, so a change that would breach the remaining budget is refused with 402.
    Only INCREASES are gated - pausing or slowing a subscription is always allowed, even
    for a client already over their cap, because refusing it would trap them there.
    """
    existing = await asyncio.to_thread(repo.get_by_code, code)
    if existing is None:
        raise _KEYWORD_NOT_FOUND

    provided = body.model_dump(exclude_unset=True)
    if not provided:
        raise _NOTHING_TO_UPDATE

    changes: dict[str, Any] = {}
    if "status" in provided and body.status is not None:
        changes["status"] = body.status
        if body.status == "active" and str(existing.get("status") or "") != "active":
            # Resuming: make it due now rather than honouring a next_check_on that
            # elapsed during the pause (or sitting stale until the old slot comes round).
            changes["next_check_on"] = datetime.now(UTC).date()
    if "cadence" in provided and body.cadence is not None:
        changes["cadence"] = body.cadence
    if "tags" in provided:
        changes["tags"] = body.tags or []
    if "target_url" in provided:
        changes["target_url"] = body.target_url or ""
    if not changes:
        raise _NOTHING_TO_UPDATE

    # N-A: re-gate the COMMITMENT whenever this change could raise it. Tag/URL edits
    # cost nothing, so they skip the pricing round-trip entirely.
    if "status" in changes or "cadence" in changes:
        await _guard_commitment_change(repo, settings, existing, changes)

    row = await asyncio.to_thread(repo.update_keyword, code, changes)
    if row is None:
        raise _KEYWORD_NOT_FOUND

    await record_activity(
        actor,
        kind="client",
        action="updated a tracked keyword",
        target=str(row.get("client_name", "") or "") or str(row.get("keyword", "") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id") or "") or None,
    )
    return to_response(row)
