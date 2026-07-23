"""Competitor-intel workers: the cost-gated gap analysis + the SERP auto-discovery.

Built on the never-stuck / never-re-raise / idempotent worker template
(``app.modules.keyword_research.tasks`` / ``app.modules.rank_tracker.tasks``): with
``task_acks_late`` a raised exception REDELIVERS the job, and for this module a
redelivery means a second PAID provider pull - i.e. double-billing the client. So every
task ACKs and returns a small result dict.

The flow:

    run_gap_analysis: load the competitor -> R5 cost pre-check (gate.evaluate) ->
      provider.ranked_keywords -> gate.commit -> read the client's OWN positions FREE
      from the Rank Tracker -> service.analyze_gaps -> upsert the gaps + roll the
      competitor's read model -> stamp last_analyzed_at

    discover_competitors: load the client's tracked keywords -> R5 pre-check for the
      WHOLE sweep -> one SERP per keyword -> gate.commit for what actually succeeded ->
      service.discover_competitors -> insert the proposals (serp_auto)

THE COST RULES:

* R5 - the gate is consulted BEFORE the provider, so a blocked run spends nothing.
* A gate block DEGRADES: no call, an honest $0, the stored analysis simply stays as it
  was. It never crashes and never writes a partial, fabricated result - a competitor's
  gaps from last week are old but TRUE, whereas an empty gap set written by a blocked
  run would read as "this rival has no advantage over us", which is a lie.
* ``gate.commit`` sits AFTER a SUCCESSFUL fetch, so a failed pull costs the client $0.
* The analysis bill is the CLIENT's (0037 makes ``competitors.client_id`` NOT NULL), so
  every ``GateContext.client_id`` is the competitor's client - never None, never the
  agency.

IDEMPOTENCY: the gap upsert is keyed by ``(competitor_id, keyword)`` (0037) and the
discovery insert by ``(client_id, domain)``, so a redelivery converges on the same rows
rather than duplicating them.

The Celery app is imported LAST (after the pure core), per the worker template, so
importing this module stays Celery-free at the API edge.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.competitor_intel.provider import (
    analysis_pricing,
    discovery_pricing,
    keyword_source_from_settings,
    serp_source_from_settings,
)
from app.modules.competitor_intel.repo import ServiceCompetitorStore, service_competitor_store
from app.modules.competitor_intel.service import (
    analyze_gaps,
    normalize_domain,
)
from app.modules.competitor_intel.service import (
    discover_competitors as tally_competitors,
)
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore
from app.services.pricing import serper_cost
from integrations.content_research import SerpResearcher
from integrations.keyword_data import KeywordDataProvider

logger = get_logger("workers.competitor_intel")

# The competitor-intel spend rides its OWN money-dial feature so ops can throttle
# competitive research independently of audits, content and rank tracking. job_type is
# the free-text cost-log label.
_FEATURE = "competitor_intel"
_JOB_TYPE_ANALYSIS = "gap_analysis"
_JOB_TYPE_DISCOVERY = "competitor_discovery"


class _NullCostCache:
    """A no-op ``CostCache``: a competitive pull is deliberately NOT cache-keyed - the
    product IS a fresh reading of a rival's ranking set, and a cached gap is a wrong
    gap. The money-dial + budgets still gate it."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


