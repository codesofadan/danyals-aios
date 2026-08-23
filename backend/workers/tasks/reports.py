"""Autonomous reporting workers: the platform's recurring, beat-driven SEO/reporting
jobs. These are what makes the admin Reports tab REAL - the platform runs them on its
own schedule (celery beat), stores what they produce, and surfaces both the schedule
and the produced reports.

Three beat tasks, all on the never-stuck / never-re-raise / idempotent worker template
(``workers.tasks.audit`` / ``workers.tasks.offpage``) - with ``task_acks_late`` a raised
exception would REDELIVER the job and re-do paid work, so every task ACKs, records a run
in the ledger, and returns a small result dict:

* ``refresh_client_audits``   (WEEKLY) - re-run the audit engine per ACTIVE client and
  store the report. Reuses the EXISTING audit worker (it stores the PDF/JSON + surfaces
  it in the Reports library via /audits); this task only CLAIMS the fan-out set, dedupes
  recent audits, and enqueues. Free-tier by default = $0; a Paid sweep clears the audit
  cost gate per run.
* ``generate_monthly_reports`` (MONTHLY) - one stored, downloadable JSON summary per
  active client (audit-score trend + ranks + content shipped + backlinks/citations
  delta). Idempotent per client x month.
* ``sweep_offpage_monitors``   (WEEKLY) - enqueue the EXISTING backlink/citation monitor
  per active client with a domain; degrades cleanly when the off-page providers are
  unconfigured.

The pure cores take an injected ``ReportStore`` (backed by the privileged
``ServiceReportsStore``) + injected ``enqueue`` callables, so they are unit-tested with a
fake store + a capturing enqueue - no DB, no Celery, no network. The Celery app is
imported LAST (after the pure core), per the worker template, so importing this module
stays Celery-free at the API edge.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from app.config import Settings, get_settings
from app.db.reports_repo import service_reports_store
from app.logging_setup import get_logger

logger = get_logger("workers.reports")

# Beat entry keys (must match workers/celery_app.py so the Reports panel's last-run join
# lines up) + the Celery task names.
_AUDIT_JOB = "refresh-client-audits"
_AUDIT_TASK = "refresh_client_audits"
_MONTHLY_JOB = "generate-monthly-reports"
_MONTHLY_TASK = "generate_monthly_reports"
_SWEEP_JOB = "sweep-offpage-monitors"
_SWEEP_TASK = "sweep_offpage_monitors"

_MONTHLY_TITLE = "Monthly SEO Report"


class ReportStore(Protocol):
    """The DB seam the report jobs need (backed by ``ServiceReportsStore``)."""

    def list_active_clients(self, *, limit: int) -> list[dict[str, Any]]: ...
    def recent_audit_exists(self, client_id: str, *, since: datetime) -> bool: ...
    def insert_audit(self, *, client_id: str, client_name: str, url: str, tier: str) -> str: ...
    def report_exists(self, *, client_id: str, period: str, title: str) -> bool: ...
    def monthly_metrics(self, client_id: str) -> dict[str, Any]: ...
    def record_run(self, *, job_name: str, task: str, status: str, detail: str) -> str: ...
    def insert_report(
        self,
        *,
        job_name: str,
        task: str,
        client_id: str,
        client_name: str,
        title: str,
        period: str,
        report: dict[str, Any],
        detail: str = "",
    ) -> str: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _audit_url(domain: str) -> str:
    """Normalize a stored site domain into an absolute URL the engine can crawl."""
    domain = (domain or "").strip()
    if not domain:
        return ""
    if domain.startswith(("http://", "https://")):
        return domain
    return f"https://{domain}"


def _period_label(now: datetime) -> str:
    """The month a report covers, e.g. 'July 2026'."""
    return now.strftime("%B %Y")


# --------------------------------------------------------------------------- #
# Monthly SEO report: build the downloadable summary from the raw metrics.
# --------------------------------------------------------------------------- #
def build_monthly_summary(
    *, client_name: str, period: str, metrics: dict[str, Any], now: datetime
) -> tuple[dict[str, Any], str]:
    """Turn the raw per-client metrics into (downloadable payload, one-line detail).

    Pure + deterministic: the payload is the JSON a staff member downloads; the detail
    is the short human line shown on the run + the library card. Honest about empty data
    (a brand-new client reads as zeros, never a crash)."""
    latest = metrics.get("audit_latest")
    delta = metrics.get("audit_delta")
    content_30d = int(metrics.get("content_30d") or 0)
    tracked = int(metrics.get("keywords_tracked") or 0)
    top10 = int(metrics.get("keywords_top10") or 0)
    bl_total = int(metrics.get("backlinks_total") or 0)
    bl_new = int(metrics.get("backlinks_new_30d") or 0)
    citations = int(metrics.get("citations_total") or 0)

    payload: dict[str, Any] = {
        "kind": "monthly_seo",
        "title": _MONTHLY_TITLE,
        "client": client_name,
        "period": period,
        "generated_at": now.isoformat(),
        "sections": {
            "audit": {
                "latest_score": latest,
                "first_score": metrics.get("audit_first"),
                "delta": delta,
            },
            "content": {"published_last_30d": content_30d},
            "rankings": {"tracked_keywords": tracked, "in_top_10": top10},
            "backlinks": {"referring_domains": bl_total, "new_last_30d": bl_new},
            "citations": {"listings": citations},
        },
    }

    def _delta_str(value: Any) -> str:
        if value is None:
            return ""
        n = int(value)
        return f" ({'+' if n >= 0 else ''}{n})"

    score_part = f"Score {latest}{_delta_str(delta)}" if latest is not None else "No audit yet"
    payload["headline"] = score_part
    detail = (
        f"{score_part}, {content_30d} post{'' if content_30d == 1 else 's'} shipped, "
        f"{top10}/{tracked} keywords in top 10, {bl_new} new link"
        f"{'' if bl_new == 1 else 's'}"
    )
    return payload, detail


# --------------------------------------------------------------------------- #
# Pure cores (claim active clients + fan out / produce; never raise).
# --------------------------------------------------------------------------- #
def dispatch_audit_refresh(
    store: ReportStore,
    settings: Settings,
    *,
    enqueue: Callable[[str], Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Queue a fresh audit per active client that has a site + no recent run.

    Idempotent: a client audited within ``report_audit_refresh_min_age_days`` is skipped,
    so a re-delivered weekly tick does not double-create. Free-tier by default ($0)."""
    now = now or _utcnow()
    since = now - timedelta(days=int(settings.report_audit_refresh_min_age_days))
    tier = settings.report_audit_refresh_tier
    queued = 0
    skipped = 0
    for client in store.list_active_clients(limit=int(settings.report_audit_refresh_batch)):
        client_id = str(client.get("client_id") or "")
        url = _audit_url(str(client.get("domain") or ""))
        if not client_id or not url:
            skipped += 1
            continue
        try:
            if store.recent_audit_exists(client_id, since=since):
                skipped += 1
                continue
            audit_id = store.insert_audit(
                client_id=client_id,
                client_name=str(client.get("client_name") or ""),
                url=url,
                tier=tier,
            )
            if audit_id:
                enqueue(audit_id)
                queued += 1
        except Exception:
            logger.warning("audit_refresh_client_failed", client_id=client_id)
            skipped += 1
    detail = f"queued {queued} audit{'' if queued == 1 else 's'} ({tier}), skipped {skipped}"
    _safe_record(store, job_name=_AUDIT_JOB, task=_AUDIT_TASK, status="ok", detail=detail)
    logger.info("audit_refresh_done", queued=queued, skipped=skipped, tier=tier)
    return {"state": "ok", "queued": queued, "skipped": skipped}


