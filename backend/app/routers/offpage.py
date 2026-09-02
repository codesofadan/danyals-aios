"""Off-page module endpoints (7B): backlink + citation MONITORING and the Web 2.0
property ledger.

Reads require any provisioned staff (``view_reports``, which a portal client does
NOT hold - so clients are 403'd out of this namespace, mirroring tasks/milestones).
Writes (the citation Submit/Update actions and the toxic-backlink flagger) require a
LEAD (owner/admin/manager) - the same set the RLS insert/update policies gate to; the
app-layer 403 here is clean UX on top of that DB boundary. The paid-tier gate for the
off-page deliverable lives at the service layer, not here.

Responses are the frontend ``Backlink`` / ``Citation`` / ``Web2Property`` shapes
(``lib/offpage.ts``); the internal ``client_id`` never leaks. Every mutation offloads
the blocking psycopg call with ``asyncio.to_thread`` and records an activity entry
(kind=content, entity=client) so the off-page work keeps each client's context fresh.
The Web 2.0 surface is complete here: the property ledger and platform board (reads),
the single-property plan/approve pair, and the CAMPAIGN routes - estimate (prices and
schedules a request without creating anything), create (fans one request out into N
properties and starts drafting), and the campaign board. Nothing on this router
publishes: every path ends at the review gate, and only a lead's approve releases a
placement to the publish worker.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Callable
from datetime import UTC, datetime, time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from app.config import get_settings
from app.core.auth import CurrentUser, require_perm, require_role
from app.core.deps import RedisDep, SettingsDep
from app.core.pagination import PageDep
from app.db.offpage_repo import OffpageRepoDep
from app.logging_setup import get_logger
from app.schemas.offpage import (
    BacklinkResponse,
    BacklinkStatus,
    CitationActionRequest,
    CitationBulkRequest,
    CitationResponse,
    FlagToxicRequest,
    NapStatus,
    OffpageKpisResponse,
    Web2AccountCheckResponse,
    Web2AccountCreateRequest,
    Web2AccountResponse,
    Web2AnchorCheckRequest,
    Web2AnchorCheckResponse,
    Web2AuthorityTier,
    Web2AuthType,
    Web2CampaignApprovalResponse,
    Web2CampaignEstimateResponse,
    Web2CampaignHold,
    Web2CampaignRequest,
    Web2CampaignResponse,
    Web2CampaignStatus,
    Web2CatalogResponse,
    Web2ClientIdentityRequest,
    Web2ClientIdentityResponse,
    Web2PlacementResponse,
    Web2PlannedPropertyResponse,
    Web2PlanRequest,
    Web2PlatformCatalogResponse,
    Web2PlatformStatusResponse,
    Web2PropertyResponse,
    Web2ProvisionAdvanceRequest,
    Web2ProvisionItemResponse,
    Web2ProvisionStartRequest,
    Web2ReviewRequest,
    action_for,
)
from app.services.activity import record_activity

logger = get_logger(__name__)

router = APIRouter(tags=["offpage"])

# All six staff roles hold view_reports; a portal client does NOT (clients are
# confined out of the staff namespace, mirroring tasks.py / milestones.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Writes are lead-only (owner/admin/manager) - the RLS insert/update set. Owner
# auto-passes require_role.
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_CITATION_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Citation not found"
)
_WEB2_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Web 2.0 property not found"
)
_CLIENT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
)


def get_web2_write_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the Web 2.0 WRITE worker (overridable in tests).

    The worker task is imported lazily so the API process never pulls in the Celery
    task modules just to import this router (mirrors ``get_audit_enqueuer``)."""

    def _enqueue(web2_id: str) -> None:
        from workers.tasks.offpage import web2_write_job

        web2_write_job.delay(web2_id)

    return _enqueue


def get_web2_publish_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the Web 2.0 PUBLISH worker (overridable in tests)."""

    def _enqueue(web2_id: str) -> None:
        from workers.tasks.offpage import web2_publish_job

        web2_publish_job.delay(web2_id)

    return _enqueue


def get_web2_similarity_rechecker() -> Callable[[str], str]:
    """Dependency: re-run the cross-property similarity gate for one property NOW.

    A dependency rather than a direct call so it is overridable in tests (mirroring the
    enqueuers) and so this router keeps no hard import of the privileged store. Returns
    the machine-readable code (``""`` when clean, ``sim_unavailable:`` on any failure).
    """

    def _recheck(web2_id: str) -> str:
        if not web2_id:
            return "sim_unavailable:error"
        try:
            from app.db.offpage_repo import service_offpage_store
            from app.services import web2_gate

            store = service_offpage_store()
            # RE-LOAD through the PRIVILEGED store rather than scoring the RLS row the
            # endpoint already holds. Not defensive duplication: `load_web2` LEFT JOINs
            # the client's city in as `client_geo` and `OffpageRepo.get_web2` does not.
            # The gate MASKS the city before hashing, so scoring here with geo='' while
            # the corpus was fingerprinted with geo='Leeds' yields two different masks -
            # the hashes never line up, every comparison scores ~0, and the gate reports
            # a confident `pass` on an identical article while LOOKING fully wired. Both
            # sides must fingerprint through identical inputs or neither measures anything.
            row = store.load_web2(web2_id)
            if row is None:
                return "sim_unavailable:error"
            body_md = str(row.get("body_md") or "")
            if not body_md.strip():
                return ""  # nothing drafted yet; the status check already rejects this
            return web2_gate.evaluate_draft(
                store,
                get_settings(),
                web2_id=web2_id,
                row=row,
                body_md=body_md,
                client_name=str(row.get("client_name") or ""),
                geo=str(row.get("client_geo") or ""),
            ).code
        except Exception:
            return "sim_unavailable:error"

    return _recheck


Web2WriteEnqueuerDep = Annotated[Callable[[str], None], Depends(get_web2_write_enqueuer)]
Web2PublishEnqueuerDep = Annotated[Callable[[str], None], Depends(get_web2_publish_enqueuer)]
Web2SimilarityRecheckDep = Annotated[
    Callable[[str], str], Depends(get_web2_similarity_rechecker)
]


class FlagToxicResponse(BaseModel):
    """The outcome of a disavow-review flag pass: how many backlinks were moved into
    ``toxic``."""

    flagged: int


def _client_entity(row: dict[str, Any]) -> tuple[str | None, str | None]:
    """The context entity an off-page mutation touches - always the CLIENT the row
    belongs to (its world is what changed). A client-less row (should not happen for
    a live row) links nothing so the event is still recorded, just unlinked."""
    client_id = row.get("client_id")
    return ("client", str(client_id)) if client_id is not None else (None, None)


async def _record_per_client(
    actor: CurrentUser, rows: list[dict[str, Any]], *, action: str
) -> None:
    """Record ONE activity per distinct client touched by a batch mutation, so every
    affected client's context is refreshed (and the feed is not spammed per-row)."""
    seen: set[str] = set()
    for row in rows:
        client_id = row.get("client_id")
        if client_id is None:
            continue
        key = str(client_id)
        if key in seen:
            continue
        seen.add(key)
        await record_activity(
            actor, kind="content", action=action, target=row.get("client_name", ""),
            entity_type="client", entity_id=key,
        )


# --- backlinks ----------------------------------------------------------------


