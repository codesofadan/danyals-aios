"""Module 01 Audit endpoints. Reads require any provisioned staff; running an
audit requires ``run_audits``. Responses match the frontend ``AuditRow`` shape.

POST /audits SSRF-guards the URL (off the event loop), gates paid audit types
off the Free tier, inserts a ``queued`` row (RLS-scoped), and enqueues the
Celery worker that runs the external engine. The worker owns the run lifecycle.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Annotated

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
    AuditResponse,
    AuditStatsResponse,
    compute_audit_stats,
    tier_to_db,
)
from app.services.activity import record_activity
from app.services.audit_artifacts import LocalArtifactStore, local_store_from_settings

router = APIRouter(tags=["audits"])

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


@router.get("/audits", response_model=list[AuditResponse])
async def list_audits(repo: AuditsRepoDep, page: PageDep, _user: ViewReports) -> list[AuditResponse]:
    rows = await asyncio.to_thread(repo.list_audits, limit=page.limit, offset=page.offset)
    return [AuditResponse.from_row(r) for r in rows]


@router.get("/audits/stats", response_model=AuditStatsResponse)
async def audit_stats(repo: AuditsRepoDep, _user: ViewReports) -> AuditStatsResponse:
    rows = await asyncio.to_thread(repo.list_audits)
    return compute_audit_stats(rows)


@router.get("/audits/{audit_id}", response_model=AuditResponse)
async def get_audit(audit_id: str, repo: AuditsRepoDep, _user: ViewReports) -> AuditResponse:
    row = await asyncio.to_thread(repo.get_audit, audit_id)
    if row is None:
        raise _AUDIT_NOT_FOUND
    return AuditResponse.from_row(row)


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

    row = await asyncio.to_thread(
        repo.insert_audit,
        {
            "client_id": body.client_id,
            "client_name": client.get("name", ""),
            "url": body.url,
            "types": body.types,
            "tier": tier_to_db(body.tier),
            "status": "queued",
        },
    )
    enqueue(str(row["id"]))
    await record_activity(
        actor, kind="audit", action="ran an audit", target=body.url,
        entity_type="client", entity_id=body.client_id,
    )
    return AuditResponse.from_row(row)
