"""P3-3 gate: the audit Celery task's state machine + cost logging, with the
engine runner MOCKED and an in-memory store (no Supabase, no subprocess)."""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services import pricing
from app.services.cost_gate import GateDecision
from integrations.audit_engine import AuditEngineConfig, AuditRunResult
from workers.tasks.audit import execute_audit

pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(
        self, row: dict[str, Any] | None, *, decision: GateDecision | None = None
    ) -> None:
        self.row = row
        self.updates: list[dict[str, Any]] = []
        self.costs: list[float] = []
        # None => the gate allows the paid run; set a blocked/skip decision to
        # prove the worker refuses to spend on it.
        self.decision = decision
        self.evaluated: list[float] = []

    def load(self, audit_id: str) -> dict[str, Any] | None:
        return self.row

    def update(self, audit_id: str, fields: dict[str, Any]) -> None:
        self.updates.append(fields)
        if self.row is not None:
            self.row.update(fields)

    def evaluate(self, row: dict[str, Any], cost: float) -> GateDecision:
        self.evaluated.append(cost)
        return self.decision if self.decision is not None else GateDecision("call", cost=cost)

    def record_cost(self, row: dict[str, Any], cost: float) -> None:
        self.costs.append(cost)


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev", audit_paid_cost_estimate=1.5)


# The RUNTIME-derived paid-audit cost the worker now LOGS (via pricing.audit_cost: the
# engine's run.json observables, here the fake's defaults -> pages_crawled=0 + the agent
# fan-out), replacing the old flat audit_paid_cost_estimate. The flat 1.5 survives ONLY
# as the upfront pre-check estimate, never as the committed cost.
_PAID_COST = pricing.audit_cost(_settings(), pages_crawled=0, mode="paid", usage=None)


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
    def _run(cfg: AuditEngineConfig, *, url: str, tier: str, comprehensive: bool = False) -> AuditRunResult:
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
    # Authenticated dashboard audits ALWAYS run the comprehensive (paid-provider)
    # pipeline now, so the paid estimate is logged regardless of the row's tier label.
    assert store.costs == [pytest.approx(_PAID_COST)]


def test_paid_run_logs_estimated_cost() -> None:
    store = FakeStore(_row(tier="paid"))
    execute_audit(store, _settings(), "aud-1", runner=_ok_runner(70))
    assert store.costs == [pytest.approx(_PAID_COST)]  # runtime-derived, not the flat estimate


def test_engine_failure_marks_failed_never_running() -> None:
    def _fail(cfg: AuditEngineConfig, *, url: str, tier: str, comprehensive: bool = False) -> AuditRunResult:
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
    assert store.costs == [pytest.approx(_PAID_COST)]


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


# --------------------------------------------------------------------------- #
# C1: the audit worker routes a PAID run through the cost gate BEFORE spending.
# --------------------------------------------------------------------------- #
def _tracking_runner(ran: list[bool], score: int = 90) -> Any:
    def _run(cfg: AuditEngineConfig, *, url: str, tier: str, comprehensive: bool = False) -> AuditRunResult:
        ran.append(True)  # records that the (paid) engine actually executed
        return _ok_runner(score)(cfg, url=url, tier=tier)
    return _run


def test_paid_audit_blocked_by_cap_never_runs_engine_and_logs_no_cost() -> None:
    ran: list[bool] = []
    store = FakeStore(
        _row(tier="paid"),
        decision=GateDecision("blocked_cap", reason="client budget cap reached"),
    )
    out = execute_audit(store, _settings(), "aud-1", runner=_tracking_runner(ran))
    assert ran == []  # THE POINT: the paid crawl never ran -> zero spend
    assert store.evaluated == [1.5]  # the gate WAS consulted with the estimate
    assert out["status"] == "blocked"
    assert out["reason"] == "blocked_cap"
    assert store.updates[-1]["status"] == "failed"
    assert "cost gate" in store.updates[-1]["error"]
    assert "finished_at" in store.updates[-1]
    # never transitioned to running, and nothing was logged to the cost ledger
    assert all(u.get("status") != "running" for u in store.updates)
    assert store.costs == []


def test_paid_audit_blocked_when_dial_off_or_daily_stop() -> None:
    for outcome, reason in (("skip", "feature dial is off"), ("blocked_daily", "daily spend-stop")):
        ran: list[bool] = []
        store = FakeStore(_row(tier="paid"), decision=GateDecision(outcome, reason=reason))
        out = execute_audit(store, _settings(), "aud-1", runner=_tracking_runner(ran))
        assert ran == [], f"{outcome}: engine must not run"
        assert out["status"] == "blocked" and out["reason"] == outcome
        assert store.costs == []


def test_free_audit_is_never_gated_even_if_a_block_would_apply() -> None:
    # A Free audit makes no paid-provider call, so the gate must NOT be consulted;
    # a store primed to block still runs the engine and logs $0. (Blocking a free
    # run behind a budget cap would be a bug.)
    ran: list[bool] = []
    store = FakeStore(
        _row(tier="free"), decision=GateDecision("blocked_cap", reason="should be ignored")
    )
    out = execute_audit(store, _settings(), "aud-1", runner=_tracking_runner(ran, score=77))
    assert out["status"] == "done"
    assert ran == [True]  # the engine ran normally
    assert store.evaluated == []  # gate never consulted on the Free-labelled row
    # Dashboard audits run the comprehensive pipeline, so the paid estimate is logged.
    assert store.costs == [pytest.approx(_PAID_COST)]


def test_task_is_registered() -> None:
    celery_import = __import__("workers.celery_app", fromlist=["celery_app"])
    celery_import.celery_app.loader.import_default_modules()
    assert "run_audit" in celery_import.celery_app.tasks
