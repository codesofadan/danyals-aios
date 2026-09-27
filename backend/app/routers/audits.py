"""Module 01 Audit endpoints. Reads require any provisioned staff; running an
audit requires ``run_audits``. Responses match the frontend ``AuditRow`` shape.

POST /audits SSRF-guards the URL (off the event loop), gates paid DEPTH
off the Free tier, inserts a ``queued`` row (RLS-scoped), and enqueues the
Celery worker that runs the external engine. The worker owns the run lifecycle.

It also resolves the run's DEPTH (recovery plan §3.2): ``free`` | ``standard`` |
``deep``. Depth is now the ONLY scope axis and it subsumes ``tier``: ``free``
runs ``--mode free`` and spends nothing, the other two buy paid corroboration.
The audit-TYPE picker that used to sit alongside it is gone - it promised
per-dimension scoping the engine cannot do, since the deterministic crawl has no
per-dimension flag and always runs in full. ``deep`` must be confirmed against a
cost estimate before it runs; ``POST /audits/estimate`` produces that quote and
spends nothing to do it.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.config import Settings
from app.core.auth import CurrentUser, require_perm
from app.core.deps import SettingsDep
from app.core.pagination import PageDep
from app.core.ratelimit import rate_limit
from app.core.security import PrivateAddressError, validate_public_host
from app.db.audits_repo import AuditsRepoDep
from app.db.clients_repo import ClientsRepoDep
from app.schemas.audits import (
    AuditCreate,
    AuditEstimateRequest,
    AuditEstimateResponse,
    AuditPublicPageResponse,
    AuditPublicPageUpdate,
    AuditRefreshItem,
    AuditRefreshRequest,
    AuditRefreshResponse,
    AuditReingestResponse,
    AuditResponse,
    AuditStatsResponse,
    AuditTier,
    AuditVisibilityUpdate,
    compute_audit_stats,
    tier_to_db,
)
from app.services.activity import record_activity
from app.services.audit_artifacts import (
    REPORT_HTML_VIEW_HEADERS,
    REPORT_PDF_NAME,
    LocalArtifactStore,
    honest_artifact_flags,
    local_store_from_settings,
)
from app.services.audit_depth import (
    CONFIRM_REQUIRED_DEPTHS,
    agent_fanout_enabled,
    depth_ceiling,
    estimate_audit_cost,
    planned_pages,
)
from app.services.audit_reingest import ReingestUnavailableError, reingest_audit
from app.services.audit_sheets import SHEET_FILES, sheet_media_type
from app.services.cost_gate import CostGate, GateContext, GateDecision, SpendHaltedError
from app.services.cost_store import PostgresCostStore
from app.services.site_size import UNKNOWN, SitemapSizeProbe, SiteSize

router = APIRouter(tags=["audits"])

# The technical-audit cost identity, shared with workers/tasks/audit.py.
_TECH_AUDIT_FEATURE = "tech_audit"
_AUDIT_PROVIDER = "audit_engine"


class _NullCostCache:
    """No-op ``CostCache``: a Paid audit is a unique live crawl, never cached."""

    def get(self, key: str) -> object | None:
        return None

    def set(self, key: str, value: object) -> None:
        return None

RunAudits = Annotated[CurrentUser, Depends(require_perm("run_audits"))]
# All six staff roles hold view_reports; a portal client does NOT (role_has_perm
# early-returns False for 'client'), so this confines clients out of the staff
# audit namespace - they use /portal/* instead (finding 7 / D10).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]

_AUDIT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
_ARTIFACT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not available"
)


def _iso_or_none(value: Any) -> str | None:
    """An ISO timestamp, or None - never the string "None" in a response body."""
    return value.isoformat() if isinstance(value, datetime) else None


def get_artifact_store(settings: SettingsDep) -> LocalArtifactStore | None:
    """Dependency: the configured artifact store, or ``None`` when unset."""
    return local_store_from_settings(settings)


ArtifactStoreDep = Annotated["LocalArtifactStore | None", Depends(get_artifact_store)]


async def _serve_artifact(
    repo: AuditsRepoDep,
    store: LocalArtifactStore | None,
    audit_id: str,
    column: str,
    media_type: str,
    download_name: str,
) -> FileResponse:
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    row = await asyncio.to_thread(repo.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND
    key = row.get(column)
    path: Path | None = store.resolve(key) if key else None
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type=media_type, filename=download_name)


def get_audit_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the audit worker (overridable in tests).

    The worker task is imported lazily so the API process never pulls in Celery
    task modules just to import this router.
    """

    def _enqueue(audit_id: str) -> None:
        from workers.tasks.audit import run_audit_job

        run_audit_job.delay(audit_id)

    return _enqueue


