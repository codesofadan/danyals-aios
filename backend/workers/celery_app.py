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
from celery.signals import worker_init, worker_process_init

from app.config import apply_provider_env, get_settings, validate_settings
from app.jobs.celery_task import route_task
from app.jobs.status import BROKER_VISIBILITY_TIMEOUT

settings = get_settings()
# Same reason as app/main.py: the Anthropic SDK resolves its host from os.environ, and
# the audit-engine subprocess inherits this process's environment. Worker tasks are the
# heaviest LLM callers (content pipeline, SME questions, audit narrative), so the export
# has to happen here too - the API's copy does not reach this process.
apply_provider_env(settings)


@worker_process_init.connect  # type: ignore[untyped-decorator]  # celery's signal decorator is untyped
def _init_worker_db_pools(**_kwargs: object) -> None:
    """Build THIS worker process's DB pools.

    The API opens its pools in the FastAPI lifespan; a Celery worker has no
    lifespan, so without this every DB-touching task (audit, content, rank
    tracker, ...) fails with ``DatabaseNotConfiguredError`` - the pool globals stay
    ``None``. Built per worker process (post-fork under the prefork pool) so a
    psycopg connection is never shared across a fork.

    THIS SIGNAL DOES NOT FIRE FOR EVERY POOL, and the docstring here used to claim
    it covered solo as well and stop there - which read as "all pools are handled".
    In celery 5.6.3 exactly two concurrency backends send ``worker_process_init``:
    ``concurrency/solo.py:20`` and ``concurrency/prefork.py:82``. The THREAD pool
    sends nothing. ``Start-Worker.bat`` - the documented way to run a worker on
    Windows, which is where this platform is developed - launches with
    ``--pool=threads``, so on that machine this function never ran, both pools
    stayed ``None``, and every DB-touching job died at its first ledger write. A
    queued replication then sat on the card reading "Waiting for the worker..."
    forever, which is indistinguishable from "slow". ``_init_worker_db_pools_any_pool``
    below is the fallback that closes it.
    """
    from app.db.database import build_admin_pool, build_rls_pool, set_pools

    s = get_settings()
    # The documented fail-fast on missing production secrets ran in the API's
    # lifespan and NOWHERE ELSE - so the process that actually spends money started
    # blind. A worker with, say, no VAULT_MASTER_KEY or no provider key came up
    # healthy, accepted jobs, and failed them one at a time at runtime instead of
    # refusing to start. In prod this raises and the unit stops; in dev it warns,
    # exactly as it does for the API.
    validate_settings(s)
    rls = build_rls_pool(s.database_url)
    admin = build_admin_pool(s.database_admin_url)
    if rls is not None:
        rls.open()
    if admin is not None:
        admin.open()
    set_pools(rls, admin)


@worker_init.connect  # type: ignore[untyped-decorator]  # celery's signal decorator is untyped
def _init_worker_db_pools_any_pool(**_kwargs: object) -> None:
    """Build the pools for the pools ``worker_process_init`` never reaches.

    ``worker_init`` fires once per worker, for EVERY concurrency backend, before the
    pool starts. That is the right hook for the thread and gevent/eventlet pools,
    which run tasks in the main process and never emit ``worker_process_init``.

    It is the WRONG hook for prefork, where it runs in the parent BEFORE the fork:
    pools built here would be inherited by every child, and a psycopg connection
    shared across a fork is a corruption bug, not a performance one. So prefork is
    explicitly skipped and left to ``worker_process_init``, which runs post-fork.

    Idempotent by construction - it does nothing when pools already exist - so the
    two handlers can never fight, whichever order they fire in.
    """
    import sys

    from app.db import database

    # The COMMAND LINE is authoritative and is read FIRST. At worker_init time celery
    # has NOT yet applied `-P/--pool` to conf, so conf.get("worker_pool") still reports
    # its default ("prefork") even for `--pool=threads`. Trusting conf here made this
    # handler return early on Windows -- where prefork does not work and threads is the
    # only option -- so neither hook ever built the pools and EVERY task failed with
    # DatabaseNotConfiguredError. Prod is unaffected either way: it passes no --pool, so
    # argv yields nothing, conf's "prefork" wins, and worker_process_init builds the
    # pools post-fork as before.
    pool = ""
    for i, arg in enumerate(sys.argv):
        if arg in ("-P", "--pool") and i + 1 < len(sys.argv):
            pool = sys.argv[i + 1]
        elif arg.startswith("--pool="):
            pool = arg.split("=", 1)[1]
    if not pool:  # no CLI override -- fall back to whatever conf reports
        try:
            pool = str(celery_app.conf.get("worker_pool") or "")
        except Exception:  # conf may not be fully resolved this early
            pool = ""
    if "prefork" in pool or "processes" in pool:
        return  # post-fork initialisation is worker_process_init's job

    # Read the module globals rather than get_rls_pool()/get_admin_pool(), which
    # RAISE when unset - "is it configured" must not be asked with an exception.
    if database._rls_pool is not None or database._admin_pool is not None:
        return  # already built; nothing to do
    _init_worker_db_pools()