@router.get("/offpage/backlinks", response_model=list[BacklinkResponse])
async def list_backlinks(
    repo: OffpageRepoDep,
    page: PageDep,
    _user: ViewReports,
    status_filter: Annotated[BacklinkStatus | None, Query(alias="status")] = None,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[BacklinkResponse]:
    """The referring-domain profile (freshest first). ``status=toxic`` returns the
    disavow-review queue; ``status``/``clientId`` narrow the board."""
    rows = await asyncio.to_thread(
        repo.list_backlinks,
        status=status_filter,
        client_id=client_id,
        limit=page.limit,
        offset=page.offset,
    )
    return [BacklinkResponse.from_row(r) for r in rows]


@router.post("/offpage/backlinks/flag-toxic", response_model=FlagToxicResponse)
async def flag_toxic_backlinks(
    body: FlagToxicRequest, repo: OffpageRepoDep, actor: Lead
) -> FlagToxicResponse:
    """Flag every backlink at/above ``spamThreshold`` spam as ``toxic`` (queue them
    for a disavow review). Lead-only. Idempotent; returns how many were moved."""
    rows = await asyncio.to_thread(
        repo.flag_toxic_backlinks, spam_threshold=body.spam_threshold
    )
    await _record_per_client(actor, rows, action="flagged toxic backlinks for disavow")
    return FlagToxicResponse(flagged=len(rows))


# --- citations ----------------------------------------------------------------


@router.get("/offpage/citations", response_model=list[CitationResponse])
async def list_citations(
    repo: OffpageRepoDep,
    page: PageDep,
    _user: ViewReports,
    nap: Annotated[NapStatus | None, Query()] = None,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[CitationResponse]:
    """The local directory / NAP listings. ``nap``/``clientId`` narrow the board."""
    rows = await asyncio.to_thread(
        repo.list_citations,
        nap_status=nap,
        client_id=client_id,
        limit=page.limit,
        offset=page.offset,
    )
    return [CitationResponse.from_row(r) for r in rows]


@router.post("/offpage/citations/{citation_id}/action", response_model=CitationResponse)
async def act_on_citation(
    citation_id: str,
    body: CitationActionRequest,
    repo: OffpageRepoDep,
    actor: Lead,
) -> CitationResponse:
    """Mark ONE listing handled: a Submit (created a missing listing) or an Update
    (fixed drift) both resolve the NAP to ``consistent``. Lead-only; 404 if unknown."""
    row = await asyncio.to_thread(repo.get_citation, citation_id)
    if row is None:
        raise _CITATION_NOT_FOUND

    changes: dict[str, Any] = {"nap_status": "consistent", "action": action_for("consistent")}
    # A human acting on a listing (Submit a missing one, finish a bot-built handoff, or
    # re-sync a drift) is ASSERTING it is now live. Advance ANY not-yet-live submission
    # state to `submitted` so the row SETTLES to a done state. Without this a manually
    # handled row lingers at `queued`/`not_started` (there is no local worker to move
    # it), which renders as a permanent, no-op "Update" action. An already-`verified`
    # row keeps the stronger state.
    if row.get("submit_status") not in ("submitted", "verified"):
        changes["submit_status"] = "submitted"
    if body.note is not None:
        changes["note"] = body.note
    updated = await asyncio.to_thread(repo.update_citation, citation_id, changes)
    if updated is None:
        raise _CITATION_NOT_FOUND

    ent_type, ent_id = _client_entity(row)
    verb = "submitted a citation" if body.action == "Submit" else "updated a citation"
    await record_activity(
        actor, kind="content", action=verb, target=row.get("client_name", ""),
        entity_type=ent_type, entity_id=ent_id,
    )
    return CitationResponse.from_row(updated)


@router.post("/offpage/citations/bulk", response_model=list[CitationResponse])
async def bulk_update_citations(
    body: CitationBulkRequest, repo: OffpageRepoDep, actor: Lead
) -> list[CitationResponse]:
    """Mark many listings ``consistent`` in one shot (a batch Submit/Update). Only
    the rows RLS lets the caller see are affected. Lead-only. Records one activity per
    distinct client touched."""
    changes: dict[str, Any] = {"nap_status": "consistent", "action": action_for("consistent")}
    rows = await asyncio.to_thread(repo.bulk_update_citations, body.ids, changes)
    await _record_per_client(actor, rows, action="reconciled citations")
    return [CitationResponse.from_row(r) for r in rows]


# --- web 2.0 ------------------------------------------------------------------


@router.get("/offpage/web2", response_model=list[Web2PropertyResponse])
async def list_web2(
    repo: OffpageRepoDep,
    page: PageDep,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[Web2PropertyResponse]:
    """The Web 2.0 property ledger (newest-published first). Reads every placement -
    drafts, ones awaiting review, and live posts (status is internal; the UI sees the
    same 7 fields regardless)."""
    rows = await asyncio.to_thread(
        repo.list_web2, client_id=client_id, limit=page.limit, offset=page.offset
    )
    return [Web2PropertyResponse.from_row(r) for r in rows]


@router.get("/offpage/web2/catalog", response_model=Web2CatalogResponse)
async def web2_catalog(
    repo: OffpageRepoDep,
    _user: ViewReports,
    auth_type: Annotated[Web2AuthType | None, Query(alias="authType")] = None,
    authority_tier: Annotated[Web2AuthorityTier | None, Query(alias="authorityTier")] = None,
    automation_ready: Annotated[bool | None, Query(alias="automationReady")] = None,
) -> Web2CatalogResponse:
    """The Web 2.0 platform CATALOG (``public.web2_platforms``, 0062/0063): the curated
    target list of real web2 backlink properties the off-page automation works through -
    the web2 analogue of the citation-directory catalog. Reference data, so it is
    staff-readable (``view_reports``); a portal client is 403'd out of the namespace.

    Returns the rows plus a rollup header (total, how many ``automationReady`` - i.e.
    hold a real publisher class - and a per-``authType`` breakdown). ``authType`` /
    ``authorityTier`` / ``automationReady`` narrow the board."""
    rows = await asyncio.to_thread(
        repo.list_web2_platforms,
        auth_type=auth_type,
        authority_tier=authority_tier,
        automation_ready=automation_ready,
    )
    from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

    platforms = [Web2PlatformCatalogResponse.from_row(r) for r in rows]
    credential_fields = {
        name: list(fields) for name, fields in PLATFORM_CREDENTIAL_FIELDS.items() if fields
    }
    by_auth_type: dict[str, int] = {}
    for p in platforms:
        by_auth_type[p.auth_type] = by_auth_type.get(p.auth_type, 0) + 1
    return Web2CatalogResponse(
        total=len(platforms),
        automation_ready=sum(1 for p in platforms if p.automation_ready),
        by_auth_type=by_auth_type,
        platforms=platforms,
        credential_fields=credential_fields,
    )


@router.post("/offpage/web2/anchor-check", response_model=Web2AnchorCheckResponse)
async def check_web2_anchor(
    body: Web2AnchorCheckRequest, repo: OffpageRepoDep, _actor: ViewReports
) -> Web2AnchorCheckResponse:
    """Ask whether an anchor is usable, BEFORE anything is created or paid for.

    ``plan_web2`` already refuses an exact-match commercial anchor - but it refuses at
    the moment of submission, as a 422 the planning modal swallowed, so the operator
    saw a queued property that did not exist. This lets the form say so beside the
    field while they are still typing.

    Free by construction: no write, no enqueue, no outbound call (``check_anchor`` is
    pure). Hence ``view_reports`` rather than ``Lead`` - asking whether a string is a
    good anchor is not a privileged act, and gating it behind the write role would
    stop a specialist drafting a brief.

    The rule is NOT reimplemented client-side, deliberately: the brand exemption needs
    ``client_name`` from the database, and a second copy would drift from the one the
    plan route enforces - so the form could bless an anchor the write path then refuses.
    """
    name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND

    from app.services.web2_anchor import check_anchor

    verdict = check_anchor(
        body.anchor, target_url=body.target_url, topic=body.topic, client_name=name
    )
    return Web2AnchorCheckResponse(
        allowed=verdict.allowed,
        verdict=verdict.verdict,
        reason=verdict.reason,
        suggestion=verdict.suggestion,
    )


@router.post(
    "/offpage/web2/plan",
    response_model=Web2PropertyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def plan_web2(
    body: Web2PlanRequest,
    repo: OffpageRepoDep,
    actor: Lead,
    enqueue: Web2WriteEnqueuerDep,
) -> Web2PropertyResponse:
    """Queue a new Web 2.0 property (lead-only). Creates a ``draft`` placement and hands
    it to the write worker, which drafts the branded article and parks it at
    ``needs_review`` for a lead to approve - it is NEVER auto-published. 404s if the
    client is unknown/invisible; ``client_name`` is snapshotted so client_id never leaks."""
    name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND

    # THE SAME GUARDS THE CAMPAIGN PATH RUNS. This route creates a property and spends
    # real drafting money, and it used to run NONE of them: no eligibility, no connected
    # account, no anchor check. Two doors into one table with different rules is how a
    # placement lands on a platform the client may not use, or one holding no credential,
    # after the article has been written and paid for.
    selection = await asyncio.to_thread(
        _eligible_for, repo, body.client_id, [body.platform],
        acknowledged=body.acknowledge_platform_advisory,
    )
    if selection.advisories:
        # Not a refusal - a question, asked with the platform's own rule attached so the
        # answer is informed. The operator may use any platform the pipeline can drive.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                selection.advisories[0]
                + "  Re-submit with acknowledgePlatformAdvisory=true to use it anyway."
            ),
        )
    if not selection.allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                selection.blocked[0]
                if selection.blocked
                else f"{body.platform} cannot be used for this client."
            ),
        )

    # The one campaign guard this door still lacked: the burst cap. A campaign request
    # is capped at max_properties_per_client_campaign, but N calls to this route were
    # uncapped - the same burst through a different door.
    from app.services.web2_pacing import burst_refusal

    pacing_refusal = await asyncio.to_thread(
        lambda: burst_refusal(
            now=datetime.now(UTC),
            history=_history(repo, body.client_id),
            caps=_pacing_caps(repo),
        )
    )
    if pacing_refusal:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=pacing_refusal
        )

    # R2-14: an exact-match commercial anchor has no editorial justification, and catching
    # it at review means discarding paid work rather than preventing it.
    from app.services.web2_anchor import check_anchor

    verdict = check_anchor(
        body.anchor, target_url=body.target_url, topic=body.topic or "", client_name=name
    )
    if not verdict.allowed:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"{verdict.reason}"
                + (f" Try instead: {verdict.suggestion}" if verdict.suggestion else "")
            ),
        )

    # Seed the writer's grounding pack (mirrors the content job): first-hand proof so
    # the draft is gap-free instead of holding at [NEEDS:]. Blank lines dropped; an
    # empty pack simply degrades to [NEEDS:] exactly as before.
    def _lines(items: list[str]) -> list[str]:
        return [s.strip() for s in items if isinstance(s, str) and s.strip()]

    source_pack: dict[str, Any] = {"client_name": name}
    if _lines(body.proof_points):
        source_pack["proof_points"] = _lines(body.proof_points)
    if _lines(body.testimonials):
        source_pack["testimonials"] = _lines(body.testimonials)
    if _lines(body.unique_data):
        source_pack["unique_data"] = _lines(body.unique_data)
    if _lines(body.services):
        source_pack["services"] = _lines(body.services)
    row = await asyncio.to_thread(
        repo.create_web2,
        client_id=body.client_id,
        client_name=name,
        platform=body.platform,
        anchor=body.anchor,
        target_url=body.target_url,
        topic=(body.topic or body.anchor),
        page_type=body.page_type,
        framework=body.framework,
        source_pack=source_pack,
    )
    if row is None:  # RLS/insert rejected (should not happen for a lead)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Could not create the placement"
        )
    enqueue(str(row["id"]))
    await record_activity(
        actor, kind="content", action="planned a Web 2.0 property", target=name,
        entity_type="client", entity_id=body.client_id,
    )
    return Web2PropertyResponse.from_row(row)


