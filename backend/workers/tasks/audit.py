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
from html import escape as html_escape
from typing import Any, Protocol

from psycopg import sql
from psycopg.types.json import Jsonb

from app.config import Settings, get_settings
from app.db.database import privileged_connection
from app.logging_setup import get_logger
from app.services import audit_ingest, audit_report, audit_workbook, pricing
from app.services.audit_artifacts import ArtifactStore, LocalArtifactStore, local_store_from_settings
from app.services.audit_sheets import SheetMeta, store_audit_sheets
from app.services.cost_gate import CostGate, GateContext, GateDecision
from app.services.cost_store import PostgresCostStore
from app.services.deliverables import emit_deliverable
from app.services.notifications import email_client_sync, notify_leads_sync
from integrations.audit_engine import AuditEngineConfig, AuditRunResult, run_audit
from workers.celery_app import celery_app

logger = get_logger("workers.audit")

# Cost log grouping: the audit run is one logical "call" against this provider,
# gathered under the technical-audit dial feature.
_COST_FEATURE = "tech_audit"
_COST_PROVIDER = "audit_engine"
_COST_JOB_TYPE = "audit"
# The PUBLIC funnel meters under its OWN dial key, not the paid audit's: it is
# unauthenticated, and an operator must be able to switch the lead magnet off in
# an abuse episode without disabling the paid product every client pays for. Must
# stay registered in `app.schemas.cost.DIAL_FEATURES` - an unregistered key
# resolves to "off" AND is rejected by PATCH /cost/dials, i.e. it is
# unswitchable-on, not merely defaulted-off.
_PUBLIC_COST_FEATURE = "public_audit"
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
    def __call__(
        self,
        cfg: AuditEngineConfig,
        *,
        url: str,
        tier: str,
        comprehensive: bool = False,
        depth: str | None = None,
        max_pages: int | None = None,
    ) -> AuditRunResult: ...


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
        other paid worker (spend halt -> dial -> client cap). The caller
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
    """Copy the run's PDF + findings + report.html into the controlled root; never fatal."""
    if artifacts is None:
        return None, None
    try:
        return artifacts.store(
            audit_id,
            pdf_src=result.pdf_path,
            findings_src=result.findings_path,
            html_src=result.html_path,
        )
    except Exception as exc:
        # Never fatal (a done audit must not fail on a copy hiccup), but log LOUDLY
        # with the reason: a real prod failure here (e.g. PermissionError writing to
        # the artifact volume, or ENOSPC) is exactly why pdf_path ends up NULL and no
        # download button appears - it must be diagnosable, not swallowed silently.
        logger.error(
            "audit_artifact_store_failed",
            audit_id=audit_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        return None, None


def _store_sheets(
    artifacts: ArtifactStore | None,
    audit_id: str,
    result: AuditRunResult,
    row: dict[str, Any],
    *,
    tier_label: str,
) -> None:
    """Build the role-based remediation sheets from findings.json; never fatal.

    Deterministic pure transform (no AI/paid calls), generated eagerly here
    alongside the PDF/findings copy so downloads just serve a file. Only the
    on-disk ``LocalArtifactStore`` supports it; a missing/malformed findings file
    skips (``store_audit_sheets`` returns ``[]``). A sheet-build error must NEVER
    fail a completed audit - it is swallowed and logged.
    """
    if not isinstance(artifacts, LocalArtifactStore):
        return
    try:
        meta = SheetMeta(
            audit_id=audit_id,
            client_name=str(row.get("client_name") or ""),
            url=str(row.get("url") or ""),
            tier=tier_label,
            generated_at=_utcnow().isoformat(),
        )
        store_audit_sheets(artifacts, audit_id, result.findings_path, meta)
    except Exception:
        logger.warning("audit_sheet_build_failed", audit_id=audit_id)


def _ingest_altitudes(
    artifacts: ArtifactStore | None,
    audit_id: str,
    result: AuditRunResult,
    row: dict[str, Any],
    *,
    tier_label: str,
) -> None:
    """Load the run into the three altitude tables, then build the workbook.

    This is what turns a 9.3 MB JSON blob into rows a human and a query can both
    use: on a real 197-page audit, 15,617 findings become 197 pages + 461 causes
    + 8,077 instances + 105 rollups in ~1.3s.

    NEVER FATAL, for the same reason ``_store_sheets`` is not: the audit itself
    has already succeeded and its report already exists. Losing a completed
    client deliverable because a supplementary transform failed would be a strictly
    worse outcome than shipping without the workbook. Failures are logged and the
    audit stays ``done``.
    """
    if not result.artifact_dir:
        return
    try:
        ingested = audit_ingest.ingest(
            audit_id=audit_id,
            client_id=str(row["client_id"]) if row.get("client_id") else None,
            artifact_dir=result.artifact_dir,
            site_url=str(row.get("url") or ""),
            run_uuid=str(result.run_uuid or ""),
            tier=tier_label.lower(),
            types=list(row.get("types") or []),
        )
        logger.info(
            "audit_altitudes_ingested",
            audit_id=audit_id,
            pages=ingested.pages,
            findings=ingested.findings,
            instances=ingested.instances,
            truncated=ingested.truncated,
        )
    except Exception as exc:
        logger.warning(
            "audit_altitude_ingest_failed",
            audit_id=audit_id,
            error=f"{type(exc).__name__}: {exc}",
        )
        return

    # The plan. Deterministic and model-free: if this fails the audit still has
    # its findings, so it is warned about rather than raised.
    try:
        planned = audit_ingest.store_roadmap(
            audit_id=audit_id,
            client_id=str(row["client_id"]) if row.get("client_id") else None,
        )
        logger.info("audit_roadmap_stored", audit_id=audit_id, **planned)
    except Exception as exc:
        logger.warning(
            "audit_roadmap_failed",
            audit_id=audit_id,
            error=f"{type(exc).__name__}: {exc}",
        )

    if not isinstance(artifacts, LocalArtifactStore):
        return
    try:
        built = audit_workbook.build(
            audit_id=audit_id,
            out_dir=artifacts.sheets_dir(audit_id),
            artifact_dir=result.artifact_dir,
            meta={
                "url": str(row.get("url") or ""),
                "client_name": str(row.get("client_name") or ""),
                "tier": tier_label,
                "generated_at": _utcnow().isoformat(),
            },
        )
        # The client-facing document, from the same rows. Deterministic and free:
        # no model call, so it costs nothing per report and cannot invent a number.
        audit_report.build(
            audit_id=audit_id,
            out_dir=artifacts.sheets_dir(audit_id),
            meta={
                "url": str(row.get("url") or ""),
                "client_name": str(row.get("client_name") or ""),
                "tier": tier_label,
                "generated_at": _utcnow().strftime("%d %B %Y"),
            },
        )
        logger.info(
            "audit_workbook_built",
            audit_id=audit_id,
            findings=built.findings,
            instances=built.instances,
            capped=built.capped,
        )
    except Exception as exc:
        logger.warning(
            "audit_workbook_build_failed",
            audit_id=audit_id,
            error=f"{type(exc).__name__}: {exc}",
        )


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
    # clear the pre-flight gate (spend halt -> dial -> client cap) BEFORE
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
        # The authenticated dashboard audit runs the consulting pipeline over EVERY
        # dimension; ``depth`` decides how much paid corroboration it buys (see
        # ``build_argv``). It replaced an audit-type picker that could not do what
        # its labels said - the deterministic crawl always ran in full, so a run
        # scoped to "on-page + technical" still returned GEO and strategy findings.
        # The public homepage funnel stays light/$0 - see below.
        result = runner(
            _config_from_settings(settings),
            url=row["url"],
            tier=tier,
            comprehensive=True,
            depth=row.get("depth"),
            # The breadth the OPERATOR asked for, snapshotted on the row at
            # enqueue. Null on rows written before migration 0084, which falls
            # back to the config default - i.e. exactly what those rows already
            # ran at, so a queued-before-deploy job is unaffected.
            max_pages=row.get("max_pages"),
        )
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

    # Commit the run cost through the Part-2 cost path once the engine has actually
    # started (a run_uuid was minted). The cost is computed at RUNTIME from the
    # engine's run.json observables (real token usage + serper queries when the
    # engine reports a `usage` block; else derived from pages_crawled + the agent
    # fan-out) -- NEVER the flat estimate, which only fed the pre-flight gate above.
    #
    # THE MODE IS THE ENGINE'S, NOT AN ASSUMPTION. This used to pass `mode="paid"`
    # unconditionally, on the reasoning that "a dashboard audit is always the
    # comprehensive run". That stopped being true when depth replaced the audit-type
    # picker: `free` depth now runs `--mode free`, which the engine enforces by
    # clearing every provider - so hardcoding paid would bill a real figure against
    # a run that provably spent nothing. The public funnel already read the engine's
    # own reported mode for exactly this reason; both paths now agree.
    #
    # The fallback is the mode we INVOKED with, derived from the row's depth, so a
    # run that died before writing run.json is still billed if it could have spent.
    # Fail-closed on money, in the direction that cannot under-report.
    if result.run_uuid is not None:
        invoked_mode = "free" if (row.get("depth") or "standard") == "free" else "paid"
        cost = pricing.audit_cost(
            settings,
            pages_crawled=result.pages_crawled,
            mode=result.mode or invoked_mode,
            usage=result.usage,
        )
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
    # Role-based remediation sheets (xlsx + csvs) from the SAME findings.json.
    _store_sheets(artifacts, audit_id, result, row, tier_label="Paid" if tier == "paid" else "Free")
    _ingest_altitudes(artifacts, audit_id, result, row, tier_label="Paid" if tier == "paid" else "Free")
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
    # Email + in-app the leads that a report is ready (best-effort; never fails the
    # job). The audits ledger carries no requester column, so this addresses the
    # review/lead queue. audit_done is a NOTIF_EVENTS key (email default on), so it
    # fires through Resend when RESEND_API_KEY is present, else in-app only.
    subject = row.get("client_name") or row.get("url") or "a client"
    notify_leads_sync(
        "audit_done",
        f"Audit ready: {row.get('url') or subject}",
        f"The audit for {subject} finished (score {result.score}). "
        "The report is ready to review and deliver.",
    )
    # ADMIN/LEAD -> CLIENT: email the client that their report is ready in the portal
    # (best-effort; never fails the job). Only for a client-linked run (a public /
    # unlinked audit has no tenant) that produced a downloadable PDF. email_client_sync
    # resolves the client's contact email + is key-gated, so a keyless/failing provider
    # or an unresolvable recipient degrades silently - it can never break the done job.
    client_id = row.get("client_id")
    if client_id and pdf_key:
        _email_client_audit_ready(
            str(client_id), str(row.get("client_name") or ""), str(row.get("url") or "")
        )
    return {"audit_id": audit_id, "status": "done", "score": result.score}


def _email_client_audit_ready(client_id: str, client_name: str, url: str) -> None:
    """Best-effort: email the client that their SEO audit report is ready."""
    who = client_name or "there"
    site = f" for {url}" if url else ""
    subject = "Your SEO audit report is ready"
    text = (
        f"Hi {who}, your SEO audit{site} is complete. Sign in to your client portal to "
        "view the findings and download the full report."
    )
    html = (
        f"<h2>Your SEO audit report is ready</h2>"
        f"<p>Hi {html_escape(who)}, your SEO audit{html_escape(site)} is complete.</p>"
        "<p>Sign in to your client portal to view the findings and download the full report.</p>"
    )
    email_client_sync(client_id, subject, html, text)


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
# There is NO tenant linkage - a public run has no client_id/tier/cost columns.
# COST NOTE: the public/free audit is now the COMPREHENSIVE lead-gen run (all six
# dimensions with real data), so the engine DOES spend on the wired providers
# (Serper + Google Places, degrade-safe) per run - it is no longer strictly $0 of
# provider spend. There is no tenant to attribute that spend to, so the public
# cost ledger still records the funnel entry at $0 (the money-dial accounts for
# the run's existence); the real provider spend is intentional and untracked
# per-run here. The store + engine adapter are reused; only the table differs.
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

    def _ctx(self, row: dict[str, Any], cost: float) -> GateContext:
        """The gate context for one public run.

        No tenant, so ``client_id`` is ``None`` and no per-client budget cap
        applies - the agency-global spend halt and the ``public_audit`` dial are
        what bound this path.
        """
        return GateContext(
            feature_key=_PUBLIC_COST_FEATURE,
            client_id=None,
            provider=_COST_PROVIDER,
            estimated_cost=cost,
            job_id=str(row.get("id", "")),
            job_type=_PUBLIC_COST_JOB_TYPE,
            client_name="",
        )

    def evaluate(self, row: dict[str, Any], cost: float) -> GateDecision:
        """Pre-flight the run through the SAME gate every paid call passes.

        This used to return an unconditional ``call`` on the reasoning that a
        public run is free and therefore needs no gate. That reasoning is what let
        the funnel bypass the gate entirely while ``build_argv`` was silently
        running it with paid providers on - the one path in the system that could
        reach a provider without the gate ever seeing it. The gate is now consulted
        on every run, so a spend halt or an ``off``/``byhand`` dial stops the
        funnel whatever the engine is currently configured to do.
        """
        return CostGate(PostgresCostStore(), _NullCostCache()).evaluate(self._ctx(row, cost))

    def record_cost(self, row: dict[str, Any], cost: float) -> None:
        """Commit the run's REAL cost.

        The caller computes it from the run's own observables
        (``pricing.audit_cost``); this method no longer assumes zero.
        """
        PostgresCostStore().record_cost(self._ctx(row, cost), cost, cached=False)


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
    ALWAYS at the Free tier: a CONDENSED ``--mode free`` engine run that calls no
    paid provider (DECISIONS_LOG D-1; see ``build_argv``).

    Two P0-2 changes from the previous behaviour:

    * **The run is gated.** The ``public_audit`` dial and the agency-global spend
      halt are consulted BEFORE the engine is launched. This path used to be the
      one place in the system that could reach a provider without the gate ever
      seeing it.
    * **The committed cost is DERIVED, never asserted.** It is
      ``pricing.audit_cost`` over the engine's own ``run.json`` observables - the
      same computation the paid path uses. For a genuine free run that is 0.0, but
      it is 0.0 *because the run reported* ``mode="free"``, not because a literal
      was written here. If this path is ever re-widened, the ledger becomes
      truthful automatically instead of silently staying at zero.

    Injected store + runner keep it unit-testable with fakes. The live engine run
    is DEFERRED exactly like the tenant worker: with no engine env the adapter
    returns ``ok=False`` (run_uuid None) and the row is marked ``failed``.
    """
    row = store.load(public_audit_id)
    if row is None:
        logger.warning("public_audit_job_missing", public_audit_id=public_audit_id)
        return {"public_audit_id": public_audit_id, "status": "failed", "reason": "not found"}
    if row.get("status") == "done":
        # Idempotency: a redelivered job (acks_late) must not re-run the engine.
        return {"public_audit_id": public_audit_id, "status": "done", "reason": "already complete"}

    # Pre-flight the gate BEFORE launching the engine. A spend halt or an
    # `off`/`byhand` dial must stop the funnel here, not after the work is done.
    # The row is marked failed with the operator-set reason on it, so the lead
    # sees an honest "unavailable", never a fabricated report.
    decision = store.evaluate(row, 0.0)
    if not decision.allowed:
        logger.info(
            "public_audit_gate_blocked",
            public_audit_id=public_audit_id,
            outcome=decision.outcome,
            reason=decision.reason,
        )
        store.update(
            public_audit_id,
            {
                "status": "failed",
                "error": f"free audit unavailable: {decision.reason or decision.outcome}"[:_ERROR_MAX],
            },
        )
        return {
            "public_audit_id": public_audit_id,
            "status": "blocked",
            "reason": decision.reason or decision.outcome,
        }

    store.update(public_audit_id, {"status": "running"})

    try:
        # CONDENSED + GENUINELY FREE: `tier="free"` with `comprehensive=False`
        # builds `--mode free`, which the engine enforces by hard-clearing every
        # paid integration after parsing. No Serper, no Places, no citations, no
        # PSI - so there is no per-run spend to meter and no denial-of-wallet
        # vector on an unauthenticated endpoint. See build_argv's FREE FUNNEL note.
        result = runner(_config_from_settings(settings), url=row["url"], tier="free")
    except Exception as exc:  # the engine/adapter should not raise, but never trust it
        logger.exception("public_audit_job_crashed", public_audit_id=public_audit_id)
        store.update(
            public_audit_id,
            {"status": "failed", "error": f"worker error: {exc!r}"[:_ERROR_MAX]},
        )
        return {"public_audit_id": public_audit_id, "status": "failed", "reason": "worker error"}

    # Commit the run's cost once the engine actually started. COMPUTED from the
    # run's own observables via the same function the paid path uses - never a
    # literal. `mode="free"` makes this 0.0 by derivation; any other mode prices
    # the real work. This is the fix for "the free audit spends real money and
    # logs $0.00": the number now follows the run instead of asserting it.
    if result.run_uuid is not None:
        # The engine's OWN reported mode is authoritative - it knows what it
        # actually ran. When it reports none (an older build, or a run that died
        # before writing run.json), fall back to the mode we INVOKED it with
        # rather than to the derived paid estimate: charging this path for a
        # 21-agent fan-out that `--mode free` makes impossible would be a
        # fabricated cost in the other direction.
        cost = pricing.audit_cost(
            settings,
            pages_crawled=result.pages_crawled,
            mode=result.mode or "free",
            usage=result.usage,
        )
        if cost > 0:
            # A "free" funnel that priced above zero means the engine did paid
            # work. Record it truthfully AND say so loudly - this is exactly the
            # condition that went unnoticed before, and it must never be silent.
            logger.warning(
                "public_audit_incurred_cost",
                public_audit_id=public_audit_id,
                cost=cost,
                engine_mode=result.mode,
                pages_crawled=result.pages_crawled,
            )
        _safe_record_cost(store, row, cost)

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
    # Role-based remediation sheets from the SAME findings.json (public = Free).
    _store_sheets(artifacts, str(public_audit_id), result, row, tier_label="Free")
    return {"public_audit_id": public_audit_id, "status": "done", "score": result.score}


@celery_app.task(name="run_public_audit")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_public_audit_job(public_audit_id: str) -> dict[str, Any]:
    """Entry point: wire the public store + settings and run the public job."""
    settings = get_settings()
    store = PublicAuditStore()
    return execute_public_audit(
        store, settings, public_audit_id, artifacts=local_store_from_settings(settings)
    )
