"""Design Replication endpoints - the replica engine's front door.

``POST /replica`` queues the URL -> Elementor-draft pipeline on the Celery BROWSER
queue (the capture drives Playwright for ~30-60s, so it NEVER runs inline here) and
returns 202 with a job handle. ``GET /replica/{job_id}`` reads that job's status and
result straight off the job ledger (``job_runs``) - the worker runs under
``@aios_job``, so the ledger row is the one honest record and this router adds no
second status store to drift from it.

Two gates before anything is enqueued:

* the COPYRIGHT gate - the rebuild carries the source page's own copy and imagery,
  so the caller must assert the client owns the source (400 otherwise);
* the SSRF guard - the URL must resolve to a public address (400 otherwise), checked
  off the event loop because ``getaddrinfo`` blocks.

Both routes are staff-only behind ``publish_content`` (the same permission that
pushes content live), and WordPress credentials never appear in the request: the
worker resolves the client's STORED connection (0058) server-side.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.auth import CurrentUser, require_perm
from app.core.security import PrivateAddressError, validate_public_host
from app.db.clients_repo import ClientsRepoDep
from app.db.job_runs_repo import JobRunsRepo, JobRunsRepoDep
from app.schemas.replica import (
    ReplicaCreateRequest,
    ReplicaJobResponse,
    ReplicaQueuedResponse,
)
from app.services.activity import record_activity

router = APIRouter(tags=["replica"])

# Queueing a replica publishes a draft carrying a whole page onto a client's site -
# the publish_content permission, same as the content module's create/queue door.
PublishContent = Annotated[CurrentUser, Depends(require_perm("publish_content"))]

#: The logical job name the worker records (pinned in ``workers/tasks/replica.py``;
#: mirrored here so reading the ledger does not import the Celery task module).
_JOB_NAME = "replica.publish"

_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replica job not found")


def get_replica_starter() -> Callable[..., str]:
    """Dependency: start (or find) the replica job; returns the job id (overridable
    in tests).

    Lazy imports keep Celery task modules out of the API process until a replica is
    actually queued - the same rule as the audits/content enqueuers. Importing the
    task module also registers its queue in ``TASK_QUEUES``, so ``enqueue`` routes
    to ``browser`` rather than the default queue.

    IDEMPOTENT CREATE: the job's key is a deterministic function of the WORK
    (client, url, slug). When a run for that key already exists, its handle is
    returned instead of enqueueing a duplicate - the runner's claim would skip the
    duplicate anyway, but its fresh Celery id would then never map to a ledger row
    and would read "queued" forever. Two racing first-POSTs can still each enqueue
    (no row exists yet to find); the claim resolves that race at the database and
    the loser's handle stays honestly unclaimed.
    """

    def _start(
        repo: JobRunsRepo,
        *,
        client_id: str,
        url: str,
        title: str | None,
        slug: str | None,
        client_name: str,
    ) -> str:
        from app.jobs.celery_task import enqueue
        from workers.tasks.replica import TASK_NAME, replica_idempotency_key

        existing = repo.get_run_by_idempotency_key(replica_idempotency_key(client_id, url, slug))
        if existing is not None and existing.get("celery_task_id"):
            return str(existing["celery_task_id"])
        return enqueue(
            TASK_NAME, client_id, url, title=title, slug=slug, client_name=client_name
        )

    return _start


ReplicaStarterDep = Annotated[Callable[..., str], Depends(get_replica_starter)]


@router.post(
    "/replica", response_model=ReplicaQueuedResponse, status_code=status.HTTP_202_ACCEPTED
)
async def create_replica_job(
    body: ReplicaCreateRequest,
    actor: PublishContent,
    clients: ClientsRepoDep,
    repo: JobRunsRepoDep,
    start: ReplicaStarterDep,
) -> ReplicaQueuedResponse:
    """Queue a design replication of ``body.url`` onto the client's connected site."""
    # The copyright gate. Refused HERE, before anything is captured: the rebuild
    # carries the source page's actual words and imagery, so a person must assert
    # the client owns them - a URL cannot prove ownership on its own.
    if not body.owner_confirmed_source:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "owner_confirmed_source must be true: the rebuild carries the source "
                "page's own copy and imagery, so the caller must assert the client "
                "owns the source before it is captured."
            ),
        )

    # SSRF guard: getaddrinfo blocks, so validate off the event loop. The worker
    # re-checks the same guard at run time (defence in depth).
    try:
        await asyncio.to_thread(validate_public_host, body.url)
    except PrivateAddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"URL is not a public address: {exc}",
        ) from exc

    # Resolve + snapshot the client name (also validates tenant scope via RLS).
    client = await asyncio.to_thread(clients.get_client, str(body.client_id))
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Client not found")

    # The starter reads the ledger and talks to the broker - both blocking.
    job_id = await asyncio.to_thread(
        start,
        repo,
        client_id=str(body.client_id),
        url=body.url,
        title=body.title,
        slug=body.slug,
        client_name=str(client.get("name", "")),
    )
    await record_activity(
        actor,
        kind="content",
        action="queued a design replication",
        target=body.url,
        meta=f"job {job_id}",
        entity_type="client",
        entity_id=str(body.client_id),
    )
    return ReplicaQueuedResponse(job_id=job_id, status="queued")


@router.get("/replica/{job_id}", response_model=ReplicaJobResponse)
async def get_replica_job(
    job_id: str, repo: JobRunsRepoDep, _user: PublishContent
) -> ReplicaJobResponse:
    """The job's status and result, read straight off the job ledger.

    The handle is the Celery message id; the ledger row is created at the worker's
    first CLAIM, so a row that does not exist yet is honestly ``queued`` (accepted,
    not yet claimed) rather than a 404. A handle that could never have come from
    POST (not a UUID) IS a 404. The lookup is scoped to this module's job_name, so
    another module's run id can never be dressed in the replica response shape.
    """
    try:
        UUID(job_id)
    except ValueError as exc:
        raise _NOT_FOUND from exc
    row = await asyncio.to_thread(repo.get_run_by_celery_task_id, job_id, job_name=_JOB_NAME)
    if row is None:
        return ReplicaJobResponse(job_id=job_id, status="queued")
    return ReplicaJobResponse.from_run(job_id, row)
