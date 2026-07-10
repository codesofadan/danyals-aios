"""A trivial liveness task used to prove the worker + broker round-trip works."""

from __future__ import annotations

from workers.celery_app import celery_app


@celery_app.task(name="ping")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def ping() -> str:
    """Return ``"pong"``. Enqueue this to confirm a worker is consuming jobs."""
    return "pong"
