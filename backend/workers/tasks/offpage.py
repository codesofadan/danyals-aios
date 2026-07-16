"""Off-page workers (7B-3): the Web 2.0 publish pipeline drivers + the backlink /
citation MONITORING sweep.

Three Celery tasks, all built on the never-stuck / never-re-raise / idempotent worker
template (``workers.tasks.audit``) - with ``task_acks_late`` a raised exception would
redeliver the job and re-run a PAID stage (double spend), so every task acks and
returns a small result dict:

* ``web2_write_job``   - drive one planned property plan -> write -> ``needs_review``
  (the human quality gate). Never publishes.
* ``web2_publish_job`` - after a lead APPROVES, drive publish -> verify -> track.
* ``monitor_offpage_job`` - pull a client's live backlink profile + citation listings,
  DIFF new/lost vs the stored ledger, apply the changes, and call the ``notify_new_lost``
  alert SEAM for new/lost links.

The pipeline stages themselves live in ``app.services.web2_pipeline`` (pure of Celery +
network); this module WIRES the concrete privileged store, the cost gate, and the
key/OAuth-gated providers, then runs the pure orchestration. The monitoring DIFF is
also a pure function (``diff_backlinks`` / ``diff_citations``) so it is unit-tested
directly with the deterministic provider fakes - no DB, no network.

7F-1 DECOUPLING: the alert delivery (the notifications service) is built in a PARALLEL
chunk. ``notify_new_lost`` imports it LAZILY + GUARDED, so this worker has NO hard
dependency on 7F-1: if the notifications service is not importable yet it logs a no-op
and returns. When 7F-1 lands, the same seam starts delivering with no change here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.config import Settings, get_settings
from app.db.offpage_repo import ServiceOffpageStore, service_offpage_store
from app.logging_setup import get_logger
from app.schemas.offpage import action_for
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from app.services.web2_pipeline import Web2Client, Web2Outcome, run_publish, run_write
from integrations.backlinks import BacklinkProvider, BacklinkRecord, backlink_provider_from_settings
from integrations.citations import CitationProvider, CitationRecord, citation_provider_from_settings
from integrations.content_providers import content_providers_from_settings
from integrations.web2_publishers import web2_publisher_from_settings

logger = get_logger("workers.offpage")

# Off-page monitoring pulls ride the 'backlinks' (off-page) money-dial; the provider
# labels are for the cost log only (not the frontend dial's Provider union).
_MONITOR_FEATURE = "backlinks"
_MONITOR_JOB_TYPE = "backlinks"

# The notify callback shape: (client_id, client_name, new_links, lost_rows).
NotifyFn = Callable[[str | None, str, list[BacklinkRecord], list[dict[str, Any]]], None]


class _NullCostCache:
    """A no-op ``CostCache`` for the worker's gate (these off-page pulls/publishes are
    not cache-keyed - a live monitoring pull must always hit the provider; the dial +
    budgets still gate it)."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


# --------------------------------------------------------------------------- #
# The notify / alert SEAM (7F-1 is parallel - lazy + guarded, never a hard dep).
# --------------------------------------------------------------------------- #
def notify_new_lost(
    client_id: str | None,
    client_name: str,
    new_links: list[BacklinkRecord],
    lost_links: list[dict[str, Any]],
) -> None:
    """Alert on new/lost backlinks. Best-effort: delivers via the notifications service
    when it is importable (7F-1), else logs a no-op. NEVER raises - a monitoring sweep
    must not fail because the alert channel is missing or hiccups."""
    if not new_links and not lost_links:
        return
    try:
        # 7F-1 (parallel): the concrete alert delivery. Import lazily + guarded so this
        # worker builds + runs with NO hard dependency on that chunk.
        from app.services.notifications import notify_offpage_changes
    except Exception:
        logger.info(
            "offpage_notify_noop", client=client_name,
            new=len(new_links), lost=len(lost_links),
        )
        return
    try:
        notify_offpage_changes(
            client_id=client_id, client_name=client_name,
            new_links=new_links, lost_links=lost_links,
        )
    except Exception:
        logger.warning("offpage_notify_failed", client=client_name)


