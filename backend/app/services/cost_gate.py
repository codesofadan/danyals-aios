"""The reusable per-call cost gate.

Every paid provider call (later, from workers) passes through here first:

    dial allows? -> cached? -> under client cap? -> under daily stop? -> call + log

``evaluate`` returns a decision without making the call (the caller owns the
provider call, so the gate stays provider-agnostic and fully unit-testable). On
an allowed call the caller invokes ``commit`` with the real cost to log it and
warm the cache. A cached hit costs 0 and is logged as cached.

The DB/Redis wiring lives behind the ``CostStore`` / ``CostCache`` protocols so
the gate can be tested with in-memory fakes; the concrete store
(``app/services/cost_store.py``) is exercised in the integration suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

DialMode = Literal["api", "byhand", "off"]

# call = proceed to the paid provider; cached = served from cache (cost 0);
# skip = dial off (stub); manual = dial by-hand (queue for a human);
# blocked_cap / blocked_daily = a limit stopped the call.
GateOutcome = Literal["call", "cached", "skip", "manual", "blocked_cap", "blocked_daily"]

# Outcomes for which NO paid call happens.
_NO_CALL: frozenset[GateOutcome] = frozenset({"cached", "skip", "manual", "blocked_cap", "blocked_daily"})


@dataclass(frozen=True)
class GateContext:
    """Everything the gate needs to decide about one prospective paid call."""

    feature_key: str
    client_id: str | None
    provider: str
    estimated_cost: float
    job_id: str = ""
    job_type: str = ""
    client_name: str = ""
    cache_key: str | None = None


@dataclass(frozen=True)
class GateDecision:
    outcome: GateOutcome
    cost: float = 0.0
    cached_value: Any | None = None
    reason: str = ""

    @property
    def allowed(self) -> bool:
        """Whether the caller should make the paid provider call."""
        return self.outcome == "call"

    @property
    def blocked(self) -> bool:
        return self.outcome in ("blocked_cap", "blocked_daily")


class CostStore(Protocol):
    def dial_mode(self, feature_key: str) -> DialMode: ...
    def client_budget(self, client_id: str) -> tuple[float, float] | None: ...
    def daily_spent(self) -> float: ...
    def daily_stop(self) -> float: ...
    def is_halted(self) -> bool: ...
    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None: ...


class CostCache(Protocol):
    def get(self, key: str) -> Any | None: ...
    def set(self, key: str, value: Any) -> None: ...


class CostGate:
    """Stateless orchestrator over a ``CostStore`` + ``CostCache``."""

    def __init__(self, store: CostStore, cache: CostCache) -> None:
        self._store = store
        self._cache = cache

    def evaluate(self, ctx: GateContext) -> GateDecision:
        """Decide the fate of a prospective paid call (makes no call itself)."""
        mode = self._store.dial_mode(ctx.feature_key)
        if mode == "off":
            return GateDecision("skip", reason="feature dial is off")
        if mode == "byhand":
            return GateDecision("manual", reason="feature requires manual review")

        # dial == "api": try cache first (a hit costs nothing).
        if ctx.cache_key is not None:
            hit = self._cache.get(ctx.cache_key)
            if hit is not None:
                self._store.record_cost(ctx, 0.0, cached=True)
                return GateDecision("cached", cost=0.0, cached_value=hit)

        # under the client's monthly cap?
        budget = self._store.client_budget(ctx.client_id) if ctx.client_id else None
        if budget is not None:
            cap, spent = budget
            if cap > 0 and spent + ctx.estimated_cost > cap:
                return GateDecision("blocked_cap", reason="client budget cap reached")

        # under the org daily spend-stop (and not manually halted)?
        if self._store.is_halted():
            return GateDecision("blocked_daily", reason="daily spend-stop is engaged")
        if self._store.daily_spent() + ctx.estimated_cost > self._store.daily_stop():
            return GateDecision("blocked_daily", reason="daily spend-stop threshold reached")

        return GateDecision("call", cost=ctx.estimated_cost)

    def commit(self, ctx: GateContext, cost: float, *, cache_value: Any | None = None) -> None:
        """Record a completed paid call's cost and warm the cache."""
        self._store.record_cost(ctx, cost, cached=False)
        if ctx.cache_key is not None and cache_value is not None:
            self._cache.set(ctx.cache_key, cache_value)

    def run(self, ctx: GateContext) -> GateDecision:
        """Convenience for callers with no real provider call yet (Part 2).

        Evaluates and, for an allowed call, immediately logs the estimated cost so
        the log + budget reflect it. Real workers will instead ``evaluate`` ->
        call the provider -> ``commit`` with the actual cost.
        """
        decision = self.evaluate(ctx)
        if decision.outcome == "call":
            self.commit(ctx, ctx.estimated_cost)
        return decision


def outcome_makes_call(outcome: GateOutcome) -> bool:
    """Whether an outcome results in a paid provider call."""
    return outcome not in _NO_CALL
