"""Part 7 Module 02 (Content) endpoints: the content-job board, the create-and-
enqueue seam, and the human review gate. Reads require any provisioned staff
(``view_reports`` - a portal client holds none, so clients are 403'd off the whole
surface); creating a job requires ``publish_content``; the review/edit decisions
are LEAD-only (owner/admin/manager).

Responses are the frontend ``ContentJob`` shape (``id`` = the public ``CJ-####``
code; ``client``/``color`` are display SNAPSHOTS so ``client_id`` never leaks). The
app-layer 403/409 here are clean UX; the REAL lifecycle boundary is the
``content_jobs_guard_update`` DB trigger (the 3-actor model: the worker advances
``queued->drafting->needs_review`` + ``publishing->done`` on the privileged pool;
LEADS own the review exit ``needs_review->publishing/rejected/drafting`` on the RLS
pool; a non-lead can drive NOTHING). Every human mutation therefore stays on the
RLS path (``ContentRepo`` -> ``rls_connection``); only the worker touches the
privileged pool. Blocking psycopg calls are offloaded with ``asyncio.to_thread``
and every mutation appends an activity entry.

The create seam SNAPSHOTS the client name/color, RESOLVES the framework (``Auto`` ->
``auto_framework(pageType)`` with ``auto=true``) + the JSON-LD ``schema_type``
(``schema_for(pageType)``) server-side, and SEEDS ``source_pack`` (client facts +
WordPress publish config) so the worker draws grounding + the publish target from
the row, never from a request body. The worker enqueue + the publish enqueue are
overridable dependencies so the endpoints unit-test with zero broker.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.pagination import PageDep
from app.db.clients_repo import ClientsRepoDep
from app.db.content_repo import ContentRepoDep
from app.schemas.content import (
    ContentJobCreate,
    ContentJobResponse,
    ContentJobUpdate,
    ContentReviewRequest,
    ContentStatsResponse,
    auto_framework,
    compute_content_stats,
    schema_for,
)
from app.services.activity import record_activity

router = APIRouter(tags=["content"])

# All six staff roles hold view_reports; a portal client does NOT, confining
# clients out of the staff content namespace (mirrors audits.py / tasks.py).
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Creating (queueing) a content job = the publish_content permission (owner/admin/
# manager/specialist hold it). The closest content perm in the 8-permission matrix.
PublishContent = Annotated[CurrentUser, Depends(require_perm("publish_content"))]
# The review gate + limited edits are LEAD-only (owner/admin/manager) - the exact
# set the DB guard's path-2 recognises for the needs_review exit.
LeadOnly = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

# The server-only rich columns each rich-retrieval endpoint returns (never in the
# 15-key ContentJob contract). Keyed by the URL suffix.
_RICH_COLUMNS: dict[str, str] = {
    "draft": "draft_md",
    "keywords": "keyword_map",
    "qa": "qa_score",
    "schema": "json_ld",
}

_JOB_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Content job not found")
_NOT_IN_REVIEW = HTTPException(
    status_code=status.HTTP_409_CONFLICT, detail="Content job is not awaiting review"
)


# --------------------------------------------------------------------------- #
# Enqueuer dependencies (overridable in tests; the worker task is imported lazily
# so the API process never pulls in Celery task modules just to import the router).
# --------------------------------------------------------------------------- #
def get_content_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the content PIPELINE worker for a job code."""

    def _enqueue(code: str) -> None:
        from workers.tasks.content import run_content_job

        run_content_job.delay(code)

    return _enqueue


def get_content_publish_enqueuer() -> Callable[[str], None]:
    """Dependency: enqueue the content PUBLISH worker for an approved job code."""

    def _enqueue(code: str) -> None:
        from workers.tasks.content import publish_content_job_task

        publish_content_job_task.delay(code)

    return _enqueue


ContentEnqueuerDep = Annotated[Callable[[str], None], Depends(get_content_enqueuer)]
ContentPublishEnqueuerDep = Annotated[Callable[[str], None], Depends(get_content_publish_enqueuer)]