def execute_monthly_reports(
    store: ReportStore, settings: Settings, *, now: datetime | None = None
) -> dict[str, Any]:
    """Produce + store one monthly SEO report per active client for the current period.

    Idempotent: a client already reported for this period is skipped. Best-effort per
    client (one bad client never stops the batch); never raises for a DB reason."""
    now = now or _utcnow()
    period = _period_label(now)
    produced = 0
    skipped = 0
    for client in store.list_active_clients(limit=int(settings.report_monthly_batch)):
        client_id = str(client.get("client_id") or "")
        client_name = str(client.get("client_name") or "")
        if not client_id:
            skipped += 1
            continue
        try:
            if store.report_exists(client_id=client_id, period=period, title=_MONTHLY_TITLE):
                skipped += 1
                continue
            metrics = store.monthly_metrics(client_id)
            payload, detail = build_monthly_summary(
                client_name=client_name, period=period, metrics=metrics, now=now
            )
            store.insert_report(
                job_name=_MONTHLY_JOB,
                task=_MONTHLY_TASK,
                client_id=client_id,
                client_name=client_name,
                title=_MONTHLY_TITLE,
                period=period,
                report=payload,
                detail=detail,
            )
            produced += 1
        except Exception:
            logger.warning("monthly_report_client_failed", client_id=client_id)
            skipped += 1
    detail = f"produced {produced} report{'' if produced == 1 else 's'} for {period}, skipped {skipped}"
    _safe_record(store, job_name=_MONTHLY_JOB, task=_MONTHLY_TASK, status="ok", detail=detail)
    logger.info("monthly_reports_done", produced=produced, skipped=skipped, period=period)
    return {"state": "ok", "produced": produced, "skipped": skipped, "period": period}


