"""The job contract - the spine every background job in the platform stands on.

Importing this package does NOT import Celery. The Celery binding lives in
``app.jobs.celery_task`` and is imported only by task modules, so the FastAPI edge
can read job status, enqueue nothing, and stay broker-free.

    app.jobs.status      the one status vocabulary + the four duration classes
    app.jobs.contract    what a job returns, raises, and is handed
    app.jobs.runner      idempotency, retry, capping, cancellation, dead-lettering
    app.jobs.celery_task @aios_job and enqueue (the only Celery-aware module)
"""

from __future__ import annotations

from app.jobs.contract import (
    JobBlocked,
    JobCancelled,
    JobContext,
    JobError,
    JobOutcome,
    JobRunStore,
    PermanentJobError,
    RetryableJobError,
    StartOutcome,
    StartResult,
)
from app.jobs.runner import Disposition, JobSpec, JobTarget, compute_backoff, run_job
from app.jobs.status import (
    BROKER_VISIBILITY_TIMEOUT,
    SOFT_TIME_LIMITS,
    TERMINAL,
    TIME_LIMITS,
    JobQueue,
    JobStatus,
    is_success,
    is_terminal,
    needs_attention,
    stale_after_seconds,
    terminal_for,
)

__all__ = [
    "BROKER_VISIBILITY_TIMEOUT",
    "SOFT_TIME_LIMITS",
    "TERMINAL",
    "TIME_LIMITS",
    "Disposition",
    "JobBlocked",
    "JobCancelled",
    "JobContext",
    "JobError",
    "JobOutcome",
    "JobQueue",
    "JobRunStore",
    "JobSpec",
    "JobStatus",
    "JobTarget",
    "PermanentJobError",
    "RetryableJobError",
    "StartOutcome",
    "StartResult",
    "compute_backoff",
    "is_success",
    "is_terminal",
    "needs_attention",
    "run_job",
    "stale_after_seconds",
    "terminal_for",
]