def _is_scheduled_later(row: dict[str, Any]) -> bool:
    """True when this property's pacing slot is still in the future.

    A missing or past slot means "publish now" - the default and the immediate path. Only
    a genuinely future slot defers, so a row that never went through campaign planning
    behaves exactly as it did before campaigns existed.
    """
    slot = row.get("scheduled_for")
    if slot is None:
        return False
    stamp = slot if isinstance(slot, datetime) else None
    if stamp is None:
        return False
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=UTC)
    return stamp > datetime.now(UTC)


def _guard_similarity(row: dict[str, Any], body: Web2ReviewRequest, live_code: str) -> None:
    """Refuse an approval the cross-property similarity gate does not support.

    FAIL-CLOSED here, deliberately - the mirror of ``run_write``'s fail-open. At draft
    time a collision and a clean draft land in the same place, so a gate outage must not
    stop drafting. But this endpoint is the last step before a placement goes LIVE under
    a client's name, so an outage here means we do not know whether it duplicates
    something, and publishing on 'we could not check' is precisely the harm the gate
    exists to prevent.

    A recorded `warn` or `block` is passable only with an explicit
    ``acknowledge_similarity`` - and a `block` only while the enforcement switch is off
    (``settings.web2_similarity_enforce``), which is where it ships until the thresholds
    are calibrated against a graded golden set (R2 O-1).
    """
    # The LIVE verdict wins over the one recorded at draft time.
    #
    # Re-running at approval is the load-bearing check for campaigns, not a repeat of the
    # draft-time one. A campaign drafts N properties before a human approves any, so when
    # each was written none of its siblings was in the corpus and every one scored clean.
    # Fingerprints enter the corpus as properties go live, so the duplicate only becomes
    # visible HERE. Enforcing the frozen draft-time verdict would wave through an entire
    # campaign of identical articles, each honestly "clean" at the moment it was written.
    code = live_code or str(row.get("error") or "")
    if not code.startswith(("sim_warn:", "sim_block:", "sim_unavailable:")):
        return  # no similarity finding on this row (or a plain grounding-gap message)

    if code.startswith("sim_unavailable:"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "The cross-property similarity gate could not run for this placement "
                f"({code}). Re-draft it once the gate is available - approving now would "
                "publish without knowing whether it duplicates another property."
            ),
        )

    settings = get_settings()
    if code.startswith("sim_block:") and settings.web2_similarity_enforce:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"This draft duplicates an existing property ({code}). Re-draft it with "
                "different structure and wording; it cannot be approved as it stands."
            ),
        )

    if not body.acknowledge_similarity:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"The similarity gate flagged this placement ({code}). Review the "
                "colliding property, then re-submit with acknowledgeSimilarity=true to "
                "confirm this article is genuinely distinct."
            ),
        )


@router.post("/offpage/web2/{web2_id}/approve", response_model=Web2PropertyResponse)
async def approve_web2(
    web2_id: str,
    body: Web2ReviewRequest,
    repo: OffpageRepoDep,
    actor: Lead,
    enqueue: Web2PublishEnqueuerDep,
    recheck_similarity: Web2SimilarityRecheckDep,
) -> Web2PropertyResponse:
    """The human quality gate (lead-only). ``approve`` moves a ``needs_review`` draft to
    ``publishing`` and enqueues the publish worker (publish -> verify -> track);
    ``reject`` moves it to ``rejected``. 404 if unknown; 409 if it is not awaiting review
    (only a drafted, human-reviewed article may be published)."""
    row = await asyncio.to_thread(repo.get_web2, web2_id)
    if row is None:
        raise _WEB2_NOT_FOUND
    current = str(row.get("status") or "")
    if current != "needs_review":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Placement is not awaiting review (status={current})",
        )

    ent_type, ent_id = _client_entity(row)
    if body.action == "approve":
        live_code = await asyncio.to_thread(recheck_similarity, web2_id)
        _guard_similarity(row, body, live_code)
    if body.action == "reject":
        updated = await asyncio.to_thread(
            repo.update_web2_status, web2_id, {"status": "rejected"}
        )
        await record_activity(
            actor, kind="content", action="rejected a Web 2.0 property",
            target=row.get("client_name", ""), entity_type=ent_type, entity_id=ent_id,
        )
        return Web2PropertyResponse.from_row(updated or row)

    updated = await asyncio.to_thread(
        repo.update_web2_status, web2_id, {"status": "publishing"}
    )
    if updated is None:
        raise _WEB2_NOT_FOUND
    # Approval always moves the row to `publishing`; whether it goes out NOW depends on
    # its pacing slot. A future `scheduled_for` means the lead has said "yes, and on the
    # drip" - so the immediate enqueue is skipped and the release tick claims it when due.
    # This is exactly the content module's scheduled-publish shape (0072), reused rather
    # than reinvented so the drip inherits machinery that is already proven.
    if not _is_scheduled_later(updated):
        enqueue(web2_id)
    await record_activity(
        actor, kind="content", action="approved a Web 2.0 property",
        target=row.get("client_name", ""), entity_type=ent_type, entity_id=ent_id,
    )
    return Web2PropertyResponse.from_row(updated)


# --- Web 2.0 CAMPAIGNS ---------------------------------------------------------
#
# The unit of work the module was missing. Everything underneath already worked - 53
# publishers, a grounded generator, the similarity gate, pacing - but there was no way
# to ASK for thirty properties, so it meant thirty separate calls with no shared budget,
# no shared schedule, no single approval, and nothing that could answer "how is it
# going?". These four routes are that.


# The request the campaign path hands the per-property guard: an approve that carries NO
# acknowledgement, so a campaign-level decision can never acknowledge a collision on a
# property the operator has not looked at individually.
_CAMPAIGN_REVIEW = Web2ReviewRequest(action="approve")


def _pacing_caps(repo: Any) -> Any:
    from app.services.web2_pacing import PacingCaps

    return PacingCaps.from_row(repo.pacing_caps_row())


