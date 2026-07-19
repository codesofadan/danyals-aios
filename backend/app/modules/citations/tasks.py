"""Citation-submission worker (7B-4): the never-stuck / never-re-raise / idempotent
driver that claims a QUEUED citation row, dispatches it to the right engine (a
direct API, the self-hosted Playwright bot, or the Apify fallback), and tracks the
outcome. Mirrors ``workers/tasks/offpage.py``'s Web 2.0 tasks exactly - with
``task_acks_late`` a raised exception would redeliver the job and re-run a PAID
stage (double spend), so this always acks and returns a small result dict.

``_FEATURE`` is the money-dial this module's only paid stage gates through -
``tests/test_dial_registration.py`` auto-discovers this constant and fails the
build if it is not registered in ``app/schemas/cost.py`` (the exact defect that bit
four Part-8 modules before that guard existed).
"""

from __future__ import annotations

import contextlib
from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.citations.repo import ServiceCitationsStore, service_citations_store
from app.modules.citations.service import job_from_row, submitter_for
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.captcha_solver import captcha_solver_from_settings
from integrations.citation_apify import apify_submitter_from_settings
from integrations.citation_apis import BingPlacesSubmitter, FoursquareSubmitter
from integrations.citation_bot import citation_bot_from_settings
from integrations.citation_submitters import CitationSubmitter
from integrations.errors import ProviderNotConfiguredError

logger = get_logger("app.modules.citations.tasks")

_FEATURE = "citations"
_JOB_TYPE = "citations"
_ERROR_MAX = 500
_TERMINAL = frozenset({"submitted", "verified", "failed"})


class _NullCostCache:
    """A no-op ``CostCache`` - a citation submit is never cache-keyed (a live
    submission must always run; the dial + budgets still gate it)."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


def _api_submitters(settings: Settings) -> dict[str, CitationSubmitter]:
    """The direct-API engines, keyed to match a directory's ``submit_method``
    suffix (``api:bing_places`` -> key ``bing_places``). Each is built only when its
    key is present, so the dict only ever holds real, callable clients -
    ``submitter_for`` reports the honest "not configured" reason for anything
    missing rather than a caller having to None-check twice."""
    out: dict[str, CitationSubmitter] = {}
    if settings.bing_places_api_key:
        with contextlib.suppress(ProviderNotConfiguredError):
            out["bing_places"] = BingPlacesSubmitter(api_key=settings.bing_places_api_key.get_secret_value())
    if settings.foursquare_api_key:
        with contextlib.suppress(ProviderNotConfiguredError):
            out["foursquare_places"] = FoursquareSubmitter(
                api_key=settings.foursquare_api_key.get_secret_value()
            )
    return out


def _cost_estimate_for(tier: str, settings: Settings) -> float:
    if tier in ("api", "aggregator"):
        return settings.citation_api_cost_estimate
    if tier == "bot_fillable":
        return settings.citation_bot_cost_estimate
    if tier == "captcha_assisted":
        return settings.citation_captcha_cost_estimate
    return settings.citation_apify_cost_estimate


def execute_citation_submit(
    store: ServiceCitationsStore, settings: Settings, citation_id: str
) -> dict[str, Any]:
    """Submit ONE queued citation. Never raises - a redelivered/already-terminal row
    is a clean no-op; any failure marks the row ``failed`` with a capped error,
    never leaves it stuck at ``submitting``."""
    try:
        row = store.load_citation_with_directory(citation_id)
        if row is None:
            logger.warning("citation_submit_missing", citation_id=citation_id)
            return {"state": "error", "reason": "not found"}
        status = str(row.get("submit_status") or "not_started")
        if status in _TERMINAL:
            return {"state": "unchanged", "reason": f"submit_status={status}"}
        if status != "queued":
            return {"state": "skipped", "reason": f"submit_status={status}"}

        tier = str(row.get("directory_tier") or "")
        client_id = row.get("client_id")
        ctx = GateContext(
            feature_key=_FEATURE,
            client_id=str(client_id) if client_id else None,
            provider=f"citations:{tier or 'unknown'}",
            estimated_cost=_cost_estimate_for(tier, settings),
            job_id=citation_id,
            job_type=_JOB_TYPE,
            client_name=str(row.get("client_name") or ""),
        )
        decision = _gate().evaluate(ctx)
        if not decision.allowed:
            store.update_citation(
                citation_id, {"submit_status": "blocked", "error": f"spend_blocked:{decision.outcome}"}
            )
            logger.info("citation_submit_blocked", citation_id=citation_id, outcome=decision.outcome)
            return {"state": "blocked", "reason": decision.outcome}

        store.update_citation(citation_id, {"submit_status": "submitting"})
        job = job_from_row(row)
        submit_method = str(row.get("submit_method") or "")
        bot = citation_bot_from_settings(settings, captcha_solver=captcha_solver_from_settings(settings))
        apify = apify_submitter_from_settings(settings)
        submitter, reason = submitter_for(
            submit_method, api_submitters=_api_submitters(settings), bot=bot, apify=apify,
        )
        if submitter is None:
            store.update_citation(citation_id, {"submit_status": "blocked", "error": reason[:_ERROR_MAX]})
            logger.info("citation_submit_no_engine", citation_id=citation_id, reason=reason)
            return {"state": "blocked", "reason": reason}

        try:
            result = submitter.submit(job)
        except Exception as exc:  # a provider crash still marks failed - never stuck, never re-raised
            _gate().commit(ctx, ctx.estimated_cost)  # the attempt still incurred the metered cost
            logger.exception("citation_submit_provider_error", citation_id=citation_id)
            store.update_citation(citation_id, {"submit_status": "failed", "error": f"{exc!r}"[:_ERROR_MAX]})
            return {"state": "failed", "reason": f"{exc!r}"[:_ERROR_MAX]}

        _gate().commit(ctx, ctx.estimated_cost)
        fields: dict[str, Any] = {
            "submit_status": result.status,
            "proof_url": result.proof_url,
            "error": result.error[:_ERROR_MAX],
        }
        if result.external_ref:
            fields["external_ref"] = result.external_ref
        if result.status in ("submitted", "verified"):
            fields["nap_status"] = "consistent"
            fields["action"] = "Update"
            fields["submitted_at"] = datetime.now(UTC)
        store.update_citation(citation_id, fields)
        logger.info("citation_submit_done", citation_id=citation_id, status=result.status)
        return {"state": result.status, "reason": result.error}
    except Exception as exc:  # never re-raise (acks_late would redeliver = double spend)
        logger.exception("citation_submit_error", citation_id=citation_id)
        try:
            store.update_citation(citation_id, {"submit_status": "failed", "error": f"{exc!r}"[:_ERROR_MAX]})
        except Exception:
            logger.warning("citation_submit_mark_failed_failed", citation_id=citation_id)
        return {"state": "error", "reason": f"{exc!r}"[:_ERROR_MAX]}


# --------------------------------------------------------------------------- #
# Celery entry point (thin; import the app lazily-free at module load, per the
# worker template).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="citation_submit")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def citation_submit_job(citation_id: str) -> dict[str, Any]:
    """Entry point: submit one queued citation row."""
    settings = get_settings()
    return execute_citation_submit(service_citations_store(), settings, citation_id)
