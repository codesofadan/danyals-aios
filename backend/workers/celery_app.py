"""Celery application for AIOS background jobs.

Broker and result backend live on separate Redis logical DBs from the app cache
(broker db 1, results db 2; see ``Settings``) so a cache FLUSHDB can never wipe
queued jobs. Tasks are registered via ``include=[...]`` (deterministic) rather
than ``autodiscover_tasks``, which would look for a non-existent
``workers.tasks.tasks`` module and silently register nothing.
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

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
        # Part 8: the billing past-due sweep (mark_past_due). BEAT-driven (see the
        # schedule below); the flip is a single idempotent UPDATE, so Postgres's row
        # locks serialise overlapping ticks and no overlap-lock is needed.
        "app.modules.billing.tasks",
        # Part 8: the local-SEO workers. refresh_local_ranks IS beat-driven (see the
        # beat_schedule below) and therefore DOES take the R6 overlap lock;
        # sync_gbp_profile is event-driven (enqueued per profile).
        "app.modules.local_seo.tasks",
        # Part 8: the on-page workers (analyze_page / apply_onpage_fix /
        # revert_onpage_fix). All event-driven (enqueued per analysis / per lead
        # decision), so no beat entry / overlap-lock is needed. The apply + revert
        # tasks take the acting LEAD's id and run on that RLS identity - the 0038
        # guard trigger refuses a live-site write that is not lead-attributed.
        "app.modules.on_page.tasks",
        # Part 8 Phase 2B: the rank-tracker workers. SCHEDULED (dispatch_rank_checks
        # nightly + rollup_rank_history weekly) rather than event-driven - a tracked
        # keyword is a standing per-client subscription, so it needs the beat entries
        # below and DOES take the R6 overlap lock.
        "app.modules.rank_tracker.tasks",
        # Part 8 Phase 2G: the data-import worker (run_import). Event-driven (enqueued
        # when a lead commits an uploaded file), so no beat entry is needed. It takes no
        # overlap lock either: the run-CLAIM (a conditional UPDATE to 'importing') is a
        # per-run mutex, which is exactly the right granularity - two DIFFERENT files
        # should import concurrently, and the same file must not import twice.
        "app.modules.data_import.tasks",
        # Part 8 Phase 2C: the competitor-intel workers (run_gap_analysis /
        # discover_competitors). Both event-driven (enqueued per analyse / per discover
        # press), so no beat entry / overlap-lock is needed - competitive intelligence
        # is pulled when an analyst asks, never on a standing schedule.
        "app.modules.competitor_intel.tasks",
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
#
# The billing past-due sweep (Part 8 Phase 2H) runs nightly by default: it flips every
# `open` invoice whose due date has passed to `past_due` (the one automatic status
# transition in the module - it notices a date, it does not move money). A single
# idempotent UPDATE keyed on `status = 'open'`, so a re-run or an overlapping tick is
# a no-op and it needs no overlap lock.
celery_app.conf.beat_schedule = {
    "dispatch-context": {
        "task": "dispatch_context",
        "schedule": float(settings.context_debounce_seconds),
    },
    "reconcile-context-vectors": {
        "task": "reconcile_context_vectors",
        "schedule": float(settings.context_reconcile_seconds),
    },
    "mark-past-due-invoices": {
        "task": "mark_past_due",
        "schedule": float(settings.billing_past_due_sweep_seconds),
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
    # Part 8 Phase 2B - the rank tracker. dispatch-rank-checks runs NIGHTLY (03:15 UTC,
    # off the daily-traffic peak): it takes the R6 beat-overlap lock, claims every due
    # active subscription (FOR UPDATE SKIP LOCKED, advancing next_check_on in the same
    # statement) and fans out one check_keyword_rank per claim. Per-keyword cadence
    # lives in tracked_keywords.next_check_on, so this beat only drains what is due -
    # a daily tick serves weekly keywords correctly without a second schedule.
    #
    # rollup-rank-history runs weekly (Sunday 04:10 UTC): it thins history older than
    # rank_tracker_rollup_after_days to one snapshot per ISO week and purges past
    # rank_tracker_history_retention_days. This is the DELIBERATE alternative to
    # partitioning keyword_rankings (see 0036's header) - gradual and observable, with
    # no month-rollover cliff.
    "dispatch-rank-checks": {
        "task": "dispatch_rank_checks",
        "schedule": crontab(hour=3, minute=15),
    },
    "rollup-rank-history": {
        "task": "rollup_rank_history",
        "schedule": crontab(hour=4, minute=10, day_of_week=0),
    },
}