def _history(repo: Any, client_id: str) -> list[Any]:
    """Recent placements for pacing. A client who published yesterday does not start
    a new campaign from zero."""
    from app.services.web2_pacing import Placement

    out: list[Any] = []
    for row in repo.client_publish_history(client_id):
        when = row.get("scheduled_for") or row.get("published_at")
        if when is None:
            continue
        stamp = when if isinstance(when, datetime) else datetime.combine(when, time.min, tzinfo=UTC)
        out.append(
            Placement(
                published_at=stamp,
                web2_id=str(row.get("id") or ""),
                client_id=client_id,
                platform=str(row.get("platform") or ""),
                account_id=str(row.get("account_id") or "") or None,
            )
        )
    return out


def _eligible_for(
    repo: Any, client_id: str, selected: list[str], *, acknowledged: bool = False
) -> Any:
    """Narrow the operator's selection into plan / refuse / ask.

    Returns a ``SelectionVerdict``. Refusals are RETURNED rather than silently dropped:
    a selection quietly shrunk from thirty platforms to four is a lie the operator would
    discover weeks later, and the platform's own reason is what teaches the rule.

    ``acknowledged`` is the operator saying "I have read that platform's rule and I am
    choosing it anyway" - it moves the JUDGEMENT states (topical mismatch, unreviewed
    terms) into ``allowed``. It can never move a missing publisher or a missing
    credential, which are facts about the machine rather than opinions about fit.
    """
    from app.services.web2_eligibility import evaluate_catalog, resolve_selection

    scope = repo.client_web2_scope(client_id)
    # The connected set comes from ACCOUNTS, never from the operator's own selection.
    # Feeding `selected` back in declares every requested platform connected by
    # construction, so `not_connected` can never fire on the WRITE path: a campaign is
    # then planned, its properties created and its drafting PAID FOR against platforms
    # holding no credential, and the failure only surfaces at publish time - after the
    # spend, and after the operator was told it was scheduled.
    board = evaluate_catalog(
        repo.eligible_catalog(),
        client_scope=scope,
        connected_platforms=repo.connected_platforms_for(client_id),
    )
    return resolve_selection(board, selected, acknowledged=acknowledged)


def _build_plan(repo: Any, body: Web2CampaignRequest, client_name: str) -> Any:
    from app.services.web2_campaign import CampaignRefusedError, plan_campaign

    selection = _eligible_for(
        repo, body.client_id, list(body.platforms),
        acknowledged=body.acknowledge_platform_advisories,
    )
    allowed, refusals = selection.allowed, selection.blocked
    # An UNACKNOWLEDGED judgement platform stops the request and asks, rather than
    # being dropped from the plan behind the operator's back. Silently shrinking a
    # ten-platform selection to four is how the module taught operators that their
    # choices did not matter; the platform's own rule is quoted so the answer is
    # informed, and one acknowledgement covers the campaign.
    if selection.advisories:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                "These platforms need your explicit go-ahead for this client: "
                + "  ".join(selection.advisories)
                + "  Re-submit with acknowledgePlatformAdvisories=true to use them."
            ),
        )
    if not allowed and refusals:
        # The per-platform reasons are the whole value here. Falling through to the
        # planner's generic "restricted by their own content policies" would name the
        # wrong cause for a platform that is merely missing an account - sending the
        # operator to re-read a content policy when the fix is to connect a credential.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="No platform in this selection can be used. " + "  ".join(refusals),
        )
    settings = get_settings()
    try:
        plan = plan_campaign(
            now=datetime.now(UTC),
            client_id=body.client_id,
            client_name=client_name,
            requested_count=body.article_count,
            topics=body.topics,
            platforms=allowed,
            anchors=body.anchors,
            target_url=body.target_url,
            caps=_pacing_caps(repo),
            per_article_cost=settings.content_generate_cost_estimate,
            history=_history(repo, body.client_id),
            cost_ceiling_usd=body.cost_ceiling_usd,
        )
    except CampaignRefusedError as refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(refused)
        ) from refused
    plan.notes.extend(refusals)
    return plan


def _estimate_response(plan: Any) -> Web2CampaignEstimateResponse:
    return Web2CampaignEstimateResponse(
        count=plan.count,
        estimated_cost_usd=plan.estimated_cost_usd,
        projected_completion=(
            plan.projected_completion.isoformat() if plan.projected_completion else ""
        ),
        properties=[
            Web2PlannedPropertyResponse(
                platform=p.platform, topic=p.topic, anchor=p.anchor, framework=p.framework,
                scheduled_for=p.scheduled_for.isoformat() if p.scheduled_for else "",
            )
            for p in plan.properties
        ],
        notes=list(plan.notes),
    )


