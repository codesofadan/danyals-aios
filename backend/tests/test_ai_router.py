"""The model router - the one door every model call goes through.

Five things have to hold, and each of them is a defect this repo has actually shipped
at least once in the scattered form the router replaces:

* the MODEL comes from the task tier, not from a string a caller typed;
* the cost gate is consulted BEFORE the provider, and a block spends nothing;
* the committed cost is the ACTUAL one, priced with cache reads and writes at their own
  rates (``pricing.anthropic_cost`` alone is wrong in both directions on a cached call);
* a backend that cannot honour a tier's configuration is either BLOCKED (reasoning /
  judge, where the configuration IS the quality contract) or RECORDED (everything else)
  - never silently ignored;
* the pre-call ESTIMATE is sized from the expected answer, not from ``max_tokens``, which
  is a runaway ceiling. Conflating them priced a 900-word article at ~$0.20 instead of
  ~$0.03 and would have had the gate refuse work a client could comfortably afford.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pytest

from app.config import Settings
from app.platform.ai.router import (
    CAP_ADAPTIVE_THINKING,
    CAP_EFFORT,
    CAP_PROMPT_CACHE,
    DEFAULT_EXPECTED_OUTPUT_TOKENS,
    CapabilityMissingError,
    CostBlockedError,
    ModelRequest,
    ModelRouter,
    RouterSummarizer,
    SummarizerBackend,
    build_router,
)
from app.platform.ai.tiers import TaskTier
from app.services.cost_gate import CostGate, GateContext
from integrations.llm import FakeSummarizer, LLMResult

pytestmark = pytest.mark.unit


class _Store:
    """A cost store that records what was committed and can refuse."""

    def __init__(self, mode: str = "on", halted: bool = False) -> None:
        self.mode = mode
        self.halted = halted
        self.committed: list[tuple[str, float]] = []

    def dial_mode(self, feature_key: str) -> Any:
        return self.mode

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return None

    def is_halted(self) -> bool:
        return self.halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.committed.append((ctx.feature_key, cost))


class _Cache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class _SpyingSummarizer:
    """Records the arguments it was called with, and reports fixed usage."""

    def __init__(self, *, usage: LLMResult | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._usage = usage

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | Sequence[str] | None = None,
        cache: Sequence[bool] | None = None,
    ) -> LLMResult:
        self.calls.append(
            {"prompt": prompt, "model": model, "max_tokens": max_tokens,
             "system": system, "cache": cache}
        )
        return self._usage or LLMResult(text="drafted", input_tokens=100, output_tokens=50)


def _settings(**overrides: Any) -> Settings:
    return Settings(app_env="dev", **overrides)


def _router(
    summarizer: Any = None, *, store: _Store | None = None, settings: Settings | None = None,
    supports_cache: bool = True, name: str = "test",
) -> tuple[ModelRouter, _Store]:
    used_store = store or _Store()
    used_settings = settings or _settings()
    backend = SummarizerBackend(
        summarizer or FakeSummarizer(), name=name, supports_cache=supports_cache
    )
    return ModelRouter(backend, CostGate(used_store, _Cache()), used_settings), used_store


# --------------------------------------------------------------------------- #
# The tier decides the model
# --------------------------------------------------------------------------- #
def test_the_tier_picks_the_model_and_the_callers_model_string_is_ignored() -> None:
    """A caller states what KIND of work it is; the table answers with a model.

    This is the whole reason the router exists. Before it, ~15 call sites passed a model
    name (``"content-writer"``, a literal that is not even a real model id), so changing
    a model meant grepping for strings across two repos.
    """
    spy = _SpyingSummarizer()
    router, _ = _router(spy)

    router.complete(ModelRequest(task=TaskTier.BULK, prompt="alt text please"))
    assert spy.calls[0]["model"] == "claude-haiku-4-5"

    router.complete(ModelRequest(task=TaskTier.DRAFTING, prompt="write the section"))
    assert spy.calls[1]["model"] == "claude-opus-5"

    router.complete(ModelRequest(task=TaskTier.STRUCTURED, prompt="classify this"))
    assert spy.calls[2]["model"] == "claude-sonnet-5"


def test_a_summarizer_backend_forwards_the_system_prompt() -> None:
    """The ``system`` argument is load-bearing and has been dropped before.

    ``integrations/llm.py`` records the incident: every article ever drafted was written
    under the context-COMPACTION system prompt because a gated wrapper did not accept a
    ``system`` parameter, so the generator had no way to pass one. Claude was told it was
    a summarisation service and then asked for marketing copy.
    """
    spy = _SpyingSummarizer()
    router, _ = _router(spy)

    router.complete(
        ModelRequest(task=TaskTier.DRAFTING, prompt="p", system=["stable", "volatile"])
    )
    assert spy.calls[0]["system"] == ["stable", "volatile"]


# --------------------------------------------------------------------------- #
# The gate runs first, and a block spends nothing
# --------------------------------------------------------------------------- #
def test_a_gate_block_raises_before_the_provider_is_contacted() -> None:
    spy = _SpyingSummarizer()
    router, store = _router(spy, store=_Store(halted=True))

    with pytest.raises(CostBlockedError) as caught:
        router.complete(ModelRequest(task=TaskTier.DRAFTING, prompt="expensive"))

    assert caught.value.outcome == "blocked_halt"
    assert spy.calls == [], "the provider must not be called when the gate refuses"
    assert store.committed == [], "a refused call must not appear in the cost ledger"


def test_the_committed_cost_is_the_actual_usage_not_the_estimate() -> None:
    """What lands in the ledger is derived from the call's REAL token counts."""
    usage = LLMResult(text="out", input_tokens=1_000_000, output_tokens=0)
    router, store = _router(_SpyingSummarizer(usage=usage))

    result = router.complete(ModelRequest(task=TaskTier.BULK, prompt="x", feature_key="content"))

    # Haiku input is $1.00/MTok, so 1M input tokens and no output is exactly $1.00.
    assert result.cost_usd == pytest.approx(1.0)
    assert store.committed == [("content", pytest.approx(1.0))]