def dispatch_offpage_sweep(
    store: ReportStore,
    settings: Settings,
    *,
    enqueue: Callable[[str, str], Any],
    now: datetime | None = None,
) -> dict[str, Any]:
    """Enqueue the existing backlink/citation monitor per active client with a domain.

    The monitor task itself is cost-gated + degrades cleanly with no provider key, so
    this sweep just claims the fan-out set and fans out one monitor per client."""
    now = now or _utcnow()
    dispatched = 0
    skipped = 0
    for client in store.list_active_clients(limit=int(settings.report_offpage_sweep_batch)):
        client_id = str(client.get("client_id") or "")
        domain = str(client.get("domain") or "").strip()
        if not client_id or not domain:
            skipped += 1
            continue
        try:
            enqueue(client_id, domain)
            dispatched += 1
        except Exception:
            logger.warning("offpage_sweep_client_failed", client_id=client_id)
            skipped += 1
    detail = f"swept {dispatched} client{'' if dispatched == 1 else 's'}, skipped {skipped}"
    _safe_record(store, job_name=_SWEEP_JOB, task=_SWEEP_TASK, status="ok", detail=detail)
    logger.info("offpage_sweep_done", dispatched=dispatched, skipped=skipped)
    return {"state": "ok", "dispatched": dispatched, "skipped": skipped}


def _safe_record(store: ReportStore, *, job_name: str, task: str, status: str, detail: str) -> None:
    """Record a heartbeat run; a ledger hiccup must never fail the completed job."""
    try:
        store.record_run(job_name=job_name, task=task, status=status, detail=detail)
    except Exception:
        logger.warning("job_run_record_failed", job_name=job_name)


# --------------------------------------------------------------------------- #
# Celery entry points (thin; the app is imported after the pure core).
# --------------------------------------------------------------------------- #
import psycopg  # noqa: E402

from app.jobs import JobContext, JobOutcome  # noqa: E402
from app.jobs.celery_task import aios_job  # noqa: E402 - after the pure core, per the worker template
from app.jobs.status import JobQueue  # noqa: E402

# WHY THESE FAN OUT WITH `.delay()` AND NOT `enqueue_child()`.
#
# `enqueue_child` propagates the correlation id so one sweep and the N per-client jobs
# it spawns are a single indexed query in `job_runs`. It does that by injecting a
# reserved `_aios_correlation_id` kwarg, which `@aios_job` strips before calling the
# body - so it is only safe to send to a task that is ITSELF migrated. `run_audit_job`
# and `monitor_offpage_job` are not yet, and would receive an unexpected keyword
# argument and fail at the worker.
#
# So the fan-out stays `.delay()` until the children migrate, and the parent's own run
# is still recorded honestly. Wiring the correlation is a one-line change per call site
# AFTER the child moves - and the child must move first, which is the general ordering
# rule for migrating a fan-out.