# --------------------------------------------------------------------------- #
# source_pack seeding (client facts + WordPress publish config)
# --------------------------------------------------------------------------- #
def _seed_source_pack(client: dict[str, Any], site: dict[str, Any] | None, *, target: str) -> dict[str, Any]:
    """Assemble the worker's ``source_pack`` grounding from the client + its site.

    Snapshots the client FACTS (name/industry/founded/contact) the generator grounds
    against, and - for a WordPress target - the publish site URL. Per-site WP app
    passwords live encrypted in the vault (never in a request body); the publish
    chunk reveals them, so this seeds only the non-secret site reference. A missing
    site simply omits the WP config, and the publish path degrades to artifact-only.
    """
    facts: dict[str, str] = {}
    if client.get("industry"):
        facts["industry"] = str(client["industry"])
    if client.get("since_year"):
        facts["founded"] = str(client["since_year"])
    if client.get("contact_name"):
        facts["primary_contact"] = str(client["contact_name"])
    if client.get("contact_role"):
        facts["contact_role"] = str(client["contact_role"])

    pack: dict[str, Any] = {"client_name": client.get("name", ""), "facts": facts}
    if target == "WordPress" and site is not None:
        domain = str(site.get("domain") or "").strip()
        if domain:
            site_url = domain if domain.startswith(("http://", "https://")) else f"https://{domain}"
            pack["wp_site_url"] = site_url
            pack["site_url"] = site_url
    return pack


async def _first_site(clients: ClientsRepoDep, client_id: str) -> dict[str, Any] | None:
    sites = await asyncio.to_thread(clients.list_sites, client_id, limit=1, offset=0)
    return sites[0] if sites else None


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get("/content/jobs", response_model=list[ContentJobResponse])
async def list_content_jobs(
    repo: ContentRepoDep,
    page: PageDep,
    _user: ViewReports,
    client: Annotated[str | None, Query()] = None,
    status_: Annotated[str | None, Query(alias="status")] = None,
) -> list[ContentJobResponse]:
    """List content jobs (created_at desc). Optional ``?client`` (client_id) and
    ``?status`` filters; paginated via the hard-capped PageDep."""
    rows = await asyncio.to_thread(
        repo.list_jobs, client_id=client, status=status_, limit=page.limit, offset=page.offset
    )
    return [ContentJobResponse.from_row(r) for r in rows]


@router.get("/content/jobs/stats", response_model=ContentStatsResponse)
async def content_stats(repo: ContentRepoDep, _user: ViewReports) -> ContentStatsResponse:
    """The 4 content-board KPIs (in-pipeline, awaiting-review, published-this-month,
    avg cost of priced jobs)."""
    rows = await asyncio.to_thread(repo.list_jobs)
    return compute_content_stats(rows)


@router.get("/content/jobs/{code}", response_model=ContentJobResponse)
async def get_content_job(code: str, repo: ContentRepoDep, _user: ViewReports) -> ContentJobResponse:
    """One content job in the 15-key ContentJob shape."""
    row = await asyncio.to_thread(repo.get_job_by_code, code)
    if row is None:
        raise _JOB_NOT_FOUND
    return ContentJobResponse.from_row(row)


@router.get("/content/jobs/{code}/{column}")
async def get_content_rich(code: str, column: str, repo: ContentRepoDep, _user: ViewReports) -> dict[str, Any]:
    """Rich retrieval (staff-only, NOT contract-locked): the server-only pipeline
    columns a reviewer needs - ``draft`` (markdown), ``keywords`` (keyword_map),
    ``qa`` (the QA scorecard), ``schema`` (the assembled JSON-LD). 404 on an
    unknown column or job."""
    db_column = _RICH_COLUMNS.get(column)
    if db_column is None:
        raise _JOB_NOT_FOUND
    row = await asyncio.to_thread(repo.get_job_by_code, code)
    if row is None:
        raise _JOB_NOT_FOUND
    return {"id": str(row.get("code", code)), column: row.get(db_column)}


