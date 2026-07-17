"""Celery task: run one audit through the external engine, own its lifecycle.

State machine:  queued -> running -> (engine) -> done | failed.

The engine neither times out nor catches its own top-level errors, so THIS task
owns failure: the adapter enforces the hard timeout, and any timeout / crash /
non-zero exit / missing output marks the job ``failed`` - a run is NEVER left
stuck ``running``. The task never re-raises (with ``task_acks_late`` a raised
exception would redeliver the job and run the engine twice = double spend); it
always acks and returns a small result dict.

The DB + cost writes go through an injected ``AuditStore`` (backed by the
privileged ``service_role`` psycopg connection, which bypasses RLS by design) so
the core is unit-tested with a fake store and a mocked engine runner - no DB, no
real subprocess.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

from psycopg import sql
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.services.audit_artifacts import ArtifactStore, local_store_from_settings
from app.services.cost_gate import CostGate, GateContext, GateDecision
from app.services.cost_store import PostgresCostStore
from app.services.deliverables import emit_deliverable
from integrations.audit_engine import AuditEngineConfig, AuditRunResult, run_audit
from workers.celery_app import celery_app

logger = get_logger("workers.audit")

# Cost log grouping: the audit run is one logical "call" against this provider,
# gathered under the technical-audit dial feature.
_COST_FEATURE = "tech_audit"
_COST_PROVIDER = "audit_engine"
_COST_JOB_TYPE = "audit"
_PUBLIC_COST_JOB_TYPE = "public_audit"
_ERROR_MAX = 500  # cap the stored error string; it is server-side only


class _NullCostCache:
    """A no-op ``CostCache`` for the audit gate: a Paid audit is a unique live
    crawl of one URL, never a cache hit. Matches the content/off-page workers."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _dynamic_update(table: str, row_id: str, fields: dict[str, Any]) -> None:
    """UPDATE ``public.<table>`` SET the given fields WHERE id = row_id (privileged).

    Column names are static ``sql.Identifier``s (never a bound param); values are
    always bound. A dict value (``scores``) is wrapped for its jsonb column. Shared
    by the tenant-audit and public-audit stores so the injection-safe assignment
    builder lives in exactly one place.
    """
    if not fields:
        return
    assignments = sql.SQL(", ").join(
        sql.SQL("{} = %s").format(sql.Identifier(col)) for col in fields
    )
    stmt = sql.SQL("update {tbl} set {sets} where id = %s").format(
        tbl=sql.Identifier("public", table), sets=assignments
    )
    params = [Jsonb(v) if isinstance(v, dict) else v for v in fields.values()]
    with privileged_connection() as cur:
        cur.execute(stmt, [*params, row_id])


class AuditStore(Protocol):
    """The DB/cost seam the task needs (backed by the privileged connection)."""

    def load(self, audit_id: str) -> dict[str, Any] | None: ...
    def update(self, audit_id: str, fields: dict[str, Any]) -> None: ...
    def evaluate(self, row: dict[str, Any], cost: float) -> GateDecision: ...
    def record_cost(self, row: dict[str, Any], cost: float) -> None: ...


class _Runner(Protocol):
    def __call__(self, cfg: AuditEngineConfig, *, url: str, tier: str) -> AuditRunResult: ...


