"""Scheduled-jobs catalogue: the LIVE Celery beat schedule, humanized + enriched.

The Reports "Scheduled jobs" panel lists the cron jobs the platform actually runs in the
background. Rather than hard-code a list, this reads the SAME ``beat_schedule`` the beat
process runs (``workers/celery_app.py``) and turns each entry into a ``ScheduledJob`` -
so the panel can never drift from what is scheduled. Per entry it derives:

* ``cadence``    - the human schedule (a ``crontab`` or an interval-in-seconds, several
  resolving from ``Settings``), so re-tuning an interval is reflected with no change here.
* ``next_run``   - the next fire time, computed from the schedule (+ the last run for an
  interval), so the operator sees WHEN each job runs next.
* ``last_run`` / ``last_status`` - from the ``scheduled_job_runs`` ledger the workers
  append to (passed in by the router; the beat schedule alone cannot carry a run history).
* ``waiting_on`` - a job that genuinely needs an absent provider key is still SHOWN, but
  flagged "waiting on <provider>" rather than hidden - the operator wants to SEE the
  configured schedule.

``scheduled_jobs`` imports the Celery app lazily (like the audits router's enqueuer) so
the API process never pulls Celery task modules in just to read the schedule; constructing
the ``Celery`` object opens no broker connection.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field

from app.config import Settings


class ScheduledJob(BaseModel):
    """One beat entry, in the shape the Reports panel renders."""

    name: str  # the beat entry key (a stable slug)
    task: str  # the Celery task name it runs
    description: str  # what the job does, in plain language
    cadence: str  # human-readable schedule (e.g. "Every 6 hours", "Daily at 03:15 UTC")
    # The next fire time (ISO 8601, UTC), or None when it cannot be computed.
    next_run: str | None = Field(default=None, serialization_alias="nextRun")
    # The last run's timestamp + outcome from the scheduled_job_runs ledger (None until a
    # job has run once, or for a job that does not write the ledger).
    last_run: str | None = Field(default=None, serialization_alias="lastRun")
    last_status: str | None = Field(default=None, serialization_alias="lastStatus")
    # Set when the job needs an absent provider key to do useful work (still scheduled).
    waiting_on: str | None = Field(default=None, serialization_alias="waitingOn")


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
    "refresh_client_audits": (
        "Re-runs the SEO audit engine for every active client and stores the fresh report "
        "(it then appears in the Reports library)."
    ),
    "generate_monthly_reports": (
        "Generates and stores a downloadable monthly SEO report per active client - audit-score "
        "trend, rankings, content shipped, and the backlink / citation delta."
    ),
    "sweep_offpage_monitors": (
        "Sweeps each active client's backlink profile and citation / NAP listings for new and "
        "lost links."
    ),
}
_DEFAULT_DESCRIPTION = "Scheduled background job."

# celery crontab day_of_week: 0 (and 7) = Sunday, 1 = Monday, ... 6 = Saturday.
_DOW = ("Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday")


def _present(value: Any) -> bool:
    """True when a setting (plain str or a ``SecretStr``) is present and non-empty."""
    getter = getattr(value, "get_secret_value", None)
    raw = getter() if callable(getter) else value
    return bool(raw)


def _waiting_on(task: str, settings: Settings) -> str | None:
    """The provider a report job needs but is missing, or None when it can run.

    Deliberately narrow: only jobs that genuinely produce NOTHING useful without external
    config are flagged. The rank / local / policy jobs degrade to a fake provider (they
    still run), and the monthly report reads only the platform's own data, so none of
    those is flagged."""
    if task == "refresh_client_audits":
        if not (_present(settings.audit_engine_dir) and _present(settings.audit_engine_python)):
            return "audit engine (AUDIT_ENGINE_DIR)"
        return None
    if task == "sweep_offpage_monitors":
        dataforseo = _present(settings.dataforseo_login) and _present(settings.dataforseo_password)
        if not (dataforseo or _present(settings.brightlocal_api_key)):
            return "DataForSEO / BrightLocal key"
        return None
    return None


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
    """A celery ``crontab`` humanized: monthly (a fixed day-of-month), weekly (a fixed
    day-of-week), or daily - each 'at HH:MM UTC'."""
    minutes = sorted(int(m) for m in cron.minute)
    hours = sorted(int(h) for h in cron.hour)
    at = f"{(hours[0] if hours else 0):02d}:{(minutes[0] if minutes else 0):02d} UTC"
    dom = {int(d) for d in cron.day_of_month}
    if len(dom) < 31:  # a specific day-of-month -> a monthly cadence
        return f"Monthly on day {min(dom) if dom else 1} at {at}"
    dow = sorted(int(d) % 7 for d in cron.day_of_week)
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


def _next_run(raw: Any, *, now: datetime, last_run_at: datetime | None) -> str | None:
    """The next fire time as an ISO string, or None when it cannot be derived.

    A crontab computes its own next instant after ``now``; an interval schedule fires
    ``interval`` after its last run (or after ``now`` when it has never run). Never
    raises - an unrecognised schedule simply yields no next-run."""
    try:
        if hasattr(raw, "remaining_estimate"):  # a crontab / schedule object
            seconds = float(raw.remaining_estimate(now).total_seconds())
            base = now
        else:
            seconds = float(raw)
            base = last_run_at or now
        return (base + timedelta(seconds=seconds)).isoformat()
    except Exception:
        return None


def _as_dt(value: Any) -> datetime | None:
    """Coerce a ledger ``created_at`` (datetime or ISO string) to an aware datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def scheduled_jobs(
    *,
    last_runs: dict[str, dict[str, Any]] | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> list[ScheduledJob]:
    """The live beat schedule as a sorted list of humanized, enriched jobs.

    ``last_runs`` maps a beat entry name to its most recent ``scheduled_job_runs`` row
    ({status, created_at, ...}); ``settings`` gates the waiting-on-key flag. Both are
    optional so the pure schedule (name/task/description/cadence) is derivable with no
    DB. Blocking only in that it constructs the Celery app on first import; the caller
    offloads it with ``asyncio.to_thread``.
    """
    from workers.celery_app import celery_app

    now = now or datetime.now(UTC)
    last_runs = last_runs or {}
    schedule: dict[str, Any] = dict(celery_app.conf.beat_schedule or {})
    jobs: list[ScheduledJob] = []
    for name, entry in schedule.items():
        task = str(entry.get("task", ""))
        run = last_runs.get(str(name))
        last_run_at = _as_dt(run.get("created_at")) if run else None
        jobs.append(
            ScheduledJob(
                name=str(name),
                task=task,
                description=_TASK_DESCRIPTIONS.get(task, _DEFAULT_DESCRIPTION),
                cadence=_humanize_schedule(entry.get("schedule")),
                next_run=_next_run(entry.get("schedule"), now=now, last_run_at=last_run_at),
                last_run=last_run_at.isoformat() if last_run_at else None,
                last_status=str(run.get("status")) if run and run.get("status") else None,
                waiting_on=_waiting_on(task, settings) if settings else None,
            )
        )
    jobs.sort(key=lambda j: j.name)
    return jobs