# --------------------------------------------------------------------------- #
# Create (queue + enqueue the pipeline worker)
# --------------------------------------------------------------------------- #
@router.post("/content/jobs", response_model=ContentJobResponse, status_code=status.HTTP_201_CREATED)
async def create_content_job(
    body: ContentJobCreate,
    repo: ContentRepoDep,
    clients: ClientsRepoDep,
    enqueue: ContentEnqueuerDep,
    actor: PublishContent,
) -> ContentJobResponse:
    """Queue a new content job (status=queued) and enqueue the pipeline worker.

    Validates + snapshots the client (name/color - never the client_id), RESOLVES
    the framework (``Auto`` -> ``auto_framework(pageType)`` with ``auto=true``) and
    the JSON-LD ``schema_type`` (``schema_for(pageType)``) server-side, seeds
    ``source_pack`` (client facts + WP publish config), inserts the queued row on
    the RLS path, and enqueues ``run_content_job``.
    """
    client = await asyncio.to_thread(clients.get_client, body.client_id)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    # Resolve the framework: the "Auto" sentinel picks per page type + flags auto.
    if body.framework == "Auto":
        framework = auto_framework(body.page_type)
        auto = True
    else:
        framework = body.framework
        auto = False

    site = await _first_site(clients, body.client_id) if body.target == "WordPress" else None
    source_pack = _seed_source_pack(client, site, target=body.target)

    row = await asyncio.to_thread(
        repo.insert_job,
        {
            "client_id": body.client_id,
            "client_name": client.get("name", ""),
            "color": client.get("contact_color", "#7B69EE"),
            "page_type": body.page_type,
            "topic": body.topic,
            "framework": framework,
            "auto": auto,
            "target": body.target,
            "status": "queued",
            "schema_type": schema_for(body.page_type),
            "stage": "Queued",
            "source_pack": Jsonb(source_pack),
        },
    )
    enqueue(str(row["code"]))
    await record_activity(
        actor, kind="content", action="queued a content job", target=client.get("name", ""),
        entity_type="client", entity_id=body.client_id,
    )
    return ContentJobResponse.from_row(row)


# --------------------------------------------------------------------------- #
# Review gate (LEAD-only; the needs_review exit)
# --------------------------------------------------------------------------- #
@router.post("/content/jobs/{code}/review", response_model=ContentJobResponse)
async def review_content_job(
    code: str,
    body: ContentReviewRequest,
    repo: ContentRepoDep,
    enqueue_publish: ContentPublishEnqueuerDep,
    actor: LeadOnly,
) -> ContentJobResponse:
    """The human review gate (owner/admin/manager only). ``approve`` -> publishing
    (and enqueue the publish worker), ``edit`` -> drafting, ``reject`` -> rejected.
    409 unless the job is in needs_review (optimistic ``expect_status``). All three
    transitions run on the RLS path, where the DB guard recognises the lead."""
    job = await asyncio.to_thread(repo.get_job_by_code, code)
    if job is None:
        raise _JOB_NOT_FOUND
    if job.get("status") != "needs_review":
        raise _NOT_IN_REVIEW

    new_status = {"approve": "publishing", "edit": "drafting", "reject": "rejected"}[body.action]
    updated = await asyncio.to_thread(
        repo.update_job_by_code, code, {"status": new_status}, "needs_review"
    )
    if updated is None:
        # A racing transition already moved the row (optimistic concurrency), or the
        # DB guard rejected it (defense in depth) - either way it is no longer ours.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Content job changed concurrently")

    if body.action == "approve":
        # The worker owns publishing->done on the privileged pool; hand it off.
        enqueue_publish(code)

    action = {
        "approve": "approved content for publishing",
        "edit": "sent content back for edits",
        "reject": "rejected content",
    }[body.action]
    client_id = job.get("client_id")
    await record_activity(
        actor, kind="content", action=action, target=job.get("client_name", ""),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    return ContentJobResponse.from_row(updated)


# --------------------------------------------------------------------------- #
# Limited edit (LEAD-only)
# --------------------------------------------------------------------------- #
@router.patch("/content/jobs/{code}", response_model=ContentJobResponse)
async def patch_content_job(
    code: str, body: ContentJobUpdate, repo: ContentRepoDep, actor: LeadOnly
) -> ContentJobResponse:
    """Edit a job's inputs (topic/brief) - LEAD-only. Status is untouched (it moves
    only via /review and the worker). Runs on the RLS path (the DB guard's lead
    branch); an empty patch is a no-op."""
    job = await asyncio.to_thread(repo.get_job_by_code, code)
    if job is None:
        raise _JOB_NOT_FOUND

    provided = body.model_dump(exclude_unset=True)
    patch: dict[str, Any] = {}
    if provided.get("topic") is not None:
        patch["topic"] = provided["topic"]
    if "brief" in provided and provided["brief"] is not None:
        patch["brief"] = provided["brief"]

    if not patch:
        return ContentJobResponse.from_row(job)  # nothing to change

    updated = await asyncio.to_thread(repo.update_job_by_code, code, patch)
    if updated is None:
        raise _JOB_NOT_FOUND
    client_id = job.get("client_id")
    await record_activity(
        actor, kind="content", action="edited a content job", target=job.get("client_name", ""),
        entity_type="client" if client_id is not None else None,
        entity_id=str(client_id) if client_id is not None else None,
    )
    return ContentJobResponse.from_row(updated)