AuditEnqueuerDep = Annotated[Callable[[str], None], Depends(get_audit_enqueuer)]


def get_paid_audit_gate() -> Callable[[str | None, str, float], GateDecision]:
    """Dependency: evaluate a prospective PAID audit against the cost gate
    (overridable in tests).

    Reuses the SAME gate the worker runs (spend halt -> dial -> client cap) so the
    enqueue pre-check and the worker's run-time gate can never diverge. The
    gate makes no paid call - it only decides - so a read here is cheap and safe.
    """

    def _evaluate(
        client_id: str | None, client_name: str, estimated_cost: float
    ) -> GateDecision:
        ctx = GateContext(
            feature_key=_TECH_AUDIT_FEATURE,
            client_id=client_id,
            provider=_AUDIT_PROVIDER,
            estimated_cost=estimated_cost,
            job_type="audit",
            client_name=client_name,
        )
        return CostGate(PostgresCostStore(), _NullCostCache()).evaluate(ctx)

    return _evaluate


def get_site_size_probe() -> Callable[[str], SiteSize]:
    """Dependency: measure a site's page count from its own sitemaps (test-overridable).

    Free (no metered provider), bounded, and SSRF-guarded at every redirect hop.
    Blocking, so callers hand it to ``asyncio.to_thread``.
    """
    probe = SitemapSizeProbe()

    def _measure(url: str) -> SiteSize:
        return probe.measure(url)

    return _measure


SiteSizeProbeDep = Annotated[Callable[[str], SiteSize], Depends(get_site_size_probe)]


# `str | None` in the first slot: an audit may have no client, and the gate is
# built for that - it drops the per-client budget cap and keeps the global spend
# halt and the feature dial.
PaidAuditGateDep = Annotated[
    Callable[[str | None, str, float], GateDecision], Depends(get_paid_audit_gate)
]


def _rows_to_responses(
    rows: list[dict[str, Any]],
    store: LocalArtifactStore | None,
    settings: Settings,
    slugs: dict[str, str],
) -> list[AuditResponse]:
    """Build the AuditRow responses with the pdf/json download flags DOWNGRADED to
    on-disk reality (see ``honest_artifact_flags``) so the dashboard never offers a
    download that 404s. Runs in a worker thread (filesystem ``stat`` per row).

    ``slugs`` carries only PUBLISHED pages, so an audit missing from it renders
    with no public link - which is the honest reading of both reasons it can be
    missing (never minted, or minted but not published)."""
    out: list[AuditResponse] = []
    for r in rows:
        resp = AuditResponse.from_row(r)
        resp.pdf, resp.json_ = honest_artifact_flags(store, r)
        slug = slugs.get(str(r.get("id")))
        if slug:
            resp.public_slug = slug
            resp.public_url = public_page_url(settings, slug)
        out.append(resp)
    return out


@router.get("/audits", response_model=list[AuditResponse])
async def list_audits(
    repo: AuditsRepoDep,
    page: PageDep,
    store: ArtifactStoreDep,
    settings: SettingsDep,
    _user: ViewReports,
) -> list[AuditResponse]:
    rows = await asyncio.to_thread(repo.list_audits, limit=page.limit, offset=page.offset)
    slugs = await asyncio.to_thread(repo.published_pages)
    return await asyncio.to_thread(_rows_to_responses, rows, store, settings, slugs)


@router.get("/audits/stats", response_model=AuditStatsResponse)
async def audit_stats(repo: AuditsRepoDep, _user: ViewReports) -> AuditStatsResponse:
    rows = await asyncio.to_thread(repo.list_audits)
    return compute_audit_stats(rows)


