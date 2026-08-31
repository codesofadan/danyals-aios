"""The automation dispatcher: one beat tick, many editable schedules.

WHY THIS EXISTS. Celery beat reads its schedule when the process starts, so a static
`beat_schedule` cannot be edited, paused or extended without a deploy - and the fourteen
entries this platform had were switched off wholesale on 2026-08-19 rather than
individually, because switching them off individually was not possible.

So beat now carries one business entry: this tick. It reads due rows from
`public.automations`, which an admin can create, re-time, pause and audit from the
dashboard. That is not a second scheduler - it is the pattern this codebase already
uses twice (`dispatch_context` claims due rows from `context_dirty`,
`dispatch_rank_checks` claims due subscriptions FOR UPDATE SKIP LOCKED) - with the
schedule itself made editable.

NOT ITSELF AN @aios_job. A minute-by-minute tick under the job contract would write
~1,440 ledger rows a day into the very table it exists to populate, burying the runs an
operator actually wants to read. It follows `reap_stale_job_runs`, which is a plain
task for the same reason. What it ENQUEUES is fully under the contract.

DUPLICATE EXECUTION IS GUARDED THREE TIMES, deliberately, because "it fired twice"
means a client was billed twice:

  1. an advisory lock, so two overlapping ticks do not both dispatch;
  2. FOR UPDATE SKIP LOCKED + advancing `next_due_at` in the claim transaction, so a
     tick that gets past the lock still cannot re-claim a row another tick took;
  3. a per-fire idempotency key (`automation:{id}:{scheduled_ts}`), resolved by the
     job contract's unique index - so even a duplicate ENQUEUE collapses onto one run.

Any one of them would usually be enough. Together they make a double-charge require
three independent failures.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.db.automations_repo import AutomationsStore, automations_store
from app.db.database import privileged_connection
from app.jobs.automation_capabilities import capability
from app.logging_setup import get_logger

logger = get_logger("workers.automations")

#: The advisory-lock key for the dispatcher, in the R6 overlap-lock style used by
#: local_seo and rank_tracker. Transaction-scoped, so it is released by COMMIT
#: whatever happens.
_DISPATCH_LOCK_KEY = 0x41_55_54_4F  # 'AUTO'


def _try_lock() -> bool:
    """Take the dispatcher lock, or report that another tick already holds it."""
    with privileged_connection() as cur:
        cur.execute("select pg_try_advisory_xact_lock(%s) as got", (_DISPATCH_LOCK_KEY,))
        row = cur.fetchone()
        return bool(row and row["got"])


def _client_ids(params: dict[str, Any]) -> list[str]:
    raw = params.get("clientIds") or params.get("client_ids") or []
    return [str(c) for c in raw if c]


def execute_dispatch(
    store: AutomationsStore,
    *,
    enqueue: Any,
    notify: Any,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The pure-ish core: claim what is due, enqueue it, report failures.

    ``enqueue`` and ``notify`` are injected so this is testable without a broker or a
    mail provider - the seam every other worker in this codebase uses.
    """
    at = now or datetime.now(UTC)
    dispatched = 0
    skipped: list[str] = []

    for row in store.claim_due(now=at):
        automation_id = str(row["id"])
        cap = capability(str(row["kind"]))
        if cap is None:
            # The capability was removed or renamed under a live automation. Firing
            # nothing and saying nothing is how scheduled work silently stops; this
            # is at least visible in the logs and leaves the row for an operator.
            logger.warning(
                "automation_unknown_capability",
                automation=automation_id, kind=row["kind"], name=row["name"],
            )
            skipped.append(automation_id)
            continue

        # The SCHEDULED time, not the dispatch time, so a retried tick a few seconds
        # later derives the same key and collapses onto the same run.
        stamp = at.strftime("%Y-%m-%dT%H:%M")
        params = dict(row["params"] or {})
        targets = _client_ids(params) if cap.scope == "client" else [None]

        last_run_id: str | None = None
        for client_id in targets:
            key = f"automation:{automation_id}:{stamp}" + (f":{client_id}" if client_id else "")
            try:
                if client_id:
                    enqueue(
                        cap.task,
                        client_id,
                        correlation_id=automation_id,
                        idempotency_key=key,
                    )
                else:
                    enqueue(cap.task, correlation_id=automation_id, idempotency_key=key)
                last_run_id = key
                dispatched += 1
            except Exception as exc:
                # One automation's failure to enqueue must not stop the rest of the
                # tick: the others are due too, and a broker blip should cost one
                # window rather than all of them.
                logger.warning(
                    "automation_enqueue_failed",
                    automation=automation_id, kind=cap.kind,
                    error=f"{type(exc).__name__}: {exc}",
                )

        if last_run_id is not None:
            _record_latest_run(store, automation_id, last_run_id)

    notified = _notify_failures(store, notify)
    if dispatched or notified:
        logger.info("automations_dispatched", dispatched=dispatched, notified=notified)
    return {"dispatched": dispatched, "notified": notified, "skipped": len(skipped)}


