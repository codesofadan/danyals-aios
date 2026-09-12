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
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from fastapi.responses import FileResponse

from app.config import get_settings
from app.core.auth import CurrentUser, require_perm, require_role
from app.core.deps import RedisDep
from app.core.ratelimit import _enforce
from app.core.security import is_public_url
from app.db.offpage_repo import OffpageRepo
from app.logging_setup import get_logger
from app.modules.citations.evidence import citation_evidence_store
from app.modules.citations.operator_auth import (
    OperatorOrUserDep,
    OperatorOrUserWriteDep,
    operator_principal_of,
    require_operator_lead,
    require_operator_lead_over,
    require_operator_scope_or_perm,
    require_operator_scope_sets,
)
from app.modules.citations.repo import (
    CitationQueueRepoDep,
    CitationQueueRepoWriteDep,
    CitationsRepo,
    CitationsRepoDep,
    DirectorySpecsRepo,
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
    CampaignRollupResponse,
    CampaignRowResponse,
    CampaignSummaryResponse,
    CitationCampaignRequest,
    CitationCampaignResponse,
    CitationLiveUrl,
    CitationSkip,
    CitationVerifyFirst,
    DirectoryResponse,
    DirectorySpecResponse,
    EngineStatusBoardResponse,
    EngineStatusResponse,
    GapAnalysisResponse,
    OperatorSessionResponse,
    QueueBlockedRequest,
    QueueBoardResponse,
    QueueClaimRequest,
    QueueCompleteRequest,
    QueueCompleteResponse,
    QueueFieldValue,
    QueueHeartbeatRequest,
    QueueItemResponse,
    SessionActionResponse,
    SessionClientCount,
    SessionCreateRequest,
    SessionDetailResponse,
    SessionHeartbeatResponse,
    SessionSkipRequest,
    SessionTaskCard,
    SessionTelemetryRequest,
    SessionWeb2BlockRequest,
    SpecBoardResponse,
    SpecCreateRequest,
    SpecDeactivateRequest,
    SpecFirstLiveRequest,
    SpecVerifyRequest,
    Web2CopyBlock,
    Web2PlacementTaskCard,
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
    summarize_campaign_rows,
)
from app.modules.citations.sessions import (
    SESSION_LEASE_SECONDS,
    ActiveSessionExistsError,
    NoSessionWorkError,
    OperatorSessionsRepoDep,
    OperatorSessionsRepoWriteDep,
)
from app.modules.citations.verticals import normalize_vertical
from app.rbac import role_has_perm
from app.services.activity import record_activity
from app.services.citation_liveness import http_liveness_probe, judge_liveness
from app.services.web2_placement import copy_blocks_for, editor_url_for, spec_selectors
from integrations.citation_status import citation_engine_board
from integrations.directory_specs import db_spec_loader
from integrations.web2_status import web2_status_board

logger = get_logger("app.modules.citations.router")

