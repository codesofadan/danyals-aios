"""Local-SEO endpoints (Part 8 Phase 2E): map-pack rank tracking + GBP profiles.

No ``frontend/lib/*.ts`` type mirrors this module - the responses are
SERVER-AUTHORITATIVE (``schemas.py`` owns the shape + its own shape tests). The
``GET /local-seo/workspace`` adapter emits the ``lib/tools.ts`` ``local_seo`` EXTRA
shape (KPIs + the map-pack table + the CTA), with table columns pinned to
``tests/test_tool_workspace_contract.py``.

Tables owned: ``local_rankings`` / ``local_rank_history`` / ``gbp_profiles``
(migration ``0039_local_seo``). The Citations KPI + the NAP-alignment report READ the
EXISTING ``citations`` table from ``0018_offpage``, which the off-page module owns and
this one never writes. Cost-gate dial: ``local_rank`` (the map-pack check spend; the
refresh worker gates on it and bills the ROW's client).

SCOPE: map-pack rank is a SINGLE position per (profile, keyword, geo) at one
representative locale - there is no geo-grid / heatmap surface here. GBP is profile
management + NAP, READ-ONLY: no posting route, no review-reply route.

Access: every route requires the ``local_seo`` FEATURE grant. Reads add
``view_reports``; every mutation adds ``require_role(owner, admin, manager)`` - the
LEADS - which lines up with the 0039 RLS insert/update policies byte-for-byte. The
internal ``client_id`` never leaks (``client`` is the snapshotted name); every
mutation offloads the blocking psycopg call with ``asyncio.to_thread`` and records an
activity entry (kind=client, entity=client) so the local work keeps each client's
context fresh.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_feature, require_perm, require_role
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.core.ratelimit import rate_limit
from app.modules.local_seo.repo import LocalRepoDep
from app.modules.local_seo.schemas import (
    GbpProfileResponse,
    LocalRankHistoryPoint,
    LocalRankingCreate,
    LocalRankingResponse,
    LocalRankingUpdate,
    LocalStats,
    NapAlignmentReport,
    ProfileAuditReport,
    ProfileUpsert,
    RefreshQueuedResponse,
)
from app.modules.local_seo.service import build_audit_report, build_nap_alignment, build_workspace
from app.schemas.tool_workspace import ToolExtraResponse
from app.services.activity import record_activity

router = APIRouter(tags=["local-seo"])

# Every tool route requires the fine-grained local_seo feature grant (owner is
# all-on). Reads additionally require view_reports; every mutation requires a LEAD
# role (owner/admin/manager), mirroring the 0039 RLS insert/update policies
# (``current_app_role() in ('owner','admin','manager')``) exactly - a caller who
# passed the app gate but failed RLS would get an opaque database error instead of a
# clean 403.
Feature = Annotated[CurrentUser, Depends(require_feature("local_seo"))]
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

# A manual refresh triggers a PAID provider check, so it is rate-limited per user on
# top of the cost gate: the gate bounds the MONEY, this bounds the hammering.
_REFRESH_LIMIT = Depends(rate_limit("local_rank_refresh", limit=20, per_seconds=60))

_RANKING_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Ranking not found"
)
_PROFILE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found"
)
_CLIENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
)
_NOTHING_TO_UPDATE = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
)
_PROFILE_REQUIRED = HTTPException(
    status_code=status.HTTP_400_BAD_REQUEST,
    detail="clientId and locationLabel are required to create a profile",
)


def get_rank_refresh_enqueuer() -> Callable[[], None]:
    """Dependency: enqueue the map-pack refresh beat (overridable in tests).

    The Celery task is imported lazily so the API process never pulls in the task
    module just to import this router (mirrors ``get_research_enqueuer``)."""

    def _enqueue() -> None:
        from app.modules.local_seo.tasks import refresh_local_ranks

        refresh_local_ranks.delay()

    return _enqueue


def get_gbp_sync_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the read-only GBP profile sync (overridable in tests)."""

    def _enqueue(profile_id: str) -> None:
        from app.modules.local_seo.tasks import sync_gbp_profile

        sync_gbp_profile.delay(profile_id)

    return _enqueue


RankRefreshEnqueuerDep = Annotated[Callable[[], None], Depends(get_rank_refresh_enqueuer)]
GbpSyncEnqueuerDep = Annotated[Callable[[str], None], Depends(get_gbp_sync_enqueuer)]


# --- reads --------------------------------------------------------------------


