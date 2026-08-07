"""P6C gate: the PUBLIC free-audit worker's state machine over public_audits.

Mirrors test_audit_task.py but for ``execute_public_audit`` - always Free ($0),
no tier/client/timing columns. Engine runner MOCKED, in-memory store (no DB, no
subprocess)."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.cost_gate import GateDecision
from integrations.audit_engine import AuditEngineConfig, AuditRunResult
from workers.tasks.audit import execute_public_audit

pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(self, row: dict[str, Any] | None) -> None:
        self.row = row
        self.updates: list[dict[str, Any]] = []
        self.costs: list[float] = []

    def load(self, public_audit_id: str) -> dict[str, Any] | None:
        return self.row

    def update(self, public_audit_id: str, fields: dict[str, Any]) -> None:
        self.updates.append(fields)
        if self.row is not None:
            self.row.update(fields)

    def evaluate(self, row: dict[str, Any], cost: float) -> GateDecision:
        # Public audits are always Free ($0) and never gated; execute_public_audit
        # never calls this. Present only to satisfy the AuditStore protocol.
        return GateDecision("call", cost=0.0)

    def record_cost(self, row: dict[str, Any], cost: float) -> None:
        self.costs.append(cost)


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev")


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "pa-1",
        "email": "lead@example.com",
        "url": "https://example.com",
        "status": "queued",
    }
    row.update(over)
    return row


def _ok_runner(score: int) -> Any:
    def _run(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        assert tier == "free"  # public is ALWAYS free
        return AuditRunResult(
            ok=True, run_uuid="u-1", artifact_dir="/art/u-1", score=score,
            scores={"overall": score, "technical": 90}, runtime_seconds=372, exit_code=0,
        )
    return _run


def test_success_marks_running_then_done_and_logs_zero_cost() -> None:
    store = FakeStore(_row())
    out = execute_public_audit(store, _settings(), "pa-1", runner=_ok_runner(82))
    assert out["status"] == "done"
    assert out["score"] == 82
    assert store.updates[0] == {"status": "running"}
    done = store.updates[-1]
    assert done["status"] == "done"
    assert done["score"] == 82
    assert done["run_uuid"] == "u-1"
    assert done["scores"] == {"overall": 82, "technical": 90}
    # No tier/client/timing columns are written to public_audits.
    assert "started_at" not in done and "finished_at" not in done
    assert "runtime_seconds" not in done and "tier" not in done
    assert store.costs == [0.0]  # public = Free -> always $0


def test_engine_failure_marks_failed_never_running() -> None:
    def _fail(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        return AuditRunResult(ok=False, run_uuid="u-9", error="engine timed out after 1500s")

    store = FakeStore(_row())
    out = execute_public_audit(store, _settings(), "pa-1", runner=_fail)
    assert out["status"] == "failed"
    final = store.updates[-1]
    assert final["status"] == "failed"
    assert "timed out" in final["error"]
    assert final["run_uuid"] == "u-9"
    assert store.costs == [0.0]  # engine started (run_uuid) -> $0 logged


def test_deferred_engine_unconfigured_marks_failed_no_cost() -> None:
    # Mirrors the DEFERRED live path: adapter returns ok=False, run_uuid None.
    def _unconfigured(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        return AuditRunResult(ok=False, error="audit engine is not configured")

    store = FakeStore(_row())
    out = execute_public_audit(store, _settings(), "pa-1", runner=_unconfigured)
    assert out["status"] == "failed"
    assert store.updates[-1]["status"] == "failed"
    assert store.costs == []  # never started -> no cost


def test_worker_exception_marks_failed_and_does_not_reraise() -> None:
    def _boom(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        raise RuntimeError("unexpected")

    store = FakeStore(_row())
    out = execute_public_audit(store, _settings(), "pa-1", runner=_boom)  # must NOT raise
    assert out["status"] == "failed"
    assert store.updates[-1]["status"] == "failed"
    assert "worker error" in store.updates[-1]["error"]
    assert store.costs == []


def test_missing_row_is_failed_noop() -> None:
    store = FakeStore(None)
    out = execute_public_audit(store, _settings(), "nope", runner=_ok_runner(1))
    assert out["status"] == "failed"
    assert store.updates == []


def test_already_done_is_idempotent() -> None:
    store = FakeStore(_row(status="done"))
    out = execute_public_audit(store, _settings(), "pa-1", runner=_ok_runner(1))
    assert out["status"] == "done"
    assert store.updates == []  # never re-runs the engine on redelivery
    assert store.costs == []


def test_public_task_is_registered() -> None:
    celery_import = __import__("workers.celery_app", fromlist=["celery_app"])
    celery_import.celery_app.loader.import_default_modules()
    assert "run_public_audit" in celery_import.celery_app.tasks
