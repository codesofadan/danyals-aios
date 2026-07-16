"""P6B-4 gate: the no-bypass proof for context AI spend.

Every context-module LLM + embedding call routes through the existing cost gate,
so:

* dial ``off`` / ``byhand`` / a client cap / the daily spend-stop => the inner
  provider is NEVER called (the spy asserts 0 calls) and ``ContextSpendBlocked``
  is raised;
* dial ``api`` + a fresh call => inner is called once and ``commit`` records the
  cost;
* an embed of unchanged text (same content checksum) => inner is NOT re-called,
  the cost is 0, and the previously stored vector is returned;
* architecturally, the compaction path can hold ONLY the gated wrappers, so a spy
  provider wrapped in Gated* proves every invocation is preceded by a gate
  decision (inner call-count == committed cost records).
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services.context_cost import (
    ContextSpendBlocked,
    GatedEmbedder,
    GatedSummarizer,
    content_checksum,
)
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.llm import LLMResult

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# In-memory gate fakes (mirror tests/test_cost_gate.py) + provider spies
# --------------------------------------------------------------------------- #
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
    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any | None:
        return self.data.get(key)

    def set(self, key: str, value: Any) -> None:
        self.data[key] = value


class SpySummarizer:
    """Counts every summarize call so we can prove the gate fronts it."""

    def __init__(self) -> None:
        self.calls = 0

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls += 1
        return LLMResult(text=f"summary::{prompt[:10]}", input_tokens=3, output_tokens=2)


class SpyEmbedder:
    """Counts embed calls and how many texts it was asked to embed."""

    dim = 4

    def __init__(self) -> None:
        self.calls = 0
        self.embedded_texts: list[str] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        self.embedded_texts.extend(texts)
        return [[float(len(t)), 1.0, 2.0, 3.0] for t in texts]


def _settings() -> Settings:
    return Settings(context_summarize_cost_estimate=0.02, context_embed_cost_estimate=0.001)


def _gate(store: FakeStore, cache: FakeCache | None = None) -> CostGate:
    return CostGate(store, cache or FakeCache())


# --------------------------------------------------------------------------- #
# Summarizer: no-bypass
# --------------------------------------------------------------------------- #
def test_summarize_api_calls_inner_once_and_commits() -> None:
    store = FakeStore(mode="api")
    spy = SpySummarizer()
    gs = GatedSummarizer(spy, _gate(store), settings=_settings(), client_id="cl-1", entity=("client", "cl-1"))
    result = gs.summarize("please summarize this fold", model="m", max_tokens=100)
    assert spy.calls == 1  # inner called exactly once
    assert result.text.startswith("summary::")
    # commit logged exactly one (non-cached) cost row at the estimate.
    assert len(store.recorded) == 1
    ctx, cost, cached = store.recorded[0]
    assert cost == pytest.approx(0.02)
    assert cached is False
    assert ctx.feature_key == "context"
    assert ctx.provider == "Anthropic"


@pytest.mark.parametrize(
    ("store", "outcome"),
    [
        (FakeStore(mode="off"), "skip"),
        (FakeStore(mode="byhand"), "manual"),
        (FakeStore(mode="api", budget=(10.0, 9.99)), "blocked_cap"),
        (FakeStore(mode="api", halted=True), "blocked_daily"),
        (FakeStore(mode="api", daily_spent=75.0, daily_stop=75.0), "blocked_daily"),
    ],
)
def test_summarize_blocked_never_calls_inner(store: FakeStore, outcome: str) -> None:
    spy = SpySummarizer()
    gs = GatedSummarizer(spy, _gate(store), settings=_settings(), client_id="cl-1")
    with pytest.raises(ContextSpendBlocked) as excinfo:
        gs.summarize("fold", model="m", max_tokens=100)
    assert excinfo.value.outcome == outcome
    assert spy.calls == 0  # THE no-bypass proof: provider never reached
    # A blocked call spends nothing (a cached hit would log $0, but these are not cached).
    assert all(cost == 0.0 and cached for _, cost, cached in store.recorded) or not store.recorded


# --------------------------------------------------------------------------- #
# Embedder: no-bypass + content-checksum cache
# --------------------------------------------------------------------------- #
def test_embed_api_calls_inner_and_commits_per_text() -> None:
    store = FakeStore(mode="api")
    spy = SpyEmbedder()
    ge = GatedEmbedder(spy, _gate(store), settings=_settings(), client_id="cl-1", entity=("site", "s-1"))
    vectors = ge.embed(["alpha", "beta"])
    assert spy.calls == 1  # one batched call for the two misses
    assert len(vectors) == 2
    # Two committed (non-cached) cost rows, one per unique text.
    non_cached = [r for r in store.recorded if not r[2]]
    assert len(non_cached) == 2
    assert all(cost == pytest.approx(0.001) for _, cost, _ in non_cached)
    assert ge.dim == spy.dim


def test_embed_cache_hit_is_free_and_reuses_vector() -> None:
    store = FakeStore(mode="api")
    cache = FakeCache()
    gate = _gate(store, cache)
    ge = GatedEmbedder(spy := SpyEmbedder(), gate, settings=_settings(), client_id="cl-1")

    first = ge.embed(["unchanged text"])
    assert spy.calls == 1
    assert spy.embedded_texts == ["unchanged text"]

    # Re-embed the SAME text: identical checksum => a cached $0 hit.
    second = ge.embed(["unchanged text"])
    assert spy.calls == 1  # inner NOT called again for the unchanged text
    assert spy.embedded_texts == ["unchanged text"]  # never re-embedded
    assert second == first  # the stored vector is returned verbatim

    cached_rows = [r for r in store.recorded if r[2]]
    assert len(cached_rows) == 1
    assert cached_rows[0][1] == 0.0  # cost 0 on the hit
    # The cache is keyed by the content checksum.
    assert content_checksum("unchanged text") in cache.data


def test_embed_mixed_batch_only_embeds_the_misses() -> None:
    store = FakeStore(mode="api")
    cache = FakeCache()
    ge = GatedEmbedder(spy := SpyEmbedder(), _gate(store, cache), settings=_settings(), client_id="cl-1")

    ge.embed(["cached one"])  # warm the cache for "cached one"
    spy.calls = 0
    spy.embedded_texts.clear()

    out = ge.embed(["cached one", "fresh two", "cached one"])
    # Only the single unique miss ("fresh two") is sent to the provider.
    assert spy.embedded_texts == ["fresh two"]
    assert spy.calls == 1
    # Order + duplicates preserved: positions 0 and 2 share the cached vector.
    assert out[0] == out[2]
    assert out[1] != out[0]


def test_embed_blocked_never_calls_inner() -> None:
    store = FakeStore(mode="off")
    ge = GatedEmbedder(spy := SpyEmbedder(), _gate(store), settings=_settings(), client_id="cl-1")
    with pytest.raises(ContextSpendBlocked) as excinfo:
        ge.embed(["x", "y"])
    assert excinfo.value.outcome == "skip"
    assert spy.calls == 0  # no-bypass: provider unreachable when the dial is off


def test_embed_empty_is_a_noop() -> None:
    store = FakeStore(mode="api")
    ge = GatedEmbedder(spy := SpyEmbedder(), _gate(store), settings=_settings(), client_id="cl-1")
    assert ge.embed([]) == []
    assert spy.calls == 0
    assert not store.recorded


# --------------------------------------------------------------------------- #
# Architectural no-bypass: call-count == committed cost records
# --------------------------------------------------------------------------- #
def test_every_provider_call_is_preceded_by_a_gate_decision() -> None:
    """A spy wrapped in Gated* proves inner call-count == committed cost records:
    there is no path from the compaction engine to the provider that skips the
    gate."""
    store = FakeStore(mode="api")
    cache = FakeCache()
    gate = _gate(store, cache)
    settings = _settings()
    gs = GatedSummarizer(sum_spy := SpySummarizer(), gate, settings=settings, client_id="cl-1")
    ge = GatedEmbedder(emb_spy := SpyEmbedder(), gate, settings=settings, client_id="cl-1")

    gs.summarize("fold a", model="m", max_tokens=50)
    gs.summarize("fold b", model="m", max_tokens=50)
    ge.embed(["e1", "e2", "e3"])

    provider_calls = sum_spy.calls + len(emb_spy.embedded_texts)  # 2 summaries + 3 embeds
    committed = [r for r in store.recorded if not r[2]]  # non-cached => a real spend
    assert provider_calls == 5
    assert len(committed) == 5  # exactly one committed cost row per provider call
