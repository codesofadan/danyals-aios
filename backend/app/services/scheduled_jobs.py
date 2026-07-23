"""Scheduled-jobs catalogue: the LIVE Celery beat schedule, humanized.

The Reports "Scheduled jobs" panel lists the cron jobs the platform actually runs
in the background. Rather than hard-code a list, this reads the SAME
``beat_schedule`` the beat process runs (``workers/celery_app.py``) and turns each
entry into ``{name, task, description, cadence}`` - so the panel can never drift
from what is scheduled. Only the plain-language description per task lives here (the
schedule itself carries just a task NAME); the cadence is derived from the live
schedule value - a ``crontab`` or an interval in seconds, several of which resolve
from ``Settings`` - so re-tuning an interval is reflected with no change here.

``scheduled_jobs`` imports the Celery app lazily (like the audits router's enqueuer)
so the API process never pulls Celery task modules in just to read the schedule;
constructing the ``Celery`` object opens no broker connection.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ScheduledJob(BaseModel):
    """One beat entry, in the shape the Reports panel renders."""

    name: str  # the beat entry key (a stable slug)
    task: str  # the Celery task name it runs
    description: str  # what the job does, in plain language
    cadence: str  # human-readable schedule (e.g. "Every 6 hours", "Daily at 03:15 UTC")


# Plain-language description per Celery task name. A task with no entry here falls
# back to a generic label rather than exposing nothing.
_TASK_DESCRIPTIONS: dict[str, str] = {
    "dispatch_context": (
        "Folds recent activity into each client / site / user's living AI-memory context."
    ),
    "reconcile_context_vectors": (
        "Safety sweep that heals any drift between the context store and its vector index."
    ),
    "watch_policy_sources": (
        "Re-fetches the curated Google policy sources, diffs each by content hash, and files "
        "a change event (and KB analysis) on any update."
    ),
    "mark_past_due": "Flips invoices whose due date has passed from open to past-due.",
    "refresh_local_ranks": (
        "Refreshes map-pack (local) ranking positions for every active local ranking that is due."
    ),
    "dispatch_rank_checks": (
        "Queues a SERP rank check for every tracked-keyword subscription that is due."
    ),
    "rollup_rank_history": (
        "Thins and purges old keyword-ranking history to keep the ledger lean."
    ),
}
_DEFAULT_DESCRIPTION = "Scheduled background job."

# celery crontab day_of_week: 0 (and 7) = Sunday, 1 = Monday, ... 6 = Saturday.
_DOW = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def _humanize_interval(seconds: float) -> str:
    """A round interval-in-seconds as 'Every N <unit>' at the coarsest whole unit."""
    total = round(seconds)
    if total < 60:
        unit, n = "second", total
    elif total < 3600:
        unit, n = "minute", total // 60
    elif total < 86_400:
        unit, n = "hour", total // 3600
    else:
        unit, n = "day", total // 86_400
    return f"Every {n} {unit}{'' if n == 1 else 's'}"


def _humanize_crontab(cron: Any) -> str:
    """A celery ``crontab`` as 'Daily at HH:MM UTC' or 'Weekly on <day> at HH:MM UTC'."""
    minutes = sorted(int(m) for m in cron.minute)
    hours = sorted(int(h) for h in cron.hour)
    dow = sorted(int(d) % 7 for d in cron.day_of_week)
    at = f"{(hours[0] if hours else 0):02d}:{(minutes[0] if minutes else 0):02d} UTC"
    if len(set(dow)) >= 7:  # every weekday selected -> a daily run
        return f"Daily at {at}"
    days = ", ".join(_DOW[d] for d in dow)
    return f"Weekly on {days} at {at}"


def _humanize_schedule(raw: Any) -> str:
    """Humanize a beat ``schedule`` value (a crontab or an interval-in-seconds)."""
    if hasattr(raw, "day_of_week") and hasattr(raw, "hour") and hasattr(raw, "minute"):
        return _humanize_crontab(raw)
    try:
        return _humanize_interval(float(raw))
    except (TypeError, ValueError):
        return "On a schedule"


def scheduled_jobs() -> list[ScheduledJob]:
    """The live beat schedule as a sorted list of humanized jobs.

    Blocking only in that it constructs the Celery app on first import; the caller
    offloads it with ``asyncio.to_thread``.
    """
    from workers.celery_app import celery_app

    schedule: dict[str, Any] = dict(celery_app.conf.beat_schedule or {})
    jobs: list[ScheduledJob] = []
    for name, entry in schedule.items():
        task = str(entry.get("task", ""))
        jobs.append(
            ScheduledJob(
                name=str(name),
                task=task,
                description=_TASK_DESCRIPTIONS.get(task, _DEFAULT_DESCRIPTION),
                cadence=_humanize_schedule(entry.get("schedule")),
            )
        )
    jobs.sort(key=lambda j: j.name)
    return jobs