@router.get("/offpage/web2/platform-board", response_model=list[Web2PlatformStatusResponse])
async def web2_platform_board(
    repo: OffpageRepoDep,
    actor: ViewReports,
    client_id: Annotated[str, Query(alias="clientId", min_length=1)],
) -> list[Web2PlatformStatusResponse]:
    """The five-state platform board for one client (WEB2-012).

    Every catalogue row is returned, with a reason on the ones this client may not use.
    Hiding them would make the product look smaller than it is AND leave the operator
    guessing; showing them with the platform's own policy attached is what lets a
    50+ platform catalogue be offered honestly. Honesty cuts both ways: a row nobody
    has adjudicated reports ``not_reviewed`` (a safe default), never a fabricated
    policy verdict, and a row without publisher code reports ``not_supported``.
    """
    from app.services.web2_eligibility import evaluate_catalog

    name = await asyncio.to_thread(repo.client_name_for, client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    scope = await asyncio.to_thread(repo.client_web2_scope, client_id)
    rows = await asyncio.to_thread(repo.eligible_catalog)
    # From ACCOUNTS, never from the catalogue. Deriving "connected" from the catalogue
    # rows themselves marks every mapped platform connected, which makes `not_connected`
    # unreachable and shows a green "eligible" for platforms holding no credential at
    # all - sending an operator to publish somewhere the pipeline cannot authenticate.
    connected = await asyncio.to_thread(repo.connected_platforms_for, client_id)
    board = evaluate_catalog(rows, client_scope=scope, connected_platforms=connected)
    from app.services.web2_provisioning import GUIDES
    from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

    out: list[Web2PlatformStatusResponse] = []
    for v in board:
        # Both GUIDES and PLATFORM_CREDENTIAL_FIELDS are keyed by the publishing enum's
        # label; the catalogue name usually equals it, but instance-qualified rows
        # ("Mastodon (mastodon.social)") only resolve through platform_enum.
        guide = GUIDES.get(v.name) or (GUIDES.get(v.platform_enum) if v.platform_enum else None)
        credential_fields = PLATFORM_CREDENTIAL_FIELDS.get(v.name) or (
            PLATFORM_CREDENTIAL_FIELDS.get(v.platform_enum, ()) if v.platform_enum else ()
        )
        out.append(
            Web2PlatformStatusResponse(
                name=v.name, platform=v.platform_enum, status=v.status, reason=v.reason,
                authority=v.authority_tier,
                terms_checked_on=v.terms_checked_on,
                terms_source_url=v.terms_source_url,
                setup_url=guide.where if guide else "",
                setup_steps=guide.steps if guide else "",
                setup_cost=guide.cost if guide else "",
                setup_blocker=guide.blocker if guide else "",
                account_needed=guide.account_needed if guide else "",
                credential_fields=list(credential_fields),
            )
        )
    return out


@router.post("/offpage/web2/campaigns/estimate", response_model=Web2CampaignEstimateResponse)
async def estimate_web2_campaign(
    body: Web2CampaignRequest, repo: OffpageRepoDep, actor: Lead
) -> Web2CampaignEstimateResponse:
    """Price and schedule a campaign WITHOUT creating anything.

    Nothing is queued and nothing is spent. This is the screen where the operator sees
    that thirty articles is thirty metered drafting runs and about a month of publishing
    - both facts belong in front of them at the moment they decide.
    """
    name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    plan = await asyncio.to_thread(_build_plan, repo, body, name)
    return _estimate_response(plan)


@router.post(
    "/offpage/web2/campaigns",
    response_model=Web2CampaignResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_web2_campaign(
    body: Web2CampaignRequest,
    repo: OffpageRepoDep,
    actor: Lead,
    enqueue: Web2WriteEnqueuerDep,
) -> Web2CampaignResponse:
    """Create the campaign and its properties, and start drafting (lead-only).

    Each property is created exactly as a single planned placement is, so it inherits
    the whole existing pipeline unchanged: grounded drafting, the cost gate per call,
    the similarity gate, and the review hold. Nothing publishes here - the campaign
    parks at ``needs_approval`` for ONE operator decision.
    """
    name = await asyncio.to_thread(repo.client_name_for, body.client_id)
    if name is None:
        raise _CLIENT_NOT_FOUND
    plan = await asyncio.to_thread(_build_plan, repo, body, name)

    def _lines(items: list[str]) -> list[str]:
        return [s.strip() for s in items if isinstance(s, str) and s.strip()]

    # The REQUEST wins where it says something; the client's standing brief fills the
    # rest. Without this fallback the wizard starts empty for every campaign of every
    # client, so the grounding facts are retyped fifty times or - far more likely -
    # skipped, and the campaign parks unpublishable on [NEEDS:] gaps.
    stored = await asyncio.to_thread(repo.client_web2_identity, body.client_id)
    stored_brief = (stored or {}).get("web2_brief") or {}
    if not isinstance(stored_brief, dict):
        stored_brief = {}

    source_pack: dict[str, Any] = {"client_name": name}
    for key, values in (
        ("proof_points", body.proof_points), ("testimonials", body.testimonials),
        ("unique_data", body.unique_data), ("services", body.services),
    ):
        chosen = _lines(values)
        if not chosen:
            fallback = stored_brief.get(key)
            chosen = _lines(fallback) if isinstance(fallback, list) else []
        if chosen:
            source_pack[key] = chosen

    campaign = await asyncio.to_thread(
        repo.create_campaign,
        client_id=body.client_id, client_name=name, title=body.title or "Web 2.0 campaign",
        article_count=plan.count, platforms=[p.platform for p in plan.properties],
        pacing=body.pacing, drip_window_days=body.drip_window_days,
        target_url=body.target_url, cost_ceiling_usd=body.cost_ceiling_usd,
        created_by=actor.id,
    )
    if campaign is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Could not create the campaign"
        )
    campaign_id = str(campaign["id"])

    for planned in plan.properties:
        row = await asyncio.to_thread(
            repo.create_web2,
            client_id=body.client_id, client_name=name, platform=planned.platform,
            anchor=planned.anchor, target_url=body.target_url, topic=planned.topic,
            page_type="blog", framework=planned.framework, source_pack=source_pack,
        )
        if row is None:
            continue
        await asyncio.to_thread(
            repo.attach_property_to_campaign, str(row["id"]), campaign_id,
            planned.scheduled_for,
        )
        enqueue(str(row["id"]))

    await record_activity(
        actor, kind="content", action=f"planned a {plan.count}-property Web 2.0 campaign",
        target=name, entity_type="client", entity_id=body.client_id,
    )
    return Web2CampaignResponse.from_row(campaign, published=0, total=plan.count)


@router.post(
    "/offpage/web2/campaigns/{campaign_id}/approve",
    response_model=Web2CampaignApprovalResponse,
)
async def approve_web2_campaign(
    campaign_id: str,
    body: Web2ReviewRequest,
    repo: OffpageRepoDep,
    actor: Lead,
    enqueue: Web2PublishEnqueuerDep,
    recheck_similarity: Web2SimilarityRecheckDep,
) -> Web2CampaignApprovalResponse:
    """ONE operator decision for the whole campaign - and still one state transition per
    property underneath.

    The distinction is the point. Reviewing thirty drafts one at a time is the workflow
    this module was built to remove, but a BATCH publish is not the answer either:
    Tumblr's API License requires a per-post human action before an application posts on
    an account holder's behalf, so there is deliberately no endpoint that flips many rows
    with one write. This route iterates, re-running the similarity gate for each row
    exactly as the single-property route does, and every property that publishes does so
    through its own checked transition. The operator clicks once; the guarantees are
    unchanged.

    A property whose gate now BLOCKS is left at ``needs_review`` and reported in ``held``
    rather than silently approved with the rest - the whole value of the gate is that a
    bulk action cannot wave work past it.
    """
    campaign = await asyncio.to_thread(repo.get_campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    current = str(campaign.get("status") or "")
    if current not in ("needs_approval", "planning"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Campaign is not awaiting approval (status={current})",
        )

    props = await asyncio.to_thread(repo.campaign_properties, campaign_id)
    pending = [p for p in props if str(p.get("status") or "") == "needs_review"]

    approved: list[str] = []
    held: list[Web2CampaignHold] = []
    rejected: list[str] = []

    for prop in pending:
        web2_id = str(prop["id"])
        if body.action == "reject":
            await asyncio.to_thread(repo.update_web2_status, web2_id, {"status": "rejected"})
            rejected.append(web2_id)
            continue

        # Per-property re-check: the corpus may have grown since this draft was written
        # (its own campaign siblings were approved moments ago), so a collision that did
        # not exist at draft time can exist now.
        live_code = await asyncio.to_thread(recheck_similarity, web2_id)
        try:
            # NOTE the deliberately un-acknowledged request. A bulk acknowledgement would
            # let one checkbox wave every collision in the campaign through sight-unseen,
            # which is exactly the click-through the named acknowledgement exists to stop.
            # A collision must be acknowledged on the property it belongs to, through the
            # single-property route, after the operator has read THAT property's reason.
            _guard_similarity(prop, _CAMPAIGN_REVIEW, live_code)
        except HTTPException as blocked:
            held.append(
                Web2CampaignHold(
                    web2_id=web2_id,
                    topic=str(prop.get("topic") or ""),
                    platform=str(prop.get("platform") or ""),
                    reason=str(blocked.detail),
                )
            )
            continue

        updated = await asyncio.to_thread(
            repo.update_web2_status, web2_id, {"status": "publishing"}
        )
        if updated is None:
            continue
        if not _is_scheduled_later(updated):
            enqueue(web2_id)
        approved.append(web2_id)

    # The campaign's own status follows what actually happened, never the intent. If any
    # property is still held, the campaign is NOT simply "scheduled" - saying so would be
    # the partial-delivery-reported-as-success defect this module keeps guarding against.
    next_status: Web2CampaignStatus
    if body.action == "reject":
        next_status = "cancelled"
    elif held:
        next_status = "needs_approval"
    else:
        next_status = "scheduled"
    now = datetime.now(UTC)
    await asyncio.to_thread(
        repo.update_campaign,
        campaign_id,
        {"status": next_status, "approved_by": actor.id, "approved_at": now},
    )
    await record_activity(
        actor,
        kind="content",
        action=(
            f"rejected a Web 2.0 campaign ({len(rejected)} properties)"
            if body.action == "reject"
            else f"approved a Web 2.0 campaign ({len(approved)} properties)"
        ),
        target=str(campaign.get("client_name") or ""),
        entity_type="client",
        entity_id=str(campaign.get("client_id") or "") or None,
    )
    return Web2CampaignApprovalResponse(
        campaign_id=campaign_id,
        status=next_status,
        approved=len(approved),
        held=held,
        rejected=len(rejected),
    )


@router.get("/offpage/web2/campaigns", response_model=list[Web2CampaignResponse])
async def list_web2_campaigns(
    repo: OffpageRepoDep,
    actor: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[Web2CampaignResponse]:
    rows = await asyncio.to_thread(repo.list_campaigns, client_id=client_id)
    out: list[Web2CampaignResponse] = []
    for row in rows:
        props = await asyncio.to_thread(repo.campaign_properties, str(row["id"]))
        out.append(_campaign_response(row, props))
    return out


@router.get("/offpage/web2/campaigns/{campaign_id}", response_model=Web2CampaignResponse)
async def get_web2_campaign(
    campaign_id: str, repo: OffpageRepoDep, actor: ViewReports
) -> Web2CampaignResponse:
    row = await asyncio.to_thread(repo.get_campaign, campaign_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    props = await asyncio.to_thread(repo.campaign_properties, campaign_id)
    return _campaign_response(row, props)


@router.get(
    "/offpage/web2/campaigns/{campaign_id}/placements",
    response_model=list[Web2PlacementResponse],
)
async def list_campaign_placements(
    campaign_id: str, repo: OffpageRepoDep, actor: ViewReports
) -> list[Web2PlacementResponse]:
    """Every placement in a campaign, in full - what was built, where it lives, and
    whether the link is genuinely on the page.

    This is the report the module was missing. A campaign could be planned, drafted,
    approved and published, and there was still no way to answer a client asking "so
    where are my links?" - the facts were all in the row and none of them were reachable.
    """
    campaign = await asyncio.to_thread(repo.get_campaign, campaign_id)
    if campaign is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Campaign not found")
    rows = await asyncio.to_thread(repo.campaign_placements, campaign_id)
    return [Web2PlacementResponse.from_row(r) for r in rows]


def _account_fetcher() -> Any:
    """The real HTTP seam for credential verification (read-only calls)."""
    import httpx

    def fetch(req: Any) -> tuple[int, str]:
        # follow_redirects=False ON PURPOSE: a credential check must see the API's own
        # answer. Following a redirect lands on whatever page the platform points at -
        # typically docs or an announcement - which answers 200 and makes a retired
        # endpoint look authenticated.
        with httpx.Client(timeout=25.0, follow_redirects=False) as client:
            resp = client.request(req.method, req.url, headers=req.headers, json=req.json_body)
        return resp.status_code, resp.text[:4000]

    return fetch


def _credential_for(row: dict[str, Any]) -> dict[str, str]:
    """Open the sealed credential for verification only. Never returned to a caller."""
    from app.services.vault import find_secret

    raw = find_secret(
        provider=str(row.get("vault_provider") or ""), label=str(row.get("vault_label") or "")
    )
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return {str(k): str(v) for k, v in parsed.items()} if isinstance(parsed, dict) else {}


@router.post(
    "/offpage/web2/accounts",
    response_model=Web2AccountResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_web2_account(
    body: Web2AccountCreateRequest, repo: OffpageRepoDep, actor: Lead
) -> Web2AccountResponse:
    """Register a publishing account and seal its credential (lead-only).

    WHY THIS EXISTS. Registration was CLI-only, while the board's empty state told the
    operator to "register it here" - a promise the UI could not keep, leaving onboarding
    an engineer's job and the operator stuck on a screen with no action.

    The validation is NOT reimplemented here. ``build_spec`` is the same function the CLI
    calls, so the R2-08 identity rules (no platform slug or hex run in a per-client
    handle, no shared catch-all domain behind a client account) hold identically whoever
    registers. Two copies of those rules would drift, and the drift would show up as a
    footprint months later.

    The credential is sealed and never read back - it appears in no response, no log and
    no error. A refusal names the RULE, never the value.
    """
    from app.cli.web2_accounts import (
        HandleRejectedError,
        _shared_domains,
        build_spec,
        insert_account,
    )
    from app.services.vault import add_key
    from integrations.web2_credentials import VAULT_KIND_CLIENT_ACCESS, vault_provider_for
    from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

    try:
        spec = await asyncio.to_thread(
            lambda: build_spec(
                platform=body.platform,
                ownership=body.ownership,
                handle=body.handle,
                client_id=body.client_id or None,
                registration_email=body.email,
                property_url=body.property_url,
                max_properties=body.max_properties,
                credential={k: v for k, v in body.credential.items() if str(v).strip()},
                shared_domains=_shared_domains(),
            )
        )
    except (HandleRejectedError, ValueError) as refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(refused)
        ) from refused

    account_id = await asyncio.to_thread(insert_account, spec)
    if spec.credential:
        await asyncio.to_thread(
            add_key,
            provider=vault_provider_for(spec.platform),
            label=account_id,
            secret=json.dumps(spec.credential),
            kind=VAULT_KIND_CLIENT_ACCESS,
        )
    row = await asyncio.to_thread(repo.get_web2_account, account_id)
    if row is None:  # the insert returned an id, so this is unreachable in practice
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="the account was created but could not be read back",
        )
    required = list(PLATFORM_CREDENTIAL_FIELDS.get(spec.platform, ()))
    return Web2AccountResponse.from_row(
        row, required=required, complete=not spec.missing_fields()
    )


_IDENTITY_VAULT_PROVIDER = "web2:mailbox"


def _identity_response(row: dict[str, Any]) -> Web2ClientIdentityResponse:
    """Shape one identity row, resolving whether a mailbox password is actually held.

    The vault is CONSULTED rather than trusting the row's label column: a label written
    while the seal failed would otherwise report a ready mailbox that cannot open, and
    the builder would queue signups it can never verify.
    """
    from app.services.vault import find_secret

    label = str(row.get("web2_imap_vault_label") or "")
    provider = str(row.get("web2_imap_vault_provider") or "")
    held = bool(label and provider and find_secret(provider=provider, label=label))
    return Web2ClientIdentityResponse.from_row(row, password_held=held)


@router.get(
    "/offpage/web2/clients/{client_id}/identity",
    response_model=Web2ClientIdentityResponse,
)
async def get_web2_client_identity(
    client_id: str, repo: OffpageRepoDep, _actor: ViewReports
) -> Web2ClientIdentityResponse:
    """The standing publishing identity for one client - who its accounts are, where
    their verification mail lands, and whether the builder can read that mailbox.

    Never returns the mailbox password, only whether one is sealed."""
    row = await asyncio.to_thread(repo.client_web2_identity, client_id)
    if row is None:
        raise _CLIENT_NOT_FOUND
    return await asyncio.to_thread(_identity_response, row)


@router.put(
    "/offpage/web2/clients/{client_id}/identity",
    response_model=Web2ClientIdentityResponse,
)
async def put_web2_client_identity(
    client_id: str, body: Web2ClientIdentityRequest, repo: OffpageRepoDep, actor: Lead
) -> Web2ClientIdentityResponse:
    """Set the identity every future signup for this client reuses (lead-only).

    THE RULE THIS ENFORCES, and why it is not merely advice: a per-client account must
    not register on the agency's shared catch-all domain. Aliases minted per (platform,
    client) on one domain share a platform prefix, a client-id hash and a registrant
    domain, so suspending ONE account hands a trust-and-safety team the query that finds
    every other client (R2-08). That footprint is invisible to the similarity gate and
    no content quality fixes it, so the refusal is structural rather than a warning.

    The mailbox password is sealed into the vault and never read back. A blank password
    LEAVES an existing seal untouched - dropping a working credential because a form
    round-tripped an empty field is a silent failure, so clearing is explicit.
    """
    from app.cli.web2_accounts import _shared_domains
    from app.services.vault import add_key

    existing = await asyncio.to_thread(repo.client_web2_identity, client_id)
    if existing is None:
        raise _CLIENT_NOT_FOUND

    email = body.contact_email.strip()
    if email:
        domain = email.rpartition("@")[2].lower()
        if not domain or "@" not in email:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"{email!r} is not an email address.",
            )
        shared = {d.lower() for d in await asyncio.to_thread(_shared_domains) if d}
        if domain in shared:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    f"{domain} is the agency's shared catch-all. A per-client account "
                    "must register on the CLIENT's own domain - one suspension on a "
                    "shared domain exposes every client that shares it (R2-08). Use an "
                    "address on the client's domain, or leave this blank."
                ),
            )

    label = str(existing.get("web2_imap_vault_label") or "")
    provider = str(existing.get("web2_imap_vault_provider") or "")
    if body.clear_imap_password:
        label, provider = "", ""
    elif body.imap_password.strip():
        label = label or f"{client_id}:mailbox"
        provider = _IDENTITY_VAULT_PROVIDER
        await asyncio.to_thread(
            add_key,
            provider=provider,
            label=label,
            secret=body.imap_password.strip(),
            kind="client_access",
        )

    def _clean(values: list[str]) -> list[str]:
        return [v.strip() for v in values if isinstance(v, str) and v.strip()]

    brief = {
        "proof_points": _clean(body.proof_points),
        "testimonials": _clean(body.testimonials),
        "unique_data": _clean(body.unique_data),
        "services": _clean(body.services),
    }
    await asyncio.to_thread(repo.set_client_web2_brief, client_id, brief)

    row = await asyncio.to_thread(
        repo.set_client_web2_identity,
        client_id,
        handle_base=body.handle_base.strip(),
        contact_email=email,
        imap_host=body.imap_host.strip(),
        imap_port=body.imap_port,
        imap_user=body.imap_user.strip(),
        vault_provider=provider,
        vault_label=label,
    )
    if row is None:
        raise _CLIENT_NOT_FOUND
    await record_activity(
        actor, kind="client", action="set the Web 2.0 publishing identity",
        target=str(row.get("name") or ""), entity_type="client", entity_id=client_id,
    )
    return await asyncio.to_thread(_identity_response, row)


