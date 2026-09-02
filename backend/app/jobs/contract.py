"""The job contract: what a job returns, what it may raise, and what it is handed.

A job under this contract is an ordinary function. It receives a :class:`JobContext`
and returns a :class:`JobOutcome`; the runner around it owns everything else -
idempotency, the run row, retries, the dead letter, the concurrency slot.

The contract is deliberately narrow in one direction: **a job cannot report a
success it did not achieve.** ``JobOutcome.completed()`` takes no reason because
there is nothing to explain; ``degraded()`` and ``blocked()`` cannot be constructed
without one. That asymmetry is the whole design - the cheapest thing to write is the
truth.

WHAT A JOB MAY RAISE
    JobBlocked          a gate refused: no credential, cost cap, automation ceiling.
                        Nothing was spent. Not retried - retrying a refusal just
                        refuses again.
    JobCancelled        a human asked it to stop and it stopped at a checkpoint.
    RetryableJobError   a transient fault (provider 5xx, timeout, lock contention).
                        Retried with backoff until the attempt budget is spent, then
                        failed and dead-lettered.
    PermanentJobError   a fault that will recur identically on every attempt (bad
                        input, a 4xx, a contract violation). Failed and dead-lettered
                        immediately - burning three attempts on it wastes the retry
                        budget and delays the operator seeing it.

Anything else a job raises is treated as PERMANENT. That is the conservative choice:
an unclassified exception is one nobody has reasoned about, and re-running unreasoned
code that touches paid providers is how a bug becomes a bill.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from typing import Any, Final, Protocol

from app.jobs.status import JobQueue, JobStatus

#: A machine-readable reason must be a stable IDENTIFIER, not a sentence - lower
#: snake_case, 3-64 chars. Mirrors the `job_runs_reason_code_format_ck` constraint, so
#: a bad code is a TypeError at the call site rather than a constraint violation at
#: the moment a job is trying to record why it refused to spend.
_REASON_CODE_RE: Final = re.compile(r"^[a-z][a-z0-9_]{2,63}$")


def validate_reason_code(code: str) -> str:
    """Raise unless ``code`` is a stable snake_case identifier.

    The point of the code is that it can be GROUPED, filtered and compared - across
    modules and across months. Prose cannot: every call site phrases "no WordPress
    credentials" differently, so the only way to ask how often that block happens is
    to grep free text, which is how a recurring and fixable refusal stays invisible.
    """
    if not _REASON_CODE_RE.match(code):
        raise ValueError(
            f"reason_code {code!r} must be lower snake_case, 3-64 chars "
            "(a stable identifier to group by, not a sentence - the prose goes in `reason`)"
        )
    return code

# --------------------------------------------------------------------------- #
# Exceptions
# --------------------------------------------------------------------------- #


class JobError(Exception):
    """Base for every exception the contract understands."""


class JobBlocked(JobError):  # noqa: N818 - reads as a state at the raise site, not an error object
    """A gate refused to let the job spend. Terminal, never retried.

    ``reason`` is mandatory and is written to ``job_runs.reason``, where the DB
    check constraint also requires it. A block is a loud, explained refusal - it is
    never a silent 202 and never an empty result that looks like nothing to do.
    """

    def __init__(self, reason_code: str, reason: str, *, detail: str = "") -> None:
        if not reason.strip():
            raise ValueError("JobBlocked requires a reason: a refusal that cannot say why is a lie")
        validate_reason_code(reason_code)
        super().__init__(reason)
        self.reason_code = reason_code
        self.reason = reason
        self.detail = detail or reason


class JobCancelled(JobError):  # noqa: N818 - reads as a state at the raise site, not an error object
    """A human requested cancellation and the job stopped at a checkpoint."""

    def __init__(self, detail: str = "cancelled by operator request") -> None:
        super().__init__(detail)
        self.detail = detail


class RetryableJobError(JobError):
    """A transient fault. Retried with backoff while the attempt budget lasts.

    ``retry_after`` overrides the computed backoff - use it when the provider told
    us how long to wait (a ``Retry-After`` header, a rate-limit reset).
    """

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class PermanentJobError(JobError):
    """A fault that will recur identically on every attempt. Never retried."""


# --------------------------------------------------------------------------- #
# The outcome
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class JobOutcome:
    """What a job returns. Terminal by construction.

    Build one with the classmethods rather than the constructor - they encode which
    fields each terminal state requires, so an invalid outcome is a TypeError at the
    call site rather than a constraint violation at the database.
    """

    status: JobStatus
    detail: str = ""
    reason: str = ""
    reason_code: str = ""
    error_type: str = ""
    error_message: str = ""
    cost_usd: Decimal = Decimal("0")
    result: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            JobStatus.COMPLETED,
            JobStatus.DEGRADED,
            JobStatus.BLOCKED,
            JobStatus.FAILED,
            JobStatus.CANCELLED,
        }:
            raise ValueError(f"JobOutcome must be terminal, got {self.status!r}")
        if self.status in {JobStatus.DEGRADED, JobStatus.BLOCKED}:
            if not self.reason.strip():
                raise ValueError(f"a {self.status} outcome requires a reason")
            # Both registers, always: the prose for a person, the code for every
            # dashboard, filter and automation that has to count this happening.
            validate_reason_code(self.reason_code)
        if self.status is JobStatus.FAILED and not self.error_type.strip():
            raise ValueError("a failed outcome requires an error_type")
        if self.cost_usd < 0:
            raise ValueError("cost_usd cannot be negative")

    # --- constructors -------------------------------------------------------
    @classmethod
    def completed(
        cls,
        detail: str = "",
        *,
        cost_usd: Decimal | float | int = 0,
        result: dict[str, Any] | None = None,
    ) -> JobOutcome:
        """The promise was kept in full. The ONLY outcome that renders as success.

        Takes no reason, on purpose: if the job needs to explain a caveat, the
        caveat means it was degraded, not completed.
        """
        return cls(
            status=JobStatus.COMPLETED,
            detail=detail,
            cost_usd=_as_decimal(cost_usd),
            result=result,
        )

    @classmethod
    def degraded(
        cls,
        reason_code: str,
        reason: str,
        *,
        detail: str = "",
        cost_usd: Decimal | float | int = 0,
        result: dict[str, Any] | None = None,
    ) -> JobOutcome:
        """The job finished, and part of what it promised did not happen.

        ``reason_code`` is the stable identifier an operator surface groups by
        (``wp_rest_rejected``). ``reason`` names the part that did not happen in
        words a person can act on: "published 2 of 10 pages; 8 rejected by the site's
        REST API" - not "partial success".

        Both are required. The code alone is unreadable; the prose alone is
        un-countable, and a partial outcome nobody can count is one nobody fixes.
        """
        return cls(
            status=JobStatus.DEGRADED,
            detail=detail or reason,
            reason=reason,
            reason_code=reason_code,
            cost_usd=_as_decimal(cost_usd),
            result=result,
        )

    @classmethod
    def blocked(
        cls,
        reason_code: str,
        reason: str,
        *,
        detail: str = "",
        result: dict[str, Any] | None = None,
    ) -> JobOutcome:
        """A gate refused. Nothing was spent, so there is no cost argument.

        ``reason_code`` is what makes a refusal actionable in aggregate - "47 publishes
        blocked on ``wp_credentials_missing`` this week" is a task; forty-seven
        differently-worded sentences are not.
        """
        return cls(
            status=JobStatus.BLOCKED,
            detail=detail or reason,
            reason=reason,
            reason_code=reason_code,
            result=result,
        )

    @classmethod
    def failed(
        cls,
        error_type: str,
        error_message: str = "",
        *,
        detail: str = "",
        cost_usd: Decimal | float | int = 0,
        result: dict[str, Any] | None = None,
    ) -> JobOutcome:
        """An unrecoverable error. Carries a cost because a job can fail after spending."""
        return cls(
            status=JobStatus.FAILED,
            detail=detail or error_message or error_type,
            error_type=error_type,
            error_message=error_message,
            cost_usd=_as_decimal(cost_usd),
            result=result,
        )

    @classmethod
    def cancelled(cls, detail: str = "cancelled by operator request") -> JobOutcome:
        return cls(status=JobStatus.CANCELLED, detail=detail)

    # --- queries ------------------------------------------------------------
    @property
    def succeeded(self) -> bool:
        """True only for ``completed`` - see ``app.jobs.status.is_success``."""
        return self.status is JobStatus.COMPLETED


def _as_decimal(value: Decimal | float | int) -> Decimal:
    """Coerce a cost to Decimal without going through binary float where avoidable."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# --------------------------------------------------------------------------- #