# --------------------------------------------------------------------------- #
# The pure-ish cores (wired from a store + gate + provider; NO Celery import).
# --------------------------------------------------------------------------- #
def execute_gap_analysis(
    store: ServiceCompetitorStore,
    provider: KeywordDataProvider,
    gate: CostGate,
    settings: Settings,
    *,
    competitor_id: str,
    live: bool = True,
) -> dict[str, Any]:
    """Run ONE gap analysis and record it. Never raises for a provider/gate reason.

    Ordering is the whole contract (see the module docstring):
    load -> R5 gate -> fetch -> (error? bail, writing NOTHING) -> commit -> the FREE
    client positions -> classify -> upsert.
    """
    row = store.get_competitor(competitor_id)
    if row is None:
        return {"state": "error", "reason": "unknown competitor", "competitor_id": competitor_id}

    domain = normalize_domain(str(row.get("domain") or ""))
    if not domain:
        # Nothing to analyse: without a domain there is no ranked set to ask for. Do
        # not spend money to learn nothing.
        return {"state": "error", "reason": "no domain to analyze", "competitor_id": competitor_id}

    client_id = str(row.get("client_id") or "")
    pricing = analysis_pricing(settings)
    ctx = GateContext(
        feature_key=_FEATURE,
        # The analysis bill is the CLIENT's - 0037 makes client_id NOT NULL, so this is
        # never None and never the agency.
        client_id=client_id or None,
        provider=pricing.provider,
        estimated_cost=pricing.cost,
        job_id=str(row.get("code") or competitor_id),
        job_type=_JOB_TYPE_ANALYSIS,
        client_name=str(row.get("client_name") or ""),
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        # DEGRADE: no call, an honest $0, the stored analysis untouched. Deliberately
        # NOT an empty write - see the module docstring.
        logger.warning(
            "gap_analysis_blocked",
            competitor_id=competitor_id,
            code=str(row.get("code") or ""),
            outcome=decision.outcome,
            reason=decision.reason,
        )
        return {
            "state": "blocked",
            "reason": decision.outcome,
            "competitor_id": competitor_id,
            "gaps": 0,
        }

    try:
        ranked = provider.ranked_keywords(
            domain, geo=None, limit=int(settings.competitor_intel_ranked_limit)
        )
    except Exception:
        # A failed pull writes NOTHING and costs the client $0 (no commit). The
        # previous analysis stands - old but true.
        logger.exception("gap_analysis_fetch_failed", competitor_id=competitor_id, domain=domain)
        return {
            "state": "error",
            "reason": "provider fetch failed",
            "competitor_id": competitor_id,
            "gaps": 0,
        }
    gate.commit(ctx, ctx.estimated_cost)

    # The CLIENT's own positions - FREE, from the Rank Tracker's read model (0036).
    # This reuse is the point of the phase: the client already pays for these nightly.
    client_positions = store.client_positions(client_id)

    analysis = analyze_gaps(
        ranked,
        client_positions,
        untapped_volume=int(settings.competitor_intel_untapped_volume),
    )

    analyzed_at = datetime.now(UTC)
    written = store.record_analysis(
        competitor_id,
        client_id=client_id,
        gaps=[
            {
                "keyword": g.keyword,
                "volume": g.volume,
                "difficulty": g.difficulty,
                "intent": g.intent,
                "competitor_position": g.competitor_position,
                "client_position": g.client_position,
                "gap_type": g.gap_type,
                "opportunity": g.opportunity,
            }
            for g in analysis.gaps
        ],
        overlap_pct=analysis.overlap_pct,
        keyword_gaps_count=analysis.keyword_gaps_count,
        common_keywords=analysis.common_keywords,
        analyzed_at=analyzed_at,
    )

    logger.info(
        "gap_analysis_done",
        competitor_id=competitor_id,
        code=str(row.get("code") or ""),
        domain=domain,
        gaps=analysis.keyword_gaps_count,
        common=analysis.common_keywords,
        overlap=analysis.overlap_pct,
        live=live,
    )
    return {
        "state": "ok",
        "competitor_id": competitor_id,
        "analyzed": len(analysis.gaps),
        "written": written,
        "gaps": analysis.keyword_gaps_count,
        "common": analysis.common_keywords,
        "overlap": analysis.overlap_pct,
        "cost": ctx.estimated_cost,
    }


def execute_discovery(
    store: ServiceCompetitorStore,
    researcher: SerpResearcher,
    gate: CostGate,
    settings: Settings,
    *,
    client_id: str,
) -> dict[str, Any]:
    """Propose competitors for ONE client from their tracked-keyword SERPs.

    Never raises for a provider/gate reason. The R5 pre-check prices the WHOLE sweep
    in one context (see ``provider.discovery_pricing``), so a client near their cap is
    refused the sweep rather than being walked past it one SERP at a time.
    """
    sample = store.tracked_keywords_sample(
        client_id, limit=int(settings.competitor_intel_discovery_keywords)
    )
    if not sample:
        # Discovery mines the client's tracked SERPs; an empty tracking book is a
        # no-op, not an error - and emphatically not a paid call that finds nothing.
        return {"state": "skipped", "reason": "no tracked keywords", "client_id": client_id, "found": 0}

    client_name = store.get_client_name(client_id) or ""
    pricing = discovery_pricing(settings, keywords=len(sample))
    ctx = GateContext(
        feature_key=_FEATURE,
        client_id=client_id,
        provider=pricing.provider,
        estimated_cost=pricing.cost,
        job_id=client_id,
        job_type=_JOB_TYPE_DISCOVERY,
        client_name=client_name,
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        logger.warning(
            "competitor_discovery_blocked",
            client_id=client_id,
            outcome=decision.outcome,
            reason=decision.reason,
        )
        return {"state": "blocked", "reason": decision.outcome, "client_id": client_id, "found": 0}

    serps: list[tuple[str, int, list[str]]] = []
    failures = 0
    for row in sample:
        keyword = str(row.get("keyword") or "")
        volume = int(row.get("search_volume") or 0)
        try:
            result = researcher.serp(keyword)
        except Exception:
            # One bad SERP does not sink the sweep: tally what DID come back. A
            # discovery built on 9 of 10 SERPs is still useful; crashing would waste
            # the 9 the client already paid for.
            failures += 1
            logger.warning("competitor_discovery_serp_failed", keyword=keyword)
            continue
        serps.append((keyword, volume, [hit.link for hit in result.organic]))

    if not serps:
        # Every SERP failed: nothing was delivered, so nothing is billed.
        logger.warning("competitor_discovery_all_failed", client_id=client_id)
        return {
            "state": "error", "reason": "provider fetch failed", "client_id": client_id, "found": 0
        }

    # Commit only what was actually DELIVERED - a partial sweep bills partially. The
    # ACTUAL cost = the number of SERPs actually read x the per-query unit price
    # (pricing.py); the gate was pre-checked for the full sweep (the conservative
    # direction), so this can only ever charge less than was authorised.
    delivered = serper_cost(settings, queries=len(serps))
    gate.commit(ctx, delivered)

    candidates = tally_competitors(
        serps,
        client_domain=store.client_domain(client_id),
        existing_domains=store.existing_domains(client_id),
        limit=int(settings.competitor_intel_discovery_limit),
        min_appearances=int(settings.competitor_intel_discovery_min_appearances),
    )

    added = 0
    for candidate in candidates:
        if store.add_discovered(
            client_id=client_id,
            client_name=client_name,
            domain=candidate.domain,
            label=f"Appears on {candidate.appearances} tracked keyword(s)",
        ):
            added += 1

    logger.info(
        "competitor_discovery_done",
        client_id=client_id,
        serps=len(serps),
        failures=failures,
        candidates=len(candidates),
        added=added,
    )
    return {
        "state": "ok",
        "client_id": client_id,
        "serps": len(serps),
        "failures": failures,
        "found": len(candidates),
        "added": added,
        "cost": delivered,
    }


# --------------------------------------------------------------------------- #
# Celery entry points (thin; the app is imported after the pure core).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="run_gap_analysis")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def run_gap_analysis(competitor_id: str) -> dict[str, Any]:
    """Entry point: run ONE cost-gated gap analysis and record it.

    Wraps the pure core in a guard so the task NEVER re-raises (a redelivery would
    re-run a PAID pull and double-bill the client); a failure comes back as an
    ``error`` result dict.
    """
    settings = get_settings()
    try:
        provider, live = keyword_source_from_settings(settings)
        return execute_gap_analysis(
            service_competitor_store(),
            provider,
            _gate(),
            settings,
            competitor_id=competitor_id,
            live=live,
        )
    except Exception:
        logger.exception("run_gap_analysis_task_failed", competitor_id=competitor_id)
        return {"state": "error", "reason": "task failed", "competitor_id": competitor_id}


@celery_app.task(name="discover_competitors")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def discover_competitors(client_id: str) -> dict[str, Any]:
    """Entry point: propose competitors for ONE client from their tracked SERPs.

    Never re-raises (a redelivery would re-run a PAID sweep); the insert is idempotent
    on ``(client_id, domain)``, so a redelivery that DOES get through adds nothing.
    """
    settings = get_settings()
    try:
        researcher, _live = serp_source_from_settings(settings)
        return execute_discovery(
            service_competitor_store(), researcher, _gate(), settings, client_id=client_id
        )
    except Exception:
        logger.exception("discover_competitors_task_failed", client_id=client_id)
        return {"state": "error", "reason": "task failed", "client_id": client_id}
