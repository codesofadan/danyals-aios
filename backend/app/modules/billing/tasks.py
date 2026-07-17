"""Billing worker: the nightly past-due sweep.

One task, ``mark_past_due``, built on the never-stuck / never-re-raise / idempotent
worker template (``workers.tasks.audit`` / ``app.modules.keyword_research.tasks``):
with ``task_acks_late`` a raised exception would redeliver the job, so the task ACKs
and returns a small result dict.

It flips every ``open`` invoice whose ``due_date`` has passed (plus an optional grace
window) to ``past_due``, which is what feeds the ``Past due`` KPI. This is the ONE
automatic status transition in the module - and it is not a payment action: it just
notices that a date went by. There is still no gateway, no dunning, no reconciliation.

Why a beat sweep rather than deriving past-due on read: the status is a real,
queryable fact the ledger holds (it drives the KPI count, the invoice filters and the
workspace tone), and ``0043``'s state machine treats it as a first-class state. A
read-time derivation would leave the stored status lying, and every consumer would
have to re-derive it identically or disagree.

Concurrency: the flip is a SINGLE ``update ... where status = 'open'`` statement, so
Postgres's row locks serialise two overlapping beat ticks by themselves - the loser
re-evaluates the predicate and matches zero rows. That is why no advisory/overlap lock
is taken (the codebase defines none; the context dispatcher uses FOR UPDATE SKIP
LOCKED claims for the same reason). ``service_role`` bypasses RLS but NOT triggers, so
``invoices_guard_update`` still vets the flip - ``open -> past_due`` is legal, so it
passes.

The Celery app is imported LAST (after the pure core), per the worker template, so
importing this module stays Celery-free at the API edge.
"""

from __future__ import annotations

from typing import Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.billing.repo import ServiceBillingStore, service_billing_store

logger = get_logger("workers.billing")


def execute_mark_past_due(store: ServiceBillingStore, settings: Settings) -> dict[str, Any]:
    """Flip overdue OPEN invoices to ``past_due``. Never raises.

    Idempotent: the ``where status = 'open'`` predicate means a re-run finds nothing
    left to flip, so a Celery redelivery is a no-op rather than a double-transition.
    No paid provider is involved (this module calls nothing external), so there is no
    cost gate to pre-check - the only failure mode is the DB being unreachable, which
    comes back as an ``error`` result instead of a redelivery.
    """
    try:
        flipped = store.flip_overdue_open_invoices(
            grace_days=int(settings.billing_past_due_grace_days)
        )
    except Exception:
        logger.exception("mark_past_due_failed")
        return {"state": "error", "flipped": 0}
    if flipped:
        logger.info("mark_past_due_done", flipped=flipped)
    return {"state": "ok", "flipped": flipped}


# --------------------------------------------------------------------------- #
# Celery entry point (thin; import the app after the pure core).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="mark_past_due")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def mark_past_due() -> dict[str, Any]:
    """BEAT task: flip every overdue ``open`` invoice to ``past_due``.

    Wraps the pure core in a guard so the task NEVER re-raises (acks_late-safe); a
    failure is returned as an ``error`` result dict."""
    try:
        return execute_mark_past_due(service_billing_store(), get_settings())
    except Exception:
        logger.exception("mark_past_due_task_failed")
        return {"state": "error", "flipped": 0}