@router.get("/audits/{audit_id}", response_model=AuditResponse)
async def get_audit(
    audit_id: str,
    repo: AuditsRepoDep,
    store: ArtifactStoreDep,
    settings: SettingsDep,
    _user: ViewReports,
) -> AuditResponse:
    row = await asyncio.to_thread(repo.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND
    resp = AuditResponse.from_row(row)
    resp.pdf, resp.json_ = await asyncio.to_thread(honest_artifact_flags, store, row)
    # The detail view is where an operator goes to copy the link, so the page is
    # read here even though the list already carries it for the board.
    page_row = await asyncio.to_thread(repo.public_page, audit_id)
    if page_row and page_row.get("published"):
        resp.public_slug = str(page_row["slug"])
        resp.public_url = public_page_url(settings, str(page_row["slug"]))
        # The follow-up signal (0161): an operator who shared a link wants to know whether
        # it was opened, and this is the screen they are on when they ask.
        resp.public_views = int(page_row.get("views") or 0)
        resp.public_last_viewed = _iso_or_none(page_row.get("last_viewed_at"))
        resp.public_expires_at = _iso_or_none(page_row.get("expires_at"))
    return resp


@router.get("/audits/{audit_id}/report.pdf")
async def download_audit_pdf(
    audit_id: str, repo: AuditsRepoDep, store: ArtifactStoreDep, _user: ViewReports
) -> FileResponse:
    """The client-facing PDF.

    PREFERS the platform's own report over the engine's. They are two documents:
    the engine writes a narrative built from agent-written markdown, and the ingest
    step writes one built from the same stored rows as the workbook. Only the
    second can reconcile with the workbook, because it is the same query - which
    is the whole complaint the platform report exists to answer ("it was not
    giving the confidence that the pdf is representing the same audit that is
    present in the xlsx").

    Falls back to the engine's PDF, so every run that could be downloaded before
    still can, including ones that predate the platform report.
    """
    if store is not None:
        row = await asyncio.to_thread(repo.get_audit, audit_id)
        if row is None:
            raise _AUDIT_NOT_FOUND
        path = await asyncio.to_thread(store.resolve_sheet, audit_id, REPORT_PDF_NAME)
        if path is not None:
            return FileResponse(path, media_type="application/pdf",
                                filename=f"audit-{audit_id}.pdf")
    return await _serve_artifact(
        repo, store, audit_id, "pdf_path", "application/pdf", f"audit-{audit_id}.pdf"
    )


@router.get("/audits/{audit_id}/findings.json")
async def download_audit_findings(
    audit_id: str, repo: AuditsRepoDep, store: ArtifactStoreDep, _user: ViewReports
) -> FileResponse:
    return await _serve_artifact(
        repo, store, audit_id, "json_path", "application/json", f"audit-{audit_id}.json"
    )


@router.get("/audits/{audit_id}/report.html")
async def view_audit_report_html(
    audit_id: str, repo: AuditsRepoDep, store: ArtifactStoreDep, _user: ViewReports
) -> FileResponse:
    """Serve the self-contained report.html for the in-dashboard page-viewer.

    Resolved by convention from the audit id (sibling of report.pdf), so it is
    available even for a run whose PDF backend was unavailable. Same document the
    PDF is rendered from, so the viewer matches the download.
    """
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    row = await asyncio.to_thread(repo.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND
    path = store.resolve_report_html(audit_id)
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type="text/html", headers=REPORT_HTML_VIEW_HEADERS)


@router.get("/audits/{audit_id}/sheets/{name}")
async def download_audit_sheet(
    audit_id: str, name: str, repo: AuditsRepoDep, store: ArtifactStoreDep, _user: ViewReports
) -> FileResponse:
    """Download a role-based remediation sheet (xlsx workbook or a csv export).

    Guarded exactly like the report.pdf/findings.json downloads (``view_reports``
    - all six staff roles, no client). ``name`` is restricted to the known sheet
    allow-list before resolving, and the path is resolved traversal-safe by
    convention from the audit id (no DB column). 404 if the sheet is not present
    (e.g. an audit that completed before this feature, or one with no findings).
    """
    if name not in SHEET_FILES or store is None:
        raise _ARTIFACT_NOT_FOUND
    row = await asyncio.to_thread(repo.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND
    path = store.resolve_sheet(audit_id, name)
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(
        path, media_type=sheet_media_type(name), filename=f"audit-{audit_id}-{name}"
    )


@router.post(
    "/audits/estimate",
    response_model=AuditEstimateResponse,
    dependencies=[Depends(rate_limit("audit_estimate", 60))],
)
async def estimate_audit(
    body: AuditEstimateRequest,
    settings: SettingsDep,
    probe: SiteSizeProbeDep,
    _actor: RunAudits,
) -> AuditEstimateResponse:
    """Quote one audit run without creating it. Spends nothing, touches no tenant.

    Guarded by ``run_audits`` rather than left open to any staff reader: the reply
    is a price list of the platform's own provider costs, derived from the unit
    prices in settings. WU-13/WU-14 found the same shape twice - a handler that
    serves in-process constants is never RLS-bounded, whatever table it sits
    beside - so the guard is at the app layer, deliberately and by name.

    The quote carries its derivation (``pages``, ``agents``) because approving a
    spend means approving a judgement, and a bare figure cannot be reviewed.
    """
    depth = body.resolved_depth()
    if body.tier == "Free" and depth != "free":
        # Same refusal as POST /audits, for the same reason - quoting a
        # combination that cannot be created would be a misleading price.
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Depth '{depth}' requires the Paid tier; Free audits run at 'free' depth",
        )

    # Measure the site only where the answer can change the quote: `deep` is the
    # one depth that scales to site size. Free and standard are small fixed reads,
    # so probing them would spend a request on a number nothing consumes.
    size = UNKNOWN
    if depth == "deep" and body.url:
        try:
            # Blocks on DNS + HTTP; must not run on the event loop.
            size = await asyncio.to_thread(probe, body.url)
        except PrivateAddressError as exc:
            # Never degraded to "unknown": quoting a run against a host the SSRF
            # guard just refused would price work that can never legitimately run.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"URL is not a public address: {exc}",
            ) from exc

    pages = planned_pages(settings, depth, measured=size.pages)
    return AuditEstimateResponse(
        tier=body.tier,
        depth=depth,
        pages=pages,
        agents=body.tier == "Paid" and agent_fanout_enabled(depth),
        estimated_cost=estimate_audit_cost(
            settings, mode=tier_to_db(body.tier), depth=depth, pages=pages
        ),
        confirmation_required=depth in CONFIRM_REQUIRED_DEPTHS,
        measured_pages=size.pages,
        size_source=size.source,
        size_truncated=size.truncated,
    )