@router.get("/local-seo/rankings", response_model=list[LocalRankingResponse])
async def list_rankings(
    repo: LocalRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    profile_id: Annotated[str | None, Query(alias="profileId")] = None,
    keyword: Annotated[str | None, Query()] = None,
    geo: Annotated[str | None, Query()] = None,
    in_map_pack: Annotated[bool | None, Query(alias="inMapPack")] = None,
    is_active: Annotated[bool | None, Query(alias="isActive")] = None,
) -> list[LocalRankingResponse]:
    """The tracked map-pack rankings (best ranks first, unranked last). Filters narrow
    the board by client, location, keyword, locale, pack membership, or tracking state."""
    rows = await asyncio.to_thread(
        repo.list_rankings,
        client_id=client_id,
        profile_id=profile_id,
        keyword=keyword,
        geo=geo,
        in_map_pack=in_map_pack,
        is_active=is_active,
        limit=page.limit,
        offset=page.offset,
    )
    return [LocalRankingResponse.from_row(r) for r in rows]


@router.get("/local-seo/stats", response_model=LocalStats)
async def local_stats(repo: LocalRepoDep, _feat: Feature, _user: ViewReports) -> LocalStats:
    """The summary tiles: tracked GBP profiles, average map rank (ranked+active rows
    only), and the citation count off the EXISTING 0018 ledger."""
    row = await asyncio.to_thread(repo.local_stats)
    return LocalStats.from_row(row)


@router.get("/local-seo/workspace", response_model=ToolExtraResponse)
async def local_workspace(
    repo: LocalRepoDep, _feat: Feature, _user: ViewReports
) -> ToolExtraResponse:
    """The tool workspace (``lib/tools.ts`` ``local_seo`` shape): KPI tiles, the
    map-pack table (cols ``Location|Client|Keyword|Rank``), and the CTA."""
    stats_row = await asyncio.to_thread(repo.local_stats)
    top = await asyncio.to_thread(repo.list_rankings, limit=8, offset=0)
    return build_workspace(LocalStats.from_row(stats_row), top)


@router.get("/local-seo/rankings/{ranking_id}/history", response_model=list[LocalRankHistoryPoint])
async def ranking_history(
    ranking_id: str,
    repo: LocalRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
) -> list[LocalRankHistoryPoint]:
    """One ranking's append-only timeline, newest first. A ``rank`` of null is a real
    observation ("out of the pack" that day), never a failed check - failures are
    never appended."""
    if await asyncio.to_thread(repo.get_ranking, ranking_id) is None:
        raise _RANKING_NOT_FOUND
    rows = await asyncio.to_thread(repo.rank_history, ranking_id, limit=page.limit)
    return [LocalRankHistoryPoint.from_row(r) for r in rows]