def test_cache_reads_and_writes_are_priced_at_their_own_rates() -> None:
    """A cached call is not an ordinary call, and ``input_tokens`` alone cannot say so.

    The API reports the cached prefix SEPARATELY from ``input_tokens``. Pricing from
    ``input_tokens`` alone misses both the 1.25x write surcharge and the 0.1x read
    discount - the error that made the doctrine cost model 30% low once already.
    """
    usage = LLMResult(
        text="out", input_tokens=0, output_tokens=0,
        cache_write_tokens=1_000_000, cache_read_tokens=1_000_000,
    )
    router, _ = _router(_SpyingSummarizer(usage=usage))

    result = router.complete(ModelRequest(task=TaskTier.BULK, prompt="x"))

    # Haiku input $1.00/MTok: 1M written at 1.25x + 1M read at 0.10x = $1.35.
    assert result.cost_usd == pytest.approx(1.35)
    assert result.cache_hit is True


# --------------------------------------------------------------------------- #
# The estimate
# --------------------------------------------------------------------------- #
def test_the_estimate_is_sized_from_the_expected_answer_not_the_token_ceiling() -> None:
    """``max_tokens`` is a runaway guard, not a purchase - and the gate decides on the
    estimate, so treating the ceiling as the expectation refuses affordable work.

    A drafting call with the tier's 16000 ceiling must not be priced as 16000 (or 8000)
    output tokens when the caller expects 1200.
    """
    router, _ = _router()

    expected = router.complete(
        ModelRequest(task=TaskTier.DRAFTING, prompt="short", expected_output_tokens=1200)
    ).estimated_usd
    ceiling_priced = 16_000 * 25.0 / 1_000_000  # opus output at the full ceiling

    assert expected < ceiling_priced / 10
    assert expected == pytest.approx(1200 * 25.0 / 1_000_000, rel=0.05)


def test_an_undeclared_output_size_falls_back_to_the_documented_default() -> None:
    router, _ = _router()
    result = router.complete(ModelRequest(task=TaskTier.DRAFTING, prompt="p"))
    assert result.estimated_usd == pytest.approx(
        DEFAULT_EXPECTED_OUTPUT_TOKENS * 25.0 / 1_000_000, rel=0.05
    )


def test_the_estimate_never_exceeds_the_hard_token_ceiling() -> None:
    """A caller that over-declares is clamped: the ceiling really is a ceiling."""
    router, _ = _router()
    result = router.complete(
        ModelRequest(
            task=TaskTier.BULK, prompt="p", max_tokens=500, expected_output_tokens=999_999
        )
    )
    assert result.estimated_usd == pytest.approx(500 * 5.0 / 1_000_000, rel=0.05)


# --------------------------------------------------------------------------- #
# Capabilities: block where the configuration IS the contract, record elsewhere
# --------------------------------------------------------------------------- #
def test_a_judge_call_blocks_on_a_backend_that_cannot_think() -> None:
    """A judge that does not think is a different grader, not a cheaper one.

    §8 requires the grader never share the generator's configuration; an eval calibrated
    against a thinking judge says nothing about a non-thinking one. So the router refuses
    rather than quietly producing a grade nobody can interpret.
    """
    router, _ = _router()
    with pytest.raises(CapabilityMissingError) as caught:
        router.complete(ModelRequest(task=TaskTier.JUDGE, prompt="grade this"))
    assert CAP_ADAPTIVE_THINKING in str(caught.value)


