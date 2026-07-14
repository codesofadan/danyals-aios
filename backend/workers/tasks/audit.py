"""Celery task: run one audit through the external engine, own its lifecycle.

State machine:  queued -> running -> (engine) -> done | failed.

The engine neither times out nor catches its own top-level errors, so THIS task
owns failure: the adapter enforces the hard timeout, and any timeout / crash /
non-zero exit / missing output marks the job ``failed`` - a run is NEVER left
stuck ``running``. The task never re-raises (with ``task_acks_late`` a raised
exception would redeliver the job and run the engine twice = double spend); it
always acks and returns a small result dict.

The DB + cost writes go through an injected ``AuditStore`` (service_role admin
client, which bypasses RLS by design) so the core is unit-tested with a fake
store and a mocked engine runner - no Supabase, no real subprocess.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from app.config import Settings, get_settings
from app.db.supabase import get_admin_client
from app.logging_setup import get_logger
from app.services.cost_gate import GateContext
from app.services.cost_store import SupabaseCostStore
from integrations.audit_engine import AuditEngineConfig, AuditRunResult, run_audit
from workers.celery_app import celery_app

logger = get_logger("workers.audit")

# Cost log grouping: the audit run is one logical "call" against this provider,
# gathered under the technical-audit dial feature.
_COST_FEATURE = "tech_audit"
_COST_PROVIDER = "audit_engine"
_COST_JOB_TYPE = "audit"
_ERROR_MAX = 500  # cap the stored error string; it is server-side only


class AuditStore(Protocol):
    """The DB/cost seam the task needs (backed by the service_role client)."""

    def load(self, audit_id: str) -> dict[str, Any] | None: ...
    def update(self, audit_id: str, fields: dict[str, Any]) -> None: ...
    def record_cost(self, row: dict[str, Any], cost: float) -> None: ...


class _Runner(Protocol):
    def __call__(self, cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult: ...


class SupabaseAuditStore:
    """Concrete ``AuditStore`` over the service_role admin client."""

    def __init__(self, admin: Any) -> None:
        self._admin = admin

    def load(self, audit_id: str) -> dict[str, Any] | None:
        resp = self._admin.table("audits").select("*").eq("id", audit_id).limit(1).execute()
        rows = resp.data or []
        return rows[0] if rows else None

    def update(self, audit_id: str, fields: dict[str, Any]) -> None:
        self._admin.table("audits").update(fields).eq("id", audit_id).execute()

    def record_cost(self, row: dict[str, Any], cost: float) -> None:
        ctx = GateContext(
            feature_key=_COST_FEATURE,
            client_id=row.get("client_id"),
            provider=_COST_PROVIDER,
            estimated_cost=cost,
            job_id=str(row.get("id", "")),
            job_type=_COST_JOB_TYPE,
            client_name=row.get("client_name", ""),
        )
        SupabaseCostStore(self._admin).record_cost(ctx, cost, cached=False)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _config_from_settings(settings: Settings) -> AuditEngineConfig:
    return AuditEngineConfig(
        engine_dir=settings.audit_engine_dir or "",
        engine_python=settings.audit_engine_python or "",
        timeout_seconds=settings.audit_timeout_seconds,
        max_pages=settings.audit_max_pages,
        profile=settings.audit_profile,
    )


def _safe_record_cost(store: AuditStore, row: dict[str, Any], cost: float) -> None:
    """Log the run cost; a logging hiccup must never fail the completed job."""
    try:
        store.record_cost(row, cost)
    except Exception:
        logger.warning("audit_cost_log_failed", audit_id=str(row.get("id", "")))


def execute_audit(
    store: AuditStore,
    settings: Settings,
    audit_id: str,
    *,
    runner: _Runner = run_audit,
) -> dict[str, Any]:
    """Run the audit job and drive the row through its state machine.

    Pure of Celery + Supabase specifics (both are injected), so it is fully
    unit-testable. Returns a small status dict; never raises.
    """
    row = store.load(audit_id)
    if row is None:
        logger.warning("audit_job_missing", audit_id=audit_id)
        return {"audit_id": audit_id, "status": "failed", "reason": "not found"}
    if row.get("status") == "done":
        # Idempotency: a redelivered job (acks_late) must not re-run the engine.
        return {"audit_id": audit_id, "status": "done", "reason": "already complete"}

    tier = row.get("tier", "free")
    store.update(audit_id, {"status": "running", "started_at": _utcnow().isoformat()})

    try:
        result = runner(_config_from_settings(settings), url=row["url"], tier=tier)
    except Exception as exc:  # the engine/adapter should not raise, but never trust it
        logger.exception("audit_job_crashed", audit_id=audit_id)
        store.update(
            audit_id,
            {
                "status": "failed",
                "error": f"worker error: {exc!r}"[:_ERROR_MAX],
                "finished_at": _utcnow().isoformat(),
            },
        )
        return {"audit_id": audit_id, "status": "failed", "reason": "worker error"}

    finished = _utcnow().isoformat()

    # Log the run cost through the Part-2 cost path once the engine has actually
    # started (a run_uuid was minted): Free = $0, Paid = the configured estimate
    # (the engine reports no machine-readable spend).
    if result.run_uuid is not None:
        cost = settings.audit_paid_cost_estimate if tier == "paid" else 0.0
        _safe_record_cost(store, row, cost)

    if not result.ok:
        store.update(
            audit_id,
            {
                "status": "failed",
                "error": (result.error or "audit failed")[:_ERROR_MAX],
                "run_uuid": result.run_uuid,
                "artifact_dir": result.artifact_dir,
                "runtime_seconds": result.runtime_seconds,
                "finished_at": finished,
            },
        )
        return {"audit_id": audit_id, "status": "failed", "reason": result.error}

    store.update(
        audit_id,
        {
            "status": "done",
            "run_uuid": result.run_uuid,
            "artifact_dir": result.artifact_dir,
            "score": result.score,
            "scores": result.scores,
            "runtime_seconds": result.runtime_seconds,
            "finished_at": finished,
        },
    )
    return {"audit_id": audit_id, "status": "done", "score": result.score}


@celery_app.task(name="run_audit")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_audit_job(audit_id: str) -> dict[str, Any]:
    """Entry point: wire the concrete store + settings and run the job."""
    store = SupabaseAuditStore(get_admin_client())
    return execute_audit(store, get_settings(), audit_id)