celery_app = Celery(
    "aios",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=[
        "workers.tasks.ping",
        "workers.tasks.audit",
        "workers.tasks.content",
        # The doctrine engine's entry point. Registered so it is dispatchable;
        # `settings.content_engine` decides which engine a new job is routed to,
        # and it defaults to v1 until the pipeline has had a real end-to-end run.
        "workers.tasks.content_pipeline",
        "workers.tasks.context",
        "workers.tasks.context_reconcile",
        # Part 7 Module 05: the Policy-Radar tasks. DEFAULT = generate_policy_daily (the
        # BEAT-driven Anthropic daily brief; idempotent per UTC day, never re-raises).
        # The legacy Google-scrape watcher (watch_policy_sources) lives here too but is no
        # longer on the beat schedule (kept for reference / re-enablement).
        "workers.tasks.policy",
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
        # 7B-4: the citation-submission worker (citation_submit). Event-driven
        # (enqueued per row when a lead dispatches a campaign), so no beat entry /
        # overlap-lock is needed - each row is claimed exactly once by its own id.
        "app.modules.citations.tasks",
        # 7C: the site-analytics workers (sync_gsc_property / sync_ga4_property).
        # Both event-driven (enqueued per property from the router), so no beat
        # entry / overlap-lock is needed - each property is synced on request.
        "app.modules.site_analytics.tasks",
        # Indexing: submit_urls_for_indexing. Event-driven (enqueued best-effort after a
        # successful content publish, and by the on-demand endpoint), so no beat entry /
        # overlap-lock is needed. FREE engines -> no cost dial.
        "app.modules.indexing.tasks",
        # Website Reconstruction Phase 1+2: analyze_site (real Playwright-measured
        # website capture -> a persisted, versioned DesignIR). Event-driven (enqueued
        # per POST /site-builder/analyze), so no beat entry / overlap-lock is needed -
        # each job id is claimed exactly once by its own row.
        "app.modules.site_builder.tasks",
        # Design Replication (stage 6): run_replica ('aios.replica.run') - the full
        # URL -> Elementor-draft pipeline under @aios_job on the BROWSER queue (it
        # drives a ~30-60s Playwright capture). Event-driven (enqueued per POST
        # /replica), idempotent on (client, url, slug), so no beat entry is needed.
        "workers.tasks.replica",
        # Reports/cron: the AUTONOMOUS reporting jobs (refresh_client_audits weekly,
        # generate_monthly_reports monthly, sweep_offpage_monitors weekly). All are
        # BEAT-driven (see the beat_schedule below) and idempotent: the audit refresh
        # dedupes on a recent audit, the monthly report dedupes per client x month, and
        # the off-page sweep just fans out the already-idempotent monitor task. Each
        # records its run in the scheduled_job_runs ledger so the Reports tab can show
        # last-run / last-status, and none re-raises into beat.
        "workers.tasks.reports",
        # The nightly Postgres snapshot (run_nightly_backup). Before this, the ONLY
        # caller of the pg_dump service was a human pressing POST /backups/run, while
        # backup_config.nightly_enabled defaulted to true and the panel rendered a
        # nightly schedule - a promise with no mechanism. Registered here so it is
        # dispatchable now; its beat entry sits in the PRESERVED table below, because
        # cron stays parked.
        "workers.tasks.backups",
        # The job contract's own maintenance: the stuck-run reaper. It repairs the
        # ledger, so it deliberately does NOT run under @aios_job - see the module
        # docstring.
        "workers.tasks.automations",
        "workers.tasks.job_maintenance",
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
    # The DEFAULT limits, for the tasks that predate the job contract. A task
    # registered with @aios_job overrides both from its queue's duration class
    # (app/jobs/status.py TIME_LIMITS), so the two never have to be kept in step
    # by hand.
    task_time_limit=1800,
    task_soft_time_limit=1740,
    result_expires=3600,
    # --- QUEUES BY DURATION CLASS (job contract) --------------------------- #
    # Four queues, split by how long a job runs rather than by which module it
    # belongs to. Splitting by module puts a 2-second webhook behind a 40-minute
    # crawl on the same queue - and with worker_prefetch_multiplier=1 that webhook
    # waits for the crawl. Splitting by duration means a slow class can only ever
    # starve itself.
    #
    # `browser` is separate from `long` for a second reason: it is the only class
    # that needs Chromium + Playwright in its image, so it runs on its own worker
    # with its own memory envelope. That is what keeps an audit from taking the API
    # host down with it.
    #
    # Start the workers with explicit queues, e.g.
    #   celery -A workers.celery_app worker -Q celery,interactive,standard -c 8
    #   celery -A workers.celery_app worker -Q long -c 2
    #   celery -A workers.celery_app worker -Q browser -c 1   (browser image only)
    #
    # task_default_queue is DELIBERATELY left at Celery's own default ("celery").
    # Setting it to "standard" looked tidier and was a live-deploy hazard: the 39
    # tasks that predate the contract publish to the default queue, so changing its
    # NAME strands every message already sitting on `celery` at the moment of a
    # deploy, and a worker started without -Q would stop consuming them entirely.
    # Legacy tasks keep their queue until each is migrated to @aios_job; only tasks
    # that explicitly declare a duration class are routed away from it.
    task_routes=(route_task,),
    # INVARIANT (unchanged in meaning, updated in value): with task_acks_late=True on
    # a Redis broker, visibility_timeout MUST be >= the longest hard task_time_limit.
    # Otherwise a job that runs longer than the visibility window is re-delivered to a
    # SECOND worker and RUNS TWICE (double API spend). The browser class now allows
    # 7200s, so the window is derived from the duration classes rather than hardcoded:
    # BROKER_VISIBILITY_TIMEOUT = max(TIME_LIMITS) + 300. tests/test_job_queues.py
    # asserts the two cannot drift apart.
    #
    # The cost of the larger window: a message genuinely lost to a dead worker is not
    # redelivered for ~2 hours. That is why the job contract does not rely on
    # redelivery to notice a dead job - the heartbeat reaper (reap_stale_job_runs)
    # does, within one queue time-limit.
    broker_transport_options={"visibility_timeout": BROKER_VISIBILITY_TIMEOUT},
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
# --------------------------------------------------------------------------- #
# BEAT CARRIES TWO ENTRIES, AND NEITHER OF THEM IS A BUSINESS DECISION.
#
# The fourteen periodic jobs that used to live here were switched off wholesale on
# 2026-08-19 (preserved verbatim below in ``_BEAT_SCHEDULE_DISABLED``). Switching them
# off wholesale was the only option available: a static schedule is read at process
# start, so pausing one, re-timing one, or scoping one to particular clients each
# needed a developer and a deploy.
#
# They are automations now - rows in ``public.automations`` (0118), all seeded PAUSED,
# each created / re-timed / enabled / audited from the dashboard. So this table holds
# only the two things that are infrastructure rather than anyone's choice:
#
#   dispatch-automations  reads due automations and fires them. It is the mechanism
#                         that makes the editable schedule work; with it off, every
#                         automation an admin enables silently does nothing.
#   reap-stale-job-runs   repairs the job ledger after a worker dies. It costs
#                         nothing, and must NOT be pausable from the surface it
#                         protects - an operator turning it off would leave stuck runs
#                         permanent, which is exactly when it is most needed.
#
# Adding a business job back to THIS table would put it beyond the reach of the
# manager that exists to control it. ``tests/test_automations.py`` holds the set at
# these two.
celery_app.conf.beat_schedule = {
    "dispatch-automations": {
        "task": "dispatch_automations",
        # A minute is the resolution the whole feature promises: an automation set for
        # 02:00 fires within a minute of it. It is also the floor the schema enforces
        # on intervals, so the two cannot disagree.
        "schedule": 60.0,
    },
    "reap-stale-job-runs": {
        "task": "reap_stale_job_runs",
        "schedule": 300.0,
    },
}

_BEAT_SCHEDULE_DISABLED = {
    # Citation liveness re-check (0106). A listing is not a fact you establish once:
    # directories delete listings, merge duplicates, expire unclaimed entries and quietly
    # change a phone number, and none of that notifies us. Without this sweep `live`
    # decays from an observation into a claim - the same defect class as the
    # screenshot-as-live-URL this module was recovering from.
    #
    # Hourly is not a cadence choice, it is a POLLING choice: the actual cadence lives per
    # row in `citations.next_recheck_at` (+3d, +14d, +60d for a new listing, then monthly
    # for route A / core and quarterly for the rest). This sweep just asks "is anything
    # due?" and does nothing when the answer is no. It makes NO provider call - plain HTTP
    # GETs against listing URLs - so it is not metered and needs no dial.
    #
    # NOTE: beat is OFF (see above), so this does not run today. Until it is switched on,
    # the same task is reachable on demand at POST /citation-builder/recheck, which is how
    # the feature is usable without reversing the owner's decision about cron.
    "citation-liveness-recheck": {
        "task": "citation_liveness_recheck",
        "schedule": 3600.0,
    },
    # Scheduled content publishing (spec section 46). A lead's approve already moved
    # the job to `publishing` (the human gate is unchanged); this sweep only fires
    # the already-approved push once its publish_at is due. 5-minute cadence is
    # plenty for a human-scheduled publish time (not a hot path).
    "dispatch-scheduled-content-publishes": {
        "task": "dispatch_scheduled_content_publishes",
        "schedule": 300.0,
    },
    "dispatch-context": {
        "task": "dispatch_context",
        "schedule": float(settings.context_debounce_seconds),
    },
    "reconcile-context-vectors": {
        "task": "reconcile_context_vectors",
        "schedule": float(settings.context_reconcile_seconds),
    },
    # Part 7 Module 05 - the DAILY Policy Radar GENERATOR (Anthropic). Once a day Claude
    # researches the current top Google-Search policy/algorithm developments via the
    # server-side web_search tool and writes policy_daily_count items into change_events +
    # kb_entries + recommendations - the SAME tables the dashboard reads. This REPLACED the
    # Google-scrape watcher (watch_policy_sources), which the user moved off of; the
    # watcher task is retained in workers/tasks/policy.py but is no longer scheduled. The
    # task is idempotent per UTC day (count_generated_today) so a re-delivered tick never
    # double-spends, and it degrades to nothing (never crashes) when keyless / dial-blocked.
    "generate-policy-daily": {
        "task": "generate_policy_daily",
        "schedule": crontab(
            hour=settings.policy_generate_hour,
            minute=settings.policy_generate_minute,
        ),
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
    # Reports/cron (autonomous SEO reporting). All degrade cleanly with no external keys
    # and never re-raise into beat; each records a row in scheduled_job_runs so the
    # Reports tab shows last-run / last-status alongside the live cadence.
    #
    # refresh-client-audits (WEEKLY): re-run the audit engine per active client and store
    # the report (it then appears in the Reports library via /audits). Dedupes a client
    # audited within report_audit_refresh_min_age_days, so a re-delivered tick is a no-op.
    "refresh-client-audits": {
        "task": "refresh_client_audits",
        "schedule": float(settings.report_audit_refresh_seconds),
    },
    # generate-monthly-reports (MONTHLY): one stored, downloadable JSON SEO summary per
    # active client (audit-score trend + ranks + content shipped + backlinks/citations
    # delta), on a day-of-month crontab. Idempotent per client x month.
    "generate-monthly-reports": {
        "task": "generate_monthly_reports",
        "schedule": crontab(
            day_of_month=settings.report_monthly_day,
            hour=settings.report_monthly_hour,
            minute=0,
        ),
    },
    # sweep-offpage-monitors (WEEKLY): fan out the existing backlink/citation monitor per
    # active client with a domain. The monitor is itself cost-gated + key-degrading.
    "sweep-offpage-monitors": {
        "task": "sweep_offpage_monitors",
        "schedule": float(settings.report_offpage_sweep_seconds),
    },
    # The NIGHTLY POSTGRES SNAPSHOT (workers/tasks/backups.py). 02:00 UTC matches the
    # `backup_config.nightly_time` default that 0026 seeds and the config panel renders;
    # the two are NOT wired to each other and cannot be - beat reads a static table at
    # process start and has no database. Editing nightly_time in the UI therefore changes
    # what the panel SAYS, not when this fires. What the task does honour at run time is
    # `nightly_enabled`: with the toggle off it returns a BLOCKED outcome naming the
    # toggle rather than quietly taking a snapshot the operator switched off.
    #
    # NOTE: beat is OFF (see above), so this does not run today. Until it is switched on,
    # a snapshot is taken on demand at POST /backups/run (owner/admin) - which is how the
    # capability is usable without reversing the owner's decision about cron.
    "nightly-backup": {
        "task": "run_nightly_backup",
        "schedule": crontab(hour=2, minute=0),
    },
    # The STUCK-RUN REAPER (workers/tasks/job_maintenance.py). The task has existed since
    # the job contract landed and was registered in `include` above, but nothing ever
    # called it - so `JobRunsStore.start` counted `running` rows against the per-client
    # concurrency cap while nothing on the system could ever clear a row whose worker died
    # without writing an outcome. That is a cap that only ever tightens.
    #
    # Every 5 minutes is derived, not picked: the tightest staleness budget is INTERACTIVE
    # (TIME_LIMITS 60s + HEARTBEAT_GRACE_SECONDS 300 = 360s of silence), so a 300s sweep
    # bounds detection lag to under one grace window for every queue. A slower sweep would
    # let a dead interactive run hold a client's slot for materially longer than the
    # contract says it can.
    #
    # NOTE: beat is OFF (see above), so this does not run today. Until it is switched on,
    # the same sweep is reachable on demand at POST /maintenance/reap-stuck-jobs
    # (owner-only, in app/routers/backups.py).
    "reap-stale-job-runs": {
        "task": "reap_stale_job_runs",
        "schedule": 300.0,
    },
}
