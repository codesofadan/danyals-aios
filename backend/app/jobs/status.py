"""The ONE status vocabulary, and the queue duration classes.

Every background job in the platform reports its outcome in these seven words, and
every operator surface keys off them. The value of a shared vocabulary is entirely in
the distinction it forces:

    completed  the promise was kept
    degraded   the job finished but part of the promise was NOT kept
    blocked    the job deliberately did not spend (gate, missing credential, cap)
    failed     the job hit an error it could not recover from
    cancelled  a human stopped it

Before this module, ``audit_status`` said ``done``, ``site_job_status`` said
``completed``, ``scheduled_job_status`` said ``ok`` - and not one of them could say
``degraded``. A WordPress publish that reached no website at all reported ``done``,
because ``done`` was the only terminal word available. ``DOMAIN_TERMINAL_MAP`` below
translates each module's own lifecycle word into this vocabulary so a dashboard can
ask one question of every module.

THE RULE THAT MATTERS: ``is_success`` returns True for ``completed`` and nothing
else. ``degraded`` is not a success. Anything that renders a green tick, increments a
"jobs completed" counter, or reports to a client must go through ``is_success``.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final


class JobStatus(StrEnum):
    """The canonical execution vocabulary (mirrors ``public.job_status``)."""

    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: The five values that end a run. A row in any of these MUST carry ``finished_at``
#: (enforced by ``job_runs_finished_ck``).
TERMINAL: Final[frozenset[JobStatus]] = frozenset(
    {
        JobStatus.COMPLETED,
        JobStatus.DEGRADED,
        JobStatus.BLOCKED,
        JobStatus.FAILED,
        JobStatus.CANCELLED,
    }
)

#: Terminal states that REQUIRE a written reason (``job_runs_reason_required_ck``).
#: A partial outcome that cannot say which part failed is indistinguishable from a
#: success, which is precisely the defect this contract exists to remove.
REASON_REQUIRED: Final[frozenset[JobStatus]] = frozenset({JobStatus.DEGRADED, JobStatus.BLOCKED})

#: States in which a run occupies a per-client concurrency slot.
IN_FLIGHT: Final[frozenset[JobStatus]] = frozenset({JobStatus.QUEUED, JobStatus.RUNNING})

#: Terminal states that are NOT a success, i.e. everything an operator must look at.
NEEDS_ATTENTION: Final[frozenset[JobStatus]] = frozenset(
    {JobStatus.DEGRADED, JobStatus.BLOCKED, JobStatus.FAILED}
)


def is_terminal(status: JobStatus | str) -> bool:
    """True when ``status`` ends the run (nothing further will happen to it)."""
    return JobStatus(status) in TERMINAL


def is_success(status: JobStatus | str) -> bool:
    """True ONLY for ``completed``.

    This is the single gate every success signal in the product must pass through -
    a green tick, a "jobs completed" count, a client-facing "your pages are live".
    ``degraded`` deliberately returns False: a job that published two of ten pages
    did not succeed, and the moment it is allowed to look like it did, the operator
    is back to reading a board that lies.
    """
    return JobStatus(status) is JobStatus.COMPLETED


def needs_attention(status: JobStatus | str) -> bool:
    """True for the three terminal states an operator has to do something about."""
    return JobStatus(status) in NEEDS_ATTENTION


# --------------------------------------------------------------------------- #
# Duration classes
# --------------------------------------------------------------------------- #
class JobQueue(StrEnum):
    """Queue by DURATION, not by module (mirrors ``public.job_queue``).

    Splitting by module puts a 2-second webhook behind a 40-minute crawl on the same
    queue; with ``worker_prefetch_multiplier=1`` that webhook waits for the crawl.
    Splitting by duration means a slow class can only ever starve itself.

    ``BROWSER`` is separate from ``LONG`` for a second reason: it is the only class
    that needs Chromium and Playwright in its image, so it runs on its own worker
    with its own memory envelope. That is what keeps an audit from taking down the
    API host.
    """

    INTERACTIVE = "interactive"
    STANDARD = "standard"
    LONG = "long"
    BROWSER = "browser"


#: Hard time limit per queue, in seconds. A task exceeding this is killed by Celery.
#:
#: INVARIANT (carried from ``workers/celery_app.py``): with ``task_acks_late=True`` on
#: a Redis broker, the broker's ``visibility_timeout`` MUST be >= the largest value
#: here, or a job that runs longer than the visibility window is redelivered to a
#: SECOND worker and runs twice - double spend. ``queue_time_limits`` and the broker
#: option are asserted against each other in ``tests/test_job_queues.py``.
TIME_LIMITS: Final[dict[JobQueue, int]] = {
    JobQueue.INTERACTIVE: 60,
    JobQueue.STANDARD: 300,
    JobQueue.LONG: 1800,
    JobQueue.BROWSER: 7200,
}

def _soft_limit(hard: int) -> int:
    """The soft limit for a hard limit: 60s of grace, or a quarter of the budget for a
    class too short to spare a minute.

    The grace is not decoration - ``SoftTimeLimitExceeded`` is raised INSIDE the task,
    which is the job's only chance to record an honest terminal state before Celery
    kills the process. A flat ``hard - 60`` produced a soft limit of ZERO on the
    60-second interactive class, which Celery reads as falsy: no soft limit at all,
    and therefore no honest outcome from any interactive job that overran.
    """
    return hard - min(60, max(5, hard // 4))


#: Soft limit (raises ``SoftTimeLimitExceeded`` inside the task so it can finish its
#: bookkeeping and record an honest terminal state) below the hard kill.
SOFT_TIME_LIMITS: Final[dict[JobQueue, int]] = {q: _soft_limit(limit) for q, limit in TIME_LIMITS.items()}

#: The broker visibility timeout that satisfies the invariant above, with a margin so
#: a job that runs to its exact hard limit still ACKs before the window closes.
BROKER_VISIBILITY_TIMEOUT: Final[int] = max(TIME_LIMITS.values()) + 300

#: A run whose heartbeat is older than its queue's time limit plus this grace was
#: killed without ACKing (OOM, worker restart, host reboot). The reaper marks it
#: failed rather than leaving a `running` row that holds a concurrency slot forever.
HEARTBEAT_GRACE_SECONDS: Final[int] = 300


def stale_after_seconds(queue: JobQueue | str) -> int:
    """Seconds of heartbeat silence after which a ``running`` run is presumed dead."""
    return TIME_LIMITS[JobQueue(queue)] + HEARTBEAT_GRACE_SECONDS


# --------------------------------------------------------------------------- #
# Translating the existing module vocabularies
# --------------------------------------------------------------------------- #
#: Per-module lifecycle word -> canonical terminal state.
#:
#: The module tables keep their own enums (they encode a HUMAN workflow -
#: ``needs_review`` is a real and useful state that this vocabulary has no word for,
#: and should not). This map covers only the TERMINAL words, so a rollup across
#: modules can be computed without teaching every dashboard six vocabularies.
#:
#: Note what is deliberately absent: no module enum currently has a ``degraded``
#: label, which is why a degraded outcome had nowhere to go. Adding that label to the
#: module enums is the next step of the contract (spine item 2); until then a module
#: records its degradation on the ``job_runs`` row, and the rollup is honest even
#: while the module table is not.
DOMAIN_TERMINAL_MAP: Final[dict[str, dict[str, JobStatus]]] = {
    "audit_status": {
        "done": JobStatus.COMPLETED,
        "failed": JobStatus.FAILED,
    },
    "content_status": {
        "done": JobStatus.COMPLETED,
        # Added ahead of P0-4, which adds the `degraded` label to `content_status`
        # (migration 0081) so a credential-less WordPress publish stops recording
        # `done` while nothing reached the client's site. Mapping it here FIRST is
        # deliberate: the map is read by rollups, and a module status with no mapping
        # is worse than one that maps early - an unmapped terminal word silently
        # disappears from every cross-module count.
        "degraded": JobStatus.DEGRADED,
        "failed": JobStatus.FAILED,
        # A lead's rejection is a human decision that ends the run. It is not an
        # error and it is not a success - `cancelled` is the honest word.
        "rejected": JobStatus.CANCELLED,
    },
    "web2_status": {
        "published": JobStatus.COMPLETED,
        "failed": JobStatus.FAILED,
        "rejected": JobStatus.CANCELLED,
    },
    "site_job_status": {
        "completed": JobStatus.COMPLETED,
        "failed": JobStatus.FAILED,
    },
    "onpage_analysis_status": {
        "done": JobStatus.COMPLETED,
        "failed": JobStatus.FAILED,
        # `held` is a refusal to act on a live site without lead attribution.
        "held": JobStatus.BLOCKED,
    },
    "citation_submit_status": {
        "verified": JobStatus.COMPLETED,
        # `submitted` is NOT completed: the listing has been sent and not yet proven
        # live. Treating it as success is how a citation count stops being true.
        "submitted": JobStatus.DEGRADED,
        "failed": JobStatus.FAILED,
        "blocked": JobStatus.BLOCKED,
    },
    "import_status": {
        "imported": JobStatus.COMPLETED,
        "partial": JobStatus.DEGRADED,
        "failed": JobStatus.FAILED,
    },
    "scheduled_job_status": {
        "ok": JobStatus.COMPLETED,
        "degraded": JobStatus.DEGRADED,
        "blocked": JobStatus.BLOCKED,
        "error": JobStatus.FAILED,
        "skipped": JobStatus.CANCELLED,
    },
}


def terminal_for(domain_enum: str, value: str) -> JobStatus | None:
    """Map a module's own terminal word onto the canonical vocabulary.

    Returns ``None`` when ``value`` is a non-terminal lifecycle state (``queued``,
    ``drafting``, ``needs_review``) - those have no canonical equivalent by design.
    Raises ``KeyError`` for an unknown ``domain_enum`` so a new module cannot quietly
    opt out of the rollup.
    """
    return DOMAIN_TERMINAL_MAP[domain_enum].get(value)