# WHICH FAILURES ARE TRANSIENT, declared once.
#
# These three cores talk to exactly one thing: Postgres. `OperationalError` is the
# availability class - connection refused, server restarting, a dropped socket - and is
# worth retrying. Everything else that psycopg can raise (ProgrammingError, a bad
# column, a violated constraint) is a BUG: it will fail identically on every attempt,
# so burning the budget on it only delays an operator seeing it.
#
# Declaring this via the contract's `retry_on` rather than translating exceptions by
# hand keeps the conservative default intact - anything not named here is permanent.
_TRANSIENT: tuple[type[BaseException], ...] = (psycopg.OperationalError,)


@aios_job(
    name=_AUDIT_TASK,
    job_name="reports.audit_refresh",
    queue=JobQueue.STANDARD,
    max_attempts=3,
    retry_backoff=120.0,
    retry_on=_TRANSIENT,
    scope_type="workspace",
)
def refresh_client_audits(ctx: JobContext) -> JobOutcome:
    """BEAT job (weekly): re-run the audit engine per active client and store the report.

    Un-keyed: the set of clients due a refresh changes through the week, so a per-week
    key would suppress a legitimate later run. The core already dedupes on a recent
    audit, which is the idempotency that matters.
    """
    def _enqueue(audit_id: str) -> None:
        from workers.tasks.audit import run_audit_job

        run_audit_job.delay(audit_id)

    result = dispatch_audit_refresh(service_reports_store(), get_settings(), enqueue=_enqueue)
    queued = int(result.get("queued", 0))
    skipped = int(result.get("skipped", 0))
    return JobOutcome.completed(
        f"queued {queued} audit(s), skipped {skipped} with a recent run", result=result
    )


@aios_job(
    name=_MONTHLY_TASK,
    job_name="reports.monthly",
    queue=JobQueue.LONG,
    max_attempts=3,
    retry_backoff=300.0,
    retry_on=_TRANSIENT,
    scope_type="workspace",
)
def generate_monthly_reports(ctx: JobContext) -> JobOutcome:
    """BEAT job (monthly): one stored, downloadable SEO report per active client.

    LONG rather than STANDARD: unlike its two siblings this one does the work itself
    rather than fanning out, and it builds a report per client - at 100 clients that is
    not a five-minute job.

    Un-keyed for the same reason as the others: the core is idempotent per client x
    month, so a re-run produces only what is genuinely missing. A per-month key would
    instead suppress the re-run that catches a client onboarded mid-month.
    """
    result = execute_monthly_reports(service_reports_store(), get_settings())
    produced = int(result.get("produced", 0))
    skipped = int(result.get("skipped", 0))
    return JobOutcome.completed(
        f"produced {produced} report(s) for {result.get('period', '')}, "
        f"skipped {skipped} already present",
        result=result,
    )


@aios_job(
    name=_SWEEP_TASK,
    job_name="offpage.monitor_sweep",
    queue=JobQueue.STANDARD,
    max_attempts=3,
    retry_backoff=120.0,
    retry_on=_TRANSIENT,
    scope_type="workspace",
)
def sweep_offpage_monitors(ctx: JobContext) -> JobOutcome:
    """BEAT job (weekly): fan out the backlink/citation monitor per active client."""
    def _enqueue(client_id: str, domain: str) -> None:
        from workers.tasks.offpage import monitor_offpage_job

        monitor_offpage_job.delay(client_id, domain)

    result = dispatch_offpage_sweep(service_reports_store(), get_settings(), enqueue=_enqueue)
    dispatched = int(result.get("dispatched", 0))
    skipped = int(result.get("skipped", 0))
    return JobOutcome.completed(
        f"dispatched {dispatched} monitor(s), skipped {skipped} without a domain", result=result
    )
