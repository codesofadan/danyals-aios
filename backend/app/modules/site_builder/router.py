"""Site Builder endpoints: kick off a website analysis/generation job, review the
resolved DesignIR, then explicitly PUBLISH it + poll status + read visual QA.

Access mirrors ``on_page``'s exact reasoning throughout: creating a job / queueing
visual QA only READS an external URL, so both are gated on ``run_audits`` rather
than a lead-only perm; reads add ``view_reports``. PUBLISHING is the one action that
writes to a client's LIVE WordPress site, so - exactly like on_page's apply/revert -
it is LEAD-only (owner/admin/manager): there is deliberately NO auto-publish once
analysis resolves a design, mirroring the content module's own human review gate
(``needs_review``) - a human looks at the resolved design before it goes anywhere.
No feature grant is registered for this module yet (Phase 1) - it ships on the same
perm surface every other read/queue-only action uses, and a dedicated feature grant
can be added once the wizard needs its own on/off toggle.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core import security
from app.core.auth import CurrentUser, require_perm, require_role
from app.core.security import PrivateAddressError
from app.modules.site_builder.repo import SiteBuilderRepoDep
from app.modules.site_builder.schemas import (
    AnalyzeRequest,
    DesignIR,
    SiteGenerationJob,
    SiteTemplate,
    VisualQaRequest,
    VisualValidation,
    design_ir_row_to_response,
    job_row_to_response,
    template_row_to_response,
    visual_validation_row_to_response,
)
from app.modules.site_builder.service import rank_templates
from app.services.activity import record_activity

router = APIRouter(tags=["site-builder"])

ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
RunAudits = Annotated[CurrentUser, Depends(require_perm("run_audits"))]
Lead = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_JOB_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
_DESIGN_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Design not found")
_TEMPLATE_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Template not found")
_URL_REQUIRED = HTTPException(
    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
    detail="source_url is required for existing_site/reference_site",
)
_NOT_READY_TO_PUBLISH = HTTPException(
    status_code=status.HTTP_409_CONFLICT,
    detail="This build is not ready to publish - it has not resolved a design yet",
)


def get_analyze_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the analyze worker (overridable in tests). The Celery
    task is imported lazily so the API process never pulls in the task module (and
    therefore Celery) just to import this router."""

    def _enqueue(job_id: str) -> None:
        from app.modules.site_builder.tasks import analyze_site

        analyze_site.delay(job_id)

    return _enqueue


AnalyzeEnqueuerDep = Annotated[Callable[[str], None], Depends(get_analyze_enqueuer)]


