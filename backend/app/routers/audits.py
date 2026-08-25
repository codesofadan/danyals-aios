"""Module 01 Audit endpoints. Reads require any provisioned staff; running an
audit requires ``run_audits``. Responses match the frontend ``AuditRow`` shape.

POST /audits SSRF-guards the URL (off the event loop), gates paid audit types
off the Free tier, inserts a ``queued`` row (RLS-scoped), and enqueues the
Celery worker that runs the external engine. The worker owns the run lifecycle.

It also resolves the run's DEPTH (recovery plan §3.2): ``free`` | ``standard`` |
``deep``, a breadth axis distinct from ``tier`` (which authorises spend) and from
``types`` (which scopes dimensions). ``deep`` must be confirmed against a cost
estimate before it runs; ``POST /audits/estimate`` produces that quote and
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
    AuditResponse,
    AuditStatsResponse,
    compute_audit_stats,
    tier_to_db,
)
from app.services.activity import record_activity
from app.services.audit_artifacts import (
    REPORT_HTML_VIEW_HEADERS,
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


def get_paid_audit_gate() -> Callable[[str, str, float], GateDecision]:
    """Dependency: evaluate a prospective PAID audit against the cost gate
    (overridable in tests).

    Reuses the SAME gate the worker runs (spend halt -> dial -> client cap) so the
    enqueue pre-check and the worker's run-time gate can never diverge. The
    gate makes no paid call - it only decides - so a read here is cheap and safe.
    """

    def _evaluate(client_id: str, client_name: str, estimated_cost: float) -> GateDecision:
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


PaidAuditGateDep = Annotated[Callable[[str, str, float], GateDecision], Depends(get_paid_audit_gate)]


def _rows_to_responses(
    rows: list[dict[str, Any]], store: LocalArtifactStore | None
) -> list[AuditResponse]:
    """Build the AuditRow responses with the pdf/json download flags DOWNGRADED to
    on-disk reality (see ``honest_artifact_flags``) so the dashboard never offers a
    download that 404s. Runs in a worker thread (filesystem ``stat`` per row)."""
    out: list[AuditResponse] = []
    for r in rows:
        resp = AuditResponse.from_row(r)
        resp.pdf, resp.json_ = honest_artifact_flags(store, r)
        out.append(resp)
    return out


@router.get("/audits", response_model=list[AuditResponse])
async def list_audits(
    repo: AuditsRepoDep, page: PageDep, store: ArtifactStoreDep, _user: ViewReports
) -> list[AuditResponse]:
    rows = await asyncio.to_thread(repo.list_audits, limit=page.limit, offset=page.offset)
    return await asyncio.to_thread(_rows_to_responses, rows, store)


@router.get("/audits/stats", response_model=AuditStatsResponse)
async def audit_stats(repo: AuditsRepoDep, _user: ViewReports) -> AuditStatsResponse:
    rows = await asyncio.to_thread(repo.list_audits)
    return compute_audit_stats(rows)


@router.get("/audits/{audit_id}", response_model=AuditResponse)
async def get_audit(
    audit_id: str, repo: AuditsRepoDep, store: ArtifactStoreDep, _user: ViewReports
) -> AuditResponse:
    row = await asyncio.to_thread(repo.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND
    resp = AuditResponse.from_row(row)
    resp.pdf, resp.json_ = await asyncio.to_thread(honest_artifact_flags, store, row)
    return resp


@router.get("/audits/{audit_id}/report.pdf")
async def download_audit_pdf(
    audit_id: str, repo: AuditsRepoDep, store: ArtifactStoreDep, _user: ViewReports
) -> FileResponse:
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
    types = list(body.types)

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
        agents=body.tier == "Paid" and agent_fanout_enabled(types),
        estimated_cost=estimate_audit_cost(
            settings, mode=tier_to_db(body.tier), depth=depth, types=types, pages=pages
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
    # Free tier makes zero paid-provider spend: reject paid audit types up front.
    if body.tier == "Free":
        paid = body.paid_types()
        if paid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Paid audit types require the Paid tier: {', '.join(paid)}",
            )
        # An EMPTY selection is the FULL comprehensive run, and this check used to
        # miss it entirely - `paid_types()` returns [] for an empty list, so a
        # request for every dimension read as the cheapest possible one.
        #
        # THE BYPASS THIS CLOSES (measured, not reasoned):
        #   frontend sends types=[] -> tier "Free" (`types.some(isPaid)` is false
        #   for an empty array) -> this endpoint's gate is skipped (`if body.tier
        #   == "Paid"`) -> row stored tier=free -> the worker's re-check is skipped
        #   for the same reason -> `execute_audit` calls the engine with
        #   `comprehensive=True`, which forces `mode="paid"` REGARDLESS of the
        #   stored tier -> `--serper --places --citations --agents on
        #   --ai-narrative on`.
        # So the platform's single largest spend ran with neither the cost dial,
        # nor the client budget cap, nor the global spend halt applied. The money
        # was still LOGGED afterwards (the commit hardcodes mode="paid"), so this
        # was never invisible spend - it was ungated spend, which is what a
        # pre-flight gate exists to prevent.
        #
        # Refused rather than silently upgraded to Paid. Silent upgrade is the
        # exact mistake WU-7 removed from the public funnel ("the caller asked for
        # free and got auto with every provider on"); doing it here would be that
        # mistake mirrored, and would spend a client's budget on a request that
        # said Free.
        if body.runs_paid_providers():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "An audit with no types selected is the full comprehensive run "
                    "(every paid provider + the AI agents) and requires the Paid tier. "
                    "Select specific free types, or run it as Paid."
                ),
            )
        # ... and a Free run may not buy extra BREADTH either. `--mode free` clears
        # every paid provider at the engine, so a `standard`/`deep` free crawl
        # returns more pages of the same two deterministic dimensions while
        # multiplying the load on an UNMETERED path - the exact shape of the
        # denial-of-wallet vector WU-7 closed on the public funnel. Refused
        # explicitly rather than silently downgraded: a caller that asked for 300
        # pages and got 15 without being told would report the wrong thing.
        if body.depth is not None and body.depth != "free":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Depth '{body.depth}' requires the Paid tier; Free audits run at 'free' depth",
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
        settings, mode=tier_to_db(body.tier), depth=depth, types=list(body.types), pages=pages
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
    client = await asyncio.to_thread(clients.get_client, body.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

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
        decision = await asyncio.to_thread(
            gate, body.client_id, client.get("name", ""), estimate
        )
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
            "client_id": body.client_id,
            "client_name": client.get("name", ""),
            "url": body.url,
            "types": body.types,
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
        },
    )
    enqueue(str(row["id"]))
    await record_activity(
        actor, kind="audit", action="ran an audit", target=body.url,
        entity_type="client", entity_id=body.client_id,
    )
    return AuditResponse.from_row(row)
