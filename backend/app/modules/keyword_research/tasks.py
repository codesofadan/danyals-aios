"""Keyword-research worker: the cost-gated research run + its Celery entry point.

One task, ``research_keywords``, built on the never-stuck / never-re-raise / idempotent
worker template (``workers.tasks.audit`` / ``workers.tasks.offpage``): with
``task_acks_late`` a raised exception would redeliver the job and re-run a PAID
provider pull (double spend), so the task ACKs and returns a small result dict.

The flow (all in the pure ``execute_research`` core, wired here from a privileged
store + the cost gate + the key-gated provider):

  R5 cost pre-check -> (blocked? DEGRADE, no spend) -> provider fetch -> commit cost ->
  ``service.plan_research`` (intent cascade + opportunity + winnability + clustering)
  -> idempotent upsert of the cluster + each keyword into the bank.

A gate block DEGRADES (returns ``state='blocked'`` with zero spend); a provider
failure returns ``state='error'``; the keyless path degrades to the deterministic
fake provider (never a crash). The Celery app is imported LAST (after the pure core),
per the worker template, so importing this module stays Celery-free at the API edge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.keyword_research.repo import ServiceKeywordStore, service_keyword_store
from app.modules.keyword_research.service import plan_research
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from integrations.keyword_data import (
    KeywordDataProvider,
    keyword_data_provider_from_settings,
)

logger = get_logger("workers.keyword_research")

# The keyword-research spend rides its OWN money-dial feature (a dedicated DataForSEO
# metrics dial), so ops can throttle it off/byhand/api independently. job_type is the
# free-text cost-log label.
# NOTE: this is the REGISTERED dial key "keywords" (app/schemas/cost.py), whose meta
# is literally label="Keyword Research". We reuse it rather than minting a twin dial:
# an unregistered key would make dial_mode() fall back to "off" AND make PATCH
# /cost/dials reject it, leaving this module permanently unswitchable-on.
_FEATURE = "keywords"
_JOB_TYPE = "keywords"


class _NullCostCache:
    """A no-op ``CostCache``: a live research pull is not cache-keyed here (it must hit
    the provider); the dial + budgets still gate it."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


def execute_research(
    store: ServiceKeywordStore,
    provider: KeywordDataProvider,
    gate: CostGate,
    settings: Settings,
    *,
    seed: str,
    geo: str | None,
    client_id: str | None,
) -> dict[str, Any]:
    """Run one research pull for ``seed`` and upsert the bank. Never raises.

    R5: a cost pre-check on the ``keyword_research`` dial BEFORE the paid provider
    pull - a block skips the pull (no spend) and DEGRADES. A provider failure returns
    an ``error`` result; the upsert is idempotent (keyed by client/keyword/geo), so a
    redelivery is a safe no-op."""
    seed = seed.strip()
    if not seed:
        return {"state": "error", "reason": "empty seed", "saved": 0}

    client_name = ""
    if client_id:
        client_name = store.get_client_name(client_id) or ""

    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=client_id,
        provider="DataForSEO",
        estimated_cost=float(settings.keyword_research_cost_estimate),
        job_id=seed,
        job_type=_JOB_TYPE,
        client_name=client_name,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.info("keyword_research_blocked", seed=seed, outcome=decision.outcome)
        return {"state": "blocked", "reason": decision.outcome, "saved": 0}

    try:
        ideas = provider.keyword_ideas(seed, geo=geo)
        related = provider.related_keywords(seed, geo=geo)
        provider_intent = provider.search_intent(seed)
    except Exception:
        logger.exception("keyword_research_fetch_failed", seed=seed)
        return {"state": "error", "reason": "provider fetch failed", "saved": 0}
    gate.commit(ctx, ctx.estimated_cost)

    plan = plan_research(
        seed,
        ideas,
        related,
        provider_intents={seed: provider_intent} if provider_intent else {},
        client_da=None,
        neutral_da=float(settings.content_research_neutral_da),
        winnable_stretch=float(settings.content_research_winnable_stretch),
    )

    provider_label = getattr(provider, "provider", "fake")
    fetched_at = datetime.now(UTC)
    cluster_id = store.upsert_cluster(
        client_id=client_id,
        client_name=client_name,
        name=plan.cluster.name,
        pillar_keyword=plan.cluster.pillar_keyword,
        dominant_intent=plan.cluster.dominant_intent,
        size=plan.cluster.size,
        total_volume=plan.cluster.total_volume,
        avg_difficulty=plan.cluster.avg_difficulty,
    )

    saved = 0
    for kw in plan.keywords:
        inserted = store.upsert_keyword(
            client_id=client_id,
            client_name=client_name,
            keyword=kw.keyword,
            geo=geo,
            volume=kw.volume,
            difficulty=kw.difficulty,
            cpc=kw.cpc,
            competition=kw.competition,
            intent=kw.intent,
            intent_source=kw.intent_source,
            intent_confidence=kw.intent_confidence,
            cluster_id=cluster_id or None,
            opportunity=kw.opportunity,
            winnable=kw.winnable,
            source="research",
            metrics_confidence=kw.metrics_confidence,
            provider=provider_label,
            fetched_at=fetched_at,
        )
        if inserted:
            saved += 1

    logger.info(
        "keyword_research_done", seed=seed, cluster=plan.cluster.name,
        keywords=len(plan.keywords), saved=saved,
    )
    return {
        "state": "ok",
        "seed": seed,
        "cluster": plan.cluster.name,
        "keywords": len(plan.keywords),
        "saved": saved,
    }


# --------------------------------------------------------------------------- #
# Celery entry point (thin; import the app lazily-free at module load).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="research_keywords")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def research_keywords(seed: str, geo: str | None = None, client_id: str | None = None) -> dict[str, Any]:
    """Entry point: run one cost-gated keyword research pull + upsert the bank.

    Wraps the pure core in a guard so the task NEVER re-raises (a redelivery would
    re-run a paid pull); a failure is returned as an ``error`` result dict."""
    settings = get_settings()
    try:
        return execute_research(
            service_keyword_store(),
            keyword_data_provider_from_settings(settings),
            _gate(),
            settings,
            seed=seed,
            geo=geo,
            client_id=client_id,
        )
    except Exception:
        logger.exception("research_keywords_task_failed", seed=seed)
        return {"state": "error", "reason": "task failed", "saved": 0}