router = APIRouter(prefix="/citation-builder", tags=["citation-builder"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# The QUEUE routes only. These accept a dashboard bearer token OR the extension's
# `X-Operator-Token`, resolving both to the same CurrentUser - so there is ONE
# implementation of "a completion is checked by fetching the URL", not two.
#
# The Phase-2 scope split is APPLIED here (Phase 3): reads resolve through
# `citation_queue:read` (`OperatorOrUser`), every mutation through
# `citation_queue:write` (`OperatorOrUserWrite`, and `require_operator_lead` which
# wraps it). The legacy umbrella `citation_queue` satisfies both until those tokens
# age out; bearer callers are governed by their role exactly as before.
#
# `OperatorOrUserLead` additionally requires a lead role, exactly as the bearer-only
# version did: an operator token inherits its holder's role and grants nothing extra.
# A non-lead paired extension is refused the write endpoints for the same reason a
# non-lead session is.
OperatorOrUser = OperatorOrUserDep
OperatorOrUserWrite = OperatorOrUserWriteDep
OperatorOrUserLead = Annotated[CurrentUser, Depends(require_operator_lead)]
# Reads that serve CANONICAL BUSINESS-PROFILE values: the extension path needs the
# `client_profile:read` scope; a bearer caller still needs `view_reports`, exactly as
# before the extension could reach these. A module-level OBJECT so the repo
# dependency below binds to the SAME resolver (one credential resolution per request,
# and tests can override it by identity).
resolve_profile_reader = require_operator_scope_or_perm("client_profile:read", "view_reports")
ProfileReader = Annotated[CurrentUser, Depends(resolve_profile_reader)]


def get_citations_repo_profile(
    user: Annotated[CurrentUser, Depends(resolve_profile_reader)],
) -> CitationsRepo:
    """CitationsRepo for the extension-reachable business-profile READ. The plain
    `CitationsRepoDep` resolves bearer-only `get_current_user`, which would 401 an
    operator token before `resolve_profile_reader` was ever consulted - the exact
    failure mode `get_citation_queue_repo`'s docstring documents. Bound to the same
    hybrid guard the route declares, so the scope/permission bar is unchanged."""
    return CitationsRepo(user.id)


CitationsRepoProfileDep = Annotated[CitationsRepo, Depends(get_citations_repo_profile)]
# Gap/coverage reads reachable by the extension: `citation_queue:read` on the operator
# path, the unchanged `view_reports` on the bearer path.
QueueReader = Annotated[
    CurrentUser, Depends(require_operator_scope_or_perm("citation_queue:read", "view_reports"))
]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_PROFILE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Business profile not found"
)
_CLIENT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")


def get_discovery_dial_reader() -> Callable[[], str]:
    """Dependency: read the citation_discovery dial (overridable in tests).

    Read SYNCHRONOUSLY at the route so a refusal is stated at click time. The audit
    used to 202 "queued" into a dial that silently blocked the sweep — zero rows
    written, and the operator discovered it by polling nothing."""

    def _read() -> str:
        from app.services.cost_store import PostgresCostStore

        try:
            return str(PostgresCostStore().dial_mode("citation_discovery"))
        except Exception:
            # An unreadable dial must not take the audit down; the worker's own gate
            # still decides. "unknown" renders as willRun-unknown, never as a promise.
            return "unknown"

    return _read


DiscoveryDialDep = Annotated[Callable[[], str], Depends(get_discovery_dial_reader)]


def get_citation_enqueuer() -> Callable[..., None]:
    """Dependency: enqueue the citation-submit worker (overridable in tests).

    Goes through ``app.jobs.celery_task.enqueue``, not ``.delay()``: enqueue writes the
    ``job_runs`` row AT SEND TIME, which is what makes a 45-row campaign visible in
    Operations even when no worker is running — the bare ``.delay()`` this used to be
    left the whole campaign without a single ledger row (2026-09-01). The correlation
    id groups a campaign's fan-out into one reassemblable unit."""

    def _enqueue(citation_id: str, *, client_id: str = "", correlation_id: str = "") -> None:
        from app.jobs.celery_task import enqueue as contract_enqueue

        contract_enqueue(
            "citation_submit",
            citation_id,
            client_id=client_id,
            campaign_id=correlation_id,
            correlation_id=correlation_id or None,
        )

    return _enqueue


CitationEnqueuerDep = Annotated[Callable[..., None], Depends(get_citation_enqueuer)]


def get_audit_enqueuer() -> Callable[[str, str, str], str]:
    """Dependency: enqueue the citation-AUDIT sweep (overridable in tests).

    Reuses the built off-page monitor worker (``monitor_offpage``): it pulls the
    business's directory listings from the configured citation tracker, diffs vs the
    ledger, and writes real ``nap_status`` rows (consistent / inconsistent / missing)
    - i.e. discovers where the business is already listed vs where it is not. Lazily
    imported so the API process never pulls in Celery just to import this router."""

    def _enqueue(client_id: str, domain: str, business: str) -> str:
        from app.jobs.celery_task import enqueue as enqueue_job

        # A MINUTE BUCKET, not a bare send. Two clicks a second apart are one unit of
        # work and collapse onto one run; a re-run five minutes later is a genuinely
        # new one and gets its own. The key is supplied here rather than derived in the
        # task, so a deliberate re-audit is never silently a no-op.
        bucket = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M")
        enqueue_job(
            "monitor_offpage",
            client_id,
            domain,
            business,
            idempotency_key=f"offpage.monitor:{client_id}:{bucket}",
        )
        return f"offpage.monitor:{client_id}:{bucket}"

    return _enqueue


AuditEnqueuerDep = Annotated[Callable[[str, str, str], str], Depends(get_audit_enqueuer)]


def _run_for_key(key: str) -> dict[str, Any] | None:
    """The job run that owns this key, so the 202 can carry an id worth polling.

    Imported lazily for the same reason the enqueuer is: the API edge must not pull in
    the job/Celery modules merely to import this router.
    """
    from app.db.job_runs_repo import job_runs_store

    try:
        return job_runs_store().get_by_idempotency_key(key)
    except Exception:
        # The work is already accepted and queued at this point. Failing the request
        # because the run could not be READ BACK would turn a visible audit into a
        # refused one; the caller simply gets no id to follow, and the board still
        # updates when the sweep lands.
        return None


def get_service_citations_store() -> ServiceCitationsStore:
    """Dependency: the privileged citations store (service_role) for the delete path.

    ``citations`` has FORCE RLS with no delete policy, so clearing rows must run on
    the service_role connection - exactly like the submit worker's writes."""
    return service_citations_store()


ServiceCitationsStoreDep = Annotated[ServiceCitationsStore, Depends(get_service_citations_store)]


# --- business profiles ----------------------------------------------------------


@router.get("/business-profiles", response_model=list[BusinessProfileResponse])
async def list_business_profiles(
    repo: CitationsRepoProfileDep,
    _user: ProfileReader,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[BusinessProfileResponse]:
    """Canonical NAP values. Reachable by the extension under `client_profile:read`
    (what its autofill types is exactly this data); bearer callers still need
    `view_reports`, unchanged."""
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
    client_id: str,
    repo: CitationsRepoDep,
    actor: Lead,
    enqueue: AuditEnqueuerDep,
    dial: DiscoveryDialDep,
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

    # THE DIAL, STATED AT CLICK TIME. `off` refuses outright — enqueueing work the
    # gate will certainly skip manufactures a dead run. `byhand` still enqueues (the
    # worker records the honest blocked outcome, and that trail is valuable) but the
    # response SAYS the sweep will not run and names the fix.
    mode = await asyncio.to_thread(dial)
    if mode == "off":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The Citation Discovery dial is OFF, so this audit would be skipped. "
                "Turn it on under Cost → dials, or approve the spend, then re-run."
            ),
        )
    will_run = mode == "api"
    discovery = {
        "dial": mode,
        "willRun": will_run,
        **(
            {}
            if will_run
            else {
                "detail": (
                    "The citation_discovery dial requires manual review - the sweep "
                    "will record a blocked run, not listings. Flip it to api on the "
                    "Cost page or approve the spend."
                )
            }
        ),
    }

    # domain is only used by the sibling backlink monitor; a citation audit keys off
    # the business name, so "" is fine here.
    key = await asyncio.to_thread(enqueue, client_id, "", business)
    # The run row exists as soon as the work is accepted, so the caller gets an id it
    # can actually follow. This used to return a bare {"status": "queued"} with nothing
    # to poll: the audit was invisible from the moment it started until whenever its
    # rows happened to appear, and a sweep that never ran looked the same as one still
    # working.
    run = await asyncio.to_thread(_run_for_key, key)
    await record_activity(
        actor, kind="content", action="ran a citation audit", target=name,
        entity_type="client", entity_id=client_id,
    )
    return {
        "status": "queued",
        "clientId": client_id,
        "business": business,
        "jobRunId": str(run["id"]) if run else None,
        "jobName": "offpage.monitor",
        "discovery": discovery,
        "detail": (
            "Citation audit queued - discovering existing vs missing listings."
            if will_run
            else "Citation audit queued, but the Citation Discovery dial will hold it - see discovery.detail."
        ),
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

    # THE CAMPAIGN IS A THING (0120). Created BEFORE the fan-out so every queued row
    # carries its id, the job ledger groups on it, and a crash mid-loop still leaves
    # an inspectable record instead of orphan rows.
    campaign_row = await asyncio.to_thread(
        repo.create_campaign,
        client_id=body.client_id,
        client_name=name,
        created_by=actor.id,
        requested=len(selection.selected),
        params={
            "markets": markets,
            "tiers": sorted(tiers),
            "cap": cap,
            "minAuthority": min_authority,
            "vertical": vertical,
            "includeMarketplaces": body.include_marketplaces,
            "directoryIds": [str(d) for d in (body.directory_ids or [])],
        },
    )
    campaign_id = str(campaign_row["id"]) if campaign_row else ""
    queued_ids: list[str] = []
    for directory in fresh:
        did = str(directory["id"])
        # A directory whose previous attempt ended blocked/failed is RE-QUEUED
        # (reset in place), not re-inserted and never silently skipped — a past
        # cost-gate hold must not permanently fence a directory off.
        stale_id = requeueable.get(did)
        if stale_id is not None:
            row = await asyncio.to_thread(repo.requeue_citation, stale_id, campaign_id or None)
        else:
            row = await asyncio.to_thread(
                repo.queue_citation,
                client_id=body.client_id,
                client_name=name,
                directory_id=did,
                directory_name=str(directory.get("name", "")),
                business_profile_id=business_profile_id,
                submit_method=submit_method_label(directory),
                campaign_id=campaign_id or None,
            )
        if row is None:
            continue
        queued_ids.append(str(row["id"]))
        enqueue(str(row["id"]), client_id=body.client_id, correlation_id=campaign_id)

    settings = get_settings()
    estimated_cost = estimate_campaign_cost(fresh, settings)
    # Persist what actually happened — including the skip ledger that used to
    # evaporate with this HTTP response.
    if campaign_id:
        await asyncio.to_thread(
            repo.finalize_campaign,
            campaign_id,
            queued=len(queued_ids),
            estimated_cost=estimated_cost,
            skipped=list(selection.skipped),
        )
    await record_activity(
        actor, kind="content", action=f"queued a citation campaign ({len(queued_ids)} directories)",
        target=name, entity_type="client", entity_id=body.client_id,
    )
    return CitationCampaignResponse(
        campaign_id=campaign_id,
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


# --- campaign identity (0120): list + rollup --------------------------------------


@router.get("/campaigns", response_model=list[CampaignSummaryResponse])
async def list_campaigns(
    repo: CitationsRepoDep,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[CampaignSummaryResponse]:
    """Recent campaigns, newest first — how the workspace finds the current one
    without the operator holding an id."""
    rows = await asyncio.to_thread(repo.list_campaigns, client_id)
    return [CampaignSummaryResponse.from_row(r) for r in rows]


@router.get("/campaigns/{campaign_id}", response_model=CampaignRollupResponse)
async def campaign_rollup(
    campaign_id: str, repo: CitationsRepoDep, _user: ViewReports
) -> CampaignRollupResponse:
    """The campaign board: per-status and per-reason rollups plus every row, computed
    LIVE from the citations table so this can never disagree with the rows. ``stuck``
    counts in-flight rows whose updated_at sat unmoved past the staleness threshold —
    the "no worker is consuming this" signal."""
    campaign = await asyncio.to_thread(repo.get_campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    rows = await asyncio.to_thread(repo.campaign_citations, campaign_id)
    rollup = summarize_campaign_rows(rows, now=datetime.now(UTC))
    created = campaign.get("created_at")
    skipped_raw = campaign.get("skipped") or []
    return CampaignRollupResponse(
        id=str(campaign["id"]),
        client=str(campaign.get("client_name") or ""),
        created_at=created.isoformat() if isinstance(created, datetime) else str(created or ""),
        requested=int(campaign.get("requested") or 0),
        queued=int(campaign.get("queued") or 0),
        estimated_cost=float(campaign.get("estimated_cost") or 0.0),
        by_status=rollup["by_status"],
        by_blocked_reason=rollup["by_blocked_reason"],
        stuck=rollup["stuck"],
        live_urls=[CitationLiveUrl(**u) for u in rollup["live_urls"]],
        skipped=[CitationSkip(**sk) for sk in skipped_raw if isinstance(sk, dict)],
        rows=[
            CampaignRowResponse(
                id=str(r["id"]),
                directory=str(r.get("directory") or ""),
                submit_status=str(r.get("submit_status") or "not_started"),
                blocked_reason=str(r.get("blocked_reason") or ""),
                live_url=str(r.get("live_url") or ""),
                detail=str(r.get("error") or "")[:300],
            )
            for r in rows
        ],
    )


# --- gap analysis -----------------------------------------------------------------


@router.get("/gap-analysis", response_model=GapAnalysisResponse)
async def gap_analysis(
    repo: CitationsRepoDep,
    _user: QueueReader,
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
        directories=directories,
        existing_citations=existing,
        vertical=vertical,
        now=datetime.now(UTC),
    )
    return GapAnalysisResponse(
        client=str(client.get("name") or ""),
        has_nap=nap_source != "none",
        nap_source=nap_source,
        business_profile_id=str(profile["id"]) if profile is not None else None,
        resolved_vertical=vertical,
        existing_count=gap.existing_count,
        covered_count=gap.covered_count,
        in_flight_count=gap.in_flight_count,
        stuck=gap.stuck,
        missing_count=len(gap.missing),
        missing=[DirectoryResponse.from_row(d) for d in gap.missing],
        live_urls=[CitationLiveUrl(**u) for u in gap.live_urls],
        # 0129: `uncertain` discoveries to verify before building - neither covered
        # nor missing - plus the per-tier tallies. The bucket is uncertain-only by
        # construction, so the model's default tier stands.
        verify_first=[
            CitationVerifyFirst(directory=v.get("directory", ""), url=v.get("url", ""))
            for v in gap.verify_first
        ],
        skipped=[CitationSkip(**s) for s in gap.skipped],
        by_submit_status=gap.by_submit_status,
        by_nap_status=gap.by_nap_status,
        by_evidence_level=gap.by_evidence_level,
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
    plan = build_audit_plan(
        directories=directories,
        existing_citations=existing,
        vertical=vertical,
        now=datetime.now(UTC),
    )

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
    """The citation-ENGINE status board, post-bot-retirement (Phase 3, plan C1): the
    earned-spec count first (it now measures extension AUTOFILL coverage in the
    operator queue - no machine submits a form), then the human-queue lane stated as
    what it is, then each real API engine CONNECTED vs MISSING with the reason and the
    external-API caveat. Derived from settings + the earned-spec count - never a live
    probe, never a spend. The retired bot/solver/proxy rows are gone; their story
    lives in `integrations/citation_status.py`'s retirement record."""

    def _active_spec_count() -> int:
        from integrations.directory_specs import active_form_specs

        return len(active_form_specs())

    board = citation_engine_board(
        get_settings(),
        active_spec_count=await asyncio.to_thread(_active_spec_count),
    )
    return EngineStatusBoardResponse(
        connected_count=board.connected_count,
        total_count=board.total_count,
        machine_submittable_directories=board.machine_submittable_directories,
        whitelist_note=board.whitelist_note,
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

# Claim throttle: fail-OPEN like every authenticated-mutation limit (the caller is
# already bounded by auth + the lease model; the limiter is a brake on a runaway
# extension loop, never the reason a legitimate claim 500s during a cache blip).
# Wired by hand because `rate_limit()`'s dependency resolves `get_current_user`
# (bearer), and a claim may arrive on the operator token with no bearer identity.
_CLAIM_LIMIT_PER_MINUTE = 30


async def _claim_rate_limit(redis: RedisDep, user_id: str) -> None:
    window = int(time.time()) // 60
    await _enforce(
        redis,
        f"rl:citation_queue_claim:{user_id}:{window}",
        "citation_queue_claim",
        _CLAIM_LIMIT_PER_MINUTE,
        60,
        fail_closed=False,
    )


def get_form_drift_recorder() -> Callable[[str, str, dict[str, Any]], dict[str, Any] | None]:
    """Dependency: deactivate a directory's ACTIVE spec on operator-reported drift
    (overridable in tests).

    THE WIRING 0108 SHIPPED WITHOUT. `DirectorySpecsRepo.record_drift` existed with no
    caller, so an operator reporting `form_changed` - the strongest drift signal the
    platform receives - left the spec active, and the extension kept autofilling
    selectors a human just said are wrong. Fail-CLOSED now: the report deactivates the
    spec (`deactivated_reason = 'drift_detected'`), and re-earning it takes the full
    verify + first-live contract. No active spec is a clean no-op (returns None)."""

    def _record(
        user_id: str, directory_id: str, evidence: dict[str, Any]
    ) -> dict[str, Any] | None:
        repo = DirectorySpecsRepo(user_id)
        active = [r for r in repo.list_specs(directory_id=directory_id) if r.get("active")]
        if not active:
            return None
        return repo.record_drift(
            str(active[0]["id"]),
            selector="",  # the operator reports the FORM changed, not which selector
            evidence=evidence,
        )

    return _record


FormDriftRecorderDep = Annotated[
    Callable[[str, str, dict[str, Any]], dict[str, Any] | None],
    Depends(get_form_drift_recorder),
]


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


# Market code -> the country name a directory form's country field expects. The profile
# stores a market code (US/UK/CA/AU), not a spelled-out country, so a country dropdown
# has nothing to match against without this.
_MARKET_COUNTRY: dict[str, str] = {
    "US": "United States",
    "UK": "United Kingdom",
    "GB": "United Kingdom",
    "CA": "Canada",
    "AU": "Australia",
}


def _queue_fields(
    row: dict[str, Any], selectors: dict[str, str] | None = None
) -> list[QueueFieldValue]:
    """Every value the operator needs, pre-computed and labelled.

    Empty values are DROPPED rather than shown blank. A form asks for what it asks for;
    presenting an operator with eight empty boxes to puzzle over is exactly the friction
    the queue exists to remove, and a blank field is better discovered on the directory's
    own form than in our panel.

    ``selectors`` may be passed pre-computed (the session card serializer reads them
    twice - once for ``hasSpec``, once here - and the spec lookup is a DB read per
    directory); omitted, they are resolved exactly as before."""
    # Country from the business MARKET code (US/UK/CA/AU) — a form's country dropdown
    # has no value to fill otherwise, and the profile carries no free-text country.
    country = _MARKET_COUNTRY.get(str(row.get("bp_market") or "").upper(), "")
    pairs: list[tuple[str, str, Any]] = [
        ("business_name", "Business name", row.get("bp_business_name")),
        ("address_line1", "Address", row.get("bp_address_line1")),
        ("address_line2", "Address line 2", row.get("bp_address_line2")),
        ("city", "City", row.get("bp_city")),
        ("region", "State / region", row.get("bp_region")),
        ("postal_code", "Postcode", row.get("bp_postal_code")),
        ("country", "Country", country),
        ("phone", "Phone", row.get("bp_phone")),
        ("website_url", "Website", row.get("bp_website_url")),
        ("email", "Email", row.get("bp_email")),
        ("description", "Description", row.get("bp_description")),
    ]
    if selectors is None:
        selectors = _spec_selectors(row)
    out = [
        QueueFieldValue(key=k, label=label, value=str(v).strip(), selector=selectors.get(k, ""))
        for k, label, v in pairs
        if str(v or "").strip()
    ]
    # Split the category list into a primary CATEGORY and a SUB-CATEGORY so a form's
    # two-level category dropdowns each get their own value. Many directories ask for
    # both; a single comma-joined "categories" value never matched either dropdown.
    cats = [str(x).strip() for x in (row.get("bp_categories") or []) if str(x).strip()]
    if cats:
        out.append(
            QueueFieldValue(
                key="category", label="Category", value=cats[0],
                # Fall back to the legacy "categories" spec key so an earned spec keeps working.
                selector=selectors.get("category", selectors.get("categories", "")),
            )
        )
    if len(cats) > 1:
        out.append(
            QueueFieldValue(
                key="sub_category", label="Sub-category", value=cats[1],
                selector=selectors.get("sub_category", ""),
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
        directory_id=str(row.get("directory_id") or ""),
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
    """The queue at a glance, plus whatever this operator is already holding.

    `mine` has been on both this response model and the frontend type since the queue
    shipped, and nothing ever filled it. So the operator's in-hand item lived only in
    component state: a reload lost it, the row stayed claimed until its twenty-minute
    lease lapsed, and re-taking it bumped `human_attempts` - which tells the next
    person "someone has tried this before". The server always knew the answer.
    """
    stats, mine = await asyncio.gather(
        asyncio.to_thread(queue.queue_stats),
        asyncio.to_thread(queue.my_claims),
    )
    median = stats.get("median_seconds")
    return QueueBoardResponse(
        waiting=int(stats.get("waiting") or 0),
        in_progress=int(stats.get("in_progress") or 0),
        median_seconds=int(median) if median is not None else None,
        mine=[_queue_item(row) for row in mine],
    )


@router.post("/queue/claim", response_model=QueueItemResponse | None)
async def claim_queue_item(
    body: QueueClaimRequest,
    queue: CitationQueueRepoWriteDep,
    sessions: OperatorSessionsRepoWriteDep,
    actor: OperatorOrUserLead,
    redis: RedisDep,
) -> QueueItemResponse | None:
    """Take the next available item. Returns ``null`` when the queue is empty.

    REFUSED (409) while the caller holds an ACTIVE session (0130): a session already
    owns a batch of claims on this operator's behalf, and an ad-hoc claim beside it
    would split the lease accounting two ways. The check reads the same partial unique
    index that enforces one-active-session, and it lazily reaps a session whose
    heartbeat went silent - a crashed browser never fences an operator out of the
    queue."""
    try:
        active = await asyncio.to_thread(sessions.active_session)
    except Exception:
        # The refusal is a coordination guard, not a security boundary: if the session
        # table cannot be read the claim must still work (the lease model bounds it),
        # exactly like the fail-open rate limiter below.
        logger.warning("session_check_unavailable_failing_open")
        active = None
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "You have an active work session - take items through the session "
                "(the extension's batch view) or close it before claiming ad hoc."
            ),
        )
    await _claim_rate_limit(redis, actor.id)
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
    citation_id: str,
    body: QueueHeartbeatRequest,
    queue: CitationQueueRepoWriteDep,
    _user: OperatorOrUserWrite,
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
    citation_id: str,
    body: QueueHeartbeatRequest,
    queue: CitationQueueRepoWriteDep,
    _user: OperatorOrUserWrite,
) -> None:
    """Hand the item back without finishing it. The attempt still counts."""
    await asyncio.to_thread(queue.release_claim, citation_id, worked_seconds=body.worked_seconds)


@router.post("/queue/{citation_id}/complete", response_model=QueueCompleteResponse)
async def complete_queue_item(
    citation_id: str,
    body: QueueCompleteRequest,
    queue: CitationQueueRepoWriteDep,
    sessions: OperatorSessionsRepoWriteDep,
    actor: OperatorOrUserLead,
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
    confirmed = body.operator_confirmed
    directory = str(row.get("directory_name") or row.get("directory") or "")
    client_id = str(row.get("client_id")) if row.get("client_id") else None

    async def _record(
        *, submit_status: str, evidence: dict[str, Any], url: str,
        verification_method: str, mark_verified: bool, recheck_days: int | None, activity_meta: str,
    ) -> None:
        """Write the completion, run the post-terminal session hook, log the activity.
        Shared by all three accepted paths so the batch-release + audit trail are identical."""
        updated = await asyncio.to_thread(
            queue.complete_item, citation_id, live_url=url, submit_status=submit_status,
            evidence=evidence, worked_seconds=body.worked_seconds, note=body.note,
            verification_method=verification_method, mark_verified=mark_verified, recheck_days=recheck_days,
        )
        if updated is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Your claim on this item expired."
            )
        # POST-TERMINAL SESSION HOOK (0130): mark the session task submitted + run the
        # batch-release check. A broken hook is logged, never fails an accepted completion.
        try:
            await asyncio.to_thread(
                sessions.mark_citation_terminal, citation_id, "submitted", meta={"live_url": url}
            )
        except Exception:
            logger.exception("session_task_mark_failed", citation_id=citation_id)
        await record_activity(
            actor, kind="task", action="completed a citation listing", target=directory,
            entity_type="client", entity_id=client_id, meta=activity_meta,
        )

    # PATH 1 — no URL. Some directories expose no public listing URL; only completable
    # with an explicit operator confirmation, recorded as submitted (never `live`).
    if not live_url:
        if not confirmed:
            return QueueCompleteResponse(
                accepted=False, submit_status=str(row.get("submit_status") or ""), live_url="",
                reason="Paste the public listing URL. If this directory shows no public URL at all, "
                "use “No public URL — I submitted it”.",
                can_confirm=True,
            )
        await _record(
            submit_status="submitted",
            evidence={"verification": "human", "operator_confirmed": True, "matched_fields": [],
                      "reason": "operator confirmed; directory exposes no public listing URL"},
            url="", verification_method="human", mark_verified=False, recheck_days=None,
            activity_meta="operator-confirmed (no public URL)",
        )
        return QueueCompleteResponse(
            accepted=True, submit_status="submitted", live_url="", operator_confirmed=True,
            reason="Recorded as submitted (operator-confirmed). No public URL to auto-verify.",
        )

    # SSRF: the URL is operator-supplied and this fetch runs server-side.
    if not await asyncio.to_thread(is_public_url, live_url):
        return QueueCompleteResponse(
            accepted=False, submit_status=str(row.get("submit_status") or ""),
            live_url=live_url, reason="That is not a reachable public URL.",
        )

    probe = await asyncio.to_thread(http_liveness_probe, live_url)
    verdict = judge_liveness(
        probe,
        business_name=str(row.get("bp_business_name") or ""),
        phone=str(row.get("bp_phone") or ""),
        address_line1=str(row.get("bp_address_line1") or ""),
    )

    # PATH 2 — probe-verified LIVE (the default, unchanged): the page loaded and carried
    # the business. `verification_method='human'` default + verified timestamp + standard
    # re-check, exactly as before.
    if verdict.is_live:
        await _record(
            submit_status=verdict.status, evidence=verdict.evidence, url=live_url,
            verification_method="human", mark_verified=True, recheck_days=3,
            activity_meta=f"live at {live_url}",
        )
        return QueueCompleteResponse(
            accepted=True, submit_status=verdict.status, live_url=live_url,
            matched_fields=list(verdict.evidence.get("matched_fields") or []),
        )

    # PATH 3 — probe could NOT confirm. Default: refuse, but tell the panel it may be a
    # false negative the operator can override (can_confirm). If the operator DID confirm,
    # record as submitted / operator-confirmed (NOT live) with a short re-check window, so
    # they are never blocked by a page we cannot read and we never claim what we did not see.
    if not confirmed:
        return QueueCompleteResponse(
            accepted=False, submit_status=str(row.get("submit_status") or ""), live_url=live_url,
            reason=str(verdict.evidence.get("reason") or "the business was not found on that page"),
            matched_fields=list(verdict.evidence.get("matched_fields") or []), can_confirm=True,
        )
    await _record(
        submit_status="submitted",
        evidence={**verdict.evidence, "verification": "human", "operator_confirmed": True},
        url=live_url, verification_method="human", mark_verified=False, recheck_days=2,
        activity_meta=f"operator-confirmed at {live_url}",
    )
    return QueueCompleteResponse(
        accepted=True, submit_status="submitted", live_url=live_url, operator_confirmed=True,
        reason="Recorded as submitted (operator-confirmed). We could not read the page "
        "automatically; a re-check will retry it.",
    )


@router.post("/queue/{citation_id}/blocked", status_code=status.HTTP_204_NO_CONTENT)
async def block_queue_item(
    citation_id: str,
    body: QueueBlockedRequest,
    queue: CitationQueueRepoWriteDep,
    sessions: OperatorSessionsRepoWriteDep,
    actor: OperatorOrUserLead,
    record_drift: FormDriftRecorderDep,
) -> None:
    """Close an item as NOT done, with a machine-readable reason.

    This is the outcome operators will reach for most often and it must cost them
    nothing to report. The reasons are a closed vocabulary so the board can answer
    'which directories are wasting our time?' - which is what eventually removes a row
    from the offer list.

    `form_changed` additionally DEACTIVATES the directory's active spec (0108 drift,
    fail-closed): a human just said the form no longer matches what the spec describes,
    so the extension must stop autofilling those selectors until the spec is re-earned."""
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
    # POST-TERMINAL SESSION HOOK (0130): same contract as complete's - mark the
    # matching session task `blocked` and run the batch-release check; a broken hook
    # never turns an honest block report into a 500.
    try:
        await asyncio.to_thread(
            sessions.mark_citation_terminal, citation_id, "blocked",
            meta={"blocked_reason": body.reason},
        )
    except Exception:
        logger.exception("session_task_mark_failed", citation_id=citation_id)
    drifted: dict[str, Any] | None = None
    if body.reason == "form_changed" and row.get("directory_id"):
        try:
            drifted = await asyncio.to_thread(
                record_drift,
                actor.id,
                str(row["directory_id"]),
                {
                    "source": "operator_blocked",
                    "reason": "form_changed",
                    "detail": detail[:500],
                    "citation_id": citation_id,
                    "reported_at": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            # The operator's report is the primary record and it is already written;
            # a failed deactivation must not turn the block into a 500. It is logged
            # loudly because an active spec surviving a drift report is exactly the
            # fail-open state this wiring exists to close.
            logger.exception(
                "citation_drift_deactivation_failed",
                citation_id=citation_id, directory_id=str(row.get("directory_id")),
            )
    await record_activity(
        actor, kind="task", action="reported a citation as blocked",
        target=str(row.get("directory_name") or row.get("directory") or ""),
        entity_type="client",
        entity_id=str(row.get("client_id")) if row.get("client_id") else None,
        meta=(
            f"{body.reason}: {detail}"
            + (" - the directory's form spec was deactivated (drift)" if drifted else "")
        ),
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
    """Turn the spec on. Since the bot's retirement (0132 retired route B with it), an
    active spec means exactly one thing: the extension AUTOFILLS this directory's form
    in the operator queue - a person still reviews and submits.

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


# --- operator sessions (0130) -------------------------------------------------------
#
# The batch layer over the SAME queue: a session hands an operator 10 items at once,
# the extension opens every tab, and the next batch releases transactionally when the
# last item of the current one goes terminal. Nothing here writes evidence - the only
# evidence writers remain /queue/{id}/complete (probe) and /queue/{id}/blocked, which
# gained the post-terminal session hook above.
#
# Auth mirrors the queue exactly, plus the NAP rule: responses that carry canonical
# business-profile values (the task cards) additionally require `client_profile:read`
# on the extension path - the same hybrid GET /business-profiles applies.

# Module-level resolver OBJECTS (not inline factory calls) so tests can override them
# by identity, exactly as they override `resolve_operator`/`resolve_operator_write`.
#
# KIND-GENERALIZED GUARDS (0136). Sessions now come in two kinds, and a token may
# legitimately hold only ONE queue's scopes - so the shared machinery routes take an
# ANY-OF floor across the two kinds' FULL scope sets for the route's verb (bearer
# callers stay governed by their role, as everywhere else): the refusal is a
# deterministic 401 before any epoch/DB work. The handlers where the session KIND is
# known (create's body, the detail read's loaded row, the web2 block door) then
# enforce that kind's EXACT granular scope via `_refuse_kind_scope`: citation
# sessions need `citation_queue:<verb>` (+ `client_profile:read` when the payload
# carries the canonical NAP), web2_placement sessions need `web2_queue:<verb>`. The
# floor is honest because every session/task query is pinned to the caller's own
# operator_id - the widest cross-kind act is orchestrating the caller's OWN
# other-kind session, with zero evidence authority; the evidence doors (queue
# complete/blocked, the placement complete) each keep their exact single scope.
#
# Every session route declares its floor BEFORE the repo dependencies, so the floor
# is what refuses a wrong-scope extension token - the repos' own any-queue-scope
# guard is containment behind it, never the front door.

# Session SUMMARY reads (the list + session-clients counts: no NAP, no drafts).
resolve_session_reader = require_operator_scope_sets(
    ("citation_queue:read",), ("web2_queue:read",)
)
# Task-CARD reads: citation cards carry the canonical NAP, so that lane's set is
# queue read + profile read; web2 cards carry the client's own approved draft.
resolve_session_card_reader = require_operator_scope_sets(
    ("citation_queue:read", "client_profile:read"), ("web2_queue:read",)
)
resolve_session_write_floor = require_operator_scope_sets(
    ("citation_queue:write",), ("web2_queue:write",)
)
# Session creation returns batch-1 CARDS, so its floor is write + the card scopes.
resolve_session_create_floor = require_operator_scope_sets(
    ("citation_queue:write", "client_profile:read"), ("web2_queue:write",)
)
resolve_session_lead = require_operator_lead_over(resolve_session_write_floor)
resolve_session_creator = require_operator_lead_over(resolve_session_create_floor)

# Session summary reads (list + per-client counts).
SessionReader = Annotated[CurrentUser, Depends(resolve_session_reader)]
# Task-card reads (the detail board; the in-handler kind check refines further).
SessionCardReader = Annotated[CurrentUser, Depends(resolve_session_card_reader)]
# Non-lead session mutations (heartbeat, telemetry).
SessionWrite = Annotated[CurrentUser, Depends(resolve_session_write_floor)]
# Lead session mutations (close, skip/defer, the web2 block door).
SessionLead = Annotated[CurrentUser, Depends(resolve_session_lead)]
# Lead session CREATION (a claim-class mutation whose response carries cards).
SessionCreator = Annotated[CurrentUser, Depends(resolve_session_creator)]


def get_citations_repo_session(
    user: Annotated[CurrentUser, Depends(resolve_session_create_floor)],
) -> CitationsRepo:
    """CitationsRepo for session CREATION (client_name_for): bound to the same floor
    object as `SessionCreator`, so either credential reaches it, the credential
    resolves once per request, and the bar is exactly the creation route's own."""
    return CitationsRepo(user.id)


CitationsRepoSessionDep = Annotated[CitationsRepo, Depends(get_citations_repo_session)]


def get_offpage_repo_session(
    user: Annotated[CurrentUser, Depends(resolve_session_write_floor)],
) -> OffpageRepo:
    """OffpageRepo for the web2 BLOCK door: the plain `OffpageRepoDep` resolves
    bearer-only `get_current_user`, which would 401 the extension before the door's
    own SessionLead guard was consulted. Bound to the same write-floor object, so
    the credential resolves once and the lead gate stays the deciding guard."""
    return OffpageRepo(user.id)


OffpageRepoSessionDep = Annotated[OffpageRepo, Depends(get_offpage_repo_session)]

#: The kind-specific scope each verb needs on the EXTENSION path.
_KIND_SCOPES: dict[str, dict[str, str]] = {
    "citation": {"read": "citation_queue:read", "write": "citation_queue:write"},
    "web2_placement": {"read": "web2_queue:read", "write": "web2_queue:write"},
}


async def _refuse_kind_scope(
    x_operator_token: str | None, kind: str, *, write: bool, cards: bool = False
) -> None:
    """Refuse unless the presented extension token holds the SESSION KIND's exact scope
    (+ `client_profile:read` for citation card payloads, which carry the canonical
    NAP). Bearer callers pass untouched - their role already governed the floor.

    THE STATUS CODE IS LOAD-BEARING. This check used to answer 401 "Not authenticated"
    for a token that is perfectly valid and simply lacks one scope, and THAT is the
    refusal an operator actually hits: the route's scope FLOOR accepts either lane's
    set, so a citation-only token passes the floor and is stopped here, by the
    kind-specific check.

    The extension maps every 401 to `NeedsPairing` and shows the pairing screen. So an
    operator on the Web 2.0 tab was told to re-pair, re-paired, received the same
    citation-only scopes (`DEFAULT_MINT_SCOPES` withholds the web2 ones), and was sent
    back to the pairing screen - forever, with nothing ever naming the cause. Reported
    as a bug on 2026-09-12 and reproduced against production.

    403 is also simply the correct code: the holder IS authenticated (the principal
    verified), they are not permitted. Nothing is leaked by saying which scope is
    missing, because identity is already proven - and that is the one fact that lets
    the operator fix it.
    """
    if not x_operator_token:
        return
    principal = await asyncio.to_thread(operator_principal_of, x_operator_token)
    verb = "write" if write else "read"
    needed = [_KIND_SCOPES.get(kind, _KIND_SCOPES["citation"])[verb]]
    if kind == "citation" and cards:
        needed.append("client_profile:read")
    if principal is None:
        # A token that does not verify at all IS an authentication failure.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )
    missing = [s for s in needed if not principal.has(s)]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                f"This extension token cannot work the {kind!r} lane: it is missing "
                + ", ".join(missing)
                + ". Mint a token with that scope in the dashboard under Settings -> "
                "Extension (choose the lanes) - re-pairing the same scopes will not help."
            ),
        )

# Session creation throttle: fail-OPEN like the claim limiter (same reasoning - the
# caller is authenticated, lead-gated and lease-bounded; the limiter is a brake on a
# runaway extension loop, never the reason a legitimate session 500s).
_SESSION_CREATE_LIMIT_PER_MINUTE = 6


async def _session_rate_limit(redis: RedisDep, user_id: str) -> None:
    window = int(time.time()) // 60
    await _enforce(
        redis,
        f"rl:citation_session_create:{user_id}:{window}",
        "citation_session_create",
        _SESSION_CREATE_LIMIT_PER_MINUTE,
        60,
        fail_closed=False,
    )


def _task_card(row: dict[str, Any]) -> SessionTaskCard:
    """One session task card from the joined task+citation+directory+NAP row.

    FAIL-CLOSED on specs, by construction: `_spec_selectors` returns {} whenever no
    ACTIVE spec exists (or the whitelist read fails), so `hasSpec` is false and every
    field ships an empty selector - the panel then offers copy-buttons, never a
    fabricated Fill."""
    selectors = _spec_selectors(row)
    prohibited = ""
    if str(row.get("directory_route") or "").upper() == "F":
        prohibited = (
            "This directory's terms forbid automated submission and it should not be in "
            f"the queue. Do not submit. {row.get('directory_tos_source_url') or ''}"
        ).strip()
    return SessionTaskCard(
        task_id=str(row.get("task_id")),
        citation_id=str(row.get("id")),
        batch_no=int(row.get("batch_no") or 1),
        position=int(row.get("position") or 0),
        ui_state=str(row.get("ui_state") or "pending"),  # type: ignore[arg-type]
        directory=str(row.get("directory_name") or row.get("directory") or ""),
        directory_id=str(row.get("directory_id") or ""),
        directory_url=str(row.get("directory_url") or ""),
        add_url=str(row.get("directory_add_url") or ""),
        has_spec=bool(selectors),
        fields=_queue_fields(row, selectors=selectors),
        queued_because=str(row.get("blocked_reason") or "") or "prepared for a human to finish",
        prohibited_warning=prohibited,
        price_note=str(row.get("directory_price_note") or ""),
    )


def _web2_task_card(row: dict[str, Any]) -> Web2PlacementTaskCard:
    """One web2_placement task card from the joined task+property+platform+spec row.

    FAIL-CLOSED by construction, twice over: with no ACTIVE placement spec,
    `placement_spec` is NULL, so `hasSpec` is false, `fields` is empty (copy-blocks
    only - the extension never fills on a guess) and the Open button falls back to
    the platform's homepage rather than a fabricated editor URL."""
    spec = row.get("placement_spec") if isinstance(row.get("placement_spec"), dict) else None
    platform_row = {
        "homepage_url": str(row.get("platform_homepage_url") or ""),
    }
    selectors = spec_selectors(spec)
    blocks = copy_blocks_for(row, spec)
    values = {b["key"]: b["value"] for b in blocks}
    return Web2PlacementTaskCard(
        task_id=str(row.get("task_id")),
        web2_id=str(row.get("id")),
        batch_no=int(row.get("batch_no") or 1),
        position=int(row.get("position") or 0),
        ui_state=str(row.get("ui_state") or "pending"),  # type: ignore[arg-type]
        platform=str(row.get("platform") or ""),
        title=str(row.get("topic") or ""),
        editor_url=editor_url_for(spec, platform_row),
        anchor=str(row.get("anchor") or ""),
        target_url=str(row.get("target_url") or ""),
        has_spec=bool(selectors),
        copy_blocks=[Web2CopyBlock(**b) for b in blocks],
        fields=[
            QueueFieldValue(
                key=key, label=key.replace("_", " ").title(), value=values.get(key, ""),
                selector=selector,
            )
            for key, selector in selectors.items()
            if values.get(key, "")
        ],
    )


def _session_summary(
    row: dict[str, Any],
    tasks: list[SessionTaskCard] | list[Web2PlacementTaskCard] | None = None,
) -> dict[str, Any]:
    """The shared kwargs for OperatorSessionResponse/SessionDetailResponse."""

    def _iso(v: Any) -> str:
        return v.isoformat() if isinstance(v, datetime) else (str(v) if v else "")

    by_state: dict[str, int] = {}
    for t in tasks or []:
        by_state[t.ui_state] = by_state.get(t.ui_state, 0) + 1
    return {
        "id": str(row["id"]),
        "client": str(row.get("client_name") or ""),
        "client_id": str(row.get("client_id") or ""),
        "status": str(row.get("status") or "active"),
        "kind": str(row.get("kind") or "citation"),
        "batch_size": int(row.get("batch_size") or 10),
        "current_batch": int(row.get("current_batch") or 1),
        "total_batches": int(row.get("total_batches") or 1),
        "task_count": int(row.get("task_count") or (len(tasks) if tasks else 0)),
        "by_ui_state": by_state,
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "closed_at": _iso(row.get("closed_at")) or None,
    }


@router.get("/session-clients", response_model=list[SessionClientCount])
async def session_client_counts(
    user: SessionReader,
    sessions: OperatorSessionsRepoDep,
    x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
) -> list[SessionClientCount]:
    """Per-client session-able workload for the extension's client selector: queue rows
    waiting for a human, verify-first discoveries, candidate gaps - and (0136) parked
    extension-lane placements. Counts only - the full gap analysis stays a per-client
    read. The guard is the session floor (either queue's read scope) so a web2-only
    token can pick a client; bearer callers keep the pre-0136 `view_reports` bar."""
    if not x_operator_token and not role_has_perm(user.role, "view_reports"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Missing permission: view_reports"
        )
    rows = await asyncio.to_thread(sessions.client_work_counts)
    return [
        SessionClientCount(
            client_id=str(r.get("client_id") or ""),
            client=str(r.get("client_name") or ""),
            ready_for_human=int(r.get("ready") or 0),
            verify_first=int(r.get("verify_first") or 0),
            candidate_gaps=int(r.get("candidate_gaps") or 0),
            web2_placements=int(r.get("web2_placements") or 0),
        )
        for r in rows
    ]


@router.post("/sessions", response_model=SessionDetailResponse, status_code=status.HTTP_201_CREATED)
async def create_operator_session(
    body: SessionCreateRequest,
    actor: SessionCreator,
    sessions: OperatorSessionsRepoDep,
    repo: CitationsRepoSessionDep,
    redis: RedisDep,
    x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
) -> SessionDetailResponse:
    """Start a work session, batched, all one transaction.

    ``kind='citation'``: select this client's workable citations (from gaps, or an
    explicit list) and CLAIM batch 1; the cards carry the canonical NAP (hence
    `client_profile:read` on the extension path). ``kind='web2_placement'`` (0136):
    select the client's parked extension-lane properties; the cards carry the
    approved draft as copy-blocks (`web2_queue:write` on the extension path).

    One active session per operator (409 otherwise - the partial unique index is the
    enforcement, this route merely words the refusal). Already-claimed / in-session
    rows are excluded at selection, never fought over."""
    await _refuse_kind_scope(x_operator_token, body.kind, write=True, cards=True)
    await _session_rate_limit(redis, actor.id)
    name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    gaps = body.from_gaps
    params: dict[str, Any] = {
        "kind": body.kind,
        "batchSize": body.batch_size,
        **({"fromGaps": gaps.model_dump()} if gaps else {}),
        **({"citationIds": body.citation_ids} if body.citation_ids else {}),
    }
    try:
        session = await asyncio.to_thread(
            sessions.create_session,
            client_id=body.client_id,
            client_name=name,
            batch_size=body.batch_size,
            params=params,
            tiers=list(gaps.tiers) if gaps and gaps.tiers else None,
            limit=gaps.limit if gaps else 25,
            citation_ids=body.citation_ids,
            kind=body.kind,
        )
    except ActiveSessionExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active session - close it before starting another.",
        ) from exc
    except NoSessionWorkError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Nothing to work for this client right now - no unclaimed queue items, "
                "candidate gaps, or parked placements matched the selection."
            ),
        ) from exc
    session_id = str(session["id"])
    if body.kind == "web2_placement":
        web2_rows = await asyncio.to_thread(sessions.web2_task_rows, session_id)
        web2_cards = [_web2_task_card(r) for r in web2_rows]
        await record_activity(
            actor, kind="task",
            action=f"started a Web 2.0 placement session ({len(web2_cards)} tasks)",
            target=name, entity_type="client", entity_id=body.client_id,
        )
        full = await asyncio.to_thread(sessions.get_session, session_id)
        return SessionDetailResponse(
            **_session_summary(full or session, web2_cards), web2_tasks=web2_cards
        )
    task_rows = await asyncio.to_thread(sessions.session_task_rows, session_id)
    cards = [_task_card(r) for r in task_rows]
    await record_activity(
        actor, kind="task", action=f"started a citation session ({len(cards)} tasks)",
        target=name, entity_type="client", entity_id=body.client_id,
    )
    full = await asyncio.to_thread(sessions.get_session, session_id)
    return SessionDetailResponse(**_session_summary(full or session, cards), tasks=cards)


@router.get("/sessions", response_model=list[OperatorSessionResponse])
async def list_operator_sessions(
    _user: SessionReader,
    sessions: OperatorSessionsRepoDep,
    mine: bool = True,
    active: bool = False,
) -> list[OperatorSessionResponse]:
    """Session summaries (no task cards, so no NAP - the session read floor, either
    queue's read scope, suffices). `?mine=true&active=true` is how the extension and
    the dashboard find the caller's live session after a reload."""
    rows = await asyncio.to_thread(sessions.list_sessions, mine=mine, active=active)
    return [OperatorSessionResponse(**_session_summary(r)) for r in rows]


@router.get("/sessions/{session_id}", response_model=SessionDetailResponse)
async def get_operator_session(
    session_id: str,
    _user: SessionCardReader,
    sessions: OperatorSessionsRepoDep,
    x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
) -> SessionDetailResponse:
    """The full session board: every task card with its ui_state and batch number.

    Citation sessions carry spec fill fields + the canonical NAP (hence
    `client_profile:read` on the extension path); web2_placement sessions carry the
    approved drafts as copy-blocks (`web2_queue:read` on the extension path). The
    kind's exact scope is enforced AFTER the row is loaded - the floor guard already
    authenticated the caller, so a wrong-scope read refuses without leaking more
    than the session's existence to its own operator."""
    row = await asyncio.to_thread(sessions.get_session, session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    kind = str(row.get("kind") or "citation")
    await _refuse_kind_scope(x_operator_token, kind, write=False, cards=True)
    if kind == "web2_placement":
        web2_rows = await asyncio.to_thread(sessions.web2_task_rows, session_id)
        web2_cards = [_web2_task_card(r) for r in web2_rows]
        return SessionDetailResponse(
            **_session_summary(row, web2_cards), web2_tasks=web2_cards
        )
    task_rows = await asyncio.to_thread(sessions.session_task_rows, session_id)
    cards = [_task_card(r) for r in task_rows]
    return SessionDetailResponse(**_session_summary(row, cards), tasks=cards)


@router.post("/sessions/{session_id}/heartbeat", response_model=SessionHeartbeatResponse)
async def heartbeat_operator_session(
    session_id: str,
    body: QueueHeartbeatRequest,
    _user: SessionWrite,
    sessions: OperatorSessionsRepoDep,
) -> SessionHeartbeatResponse:
    """Extend the lease on every released, non-terminal task and bank the time worked -
    the per-item heartbeat's semantics, batched (the delta is SPREAD across the open
    items so total minutes stay honest; see the repo). 409 once the session is no
    longer this operator's active work."""
    result = await asyncio.to_thread(
        sessions.heartbeat, session_id, worked_seconds=body.worked_seconds
    )
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This session is not active (or not yours) - start a new one.",
        )
    return SessionHeartbeatResponse(
        ok=True, lease_seconds=SESSION_LEASE_SECONDS, extended=int(result.get("extended") or 0)
    )


@router.post("/sessions/{session_id}/close", response_model=OperatorSessionResponse)
async def close_operator_session(
    session_id: str, actor: SessionLead, sessions: OperatorSessionsRepoDep
) -> OperatorSessionResponse:
    """Explicit close: every held claim is released and the outcome recorded honestly -
    `completed` when all tasks went terminal, else `abandoned`. 404 when the session
    is not this operator's open work."""
    row = await asyncio.to_thread(sessions.close_session, session_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No open session of yours by that id.",
        )
    await record_activity(
        actor, kind="task", action=f"closed a citation session ({row.get('status')})",
        target=str(row.get("client_name") or ""),
    )
    full = await asyncio.to_thread(sessions.get_session, session_id)
    return OperatorSessionResponse(**_session_summary(full or row))


@router.post("/sessions/{session_id}/tasks/{task_id}/telemetry")
async def record_session_telemetry(
    session_id: str,
    task_id: str,
    body: SessionTelemetryRequest,
    _user: SessionWrite,
    sessions: OperatorSessionsRepoDep,
) -> dict[str, Any]:
    """The extension's ui_state report: FORWARD-ONLY within the non-terminal ladder.

    Terminal values are unrepresentable in the request schema (422 by construction);
    a backwards or repeated move is a 409. Telemetry carries ZERO authority - the
    citation's own status never moves here."""
    try:
        task = await asyncio.to_thread(
            sessions.record_telemetry, session_id, task_id,
            new_state=body.ui_state, detail=body.detail,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such task in an active session of yours.",
        )
    return {"ok": True, "taskId": task_id, "uiState": str(task.get("ui_state"))}


@router.post("/sessions/{session_id}/tasks/{task_id}/skip", response_model=SessionActionResponse)
async def skip_session_task(
    session_id: str,
    task_id: str,
    body: SessionSkipRequest,
    _user: SessionLead,
    sessions: OperatorSessionsRepoDep,
) -> SessionActionResponse:
    """Skip a task (terminal, server-written): claim released, reason recorded on the
    task, batch-release check run in the same transaction. The citation row itself is
    untouched - nothing was attempted, so nothing is asserted."""
    result = await asyncio.to_thread(sessions.skip_task, session_id, task_id, reason=body.reason)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such open task in an active session of yours.",
        )
    return SessionActionResponse(
        ok=True, session_id=session_id, task_id=task_id, state="skipped",
        batch_no=int(result.get("batchNo") or 0), released=int(result.get("released") or 0),
    )


@router.post("/sessions/{session_id}/tasks/{task_id}/defer", response_model=SessionActionResponse)
async def defer_session_task(
    session_id: str,
    task_id: str,
    _user: SessionLead,
    sessions: OperatorSessionsRepoDep,
) -> SessionActionResponse:
    """Defer a task to the TAIL: it leaves the current batch (terminal `deferred` for
    batch accounting), its claim is released, and it comes back `released` when its
    new tail batch is reached."""
    result = await asyncio.to_thread(sessions.defer_task, session_id, task_id)
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such open task in an active session of yours.",
        )
    return SessionActionResponse(
        ok=True, session_id=session_id, task_id=task_id, state="deferred",
        batch_no=int(result.get("batchNo") or 0), released=int(result.get("released") or 0),
    )


@router.post(
    "/sessions/{session_id}/tasks/{task_id}/blocked", response_model=SessionActionResponse
)
async def block_web2_session_task(
    session_id: str,
    task_id: str,
    body: SessionWeb2BlockRequest,
    actor: SessionLead,
    sessions: OperatorSessionsRepoDep,
    offpage: OffpageRepoSessionDep,
    x_operator_token: Annotated[str | None, Header(alias="X-Operator-Token")] = None,
) -> SessionActionResponse:
    """Block a WEB2 placement task (terminal, server-written, closed vocabulary - the
    citation queue's, reused so the "what wastes our time" rollup spans both lanes).

    WEB2-ONLY by construction: a citation task's block must travel through
    /queue/{id}/blocked, which also writes the citation row and the drift hook - a
    citation task here is a 404, never a thinner second door. The PROPERTY stays
    parked at `publishing`: an operator's obstacle is a fact about the attempt, not
    evidence about the placement, and un-approving reviewed work is a lead's
    decision on the dashboard.

    `form_changed` additionally DEACTIVATES the platform's ACTIVE placement spec
    (0136 drift, fail-closed - the same rule the citation door applies to 0108
    specs): a human just said the editor no longer matches what the spec describes,
    so the extension must stop offering its selectors until a revision is earned."""
    await _refuse_kind_scope(x_operator_token, "web2_placement", write=True)
    try:
        result = await asyncio.to_thread(
            sessions.block_web2_task, session_id, task_id,
            reason=body.reason, detail=body.detail,
        )
    except ValueError as exc:  # unreachable via the schema; belt for direct callers
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)
        ) from exc
    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No such open web2 placement task in an active session of yours.",
        )
    if body.reason == "form_changed" and result.get("web2Id"):
        # Best-effort, logged loudly on failure: the operator's block is the primary
        # record and is already written - an active spec surviving a drift report is
        # the fail-open state this hook closes, but it must never 500 the report.
        try:
            row = await asyncio.to_thread(offpage.get_web2, str(result["web2Id"]))
            matrix = (
                await asyncio.to_thread(
                    offpage.platform_matrix_for, str(row.get("platform") or "")
                )
                if row is not None
                else None
            )
            if matrix is not None:
                await asyncio.to_thread(
                    offpage.record_placement_spec_drift,
                    str(matrix.get("id") or ""),
                    selector="",
                    evidence={
                        "source": "operator_blocked",
                        "reason": "form_changed",
                        "detail": body.detail[:500],
                        "web2_id": str(result["web2Id"]),
                        "reported_by": actor.id,
                        "reported_at": datetime.now(UTC).isoformat(),
                    },
                )
        except Exception:
            logger.exception(
                "web2_placement_drift_deactivation_failed",
                task_id=task_id, web2_id=str(result.get("web2Id") or ""),
            )
    return SessionActionResponse(
        ok=True, session_id=session_id, task_id=task_id, state="blocked",
        batch_no=int(result.get("batchNo") or 0), released=int(result.get("released") or 0),
    )