class SupabaseAuditStore:
    """Concrete ``AuditStore`` over ``privileged_connection`` (service_role, BYPASSRLS).

    Stateless: each method opens its own privileged connection, so the store
    takes no construction arguments.
    """

    def load(self, audit_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute("select * from public.audits where id = %s limit 1", (audit_id,))
            return cur.fetchone()

    def update(self, audit_id: str, fields: dict[str, Any]) -> None:
        _dynamic_update("audits", audit_id, fields)

    def evaluate(self, row: dict[str, Any], cost: float) -> GateDecision:
        """Pre-flight the paid audit spend through the SAME cost gate as every
        other paid worker (dial -> client cap -> daily spend-stop). The caller
        does NOT run the engine unless the decision is ``call``. This is the
        missing gate: previously the worker only LOGGED the cost post-hoc, so a
        Paid audit - the largest single spend - bypassed the caps entirely."""
        ctx = GateContext(
            feature_key=_COST_FEATURE,
            client_id=row.get("client_id"),
            provider=_COST_PROVIDER,
            estimated_cost=cost,
            job_id=str(row.get("id", "")),
            job_type=_COST_JOB_TYPE,
            client_name=row.get("client_name", ""),
        )
        return CostGate(PostgresCostStore(), _NullCostCache()).evaluate(ctx)

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
        PostgresCostStore().record_cost(ctx, cost, cached=False)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _month_label(iso: str) -> str:
    """A "July 2026" period label from an isoformat timestamp (empty if unparseable)."""
    try:
        return datetime.fromisoformat(iso).strftime("%B %Y")
    except ValueError:
        return ""


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


def _store_artifacts(
    artifacts: ArtifactStore | None, audit_id: str, result: AuditRunResult
) -> tuple[str | None, str | None]:
    """Copy the run's PDF + findings into the controlled root; never fatal."""
    if artifacts is None:
        return None, None
    try:
        return artifacts.store(
            audit_id, pdf_src=result.pdf_path, findings_src=result.findings_path
        )
    except Exception:
        logger.warning("audit_artifact_store_failed", audit_id=audit_id)
        return None, None


def execute_audit(
    store: AuditStore,
    settings: Settings,
    audit_id: str,
    *,
    runner: _Runner = run_audit,
    artifacts: ArtifactStore | None = None,
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

    # Cost gate (PAID only): a Paid audit is the single largest spend, so it must
    # clear the pre-flight gate (dial -> client cap -> daily spend-stop) BEFORE
    # the engine runs. A Free audit makes no paid-provider call, so it is never
    # gated ($0) - blocking a free run behind a budget cap would be wrong.
    if tier == "paid":
        decision = store.evaluate(row, settings.audit_paid_cost_estimate)
        if not decision.allowed:
            # off/byhand dial, over the client cap, or the daily stop engaged:
            # do NOT run the paid crawl. Terminal `failed` with the reason - never
            # left stuck; the operator lifts the block and re-runs the audit.
            logger.info("audit_cost_blocked", audit_id=audit_id, outcome=decision.outcome)
            store.update(
                audit_id,
                {
                    "status": "failed",
                    "error": f"cost gate: {decision.reason or decision.outcome}"[:_ERROR_MAX],
                    "finished_at": _utcnow().isoformat(),
                },
            )
            return {"audit_id": audit_id, "status": "blocked", "reason": decision.outcome}

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

    pdf_key, json_key = _store_artifacts(artifacts, audit_id, result)
    store.update(
        audit_id,
        {
            "status": "done",
            "run_uuid": result.run_uuid,
            "artifact_dir": result.artifact_dir,
            "score": result.score,
            "scores": result.scores,
            "pdf_path": pdf_key,
            "json_path": json_key,
            "runtime_seconds": result.runtime_seconds,
            "finished_at": finished,
        },
    )
    # Publish a client deliverable for a completed audit that produced a PDF
    # (best-effort; never fails the job). Public/unlinked audits have no client.
    if pdf_key and row.get("client_id"):
        emit_deliverable(
            client_id=str(row["client_id"]),
            client_name=row.get("client_name", ""),
            title="Technical SEO Audit",
            kind="Audit",
            requires="audit_scores",
            source_kind="audit",
            source_id=str(audit_id),
            icon="fact_check",
            artifact_key=pdf_key,
            media_type="application/pdf",
            period=_month_label(finished),
        )
    return {"audit_id": audit_id, "status": "done", "score": result.score}


@celery_app.task(name="run_audit")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_audit_job(audit_id: str) -> dict[str, Any]:
    """Entry point: wire the concrete store + settings and run the job."""
    settings = get_settings()
    store = SupabaseAuditStore()
    return execute_audit(
        store, settings, audit_id, artifacts=local_store_from_settings(settings)
    )


# --------------------------------------------------------------------------- #
# Public free-audit funnel (P6C): the SAME lifecycle over public.public_audits.
# There is NO tenant linkage - a public run is ALWAYS the Free tier ($0), so it
# has no client_id/tier/cost columns and never makes paid-provider spend. The
# store + engine adapter are reused; only the table + the always-free cost differ.
# --------------------------------------------------------------------------- #
class PublicAuditStore:
    """Concrete store for ``public.public_audits`` over ``privileged_connection``.

    The public leads table is written ONLY by the server (service_role), so the
    worker owns its state exactly like the tenant store - but the row has no
    tier/client/cost/timing columns, so ``update`` only ever touches columns that
    exist on ``public_audits`` (status, error, run_uuid, artifact_dir, results).
    """

    def load(self, public_audit_id: str) -> dict[str, Any] | None:
        with privileged_connection() as cur:
            cur.execute(
                "select * from public.public_audits where id = %s limit 1", (public_audit_id,)
            )
            return cur.fetchone()

    def update(self, public_audit_id: str, fields: dict[str, Any]) -> None:
        _dynamic_update("public_audits", public_audit_id, fields)

    def evaluate(self, row: dict[str, Any], cost: float) -> GateDecision:
        # A public audit is ALWAYS the Free tier ($0): it makes no paid-provider
        # call, so it is never gated. Present only to satisfy the AuditStore
        # protocol; ``execute_public_audit`` never calls it (it runs Free-only).
        return GateDecision("call", cost=0.0)

    def record_cost(self, row: dict[str, Any], cost: float) -> None:
        # No tenant: client_id is None (the money-dial handles a global/no-client
        # feature spend). A public run is Free, so cost is always 0.
        ctx = GateContext(
            feature_key=_COST_FEATURE,
            client_id=None,
            provider=_COST_PROVIDER,
            estimated_cost=cost,
            job_id=str(row.get("id", "")),
            job_type=_PUBLIC_COST_JOB_TYPE,
            client_name="",
        )
        PostgresCostStore().record_cost(ctx, cost, cached=False)


def execute_public_audit(
    store: AuditStore,
    settings: Settings,
    public_audit_id: str,
    *,
    runner: _Runner = run_audit,
    artifacts: ArtifactStore | None = None,
) -> dict[str, Any]:
    """Run a PUBLIC free-audit job and drive its row through the state machine.

    Mirrors ``execute_audit`` (queued -> running -> done|failed; never stuck,
    never re-raises, idempotent on redelivery) but over ``public_audits`` and
    ALWAYS at the Free tier ($0). Injected store + runner keep it unit-testable
    with fakes. The live engine run is DEFERRED exactly like the tenant worker:
    with no engine env the adapter returns ``ok=False`` (run_uuid None) and the
    row is marked ``failed`` without any spend.
    """
    row = store.load(public_audit_id)
    if row is None:
        logger.warning("public_audit_job_missing", public_audit_id=public_audit_id)
        return {"public_audit_id": public_audit_id, "status": "failed", "reason": "not found"}
    if row.get("status") == "done":
        # Idempotency: a redelivered job (acks_late) must not re-run the engine.
        return {"public_audit_id": public_audit_id, "status": "done", "reason": "already complete"}

    store.update(public_audit_id, {"status": "running"})

    try:
        # Public = Free tier: zero paid-provider spend by construction.
        result = runner(_config_from_settings(settings), url=row["url"], tier="free")
    except Exception as exc:  # the engine/adapter should not raise, but never trust it
        logger.exception("public_audit_job_crashed", public_audit_id=public_audit_id)
        store.update(
            public_audit_id,
            {"status": "failed", "error": f"worker error: {exc!r}"[:_ERROR_MAX]},
        )
        return {"public_audit_id": public_audit_id, "status": "failed", "reason": "worker error"}

    # Log the run through the cost path once the engine actually started (Free -> $0).
    if result.run_uuid is not None:
        _safe_record_cost(store, row, 0.0)

    if not result.ok:
        store.update(
            public_audit_id,
            {
                "status": "failed",
                "error": (result.error or "audit failed")[:_ERROR_MAX],
                "run_uuid": result.run_uuid,
                "artifact_dir": result.artifact_dir,
            },
        )
        return {"public_audit_id": public_audit_id, "status": "failed", "reason": result.error}

    pdf_key, json_key = _store_artifacts(artifacts, str(public_audit_id), result)
    store.update(
        public_audit_id,
        {
            "status": "done",
            "run_uuid": result.run_uuid,
            "artifact_dir": result.artifact_dir,
            "score": result.score,
            "scores": result.scores,
            "pdf_path": pdf_key,
            "json_path": json_key,
        },
    )
    return {"public_audit_id": public_audit_id, "status": "done", "score": result.score}


@celery_app.task(name="run_public_audit")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_public_audit_job(public_audit_id: str) -> dict[str, Any]:
    """Entry point: wire the public store + settings and run the public job."""
    settings = get_settings()
    store = PublicAuditStore()
    return execute_public_audit(
        store, settings, public_audit_id, artifacts=local_store_from_settings(settings)
    )
