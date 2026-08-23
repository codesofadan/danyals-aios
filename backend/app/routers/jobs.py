"""The job-contract operator surface: what ran, what failed, and what it cost.

The master plan's target state asks the job layer for exactly that, and before the
contract there was nowhere to ask it. `scheduled_job_runs` covered the three beat
sweeps; the other 39 tasks left no durable record at all, so "did last night's work
happen" was answered by reading worker logs.

AUTH mirrors the 0080 RLS boundary:

* Reads require any provisioned staff (``view_reports``) - which a portal client does
  NOT hold, so clients are 403'd out of the namespace, mirroring backups/reports.
  Postgres backs that up: neither table has a select policy for a client.
* Cancelling a run, replaying a dead letter and resolving one are LEAD actions
  (owner/admin/manager). Replay in particular deliberately re-runs work that has
  already spent money once.

The mutations write on the PRIVILEGED store after the router's permission check -
the same pattern as the audit worker's status writes - because neither table carries
an authenticated write policy by design.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.auth import CurrentUser, require_perm, require_role
from app.core.pagination import PageDep
from app.db.job_runs_repo import JobRunsRepoDep, job_runs_store
from app.jobs.celery_task import enqueue
from app.jobs.status import JobStatus
from app.schemas.jobs import (
    CancelRequest,
    DeadLetterResponse,
    InFlightResponse,
    JobRunResponse,
    JobSummaryResponse,
    ReplayResponse,
    ResolveRequest,
)
from app.services.activity import record_activity

router = APIRouter(tags=["jobs"])

# All six staff roles hold view_reports; a portal client does NOT.
ViewReports = Annotated[CurrentUser, Depends(require_perm("view_reports"))]
# Stopping and replaying work is a lead decision.
LeadOnly = Annotated[CurrentUser, Depends(require_role("owner", "admin", "manager"))]

_RUN_NOT_FOUND = HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job run not found")
_DL_NOT_FOUND = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Dead letter not found"
)


# --------------------------------------------------------------------------- #
# Reads
# --------------------------------------------------------------------------- #
@router.get("/jobs/summary", response_model=JobSummaryResponse)
async def job_summary(
    repo: JobRunsRepoDep,
    _user: ViewReports,
    window_hours: Annotated[int, Query(ge=1, le=720, alias="windowHours")] = 24,
) -> JobSummaryResponse:
    """Runs and spend per terminal state over a window, plus the open DLQ depth.

    ``degraded`` is its own line. It is never added to a success count, which is the
    whole reason the vocabulary distinguishes the two - a board that folds partial
    outcomes into "completed" is the board this contract was built to replace.
    """
    rows = await asyncio.to_thread(repo.counts_by_status, since_hours=window_hours)
    open_dlq = await asyncio.to_thread(repo.count_open_dead_letters)
    return JobSummaryResponse.from_rows(rows, window_hours=window_hours, open_dlq=open_dlq)


@router.get("/jobs/runs", response_model=list[JobRunResponse])
async def list_job_runs(
    repo: JobRunsRepoDep,
    page: PageDep,
    _user: ViewReports,
    run_status: Annotated[JobStatus | None, Query(alias="status")] = None,
    job_name: Annotated[str | None, Query(alias="jobName")] = None,
    client_id: Annotated[UUID | None, Query(alias="clientId")] = None,
    correlation_id: Annotated[UUID | None, Query(alias="correlationId")] = None,
    needs_attention: Annotated[bool, Query(alias="needsAttention")] = False,
) -> list[JobRunResponse]:
    """The runs board, newest first.

    ``needsAttention=true`` is the view that matters day to day: every terminal run
    that was not a clean success - degraded, blocked, failed - in one list.
    ``correlationId`` reassembles a whole fan-out: one nightly sweep and the eighty
    per-client jobs it enqueued share one id.
    """
    rows = await asyncio.to_thread(
        repo.list_runs,
        status=run_status.value if run_status else None,
        job_name=job_name,
        client_id=str(client_id) if client_id else None,
        correlation_id=str(correlation_id) if correlation_id else None,
        needs_attention=needs_attention,
        limit=page.limit,
        offset=page.offset,
    )
    return [JobRunResponse.from_row(r) for r in rows]


@router.get("/jobs/runs/{run_id}", response_model=JobRunResponse)
async def get_job_run(run_id: UUID, repo: JobRunsRepoDep, _user: ViewReports) -> JobRunResponse:
    row = await asyncio.to_thread(repo.get_run, str(run_id))
    if row is None:
        raise _RUN_NOT_FOUND
    return JobRunResponse.from_row(row)


@router.get("/jobs/in-flight", response_model=list[InFlightResponse])
async def in_flight(repo: JobRunsRepoDep, _user: ViewReports) -> list[InFlightResponse]:
    """Running jobs per (client, queue) - exactly what the concurrency cap acts on.

    This is the answer to "why is that client's work not starting": if a client sits
    at its cap on a queue, its next job is deferred rather than started, and after
    ``max_queue_seconds`` it is honestly blocked rather than deferred forever.
    """
    rows = await asyncio.to_thread(repo.in_flight_by_client)
    return [InFlightResponse.from_row(r) for r in rows]


@router.get("/jobs/dead-letters", response_model=list[DeadLetterResponse])
async def list_dead_letters(
    repo: JobRunsRepoDep,
    page: PageDep,
    _user: ViewReports,
    open_only: Annotated[bool, Query(alias="openOnly")] = True,
) -> list[DeadLetterResponse]:
    """Work the platform accepted and did not deliver.

    Open items come OLDEST first - the opposite of every other feed here, and
    deliberately: the longest-unresolved lost job is the most urgent one, not the
    least.
    """
    rows = await asyncio.to_thread(
        repo.list_dead_letters, open_only=open_only, limit=page.limit, offset=page.offset
    )
    return [DeadLetterResponse.from_row(r) for r in rows]


# --------------------------------------------------------------------------- #
# Lead actions
# --------------------------------------------------------------------------- #
@router.post("/jobs/runs/{run_id}/cancel", response_model=JobRunResponse)
async def cancel_job_run(
    run_id: UUID, body: CancelRequest, repo: JobRunsRepoDep, user: LeadOnly
) -> JobRunResponse:
    """Ask a run to stop.

    COOPERATIVE, not a kill: a Celery task cannot be safely terminated part-way
    through writing to a client's website. This sets a flag - a queued run will never
    start, and a running one stops at its next ``ctx.checkpoint()``. A job that does
    not checkpoint cannot be stopped, which is why anything that loops must.

    A run that has already finished returns 409: overwriting a real outcome with
    "cancelled" would be a fiction, and the ledger's job is to not contain those.
    """
    existing = await asyncio.to_thread(repo.get_run, str(run_id))
    if existing is None:
        raise _RUN_NOT_FOUND

    row = await asyncio.to_thread(job_runs_store().request_cancel, str(run_id), requested_by=user.id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"This run already finished ({existing['status']}) and cannot be cancelled",
        )

    await record_activity(
        user,
        kind="access",
        action="Cancelled a job run",
        target=f"{row['job_name']} ({run_id})",
        meta=body.reason or None,
        entity_type="client" if row.get("client_id") else None,
        entity_id=str(row["client_id"]) if row.get("client_id") else None,
    )
    return JobRunResponse.from_row(row)


@router.post("/jobs/dead-letters/{dead_letter_id}/replay", response_model=ReplayResponse)
async def replay_dead_letter(
    dead_letter_id: UUID, repo: JobRunsRepoDep, user: LeadOnly
) -> ReplayResponse:
    """Re-run a unit of work that was lost, with its original arguments.

    Two things make this safe to expose:

    1. The replay gets its OWN idempotency key (``replay:<dead_letter_id>``), not the
       original's. Reusing the original key would find the old terminal run and skip
       the work silently - the replay would appear to succeed and do nothing.
    2. ``mark_replayed`` only matches a dead letter that is still open, so a double
       click cannot enqueue the work twice. That matters more here than anywhere else
       in the product: replaying deliberately re-runs something that already spent
       money once.

    The run row is created HERE rather than by the worker, so the operator gets a run
    id immediately and the dead letter can point at it. The worker's own claim finds
    this queued row and starts it - the same path a retry takes.
    """
    dead_letter = await asyncio.to_thread(repo.get_dead_letter, str(dead_letter_id))
    if dead_letter is None:
        raise _DL_NOT_FOUND
    if dead_letter.get("resolved_at") or dead_letter.get("replayed_at"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This dead letter has already been replayed or resolved",
        )

    store = job_runs_store()
    replay_key = f"replay:{dead_letter_id}"
    payload: dict[str, Any] = dict(dead_letter.get("payload") or {})
    args = list(payload.get("args") or [])
    kwargs = dict(payload.get("kwargs") or {})

    run_row, created = await asyncio.to_thread(
        store.claim,
        job_name=str(dead_letter["job_name"]),
        task=str(dead_letter.get("task") or ""),
        queue=str(dead_letter["queue"]),
        idempotency_key=replay_key,
        correlation_id=str(dead_letter.get("correlation_id") or dead_letter_id),
        parent_run_id=str(dead_letter["run_id"]) if dead_letter.get("run_id") else None,
        celery_task_id="",
        client_id=str(dead_letter["client_id"]) if dead_letter.get("client_id") else None,
        client_name=str(dead_letter.get("client_name") or ""),
        scope_type=str(dead_letter.get("scope_type") or ""),
        scope_id=str(dead_letter["scope_id"]) if dead_letter.get("scope_id") else None,
        # The running code's spec is the truth about the retry budget; `start()`
        # re-stamps this the moment a worker picks the run up.
        max_attempts=1,
    )
    if not created:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A replay of this dead letter already exists",
        )

    claimed = await asyncio.to_thread(
        store.mark_replayed,
        str(dead_letter_id),
        replayed_run_id=str(run_row["id"]),
        replayed_by=user.id,
    )
    if claimed is None:
        # Someone replayed it between the read and the write. Do not enqueue.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This dead letter was replayed by someone else",
        )

    message_id = await asyncio.to_thread(
        enqueue,
        str(dead_letter["task"]),
        *args,
        correlation_id=str(run_row["correlation_id"]),
        idempotency_key=replay_key,
        **kwargs,
    )

    await record_activity(
        user,
        kind="access",
        action="Replayed a dead-lettered job",
        target=f"{dead_letter['job_name']} ({dead_letter_id})",
        meta=f"run {run_row['id']}",
        entity_type="client" if dead_letter.get("client_id") else None,
        entity_id=str(dead_letter["client_id"]) if dead_letter.get("client_id") else None,
    )
    return ReplayResponse(
        dead_letter_id=str(dead_letter_id),
        run_id=str(run_row["id"]),
        message_id=message_id,
        idempotency_key=replay_key,
    )


@router.post("/jobs/dead-letters/{dead_letter_id}/resolve", response_model=DeadLetterResponse)
async def resolve_dead_letter(
    dead_letter_id: UUID, body: ResolveRequest, repo: JobRunsRepoDep, user: LeadOnly
) -> DeadLetterResponse:
    """Close a dead letter with a written decision.

    The resolution text is required by the schema AND by a CHECK constraint. A queue
    closed with no reasons written is a graveyard - the next person cannot tell "we
    fixed the underlying bug" from "we gave up on this one".
    """
    existing = await asyncio.to_thread(repo.get_dead_letter, str(dead_letter_id))
    if existing is None:
        raise _DL_NOT_FOUND

    row = await asyncio.to_thread(
        job_runs_store().resolve_dead_letter,
        str(dead_letter_id),
        resolution=body.resolution,
        resolved_by=user.id,
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="This dead letter is already resolved"
        )

    await record_activity(
        user,
        kind="access",
        action="Resolved a dead-lettered job",
        target=f"{row['job_name']} ({dead_letter_id})",
        meta=body.resolution,
    )
    return DeadLetterResponse.from_row(row)
