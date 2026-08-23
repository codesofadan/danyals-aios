"""The runner: everything that happens around a job, with no Celery in sight.

``run_job`` is a pure function over the :class:`JobRunStore` seam. That is deliberate
and load-bearing - idempotency, the retry ladder, the concurrency deferral, the
cancellation path and the dead letter are the parts of this system most likely to be
subtly wrong, and they are also the parts hardest to exercise through a broker. Here
they are ordinary function calls against an in-memory fake, so every branch is a unit
test that runs in milliseconds with no Redis and no Postgres.

``run_job`` NEVER raises and never performs the retry itself. It returns a
:class:`Disposition` describing what should happen next, and the Celery layer in
``app.jobs.celery_task`` is the only thing that knows how to redeliver a message.

THE ORDER OF OPERATIONS, and why each step is where it is:

1. CLAIM (idempotency) - before anything else, because the whole point is to decide
   whether this work has already been done. Resolved by a unique index, not by a
   read-then-write, so two workers racing on the same key cannot both win.
2. START (cap + cancellation) - after the claim, because a run must exist before it
   can be capped or cancelled, and both answers depend on the row.
3. EXECUTE - with a context that can heartbeat and can be cancelled.
4. FINISH - exactly one terminal write, whatever happened, including the paths where
   the job itself raised.
5. DEAD-LETTER - only on `failed`, and always with the payload needed to replay.
"""

from __future__ import annotations

import random
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Final, Literal

from app.jobs.contract import (
    JobBlocked,
    JobCancelled,
    JobContext,
    JobOutcome,
    JobRunStore,
    PermanentJobError,
    RetryableJobError,
    StartOutcome,
)
from app.jobs.status import IN_FLIGHT, JobQueue, JobStatus, is_terminal
from app.logging_setup import get_logger

logger = get_logger("app.jobs.runner")

#: Reason codes the RUNNER itself emits. A module's own codes are its own; these are
#: the two blocks that come from the contract rather than from any job's logic, and
#: they are named constants so an operator surface can filter on them without a magic
#: string and without guessing how the runner phrased it.
BLOCKED_CONCURRENCY_CAP: Final[str] = "concurrency_cap_timeout"
FAILED_HEARTBEAT_LOST: Final[str] = "heartbeat_lost"


@dataclass(frozen=True, slots=True)
class JobSpec:
    """The operational envelope a job runs inside. Declared once, at decoration."""

    job_name: str
    task: str
    queue: JobQueue = JobQueue.STANDARD

    #: How many times the job body may RUN. 1 = no retries. Counted in the database,
    #: not in Celery's ``request.retries``, so a message redelivered by a broker
    #: hiccup or a concurrency deferral does not silently consume the budget.
    max_attempts: int = 1
    retry_backoff: float = 30.0
    retry_backoff_max: float = 600.0

    #: Maximum simultaneous RUNNING jobs per client on this queue. 0 = uncapped.
    #: This is what stops one client's 300-page bulk run from owning every worker.
    client_concurrency: int = 0

    #: How long a run may sit waiting for a free slot before it is honestly blocked
    #: rather than deferred forever. An hour of silent waiting is indistinguishable
    #: from a lost job.
    max_queue_seconds: float = 3600.0

    scope_type: str = ""

    #: Extra exception types treated as transient. ``RetryableJobError`` always is;
    #: this is for provider exceptions the job body would rather not translate.
    retry_on: tuple[type[BaseException], ...] = ()


@dataclass(frozen=True, slots=True)
class JobTarget:
    """Who and what a particular invocation is for.

    Derived from the call's arguments by the job's own ``target`` callable, so the
    key is a deterministic property of the WORK rather than something each caller has
    to remember to pass. A beat entry and a hand-triggered rerun of the same job for
    the same client on the same day therefore produce the same key - and the second
    one does nothing.
    """

    idempotency_key: str | None = None
    client_id: str | None = None
    client_name: str = ""
    scope_id: str | None = None


@dataclass(frozen=True, slots=True)
class Disposition:
    """What the caller (the Celery layer) should do next."""

    action: Literal["done", "retry", "skipped"]
    status: str
    detail: str = ""
    run_id: str | None = None
    correlation_id: str | None = None
    countdown: float = 0.0
    result: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        """The small JSON-serialisable value a Celery task returns.

        Deliberately small: the result backend is not a place to put a report. The
        durable record is the ``job_runs`` row, and this is just enough for a caller
        chaining on the AsyncResult to know what happened.
        """
        return {
            "action": self.action,
            "status": self.status,
            "detail": self.detail,
            "run_id": self.run_id,
            "correlation_id": self.correlation_id,
            "result": self.result,
        }


def _default_jitter(backoff: float) -> float:
    """Up to 25% extra, so N jobs failing on the same provider outage do not all come
    back at the same instant and knock it over again."""
    return random.uniform(0.0, backoff * 0.25)


