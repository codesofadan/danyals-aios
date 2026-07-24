"""Unit tests for the autonomous reporting workers (Reports/cron): the pure cores of the
weekly audit-refresh sweep, the monthly SEO-report generator, and the off-page monitor
sweep. Each is exercised with a FAKE store + a capturing enqueue - no DB, no Celery, no
network - proving: a scheduled report job produces + stores a report; the audit refresh
queues audits idempotently; and every job records a run in the ledger and never raises.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.config import Settings
from workers.tasks.reports import (
    build_monthly_summary,
    dispatch_audit_refresh,
    dispatch_offpage_sweep,
    execute_monthly_reports,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 15, 6, 0, tzinfo=UTC)


def _settings() -> Settings:
    return Settings(_env_file=None)  # type: ignore[call-arg]


class FakeReportStore:
    """In-memory ``ReportStore`` capturing every write the cores make."""

    def __init__(
        self,
        clients: list[dict[str, Any]],
        *,
        recent: set[str] | None = None,
        metrics: dict[str, dict[str, Any]] | None = None,
        existing: set[tuple[str, str]] | None = None,
    ) -> None:
        self._clients = clients
        self._recent = recent or set()
        self._metrics = metrics or {}
        self._existing = existing or set()
        self.inserted_audits: list[dict[str, Any]] = []
        self.inserted_reports: list[dict[str, Any]] = []
        self.runs: list[dict[str, Any]] = []

    def list_active_clients(self, *, limit: int) -> list[dict[str, Any]]:
        return self._clients[:limit]

    def recent_audit_exists(self, client_id: str, *, since: datetime) -> bool:
        return client_id in self._recent

    def insert_audit(self, *, client_id: str, client_name: str, url: str, tier: str) -> str:
        audit_id = f"audit-{len(self.inserted_audits)}"
        self.inserted_audits.append(
            {"id": audit_id, "client_id": client_id, "url": url, "tier": tier}
        )
        return audit_id

    def report_exists(self, *, client_id: str, period: str, title: str) -> bool:
        return (client_id, period) in self._existing

    def monthly_metrics(self, client_id: str) -> dict[str, Any]:
        return self._metrics.get(client_id, {})

    def record_run(self, *, job_name: str, task: str, status: str, detail: str) -> str:
        self.runs.append({"job_name": job_name, "status": status, "detail": detail})
        return "run-0"

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
    ) -> str:
        report_id = f"rep-{len(self.inserted_reports)}"
        self.inserted_reports.append(
            {
                "id": report_id,
                "client_id": client_id,
                "period": period,
                "title": title,
                "report": report,
                "detail": detail,
            }
        )
        return report_id


# --- weekly audit refresh -----------------------------------------------------


def test_audit_refresh_queues_eligible_dedupes_recent_and_skips_no_site() -> None:
    store = FakeReportStore(
        [
            {"client_id": "c-a", "client_name": "Acme", "domain": "acme.com"},
            {"client_id": "c-b", "client_name": "Beta", "domain": ""},  # no site -> skip
            {"client_id": "c-c", "client_name": "Cee", "domain": "cee.io"},  # recent -> skip
        ],
        recent={"c-c"},
    )
    queued: list[str] = []
    result = dispatch_audit_refresh(
        store, _settings(), enqueue=queued.append, now=_NOW
    )

    assert result == {"state": "ok", "queued": 1, "skipped": 2}
    # exactly the eligible client got an audit + an enqueue, with a normalized URL + tier
    assert [a["client_id"] for a in store.inserted_audits] == ["c-a"]
    assert store.inserted_audits[0]["url"] == "https://acme.com"
    assert store.inserted_audits[0]["tier"] == "free"
    assert queued == ["audit-0"]
    # the sweep recorded exactly one heartbeat run
    assert len(store.runs) == 1 and store.runs[0]["status"] == "ok"


def test_audit_refresh_never_raises_on_store_error() -> None:
    class Boom(FakeReportStore):
        def insert_audit(self, **_kw: Any) -> str:
            raise RuntimeError("db down")

    store = Boom([{"client_id": "c-a", "client_name": "Acme", "domain": "acme.com"}])
    # A per-client failure is swallowed (skipped), the batch still records its run.
    result = dispatch_audit_refresh(store, _settings(), enqueue=lambda _a: None, now=_NOW)
    assert result["queued"] == 0 and result["skipped"] == 1
    assert store.runs and store.runs[0]["status"] == "ok"


# --- monthly SEO report -------------------------------------------------------


_METRICS = {
    "audit_first": 70, "audit_latest": 82, "audit_delta": 12,
    "content_30d": 4, "keywords_tracked": 20, "keywords_top10": 12,
    "backlinks_total": 100, "backlinks_new_30d": 5, "citations_total": 30,
}


def test_monthly_reports_produces_stores_and_dedupes() -> None:
    store = FakeReportStore(
        [
            {"client_id": "c-a", "client_name": "Acme", "domain": "acme.com"},
            {"client_id": "c-b", "client_name": "Beta", "domain": "beta.com"},
        ],
        metrics={"c-a": _METRICS},
        existing={("c-b", "July 2026")},  # already reported this period -> skip
    )
    result = execute_monthly_reports(store, _settings(), now=_NOW)

    assert result == {"state": "ok", "produced": 1, "skipped": 1, "period": "July 2026"}
    assert len(store.inserted_reports) == 1
    stored = store.inserted_reports[0]
    assert stored["client_id"] == "c-a" and stored["period"] == "July 2026"
    # the stored payload is the real, downloadable summary
    payload = stored["report"]
    assert payload["kind"] == "monthly_seo"
    assert payload["sections"]["audit"]["latest_score"] == 82
    assert payload["sections"]["backlinks"]["new_last_30d"] == 5
    assert store.runs and store.runs[0]["job_name"] == "generate-monthly-reports"


def test_build_monthly_summary_payload_and_detail() -> None:
    payload, detail = build_monthly_summary(
        client_name="Acme", period="July 2026", metrics=_METRICS, now=_NOW
    )
    assert payload["headline"] == "Score 82 (+12)"
    assert payload["client"] == "Acme"
    assert payload["sections"]["rankings"] == {"tracked_keywords": 20, "in_top_10": 12}
    assert detail == "Score 82 (+12), 4 posts shipped, 12/20 keywords in top 10, 5 new links"


def test_build_monthly_summary_honest_on_empty_client() -> None:
    payload, detail = build_monthly_summary(
        client_name="New", period="July 2026", metrics={}, now=_NOW
    )
    assert payload["headline"] == "No audit yet"
    assert payload["sections"]["audit"]["latest_score"] is None
    assert detail == "No audit yet, 0 posts shipped, 0/0 keywords in top 10, 0 new links"


# --- off-page monitor sweep ---------------------------------------------------


def test_offpage_sweep_fans_out_per_client_with_a_domain() -> None:
    store = FakeReportStore(
        [
            {"client_id": "c-a", "client_name": "Acme", "domain": "acme.com"},
            {"client_id": "c-b", "client_name": "Beta", "domain": ""},  # no domain -> skip
            {"client_id": "c-c", "client_name": "Cee", "domain": "cee.io"},
        ]
    )
    swept: list[tuple[str, str]] = []
    result = dispatch_offpage_sweep(
        store, _settings(), enqueue=lambda cid, dom: swept.append((cid, dom)), now=_NOW
    )
    assert result == {"state": "ok", "dispatched": 2, "skipped": 1}
    assert swept == [("c-a", "acme.com"), ("c-c", "cee.io")]
    assert store.runs and store.runs[0]["job_name"] == "sweep-offpage-monitors"