@router.post(
    "/audits",
    response_model=AuditResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("audit_create", 30))],
)
async def create_audit(
    body: AuditCreate,
    repo: AuditsRepoDep,
    clients: ClientsRepoDep,
    enqueue: AuditEnqueuerDep,
    gate: PaidAuditGateDep,
    settings: SettingsDep,
    actor: RunAudits,
) -> AuditResponse:
    # Free tier makes zero paid-provider spend, and DEPTH is now the only axis
    # that can buy any. `free` depth runs `--mode free`, which the engine enforces
    # by hard-clearing every provider after parsing - so a Free run cannot spend
    # whatever flags a future change adds.
    #
    # THE BYPASS THIS REPLACED (measured, not reasoned). The gate used to read an
    # audit-TYPE selection, and an EMPTY selection meant "the full comprehensive
    # run". `paid_types()` returned [] for an empty list, so:
    #   frontend sends types=[] -> tier "Free" -> the paid gate is skipped -> row
    #   stored tier=free -> the worker's re-check is skipped for the same reason
    #   -> `execute_audit` calls the engine with `comprehensive=True`, which forced
    #   `mode="paid"` REGARDLESS of the stored tier -> every provider + agents on.
    # The platform's single largest spend ran with neither the cost dial, nor the
    # client budget cap, nor the global spend halt applied. Keyed on depth the
    # shape cannot recur: there is no value of `depth` that means "free to ask for
    # and paid to run", because the same value picks the engine mode.
    #
    # Refused rather than silently downgraded. A caller that asked for 300 pages
    # and got 15 without being told would report the wrong thing - and silent
    # upgrade is the mistake WU-7 removed from the public funnel.
    if body.tier == "Free" and body.depth is not None and body.depth != "free":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Depth '{body.depth}' runs paid providers and requires the Paid "
                "tier; Free audits run at 'free' depth"
            ),
        )

    depth = body.resolved_depth()
    ceiling = depth_ceiling(settings, depth)
    # A caller may echo back the page budget its quote was issued for, so a deep
    # run reproduces the figure it was quoted without the server re-probing the
    # site (a re-probe would make the confirmation depend on a value that can move
    # in between, producing spurious 409s). The echo is BOUNDED: it can only ever
    # narrow the run, never widen it past what the depth already allows - so a
    # caller that lies gets a smaller audit than it could have had, which is not a
    # threat worth a round trip to prevent.
    if body.max_pages is not None and body.max_pages > ceiling:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"maxPages {body.max_pages} exceeds the '{depth}' depth ceiling of {ceiling}"
            ),
        )
    pages = body.max_pages or planned_pages(settings, depth)
    estimate = estimate_audit_cost(
        settings, mode=tier_to_db(body.tier), depth=depth, pages=pages
    )

    # "Estimated and confirmed before running" (plan §3.2) for the depths that
    # warrant it. The operator echoes back the FIGURE, not a boolean, so a
    # confirmation cannot outlive the number it was given: if unit prices or the
    # depth's page budget moved between the quote and the submit, the echo no
    # longer matches and the operator is asked again.
    if depth in CONFIRM_REQUIRED_DEPTHS:
        if body.confirmed_estimate is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"A '{depth}' audit must be confirmed against its cost estimate. "
                    "POST /audits/estimate, then resubmit with confirmedEstimate."
                ),
            )
        if abs(body.confirmed_estimate - estimate) > settings.audit_estimate_tolerance_usd:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"The estimate changed since it was confirmed "
                    f"(confirmed ${body.confirmed_estimate:.4f}, now ${estimate:.4f}). "
                    "Re-request the estimate and confirm the current figure."
                ),
            )

    # SSRF guard: getaddrinfo blocks, so validate off the event loop.
    try:
        await asyncio.to_thread(validate_public_host, body.url)
    except PrivateAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL is not a public address: {exc}",
        ) from exc

    # Resolve + snapshot the client name (also validates tenant scope via RLS).
    # A run with NO client is legitimate - an internal or prospect audit - so the
    # lookup is skipped rather than failed. A client_id that IS supplied must
    # still resolve: "no client" and "a client that does not exist" are different
    # requests, and only the first one is being allowed here.
    client: dict[str, Any] | None = None
    if body.client_id:
        client = await asyncio.to_thread(clients.get_client, body.client_id)
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Client not found"
            )
    client_name = client.get("name", "") if client else ""

    # Cost pre-check (Paid only): reject an over-budget / dial-disabled paid audit
    # at ENQUEUE so the operator is told immediately, not after the worker marks it
    # failed. The worker re-checks the same gate at run time (defense in depth).
    if body.tier == "Paid":
        # `estimate` replaces the flat `settings.audit_paid_cost_estimate`, which
        # priced a 20-page on-page-only run and a 300-page full consulting run at
        # the same $1.50 - so the pre-flight gate could not distinguish a request
        # from one twenty times its size, and a client budget could be exhausted or
        # spared for reasons unrelated to what was actually being asked for. The
        # figure now comes from `pricing.audit_cost`, the SAME function that
        # computes the committed cost, over PLANNED rather than actual observables.
        # `client_id` may be None here. The gate models that directly: it skips
        # the per-client budget cap (there is no client to bill) and still
        # enforces the agency-global spend halt and the feature dial, which are
        # what actually bound an untenanted paid run. Same contract the public
        # funnel uses.
        decision = await asyncio.to_thread(gate, body.client_id, client_name, estimate)
        if decision.halted:
            # Global API-spend halt: a typed 402 "spend_halted" refusal (not run).
            raise SpendHaltedError()
        if not decision.allowed:
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Paid audit blocked by cost controls: {decision.reason or decision.outcome}",
            )

    row = await asyncio.to_thread(
        repo.insert_audit,
        {
            "client_id": body.client_id or None,
            "client_name": client_name,
            "url": body.url,
            # Always empty: the audit-type picker is gone and every run is the
            # full audit. Historical rows keep whatever they were created with, so
            # the column stays and old audits still render their scope truthfully.
            "types": [],
            "tier": tier_to_db(body.tier),
            "depth": depth,
            # Snapshotted so this run's breadth and quoted price survive a later
            # settings change. Before 0084 both lived only in process settings, so
            # a completed audit could not say what it had been asked to do.
            "max_pages": pages,
            "estimated_cost": estimate,
            "estimate_confirmed_at": (
                datetime.now(UTC) if depth in CONFIRM_REQUIRED_DEPTHS else None
            ),
            "status": "queued",
            # No client, no portal. `portal_audits` already makes a NULL-client
            # row unreachable (NULL = current_client_id() is never true), so this
            # is not what keeps it private - it is what stops the row from
            # CLAIMING to be shared. A `true` here would render a "shared" badge
            # in the admin table for an audit no one can open, which is the kind
            # of flag that gets trusted later. Store what is true.
            "visible_to_client": bool(body.visible_to_client and body.client_id),
        },
    )
    enqueue(str(row["id"]))
    await record_activity(
        actor, kind="audit", action="ran an audit", target=body.url,
        entity_type="client" if body.client_id else None,
        entity_id=body.client_id or None,
    )
    return AuditResponse.from_row(row)


