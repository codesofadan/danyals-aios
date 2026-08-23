"""Maintenance for the job contract itself: the stuck-run reaper.

A worker killed by the OOM reaper, a host reboot, or a ``systemctl restart aios-worker``
mid-job never gets to write a terminal state. Its ``job_runs`` row stays ``running``
forever - and because ``JobRunsStore.start`` counts ``running`` rows against the
per-client concurrency cap, a handful of those rows permanently reduce a client's
throughput to zero without anything appearing to be wrong.

This sweep is what makes the cap safe to enforce. It fails every run whose heartbeat
has been silent for longer than its queue allows, which turns an invisible stall into
a visible, dead-letterable failure.

The reaper deliberately does NOT run under ``@aios_job``: it is the thing that
repairs the ledger, so it cannot depend on the ledger being healthy. It follows the
older worker template instead - idempotent, never re-raising (with ``task_acks_late``
a raised exception is a redelivery risk), and recording its own run in
``scheduled_job_runs`` so the operator surface can show when it last swept.
"""

from __future__ import annotations

from typing import Any

from app.db.job_runs_repo import job_runs_store
from app.logging_setup import get_logger

logger = get_logger("workers.job_maintenance")

_REAP_JOB = "reap-stale-job-runs"
_REAP_TASK = "reap_stale_job_runs"


def execute_reap() -> dict[str, Any]:
    """The pure core: reap, log, and summarise. Never raises.

    Returns a small summary dict rather than the reaped rows - a sweep that reaped
    400 rows must not put 400 rows in the Celery result backend.
    """
    try:
        reaped = job_runs_store().reap_stale_runs()
    except Exception as exc:
        logger.error("job_reaper.failed", error=type(exc).__name__)
        return {"status": "error", "reaped": 0, "detail": type(exc).__name__}

    if not reaped:
        return {"status": "ok", "reaped": 0, "detail": "no stale runs"}

    by_job: dict[str, int] = {}
    for row in reaped:
        job_name = str(row.get("job_name", "unknown"))
        by_job[job_name] = by_job.get(job_name, 0) + 1
        logger.warning(
            "job_reaper.reaped",
            run_id=str(row.get("id")),
            job_name=job_name,
            queue=str(row.get("queue")),
            client_id=str(row.get("client_id") or ""),
            correlation_id=str(row.get("correlation_id") or ""),
        )

    detail = ", ".join(f"{name}x{count}" for name, count in sorted(by_job.items()))
    return {"status": "degraded", "reaped": len(reaped), "detail": f"reaped {detail}"}


# The Celery app is imported LAST, after the pure core, per the worker template - so
# importing this module from a test stays Celery-free.
from workers.celery_app import celery_app  # noqa: E402


@celery_app.task(name=_REAP_TASK)  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def reap_stale_job_runs() -> dict[str, Any]:
    """Beat entry: fail every run whose worker died without writing an outcome."""
    return execute_reap()
