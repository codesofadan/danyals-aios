"""Site-analytics workers: the read-only GSC + GA4 sync, APPROVAL-FREE but
CREDENTIAL-GATED.

Both tasks ride the never-stuck / never-re-raise / idempotent worker template
(``app.modules.local_seo.tasks`` / ``workers.tasks.context``): with
``task_acks_late`` a raised exception would redeliver the job and re-run a paid-
adjacent provider pull, so a task ACKs and returns a small result dict.

Unlike ``sync_gbp_profile``, these are NOT approval-gated by Google - Search Console
(``webmasters.readonly``) and GA4 (``analytics.readonly``) are standard OAuth scopes.
So the HOLD ladder here has one fewer rung than GBP's:

  * no ``google_oauth_client_id``/``secret`` configured -> HELD (``no_oauth_client``)
  * the property has no sealed refresh token yet (never connected) -> HELD
    (``no_oauth_token``)
  * the reader reports no token (a dangling vault ref) -> HELD (``no_oauth_token``,
    the reader returns ``None`` for this - mirrors ``sync_gbp_profile``'s reader)
  * a provider call fails (the reader raises) -> ERROR (never held - a configured,
    connected property that fails is a real problem worth surfacing, not a
    permanent steady state)

``gate``/``reader`` are INJECTED (mirrors ``local_seo.tasks.check_one_ranking`` /
``execute_gbp_sync``'s ``reader``), so the whole hold ladder + the successful-sync
path are unit-testable with no DB, no network, no broker; the Celery entry points
supply the real ``CostGate``/vault-backed reader.

A gate block DEGRADES (no provider call, honest $0, nothing written) exactly like
every other off-page/local seam; reads are free-tier, so the cost estimate is $0 but
still flows through the gate for spend-visibility parity with every other module.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.site_analytics.repo import ServiceSiteAnalyticsStore, service_site_analytics_store
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore

if TYPE_CHECKING:
    from integrations.ga4 import GA4Summary
    from integrations.gsc import SearchConsoleSummary

logger = get_logger("workers.site_analytics")

# NOTE: this is the REGISTERED dial key "site_analytics" (app/schemas/cost.py) - an
# unregistered key would make dial_mode() fall back to "off" AND make
# PATCH /cost/dials reject it, leaving this module unswitchable-on (the documented
# e8964de lesson).
_FEATURE = "site_analytics"
_JOB_TYPE_GSC = "gsc_sync"
_JOB_TYPE_GA4 = "ga4_sync"

GscReader = Callable[[dict[str, Any], Settings], "SearchConsoleSummary | None"]
Ga4Reader = Callable[[dict[str, Any], Settings], "GA4Summary | None"]


class _NullCostCache:
    """A no-op ``CostCache``: a GSC/GA4 read is a trailing-window SNAPSHOT, not a
    cache-keyed lookup (mirrors ``local_seo``'s own null cache) - the dial + budgets
    still gate every call, they simply never short-circuit it."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def real_cost_gate() -> CostGate:
    """The real ``CostGate`` a Celery entry point uses (service_role Postgres cost
    store); tests inject their own fake ``CostGate`` instead of calling this."""
    return CostGate(PostgresCostStore(), _NullCostCache())


def _default_gsc_reader(row: dict[str, Any], settings: Settings) -> SearchConsoleSummary | None:
    """reveal the sealed refresh token -> exchange for an access token -> build the
    real client -> fetch. Returns ``None`` (a HOLD, not an error) when the vault ref
    is dangling (``reveal_secret`` finds nothing) - the same distinction
    ``sync_gbp_profile``'s reader draws."""
    from app.services.vault import reveal_secret
    from integrations.google_oauth import refresh_access_token
    from integrations.gsc import search_console_client_from_token

    refresh_token = reveal_secret(str(row["oauth_vault_ref"]))
    if not refresh_token:
        return None
    access_token = refresh_access_token(settings, refresh_token=refresh_token)
    client = search_console_client_from_token(access_token)
    return client.fetch_summary(str(row["site_url"]))


def _default_ga4_reader(row: dict[str, Any], settings: Settings) -> GA4Summary | None:
    """Mirrors :func:`_default_gsc_reader` exactly, for GA4."""
    from app.services.vault import reveal_secret
    from integrations.ga4 import ga4_client_from_token
    from integrations.google_oauth import refresh_access_token

    refresh_token = reveal_secret(str(row["oauth_vault_ref"]))
    if not refresh_token:
        return None
    access_token = refresh_access_token(settings, refresh_token=refresh_token)
    client = ga4_client_from_token(access_token)
    return client.fetch_summary(str(row["property_id"]))


def execute_gsc_sync(
    store: ServiceSiteAnalyticsStore,
    settings: Settings,
    gate: CostGate,
    *,
    property_id: str,
    reader: GscReader | None = None,
) -> dict[str, Any]:
    """READ-ONLY GSC sync for ONE property. Never raises. See the module docstring
    for the hold ladder. ``reader`` defaults to the real vault-backed pull; tests
    inject a fake to exercise every branch with no DB/network."""
    row = store.gsc_for_sync(property_id)
    if row is None:
        return {"state": "error", "reason": "unknown property", "held": False}

    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        logger.info("gsc_sync_held", property_id=property_id, reason="no_oauth_client")
        return {"state": "held", "reason": "no_oauth_client", "held": True}
    if not row.get("oauth_connected") or not row.get("oauth_vault_ref"):
        logger.info("gsc_sync_held", property_id=property_id, reason="no_oauth_token")
        return {"state": "held", "reason": "no_oauth_token", "held": True}

    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=str(row["client_id"]),
        provider="google_search_console",
        estimated_cost=settings.site_analytics_cost_estimate,
        job_id=property_id,
        job_type=_JOB_TYPE_GSC,
        client_name="",
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        return {"state": "blocked", "reason": decision.outcome, "held": False}

    try:
        summary = (reader or _default_gsc_reader)(row, settings)
    except Exception:
        logger.exception("gsc_sync_failed", property_id=property_id)
        return {"state": "error", "reason": "gsc read failed", "held": False}
    if summary is None:
        logger.info("gsc_sync_held", property_id=property_id, reason="vault_ref_dangling")
        return {"state": "held", "reason": "no_oauth_token", "held": True}

    gate.commit(ctx, ctx.estimated_cost)
    store.update_gsc_sync(
        property_id,
        clicks=summary.clicks,
        impressions=summary.impressions,
        ctr=summary.ctr,
        avg_position=summary.avg_position,
        top_queries=[
            {"query": q.query, "clicks": q.clicks, "impressions": q.impressions}
            for q in summary.top_queries
        ],
    )
    logger.info("gsc_sync_done", property_id=property_id, clicks=summary.clicks)
    return {"state": "ok", "reason": "", "held": False, "clicks": summary.clicks}


def execute_ga4_sync(
    store: ServiceSiteAnalyticsStore,
    settings: Settings,
    gate: CostGate,
    *,
    property_id: str,
    reader: Ga4Reader | None = None,
) -> dict[str, Any]:
    """READ-ONLY GA4 sync for ONE property. Never raises. Mirrors
    :func:`execute_gsc_sync` exactly."""
    row = store.ga4_for_sync(property_id)
    if row is None:
        return {"state": "error", "reason": "unknown property", "held": False}

    if not (settings.google_oauth_client_id and settings.google_oauth_client_secret):
        logger.info("ga4_sync_held", property_id=property_id, reason="no_oauth_client")
        return {"state": "held", "reason": "no_oauth_client", "held": True}
    if not row.get("oauth_connected") or not row.get("oauth_vault_ref"):
        logger.info("ga4_sync_held", property_id=property_id, reason="no_oauth_token")
        return {"state": "held", "reason": "no_oauth_token", "held": True}

    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=str(row["client_id"]),
        provider="google_analytics",
        estimated_cost=settings.site_analytics_cost_estimate,
        job_id=property_id,
        job_type=_JOB_TYPE_GA4,
        client_name="",
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        return {"state": "blocked", "reason": decision.outcome, "held": False}

    try:
        summary = (reader or _default_ga4_reader)(row, settings)
    except Exception:
        logger.exception("ga4_sync_failed", property_id=property_id)
        return {"state": "error", "reason": "ga4 read failed", "held": False}
    if summary is None:
        logger.info("ga4_sync_held", property_id=property_id, reason="vault_ref_dangling")
        return {"state": "held", "reason": "no_oauth_token", "held": True}

    gate.commit(ctx, ctx.estimated_cost)
    store.update_ga4_sync(
        property_id,
        sessions=summary.sessions,
        users=summary.users,
        conversions=summary.conversions,
    )
    logger.info("ga4_sync_done", property_id=property_id, sessions=summary.sessions)
    return {"state": "ok", "reason": "", "held": False, "sessions": summary.sessions}


# --------------------------------------------------------------------------- #
# Celery entry points (thin; import the app lazily-free at module load).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="sync_gsc_property")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def sync_gsc_property(property_id: str) -> dict[str, Any]:
    """Event-driven task: sync one GSC property (enqueued by the router). The whole
    body is guarded (mirrors ``sync_gbp_profile``) - even a store/settings/gate
    CONSTRUCTION failure must not escape, or ``task_acks_late`` redelivers it."""
    try:
        return execute_gsc_sync(
            service_site_analytics_store(), get_settings(), real_cost_gate(), property_id=property_id
        )
    except Exception:
        logger.exception("sync_gsc_property_task_failed", property_id=property_id)
        return {"state": "error", "reason": "task failed", "held": False}


@celery_app.task(name="sync_ga4_property")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def sync_ga4_property(property_id: str) -> dict[str, Any]:
    """Event-driven task: sync one GA4 property (enqueued by the router). Mirrors
    :func:`sync_gsc_property`'s outer guard exactly."""
    try:
        return execute_ga4_sync(
            service_site_analytics_store(), get_settings(), real_cost_gate(), property_id=property_id
        )
    except Exception:
        logger.exception("sync_ga4_property_task_failed", property_id=property_id)
        return {"state": "error", "reason": "task failed", "held": False}