@router.patch("/audits/{audit_id}/visibility", response_model=AuditResponse)
async def set_audit_visibility(
    audit_id: str,
    body: AuditVisibilityUpdate,
    repo: AuditsRepoDep,
    store: ArtifactStoreDep,
    actor: RunAudits,
) -> AuditResponse:
    """Share this audit into the client's portal, or stop sharing it.

    Gated on ``run_audits`` rather than ``view_reports``: putting a document in
    front of a client is an outward-facing act, and every role that holds
    ``run_audits`` is exactly the set the ``audits_modify`` RLS policy admits.
    A ``viewer`` is refused twice over - by the permission here and by the
    policy underneath.

    RLS refusal does not raise, it matches zero rows, so a missing row is
    reported as a 404 rather than returned as a successful no-op.
    """
    if body.visible_to_client:
        current = await asyncio.to_thread(repo.get_audit, audit_id)
        if current is None:
            raise _AUDIT_NOT_FOUND
        if not current.get("client_id"):
            # An audit with no client has no portal to appear in: `portal_audits`
            # is keyed on `client_id = current_client_id()`, which NULL never
            # satisfies. Honouring this would flip a flag that changes nothing
            # and then report success, so the operator would believe a document
            # had been shared that no one can reach. Refuse and say why.
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "This audit has no client, so it cannot be shared to a client "
                    "portal. Attach it to a client first."
                ),
            )
    row = await asyncio.to_thread(
        repo.set_visibility, audit_id, visible=body.visible_to_client
    )
    if row is None:
        raise _AUDIT_NOT_FOUND
    await record_activity(
        actor,
        kind="audit",
        action=(
            "shared an audit with the client portal"
            if body.visible_to_client
            else "removed an audit from the client portal"
        ),
        target=str(row.get("url") or audit_id),
        entity_type="client",
        entity_id=str(row["client_id"]) if row.get("client_id") else None,
    )
    resp = AuditResponse.from_row(row)
    resp.pdf, resp.json_ = await asyncio.to_thread(honest_artifact_flags, store, row)
    return resp