def compute_backoff(
    attempt: int,
    *,
    base: float,
    maximum: float,
    jitter: Callable[[float], float] = _default_jitter,
) -> float:
    """Exponential backoff with jitter, capped. ``attempt`` is 1-based."""
    raw = base * float(2 ** max(attempt - 1, 0))
    capped = min(raw, maximum)
    return capped + jitter(capped)


@dataclass(slots=True)
class _RunnerDeps:
    """Seams the runner needs that are awkward to fake by monkeypatching."""

    now: Callable[[], datetime] = field(default=lambda: datetime.now(UTC))
    jitter: Callable[[float], float] = field(default=_default_jitter)


def run_job(
    fn: Callable[..., JobOutcome],
    *,
    spec: JobSpec,
    store: JobRunStore,
    target: JobTarget,
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    celery_task_id: str = "",
    correlation_id: str | None = None,
    parent_run_id: str | None = None,
    deps: _RunnerDeps | None = None,
) -> Disposition:
    """Run one job under the contract. Never raises.

    Returns a :class:`Disposition`; ``action="retry"`` means the caller must
    redeliver the message after ``countdown`` seconds.
    """
    kwargs = dict(kwargs or {})
    deps = deps or _RunnerDeps()
    correlation = correlation_id or _new_uuid()

    # --- 1 · CLAIM ---------------------------------------------------------
    row, created = store.claim(
        job_name=spec.job_name,
        task=spec.task,
        queue=spec.queue.value,
        idempotency_key=target.idempotency_key,
        correlation_id=correlation,
        parent_run_id=parent_run_id,
        celery_task_id=celery_task_id,
        client_id=target.client_id,
        client_name=target.client_name,
        scope_type=spec.scope_type,
        scope_id=target.scope_id,
        max_attempts=spec.max_attempts,
    )
    run_id = str(row["id"])
    correlation = str(row["correlation_id"])
    log = logger.bind(
        run_id=run_id,
        correlation_id=correlation,
        job_name=spec.job_name,
        client_id=target.client_id,
    )

    if not created:
        existing_status = str(row["status"])
        if is_terminal(existing_status):
            # The whole point of an idempotency key. A redelivered message, a
            # double-click, a beat tick that overlapped its predecessor: the work is
            # already done and must not be done again.
            log.info("job.skipped_already_terminal", status=existing_status)
            return Disposition(
                action="skipped",
                status=existing_status,
                detail="already completed under this idempotency key",
                run_id=run_id,
                correlation_id=correlation,
            )
        if existing_status == JobStatus.RUNNING.value and row["celery_task_id"] != celery_task_id:
            log.info("job.skipped_in_flight", status=existing_status)
            return Disposition(
                action="skipped",
                status=existing_status,
                detail="another worker is already running this unit of work",
                run_id=run_id,
                correlation_id=correlation,
            )
        # Otherwise it is queued (a deferral or our own retry) - fall through.

    # --- 2 · START (concurrency cap + cancellation) -------------------------
    start = store.start(
        run_id,
        celery_task_id=celery_task_id,
        client_concurrency=spec.client_concurrency,
        max_attempts=spec.max_attempts,
    )

    if start.outcome is StartOutcome.CANCELLED:
        store.finish(
            run_id,
            status=JobStatus.CANCELLED.value,
            detail="cancelled before it started",
            reason="",
            reason_code="",
            error_type="",
            error_message="",
            cost_usd=Decimal("0"),
            result=None,
        )
        log.info("job.cancelled_before_start")
        return Disposition(
            action="done",
            status=JobStatus.CANCELLED.value,
            detail="cancelled before it started",
            run_id=run_id,
            correlation_id=correlation,
        )

    if start.outcome is StartOutcome.NOT_CLAIMABLE:
        status = str(start.row["status"]) if start.row else JobStatus.QUEUED.value
        log.info("job.not_claimable", status=status)
        return Disposition(
            action="skipped",
            status=status,
            detail="the run was no longer claimable",
            run_id=run_id,
            correlation_id=correlation,
        )

    if start.outcome is StartOutcome.CAPPED:
        waited = _seconds_waiting(row, now=deps.now())
        if waited >= spec.max_queue_seconds:
            reason = (
                f"waited {int(waited)}s for a free slot; the client is at its "
                f"{spec.client_concurrency}-job limit on the {spec.queue.value} queue"
            )
            store.finish(
                run_id,
                status=JobStatus.BLOCKED.value,
                detail=reason,
                reason=reason,
                reason_code=BLOCKED_CONCURRENCY_CAP,
                error_type="",
                error_message="",
                cost_usd=Decimal("0"),
                result=None,
            )
            log.warning("job.blocked_by_cap", waited_seconds=int(waited), in_flight=start.in_flight)
            return Disposition(
                action="done",
                status=JobStatus.BLOCKED.value,
                detail=reason,
                run_id=run_id,
                correlation_id=correlation,
            )
        countdown = compute_backoff(1, base=spec.retry_backoff, maximum=60.0, jitter=deps.jitter)
        detail = f"waiting for a slot ({start.in_flight} of this client's jobs in flight)"
        store.defer(run_id, scheduled_for_seconds=countdown, detail=detail)
        log.info("job.deferred_by_cap", in_flight=start.in_flight, countdown=round(countdown, 1))
        return Disposition(
            action="retry",
            status=JobStatus.QUEUED.value,
            detail=detail,
            run_id=run_id,
            correlation_id=correlation,
            countdown=countdown,
        )

    started_row = start.row or row
    attempt = int(started_row["attempt"])

    ctx = JobContext(
        run_id=run_id,
        correlation_id=correlation,
        job_name=spec.job_name,
        task=spec.task,
        queue=spec.queue,
        attempt=attempt,
        max_attempts=spec.max_attempts,
        client_id=target.client_id,
        client_name=target.client_name,
        scope_type=spec.scope_type,
        scope_id=target.scope_id,
        idempotency_key=target.idempotency_key,
        _store=store,
    )

    # --- 3 · EXECUTE -------------------------------------------------------
    try:
        outcome = fn(ctx, *args, **kwargs)
        if not isinstance(outcome, JobOutcome):
            raise PermanentJobError(
                f"{spec.job_name} returned {type(outcome).__name__}, not a JobOutcome - "
                "a job that does not state its outcome cannot be trusted to have had one"
            )
    except JobBlocked as exc:
        return _finish(
            store,
            log,
            run_id=run_id,
            correlation=correlation,
            outcome=JobOutcome.blocked(exc.reason_code, exc.reason, detail=exc.detail),
        )
    except JobCancelled as exc:
        return _finish(
            store,
            log,
            run_id=run_id,
            correlation=correlation,
            outcome=JobOutcome.cancelled(exc.detail),
        )
    except BaseException as exc:
        return _handle_failure(
            exc,
            store=store,
            log=log,
            spec=spec,
            run_id=run_id,
            correlation=correlation,
            attempt=attempt,
            args=args,
            kwargs=kwargs,
            deps=deps,
        )

    # --- 4 · FINISH --------------------------------------------------------
    disposition = _finish(store, log, run_id=run_id, correlation=correlation, outcome=outcome)

    # A job may fail by RAISING or by RETURNING JobOutcome.failed(...). Both are the
    # same thing to an operator - work the platform accepted and did not deliver - so
    # both must reach the dead-letter queue. Without this, a job that knows exactly why
    # it failed and says so politely is LESS visible than one that throws, which is
    # precisely backwards.
    if outcome.status is JobStatus.FAILED:
        _write_dead_letter(
            store,
            log,
            run_id=run_id,
            args=args,
            kwargs=kwargs,
            reason_code=outcome.reason_code or "returned_failure",
            error_type=outcome.error_type,
            error_message=outcome.error_message,
            traceback_text="",
            attempt=attempt,
        )
    return disposition


