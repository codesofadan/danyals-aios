"""The reusable per-call cost gate.

Every paid provider call (later, from workers) passes through here first:

    spend halted? -> dial allows? -> cached? -> under client cap? -> call + log

``evaluate`` returns a decision without making the call (the caller owns the
provider call, so the gate stays provider-agnostic and fully unit-testable). On
an allowed call the caller invokes ``commit`` with the real cost to log it and
warm the cache. A cached hit costs 0 and is logged as cached.

The FIRST check is the agency-global, MANUAL ``spend halt`` kill-switch: when an
owner/admin engages it, EVERY metered feature is blocked (``blocked_halt``)
regardless of any dial - no provider call, nothing cached, nothing logged - and
the caller surfaces the ``spend_halted`` refusal. Because the halt is evaluated
before anything else, every gate entry honors it with no bypass; toggling it off
restores the normal dial-governed path. (The old per-day dollar spend-stop
THRESHOLD was removed - the halt replaces it.)

The DB/Redis wiring lives behind the ``CostStore`` / ``CostCache`` protocols so
the gate can be tested with in-memory fakes; the concrete store
(``app/services/cost_store.py``) is exercised in the integration suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

DialMode = Literal["api", "byhand", "off"]

# The stable machine-readable code + human message surfaced when the global,
# manual API-spend halt is engaged. A caller/UI may branch on the code; a user
# reads the message. Treat the code as a versioned contract (add, never repurpose).
SPEND_HALTED_CODE = "spend_halted"
SPEND_HALTED_MESSAGE = "API spend is halted"

# call = proceed to the paid provider; cached = served from cache (cost 0);
# skip = dial off (stub); manual = dial by-hand (queue for a human);
# blocked_cap = the per-client budget cap stopped the call;
# blocked_halt = the agency-global manual spend halt stopped the call.
GateOutcome = Literal["call", "cached", "skip", "manual", "blocked_cap", "blocked_halt"]

# Outcomes for which NO paid call happens.
_NO_CALL: frozenset[GateOutcome] = frozenset({"cached", "skip", "manual", "blocked_cap", "blocked_halt"})


class SpendHaltedError(Exception):
    """A typed refusal raised by a synchronous paid endpoint when spend is halted.

    Carries the stable machine code (``reason``) + human message so the global
    error handler can emit a consistent typed 402 refusal
    (``{"type": "spend_halted", "message": "API spend is halted", ...}``) - never
    a silent failure, and never after an actual provider call. Worker/async paths
    do not raise this; they observe ``blocked_halt`` from ``evaluate`` and degrade.
    """

    reason: str = SPEND_HALTED_CODE
    status_code: int = 402

    def __init__(self, message: str = SPEND_HALTED_MESSAGE) -> None:
        super().__init__(message)
        self.message = message


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
        return self.outcome in ("blocked_cap", "blocked_halt")

    @property
    def halted(self) -> bool:
        """Whether the global manual spend halt stopped this call."""
        return self.outcome == "blocked_halt"


class CostStore(Protocol):
    def dial_mode(self, feature_key: str) -> DialMode: ...
    def client_budget(self, client_id: str) -> tuple[float, float] | None: ...
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
        # The agency-global manual HALT overrides everything: no provider call,
        # nothing cached, nothing logged. Checked FIRST so every gate entry honors
        # it - there is no dial, cap, or cache path that can bypass a halt.
        if self._store.is_halted():
            return GateDecision("blocked_halt", reason=SPEND_HALTED_MESSAGE)

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

    def ensure_not_halted(self) -> None:
        """Raise :class:`SpendHaltedError` if the global spend halt is engaged.

        A convenience for synchronous request-path endpoints that want to refuse
        up front with the typed 402 ``spend_halted`` signal before doing any work.
        The same halt is enforced inside ``evaluate`` so worker/async callers block
        identically (they observe ``blocked_halt`` and degrade).
        """
        if self._store.is_halted():
            raise SpendHaltedError()


def outcome_makes_call(outcome: GateOutcome) -> bool:
    """Whether an outcome results in a paid provider call."""
    return outcome not in _NO_CALL