def public_page_url(settings: Settings, slug: str) -> str:
    """The address an operator pastes into a chat, for one published page.

    `public_file_base_url` is the deploy's own public origin (the same setting
    that makes a WordPress-embedded content image resolve). When it is unset the
    SITE-RELATIVE path is returned rather than a guessed hostname: a link built
    on a wrong origin 404s for the recipient, which is worse than one that is
    visibly missing its prefix and can be completed by hand.

    Note this is the READABLE page route (`/leads/<slug>`), which the frontend
    serves - not an `/api/v1/...` path. The API's own `public_file_base_url` is
    the right origin for it because in this deployment the dashboard and the API
    share a host (Caddy proxies `/api` to the backend).
    """
    # The dashboard origin, since /leads/<slug> is a Next.js route. Falls back
    # to the API origin, which is correct wherever one proxy fronts both.
    base = (settings.public_site_base_url or settings.public_file_base_url or "").rstrip("/")
    return f"{base}/leads/{slug}" if base else f"/leads/{slug}"


@router.post("/audits/{audit_id}/public-page", response_model=AuditPublicPageResponse)
async def set_audit_public_page(
    audit_id: str,
    body: AuditPublicPageUpdate,
    repo: AuditsRepoDep,
    settings: SettingsDep,
    actor: RunAudits,
) -> AuditPublicPageResponse:
    """Put this audit's report at a shareable public URL, or take it back down.

    THE LINK THIS MINTS IS OPENABLE BY ANYONE WHO HAS IT. That is the point - it
    is meant to be pasted into a WhatsApp chat or a Fiverr message - but it is
    also why publishing is an explicit staff act rather than something completion
    does on its own. `0126` deliberately defaults a paid page to
    `published = false` because a paid audit is client deliverable work, and the
    slug carries a random suffix so that even once published it is not
    enumerable from the client's name.

    Gated on ``run_audits``, matching ``/visibility`` beside it: putting a
    document in front of someone outside the agency is an outward-facing act, and
    that permission is exactly the set the ``audits_modify`` RLS policy admits.

    The page is not minted here. Completion mints it (workers/tasks/audit.py),
    which keeps slug derivation in one place - and a report that has not been
    generated has nothing to publish, so a missing row is a 409 that says so
    rather than a link to an empty page.
    """
    page = await asyncio.to_thread(repo.public_page, audit_id)
    if page is None:
        # Distinguish the two reasons there is no page, because they need
        # different actions from the operator.
        current = await asyncio.to_thread(repo.get_audit, audit_id)
        if current is None:
            raise _AUDIT_NOT_FOUND
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This audit has no public page yet. A page is minted when a run "
                "completes, so finish (or re-run) the audit first."
            ),
        )
    row = await asyncio.to_thread(
        repo.set_public_page_published, audit_id, published=body.published
    )
    if row is None:
        raise _AUDIT_NOT_FOUND
    # THE EXPIRY IS ITS OWN WRITE (0161), applied after the publish and only when the body
    # actually asked for it. Folding it into the publish update would make every publish
    # silently reset an expiry somebody had set - two different decisions sharing one
    # statement is how one of them gets lost.
    if body.clear_expiry or body.expires_at is not None:
        expiry_row = await asyncio.to_thread(
            repo.set_public_page_expiry,
            audit_id,
            expires_at=None if body.clear_expiry else body.expires_at,
        )
        if expiry_row is not None:
            row = expiry_row
    await record_activity(
        actor,
        kind="audit",
        action=(
            "published a public audit report"
            if body.published
            else "unpublished a public audit report"
        ),
        target=str(row["slug"]),
    )
    return AuditPublicPageResponse(
        slug=str(row["slug"]),
        url=public_page_url(settings, str(row["slug"])),
        published=bool(row["published"]),
        kind=str(row["kind"]),
        views=int(row.get("views") or 0),
        last_viewed_at=row.get("last_viewed_at"),
        expires_at=row.get("expires_at"),
    )


