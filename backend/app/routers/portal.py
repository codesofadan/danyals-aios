"""Client portal endpoints - the tenant-facing audit surface.

EVERY route is guarded by :data:`CurrentClientDep`, so only a provisioned
``client`` (with a ``client_id``) reaches them; staff are 403'd out and use the
staff ``/audits`` namespace instead. Reads go through the ``portal_*`` RLS views
(``PortalRepo``), so a client only ever sees its OWN tenant, and downloads verify
ownership via the view before resolving the artifact PATH server-side (the path
is never returned to the client). Creating an audit pins ``client_id`` from the
authenticated client (never the body) via :func:`create_client_audit`.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse

from app.core.auth import CurrentClientDep
from app.core.pagination import PageDep
from app.core.ratelimit import rate_limit
from app.db.database import DatabaseNotConfiguredError, get_admin_pool, privileged_connection
from app.db.portal_repo import PortalRepo, PortalRepoDep
from app.routers.audits import ArtifactStoreDep, AuditEnqueuerDep
from app.schemas.audits import PortalAuditCreate, PortalAuditResponse
from app.schemas.milestones import ClientProjectResponse
from app.schemas.portal import ClientDashboard
from app.schemas.portal_deliverables import ClientDeliverableResponse
from app.schemas.portal_reports import PortalReportResponse
from app.schemas.portal_requests import ClientRequestResponse, PortalRequestCreate
from app.services.audit_artifacts import REPORT_HTML_VIEW_HEADERS, LocalArtifactStore
from app.services.client_audits import AuditInserter, create_client_audit, insert_audit_row
from app.services.client_requests import RequestInserter, create_client_request, insert_request_row
from app.services.report_viz import build_report_viz

router = APIRouter(prefix="/portal", tags=["portal"])

_AUDIT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
_ARTIFACT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not available"
)
_DELIVERABLE_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Deliverable not found"
)
_PROJECT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Project not found"
)
_DB_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
)

# media_type -> download extension (deliverables are PDFs by default).
_MEDIA_EXT: dict[str, str] = {
    "application/pdf": ".pdf",
    "text/markdown": ".md",
    "application/json": ".json",
}


def get_portal_audit_inserter() -> AuditInserter:
    """Dependency: the privileged (service_role) inserter for the tenant-pinned insert.

    Clients have no base-table SELECT policy, so the create runs on the
    privileged (BYPASSRLS) path; ``client_id`` is pinned server-side in
    :func:`create_client_audit`. Resolving the admin pool here surfaces an
    unconfigured DB as a 503 up front. Overridable in tests.
    """
    try:
        get_admin_pool()
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    return insert_audit_row


PortalAuditInserterDep = Annotated[AuditInserter, Depends(get_portal_audit_inserter)]


def get_portal_audit_loader() -> Callable[[str], dict[str, Any] | None]:
    """Dependency: load an audit's artifact PATHS by id via the privileged connection.

    The ``portal_audits`` view deliberately hides ``pdf_path``/``json_path``, so
    resolving a file for download needs a server-side (service_role) read. Callers
    invoke this ONLY after verifying ownership through the RLS view. Overridable
    in tests.
    """

    def _load(audit_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select pdf_path, json_path from public.audits where id = %s limit 1",
                (audit_id,),
            )
            return cur.fetchone()

    return _load


PortalAuditLoaderDep = Annotated[
    Callable[[str], dict[str, Any] | None], Depends(get_portal_audit_loader)
]


def get_portal_request_inserter() -> RequestInserter:
    """Dependency: the privileged inserter for the tenant-pinned request insert.

    Clients have no base-table write policy, so the create runs on the privileged
    (BYPASSRLS) path; ``client_id`` is pinned server-side in
    :func:`create_client_request`. Resolving the admin pool here surfaces an
    unconfigured DB as a 503 up front. Overridable in tests.
    """
    try:
        get_admin_pool()
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    return insert_request_row


PortalRequestInserterDep = Annotated[RequestInserter, Depends(get_portal_request_inserter)]


def get_portal_deliverable_loader() -> Callable[[str], dict[str, Any] | None]:
    """Dependency: load a deliverable's artifact key + media type + status by id via
    the privileged connection.

    The ``portal_deliverables`` view deliberately hides ``artifact_key`` /
    ``media_type`` / ``status``-for-download, so resolving a file needs a server-side
    read. Callers invoke this ONLY after verifying ownership through the RLS view.
    Overridable in tests.
    """

    def _load(deliverable_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select artifact_key, media_type, status from public.client_deliverables "
                "where id = %s limit 1",
                (deliverable_id,),
            )
            return cur.fetchone()

    return _load


PortalDeliverableLoaderDep = Annotated[
    Callable[[str], dict[str, Any] | None], Depends(get_portal_deliverable_loader)
]


async def _serve_portal_artifact(
    reader: PortalRepo,
    loader: Callable[[str], dict[str, Any] | None],
    store: LocalArtifactStore | None,
    audit_id: str,
    column: str,
    media_type: str,
    download_name: str,
) -> FileResponse:
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    # Ownership: the RLS view returns the row ONLY if it is the caller's own audit.
    owned = await asyncio.to_thread(reader.get_audit, audit_id)
    if owned is None:
        raise _AUDIT_NOT_FOUND
    # Resolve the path server-side (the view hid it); never returned to the client.
    try:
        row = await asyncio.to_thread(loader, audit_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    key = row.get(column) if row else None
    path: Path | None = store.resolve(key) if key else None
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type=media_type, filename=download_name)


async def _serve_portal_deliverable(
    reader: PortalRepo,
    loader: Callable[[str], dict[str, Any] | None],
    store: LocalArtifactStore | None,
    deliverable_id: str,
) -> FileResponse:
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    # Ownership + grant: the RLS view returns the row ONLY if it is the caller's own
    # deliverable AND its `requires` key is granted.
    owned = await asyncio.to_thread(reader.get_deliverable, deliverable_id)
    if owned is None:
        raise _DELIVERABLE_NOT_FOUND
    if owned.get("status") != "ready":  # still generating: no artifact to serve
        raise _ARTIFACT_NOT_FOUND
    # Resolve the artifact key server-side (the view hid it); never returned.
    try:
        row = await asyncio.to_thread(loader, deliverable_id)
    except DatabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    key = row.get("artifact_key") if row else None
    media_type = (row.get("media_type") if row else None) or "application/pdf"
    path: Path | None = store.resolve(key) if key else None
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    ext = _MEDIA_EXT.get(media_type, "")
    return FileResponse(path, media_type=media_type, filename=f"deliverable-{deliverable_id}{ext}")


@router.get("/dashboard", response_model=ClientDashboard)
async def portal_dashboard(reader: PortalRepoDep, _client: CurrentClientDep) -> ClientDashboard:
    client_row = await asyncio.to_thread(reader.get_client)
    if client_row is None:  # pragma: no cover - client_id is FK-guaranteed
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")
    audits = await asyncio.to_thread(reader.list_audits)
    sites = await asyncio.to_thread(reader.list_sites)
    return ClientDashboard.build(client_row, audits, sites)


@router.get("/audits", response_model=list[PortalAuditResponse])
async def list_portal_audits(
    reader: PortalRepoDep, page: PageDep, _client: CurrentClientDep
) -> list[PortalAuditResponse]:
    rows = await asyncio.to_thread(reader.list_audits, limit=page.limit, offset=page.offset)
    return [PortalAuditResponse.from_row(r) for r in rows]


@router.get("/audits/{audit_id}", response_model=PortalAuditResponse)
async def get_portal_audit(
    audit_id: str, reader: PortalRepoDep, _client: CurrentClientDep
) -> PortalAuditResponse:
    row = await asyncio.to_thread(reader.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND
    return PortalAuditResponse.from_row(row)


@router.get("/audits/{audit_id}/report.pdf")
async def download_portal_pdf(
    audit_id: str,
    reader: PortalRepoDep,
    loader: PortalAuditLoaderDep,
    store: ArtifactStoreDep,
    _client: CurrentClientDep,
) -> FileResponse:
    return await _serve_portal_artifact(
        reader, loader, store, audit_id, "pdf_path", "application/pdf", f"audit-{audit_id}.pdf"
    )


@router.get("/audits/{audit_id}/findings.json")
async def download_portal_findings(
    audit_id: str,
    reader: PortalRepoDep,
    loader: PortalAuditLoaderDep,
    store: ArtifactStoreDep,
    _client: CurrentClientDep,
) -> FileResponse:
    return await _serve_portal_artifact(
        reader, loader, store, audit_id, "json_path", "application/json", f"audit-{audit_id}.json"
    )


@router.get("/audits/{audit_id}/report.html")
async def view_portal_report_html(
    audit_id: str,
    reader: PortalRepoDep,
    store: ArtifactStoreDep,
    _client: CurrentClientDep,
) -> FileResponse:
    """Serve the client's own report.html for the in-portal page-viewer.

    Ownership is verified through the RLS view FIRST (the row is returned only if
    it is the caller's own audit); the file is then resolved by convention from the
    audit id (sibling of report.pdf) - the path is never returned to the client.
    """
    if store is None:
        raise _ARTIFACT_NOT_FOUND
    owned = await asyncio.to_thread(reader.get_audit, audit_id)
    if owned is None:
        raise _AUDIT_NOT_FOUND
    path = store.resolve_report_html(audit_id)
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type="text/html", headers=REPORT_HTML_VIEW_HEADERS)


@router.post(
    "/audits",
    response_model=PortalAuditResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("portal_audit_create", 30))],
)
async def create_portal_audit(
    body: PortalAuditCreate,
    reader: PortalRepoDep,
    insert_audit: PortalAuditInserterDep,
    enqueue: AuditEnqueuerDep,
    client: CurrentClientDep,
) -> PortalAuditResponse:
    row = await create_client_audit(
        insert_audit=insert_audit, reader=reader, scoped=client, body=body, enqueue=enqueue
    )
    return PortalAuditResponse.from_row(row)


# --------------------------------------------------------------------------- #
# Part 8: milestones / reports / deliverables / requests
# --------------------------------------------------------------------------- #
@router.get("/milestones", response_model=ClientProjectResponse)
async def portal_milestones(
    reader: PortalRepoDep, _client: CurrentClientDep
) -> ClientProjectResponse:
    """The caller's own engagement timeline (its ClientProject + 5 lifecycle stages).
    404 if no project has been created for the client yet."""
    project = await asyncio.to_thread(reader.get_project)
    if project is None:
        raise _PROJECT_NOT_FOUND
    stages = await asyncio.to_thread(reader.list_project_stages)
    return ClientProjectResponse.from_rows(project, stages)


@router.get("/reports", response_model=list[PortalReportResponse])
async def portal_reports(
    reader: PortalRepoDep, client: CurrentClientDep
) -> list[PortalReportResponse]:
    """The visualizations for the reports the client is GRANTED (ungranted keys are
    never surfaced). Real series for audit-scores / content-status / milestones; the
    rest render representative sample data flagged ``placeholder``."""
    granted = await asyncio.to_thread(reader.granted_report_keys)
    return await asyncio.to_thread(build_report_viz, client.client_id, granted)


@router.get("/deliverables", response_model=list[ClientDeliverableResponse])
async def list_portal_deliverables(
    reader: PortalRepoDep, page: PageDep, _client: CurrentClientDep
) -> list[ClientDeliverableResponse]:
    """The caller's granted, visible deliverables (newest issued first). A deliverable
    whose ``requires`` key is not granted is hidden by the RLS view."""
    rows = await asyncio.to_thread(reader.list_deliverables, limit=page.limit, offset=page.offset)
    return [ClientDeliverableResponse.from_row(r) for r in rows]


@router.get("/deliverables/{deliverable_id}/download")
async def download_portal_deliverable(
    deliverable_id: str,
    reader: PortalRepoDep,
    loader: PortalDeliverableLoaderDep,
    store: ArtifactStoreDep,
    _client: CurrentClientDep,
) -> FileResponse:
    """Download a deliverable's artifact. Ownership + grant are verified through the
    RLS view FIRST; the artifact key is then resolved server-side (never returned).
    404 if the deliverable is unknown/ungranted or still generating."""
    return await _serve_portal_deliverable(reader, loader, store, deliverable_id)


@router.get("/requests", response_model=list[ClientRequestResponse])
async def list_portal_requests(
    reader: PortalRepoDep, page: PageDep, _client: CurrentClientDep
) -> list[ClientRequestResponse]:
    """The caller's own requests (newest first)."""
    rows = await asyncio.to_thread(reader.list_requests, limit=page.limit, offset=page.offset)
    return [ClientRequestResponse.from_row(r) for r in rows]


@router.post(
    "/requests",
    response_model=ClientRequestResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("portal_request_create", 30))],
)
async def create_portal_request(
    body: PortalRequestCreate,
    reader: PortalRepoDep,
    insert_request: PortalRequestInserterDep,
    client: CurrentClientDep,
) -> ClientRequestResponse:
    """Raise a request (status ``open``). ``client_id`` is pinned from the
    authenticated client - never from the body."""
    row = await create_client_request(
        insert_request=insert_request, reader=reader, scoped=client, body=body
    )
    return ClientRequestResponse.from_row(row)
