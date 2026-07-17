"""Rank-tracker workers: the nightly dispatcher, the cost-gated check, and the
history retention sweep.

Built on the never-stuck / never-re-raise / idempotent worker template
(``workers.tasks.context`` / ``app.modules.keyword_research.tasks``): with
``task_acks_late`` a raised exception REDELIVERS the job, and for this module a
redelivery means a second PAID rank check - i.e. double-billing the client. So every
task ACKs and returns a small result dict.

The flow:

    beat -> dispatch_rank_checks: take the R6 beat-overlap lock -> CLAIM due active
    rows (FOR UPDATE SKIP LOCKED, advancing next_check_on in the same statement) ->
    fan out one check_keyword_rank per claim
      -> check_keyword_rank: today-dedupe pre-check -> R5 cost pre-check
         (gate.evaluate) -> provider fetch -> gate.commit -> append the snapshot
         (on conflict do nothing) -> roll previous <- latest, update best, re-stamp
         next_check_on

THE CRITICAL CORRECTNESS RULE, and the reason this module exists in this shape:

    A provider ERROR (``snap.error`` set) writes NO history row and does NOT set
    position = NULL.

``position = NULL`` means "successfully checked, not in the top-N" (unranked). A
provider outage is NOT that. Writing a failed fetch as unranked would fabricate a
phantom LOST RANKING - the client's board would show a keyword falling off the map, the
change column would read "lost", and the alerting would fire - all because a vendor
returned a 503. The error path therefore leaves every position column untouched.

THE COST RULES:

* R5 - the gate is consulted BEFORE the provider, so a blocked check spends nothing.
* A gate block DEGRADES (no call, an honest $0, positions simply stay put) AND emits
  the STALENESS SIGNAL, so the stall is visible rather than silent: ``record_stall``
  re-arms the schedule while HOLDING ``latest_checked_at``, which is what the read side
  computes ``stale`` from.
* ``gate.commit`` sits AFTER a SUCCESSFUL fetch, so a failed pull costs the client $0.
* The rank-check bill is the CLIENT's, so every ``GateContext.client_id`` is the
  KEYWORD's client - never None, never the agency.

The Celery app is imported LAST (after the pure core), per the worker template, so
importing this module stays Celery-free at the API edge.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from app.config import Settings, get_settings
from app.logging_setup import get_logger
from app.modules.rank_tracker.provider import (
    RankProvider,
    find_all_positions,
    rank_provider_from_settings,
)
from app.modules.rank_tracker.repo import ServiceRankStore, service_rank_store
from app.modules.rank_tracker.service import CADENCE_INTERVAL_DAYS
from app.services.cost_gate import CostGate, GateContext
from app.services.cost_store import PostgresCostStore

logger = get_logger("workers.rank_tracker")

# The rank-check spend rides its OWN money-dial feature so ops can throttle standing
# rank tracking off/byhand/api INDEPENDENTLY of audits and content - which matters
# precisely because this is the one cost that recurs without anyone asking for it.
# job_type is the free-text cost-log label.
_FEATURE = "rank_tracker"
_JOB_TYPE = "rank_check"

_DEFAULT_CADENCE = "weekly"


class _NullCostCache:
    """A no-op ``CostCache``: a rank check is deliberately NOT cache-keyed - the whole
    product is a fresh daily reading, and a cached position is a wrong position. The
    money-dial + budgets still gate it, and the today-dedupe pre-check is what stops a
    same-day repeat from re-billing."""

    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _gate() -> CostGate:
    return CostGate(PostgresCostStore(), _NullCostCache())


def _next_check_date(cadence: str, *, after: date) -> date:
    """The next scheduled check date - the SAME interval table the N-A projection
    prices by, so the schedule and the bill can never drift apart."""
    interval = CADENCE_INTERVAL_DAYS.get(cadence, CADENCE_INTERVAL_DAYS[_DEFAULT_CADENCE])
    return after + timedelta(days=interval)


def _own_urls_json(hits: list[Any]) -> str:
    """EVERY same-domain hit, as the jsonb payload for ``keyword_rankings.own_urls``.

    More than one entry IS the cannibalization signal - two of the client's own pages
    competing for one term. Keeping only the winner would erase the evidence.
    """
    return json.dumps([{"position": h.position, "url": h.url, "title": h.title} for h in hits])


def execute_rank_check(
    store: ServiceRankStore,
    provider: RankProvider,
    gate: CostGate,
    settings: Settings,
    *,
    keyword_id: str,
    force: bool = False,
    today: date | None = None,
) -> dict[str, Any]:
    """Run ONE rank check and record it. Never raises for a PROVIDER/gate reason.

    Ordering is the whole contract (see the module docstring):
    today-dedupe -> R5 gate -> fetch -> (error? bail, writing NOTHING) -> commit ->
    append + roll forward.
    """
    checked_on = today or datetime.now(UTC).date()

    row = store.get_keyword(keyword_id)
    if row is None:
        return {"state": "error", "reason": "unknown keyword", "keyword_id": keyword_id}

    cadence = str(row.get("cadence") or _DEFAULT_CADENCE)
    client_id = str(row.get("client_id") or "")
    domain = str(row.get("site_domain") or "") or _domain_of(str(row.get("target_url") or ""))
    if not domain:
        # Nothing to look FOR: without a site domain or a target URL a "position" is
        # undefined. Do not spend money to learn nothing.
        return {"state": "error", "reason": "no domain to match", "keyword_id": keyword_id}

    # The double-spend guard, BEFORE the gate: the unique(keyword_id, checked_on) index
    # makes the write idempotent, but a redelivery would already have paid the vendor.
    # ``force`` (an operator who knows the SERP moved) deliberately bypasses it and
    # CORRECTS today's row instead - see ``replace_check``.
    already_today = store.has_ranking_on(keyword_id, checked_on)
    if already_today and not force:
        return {"state": "skipped", "reason": "already checked today", "keyword_id": keyword_id}

    depth = int(settings.rank_tracker_depth)
    ctx = GateContext(
        feature_key=_FEATURE,
        # The rank-check API cost is the CLIENT's - a tracked keyword always has one
        # (0036 makes client_id NOT NULL), so this is never None and never the agency.
        client_id=client_id or None,
        provider=provider.provider,
        estimated_cost=provider.estimated_cost(depth),
        job_id=str(row.get("code") or keyword_id),
        job_type=_JOB_TYPE,
        client_name=str(row.get("client_name") or ""),
    )
    decision = gate.evaluate(ctx)
    if not decision.allowed:
        # DEGRADE: no call, an honest $0, positions untouched - AND emit the staleness
        # signal so a stalled tracker is visible instead of showing a stale position as
        # if it were fresh. record_stall HOLDS latest_checked_at on purpose.
        store.record_stall(keyword_id, next_check_on=_next_check_date(cadence, after=checked_on))
        logger.warning(
            "rank_check_stalled",
            keyword_id=keyword_id,
            code=str(row.get("code") or ""),
            outcome=decision.outcome,
            reason=decision.reason,
        )
        return {
            "state": "blocked",
            "reason": decision.outcome,
            "keyword_id": keyword_id,
            "stale": True,
        }

    snap = provider.fetch_serp(
        str(row.get("keyword") or ""),
        location=str(row.get("location") or ""),
        device=str(row.get("device") or "desktop"),
        language=str(row.get("language") or "en"),
        country=str(row.get("country") or "us"),
        engine=str(row.get("engine") or "google"),
        depth=depth,
    )
    if not snap.ok:
        # THE CRITICAL RULE. A provider error writes NOTHING: no history row, no
        # position, no NULL. "Unranked" and "the vendor failed" are different facts,
        # and conflating them fabricates a lost ranking out of an outage. No commit
        # either - a failed pull costs the client $0. Re-arm the schedule and hold the
        # freshness stamp, exactly like the gate-block degrade.
        store.record_stall(keyword_id, next_check_on=_next_check_date(cadence, after=checked_on))
        logger.warning(
            "rank_check_provider_error",
            keyword_id=keyword_id,
            code=str(row.get("code") or ""),
            provider=snap.provider,
            error=snap.error,
        )
        return {
            "state": "error",
            "reason": "provider fetch failed",
            "keyword_id": keyword_id,
            "stale": True,
        }

    gate.commit(ctx, ctx.estimated_cost)

    hits = find_all_positions(snap, domain)
    best = hits[0] if hits else None
    # None here is the HONEST unranked reading: the fetch succeeded, the domain simply
    # is not in the fetched window.
    position = best.position if best else None
    # On a FORCED re-check today's row already rolled the read model once, so
    # ``latest_position`` holds this morning's reading, not yesterday's. The movement
    # to report is still against yesterday - i.e. the row's existing previous.
    previous = _opt_int(row.get("previous_position" if already_today else "latest_position"))
    delta = (previous - position) if (previous is not None and position is not None) else None
    next_check_on = _next_check_date(cadence, after=checked_on)
    checked_at = snap.fetched_at or datetime.now(UTC)

    if already_today:
        # Forced re-read: CORRECT today's snapshot rather than discard what was just
        # paid for. previous_position is deliberately left alone (see replace_check).
        store.replace_check(
            keyword_id,
            checked_on=checked_on,
            position=position,
            ranking_url=best.url if best else "",
            serp_features=list(snap.features),
            own_urls=_own_urls_json(hits),
            delta=delta,
            provider=snap.provider,
            cost=ctx.estimated_cost,
            next_check_on=next_check_on,
            checked_at=checked_at,
            features=list(snap.features),
        )
    else:
        inserted = store.record_check(
            keyword_id,
            client_id=client_id,
            checked_on=checked_on,
            position=position,
            ranking_url=best.url if best else "",
            serp_features=list(snap.features),
            own_urls=_own_urls_json(hits),
            delta=delta,
            provider=snap.provider,
            cost=ctx.estimated_cost,
            previous_position=previous,
            next_check_on=next_check_on,
            checked_at=checked_at,
            features=list(snap.features),
        )
        if not inserted:
            # A concurrent/redelivered run won the day's slot between our pre-check and
            # the insert. The snapshot stands; ours simply does not double-apply (which
            # would corrupt previous_position).
            logger.info("rank_check_already_recorded", keyword_id=keyword_id)
            return {
                "state": "skipped", "reason": "already checked today", "keyword_id": keyword_id
            }

    logger.info(
        "rank_check_done",
        keyword_id=keyword_id,
        code=str(row.get("code") or ""),
        position=position,
        own_hits=len(hits),
        provider=snap.provider,
    )
    return {
        "state": "ok",
        "keyword_id": keyword_id,
        "position": position,
        "previous": previous,
        "own_hits": len(hits),
        "cannibalized": len(hits) > 1,
        "cost": ctx.estimated_cost,
        "rechecked": already_today,
    }


def _opt_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _domain_of(url: str) -> str:
    """Fall back to the target URL's host when a keyword has no linked site."""
    from app.modules.rank_tracker.provider import _host

    return _host(url)