def test_reasoning_blocks_too_and_the_posture_is_configurable() -> None:
    router, _ = _router()
    with pytest.raises(CapabilityMissingError):
        router.complete(ModelRequest(task=TaskTier.REASONING, prompt="reconcile"))

    relaxed, _ = _router(settings=_settings(ai_router_strict_tiers=False))
    result = relaxed.complete(ModelRequest(task=TaskTier.REASONING, prompt="reconcile"))
    assert CAP_ADAPTIVE_THINKING in result.degraded


def test_drafting_proceeds_but_records_what_the_backend_could_not_honour() -> None:
    """Silence is what the capability rule forbids, not degradation itself.

    This deployment's live backend is an OpenAI-compatible proxy, so blocking every
    drafting call over a missing ``effort`` parameter would stop all work to enforce a
    preference. Proceeding is correct; proceeding WITHOUT SAYING SO is not.
    """
    router, _ = _router()
    result = router.complete(ModelRequest(task=TaskTier.DRAFTING, prompt="write"))
    assert result.text
    assert result.degraded == (CAP_EFFORT,)


def test_a_backend_without_prompt_cache_is_not_asked_to_cache() -> None:
    """A proxy cannot guarantee caching, so the router stops passing breakpoints.

    Claiming a cache hit we cannot substantiate would corrupt the one number §4 says to
    verify rather than assume (``cache_read_input_tokens`` charted per module).
    """
    spy = _SpyingSummarizer()
    router, _ = _router(spy, supports_cache=False)

    router.complete(
        ModelRequest(task=TaskTier.DRAFTING, prompt="p", system=["a", "b"], cache=[True, True])
    )
    assert spy.calls[0]["cache"] is None

    cached_spy = _SpyingSummarizer()
    cached_router, _ = _router(cached_spy, supports_cache=True)
    cached_router.complete(
        ModelRequest(task=TaskTier.DRAFTING, prompt="p", system=["a", "b"], cache=[True, False])
    )
    assert cached_spy.calls[0]["cache"] == [True, False]
    assert CAP_PROMPT_CACHE in cached_router._backend.capabilities  # type: ignore[union-attr]


# --------------------------------------------------------------------------- #
# The reverse adapter: existing callers routed without a rewrite
# --------------------------------------------------------------------------- #
def test_router_summarizer_routes_an_existing_caller_through_the_gate() -> None:
    """``RouterSummarizer`` is what lets ``content_generator`` - 1,000 lines, unchanged -
    have every one of its dozen internal calls tier-routed, gated, priced and traced."""
    spy = _SpyingSummarizer()
    router, store = _router(spy)
    writer = RouterSummarizer(router, task=TaskTier.DRAFTING, feature_key="content")

    result = writer.summarize("section one", model="content-writer", max_tokens=600)

    assert result.text == "drafted"
    assert spy.calls[0]["model"] == "claude-opus-5", "the tier overrides the caller's string"
    assert writer.requested_models == {"content-writer"}, "and the override is visible"
    assert writer.calls == 1
    assert store.committed and store.committed[0][0] == "content"


def test_a_gate_block_reaches_existing_callers_as_the_exception_they_handle() -> None:
    """The content pipeline already handles ``ContentSpendBlocked`` by HOLDING the draft.

    Translating here means a gate block stays the same well-handled outcome it is today,
    rather than becoming a brand-new unhandled failure at every existing call site.
    """
    from app.services.content_research import ContentSpendBlocked

    router, _ = _router(store=_Store(halted=True))
    writer = RouterSummarizer(router)

    with pytest.raises(ContentSpendBlocked):
        writer.summarize("section", model="anything", max_tokens=100)


# --------------------------------------------------------------------------- #
# Construction
# --------------------------------------------------------------------------- #
def test_a_keyless_build_yields_an_unconfigured_router_rather_than_raising() -> None:
    """Every provider seam in this repo degrades rather than crashes; so does this one."""
    router = build_router(_settings(anthropic_api_key=None), CostGate(_Store(), _Cache()))
    assert router.configured is False
    with pytest.raises(CapabilityMissingError):
        router.complete(ModelRequest(task=TaskTier.BULK, prompt="p"))


def test_an_injected_summarizer_builds_a_working_router_with_no_key() -> None:
    router = build_router(
        _settings(), CostGate(_Store(), _Cache()), summarizer=FakeSummarizer()
    )
    assert router.configured is True
    assert router.complete(ModelRequest(task=TaskTier.BULK, prompt="hello")).text


def test_a_proxy_base_url_names_the_backend_and_drops_the_cache_claim() -> None:
    router = build_router(
        _settings(anthropic_base_url="https://agentrouter.org"),
        CostGate(_Store(), _Cache()),
        summarizer=FakeSummarizer(),
    )
    assert router.backend_name == "agentrouter"
    assert CAP_PROMPT_CACHE not in router._backend.capabilities  # type: ignore[union-attr]