@router.post("/audits/{audit_id}/reingest", response_model=AuditReingestResponse)
async def reingest_audit_findings(
    audit_id: str,
    repo: AuditsRepoDep,
    store: ArtifactStoreDep,
    actor: RunAudits,
) -> AuditReingestResponse:
    """Rebuild this audit's stored findings from the artifacts it already produced.

    An audit's report and its QUERYABLE findings come from two different steps. The
    engine writes the report and the run is marked ``done``; a separate, deliberately
    non-fatal transform then loads those artifacts into the altitude tables and builds
    the workbook and the client report from them. When that second step failed - or
    never existed, for a run predating it - the audit stayed green in the list and its
    detail page was a dead end reading "No altitude data for this audit", while the
    report it was describing sat intact on disk.

    This is the way back. It re-runs the SAME transform the worker runs, against the
    stored ``artifact_dir``, so the findings, the roadmap, the workbook and the client
    report are rebuilt from the run's own evidence - one canonical stored result, not
    a second copy.

    It does not re-run the audit and it spends nothing: no engine invocation, no
    provider call. Gated on ``run_audits`` rather than ``view_reports`` because it
    writes, and it is the same permission the ``audits_modify`` policy admits.

    A run whose artifacts are gone gets a 409 saying so, rather than an empty rebuild
    reported as a success.
    """
    row = await asyncio.to_thread(repo.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND

    try:
        result = await asyncio.to_thread(reingest_audit, row, artifacts=store)
    except ReingestUnavailableError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # The recorded reason is now stale: the rows exist. Clearing it keeps
    # `audits.error` meaning "the findings are not queryable, and here is why".
    if row.get("error"):
        await asyncio.to_thread(repo.clear_error, audit_id)

    await record_activity(
        actor,
        kind="audit",
        action="rebuilt an audit's findings from its stored report",
        target=str(row.get("url") or audit_id),
        entity_type="audit",
        entity_id=audit_id,
    )
    return AuditReingestResponse(
        audit_id=audit_id,
        pages=result.pages,
        findings=result.findings,
        instances=result.instances,
        roadmap_items=result.roadmap_items,
        workbook_built=result.workbook_built,
        report_built=result.report_built,
        notes=result.notes,
    )

@router.post(
    "/audits/refresh",
    response_model=AuditRefreshResponse,
    dependencies=[Depends(rate_limit("audit_refresh", 10))],
)
async def refresh_client_audits_now(
    body: AuditRefreshRequest,
    repo: AuditsRepoDep,
    clients: ClientsRepoDep,
    enqueue: AuditEnqueuerDep,
    gate: PaidAuditGateDep,
    settings: SettingsDep,
    actor: RunAudits,
) -> AuditRefreshResponse:
    """Re-audit the SELECTED clients now, and say what it will cost before it does.

    WHY A BUTTON AND NOT A SCHEDULE. Every cron entry on this platform is off by the
    operator's decision, and month-over-month progress reporting needs periodic re-audits -
    so the recurring job has to be something a person presses. The fan-out task that ran
    weekly still exists and is unchanged; this is the same work, triggered deliberately, for
    a chosen set of clients rather than the whole roster.

    IT NEVER HALF-RUNS SILENTLY. A client with no site, over its budget, or blocked by the
    dial is reported as skipped WITH THE REASON rather than dropped - an operator who picks
    twelve clients and gets four audits must be able to see why without reading a log.

    The total is quoted and echoed back exactly as a deep single run is: ``POST /audits/
    estimate`` prices one run, this endpoint prices the set, and the caller resends the
    figure it was shown. A free-depth sweep spends nothing and therefore needs no
    confirmation - there is no figure to approve.
    """
    depth = body.depth
    # Typed as the literal the tier helpers take, not a bare str: `free` depth is the only
    # depth that spends nothing, and that mapping is the same one POST /audits enforces.
    tier_label: AuditTier = "Free" if depth == "free" else "Paid"
    pages = planned_pages(settings, depth)
    per_run = estimate_audit_cost(
        settings, mode=tier_to_db(tier_label), depth=depth, pages=pages
    )

    # Resolve each client + its site FIRST, so the quote covers only the runs that can
    # actually happen. Quoting for a client with no site would present a total nobody is
    # going to be charged.
    planned: list[tuple[dict[str, Any], str]] = []
    items: list[AuditRefreshItem] = []
    for client_id in body.client_ids:
        client = await asyncio.to_thread(clients.get_client, client_id)
        if client is None:
            items.append(AuditRefreshItem(
                client_id=client_id, outcome="skipped", reason="this client no longer exists",
            ))
            continue
        sites = await asyncio.to_thread(clients.list_sites, client_id, limit=1, offset=0)
        domain = str((sites[0] if sites else {}).get("domain") or "").strip()
        if not domain:
            items.append(AuditRefreshItem(
                client_id=client_id, client=str(client.get("name") or ""),
                outcome="skipped",
                reason="no site on record, so there is nothing to crawl",
            ))
            continue
        url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
        planned.append((client, url))

    total = round(per_run * len(planned), 4)
    if total > 0:
        if body.confirmed_total is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    f"This would run {len(planned)} audits at about ${per_run:.4f} each, "
                    f"${total:.4f} in total. Resend with confirmedTotal to approve it."
                ),
            )
        if abs(body.confirmed_total - total) > settings.audit_estimate_tolerance_usd:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"The total changed since it was quoted (approved ${body.confirmed_total:.4f}, "
                    f"now ${total:.4f}). Re-read the quote and approve the current figure."
                ),
            )

    queued = 0
    for client, url in planned:
        client_id = str(client["id"])
        name = str(client.get("name") or "")
        # The SSRF guard runs per client, because each one contributes its own URL and a
        # bad one must skip that client rather than fail the sweep.
        try:
            await asyncio.to_thread(validate_public_host, url)
        except PrivateAddressError as exc:
            items.append(AuditRefreshItem(
                client_id=client_id, client=name, url=url, outcome="skipped",
                reason=f"the site address is not publicly reachable: {exc}",
            ))
            continue
        if tier_label == "Paid":
            decision = await asyncio.to_thread(gate, client_id, name, per_run)
            if decision.halted:
                # The global halt is agency-wide: the rest of the sweep cannot run either,
                # so stop rather than reporting the same refusal N times.
                items.append(AuditRefreshItem(
                    client_id=client_id, client=name, url=url, outcome="skipped",
                    reason="API spend is halted platform-wide, so nothing further was started",
                ))
                break
            if not decision.allowed:
                items.append(AuditRefreshItem(
                    client_id=client_id, client=name, url=url, outcome="skipped",
                    reason=f"cost controls refused this client: {decision.reason or decision.outcome}",
                ))
                continue
        row = await asyncio.to_thread(
            repo.insert_audit,
            {
                "client_id": client_id,
                "client_name": name,
                "url": url,
                "types": [],
                "tier": tier_to_db(tier_label),
                "depth": depth,
                "max_pages": pages,
                "estimated_cost": per_run,
                "status": "queued",
                # Not shared automatically. A refresh is internal work until somebody
                # decides the report is worth sending, which is the same rule a
                # hand-started audit follows.
                "visible_to_client": False,
            },
        )
        enqueue(str(row["id"]))
        queued += 1
        items.append(AuditRefreshItem(
            client_id=client_id, client=name, url=url, audit_id=str(row["id"]),
            outcome="queued", estimated_cost=per_run,
        ))

    await record_activity(
        actor, kind="audit",
        action=f"re-audited {queued} client{'' if queued == 1 else 's'}",
        target=f"{depth} depth",
    )
    return AuditRefreshResponse(
        queued=queued,
        skipped=sum(1 for i in items if i.outcome == "skipped"),
        estimated_total=round(per_run * queued, 4),
        items=items,
    )
