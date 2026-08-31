"""The nightly Postgres snapshot, as a job the platform can actually run.

WHY THIS MODULE EXISTS. ``app/services/backups.py`` has taken a real ``pg_dump`` since
7G-1, but the only thing that ever called it was ``POST /backups/run`` - a human pressing
a button. Meanwhile ``backup_config.nightly_enabled`` defaults to TRUE and the config
panel renders "Nightly 02:00 UTC" with a next-backup countdown, so the platform CLAIMED a
nightly backup that no code path on the system could produce. That is the fake-success
defect class exactly: a promise rendered to an operator with no mechanism behind it.

THIS DOES NOT SWITCH CRON ON. Beat is parked platform-wide by the owner's instruction
(2026-08-19) and ``celery_app.conf.beat_schedule`` stays ``{}``. The entry for this task
goes into the PRESERVED table (``_BEAT_SCHEDULE_DISABLED``) so the job is correct the
moment beat is switched back on, and while it is parked the manual door is
``POST /backups/run`` (owner/admin), which is how a snapshot is taken today.

WHY THE WORKER NEEDS ITS OWN STORE. The service writes its ledger row through
``BackupsRepo``, which is bound to the requesting user and goes out over
``rls_connection``. A beat tick has no user, and 0026's insert policy admits only
``owner``/``admin``, so an identity-less RLS write would be refused. The worker therefore
writes on ``privileged_connection`` (service_role, BYPASSRLS) - the same seam
``ServiceReportsStore`` uses for the other beat jobs, and the same
privileged-store-beside-the-RLS-repo shape. That is safe HERE specifically because
neither ``backup_snapshots`` nor ``backup_config`` carries a ``tasks_guard_*`` trigger
that reads ``auth.uid()`` (db/migrations/0026_backups.sql: the only trigger on each is
``set_updated_at``). Do not copy this seam to a table that does have one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg import sql

from app.config import get_settings
from app.db.database import privileged_connection
from app.logging_setup import get_logger

logger = get_logger("workers.backups")

# The beat entry key MUST match workers/celery_app.py's ``_BEAT_SCHEDULE_DISABLED``, so
# the Reports "Scheduled jobs" panel's last-run join lines up; the task name is what
# beat dispatches.
_BACKUP_JOB = "nightly-backup"
_BACKUP_TASK = "run_nightly_backup"

# pg_dump dumps the DATABASE. 0026 also describes a "Full (DB + files)" scope for a
# weekly/manual run, but nothing in the service copies the file-artifacts volume yet, so
# a nightly row that claimed "Full" would be a lie in the ledger the restore path reads.
_NIGHTLY_SCOPE = "Database"
# 0026's snapshot_type enum is capitalised ('Nightly' | 'Manual'). Recording an automatic
# run as 'Manual' would make the ledger unable to answer "did last night's backup run",
# which is the only question this task exists to answer.
_NIGHTLY_TYPE = "Nightly"


class ConfigReader(Protocol):
    """The one read the core needs before it spends half an hour on a dump."""

    def get_config(self) -> dict[str, Any] | None: ...


class SnapshotRunner(Protocol):
    """The slice of ``BackupService`` the core drives (kept narrow so the unit tests
    need no subprocess, no artifact root and no DB)."""

    def run_snapshot(self, *, snap_type: str, scope: str) -> dict[str, Any]: ...


class RunRecorder(Protocol):
    """``ServiceReportsStore.record_run`` - the scheduled-jobs heartbeat ledger."""

    def record_run(self, *, job_name: str, task: str, status: str, detail: str) -> str: ...


# --------------------------------------------------------------------------- #
# The privileged store (the worker's write path; see the module docstring)
# --------------------------------------------------------------------------- #
class PrivilegedBackupsStore:
    """The four ``_SnapshotWriter`` methods ``BackupService`` needs, on the privileged
    pool instead of the caller's RLS connection.

    Deliberately a sibling of ``BackupsRepo`` rather than a subclass: the repo takes the
    connection seam from ``self._user_id`` in every method body, so there is nothing to
    override, and inventing a synthetic user id to pass it would put a user that does not
    exist into ``auth.uid()`` for the whole transaction.
    """

    def get_snapshot(self, snapshot_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.backup_snapshots where id = %s limit 1", (snapshot_id,)
            )
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def insert_snapshot(self, row: dict[str, Any]) -> dict[str, Any]:
        # Column list comes from the service's own server-built dict, never from request
        # input, and is quoted through Identifier; every VALUE is a bound param (the
        # impersonation-review SQL mandate that app/db/backups_repo.py follows).
        cols = list(row.keys())
        stmt = sql.SQL(
            "insert into public.backup_snapshots ({cols}) values ({vals}) returning *"
        ).format(
            cols=sql.SQL(", ").join(map(sql.Identifier, cols)),
            vals=sql.SQL(", ").join([sql.Placeholder()] * len(cols)),
        )
        with privileged_connection() as cur:
            cur.execute(stmt, list(row.values()))
            inserted = cur.fetchone()
            return dict(inserted) if inserted is not None else dict(row)

    def get_config(self) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute("select * from public.backup_config where id = 1 limit 1")
            row = cur.fetchone()
            return dict(row) if row is not None else None

    def update_config(self, changes: dict[str, Any]) -> dict[str, Any] | None:
        if not changes:
            return self.get_config()
        cols = list(changes.keys())
        stmt = sql.SQL(
            "insert into public.backup_config ({cols}) values ({vals}) "
            "on conflict (id) do update set {sets} returning *"
        ).format(
            cols=sql.SQL(", ").join([sql.Identifier("id"), *(sql.Identifier(c) for c in cols)]),
            vals=sql.SQL(", ").join([sql.Literal(1), *([sql.Placeholder()] * len(cols))]),
            sets=sql.SQL(", ").join(
                sql.SQL("{col} = excluded.{col}").format(col=sql.Identifier(c)) for c in cols
            ),
        )
        with privileged_connection() as cur:
            cur.execute(stmt, list(changes.values()))
            row = cur.fetchone()
            return dict(row) if row is not None else None


# --------------------------------------------------------------------------- #
# Pure core (no Celery, no DB, no subprocess - injectable seams only)
# --------------------------------------------------------------------------- #
def execute_nightly_backup(
    config_reader: ConfigReader,
    service: SnapshotRunner,
    *,
    offsite_available: bool,
    recorder: RunRecorder | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Take tonight's snapshot and describe what actually happened. Never raises.

    Returns a small verdict dict the Celery entry point maps 1:1 onto a ``JobOutcome``,
    so the honesty rules are decided HERE (where they are unit-testable) rather than in a
    task body that needs a broker to exercise:

    * ``completed`` only when the ledger row came back ``success`` - a dump that produced
      no artifact records a ``failed`` row, and reporting that as a completed backup is
      the precise defect this module was written to remove.
    * ``degraded`` when the local snapshot succeeded but an offsite copy the operator
      switched ON did not happen - a backup that exists only on the box being backed up
      is not the backup the config panel promises.
    * ``blocked`` when nightly backups are switched off. Not an error and not a success:
      a gate refused, and the operator surface should be able to count it.

    ``offsite_available`` is passed in rather than sniffed off the service because the
    service's ``_offsite`` is private and, more importantly, because the two ways an
    offsite copy fails to happen (no B2 credentials vs. an upload that errored) need
    different words in front of an operator.
    """
    now = now or datetime.now(UTC)
    try:
        config = config_reader.get_config() or {}
    except Exception as exc:
        # A config read that cannot reach Postgres is NOT "nightly disabled" and must not
        # silently skip the backup: report it as the failure it is.
        logger.error("nightly_backup.config_unreadable", error=type(exc).__name__)
        verdict = {
            "state": "failed",
            "error_type": type(exc).__name__,
            "detail": "could not read the backup config, so no snapshot was attempted",
            "snapshot_id": None,
            "status": "not_attempted",
            "size_bytes": 0,
            "offsite_synced": False,
        }
        _safe_record(recorder, status="error", detail=str(verdict["detail"]))
        return verdict

    # NOT NULL default true in 0026, and BackupConfigResponse.from_row(None) also renders
    # nightlyOn=True, so an absent row means enabled here too - the task and the panel
    # must not disagree about whether tonight's backup was supposed to happen.
    if not bool(config.get("nightly_enabled", True)):
        detail = "nightly backups are switched off in the backups config"
        logger.info("nightly_backup.disabled")
        _safe_record(recorder, status="skipped", detail=detail)
        return {
            "state": "blocked",
            "reason_code": "nightly_backups_disabled",
            "reason": detail,
            "detail": detail,
            "snapshot_id": None,
            "status": "not_attempted",
            "size_bytes": 0,
            "offsite_synced": False,
        }

    row = service.run_snapshot(snap_type=_NIGHTLY_TYPE, scope=_NIGHTLY_SCOPE)
    snapshot_id = str(row.get("id") or "") or None
    row_status = str(row.get("status") or "")
    size_bytes = int(row.get("size_bytes") or 0)
    offsite_synced = bool(row.get("offsite_synced"))
    base: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "status": row_status,
        "size_bytes": size_bytes,
        "offsite_synced": offsite_synced,
        "started_at": now.isoformat(),
    }

    if row_status != "success":
        detail = (
            f"pg_dump produced no artifact; snapshot {snapshot_id or 'unrecorded'} "
            f"is recorded as {row_status or 'unknown'}"
        )
        logger.warning("nightly_backup.failed", snapshot_id=snapshot_id, status=row_status)
        _safe_record(recorder, status="error", detail=detail)
        return {**base, "state": "failed", "error_type": "BackupSnapshotFailed", "detail": detail}

    offsite_wanted = bool(config.get("offsite_enabled"))
    if offsite_wanted and not offsite_synced:
        # Two different causes, two different sentences - "offsite not synced" alone
        # tells the operator nothing about which one to go and fix.
        reason = (
            "the snapshot was written locally but no offsite copy was made: offsite backup "
            "is enabled and no Backblaze B2 credentials are configured"
            if not offsite_available
            else "the snapshot was written locally but the offsite upload to Backblaze B2 failed"
        )
        logger.warning("nightly_backup.offsite_missing", offsite_available=offsite_available)
        _safe_record(recorder, status="degraded", detail=reason)
        return {
            **base,
            "state": "degraded",
            "reason_code": (
                "offsite_not_configured" if not offsite_available else "offsite_upload_failed"
            ),
            "reason": reason,
            "detail": reason,
        }

    detail = f"snapshot {snapshot_id or ''} written ({size_bytes} bytes)".strip()
    if offsite_wanted:
        detail += ", copied offsite"
    logger.info("nightly_backup.done", snapshot_id=snapshot_id, size_bytes=size_bytes)
    _safe_record(recorder, status="ok", detail=detail)
    return {**base, "state": "completed", "detail": detail}


