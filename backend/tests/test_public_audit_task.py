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
        self.evaluated: list[float] = []
        self.gate = GateDecision("call", cost=0.0)

    def load(self, public_audit_id: str) -> dict[str, Any] | None:
        return self.row

    def update(self, public_audit_id: str, fields: dict[str, Any]) -> None:
        self.updates.append(fields)
        if self.row is not None:
            self.row.update(fields)

    # The gate verdict this store returns. `execute_public_audit` DOES call
    # `evaluate` now: the funnel is pre-flighted against the `public_audit` dial
    # and the agency-global spend halt before the engine is launched.
    gate: GateDecision = GateDecision("call", cost=0.0)

    def evaluate(self, row: dict[str, Any], cost: float) -> GateDecision:
        self.evaluated.append(cost)
        return self.gate

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


# --------------------------------------------------------------------------- #
# P0-2 · the funnel is gated, and its cost is DERIVED
# --------------------------------------------------------------------------- #


def test_the_gate_is_consulted_before_the_engine_is_launched() -> None:
    """The public path used to be the one place that could reach a provider
    without the gate ever seeing it: `evaluate` returned an unconditional
    ``call``. It must now be asked, on every run, before any work starts."""
    store = FakeStore(_row())
    launched: list[str] = []

    def _runner(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        launched.append(url)
        return AuditRunResult(ok=True, run_uuid="u-1", artifact_dir="/a", score=70, mode="free")

    execute_public_audit(store, _settings(), "pa-1", runner=_runner)  # type: ignore[arg-type]
    assert store.evaluated, "the gate was never consulted"
    assert launched == ["https://example.com"]


def test_a_spend_halt_stops_the_funnel_without_running_the_engine() -> None:
    """The agency-global kill-switch must reach the free funnel like everything else."""
    store = FakeStore(_row())
    store.gate = GateDecision("blocked_halt", reason="API spend is halted")
    launched: list[str] = []

    def _runner(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        launched.append(url)
        raise AssertionError("the engine must not run while spend is halted")

    out = execute_public_audit(store, _settings(), "pa-1", runner=_runner)  # type: ignore[arg-type]
    assert out["status"] == "blocked"
    assert launched == []
    assert store.costs == []  # nothing spent, so nothing logged
    # The row carries an honest reason, never a half-finished "done".
    assert store.row is not None and store.row["status"] == "failed"
    assert "halted" in store.row["error"]


def test_an_off_dial_stops_the_funnel_without_running_the_engine() -> None:
    """An operator switching the lead magnet off during an abuse episode."""
    store = FakeStore(_row())
    store.gate = GateDecision("skip", reason="feature dial is off")

    def _runner(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        raise AssertionError("the engine must not run while the dial is off")

    out = execute_public_audit(store, _settings(), "pa-1", runner=_runner)  # type: ignore[arg-type]
    assert out["status"] == "blocked"
    assert store.row is not None and store.row["status"] == "failed"


def test_the_committed_cost_is_derived_from_the_engines_reported_mode() -> None:
    """A free run logs $0 BECAUSE the run reported ``mode="free"``.

    The defect this replaces was a literal `0.0` committed regardless of what the
    engine actually did — which is how a run with Serper, Places, citations and
    PSI enabled recorded $0.00.
    """
    store = FakeStore(_row())

    def _runner(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        return AuditRunResult(
            ok=True, run_uuid="u-1", artifact_dir="/a", score=70,
            mode="free", pages_crawled=12,
        )

    execute_public_audit(store, _settings(), "pa-1", runner=_runner)  # type: ignore[arg-type]
    assert store.costs == [0.0]


def test_a_funnel_that_did_paid_work_records_the_real_cost_not_zero() -> None:
    """The regression test for the original defect.

    If anything ever re-widens this path, the ledger must show the money. Proven
    by handing the worker a run that reports paid work and asserting the committed
    figure is the REAL computed cost, not the previous hardcoded zero.
    """
    from app.services import pricing

    store = FakeStore(_row())
    settings = _settings()

    def _runner(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        return AuditRunResult(
            ok=True, run_uuid="u-1", artifact_dir="/a", score=70,
            mode="paid", pages_crawled=40,
            usage={"serper_queries": 25, "places_calls": 10,
                   "input_tokens": 50_000, "output_tokens": 8_000,
                   "model": "claude-haiku-4-5"},
        )

    execute_public_audit(store, settings, "pa-1", runner=_runner)  # type: ignore[arg-type]
    expected = pricing.audit_cost(
        settings, pages_crawled=40, mode="paid",
        usage={"serper_queries": 25, "places_calls": 10,
               "input_tokens": 50_000, "output_tokens": 8_000,
               "model": "claude-haiku-4-5"},
    )
    assert expected > 0, "the fixture must represent real spend for this test to mean anything"
    assert store.costs == [expected]


def test_an_engine_that_reports_no_mode_is_priced_as_what_we_asked_for() -> None:
    """A run that dies before writing run.json must not be charged for a 21-agent
    fan-out that ``--mode free`` makes impossible — that is a fabricated cost in
    the other direction."""
    store = FakeStore(_row())

    def _runner(cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult:
        # ok=False but a run_uuid was minted: the engine started, then failed.
        return AuditRunResult(ok=False, run_uuid="u-1", error="boom", mode="", pages_crawled=0)

    execute_public_audit(store, _settings(), "pa-1", runner=_runner)  # type: ignore[arg-type]
    assert store.costs == [0.0]