# --------------------------------------------------------------------------- #
# The pure dispatch core (claim + fan-out; NO Celery import).
# --------------------------------------------------------------------------- #
def dispatch_due(
    store: ServiceRankStore, *, batch: int, enqueue: Callable[[str], Any]
) -> list[str]:
    """Claim up to ``batch`` due subscriptions and ``enqueue`` one check per claim.

    The R6 beat-overlap lock + the SKIP LOCKED claim both live in
    ``store.claim_due_keywords`` (they must share one transaction to be meaningful), so
    this stays a pure fan-out: the store does the atomic claim, ``enqueue`` is injected
    (the task passes ``check_keyword_rank.delay``), and both are unit-testable with fakes.
    """
    dispatched: list[str] = []
    for row in store.claim_due_keywords(batch):
        keyword_id = str(row["id"])
        enqueue(keyword_id)
        dispatched.append(keyword_id)
    return dispatched


def execute_rollup(store: ServiceRankStore, settings: Settings, *, today: date | None = None) -> dict[str, Any]:
    """Thin out + purge old ranking history. Never raises for a store reason.

    The deliberate alternative to partitioning the table (0036's header explains why):
    observable, gradual, and with no month-rollover cliff.
    """
    reference = today or datetime.now(UTC).date()
    rollup_before = reference - timedelta(days=int(settings.rank_tracker_rollup_after_days))
    purge_before = reference - timedelta(days=int(settings.rank_tracker_history_retention_days))
    result = store.rollup_history(rollup_before=rollup_before, purge_before=purge_before)
    logger.info("rank_history_rollup_done", **result)
    return {"state": "ok", **result}