def _safe_record(
    recorder: RunRecorder | None, *, status: str, detail: str
) -> None:
    """Append the scheduled-jobs heartbeat. A ledger hiccup must never turn a backup that
    really happened into a failed job - the snapshot ledger is the authoritative record;
    this row only feeds the Reports panel's last-run column."""
    if recorder is None:
        return
    try:
        recorder.record_run(job_name=_BACKUP_JOB, task=_BACKUP_TASK, status=status, detail=detail)
    except Exception:
        logger.warning("job_run_record_failed", job_name=_BACKUP_JOB)


# --------------------------------------------------------------------------- #
# Celery entry point (thin; the app is imported after the pure core, per the
# worker template, so the API edge can import the core without a broker in the tree).
# --------------------------------------------------------------------------- #
from app.db.reports_repo import service_reports_store  # noqa: E402
from app.jobs import JobContext, JobOutcome  # noqa: E402
from app.jobs.celery_task import aios_job  # noqa: E402
from app.jobs.status import JobQueue  # noqa: E402
from app.services.backups import build_backup_service  # noqa: E402
from integrations.b2 import offsite_store_from_settings  # noqa: E402


@aios_job(
    name=_BACKUP_TASK,
    job_name="backups.nightly",
    queue=JobQueue.LONG,
    # max_attempts=1 ON PURPOSE. A retry here re-runs a FULL pg_dump. The service already
    # converts every failure it can see - no artifact root, no pg_dump binary, a non-zero
    # exit, its own hard timeout - into a recorded `failed` ledger row rather than an
    # exception, so a second attempt would not be retrying a transient fault; it would be
    # doubling the I/O on a box that just failed a dump. A missed night is recovered by
    # the next tick or by POST /backups/run, which is cheaper than that.
    max_attempts=1,
    # LONG's hard limit is 1800s and its soft limit 1740s, while the service's own
    # backup_timeout_seconds also defaults to 1800 - so on a dump that genuinely runs to
    # the wall, Celery's SoftTimeLimitExceeded lands ~60s BEFORE pg_dump's own timeout.
    # That ordering is the safe one (the job records an honest terminal state instead of
    # being SIGKILLed mid-write), but it does mean BACKUP_TIMEOUT_SECONDS above ~1700 is
    # not actually reachable from beat. Raising it needs a queue with a longer budget,
    # not a bigger number in Settings.
    scope_type="workspace",
)
def run_nightly_backup(ctx: JobContext) -> JobOutcome:
    """BEAT job (nightly): one Postgres snapshot, recorded honestly either way.

    Un-keyed (no ``target``): this is a platform-wide sweep, not per-client work, and a
    per-night idempotency key would suppress the manual re-run that recovers a night the
    first attempt failed.
    """
    settings = get_settings()
    store = PrivilegedBackupsStore()
    verdict = execute_nightly_backup(
        store,
        build_backup_service(store, settings),
        offsite_available=offsite_store_from_settings(settings) is not None,
        recorder=service_reports_store(),
    )
    state = str(verdict.get("state"))
    detail = str(verdict.get("detail") or "")
    if state == "blocked":
        return JobOutcome.blocked(
            str(verdict["reason_code"]), str(verdict["reason"]), result=verdict
        )
    if state == "degraded":
        return JobOutcome.degraded(
            str(verdict["reason_code"]), str(verdict["reason"]), detail=detail, result=verdict
        )
    if state == "failed":
        return JobOutcome.failed(
            str(verdict.get("error_type") or "BackupSnapshotFailed"),
            detail,
            detail=detail,
            result=verdict,
        )
    return JobOutcome.completed(detail, result=verdict)
