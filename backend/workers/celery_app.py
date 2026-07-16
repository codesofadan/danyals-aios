"""Celery application for AIOS background jobs.

Broker and result backend live on separate Redis logical DBs from the app cache
(broker db 1, results db 2; see ``Settings``) so a cache FLUSHDB can never wipe
queued jobs. Tasks are registered via ``include=[...]`` (deterministic) rather
than ``autodiscover_tasks``, which would look for a non-existent
``workers.tasks.tasks`` module and silently register nothing.
"""

from __future__ import annotations

from celery import Celery

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "aios",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "workers.tasks.ping",
        "workers.tasks.audit",
        "workers.tasks.content",
        "workers.tasks.context",
        "workers.tasks.context_reconcile",
        # 7B-3: the Web 2.0 publish drivers (web2_write / web2_publish) + the backlink/
        # citation monitoring sweep (monitor_offpage). All are event-driven plain tasks
        # (the publish is enqueued on a lead's approval; monitoring is enqueued per
        # client), so no beat entry / R6 overlap-lock is needed.
        "workers.tasks.offpage",
        # Part 8: the keyword-research worker (research_keywords). Event-driven (enqueued
        # per research request), so no beat entry / overlap-lock is needed.
        "app.modules.keyword_research.tasks",
        # Part 8: the local-SEO workers. refresh_local_ranks IS beat-driven (see the
        # beat_schedule below) and therefore DOES take the R6 overlap lock;
        # sync_gbp_profile is event-driven (enqueued per profile).
        "app.modules.local_seo.tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    timezone="UTC",
    enable_utc=True,
    broker_connection_retry_on_startup=True,
    task_time_limit=1800,
    task_soft_time_limit=1740,
    result_expires=3600,
    # INVARIANT: with task_acks_late=True on a Redis broker, visibility_timeout
    # MUST be >= the longest hard task_time_limit. Otherwise a job that runs
    # longer than the visibility window is re-delivered to a SECOND worker and
    # RUNS TWICE (double API spend). When real long jobs land later, raise
    # visibility_timeout and task_time_limit together, keeping this invariant.
    broker_transport_options={"visibility_timeout": 3600},
)

# Beat schedule (P6B-7): the context-compaction dispatcher runs every debounce
# window; it CLAIMS due context_dirty rows (FOR UPDATE SKIP LOCKED) and fans out a
# compact_context task per claim. This is CONFIG ONLY - a beat process must be
# started separately (celery -A workers.celery_app beat); no beat runs here. The
# visibility_timeout >= task_time_limit invariant above still holds for these tasks.
#
# The reconcile sweep (P6B-9) runs at a much slower cadence (default hourly): it
# walks every entity with vectors and detects/logs (optionally repairs) ledger-vs-
# store drift. It is a safety net, not a hot path - Postgres is the source of truth
# and sync_vectors keeps the two in step per fold - so it deliberately runs rarely.
celery_app.conf.beat_schedule = {
    "dispatch-context": {
        "task": "dispatch_context",
        "schedule": float(settings.context_debounce_seconds),
    },
    "reconcile-context-vectors": {
        "task": "reconcile_context_vectors",
        "schedule": float(settings.context_reconcile_seconds),
    },
    # Part 8 Phase 2E: the map-pack rank refresh. It CLAIMS active local_rankings
    # rows (FOR UPDATE SKIP LOCKED) and checks each through the cost gate, so the
    # cadence is deliberately slow (default daily) - a map-pack position does not
    # move hourly and every check is PAID. The task also takes the R6 advisory
    # overlap lock, so a tick that arrives while the previous one is still draining
    # returns immediately instead of double-spending.
    "refresh-local-ranks": {
        "task": "refresh_local_ranks",
        "schedule": float(settings.local_rank_refresh_seconds),
    },
}