# The store seam
# --------------------------------------------------------------------------- #
class StartOutcome(StrEnum):
    """Why a claimed run did or did not begin executing.

    ``start()`` is the moment three separate refusals converge, and the runner has to
    tell them apart: a capped run is re-queued and tried again shortly, a cancelled
    one is finished immediately, and a run someone else already owns is dropped
    without touching it.
    """

    STARTED = "started"
    #: A human requested cancellation while it sat in the queue.
    CANCELLED = "cancelled"
    #: The client is already at its in-flight cap on this queue. Not an error - the
    #: run stays queued and the runner defers it with backoff.
    CAPPED = "capped"
    #: Another worker already moved this run out of `queued`. At-least-once delivery
    #: makes this normal, not exceptional: the duplicate simply stops here.
    NOT_CLAIMABLE = "not_claimable"


@dataclass(frozen=True, slots=True)
class StartResult:
    """The result of trying to move a claimed run into ``running``."""

    outcome: StartOutcome
    row: dict[str, Any] | None = None
    #: Populated for CAPPED: how many of this client's runs are already in flight.
    in_flight: int = 0

    @property
    def started(self) -> bool:
        return self.outcome is StartOutcome.STARTED


class JobRunStore(Protocol):
    """The persistence seam the runner needs.

    A Protocol rather than a concrete class so the whole runner - idempotency,
    retry accounting, cancellation, dead-lettering - is unit-testable against an
    in-memory fake with no Postgres, which is the only way this layer gets the test
    coverage it deserves.
    """

    def claim(
        self,
        *,
        job_name: str,
        task: str,
        queue: str,
        idempotency_key: str | None,
        correlation_id: str,
        parent_run_id: str | None,
        celery_task_id: str,
        client_id: str | None,
        client_name: str,
        scope_type: str,
        scope_id: str | None,
        max_attempts: int,
    ) -> tuple[dict[str, Any], bool]: ...

    def start(
        self, run_id: str, *, celery_task_id: str, client_concurrency: int, max_attempts: int
    ) -> StartResult: ...

    def heartbeat(self, run_id: str) -> None: ...

    def progress(self, run_id: str, detail: str) -> None: ...

    def cancel_requested(self, run_id: str) -> bool: ...

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        detail: str,
        reason: str,
        reason_code: str,
        error_type: str,
        error_message: str,
        cost_usd: Decimal,
        result: dict[str, Any] | None,
    ) -> dict[str, Any] | None: ...

    def defer(self, run_id: str, *, scheduled_for_seconds: float, detail: str) -> None: ...

    def dead_letter(
        self,
        run_id: str,
        *,
        payload: dict[str, Any],
        reason_code: str,
        error_type: str,
        error_message: str,
        traceback: str,
    ) -> str | None: ...


