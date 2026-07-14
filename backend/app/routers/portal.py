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
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import FileResponse
from supabase import Client

from app.core.auth import CurrentClientDep
from app.core.pagination import PageDep
from app.core.ratelimit import rate_limit
from app.db.portal_repo import PortalRepo, PortalRepoDep
from app.db.supabase import SupabaseNotConfiguredError, get_admin_client
from app.routers.audits import ArtifactStoreDep, AuditEnqueuerDep
from app.schemas.audits import PortalAuditCreate, PortalAuditResponse
from app.schemas.portal import ClientDashboard
from app.services.audit_artifacts import LocalArtifactStore
from app.services.client_audits import create_client_audit

router = APIRouter(prefix="/portal", tags=["portal"])

_AUDIT_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit not found")
_ARTIFACT_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Artifact not available"
)
_DB_NOT_CONFIGURED = HTTPException(
    status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not configured"
)


def get_portal_admin() -> Client:
    """Dependency: the service_role admin client for the tenant-pinned insert."""
    try:
        return get_admin_client()
    except SupabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc


PortalAdminDep = Annotated[Client, Depends(get_portal_admin)]


def get_portal_audit_loader() -> Callable[[str], dict[str, Any] | None]:
    """Dependency: load an audit's artifact PATHS by id via the admin client.

    The ``portal_audits`` view deliberately hides ``pdf_path``/``json_path``, so
    resolving a file for download needs a server-side (service_role) read. Callers
    invoke this ONLY after verifying ownership through the RLS view. Overridable
    in tests.
    """

    def _load(audit_id: str) -> dict[str, Any] | None:
        admin = get_admin_client()
        resp = (
            admin.table("audits")
            .select("pdf_path, json_path")
            .eq("id", audit_id)
            .limit(1)
            .execute()
        )
        rows = cast("list[dict[str, Any]]", resp.data or [])
        return rows[0] if rows else None

    return _load


PortalAuditLoaderDep = Annotated[
    Callable[[str], dict[str, Any] | None], Depends(get_portal_audit_loader)
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
    except SupabaseNotConfiguredError as exc:
        raise _DB_NOT_CONFIGURED from exc
    key = row.get(column) if row else None
    path: Path | None = store.resolve(key) if key else None
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(path, media_type=media_type, filename=download_name)


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


@router.post(
    "/audits",
    response_model=PortalAuditResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("portal_audit_create", 30))],
)
async def create_portal_audit(
    body: PortalAuditCreate,
    reader: PortalRepoDep,
    admin: PortalAdminDep,
    enqueue: AuditEnqueuerDep,
    client: CurrentClientDep,
) -> PortalAuditResponse:
    row = await create_client_audit(
        admin=admin, reader=reader, scoped=client, body=body, enqueue=enqueue
    )
    return PortalAuditResponse.from_row(row)