# --------------------------------------------------------------------------- #
# Celery entry points (thin; the app is imported after the pure core).
# --------------------------------------------------------------------------- #
from workers.celery_app import celery_app  # noqa: E402 - after the pure core, per the worker template


@celery_app.task(name="check_keyword_rank")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def check_keyword_rank(keyword_id: str, force: bool = False) -> dict[str, Any]:
    """Entry point: run ONE cost-gated rank check and record it.

    Wraps the pure core in a guard so the task NEVER re-raises (a redelivery would
    re-run a PAID check and double-bill the client); a failure comes back as an
    ``error`` result dict.
    """
    settings = get_settings()
    try:
        return execute_rank_check(
            service_rank_store(),
            rank_provider_from_settings(settings),
            _gate(),
            settings,
            keyword_id=keyword_id,
            force=force,
        )
    except Exception:
        logger.exception("check_keyword_rank_task_failed", keyword_id=keyword_id)
        return {"state": "error", "reason": "task failed", "keyword_id": keyword_id}


@celery_app.task(name="dispatch_rank_checks")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def dispatch_rank_checks() -> dict[str, Any]:
    """BEAT task (nightly): claim every due subscription and fan out one check each.

    Takes the R6 beat-overlap lock inside the claim, so a tick that lands while the
    previous night is still draining is a clean no-op rather than a second fan-out (=
    a second bill). Never re-raises.
    """
    settings = get_settings()
    try:
        dispatched = dispatch_due(
            service_rank_store(),
            batch=int(settings.rank_tracker_dispatch_batch),
            enqueue=lambda kid: check_keyword_rank.delay(kid),
        )
    except Exception:
        logger.exception("dispatch_rank_checks_task_failed")
        return {"state": "error", "claimed": 0}
    return {"state": "ok", "claimed": len(dispatched)}


@celery_app.task(name="rollup_rank_history")  # type: ignore[untyped-decorator]  # celery's decorator is untyped
def rollup_rank_history() -> dict[str, Any]:
    """BEAT task: roll up + purge old ranking history per the retention settings.

    Never re-raises; a redelivery is harmless (both passes are idempotent deletes -
    re-running them simply matches nothing the second time).
    """
    settings = get_settings()
    try:
        return execute_rollup(service_rank_store(), settings)
    except Exception:
        logger.exception("rollup_rank_history_task_failed")
        return {"state": "error", "rolled_up": 0, "purged": 0}
