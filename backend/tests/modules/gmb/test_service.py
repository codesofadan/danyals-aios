"""The GBP post generator: the gate contract, the degrades, and the dash guarantee.

`service.py` says its design "unit-tests deterministically with a FakeSummarizer +
a fake CostStore - zero network". It had no tests. The properties below are the
ones the module's own docstring promises, and the two that cost real money if
they are wrong:

* a KEYLESS deploy degrades WITHOUT consulting the gate and WITHOUT a provider
  call - so a missing key cannot be charged for;
* a BLOCKED gate (dial off, client cap, global halt) makes NO provider call - so
  a spend decision cannot be bypassed by a code path that asks anyway and
  discards the answer.

The spend committed is the call's REAL token usage times the model's unit price,
never the estimate the gate reserved against. An estimate that becomes the bill is
how a ledger drifts from what was actually spent.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.modules.gmb.policy import GBP_MAX_CHARS
from app.modules.gmb.service import DEGRADE_KEYLESS, run_gmb_generation
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.llm import LLMResult


class SpySummarizer:
    """Records every call and returns a canned body, so a test can assert BOTH
    that a provider call happened and what was done to its output."""

    def __init__(self, text: str = "Book a spring service today and keep the pool ready.") -> None:
        self.calls: list[tuple[str, str, int]] = []
        self.text = text
        self.input_tokens = 1000
        self.output_tokens = 500

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls.append((prompt, model, max_tokens))
        return LLMResult(text=self.text, input_tokens=self.input_tokens,
                         output_tokens=self.output_tokens)


class FakeStore:
    def __init__(self, *, mode: DialMode = "api", halted: bool = False,
                 budget: tuple[float, float] | None = None) -> None:
        self._mode, self._halted, self._budget = mode, halted, budget
        self.recorded: list[tuple[GateContext, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._mode

    def client_budget(self, client_id: str):
        return self._budget

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 75.0

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.recorded.append((ctx, cost, cached))


class FakeCache:
    """The gate takes a cache; nothing here exercises caching, so it never hits."""

    def get(self, key: str):
        return None

    def set(self, key: str, value) -> None:
        return None


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None)


def _run(summarizer, store, settings, **over):
    kw = {
        "topic": "spring pool service", "post_type": "update", "cta_type": "book",
        "cta_url": "https://example.com/book", "title": "", "client_id": "cl-1",
        "client_name": "Alligator Pools", "summarizer": summarizer,
        "gate": CostGate(store, FakeCache()), "settings": settings,
    }
    kw.update(over)
    return run_gmb_generation(**kw)


# ------------------------------------------------------------------ the degrades

def test_a_keyless_deploy_degrades_without_touching_the_gate(settings):
    store = FakeStore()
    r = _run(None, store, settings)
    assert r.status == "degraded"
    assert r.reason == DEGRADE_KEYLESS
    assert r.body == ""
    # The gate is never consulted, so a missing key cannot be charged for.
    assert store.recorded == []


def test_a_blocked_dial_makes_no_provider_call(settings):
    spy, store = SpySummarizer(), FakeStore(mode="off")
    r = _run(spy, store, settings)
    assert r.status == "degraded"
    assert r.reason.startswith("cost_gate:")
    # The property that matters: asking the provider anyway and discarding the
    # answer would spend the money the dial exists to refuse.
    assert spy.calls == []
    assert store.recorded == []


def test_a_global_spend_halt_makes_no_provider_call(settings):
    spy, store = SpySummarizer(), FakeStore(halted=True)
    r = _run(spy, store, settings)
    assert r.status == "degraded"
    assert spy.calls == []


def test_a_degraded_result_still_carries_a_policy_report(settings):
    # The UI renders `policy` unconditionally; a None here would crash the screen
    # on exactly the deploys least able to debug it.
    r = _run(None, FakeStore(), settings)
    assert r.policy is not None
    assert not r.policy.ok  # an empty body is a violation
    assert "empty" in {i.code for i in r.policy.violations}


# --------------------------------------------------------------------- the happy path

def test_an_allowed_run_calls_the_provider_and_commits_the_real_cost(settings):
    spy, store = SpySummarizer(), FakeStore()
    r = _run(spy, store, settings)
    assert r.status == "ok"
    assert len(spy.calls) == 1
    assert len(store.recorded) == 1
    _, cost, cached = store.recorded[0]
    assert cost > 0 and cached is False
    assert r.cost == pytest.approx(cost, rel=1e-6)


def test_the_committed_cost_follows_the_tokens_actually_used(settings):
    cheap, dear = SpySummarizer(), SpySummarizer()
    dear.input_tokens, dear.output_tokens = 100_000, 50_000
    a = _run(cheap, FakeStore(), settings)
    b = _run(dear, FakeStore(), settings)
    # A flat estimate would price these the same; the ledger would then drift
    # from what was really spent.
    assert b.cost > a.cost * 10


def test_the_topic_reaches_the_prompt(settings):
    spy = SpySummarizer()
    _run(spy, FakeStore(), settings, topic="winter cover fitting")
    prompt = spy.calls[0][0]
    assert "winter cover fitting" in prompt
    assert "Alligator Pools" in prompt


# ------------------------------------------------------- the two hard guarantees

def test_an_em_dash_from_the_model_never_survives(settings):
    em = chr(0x2014)  # a literal here is flagged as ambiguous, and rightly so
    spy = SpySummarizer(text=f"Spring service {em} book today {em} spaces limited.")
    r = _run(spy, FakeStore(), settings)
    assert em not in r.body and chr(0x2013) not in r.body
    # And the policy check therefore sees a clean body.
    assert "forbidden_dash" not in {i.code for i in r.policy.issues}


def test_an_overlong_draft_is_capped_on_a_word_boundary(settings):
    spy = SpySummarizer(text="word " * (GBP_MAX_CHARS // 2))
    r = _run(spy, FakeStore(), settings)
    assert len(r.body) <= GBP_MAX_CHARS
    assert not r.body.endswith(" ")
    # Cut at a space, so the post never ends mid-word.
    assert r.body.endswith("word")
    assert "too_long" not in {i.code for i in r.policy.violations}


def test_the_policy_report_describes_the_body_that_was_actually_kept(settings):
    spy = SpySummarizer(text="Book now!!! " + "detail " * 60)
    r = _run(spy, FakeStore(), settings)
    assert r.policy.char_count == len(r.body)