@router.post(
    "/offpage/web2/provisioning",
    response_model=list[Web2ProvisionItemResponse],
    status_code=status.HTTP_201_CREATED,
)
async def start_web2_provisioning(
    body: Web2ProvisionStartRequest, repo: OffpageRepoDep, actor: Lead
) -> list[Web2ProvisionItemResponse]:
    """Queue account creation for one client across N platforms (lead-only).

    THE UNIT OF WORK THIS ADDS. Before this, provisioning nine platforms for a client
    was nine unrelated form posts with no shared state - nothing recorded an account we
    INTENDED, so there was no progress to resume, nothing to hand over, and no answer to
    "what is left?". At one client that is friction; at twenty it is why the module sat
    idle with four platforms connected.

    Idempotent: a platform already in flight is reported as skipped rather than
    duplicated, so re-running the builder after connecting two accounts is safe.
    """
    from app.services.web2_provisioning import GUIDES
    from app.services.web2_provisioning_queue import IdentityFacts, plan_items

    identity_row = await asyncio.to_thread(repo.client_web2_identity, body.client_id)
    if identity_row is None:
        raise _CLIENT_NOT_FOUND
    identity = IdentityFacts.from_row(identity_row)
    existing = await asyncio.to_thread(repo.list_provision_items, body.client_id)
    plan = plan_items(body.platforms, identity=identity, existing=existing)

    created: list[dict[str, Any]] = []
    for entry in plan:
        if entry.get("action") != "queued":
            continue
        platform = str(entry["platform"])
        guide = GUIDES.get(platform)
        row = await asyncio.to_thread(
            repo.create_provision_item,
            client_id=body.client_id,
            platform=platform,
            lane=str(entry["lane"]),
            status=str(entry["status"]),
            handle=str(entry["handle"]),
            registration_email=str(entry["registration_email"]),
            signup_url=guide.where if guide else "",
            note=str(entry["note"]),
        )
        if row is not None:
            created.append(row)

    if created:
        await record_activity(
            actor, kind="client",
            action=f"queued {len(created)} Web 2.0 account(s) for setup",
            target=str(identity_row.get("name") or ""),
            entity_type="client", entity_id=body.client_id,
        )
    rows = await asyncio.to_thread(repo.list_provision_items, body.client_id)
    return [Web2ProvisionItemResponse.from_row(r) for r in rows]