# --------------------------------------------------------------------------- #
# The context handed to a job
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class JobContext:
    """Everything a job needs from the runner, and nothing it does not.

    Two of these methods carry the operational weight:

    ``heartbeat()`` - a long job must call this periodically (per page, per client,
    per batch). A run whose heartbeat goes quiet past its queue's time limit was
    killed without ACKing, and the reaper marks it failed. Without a heartbeat that
    run stays ``running`` forever and holds a concurrency slot against the client.

    ``check_cancelled()`` - cancellation is COOPERATIVE, because a Celery task cannot
    be safely killed part-way through writing to a client's website. A job that never
    checks can never be stopped, so anything that loops must check between iterations.
    Both calls are throttled internally, so calling them in a tight loop is cheap.
    """

    run_id: str
    correlation_id: str
    job_name: str
    task: str
    queue: JobQueue
    attempt: int
    max_attempts: int
    client_id: str | None = None
    client_name: str = ""
    scope_type: str = ""
    scope_id: str | None = None
    idempotency_key: str | None = None

    _store: JobRunStore | None = field(default=None, repr=False)
    _clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    _heartbeat_every: float = field(default=30.0, repr=False)
    _cancel_poll_every: float = field(default=10.0, repr=False)
    # -inf, not 0.0: a monotonic clock can legitimately start at 0, and a first call
    # that silently does nothing is exactly the kind of small wrong thing that makes a
    # long job look dead for its first throttle window.
    _last_heartbeat: float = field(default=float("-inf"), repr=False)
    _last_cancel_poll: float = field(default=float("-inf"), repr=False)
    _cancelled: bool = field(default=False, repr=False)

    @property
    def is_final_attempt(self) -> bool:
        """True when a raise from here will not be retried.

        Useful for deciding whether to degrade rather than fail: on the last attempt
        a partial result is worth recording, where on an earlier attempt it is worth
        retrying for the whole one.
        """
        return self.attempt >= self.max_attempts

    def heartbeat(self, *, force: bool = False) -> None:
        """Stamp liveness. Throttled to one write per ``_heartbeat_every`` seconds."""
        if self._store is None:
            return
        now = self._clock()
        if not force and (now - self._last_heartbeat) < self._heartbeat_every:
            return
        self._last_heartbeat = now
        self._store.heartbeat(self.run_id)

    def progress(self, detail: str, *, force: bool = False) -> None:
        """Say what this job is doing NOW, in one line a human can read.

        A long job could only ever report two things - that it had been claimed, and
        what it concluded - so "running" covered everything between, and an operator
        watching a sweep of two hundred directories had no way to tell work from a
        hang. This writes the contract's own ``detail`` column, which is documented as
        "one human line, always safe to show", and stamps liveness at the same time.

        Throttled on the heartbeat's own clock: a per-directory call would otherwise
        be one UPDATE per directory. The FINAL detail is written by ``finish``, so a
        throttled-away line is never the last word.

        ``force`` writes the line regardless of the throttle, mirroring
        ``heartbeat(force=True)``. The throttle exists to stop a loop over HUNDREDS of
        items issuing an UPDATE each; it is wrong for a job with a handful of long,
        genuinely different STAGES. A design replication has about eight stages and
        takes 12-60s, so at the default 30s throttle an operator saw one line for the
        whole run - which is barely different from the "running" it replaced. Use
        ``force`` only where the call sites are few and named.
        """
        if self._store is None or not detail:
            return
        now = self._clock()
        if not force and (now - self._last_heartbeat) < self._heartbeat_every:
            return
        self._last_heartbeat = now
        self._store.progress(self.run_id, detail)

    def cancelled(self) -> bool:
        """Whether a human has requested cancellation. Throttled; latches once True."""
        if self._cancelled:
            return True
        if self._store is None:
            return False
        now = self._clock()
        if (now - self._last_cancel_poll) < self._cancel_poll_every:
            return False
        self._last_cancel_poll = now
        self._cancelled = self._store.cancel_requested(self.run_id)
        return self._cancelled

    def check_cancelled(self) -> None:
        """Raise :class:`JobCancelled` if cancellation has been requested."""
        if self.cancelled():
            raise JobCancelled()

    def checkpoint(self) -> None:
        """Heartbeat and check for cancellation in one call.

        The idiom for the top of any loop body::

            for page in pages:
                ctx.checkpoint()
                publish(page)
        """
        self.heartbeat()
        self.check_cancelled()

    def child_key(self, suffix: str) -> str | None:
        """Derive a stable idempotency key for a job this one enqueues.

        Returns ``None`` when this run has no key of its own - a child of an
        un-keyed parent cannot be made idempotent by inheritance, and pretending
        otherwise would produce a key that collides across unrelated fan-outs.
        """
        if self.idempotency_key is None:
            return None
        return f"{self.idempotency_key}:{suffix}"