def get_publish_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the render+publish worker (overridable in tests)."""

    def _enqueue(job_id: str) -> None:
        from app.modules.site_builder.tasks import render_and_publish_site

        render_and_publish_site.delay(job_id)

    return _enqueue


PublishEnqueuerDep = Annotated[Callable[[str], None], Depends(get_publish_enqueuer)]

VisualQaEnqueuer = Callable[[str, str], None]


def get_visual_qa_enqueuer() -> VisualQaEnqueuer:
    """Dependency: enqueue the visual-QA worker (overridable in tests)."""

    def _enqueue(job_id: str, rendered_url: str) -> None:
        from app.modules.site_builder.tasks import run_visual_qa

        run_visual_qa.delay(job_id, rendered_url)

    return _enqueue


VisualQaEnqueuerDep = Annotated[VisualQaEnqueuer, Depends(get_visual_qa_enqueuer)]


async def _guard_public_url(url: str) -> None:
    """SSRF pre-check at the edge, before anything is queued - mirrors
    ``app.modules.on_page.router._guard_public_url`` byte-for-byte. This is a
    fail-fast for the operator; the worker's own ``analyze_website`` call
    re-validates regardless (the TOCTOU the guard's own caller contract warns
    about), so the security boundary does not rest on this check alone."""
    try:
        await asyncio.to_thread(security.validate_public_host, url)
    except PrivateAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Unreachable site URL: {exc}"
        ) from exc


@router.post(
    "/site-builder/analyze",
    response_model=SiteGenerationJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze(
    body: AnalyzeRequest,
    repo: SiteBuilderRepoDep,
    actor: RunAudits,
    enqueue: AnalyzeEnqueuerDep,
) -> SiteGenerationJob:
    """Queue ONE website/page build (``run_audits`` - this phase only READS an
    external URL or resolves a template; nothing is published yet).

    SSRF-checks the URL off the event loop before anything is queued when the
    source is a real site; a template/manual source skips that check entirely
    (no external fetch happens for those paths).
    """
    if body.source_type in ("existing_site", "reference_site"):
        if not body.source_url.strip():
            raise _URL_REQUIRED
        await _guard_public_url(body.source_url)

    row = await asyncio.to_thread(
        repo.create_job,
        client_id=body.client_id,
        client_name="",
        source_type=body.source_type,
        source_url=body.source_url,
        page_type=body.template or body.page_type,
        industry=body.industry,
        editor_mode=body.editor_mode,
        fidelity_mode=body.fidelity_mode,
        created_by=actor.id,
    )
    enqueue(str(row["id"]))
    await record_activity(
        actor, kind="content", action=f"started a site build ({body.source_type})",
        target=body.source_url or body.template or body.page_type or "blank",
    )
    return job_row_to_response(row)


@router.post(
    "/site-builder/jobs/{code}/publish",
    response_model=SiteGenerationJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def publish_job(
    code: str, repo: SiteBuilderRepoDep, actor: Lead, enqueue: PublishEnqueuerDep,
) -> SiteGenerationJob:
    """Render the resolved design and PUSH IT TO THE CLIENT'S LIVE WORDPRESS SITE
    as a draft (LEAD-only - owner/admin/manager).

    409 unless the job has actually resolved a design (``generating``) - mirrors the
    on_page re-analyze guard: a double-click or a build still mid-analysis gets a
    clean conflict instead of a silently-ignored publish. There is deliberately NO
    auto-publish from ``analyze`` straight through to here: a human reviews the
    resolved design (once the wizard shows it) before anything goes live, exactly
    like the content module's own ``needs_review`` gate.
    """
    row = await asyncio.to_thread(repo.get_job_by_code, code)
    if row is None:
        raise _JOB_NOT_FOUND
    if row.get("status") != "generating":
        raise _NOT_READY_TO_PUBLISH
    enqueue(str(row["id"]))
    await record_activity(
        actor, kind="content", action="published a site build to WordPress (draft)", target=code,
    )
    return job_row_to_response(row)


@router.get("/site-builder/jobs", response_model=list[SiteGenerationJob])
async def list_jobs(
    repo: SiteBuilderRepoDep,
    _user: ViewReports,
    client_id: Annotated[str | None, Query(alias="clientId")] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[SiteGenerationJob]:
    """The build queue (newest first), optionally filtered by client/status."""
    rows = await asyncio.to_thread(repo.list_jobs, client_id=client_id, status=status_, limit=100)
    return [job_row_to_response(r) for r in rows]


@router.get("/site-builder/jobs/{code}", response_model=SiteGenerationJob)
async def get_job(code: str, repo: SiteBuilderRepoDep, _user: ViewReports) -> SiteGenerationJob:
    """Poll ONE job's status - the browser's "Analyzing... Generating..." progress copy."""
    row = await asyncio.to_thread(repo.get_job_by_code, code)
    if row is None:
        raise _JOB_NOT_FOUND
    return job_row_to_response(row)


@router.get("/site-builder/designs/{design_id}", response_model=DesignIR)
async def get_design(design_id: str, repo: SiteBuilderRepoDep, _user: ViewReports) -> DesignIR:
    """Read one resolved DesignIR (the platform-independent design a job produced)."""
    row = await asyncio.to_thread(repo.get_design_ir, design_id)
    if row is None:
        raise _DESIGN_NOT_FOUND
    return design_ir_row_to_response(row)


@router.get("/site-builder/templates", response_model=list[SiteTemplate])
async def list_templates(
    repo: SiteBuilderRepoDep,
    _user: ViewReports,
    category: Annotated[str | None, Query()] = None,
    industry: Annotated[str | None, Query()] = None,
    page_type: Annotated[str | None, Query(alias="pageType")] = None,
) -> list[SiteTemplate]:
    """The template gallery (Step 2/3 of the wizard - "Template"), ranked by how
    well each entry matches the requested industry/page type when either is given."""
    rows = await asyncio.to_thread(
        repo.list_templates, category=category, industry=industry, page_type=page_type,
    )
    ranked = rank_templates(rows, industry=industry or "", page_type=page_type or "")
    return [template_row_to_response(r) for r in ranked]


@router.get("/site-builder/templates/{key}", response_model=SiteTemplate)
async def get_template(key: str, repo: SiteBuilderRepoDep, _user: ViewReports) -> SiteTemplate:
    row = await asyncio.to_thread(repo.get_template_by_key, key)
    if row is None:
        raise _TEMPLATE_NOT_FOUND
    return template_row_to_response(row)


@router.post(
    "/site-builder/jobs/{code}/visual-qa",
    response_model=SiteGenerationJob,
    status_code=status.HTTP_202_ACCEPTED,
)
async def queue_visual_qa(
    code: str,
    body: VisualQaRequest,
    repo: SiteBuilderRepoDep,
    actor: RunAudits,
    enqueue: VisualQaEnqueuerDep,
) -> SiteGenerationJob:
    """Diff ONE job's resolved design against a rendered build (``run_audits`` -
    this only READS the rendered page; the diff never mutates anything live).

    A later publish phase calls this automatically with the just-published URL;
    exposed here too so visual QA is independently triggerable/testable today.
    """
    row = await asyncio.to_thread(repo.get_job_by_code, code)
    if row is None:
        raise _JOB_NOT_FOUND
    await _guard_public_url(body.rendered_url)
    enqueue(str(row["id"]), body.rendered_url)
    await record_activity(
        actor, kind="content", action="queued visual QA for a site build", target=code,
    )
    return job_row_to_response(row)


@router.get("/site-builder/jobs/{code}/visual-validations", response_model=list[VisualValidation])
async def list_visual_validations(
    code: str, repo: SiteBuilderRepoDep, _user: ViewReports,
) -> list[VisualValidation]:
    """The visual-QA history for ONE job (newest first) - structured, multi-
    dimension diagnostics, never a single similarity score."""
    row = await asyncio.to_thread(repo.get_job_by_code, code)
    if row is None:
        raise _JOB_NOT_FOUND
    rows = await asyncio.to_thread(repo.list_visual_validations, str(row["id"]))
    return [visual_validation_row_to_response(r) for r in rows]