def _record_latest_run(store: AutomationsStore, automation_id: str, key: str) -> None:
    """Point the automation at the run its last fire produced.

    The key is what identifies the unit of work, so the run is looked up by it - the
    row exists synchronously because ``enqueue`` writes it.
    """
    try:
        from app.db.job_runs_repo import job_runs_store

        run = job_runs_store().get_by_idempotency_key(key)
        store.record_run(automation_id, str(run["id"]) if run else None)
    except Exception:
        logger.warning("automation_run_link_failed", automation=automation_id)


def _notify_failures(store: AutomationsStore, notify: Any) -> int:
    """Tell someone once when an automation's latest run went badly.

    At-most-once by `last_notified_run_id`: a failing automation reports the first
    time, not every minute until it is fixed - which is how a real alert becomes
    noise people filter out.
    """
    sent = 0
    try:
        pending = store.pending_failure_notices()
    except Exception:
        logger.warning("automation_failure_scan_failed")
        return 0

    for row in pending:
        run_id = str(row["last_run_id"])
        detail = str(row.get("reason") or row.get("error_message") or "").strip()
        try:
            notify(
                kind="automation_failed",
                title=f"Automation '{row['name']}' {row['status']}",
                body=detail or f"The {row['kind']} automation did not complete.",
            )
            sent += 1
        except Exception:
            logger.warning("automation_notify_failed", automation=str(row["id"]))
        finally:
            # Marked either way. A notification channel that is down must not turn
            # into an unbounded retry loop against every failing automation.
            store.mark_notified(str(row["id"]), run_id)
    return sent


# --------------------------------------------------------------------------- #
# Celery entry point (thin; the app imports come last, per the worker template).
# --------------------------------------------------------------------------- #
from app.jobs.celery_task import enqueue as enqueue_job  # noqa: E402
from app.services.notifications import notify_leads_sync  # noqa: E402
from workers.celery_app import celery_app  # noqa: E402


def _notify(*, kind: str, title: str, body: str) -> None:
    notify_leads_sync(kind, title, body)


@celery_app.task(name="dispatch_automations")  # type: ignore[untyped-decorator]
def dispatch_automations() -> dict[str, Any]:
    """Beat tick: fire whatever is due. Never raises - a scheduler that dies on one
    bad row stops every automation, which is worse than any single failure."""
    try:
        if not _try_lock():
            return {"dispatched": 0, "notified": 0, "skipped": 0, "detail": "another tick holds the lock"}
        return execute_dispatch(automations_store(), enqueue=enqueue_job, notify=_notify)
    except Exception as exc:
        logger.warning("automation_dispatch_failed", error=f"{type(exc).__name__}: {exc}")
        return {"dispatched": 0, "notified": 0, "skipped": 0, "error": type(exc).__name__}