_WEB2_OAUTH_STATE_TTL = 600  # 10 minutes - plenty for a consent screen


def _web2_oauth_state_key(state: str) -> str:
    return f"web2:oauth:{state}"


@router.get("/offpage/web2/provisioning/{item_id}/connect")
async def connect_web2_provisioning(
    item_id: str,
    repo: OffpageRepoDep,
    redis: RedisDep,
    settings: SettingsDep,
    actor: Lead,
) -> dict[str, Any]:
    """Start OAuth for one queue item, or say why it cannot run (lead-only).

    OAuth replaces the token hunt, not the signup: the ACCOUNT must already exist,
    because these platforms' own terms require a human to create it. What consent
    removes is the operator copying a token out of a developer console.

    HOLDS rather than fails when no app is registered for the platform, so an
    unconfigured platform reads as "not set up yet" instead of a broken button.
    """
    from app.services.web2_oauth import authorize_url, availability

    row = await asyncio.to_thread(repo.get_provision_item, item_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provisioning item not found"
        )
    platform = str(row.get("platform") or "")
    ready, reason = availability(platform, settings)
    redirect_uri = settings.web2_oauth_redirect_uri or ""
    if not ready or not redirect_uri:
        return {
            "held": True,
            "reason": reason or "No OAuth redirect URI is configured for Web 2.0.",
            "authorizeUrl": None,
        }

    state = secrets.token_urlsafe(32)
    payload = json.dumps({"item_id": item_id, "platform": platform, "actor_id": actor.id})
    await redis.set(
        _web2_oauth_state_key(state), payload.encode(), ex=_WEB2_OAUTH_STATE_TTL
    )
    return {
        "held": False,
        "reason": "",
        "authorizeUrl": authorize_url(
            platform, settings, state=state, redirect_uri=redirect_uri
        ),
    }


@router.get("/offpage/web2/oauth/callback", include_in_schema=False)
async def web2_oauth_callback(
    redis: RedisDep,
    settings: SettingsDep,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    """The platform's redirect back to us - UNAUTHENTICATED by necessity.

    The ``state`` token is the capability: single-use, ten-minute TTL, and mintable only
    by an already-authenticated lead's ``/connect`` call. It is deleted before the
    exchange, so a replayed callback cannot re-run one.
    """
    return_to = "/admin/web2"
    if error or not (code and state):
        return RedirectResponse(f"{return_to}?web2Connect=error")

    raw = await redis.get(_web2_oauth_state_key(state))
    if raw is None:
        return RedirectResponse(f"{return_to}?web2Connect=expired")
    await redis.delete(_web2_oauth_state_key(state))  # single-use, even if the rest fails

    try:
        payload = json.loads(raw)
        item_id = str(payload["item_id"])
        platform = str(payload["platform"])
        credential = await _exchange_web2_oauth(platform, settings, code=code)
        if not credential:
            logger.error("web2_oauth_no_token", platform=platform)
            return RedirectResponse(f"{return_to}?web2Connect=error")
        await asyncio.to_thread(_finish_web2_oauth_item, item_id, credential)
    except Exception:
        logger.exception("web2_oauth_callback_failed")
        return RedirectResponse(f"{return_to}?web2Connect=error")

    return RedirectResponse(f"{return_to}?web2Connect=success")


async def _exchange_web2_oauth(
    platform: str, settings: Any, *, code: str
) -> dict[str, str]:
    """Trade the consent code for a token and shape it as the publisher's credential."""
    import httpx

    from app.services.web2_oauth import credential_from_tokens, exchange_payload

    url, form = exchange_payload(
        platform, settings, code=code, redirect_uri=settings.web2_oauth_redirect_uri or ""
    )
    if not url:
        return {}

    def _post() -> dict[str, Any]:
        with httpx.Client(timeout=25.0, follow_redirects=False) as http:
            resp = http.post(url, data=form)
            resp.raise_for_status()
            parsed = resp.json()
        return parsed if isinstance(parsed, dict) else {}

    tokens = await asyncio.to_thread(_post)
    return credential_from_tokens(platform, tokens)


def _finish_web2_oauth_item(item_id: str, credential: dict[str, str]) -> None:
    """Seal the consented token against the queue item.

    The item lands at ``awaiting_credential`` with the token already held rather than at
    ``live``, because most of these platforms still need one operator-supplied field the
    consent screen cannot provide - a blog id or site host. Marking it live here would
    register an account the publisher cannot actually address.
    """
    from app.db.database import privileged_connection

    with privileged_connection() as cur:
        cur.execute(
            "update public.web2_provision_items "
            "set status = 'awaiting_credential', note = %s "
            "where id = %s and status <> 'cancelled'",
            (
                "Connected. Add the remaining field (blog id / site) to finish.",
                item_id,
            ),
        )


@router.post("/offpage/web2/provisioning/run")
async def run_web2_provisioning_tick(_actor: Lead) -> dict[str, Any]:
    """Advance every queue item that can move without a human (lead-only).

    Two jobs: mint the accounts whose platforms have a real signup API, and read each
    client's own mailbox ONCE for confirmation mail that has arrived. It never drives a
    browser through a signup form - that is a terms breach on the platforms that matter,
    not a missing feature.

    Runs on demand rather than on a schedule because beat is parked by standing owner
    instruction; scheduling it later changes only WHO calls this.
    """
    from workers.tasks.offpage import execute_web2_provision_tick

    return await asyncio.to_thread(execute_web2_provision_tick)


@router.get("/offpage/web2/provisioning", response_model=list[Web2ProvisionItemResponse])
async def list_web2_provisioning(
    repo: OffpageRepoDep,
    _actor: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[Web2ProvisionItemResponse]:
    """The account-building queue: what is intended, in flight, blocked, or done."""
    rows = await asyncio.to_thread(repo.list_provision_items, client_id)
    return [Web2ProvisionItemResponse.from_row(r) for r in rows]


@router.post(
    "/offpage/web2/provisioning/{item_id}",
    response_model=Web2ProvisionItemResponse,
)
async def advance_web2_provisioning(
    item_id: str,
    body: Web2ProvisionAdvanceRequest,
    repo: OffpageRepoDep,
    actor: Lead,
) -> Web2ProvisionItemResponse:
    """Move one queue item to its next state (lead-only).

    The final move to ``live`` is the one that matters: it registers the real
    ``web2_accounts`` row and seals the credential, through the SAME ``build_spec`` the
    CLI and the register endpoint use - so R2-08's identity rules cannot drift by being
    enforced in three places. Reaching ``live`` without a credential is refused by the
    state machine, because an account that reports live with nothing sealed is exactly
    the green-board-empty-vault failure the usable-account SQL was written after.
    """
    from app.services.web2_provisioning_queue import TransitionRefusedError, next_status

    row = await asyncio.to_thread(repo.get_provision_item, item_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provisioning item not found"
        )
    try:
        target = next_status(str(row.get("status") or ""), body.status)
    except TransitionRefusedError as refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(refused)
        ) from refused

    fields: dict[str, Any] = {}
    if target == "live":
        account_id = await _register_provisioned_account(row, body)
        fields["account_id"] = account_id

    handle = body.handle.strip()
    if handle:
        fields["handle"] = handle

    updated = await asyncio.to_thread(
        repo.update_provision_item, item_id, status=target, note=body.note.strip(), **fields
    )
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Provisioning item not found"
        )
    await record_activity(
        actor, kind="client",
        action=f"moved {row.get('platform')} account setup to {target}",
        target=str(row.get("client_name") or ""),
        entity_type="client", entity_id=str(row.get("client_id") or ""),
    )
    return Web2ProvisionItemResponse.from_row(updated)