@router.get("/local-seo/profiles", response_model=list[GbpProfileResponse])
async def list_profiles(
    repo: LocalRepoDep,
    page: PageDep,
    _feat: Feature,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[GbpProfileResponse]:
    """The tracked GBP location profiles, optionally scoped to one client."""
    rows = await asyncio.to_thread(
        repo.list_profiles, client_id=client_id, limit=page.limit, offset=page.offset
    )
    return [GbpProfileResponse.from_row(r) for r in rows]


@router.get("/local-seo/profiles/{profile_id}", response_model=GbpProfileResponse)
async def get_profile(
    profile_id: str, repo: LocalRepoDep, _feat: Feature, _user: ViewReports
) -> GbpProfileResponse:
    """ONE GBP location profile. ``oauthConnected`` says only WHETHER a token is
    sealed - the vault ref itself is never on the wire."""
    row = await asyncio.to_thread(repo.get_profile, profile_id)
    if row is None:
        raise _PROFILE_NOT_FOUND
    return GbpProfileResponse.from_row(row)


@router.get("/local-seo/profiles/{profile_id}/audit", response_model=ProfileAuditReport)
async def profile_audit(
    profile_id: str, repo: LocalRepoDep, _feat: Feature, _user: ViewReports
) -> ProfileAuditReport:
    """The profile's completeness audit: the freshly recomputed 0-100 score, the
    per-field findings, the fix-list, and its categories."""
    row = await asyncio.to_thread(repo.get_profile, profile_id)
    if row is None:
        raise _PROFILE_NOT_FOUND
    return build_audit_report(row)


@router.get("/local-seo/profiles/{profile_id}/nap-alignment", response_model=NapAlignmentReport)
async def profile_nap_alignment(
    profile_id: str, repo: LocalRepoDep, _feat: Feature, _user: ViewReports
) -> NapAlignmentReport:
    """The profile's NAP alignment across its citation directories (read off the
    EXISTING 0018 ledger). Cosmetic-only drift ("St." vs "Street") is normalised away
    and reported separately, so ``inconsistent`` names only real listing errors."""
    profile = await asyncio.to_thread(repo.get_profile, profile_id)
    if profile is None:
        raise _PROFILE_NOT_FOUND
    citations = await asyncio.to_thread(repo.citations_for_client, str(profile["client_id"]))
    return build_nap_alignment(profile, citations)


# --- mutations ----------------------------------------------------------------


@router.post(
    "/local-seo/rankings",
    response_model=LocalRankingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_ranking(
    body: LocalRankingCreate, repo: LocalRepoDep, _feat: Feature, actor: Lead
) -> LocalRankingResponse:
    """Track a keyword's map-pack position for ONE GBP profile (lead).

    The client + its display snapshot are taken from the PROFILE, never from the
    caller, so a ranking can never be mis-attributed. 404 if the profile is
    unknown/invisible. Re-tracking an existing (profile, keyword, geo) returns the
    existing row rather than erroring. Records one activity entry."""
    profile = await asyncio.to_thread(repo.get_profile, body.profile_id)
    if profile is None:
        raise _PROFILE_NOT_FOUND
    client_id = str(profile["client_id"])
    client_name = str(profile.get("client_name", "") or "")
    row = await asyncio.to_thread(
        repo.add_ranking,
        client_id=client_id,
        client_name=client_name,
        profile_id=body.profile_id,
        keyword=body.keyword,
        geo=body.geo,
    )
    if row is None:
        raise _RANKING_NOT_FOUND
    await record_activity(
        actor, kind="client", action=f"tracked local keyword '{body.keyword}'",
        target=client_name, entity_type="client", entity_id=client_id,
    )
    return LocalRankingResponse.from_row(row)


@router.patch("/local-seo/rankings/{ranking_id}", response_model=LocalRankingResponse)
async def update_ranking(
    ranking_id: str,
    body: LocalRankingUpdate,
    repo: LocalRepoDep,
    _feat: Feature,
    actor: Lead,
) -> LocalRankingResponse:
    """Activate / deactivate ONE tracked ranking (lead). Deactivating retires it from
    the refresh beat (it stops costing money) while KEEPING its history. 404 if the id
    is unknown/invisible."""
    row = await asyncio.to_thread(repo.set_ranking_active, ranking_id, is_active=body.is_active)
    if row is None:
        raise _RANKING_NOT_FOUND
    verb = "resumed" if body.is_active else "paused"
    await record_activity(
        actor, kind="client", action=f"{verb} local tracking for '{row.get('keyword', '')}'",
        target=str(row.get("client_name", "") or ""),
        entity_type="client", entity_id=str(row["client_id"]),
    )
    return LocalRankingResponse.from_row(row)


@router.post(
    "/local-seo/rankings/{ranking_id}/refresh",
    response_model=RefreshQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[_REFRESH_LIMIT],
)
async def refresh_ranking(
    ranking_id: str,
    repo: LocalRepoDep,
    _feat: Feature,
    actor: Lead,
    enqueue: RankRefreshEnqueuerDep,
) -> RefreshQueuedResponse:
    """Kick the map-pack refresh sweep (lead; rate-limited).

    Validates the ranking exists, then enqueues the same cost-gated beat the schedule
    runs - the paid check is gated in the WORKER, not here, so an on-demand refresh can
    never bypass the money dial. 404 if the id is unknown/invisible."""
    row = await asyncio.to_thread(repo.get_ranking, ranking_id)
    if row is None:
        raise _RANKING_NOT_FOUND
    enqueue()
    await record_activity(
        actor, kind="client", action=f"refreshed local rank for '{row.get('keyword', '')}'",
        target=str(row.get("client_name", "") or ""),
        entity_type="client", entity_id=str(row["client_id"]),
    )
    return RefreshQueuedResponse(id=ranking_id, queued=True)


@router.post(
    "/local-seo/profiles",
    response_model=GbpProfileResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_profile(
    body: ProfileUpsert, repo: LocalRepoDep, _feat: Feature, actor: Lead
) -> GbpProfileResponse:
    """Create ONE GBP location profile (lead).

    ``clientId`` + ``locationLabel`` are required; the client's display name is
    snapshotted server-side (404 if the client is unknown/invisible). The completeness
    score + audit are DERIVED here, never accepted from the caller. Records one
    activity entry."""
    if not body.client_id or not body.location_label:
        raise _PROFILE_REQUIRED
    client_name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if client_name is None:
        raise _CLIENT_NOT_FOUND

    values = _profile_columns(body)
    values["client_id"] = body.client_id
    values["client_name"] = client_name
    values["location_label"] = body.location_label
    _stamp_completeness(values)

    row = await asyncio.to_thread(repo.add_profile, values)
    if row is None:
        raise _PROFILE_NOT_FOUND
    await record_activity(
        actor, kind="client", action=f"added the GBP profile '{body.location_label}'",
        target=client_name, entity_type="client", entity_id=body.client_id,
    )
    return GbpProfileResponse.from_row(row)


@router.patch("/local-seo/profiles/{profile_id}", response_model=GbpProfileResponse)
async def update_profile(
    profile_id: str, body: ProfileUpsert, repo: LocalRepoDep, _feat: Feature, actor: Lead
) -> GbpProfileResponse:
    """Edit ONE GBP location profile (lead). Only the provided fields change; the
    completeness score + audit are RE-DERIVED from the merged result, so the score can
    never disagree with the fields. 404 if unknown; 400 if nothing was provided.

    ``clientId`` is deliberately NOT re-assignable: a profile's rankings + history are
    already attributed to its client, so moving it would silently re-attribute them."""
    existing = await asyncio.to_thread(repo.get_profile, profile_id)
    if existing is None:
        raise _PROFILE_NOT_FOUND

    changes = _profile_columns(body)
    if body.location_label is not None:
        changes["location_label"] = body.location_label
    if not changes:
        raise _NOTHING_TO_UPDATE
    # Score the MERGED profile: a PATCH that fills one field must re-score the whole.
    merged = {**existing, **changes}
    _stamp_completeness(merged)
    changes["completeness_score"] = merged["completeness_score"]
    changes["audit"] = merged["audit"]

    row = await asyncio.to_thread(repo.update_profile, profile_id, changes)
    if row is None:
        raise _PROFILE_NOT_FOUND
    await record_activity(
        actor, kind="client", action="updated a GBP profile",
        target=str(row.get("client_name", "") or ""),
        entity_type="client", entity_id=str(row["client_id"]),
    )
    return GbpProfileResponse.from_row(row)


@router.post(
    "/local-seo/profiles/{profile_id}/sync",
    response_model=RefreshQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def sync_profile(
    profile_id: str,
    repo: LocalRepoDep,
    settings: SettingsDep,
    _feat: Feature,
    actor: Lead,
    enqueue: GbpSyncEnqueuerDep,
) -> RefreshQueuedResponse:
    """Queue a READ-ONLY GBP profile sync (lead).

    Returns 202 with ``held=true`` when no GBP OAuth client is configured: the Google
    Business Profile API is approval-gated (a new project starts at 0 QPM), so a
    token-less deploy HOLDS honestly instead of queueing a job that cannot run. The
    module stays fully usable on map-pack rank + citations meanwhile. 404 if the
    profile is unknown/invisible."""
    profile = await asyncio.to_thread(repo.get_profile, profile_id)
    if profile is None:
        raise _PROFILE_NOT_FOUND
    if not (settings.gbp_oauth_client_id and settings.gbp_oauth_client_secret):
        return RefreshQueuedResponse(
            id=profile_id, queued=False, held=True, reason="no_oauth_client"
        )
    enqueue(profile_id)
    await record_activity(
        actor, kind="client", action="synced a GBP profile",
        target=str(profile.get("client_name", "") or ""),
        entity_type="client", entity_id=str(profile["client_id"]),
    )
    return RefreshQueuedResponse(id=profile_id, queued=True)


# --- helpers ------------------------------------------------------------------


def _profile_columns(body: ProfileUpsert) -> dict[str, Any]:
    """The SERVER-BUILT column dict for a profile upsert.

    Only the fields a caller may set are mapped, so the keys are a trusted, fixed set
    (the repo quotes them anyway) - ``completeness_score`` / ``audit`` /
    ``oauth_vault_ref`` / ``oauth_connected`` are absent by construction and can never
    be driven from request JSON.
    """
    provided = body.model_dump(exclude_unset=True)
    mapping: dict[str, str] = {
        "google_location_id": "google_location_id",
        "place_id": "place_id",
        "primary_category": "primary_category",
        "nap_name": "nap_name",
        "nap_address": "nap_address",
        "nap_phone": "nap_phone",
        "website_uri": "website_uri",
    }
    values: dict[str, Any] = {}
    for attr, column in mapping.items():
        if attr in provided:
            values[column] = getattr(body, attr) or ""
    if "secondary_categories" in provided:
        values["secondary_categories"] = body.secondary_categories or []
    if "regular_hours" in provided:
        import json

        values["regular_hours"] = json.dumps(body.regular_hours or {})
    return values


def _stamp_completeness(values: dict[str, Any]) -> None:
    """Derive + stamp ``completeness_score`` and ``audit`` onto a column dict.

    Both are SERVER-DERIVED from the profile's own fields, which is why they are
    computed here rather than accepted from the caller.
    """
    import json

    from app.modules.local_seo.service import profile_completeness

    scoring = dict(values)
    # `regular_hours` is already JSON-encoded for psycopg at this point; the checklist
    # wants the live dict, so decode it back just for scoring.
    hours = scoring.get("regular_hours")
    if isinstance(hours, str):
        try:
            scoring["regular_hours"] = json.loads(hours)
        except ValueError:
            scoring["regular_hours"] = {}
    score, audit = profile_completeness(scoring)
    values["completeness_score"] = score
    values["audit"] = json.dumps(audit)
