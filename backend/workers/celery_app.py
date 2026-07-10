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
    include=["workers.tasks.ping"],
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