# --------------------------------------------------------------------------- #
# Pure monitoring DIFFs (unit-tested directly with the provider fakes).
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class BacklinkDiff:
    """The monitoring delta: ``new`` records to insert + stored ``lost`` rows to mark."""

    new: list[BacklinkRecord] = field(default_factory=list)
    lost: list[dict[str, Any]] = field(default_factory=list)


def diff_backlinks(
    fetched: list[BacklinkRecord], stored: list[dict[str, Any]]
) -> BacklinkDiff:
    """Diff a freshly-pulled profile against the stored ledger, keyed by referring
    domain. NEW = a live (non-lost) domain not yet stored. LOST = a stored, not-already-
    lost domain that is gone from the pull OR the provider now reports it dropped. Pure
    + deterministic; a domain seen twice keeps its first occurrence."""
    stored_by_domain: dict[str, dict[str, Any]] = {}
    for row in stored:
        dom = str(row.get("ref_domain") or "").lower()
        if dom:
            stored_by_domain.setdefault(dom, row)
    fetched_by_domain: dict[str, BacklinkRecord] = {}
    for rec in fetched:
        dom = rec.ref_domain.lower()
        if dom:
            fetched_by_domain.setdefault(dom, rec)

    new = [
        rec for dom, rec in fetched_by_domain.items()
        if dom not in stored_by_domain and not rec.lost
    ]
    lost: list[dict[str, Any]] = []
    for dom, row in stored_by_domain.items():
        if str(row.get("status") or "") == "lost":
            continue  # already recorded lost
        hit = fetched_by_domain.get(dom)
        if hit is None or hit.lost:
            lost.append(row)
    return BacklinkDiff(new=new, lost=lost)


@dataclass(frozen=True)
class CitationDiff:
    """The citation delta: ``new`` directories to insert + stored rows whose NAP state
    ``changed`` (paired with the fresh record)."""

    new: list[CitationRecord] = field(default_factory=list)
    changed: list[tuple[dict[str, Any], CitationRecord]] = field(default_factory=list)


def diff_citations(
    fetched: list[CitationRecord], stored: list[dict[str, Any]]
) -> CitationDiff:
    """Diff pulled directory listings against the stored ledger, keyed by directory.
    NEW = a directory not yet stored. CHANGED = a stored directory whose NAP state now
    differs. Pure + deterministic."""
    stored_by_dir: dict[str, dict[str, Any]] = {}
    for row in stored:
        key = str(row.get("directory") or "").lower()
        if key:
            stored_by_dir.setdefault(key, row)
    new: list[CitationRecord] = []
    changed: list[tuple[dict[str, Any], CitationRecord]] = []
    for rec in fetched:
        existing = stored_by_dir.get(rec.directory.lower())
        if existing is None:
            new.append(rec)
        elif str(existing.get("nap_status") or "") != rec.nap_status:
            changed.append((existing, rec))
    return CitationDiff(new=new, changed=changed)


