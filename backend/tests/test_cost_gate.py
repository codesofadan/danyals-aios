"""The reusable per-call cost gate enforces the full chain.

spend halted? -> dial -> cache -> client cap -> call+log; a cached call is $0.

The old per-day dollar spend-stop THRESHOLD was removed; a manual, agency-global
HALT (checked FIRST, before any dial) replaces it: when engaged EVERY metered
feature is blocked with the ``spend_halted`` signal, nothing is logged, and no
provider call happens. Toggling it off restores normal dial-governed behavior.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.cost_gate import (
    SPEND_HALTED_CODE,
    SPEND_HALTED_MESSAGE,
    CostGate,
    DialMode,
    GateContext,
    SpendHaltedError,
)

pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(
        self,
        *,
        mode: DialMode = "api",
        budget: tuple[float, float] | None = None,
        halted: bool = False,
    ) -> None:
        self._mode = mode
        self._budget = budget
        self.halted = halted
        self.recorded: list[tuple[GateContext, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self._budget

    def is_halted(self) -> bool:
        return self.halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx, cost, cached))


class FakeCache:
    def __init__(self, data: dict[str, Any] | None = None) -> None:
        self.data = data or {}
        self.sets: list[tuple[str, Any]] = []

    def get(self, key: str) -> Any | None:
        return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value
        self.sets.append((key, value))


def _ctx(**over: Any) -> GateContext:
    base: dict[str, Any] = {
        "feature_key": "tech_audit", "client_id": "cl-1", "provider": "DataForSEO",
        "estimated_cost": 0.75, "cache_key": None,
    }
    base.update(over)
    return GateContext(**base)


def _gate(store: FakeStore, cache: FakeCache | None = None) -> CostGate:
    return CostGate(store, cache or FakeCache())


def test_dial_off_skips() -> None:
    store = FakeStore(mode="off")
    d = _gate(store).evaluate(_ctx())
    assert d.outcome == "skip"
    assert not store.recorded  # nothing logged, nothing spent


def test_dial_byhand_requires_manual() -> None:
    d = _gate(FakeStore(mode="byhand")).evaluate(_ctx())
    assert d.outcome == "manual"


def test_cache_hit_costs_zero_and_is_logged() -> None:
    store = FakeStore(mode="api")
    cache = FakeCache({"k1": {"cached": "value"}})
    d = _gate(store, cache).evaluate(_ctx(cache_key="k1"))
    assert d.outcome == "cached"
    assert d.cost == 0.0
    assert d.cached_value == {"cached": "value"}
    assert store.recorded[0][1] == 0.0  # logged at $0
    assert store.recorded[0][2] is True  # cached=True


def test_over_client_cap_blocks() -> None:
    store = FakeStore(mode="api", budget=(100.0, 90.0))
    d = _gate(store).evaluate(_ctx(estimated_cost=20.0))
    assert d.outcome == "blocked_cap"
    assert not store.recorded


def test_sub_dollar_spend_accumulates_against_cap() -> None:
    # The C2 scenario the numeric-column migration (0044) enables: $9.90 already
    # spent under a $10 cap, so the next $0.15 charge reaches $10.05 > $10 and is
    # blocked. Before 0044, `spent` was an INTEGER, every sub-dollar charge rounded
    # to 0, `spent` stayed 0, and this cap could NEVER trip.
    blocked = _gate(FakeStore(mode="api", budget=(10.0, 9.90))).evaluate(
        _ctx(estimated_cost=0.15)
    )
    assert blocked.outcome == "blocked_cap"
    # one cent of headroom below the cap still allows the call
    ok = _gate(FakeStore(mode="api", budget=(10.0, 9.80))).evaluate(
        _ctx(estimated_cost=0.15)
    )
    assert ok.outcome == "call"


def test_uncapped_client_passes_cap_check() -> None:
    store = FakeStore(mode="api", budget=(0.0, 5000.0))  # cap 0 = uncapped
    d = _gate(store).evaluate(_ctx())
    assert d.outcome == "call"


# --- the daily-threshold spend-stop is GONE ---------------------------------- #
def test_no_daily_threshold_blocks_a_large_spend() -> None:
    # There is NO per-day dollar ceiling any more: an arbitrarily large estimated
    # cost, with no client cap and no halt, is allowed. (Under the old spend-stop a
    # >$75/day estimate would have tripped ``blocked_daily``; that concept is gone.)
    store = FakeStore(mode="api", budget=None)
    d = _gate(store).evaluate(_ctx(estimated_cost=10_000.0))
    assert d.outcome == "call"
    assert d.allowed
    # The gate no longer consults any daily spend total or daily ceiling.
    assert not hasattr(store, "daily_stop")
    assert not hasattr(store, "daily_spent")


# --- the manual, agency-global spend HALT ------------------------------------ #
@pytest.mark.parametrize("mode", ["api", "byhand", "off"])
@pytest.mark.parametrize("cache_key", [None, "k1"])
@pytest.mark.parametrize("budget", [None, (0.0, 0.0), (100.0, 10.0)])
def test_halt_blocks_every_feature_regardless_of_dial_or_cache_or_cap(
    mode: DialMode, cache_key: str | None, budget: tuple[float, float] | None
) -> None:
    # Halt overrides EVERYTHING: any dial mode, a warm cache, any budget -> blocked,
    # with the spend_halted signal, and NOTHING is logged (no $0 cache row either).
    store = FakeStore(mode=mode, budget=budget, halted=True)
    cache = FakeCache({"k1": {"warm": 1}}) if cache_key else FakeCache()
    d = _gate(store, cache).evaluate(_ctx(cache_key=cache_key, estimated_cost=0.75))
    assert d.outcome == "blocked_halt"
    assert d.halted is True
    assert d.blocked is True
    assert d.allowed is False
    assert d.reason == SPEND_HALTED_MESSAGE
    assert not store.recorded  # commits NO cost / makes NO provider call


def test_halt_signal_constants_are_stable() -> None:
    assert SPEND_HALTED_CODE == "spend_halted"
    assert SPEND_HALTED_MESSAGE == "API spend is halted"


def test_ensure_not_halted_raises_typed_refusal_only_when_halted() -> None:
    # Engaged -> raises the typed 402 refusal carrying the machine code + message.
    with pytest.raises(SpendHaltedError) as exc:
        _gate(FakeStore(halted=True)).ensure_not_halted()
    assert exc.value.reason == "spend_halted"
    assert exc.value.status_code == 402
    assert str(exc.value) == SPEND_HALTED_MESSAGE
    # Not engaged -> no-op.
    _gate(FakeStore(halted=False)).ensure_not_halted()


def test_toggling_halt_off_restores_dial_governed_behavior() -> None:
    # Same store instance: ON -> blocked_halt; flip OFF -> the dial governs (call).
    store = FakeStore(mode="api", budget=(500.0, 100.0), halted=True)
    gate = _gate(store)
    assert gate.evaluate(_ctx()).outcome == "blocked_halt"
    store.halted = False
    restored = gate.evaluate(_ctx())
    assert restored.outcome == "call"
    assert restored.allowed


def test_clear_path_allows_call() -> None:
    store = FakeStore(mode="api", budget=(500.0, 100.0))
    d = _gate(store).evaluate(_ctx(estimated_cost=0.75))
    assert d.outcome == "call"
    assert d.allowed
    assert d.cost == 0.75
    assert not store.recorded  # evaluate does not log; commit/run does


def test_run_logs_allowed_call() -> None:
    store = FakeStore(mode="api")
    d = _gate(store).run(_ctx(estimated_cost=0.75))
    assert d.outcome == "call"
    assert store.recorded[0][1] == 0.75
    assert store.recorded[0][2] is False  # not cached


def test_run_when_halted_logs_nothing() -> None:
    store = FakeStore(mode="api", halted=True)
    d = _gate(store).run(_ctx(estimated_cost=0.75))
    assert d.outcome == "blocked_halt"
    assert not store.recorded


def test_commit_logs_and_warms_cache() -> None:
    store = FakeStore()
    cache = FakeCache()
    gate = CostGate(store, cache)
    ctx = _ctx(cache_key="k9")
    gate.commit(ctx, 1.28, cache_value={"result": 1})
    assert store.recorded[0][1] == 1.28
    assert cache.data["k9"] == {"result": 1}
