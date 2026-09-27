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
from app.modules.content_experience.router import fmt_day, resume_held_pages
from app.routers.audits import ArtifactStoreDep, AuditEnqueuerDep
from app.schemas.audits import PortalAuditCreate, PortalAuditResponse
from app.schemas.milestones import ClientProjectResponse
from app.schemas.portal import ClientDashboard
from app.schemas.portal_content import (
    PortalContentJobResponse,
    PortalExperienceAnswers,
    PortalExperienceResponse,
    PortalExperienceSlot,
    PortalExperienceSummary,
)
from app.schemas.portal_deliverables import ClientDeliverableResponse
from app.schemas.portal_reports import PortalReportResponse
from app.schemas.portal_requests import ClientRequestResponse, PortalRequestCreate
from app.schemas.threads import MessageCreate, PortalMessageResponse
from app.services import client_experience
from app.services.audit_artifacts import REPORT_HTML_VIEW_HEADERS, LocalArtifactStore
from app.services.audit_sheets import SHEET_FILES, sheet_media_type
from app.services.client_audits import AuditInserter, create_client_audit, insert_audit_row
from app.services.client_requests import RequestInserter, create_client_request, insert_request_row
from app.services.experience_options import PriorAnswer, evidence_from, options_for_all
from app.services.portal_threads import list_own_messages, post_client_message
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
# A job belonging to ANOTHER client gets this same answer as a job that does not exist:
# the portal must not be usable to probe for other tenants' page codes.
_CONTENT_JOB_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Page not found"
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


@router.get("/audits/{audit_id}/sheets/{name}")
async def download_portal_sheet(
    audit_id: str,
    name: str,
    reader: PortalRepoDep,
    store: ArtifactStoreDep,
    _client: CurrentClientDep,
) -> FileResponse:
    """Download the client's own audit remediation sheet (xlsx or csv).

    Same access as the report.pdf/findings.json portal downloads: ownership is
    verified through the RLS view FIRST (the row is returned only if it is the
    caller's own audit); the file is then resolved by convention from the audit
    id (sibling of report.pdf) - the path is never returned to the client.
    ``name`` is restricted to the known sheet allow-list.
    """
    if name not in SHEET_FILES or store is None:
        raise _ARTIFACT_NOT_FOUND
    owned = await asyncio.to_thread(reader.get_audit, audit_id)
    if owned is None:
        raise _AUDIT_NOT_FOUND
    path = store.resolve_sheet(audit_id, name)
    if path is None:
        raise _ARTIFACT_NOT_FOUND
    return FileResponse(
        path, media_type=sheet_media_type(name), filename=f"audit-{audit_id}-{name}"
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


# --- The conversation on a request (0098) ------------------------------------
# A client raises a request and the agency replies. Until now that was a single
# `support_tickets.reply` column: one reply, and the conversation had nowhere to go.
#
# Both routes address the request by its public T-#### code and resolve it through
# `portal_requests` FIRST, so a code belonging to another tenant is a 404 - the same
# answer as a code that does not exist.
_REQUEST_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="No such request"
)


@router.get("/requests/{code}/messages", response_model=list[PortalMessageResponse])
async def list_portal_request_messages(
    code: str, client: CurrentClientDep
) -> list[PortalMessageResponse]:
    """The client-visible conversation on the caller's own request, oldest first.

    Reads `portal_thread_messages`, which filters out `visibility = 'internal'` in
    the view itself - an internal note is never selected, not merely omitted from the
    response model.
    """
    rows = await asyncio.to_thread(list_own_messages, user_id=client.user.id, code=code)
    if rows is None:
        raise _REQUEST_NOT_FOUND
    return [PortalMessageResponse.from_row(r) for r in rows]


@router.post(
    "/requests/{code}/messages",
    response_model=PortalMessageResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(rate_limit("portal_message_create", 60))],
)
async def post_portal_request_message(
    code: str,
    body: MessageCreate,
    reader: PortalRepoDep,
    client: CurrentClientDep,
) -> PortalMessageResponse:
    """Add the client's own message to their request.

    `body.visibility` is IGNORED here. The service pins `client_visible` and
    `author_kind='client'` as literals, and the DB refuses the other combination
    (`thread_messages_client_is_visible_ck`), so a client cannot file an internal
    note however the request is shaped.
    """
    client_row = await asyncio.to_thread(reader.get_client)
    author = str((client_row or {}).get("name") or "Client")
    posted = await post_client_message(
        scoped=client, code=code, body=body.body, author_name=author
    )
    if posted is None:
        raise _REQUEST_NOT_FOUND
    return PortalMessageResponse.from_row(posted)


# --------------------------------------------------------------------------- #
# Content: what the client may see, and the one thing only they can answer
# --------------------------------------------------------------------------- #
# READ-ONLY, by decision (2026-09-26). The client sees the stage each page is at and
# where it published; a lead remains the only approver, so there is no mutation here
# beyond answering the Experience questions - which is not a content mutation at all,
# it is the client supplying their own facts.
@router.get("/content", response_model=list[PortalContentJobResponse])
async def list_portal_content(
    reader: PortalRepoDep, page: PageDep, _client: CurrentClientDep
) -> list[PortalContentJobResponse]:
    """The caller's own content pages (newest first), through the client-safe view."""
    rows = await asyncio.to_thread(
        reader.list_content_jobs, limit=page.limit, offset=page.offset
    )
    return [PortalContentJobResponse.from_row(r) for r in rows]


