"""P2-7 gate: the reusable per-call cost gate enforces the full chain.

dial -> cache -> client cap -> daily spend-stop -> call+log; a cached call is $0.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.cost_gate import CostGate, DialMode, GateContext

pytestmark = pytest.mark.unit


class FakeStore:
    def __init__(
        self,
        *,
        mode: DialMode = "api",
        budget: tuple[float, float] | None = None,
        daily_spent: float = 0.0,
        daily_stop: float = 75.0,
        halted: bool = False,
    ) -> None:
        self._mode = mode
        self._budget = budget
        self._daily_spent = daily_spent
        self._daily_stop = daily_stop
        self._halted = halted
        self.recorded: list[tuple[GateContext, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self._budget

    def daily_spent(self) -> float:
        return self._daily_spent

    def daily_stop(self) -> float:
        return self._daily_stop

    def is_halted(self) -> bool:
        return self._halted

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


def test_manual_halt_blocks() -> None:
    store = FakeStore(mode="api", halted=True)
    d = _gate(store).evaluate(_ctx())
    assert d.outcome == "blocked_daily"
    assert d.reason.startswith("daily spend-stop")


def test_daily_threshold_blocks() -> None:
    store = FakeStore(mode="api", daily_spent=70.0, daily_stop=75.0)
    d = _gate(store).evaluate(_ctx(estimated_cost=10.0))  # 80 > 75
    assert d.outcome == "blocked_daily"


def test_clear_path_allows_call() -> None:
    store = FakeStore(mode="api", budget=(500.0, 100.0), daily_spent=10.0, daily_stop=75.0)
    d = _gate(store).evaluate(_ctx(estimated_cost=0.75))
    assert d.outcome == "call"
    assert d.allowed
    assert d.cost == 0.75
    assert not store.recorded  # evaluate does not log; commit/run does


def test_run_logs_allowed_call() -> None:
    store = FakeStore(mode="api", daily_stop=75.0)
    d = _gate(store).run(_ctx(estimated_cost=0.75))
    assert d.outcome == "call"
    assert store.recorded[0][1] == 0.75
    assert store.recorded[0][2] is False  # not cached


def test_commit_logs_and_warms_cache() -> None:
    store = FakeStore()
    cache = FakeCache()
    gate = CostGate(store, cache)
    ctx = _ctx(cache_key="k9")
    gate.commit(ctx, 1.28, cache_value={"result": 1})
    assert store.recorded[0][1] == 1.28
    assert cache.data["k9"] == {"result": 1}
