"""Data access for the job contract (``job_runs`` + ``job_dead_letters``).

Two seams, for two different callers:

``JobRunsStore``  - the SERVER seam, on ``privileged_connection`` (service_role,
                    BYPASSRLS). This is what the worker runner uses. A Celery worker
                    has no authenticated identity, so it cannot use the RLS seam, and
                    both tables are deliberately server-written only.

``JobRunsRepo``   - the READ seam, on ``rls_connection(user_id)``. The operator API
                    reads through this so Postgres - not the router - is what stops a
                    portal client seeing the platform's execution history.

SQL rules (impersonation-review mandate): every VALUE is a bound param (``%s``),
never string-formatted; table and column names are static literals.

THE ONE PIECE OF REAL CONCURRENCY CONTROL IS ``start()``. Read its docstring before
changing it: check-then-set on the per-client cap is only safe because the count and
the transition happen inside one transaction under one advisory lock.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Any, Final

from fastapi import Depends
from psycopg.types.json import Jsonb

from app.core.auth import CurrentUserDep
from app.db.database import privileged_connection, rls_connection
from app.jobs.contract import StartOutcome, StartResult
from app.jobs.status import JobQueue, JobStatus, stale_after_seconds

_Rows = list[dict[str, Any]]

#: Namespace for the two-argument advisory locks this module takes. Postgres keeps
#: two-argument advisory locks in a separate space from the single-bigint form, so
#: this cannot collide with the beat overlap locks in ``rank_tracker`` / ``local_seo``
#: even by accident.
_JOB_CAP_LOCK_NAMESPACE: Final[int] = 0x41494F53  # 'AIOS'

#: `detail` is unbounded `text`, so the cap is about what a human can read in a row,
#: not what the column can hold - a stage line that scrolls is not a status.
_DETAIL_MAX: Final[int] = 200

_RUN_COLUMNS: Final[str] = (
    "id, job_name, task, queue, idempotency_key, correlation_id, parent_run_id, "
    "celery_task_id, client_id, client_name, scope_type, scope_id, status, attempt, "
    "max_attempts, scheduled_for, started_at, finished_at, heartbeat_at, "
    "cancel_requested_at, cancel_requested_by, detail, reason, reason_code, error_type, "
    "error_message, cost_usd, result, created_at, updated_at"
)


class JobRunsStore:
    """The server-side store the runner drives. Privileged; never client-facing."""

    # --- claim ---------------------------------------------------------------
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
    ) -> tuple[dict[str, Any], bool]:
        """Create the run row, or find the one that already owns this unit of work.

        Returns ``(row, created)``. ``created=False`` means another enqueue got here
        first: the caller must NOT do the work again - if that row is already
        terminal the work is done, and if it is in flight someone else is doing it.

        The insert is ``ON CONFLICT ... DO NOTHING`` against the partial unique index
        on ``idempotency_key``, so the race is resolved by Postgres rather than by a
        read-then-write in application code (which would lose it). The inference
        clause repeats the index predicate because a partial index cannot be inferred
        without it.

        A ``NULL`` key opts out of idempotency entirely and always inserts - NULLs do
        not conflict. That is correct for heartbeat sweeps and pure reads, and wrong
        for anything that spends money.
        """
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.job_runs ("
                "  job_name, task, queue, idempotency_key, correlation_id, parent_run_id,"
                "  celery_task_id, client_id, client_name, scope_type, scope_id, max_attempts"
                ") values (%s, %s, %s::public.job_queue, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
                "on conflict (idempotency_key) where idempotency_key is not null do nothing "
                f"returning {_RUN_COLUMNS}",
                (
                    job_name,
                    task,
                    queue,
                    idempotency_key,
                    correlation_id,
                    parent_run_id,
                    celery_task_id,
                    client_id,
                    client_name,
                    scope_type,
                    scope_id,
                    max_attempts,
                ),
            )
            inserted = cur.fetchone()
            if inserted is not None:
                return dict(inserted), True

            # The key was already taken. Return whoever owns it so the runner can
            # decide (terminal -> nothing to do; in flight -> someone else has it).
            cur.execute(
                f"select {_RUN_COLUMNS} from public.job_runs where idempotency_key = %s",
                (idempotency_key,),
            )
            existing = cur.fetchone()
            if existing is None:  # pragma: no cover - only if the row vanished mid-race
                raise RuntimeError(f"idempotency key {idempotency_key!r} conflicted but no row exists")
            return dict(existing), False

    # --- start ---------------------------------------------------------------
    def start(
        self, run_id: str, *, celery_task_id: str, client_concurrency: int, max_attempts: int
    ) -> StartResult:
        """Move a queued run into ``running``, honouring the per-client cap.

        WHY THE ADVISORY LOCK. The cap is a check-then-set: count this client's
        in-flight runs, and only then transition. Without serialisation, N workers
        picking up N of a client's jobs at the same instant all read a count below the
        cap and all start - the cap is then decorative, which is exactly how one
        client's 300-page bulk run starves every other client on the platform. The
        lock is transaction-scoped and keyed on (client, queue), so it serialises only
        the runs actually competing for the same slots; two different clients never
        block each other, and the lock is released by COMMIT no matter what happens.

        ``client_concurrency <= 0`` or a run with no ``client_id`` means no cap - a
        platform-wide sweep is not owned by any tenant and must not consume a tenant's
        slots.

        The four outcomes are distinct because the runner handles them differently:
        CAPPED is deferred and retried, CANCELLED is finished, NOT_CLAIMABLE is
        dropped silently (an at-least-once broker produces duplicates by design).
        """
        with privileged_connection() as cur:
            cur.execute(
                f"select {_RUN_COLUMNS} from public.job_runs where id = %s for update",
                (run_id,),
            )
            row = cur.fetchone()
            if row is None:
                return StartResult(outcome=StartOutcome.NOT_CLAIMABLE)

            if row["cancel_requested_at"] is not None:
                return StartResult(outcome=StartOutcome.CANCELLED, row=dict(row))

            if row["status"] != JobStatus.QUEUED.value:
                return StartResult(outcome=StartOutcome.NOT_CLAIMABLE, row=dict(row))

            client_id = row["client_id"]
            queue = row["queue"]
            if client_id is not None and client_concurrency > 0:
                # Serialise every worker competing for THIS client's slots on THIS
                # queue. Taken after the FOR UPDATE above, and both are released by
                # the same COMMIT, so the ordering is fixed and cannot deadlock
                # against another start() for the same run.
                cur.execute(
                    "select pg_advisory_xact_lock(%s, hashtext(%s))",
                    (_JOB_CAP_LOCK_NAMESPACE, f"{client_id}:{queue}"),
                )
                cur.execute(
                    "select count(*) as n from public.job_runs "
                    "where client_id = %s and queue = %s::public.job_queue "
                    "and status = 'running' and id <> %s",
                    (client_id, queue, run_id),
                )
                counted = cur.fetchone()
                in_flight = int(counted["n"]) if counted is not None else 0
                if in_flight >= client_concurrency:
                    return StartResult(
                        outcome=StartOutcome.CAPPED,
                        row=dict(row),
                        in_flight=in_flight,
                    )

            # max_attempts is (re)stamped from the CODE's spec, not left at whatever
            # the row was created with. Two callers create rows without knowing the
            # spec - the DLQ replay endpoint, and any future pre-created run - and a
            # row carrying a stale, smaller budget would violate the
            # `attempt <= max_attempts` CHECK on the job's second attempt. The spec is
            # the truth about how many attempts a job gets; the row records it.
            cur.execute(
                "update public.job_runs set status = 'running', attempt = attempt + 1, "
                "max_attempts = %s, started_at = coalesce(started_at, now()), "
                "heartbeat_at = now(), scheduled_for = null, celery_task_id = %s "
                "where id = %s and status = 'queued' "
                f"returning {_RUN_COLUMNS}",
                (max_attempts, celery_task_id, run_id),
            )
            started = cur.fetchone()
            if started is None:  # pragma: no cover - the FOR UPDATE above makes this unreachable
                return StartResult(outcome=StartOutcome.NOT_CLAIMABLE, row=dict(row))
            return StartResult(outcome=StartOutcome.STARTED, row=dict(started))

    # --- liveness + cancellation ---------------------------------------------
    def heartbeat(self, run_id: str) -> None:
        """Stamp ``heartbeat_at``. Scoped to ``running`` so it cannot revive a
        terminal row - a late heartbeat from a task that already finished is a
        no-op rather than a resurrection."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.job_runs set heartbeat_at = now() where id = %s and status = 'running'",
                (run_id,),
            )

    def progress(self, run_id: str, detail: str) -> None:
        """Record what the job is doing now, and stamp liveness while doing it.

        Scoped to ``running`` for the same reason ``heartbeat`` is: a late line from a
        task that has already finished must not overwrite the conclusion with a stage
        it was passing through. ``detail`` is the contract's one human-readable line,
        and ``finish`` writes it last, so this can only ever describe work in flight.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.job_runs set detail = %s, heartbeat_at = now() "
                "where id = %s and status = 'running'",
                (detail[:_DETAIL_MAX], run_id),
            )

    def get_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        """The run that owns this unit of work, by the key that identifies it.

        Enqueue writes the row and knows the key, so a router can hand its caller a
        durable run id in the same request - rather than a Celery message id, which
        outlives nothing, or no handle at all.
        """
        with privileged_connection() as cur:
            cur.execute(
                f"select {_RUN_COLUMNS} from public.job_runs where idempotency_key = %s",
                (key,),
            )
            return cur.fetchone()

    def cancel_requested(self, run_id: str) -> bool:
        """Whether a human has asked this run to stop."""
        with privileged_connection() as cur:
            cur.execute(
                "select (cancel_requested_at is not null) as requested "
                "from public.job_runs where id = %s",
                (run_id,),
            )
            row = cur.fetchone()
            return bool(row["requested"]) if row is not None else False

    def request_cancel(self, run_id: str, *, requested_by: str | None) -> dict[str, Any] | None:
        """Record an operator's cancellation request.

        Cooperative by design: this sets a flag, it does not kill anything. A running
        job stops at its next ``ctx.checkpoint()``; a queued one never starts. A job
        that is already terminal is left alone (the ``where`` clause), because
        "cancelled" would overwrite a real outcome with a fiction.

        Called from the API on the privileged connection AFTER the router's
        permission check - the same pattern as the audit worker's status writes,
        since neither table carries an authenticated UPDATE policy.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.job_runs set cancel_requested_at = now(), cancel_requested_by = %s "
                "where id = %s and status in ('queued', 'running') "
                f"returning {_RUN_COLUMNS}",
                (requested_by, run_id),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    # --- terminal transitions -------------------------------------------------
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
    ) -> dict[str, Any] | None:
        """Write the terminal state. The DB check constraints are the backstop here:
        a ``degraded``/``blocked`` row without a reason, or a ``failed`` row without
        an error_type, is rejected by Postgres even if this layer is bypassed."""
        with privileged_connection() as cur:
            cur.execute(
                "update public.job_runs set status = %s::public.job_status, finished_at = now(), "
                "detail = %s, reason = %s, reason_code = %s, error_type = %s, error_message = %s, "
                "cost_usd = %s, result = %s, scheduled_for = null "
                "where id = %s and finished_at is null "
                f"returning {_RUN_COLUMNS}",
                (
                    status,
                    detail,
                    reason,
                    reason_code,
                    error_type,
                    error_message,
                    cost_usd,
                    Jsonb(result) if result is not None else None,
                    run_id,
                ),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def defer(self, run_id: str, *, scheduled_for_seconds: float, detail: str) -> None:
        """Put a run back in the queue with a due time (retry backoff, or a cap wait).

        Leaves ``attempt`` untouched: a deferral is not an attempt. Only ``start()``
        increments the counter, so a run held off by a concurrency cap cannot silently
        consume its retry budget while doing no work.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.job_runs set status = 'queued', "
                "scheduled_for = now() + make_interval(secs => %s), detail = %s "
                "where id = %s and finished_at is null",
                (float(scheduled_for_seconds), detail, run_id),
            )

    def dead_letter(
        self,
        run_id: str,
        *,
        payload: dict[str, Any],
        reason_code: str,
        error_type: str,
        error_message: str,
        traceback: str,
    ) -> str | None:
        """Copy a dead run into the DLQ with enough to replay it.

        The columns are copied from ``job_runs`` inside the INSERT rather than passed
        in, so a dead letter cannot disagree with the run it describes. ``payload`` is
        supplied by the runner because it is the only layer that sees the call's args.
        """
        with privileged_connection() as cur:
            cur.execute(
                "insert into public.job_dead_letters ("
                "  run_id, job_name, task, queue, correlation_id, idempotency_key,"
                "  client_id, client_name, scope_type, scope_id, payload, attempts,"
                "  reason_code, error_type, error_message, traceback, first_failed_at"
                ") select r.id, r.job_name, r.task, r.queue, r.correlation_id, r.idempotency_key,"
                "  r.client_id, r.client_name, r.scope_type, r.scope_id, %s, r.attempt,"
                "  %s, %s, %s, %s, r.started_at "
                "from public.job_runs r where r.id = %s "
                "returning id",
                (Jsonb(payload), reason_code, error_type, error_message, traceback, run_id),
            )
            row = cur.fetchone()
            return str(row["id"]) if row is not None else None

    # --- the reaper -----------------------------------------------------------
    def reap_stale_runs(self) -> _Rows:
        """Fail every ``running`` row whose heartbeat has gone quiet past its budget.

        A worker killed by the OOM reaper, a host reboot, or a `docker compose down`
        never gets to write a terminal state. Without this sweep those rows stay
        ``running`` forever, and because ``start()`` counts ``running`` rows against
        the per-client cap, a handful of them permanently reduce a client's
        throughput to zero. The staleness budget is per queue - a browser job is
        allowed two hours of silence, an interactive one sixty seconds.

        Runs per queue rather than in one statement so each queue's threshold is
        explicit and testable rather than buried in a CASE.
        """
        reaped: _Rows = []
        with privileged_connection() as cur:
            for queue in JobQueue:
                cur.execute(
                    "update public.job_runs set status = 'failed', finished_at = now(), "
                    "error_type = 'JobHeartbeatLost', reason_code = 'heartbeat_lost', "
                    "error_message = 'the worker stopped reporting before writing an outcome', "
                    "detail = 'reaped: no heartbeat for longer than this queue allows' "
                    "where status = 'running' and queue = %s::public.job_queue "
                    "and coalesce(heartbeat_at, started_at, created_at) "
                    "    < now() - make_interval(secs => %s) "
                    f"returning {_RUN_COLUMNS}",
                    (queue.value, float(stale_after_seconds(queue))),
                )
                reaped.extend(dict(row) for row in cur.fetchall())
        return reaped

    # --- the dead-letter queue's human decisions ------------------------------
    def get_dead_letter(self, dead_letter_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.job_dead_letters where id = %s", (dead_letter_id,)
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def mark_replayed(
        self, dead_letter_id: str, *, replayed_run_id: str | None, replayed_by: str | None
    ) -> dict[str, Any] | None:
        """Record that a human re-ran a dead letter.

        Scoped to rows that are still open, so a double-click cannot enqueue the work
        twice - the second call returns ``None`` and the router refuses. That matters
        here more than usual: replaying is the one operator action that deliberately
        re-runs something which has already spent money once.
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.job_dead_letters set replayed_at = now(), "
                "replayed_run_id = %s, replayed_by = %s "
                "where id = %s and replayed_at is null and resolved_at is null "
                "returning *",
                (replayed_run_id, replayed_by, dead_letter_id),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def resolve_dead_letter(
        self, dead_letter_id: str, *, resolution: str, resolved_by: str | None
    ) -> dict[str, Any] | None:
        """Close a dead letter with a written decision.

        ``resolution`` is required by a CHECK constraint as well as here: a queue
        closed with no reasons written is a graveyard, and the next person cannot
        tell "we fixed it" from "we gave up".
        """
        with privileged_connection() as cur:
            cur.execute(
                "update public.job_dead_letters set resolved_at = now(), "
                "resolved_by = %s, resolution = %s "
                "where id = %s and resolved_at is null "
                "returning *",
                (resolved_by, resolution, dead_letter_id),
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    # --- reads the worker itself needs ---------------------------------------
    def get(self, run_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(f"select {_RUN_COLUMNS} from public.job_runs where id = %s", (run_id,))
            row = cur.fetchone()
            return dict(row) if row is not None else None


class JobRunsRepo:
    """The RLS-scoped READ seam for the operator surface.

    Reads only. Every mutation on these tables is a server action (the runner, the
    reaper, or a router that has already checked a permission and then writes on the
    privileged store) - which is why there is no authenticated write policy to scope.
    """

    def __init__(self, user_id: str) -> None:
        self._user_id = user_id

    def list_runs(
        self,
        *,
        status: str | None = None,
        job_name: str | None = None,
        client_id: str | None = None,
        correlation_id: str | None = None,
        needs_attention: bool = False,
        limit: int = 50,
        offset: int = 0,
    ) -> _Rows:
        """The runs board. ``needs_attention`` is the default operator view: every
        terminal run that was not a clean success, newest first."""
        query = [f"select {_RUN_COLUMNS} from public.job_runs where true"]
        params: list[Any] = []
        if status is not None:
            query.append("and status = %s::public.job_status")
            params.append(status)
        if needs_attention:
            query.append("and status in ('degraded', 'blocked', 'failed')")
        if job_name is not None:
            query.append("and job_name = %s")
            params.append(job_name)
        if client_id is not None:
            query.append("and client_id = %s")
            params.append(client_id)
        if correlation_id is not None:
            query.append("and correlation_id = %s")
            params.append(correlation_id)
        query.append("order by created_at desc, id limit %s offset %s")
        params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(" ".join(query), params)
            return cur.fetchall()

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute(f"select {_RUN_COLUMNS} from public.job_runs where id = %s", (run_id,))
            return cur.fetchone()

    def get_run_by_celery_task_id(
        self, task_id: str, *, job_name: str | None = None
    ) -> dict[str, Any] | None:
        """The run a given Celery message became - the ENQUEUE-time handle.

        A router that enqueues returns the Celery message id immediately, and the row
        now carries that id from the moment the work is ACCEPTED (``enqueue`` writes it
        and supplies the task id), so a status endpoint keyed by that handle finds a
        queued run rather than nothing. A missing row therefore means the send itself
        never landed - it no longer means "waiting for a worker", which is a state the
        row can now express on its own. ``job_name`` scopes the lookup to one logical
        job, so a caller
        mapping the row into a module-specific response shape can never be handed
        some other module's run. Newest first, defensively: the id is unique per
        send in practice, but nothing at the database enforces that.
        """
        query = f"select {_RUN_COLUMNS} from public.job_runs where celery_task_id = %s"
        params: list[Any] = [task_id]
        if job_name is not None:
            query += " and job_name = %s"
            params.append(job_name)
        query += " order by created_at desc limit 1"
        with rls_connection(self._user_id) as cur:
            cur.execute(query, params)
            return cur.fetchone()

    def get_run_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        """The run that owns a unit of work (the partial unique index -> at most one)."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                f"select {_RUN_COLUMNS} from public.job_runs where idempotency_key = %s",
                (key,),
            )
            return cur.fetchone()

    def list_dead_letters(self, *, open_only: bool = True, limit: int = 50, offset: int = 0) -> _Rows:
        """The DLQ. Oldest first when open: the longest-unresolved lost work is the
        most urgent, which is the opposite of every other feed in the product."""
        query = ["select * from public.job_dead_letters where true"]
        params: list[Any] = []
        if open_only:
            query.append("and resolved_at is null and replayed_at is null")
            query.append("order by dead_lettered_at asc, id")
        else:
            query.append("order by dead_lettered_at desc, id")
        query.append("limit %s offset %s")
        params += [limit, offset]
        with rls_connection(self._user_id) as cur:
            cur.execute(" ".join(query), params)
            return cur.fetchall()

    def in_flight_by_client(self) -> _Rows:
        """Current in-flight counts per (client, queue) - what the cap is acting on."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select client_id, client_name, queue, count(*) as running "
                "from public.job_runs where status = 'running' "
                "group by client_id, client_name, queue order by running desc"
            )
            return cur.fetchall()


    def get_dead_letter(self, dead_letter_id: str) -> dict[str, Any] | None:
        with rls_connection(self._user_id) as cur:
            cur.execute("select * from public.job_dead_letters where id = %s", (dead_letter_id,))
            return cur.fetchone()

    def count_open_dead_letters(self) -> int:
        """How many units of lost work are still awaiting a human decision."""
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select count(*) as n from public.job_dead_letters "
                "where resolved_at is null and replayed_at is null"
            )
            row = cur.fetchone()
            return int(row["n"]) if row is not None else 0

    def counts_by_status(self, *, since_hours: int = 24) -> _Rows:
        """The operator's headline: how many runs landed in each state recently.

        Grouped on the canonical vocabulary, so `degraded` is visible as its own
        number rather than folded into a success count - which is the entire point
        of having introduced it.
        """
        with rls_connection(self._user_id) as cur:
            cur.execute(
                "select status, count(*) as runs, coalesce(sum(cost_usd), 0) as cost_usd "
                "from public.job_runs "
                "where created_at >= now() - make_interval(hours => %s) "
                "group by status order by status",
                (since_hours,),
            )
            return cur.fetchall()


def get_job_runs_repo(user: CurrentUserDep) -> JobRunsRepo:
    """Dependency: a repo bound to the caller's verified user id (RLS-scoped)."""
    return JobRunsRepo(user.id)


JobRunsRepoDep = Annotated[JobRunsRepo, Depends(get_job_runs_repo)]

_store = JobRunsStore()


def job_runs_store() -> JobRunsStore:
    """The process-wide store singleton (it holds no state; the pool does)."""
    return _store