# --------------------------------------------------------------------------- #
# Monitoring orchestration (cost-gated; never raises).
# --------------------------------------------------------------------------- #
def run_backlink_monitor(
    store: ServiceOffpageStore,
    provider: BacklinkProvider,
    gate: CostGate,
    settings: Settings,
    *,
    client_id: str,
    client_name: str,
    domain: str,
    notify: NotifyFn = notify_new_lost,
    limit: int = 100,
) -> dict[str, Any]:
    """Pull ``domain``'s live profile, diff vs the ledger, apply new/lost, and alert.

    R5: cost pre-check on the 'backlinks' dial BEFORE the paid pull - a block skips the
    pull (no spend). Never raises: a provider failure returns an ``error`` result."""
    ctx = GateContext(
        feature_key=_MONITOR_FEATURE, client_id=client_id, provider="DataForSEO",
        estimated_cost=float(settings.offpage_monitor_cost_estimate), job_id=domain,
        job_type=_MONITOR_JOB_TYPE, client_name=client_name,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("backlink_monitor_blocked", domain=domain, outcome=decision.outcome)
        return {"state": "blocked", "reason": decision.outcome, "new": 0, "lost": 0}
    try:
        fetched = provider.fetch_backlinks(domain, limit=limit)
    except Exception:
        logger.exception("backlink_monitor_pull_failed", domain=domain)
        return {"state": "error", "reason": "provider pull failed", "new": 0, "lost": 0}
    gate.commit(ctx, ctx.estimated_cost)

    stored = store.list_backlinks_for_client(client_id)
    diff = diff_backlinks(fetched, stored)
    for rec in diff.new:
        store.insert_backlink(
            client_id=client_id, client_name=client_name, ref_domain=rec.ref_domain,
            anchor=rec.anchor, authority=rec.authority, spam=rec.spam,
            first_seen=rec.first_seen, status=rec.status,
        )
    for row in diff.lost:
        store.set_backlink_status(str(row["id"]), "lost")
    if diff.new or diff.lost:
        notify(client_id, client_name, diff.new, diff.lost)
    logger.info(
        "backlink_monitor_done", domain=domain, new=len(diff.new), lost=len(diff.lost)
    )
    return {
        "state": "ok", "new": len(diff.new), "lost": len(diff.lost),
        "notified": bool(diff.new or diff.lost),
    }


def run_citation_monitor(
    store: ServiceOffpageStore,
    provider: CitationProvider,
    gate: CostGate,
    settings: Settings,
    *,
    client_id: str,
    client_name: str,
    business: str,
    limit: int = 50,
) -> dict[str, Any]:
    """Pull ``business``'s directory listings, diff vs the ledger, and apply new/changed
    rows (NAP state drives the Submit/Update action). Cost-gated + never-raises like the
    backlink monitor."""
    ctx = GateContext(
        feature_key=_MONITOR_FEATURE, client_id=client_id, provider="BrightLocal",
        estimated_cost=float(settings.offpage_monitor_cost_estimate), job_id=business,
        job_type=_MONITOR_JOB_TYPE, client_name=client_name,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("citation_monitor_blocked", business=business, outcome=decision.outcome)
        return {"state": "blocked", "reason": decision.outcome, "new": 0, "changed": 0}
    try:
        fetched = provider.fetch_citations(business, limit=limit)
    except Exception:
        logger.exception("citation_monitor_pull_failed", business=business)
        return {"state": "error", "reason": "provider pull failed", "new": 0, "changed": 0}
    gate.commit(ctx, ctx.estimated_cost)

    stored = store.list_citations_for_client(client_id)
    diff = diff_citations(fetched, stored)
    for rec in diff.new:
        store.insert_citation(
            client_id=client_id, client_name=client_name, directory=rec.directory,
            nap_status=rec.nap_status, action=action_for(rec.nap_status), note=rec.note,
        )
    for existing, rec in diff.changed:
        store.update_citation_status(
            str(existing["id"]), nap_status=rec.nap_status,
            action=action_for(rec.nap_status), note=rec.note,
        )
    logger.info(
        "citation_monitor_done", business=business,
        new=len(diff.new), changed=len(diff.changed),
    )
    return {"state": "ok", "new": len(diff.new), "changed": len(diff.changed)}


# --------------------------------------------------------------------------- #
# Provider + client wiring (key/OAuth-gated; degraded -> None).
# --------------------------------------------------------------------------- #
def _writer_for(settings: Settings) -> tuple[Any | None, str]:
    """The content writer + its model tier, or ``(None, ...)`` degraded (no key)."""
    providers = content_providers_from_settings(settings)
    if providers is None:
        return None, "content-writer"
    return providers.writer, providers.model_writer


def _client_from_row(row: dict[str, Any]) -> Web2Client:
    """The minimal grounding client for a placement (display name + tenant id). The
    source-of-truth pack + fresh 6B context wiring is a later chunk; with none, the
    generator degrades ungrounded facts to ``[NEEDS:]`` gaps that HOLD at review."""
    client_id = row.get("client_id")
    return Web2Client(
        client_id=str(client_id) if client_id else None,
        name=str(row.get("client_name") or ""),
    )


# --------------------------------------------------------------------------- #
# Pure entry points (wire concrete deps + run the never-raising orchestration).
# --------------------------------------------------------------------------- #
def execute_web2_write(store: ServiceOffpageStore, settings: Settings, web2_id: str) -> Web2Outcome:
    """Draft one planned property to the review gate (wires the writer + gate)."""
    row = store.load_web2(web2_id)
    client = _client_from_row(row) if row else Web2Client(client_id=None, name="")
    writer, model = _writer_for(settings)
    return run_write(
        store, web2_id, client=client, writer=writer, gate=_gate(), settings=settings, model=model,
    )


def execute_web2_publish(store: ServiceOffpageStore, settings: Settings, web2_id: str) -> Web2Outcome:
    """Publish an APPROVED property (wires the OAuth-gated publisher + gate)."""
    publisher = web2_publisher_from_settings(settings)
    return run_publish(store, web2_id, publisher=publisher, gate=_gate(), settings=settings)


def execute_monitor(
    store: ServiceOffpageStore, settings: Settings, *, client_id: str, domain: str, business: str
) -> dict[str, Any]:
    """Run the backlink + citation monitoring sweep for one client (wires the key-gated
    providers). A degraded (keyless) provider is SKIPPED, never a crash."""
    gate = _gate()
    stored_name = ""
    row_source = store.list_backlinks_for_client(client_id)
    if row_source:
        stored_name = str(row_source[0].get("client_name") or "")

    result: dict[str, Any] = {"client_id": client_id}
    backlinks = backlink_provider_from_settings(settings)
    if backlinks is None:
        logger.info("backlink_monitor_degraded", client_id=client_id, reason="no_provider")
        result["backlinks"] = {"state": "degraded", "reason": "provider unconfigured"}
    else:
        result["backlinks"] = run_backlink_monitor(
            store, backlinks, gate, settings,
            client_id=client_id, client_name=stored_name, domain=domain,
        )

    citations = citation_provider_from_settings(settings)
    if citations is None or not business:
        logger.info("citation_monitor_degraded", client_id=client_id)
        result["citations"] = {"state": "degraded", "reason": "provider unconfigured or no business"}
    else:
        result["citations"] = run_citation_monitor(
            store, citations, gate, settings,
            client_id=client_id, client_name=stored_name, business=business,
        )
    return result


# --------------------------------------------------------------------------- #
# Celery entry points (thin; import the app lazily-free at module load).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="web2_write")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def web2_write_job(web2_id: str) -> dict[str, Any]:
    """Entry point: draft one planned Web 2.0 property to the review gate."""
    settings = get_settings()
    outcome = execute_web2_write(service_offpage_store(), settings, web2_id)
    return outcome.as_dict()


@celery_app.task(name="web2_publish")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def web2_publish_job(web2_id: str) -> dict[str, Any]:
    """Entry point: publish + verify + track an APPROVED Web 2.0 property."""
    settings = get_settings()
    outcome = execute_web2_publish(service_offpage_store(), settings, web2_id)
    return outcome.as_dict()


@celery_app.task(name="monitor_offpage")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def monitor_offpage_job(client_id: str, domain: str, business: str = "") -> dict[str, Any]:
    """Entry point: run the backlink + citation monitoring sweep for one client."""
    settings = get_settings()
    return execute_monitor(
        service_offpage_store(), settings, client_id=client_id, domain=domain, business=business,
    )