async def _register_provisioned_account(
    row: dict[str, Any], body: Web2ProvisionAdvanceRequest
) -> str:
    """Create the real account row + seal its credential.

    Delegates to the ONE registration path the CLI and the auto-lane worker also use, so
    R2-08's identity rules cannot drift by being enforced in three places - a drift that
    fails no test and shows up months later as one suspension enumerating a client base.
    """
    from app.services.web2_account_registration import (
        AccountRegistrationError,
        register_account,
    )

    try:
        return await asyncio.to_thread(
            lambda: register_account(
                platform=str(row.get("platform") or ""),
                client_id=str(row.get("client_id") or ""),
                handle=body.handle.strip() or str(row.get("handle") or ""),
                registration_email=str(row.get("registration_email") or ""),
                credential=dict(body.credential),
                property_url=body.property_url.strip(),
            )
        )
    except AccountRegistrationError as refused:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(refused)
        ) from refused


@router.get("/offpage/web2/accounts", response_model=list[Web2AccountResponse])
async def list_web2_accounts(
    repo: OffpageRepoDep,
    actor: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[Web2AccountResponse]:
    """The connection board: which accounts exist, and whether their credential is
    structurally usable. Registering an account was CLI-only until now, which made
    onboarding an engineer's job rather than an operator's."""
    from app.services.vault import find_secret
    from integrations.web2_credentials import build_publisher
    from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

    rows = await asyncio.to_thread(repo.list_web2_accounts, client_id)
    out: list[Web2AccountResponse] = []
    for row in rows:
        platform = str(row.get("platform") or "")
        required = list(PLATFORM_CREDENTIAL_FIELDS.get(platform, ()))
        publisher = await asyncio.to_thread(
            build_publisher,
            vault_label=str(row.get("vault_label") or ""),
            platform=platform,
            lookup=find_secret,
        )
        out.append(
            Web2AccountResponse.from_row(row, required=required, complete=publisher is not None)
        )
    return out


@router.post(
    "/offpage/web2/accounts/{account_id}/check", response_model=Web2AccountCheckResponse
)
async def check_web2_account(
    account_id: str, repo: OffpageRepoDep, actor: Lead
) -> Web2AccountCheckResponse:
    """Ask the platform, right now, whether this credential still works.

    Until this existed an account counted as connected because its fields were non-empty
    - which proves shape, not validity - so a revoked token was indistinguishable from a
    good one until a campaign failed, after the drafting spend.

    Lead-only: it opens a sealed credential (server-side, never returned) and makes an
    outbound call as the client. Read-only by construction: every verifier is a profile
    GET, so a check can never publish or modify anything.
    """
    from app.services.web2_credcheck import check_credential

    row = await asyncio.to_thread(repo.get_web2_account, account_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Account not found")

    cred = await asyncio.to_thread(_credential_for, row)
    result = await asyncio.to_thread(
        check_credential, str(row.get("platform") or ""), cred, _account_fetcher()
    )
    # Only a definite answer moves health; "unknown" must not overwrite a known-good
    # account with a verdict that came from our own network failing.
    health = {"ok": "active", "bad": "suspended"}.get(result.state)
    if health:
        # Privileged: health is a derived platform fact the server records, not
        # something an operator authors, so it is written on the service store.
        from app.db.offpage_repo import service_offpage_store

        await asyncio.to_thread(
            service_offpage_store().set_web2_account_health, account_id,
            health=health, checked_at=datetime.now(UTC),
        )
    else:
        health = str(row.get("health") or "unverified")
    await record_activity(
        actor, kind="content", action=f"checked a Web 2.0 credential ({result.state})",
        target=str(row.get("platform") or ""), entity_type="client",
        entity_id=str(row.get("client_id") or "") or None,
    )
    return Web2AccountCheckResponse(
        account_id=account_id, state=result.state, detail=result.detail,
        identity=result.identity, health=health,
    )


@router.get("/offpage/web2/placements", response_model=list[Web2PlacementResponse])
async def list_placements(
    repo: OffpageRepoDep,
    actor: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
) -> list[Web2PlacementResponse]:
    """The cross-campaign placement ledger, newest first.

    Scoped by campaign alone would hide the single-property builds that predate
    campaigns, so a client's Web 2.0 history would look shorter than it is.
    """
    rows = await asyncio.to_thread(repo.client_placements, client_id)
    return [Web2PlacementResponse.from_row(r) for r in rows]


def _campaign_response(row: dict[str, Any], props: list[dict[str, Any]]) -> Web2CampaignResponse:
    """Roll the property ledger into the campaign's honest status.

    A campaign that claimed thirty and delivered twenty-eight is DEGRADED, never
    completed - the same rule the content dispatcher enforces, and the same defect P0-4
    removed elsewhere: a green tick over work that reached nobody.
    """
    from app.services.web2_campaign import campaign_status_for

    total = len(props)
    published = sum(1 for p in props if str(p.get("status")) == "published")
    failed = sum(1 for p in props if str(p.get("status")) in ("failed", "rejected"))
    stored = str(row.get("status") or "")
    # The LEDGER is authoritative for delivery; the stored column only carries the
    # pre-delivery lifecycle. An earlier version let any of draft/planning/needs_approval
    # win outright, which pinned a campaign at "planning" forever - it published all
    # thirty properties and still reported itself as still being planned. So the stored
    # value holds only while NOTHING has been delivered yet; the moment a property has a
    # terminal outcome, what actually happened wins.
    if stored == "cancelled":
        rolled = "cancelled"  # an operator decision outranks the ledger
    elif published or failed:
        rolled = campaign_status_for(total=total, published=published, failed=failed)
    elif stored in ("draft", "planning", "needs_approval"):
        rolled = stored
    else:
        rolled = campaign_status_for(total=total, published=published, failed=failed)
    upcoming = sorted(
        (p["scheduled_for"] for p in props
         if p.get("scheduled_for") and str(p.get("status")) != "published"),
    )
    return Web2CampaignResponse.from_row(
        {**row, "status": rolled}, published=published, total=total,
        next_publish=upcoming[0].isoformat() if upcoming else "",
    )


# --- KPIs ---------------------------------------------------------------------


@router.get("/offpage/kpis", response_model=OffpageKpisResponse)
async def offpage_kpis(repo: OffpageRepoDep, _user: ViewReports) -> OffpageKpisResponse:
    """The off-page summary tiles: live profile size (distinct referring domains) plus
    the new/lost 30-day monitoring deltas and the toxic disavow-review queue size."""
    counts = await asyncio.to_thread(repo.backlink_status_counts)
    referring = await asyncio.to_thread(repo.referring_domain_count)
    return OffpageKpisResponse(
        referring_domains=referring,
        new_links_30d=counts.get("new", 0),
        lost_links_30d=counts.get("lost", 0),
        toxic_flagged=counts.get("toxic", 0),
    )