@router.get("/experience", response_model=list[PortalExperienceSummary])
async def list_portal_experience(client: CurrentClientDep) -> list[PortalExperienceSummary]:
    """Every page of the client's that is waiting on their answers.

    The portal's own to-do list. Without it the client has to be TOLD which page codes
    to open - by a person, in a message - which is exactly the work this surface removes.
    """
    rows = await asyncio.to_thread(client_experience.open_questions_for_client, client.client_id)
    return [PortalExperienceSummary.from_row(r) for r in rows]


@router.get("/experience/{code}", response_model=PortalExperienceResponse)
async def get_portal_experience(
    code: str, client: CurrentClientDep
) -> PortalExperienceResponse:
    """The client's own Experience questions for one page, with pickable options.

    The tenant is pinned from the session, so a code belonging to another client is a
    404 - the same answer as a code that does not exist, which is what stops the portal
    being used to probe for other tenants' job codes.
    """
    return await asyncio.to_thread(_portal_experience_body, code, client.client_id)


@router.put(
    "/experience/{code}",
    response_model=PortalExperienceResponse,
    dependencies=[Depends(rate_limit("portal_experience_answer", 60))],
)
async def put_portal_experience(
    code: str,
    body: PortalExperienceAnswers,
    client: CurrentClientDep,
) -> PortalExperienceResponse:
    """Record the CLIENT's answers to their own Experience questions.

    Attested as theirs (``source='client'`` plus the portal user id), because the whole
    value of a client-supplied fact is that the client stands behind it. Unknown slot
    keys are refused rather than ignored: the pipeline decides which proof categories a
    page needs, and a caller inventing a key could otherwise mark a dossier complete
    without answering what was asked.

    A completed dossier resumes the held pages, exactly as when staff answer.
    """
    job = await asyncio.to_thread(client_experience.job_for_client, code, client.client_id)
    if job is None:
        raise _CONTENT_JOB_NOT_FOUND
    found = await asyncio.to_thread(client_experience.dossier_for_client_job, job)
    if found is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This page has no questions yet - it has not started.",
        )
    dossier, slots = found
    known = {str(row["slot_key"]) for row in slots}
    unknown = sorted({a.slot_key for a in body.answers} - known)
    if unknown:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"unknown Experience slots: {', '.join(unknown)}",
        )
    status_now = await asyncio.to_thread(
        client_experience.answer_slots_as_client,
        str(dossier["id"]),
        [a.as_row() for a in body.answers],
        # The PORTAL USER who attested it. CurrentClient wraps the user row plus the
        # server-pinned tenant, so the identity lives on `.user`.
        actor_id=client.user.id,
    )
    out = await asyncio.to_thread(_portal_experience_body, code, client.client_id)
    if status_now == "complete":
        out.resumed = resume_held_pages(code)
    return out


def _portal_experience_body(code: str, client_id: str) -> PortalExperienceResponse:
    """Build the client-facing questionnaire payload. Blocking; callers offload it.

    Shares the OPTION ENGINE with the staff route rather than re-deriving suggestions:
    the client and the operator must never be shown a different set of choices for the
    same question, and one function is the only way to guarantee that.
    """
    job = client_experience.job_for_client(code, client_id)
    if job is None:
        raise _CONTENT_JOB_NOT_FOUND
    found = client_experience.dossier_for_client_job(job)
    if found is None:
        return PortalExperienceResponse(
            code=code, status="not_started", cluster_key="", topic=str(job.get("topic") or ""),
            slots=[],
        )
    dossier, slots = found
    prior = tuple(
        PriorAnswer(
            slot_key=str(row.get("slot_key") or ""),
            answer=str(row.get("answer") or ""),
            cluster_key=str(row.get("cluster_key") or ""),
            answered_on=fmt_day(row.get("answered_at")),
        )
        for row in client_experience.prior_answers_for_client(
            client_id, exclude_dossier_id=str(dossier["id"])
        )
    )
    facts = client_experience.client_facts(client_id) or {}
    # The client's own blurb, as site copy: their words about themselves. The trading year
    # is `clients.since_year` and arrives on the same row - there is no second founding-year
    # column to reconcile (an earlier version reconciled one that does not exist).
    site_copy = tuple(
        str(facts.get(field) or "")
        for field in ("description",)
        if str(facts.get(field) or "").strip()
    )
    pack = job.get("source_pack") if isinstance(job.get("source_pack"), dict) else {}
    evidence = evidence_from(
        client=facts, source_pack=pack or {}, site_copy=site_copy, prior=prior
    )
    options = options_for_all(tuple(str(s["slot_key"]) for s in slots), evidence)
    return PortalExperienceResponse(
        code=code,
        status=str(dossier.get("status") or "empty"),
        cluster_key=str(dossier.get("cluster_key") or ""),
        topic=str(job.get("topic") or ""),
        slots=[
            PortalExperienceSlot.from_row(row, options.get(str(row["slot_key"]), []))
            for row in slots
        ],
    )
