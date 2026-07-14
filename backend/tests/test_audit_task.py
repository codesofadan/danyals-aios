"""P3-3 gate: the audit Celery task's state machine + cost logging, with the
engine runner MOCKED and an in-memory store (no Supabase, no subprocess)."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from integrations.audit_engine import AuditEngineConfig, AuditRunResult
from workers.tasks.audit import execute_audit

pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.updates: list[dict[str, Any]] = []
        self.costs: list[float] = []

    def load(self, audit_id: str) -> dict[str, Any] | None:
        return self.row

    def update(self, audit_id: str, fields: dict[str, Any]) -> None:
        self.updates.append(fields)
        if self.row is not None:
            self.row.update(fields)

    def record_cost(self, row: dict[str, Any], cost: float) -> None:
        self.costs.append(cost)


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev", audit_paid_cost_estimate=1.5)


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "aud-1",
        "url": "https://example.com",
        "tier": "free",
        "status": "queued",
        "client_id": "cl-1",
        "client_name": "Verde Cafe",
    }
    row.update(over)
    return row


def _ok_runner(score: int) -> Any:
    def _run(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        return AuditRunResult(
            ok=True, run_uuid="u-1", artifact_dir="/art/u-1", score=score,
            scores={"overall": score, "technical": 90}, runtime_seconds=372, exit_code=0,
        )
    return _run


def test_success_marks_running_then_done_and_logs_zero_cost_on_free() -> None:
    store = FakeStore(_row(tier="free"))
    out = execute_audit(store, _settings(), "aud-1", runner=_ok_runner(82))
    assert out["status"] == "done"
    assert out["score"] == 82
    # first update = running, last update = done with the result fields
    assert store.updates[0]["status"] == "running" and "started_at" in store.updates[0]
    done = store.updates[-1]
    assert done["status"] == "done"
    assert done["score"] == 82
    assert done["run_uuid"] == "u-1"
    assert done["runtime_seconds"] == 372
    assert "finished_at" in done
    assert store.costs == [0.0]  # Free tier -> zero paid spend logged


def test_paid_run_logs_estimated_cost() -> None:
    store = FakeStore(_row(tier="paid"))
    execute_audit(store, _settings(), "aud-1", runner=_ok_runner(70))
    assert store.costs == [1.5]  # audit_paid_cost_estimate


def test_engine_failure_marks_failed_never_running() -> None:
    def _fail(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        return AuditRunResult(ok=False, run_uuid="u-9", runtime_seconds=5, error="engine timed out after 1500s")

    store = FakeStore(_row(tier="paid"))
    out = execute_audit(store, _settings(), "aud-1", runner=_fail)
    assert out["status"] == "failed"
    final = store.updates[-1]
    assert final["status"] == "failed"
    assert "timed out" in final["error"]
    assert final["run_uuid"] == "u-9"
    assert "finished_at" in final
    # engine started (run_uuid present) on a paid run -> cost still logged
    assert store.costs == [1.5]


def test_worker_exception_marks_failed_and_does_not_reraise() -> None:
    def _boom(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        raise RuntimeError("unexpected")

    store = FakeStore(_row())
    out = execute_audit(store, _settings(), "aud-1", runner=_boom)  # must NOT raise
    assert out["status"] == "failed"
    assert store.updates[-1]["status"] == "failed"
    assert "worker error" in store.updates[-1]["error"]
    assert store.costs == []  # never started -> no cost


def test_missing_row_is_failed_noop() -> None:
    store = FakeStore(None)
    out = execute_audit(store, _settings(), "nope", runner=_ok_runner(1))
    assert out["status"] == "failed"
    assert store.updates == []


def test_already_done_is_idempotent() -> None:
    store = FakeStore(_row(status="done"))
    out = execute_audit(store, _settings(), "aud-1", runner=_ok_runner(1))
    assert out["status"] == "done"
    assert store.updates == []  # never re-runs the engine on redelivery
    assert store.costs == []


def test_cost_log_failure_never_breaks_job() -> None:
    class ExplodingCostStore(FakeStore):
        def record_cost(self, row: dict[str, Any], cost: float) -> None:
            raise RuntimeError("cost store down")

    store = ExplodingCostStore(_row(tier="paid"))
    out = execute_audit(store, _settings(), "aud-1", runner=_ok_runner(88))
    assert out["status"] == "done"  # job still succeeds despite cost logging failure


def test_task_is_registered() -> None:
    celery_import = __import__("workers.celery_app", fromlist=["celery_app"])
    celery_import.celery_app.loader.import_default_modules()
    assert "run_audit" in celery_import.celery_app.tasks
