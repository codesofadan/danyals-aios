"""The Celery binding for the job contract: ``@aios_job`` and ``enqueue``.

This is the ONLY module in ``app/jobs`` that knows Celery exists. Everything the
contract actually decides - idempotency, retry, cancellation, capping, dead-lettering
- lives in the Celery-free ``app.jobs.runner``. Keeping the split means the hard
logic is unit-testable without a broker, and it means importing ``app.jobs`` on the
FastAPI edge does not drag Celery in (the worker-template rule already followed in
``workers/tasks/*.py``: the Celery import comes last, after the pure core).

WRITING A JOB::

    from app.jobs import JobQueue, JobOutcome, JobTarget
    from app.jobs.celery_task import aios_job

    def _target(client_id: str, day: str) -> JobTarget:
        return JobTarget(
            idempotency_key=f"rank.sweep:{client_id}:{day}",
            client_id=client_id,
            scope_id=client_id,
        )

    @aios_job(
        name="check_keyword_rank",
        job_name="rank.check",
        queue=JobQueue.STANDARD,
        max_attempts=3,
        client_concurrency=4,
        target=_target,
    )
    def check_keyword_rank(ctx, client_id: str, day: str) -> JobOutcome:
        ctx.checkpoint()
        ...
        return JobOutcome.completed("checked 40 keywords", cost_usd=0.024)

Note what the job body no longer contains: no try/except that swallows the error, no
manual ledger write, no "never re-raise" boilerplate, no status string. It states an
outcome, and the runner is responsible for the outcome being recorded exactly once.

THE IDEMPOTENCY KEY IS THE ONE THING TO GET RIGHT. It must be a deterministic
function of the WORK, not of the call: two enqueues of the same work must produce the
same key, and two genuinely different units must not collide. Including a date (or a
period) is usually what makes a recurring job safe to re-fire.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from typing import Any, Final
from uuid import uuid4

from celery.exceptions import SoftTimeLimitExceeded

from app.db.job_runs_repo import job_runs_store
from app.jobs.contract import JobContext, JobOutcome
from app.jobs.runner import JobSpec, JobTarget, run_job
from app.jobs.status import SOFT_TIME_LIMITS, TIME_LIMITS, JobQueue
from app.logging_setup import get_logger

logger = get_logger("app.jobs.celery_task")

#: Reserved kwargs the runner strips before calling the job body. Namespaced so a
#: job's own parameters can never collide with them.
_CORRELATION_KW: Final[str] = "_aios_correlation_id"
_PARENT_KW: Final[str] = "_aios_parent_run_id"
_KEY_KW: Final[str] = "_aios_idempotency_key"

#: task name -> queue. Populated at decoration time and read by the router below, so
#: a job's queue is declared once, next to the job, rather than in a routing table
#: that drifts away from it.
TASK_QUEUES: Final[dict[str, str]] = {}

#: task name -> (spec, target). The same declarations, kept whole, so ``enqueue`` can
#: write the run row at SEND time rather than leaving "queued" to be inferred from the
#: absence of one. Populated at decoration time beside TASK_QUEUES.
TASK_SPECS: Final[dict[str, tuple[JobSpec, Callable[..., JobTarget] | None]]] = {}


def route_task(
    name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    options: dict[str, Any],
    task: Any = None,
    **_: Any,
) -> dict[str, str] | None:
    """Celery router: send each task to its declared duration class.

    Wired as ``task_routes = (route_task,)``. Returning ``None`` for an unregistered
    task lets it fall through to ``task_default_queue``, so the 39 tasks that predate
    this contract keep working unchanged while they are migrated one at a time.
    """
    queue = TASK_QUEUES.get(name)
    return {"queue": queue} if queue else None


def aios_job(
    *,
    name: str,
    job_name: str,
    queue: JobQueue = JobQueue.STANDARD,
    max_attempts: int = 1,
    retry_backoff: float = 30.0,
    retry_backoff_max: float = 600.0,
    client_concurrency: int = 0,
    max_queue_seconds: float = 3600.0,
    scope_type: str = "",
    target: Callable[..., JobTarget] | None = None,
    retry_on: tuple[type[BaseException], ...] = (),
) -> Callable[[Callable[..., JobOutcome]], Any]:
    """Register a Celery task that runs under the job contract.

    ``name`` is the Celery task name (pinned explicitly, as every task in this
    codebase is, so the module can be moved without breaking routing). ``job_name`` is
    the LOGICAL job an operator groups by.

    ``target`` derives the idempotency key and the owning client from the call's own
    arguments. Omitting it means the job opts out of idempotency and out of the
    per-client cap - correct for a platform-wide sweep, wrong for anything that
    spends money on a client's behalf.

    Time limits come from the queue, not from the job, so the
    ``visibility_timeout >= longest time_limit`` invariant is a property of the
    system rather than something each task has to remember.
    """
    spec = JobSpec(
        job_name=job_name,
        task=name,
        queue=queue,
        max_attempts=max_attempts,
        retry_backoff=retry_backoff,
        retry_backoff_max=retry_backoff_max,
        client_concurrency=client_concurrency,
        max_queue_seconds=max_queue_seconds,
        scope_type=scope_type,
        # A soft time limit is Celery telling the job it is out of time. That is
        # almost always a slow provider rather than a bug, so it is transient by
        # default - but only up to max_attempts, like any other transient fault.
        retry_on=(*retry_on, SoftTimeLimitExceeded),
    )

    def decorator(fn: Callable[..., JobOutcome]) -> Any:
        # Imported here, not at module scope: the worker template keeps the Celery
        # import last so the API edge can import app.jobs without a broker in the tree.
        from workers.celery_app import celery_app

        TASK_QUEUES[name] = queue.value
        TASK_SPECS[name] = (spec, target)

        @celery_app.task(  # type: ignore[untyped-decorator]  # celery's decorator is untyped
            name=name,
            bind=True,
            queue=queue.value,
            time_limit=TIME_LIMITS[queue],
            soft_time_limit=SOFT_TIME_LIMITS[queue],
            # UNBOUNDED at the CELERY layer, on purpose - the bounds live in the DB.
            #
            # This has to be set HERE, not only at the `self.retry(max_retries=None)`
            # call below, and the difference is not cosmetic. Celery resolves
            #     max_retries = self.max_retries if max_retries is None else max_retries
            # (celery/app/task.py), so passing None to `retry()` does NOT mean
            # "unlimited" - it means "do not override the task's own setting", which
            # without this line is Celery's default of 3.
            #
            # That silently capped the CONCURRENCY WAIT. A job deferred because its
            # client is at the queue's in-flight limit comes back through the same
            # `retry()` path as a failure, so waiting for a slot burned the retry
            # budget meant for errors: submit five replications at once and the last
            # two exhausted three deferrals in ~90s and died with
            # MaxRetriesExceededError, while `max_queue_seconds` - the bound that is
            # supposed to decide this - was never reached. The work was simply lost.
            #
            # With None, redelivery is unlimited and the REAL bounds apply, exactly as
            # the retry site below already claims: `max_attempts` for errors and
            # `max_queue_seconds` for concurrency waits, both counted in Postgres by
            # the runner, which ends a hopeless wait as BLOCKED with a reason.
            max_retries=None,
        )
        @functools.wraps(fn)
        def _task(self: Any, *args: Any, **kwargs: Any) -> dict[str, Any]:
            correlation_id = kwargs.pop(_CORRELATION_KW, None)
            parent_run_id = kwargs.pop(_PARENT_KW, None)
            override_key = kwargs.pop(_KEY_KW, None)

            job_target = target(*args, **kwargs) if target is not None else JobTarget()
            if override_key:
                job_target = replace(job_target, idempotency_key=str(override_key))

            try:
                disposition = run_job(
                    fn,
                    spec=spec,
                    store=job_runs_store(),
                    target=job_target,
                    args=args,
                    kwargs=kwargs,
                    celery_task_id=str(getattr(self.request, "id", "") or ""),
                    correlation_id=correlation_id,
                    parent_run_id=parent_run_id,
                )
            except Exception as exc:
                # Only the CLAIM/START phase can reach here - every path after the job
                # body has run swallows its own store errors (see runner._finish),
                # precisely so a ledger outage can never cause a second execution.
                # Nothing has run yet, so redelivering is safe and is the right answer
                # to a transient database problem.
                logger.error(
                    "job.ledger_unavailable",
                    job_name=job_name,
                    task=name,
                    error=type(exc).__name__,
                )
                raise self.retry(countdown=60, max_retries=10, exc=exc) from exc

            if disposition.action == "retry":
                # Celery's retry is used purely as a REDELIVERY mechanism here.
                # Attempts are counted in the database, so max_retries is deliberately
                # unbounded: the real bounds are `max_attempts` (errors) and
                # `max_queue_seconds` (concurrency waits), both enforced by the runner.
                raise self.retry(countdown=disposition.countdown, max_retries=None)

            return disposition.as_dict()

        return _task

    return decorator


#: Whether this process has imported the task modules yet. `TASK_SPECS` is populated
#: at DECORATION time, so a process that has not imported a task's module does not
#: know that task is under the contract.
_specs_loaded = False


def _ensure_specs(task_name: str) -> None:
    """Make sure this process knows whether ``task_name`` is under the job contract.

    THE API PROCESS IMPORTS ROUTERS, NOT WORKER TASK MODULES - by design, so the edge
    does not drag Celery in at import time. Measured: an API process holds 2 of the
    ~15 contract specs. So `enqueue` could only pre-create a run row when the CALLER
    happened to have imported the task module first, which some routers do (via a
    lazy import in their enqueuer) and others do not. That made "a queued job is a
    row" true by coincidence rather than by construction - and silently false for any
    new caller.

    Celery already knows how to import every task module (the `include=[...]` list),
    so this asks it to, once, and only when a task is not already known. A legacy task
    is still absent afterwards, which is the correct answer for it.
    """
    global _specs_loaded
    if task_name in TASK_SPECS or _specs_loaded:
        return
    _specs_loaded = True
    try:
        from workers.celery_app import celery_app

        celery_app.loader.import_default_modules()
    except Exception as exc:
        # Degrades to the previous behaviour: no row here, the worker claims on
        # arrival. Never fails the enqueue itself.
        logger.warning("job.task_modules_unavailable", error=f"{type(exc).__name__}: {exc}")


def _precreate_run(
    task_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    *,
    correlation_id: str | None,
    parent_run_id: str | None,
    idempotency_key: str | None,
    celery_task_id: str,
    scheduled_at: datetime | None,
) -> str | None:
    """Write the ``queued`` run row at SEND time. Returns the key actually used.

    ``None`` means this task is not under the contract (a legacy ``@celery_app.task``),
    and the send proceeds exactly as before.

    A key is SYNTHESISED when the job opts out of idempotency, because a NULL key does
    not conflict: the worker's own claim would insert a SECOND row rather than adopt
    this one. The synthesised key is unique per send, so "no key" still means "always
    runs" - it only gives the worker something to rendezvous on. It is returned so the
    caller can put it in the payload, where the task wrapper applies it as an override.
    """
    _ensure_specs(task_name)
    entry = TASK_SPECS.get(task_name)
    if entry is None:
        return None
    spec, target = entry

    job_target = target(*args, **kwargs) if target is not None else JobTarget()
    key = idempotency_key or job_target.idempotency_key or f"enq:{uuid4()}"

    job_runs_store().claim(
        job_name=spec.job_name,
        task=task_name,
        queue=spec.queue.value,
        idempotency_key=key,
        correlation_id=correlation_id or str(uuid4()),
        parent_run_id=parent_run_id,
        celery_task_id=celery_task_id,
        client_id=job_target.client_id,
        client_name=job_target.client_name,
        scope_type=spec.scope_type,
        scope_id=job_target.scope_id,
        max_attempts=spec.max_attempts,
        scheduled_at=scheduled_at,
    )
    return key


def enqueue(
    task_name: str,
    *args: Any,
    correlation_id: str | None = None,
    parent_run_id: str | None = None,
    idempotency_key: str | None = None,
    countdown: float | None = None,
    scheduled_at: datetime | None = None,
    **kwargs: Any,
) -> str:
    """Send a job, propagating the correlation id so a fan-out stays reassemblable.

    Returns the Celery message id. The DURABLE identifier is the ``job_runs.id`` - a
    Celery id lives only as long as the result backend, which is an hour. Anything
    that needs to refer to a job later must use the run id.

    THE ROW IS WRITTEN HERE, NOT AT THE WORKER. It used to be created by the runner's
    CLAIM, which meant a job had no ledger row at all until a worker picked it up -
    so "queued" was not a stored fact but the absence of one, inferred by each caller.
    ``GET /replica/{id}`` did exactly that, and reported a fabricated
    ``{status: "queued", everything: null}`` for a job that no worker would ever
    consume. A queue nothing is reading and a queue that is merely busy looked
    identical, from the API and from Operations alike.

    Now the row exists the moment the work is accepted, and the worker's claim ADOPTS
    it (``runner`` falls through on an existing queued row; ``start()`` re-stamps the
    task id and attempt budget, which is what that path was already written for). So
    a queued job is visible in ``GET /jobs/runs`` with no worker running at all, and
    the UI can show what is really true: accepted, not yet started.

    A ledger failure DEGRADES to the old behaviour - the message is still sent and the
    worker still claims on arrival. Enqueueing is on the API's request path, and
    refusing to accept work because the ledger blinked would be a worse outcome than
    briefly not being able to show it.
    """
    from workers.celery_app import celery_app

    # Generated here so the row can carry it from birth. Celery accepts a
    # caller-supplied id and the worker sees the same value as `self.request.id`,
    # which is what lets `get_run_by_celery_task_id` find a not-yet-started run.
    task_id = str(uuid4())

    try:
        applied_key = _precreate_run(
            task_name,
            args,
            kwargs,
            correlation_id=correlation_id,
            parent_run_id=parent_run_id,
            idempotency_key=idempotency_key,
            celery_task_id=task_id,
            scheduled_at=scheduled_at,
        )
    except Exception as exc:
        logger.error(
            "job.enqueue_ledger_unavailable",
            task=task_name,
            error=f"{type(exc).__name__}: {exc}",
        )
        applied_key = idempotency_key

    payload = dict(kwargs)
    if correlation_id is not None:
        payload[_CORRELATION_KW] = correlation_id
    if parent_run_id is not None:
        payload[_PARENT_KW] = parent_run_id
    if applied_key is not None:
        payload[_KEY_KW] = applied_key

    result = celery_app.send_task(
        task_name,
        args=list(args),
        kwargs=payload,
        countdown=countdown,
        queue=TASK_QUEUES.get(task_name),
        task_id=task_id,
    )
    return str(result.id)


def enqueue_child(
    ctx: JobContext,
    task_name: str,
    *args: Any,
    key_suffix: str | None = None,
    countdown: float | None = None,
    **kwargs: Any,
) -> str:
    """Enqueue from inside a running job, inheriting its correlation id and parentage.

    Use this - not :func:`enqueue` - for every fan-out, so ``job_runs`` can answer
    "what did that nightly sweep actually do" with one indexed query instead of a
    timestamp-range guess.

    ``key_suffix`` derives the child's idempotency key from the parent's, which makes
    a re-run of the parent produce exactly the same children rather than a second
    fan-out beside the first.
    """
    return enqueue(
        task_name,
        *args,
        correlation_id=ctx.correlation_id,
        parent_run_id=ctx.run_id,
        idempotency_key=ctx.child_key(key_suffix) if key_suffix else None,
        countdown=countdown,
        **kwargs,
    )


__all__ = ["TASK_QUEUES", "TASK_SPECS", "aios_job", "enqueue", "enqueue_child", "route_task"]