def _finish(
    store: JobRunStore,
    log: Any,
    *,
    run_id: str,
    correlation: str,
    outcome: JobOutcome,
) -> Disposition:
    """Write the one terminal record - and never let failing to write it re-run the job.

    A ledger write that fails AFTER the body has run is the one place where retrying
    is worse than losing the record: the pages are already published, the provider is
    already billed, and a redelivery would do it all again. So the store error is
    logged loudly and the disposition still says ``done``. The run row is left
    ``running`` and the reaper will eventually mark it failed - which is a visible,
    investigable wrong state, unlike a silent second publish.
    """
    try:
        store.finish(
            run_id,
            status=outcome.status.value,
            detail=outcome.detail,
            reason=outcome.reason,
            reason_code=outcome.reason_code,
            error_type=outcome.error_type,
            error_message=outcome.error_message,
            cost_usd=outcome.cost_usd,
            result=outcome.result,
        )
    except Exception as exc:
        log.error("job.finish_write_failed", status=outcome.status.value, error=type(exc).__name__)
    else:
        log.info("job.finished", status=outcome.status.value, cost_usd=str(outcome.cost_usd))
    return Disposition(
        action="done",
        status=outcome.status.value,
        detail=outcome.detail,
        run_id=run_id,
        correlation_id=correlation,
        result=outcome.result,
    )


def _handle_failure(
    exc: BaseException,
    *,
    store: JobRunStore,
    log: Any,
    spec: JobSpec,
    run_id: str,
    correlation: str,
    attempt: int,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    deps: _RunnerDeps,
) -> Disposition:
    """Decide between retry and dead letter, and make the terminal write either way.

    The classification rule is conservative on purpose. ``RetryableJobError`` and the
    types a job explicitly declared in ``retry_on`` are transient; **everything else
    is permanent**, including exceptions nobody has thought about yet. Re-running
    unclassified code that touches paid providers is how one bug becomes three
    invoices.
    """
    error_type = type(exc).__name__
    error_message = _sanitize(str(exc))
    transient = isinstance(exc, RetryableJobError) or (
        spec.retry_on and isinstance(exc, spec.retry_on) and not isinstance(exc, PermanentJobError)
    )

    if transient and attempt < spec.max_attempts:
        retry_after = getattr(exc, "retry_after", None)
        countdown = (
            float(retry_after)
            if retry_after is not None
            else compute_backoff(
                attempt,
                base=spec.retry_backoff,
                maximum=spec.retry_backoff_max,
                jitter=deps.jitter,
            )
        )
        detail = f"attempt {attempt}/{spec.max_attempts} failed ({error_type}); retrying"
        store.defer(run_id, scheduled_for_seconds=countdown, detail=detail)
        log.warning(
            "job.retrying",
            attempt=attempt,
            max_attempts=spec.max_attempts,
            error_type=error_type,
            countdown=round(countdown, 1),
        )
        return Disposition(
            action="retry",
            status=JobStatus.QUEUED.value,
            detail=detail,
            run_id=run_id,
            correlation_id=correlation,
            countdown=countdown,
        )

    detail = (
        f"failed permanently ({error_type})"
        if not transient
        else f"failed after {attempt} of {spec.max_attempts} attempts ({error_type})"
    )
    disposition = _finish(
        store,
        log,
        run_id=run_id,
        correlation=correlation,
        outcome=JobOutcome.failed(error_type, error_message, detail=detail),
    )
    _write_dead_letter(
        store,
        log,
        run_id=run_id,
        args=args,
        kwargs=kwargs,
        # An exhausted-retry failure and a permanent one are different problems with
        # different fixes, so the DLQ can be grouped by which it was.
        reason_code="retries_exhausted" if transient else "permanent_error",
        error_type=error_type,
        error_message=error_message,
        traceback_text=_sanitize("".join(traceback.format_exception(exc))[-8000:]),
        attempt=attempt,
    )
    return disposition


def _write_dead_letter(
    store: JobRunStore,
    log: Any,
    *,
    run_id: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    reason_code: str,
    error_type: str,
    error_message: str,
    traceback_text: str,
    attempt: int,
) -> None:
    """Record lost work, and never let failing to record it mask the failure itself."""
    try:
        dead_letter_id = store.dead_letter(
            run_id,
            payload={"args": _jsonable(args), "kwargs": _jsonable(kwargs)},
            reason_code=reason_code,
            error_type=error_type,
            error_message=error_message,
            traceback=traceback_text,
        )
    except Exception as write_exc:
        log.error("job.dead_letter_write_failed", error=type(write_exc).__name__)
    else:
        log.error(
            "job.dead_lettered",
            attempt=attempt,
            error_type=error_type,
            dead_letter_id=dead_letter_id,
        )


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _new_uuid() -> str:
    import uuid

    return str(uuid.uuid4())


def _seconds_waiting(row: dict[str, Any], *, now: datetime) -> float:
    """How long this run has been waiting since it was first enqueued."""
    created = row.get("created_at")
    if not isinstance(created, datetime):
        return 0.0
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return max((now - created).total_seconds(), 0.0)


def _sanitize(text: str) -> str:
    """Keep a secret out of an error string that will be stored and displayed.

    Exception text is the classic leak path - a psycopg connection error carries the
    DSN, an httpx error carries the query string, and both end up in a column staff
    can read. This is a coarse net, not a parser: anything that looks like a
    credential-bearing URL or a key/token assignment is redacted wholesale.
    """
    import re

    redacted = re.sub(r"(?i)\b(postgres(?:ql)?|redis|rediss|amqp)://[^\s\"']+", r"\1://[redacted]", text)
    redacted = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password|authorization|bearer)\b\s*[=:]\s*\S+",
        r"\1=[redacted]",
        redacted,
    )
    return redacted[:4000]


def _jsonable(value: Any) -> Any:
    """Best-effort JSON coercion for the dead-letter payload.

    A payload that cannot be serialised must not stop the dead letter from being
    written - losing the record of lost work is strictly worse than losing the
    argument's exact type. Unserialisable values are replaced by their repr.
    """
    if isinstance(value, str | int | float | bool | type(None)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_jsonable(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return repr(value)[:500]


__all__ = [
    "IN_FLIGHT",
    "Disposition",
    "JobSpec",
    "JobTarget",
    "compute_backoff",
    "run_job",
]
