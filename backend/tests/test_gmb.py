"""Wave 5: unit tests for the GMB (Google Business Profile) post module.

Covers the PURE policy checker EXHAUSTIVELY (every hard block + advisory) and the
cost-gated, writer-injected generation core (keyless / gate-blocked degrade, the happy
path, the em/en-dash hard guarantee, and the GBP character cap). No network, no DB.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.modules.gmb.policy import (
    GBP_MAX_CHARS,
    GBP_RECOMMENDED_MAX,
    check_gbp_policy,
)
from app.modules.gmb.schemas import compute_gmb_stats
from app.modules.gmb.service import GMB_COST_ESTIMATE, run_gmb_generation
from app.services.cost_gate import CostGate, DialMode, GateContext
from integrations.llm import LLMResult

pytestmark = pytest.mark.unit

EM = chr(0x2014)
EN = chr(0x2013)


# --------------------------------------------------------------------------- #
# Policy checker - hard blocks (violations)
# --------------------------------------------------------------------------- #
def _codes(report: Any) -> set[str]:
    return {i.code for i in report.issues}


def test_policy_clean_post_is_ok() -> None:
    report = check_gbp_policy(
        "Fresh weekend brunch is back at our Portland cafe. Reserve your table now.",
        cta_type="book",
        cta_url="https://verde.example/book",
        post_type="update",
    )
    assert report.ok is True
    assert report.violations == []


def test_policy_empty_body_blocks() -> None:
    report = check_gbp_policy("", cta_type="none")
    assert report.ok is False
    assert "empty" in _codes(report)


def test_policy_over_hard_limit_blocks() -> None:
    report = check_gbp_policy("a " * (GBP_MAX_CHARS), cta_type="none")
    assert report.ok is False
    assert "too_long" in _codes(report)


def test_policy_em_or_en_dash_blocks() -> None:
    report = check_gbp_policy(f"Open early{EM}very early for brunch.", cta_type="call")
    assert report.ok is False
    assert "forbidden_dash" in _codes(report)
    assert "forbidden_dash" in _codes(check_gbp_policy(f"Open 9{EN}5 daily today.", cta_type="call"))


def test_policy_prohibited_content_blocks() -> None:
    report = check_gbp_policy("We sell cheap cigarettes and online casino access today.", cta_type="call")
    assert report.ok is False
    assert "prohibited_content" in _codes(report)


def test_policy_invalid_cta_blocks() -> None:
    report = check_gbp_policy("A perfectly fine post body here for the check.", cta_type="teleport")
    assert report.ok is False
    assert "invalid_cta" in _codes(report)


def test_policy_cta_url_required_when_button_needs_it() -> None:
    missing = check_gbp_policy("A perfectly fine post body here for the check.", cta_type="shop", cta_url="")
    assert "cta_url_missing" in _codes(missing)
    bad = check_gbp_policy("A perfectly fine post body here.", cta_type="shop", cta_url="verde.example")
    assert "cta_url_invalid" in _codes(bad)


def test_policy_call_cta_needs_no_url() -> None:
    report = check_gbp_policy("Call us to book your weekend brunch table today.", cta_type="call")
    assert report.ok is True


# --------------------------------------------------------------------------- #
# Policy checker - advisories (warnings) do NOT block
# --------------------------------------------------------------------------- #
def test_policy_no_cta_warns_but_ok() -> None:
    report = check_gbp_policy("Fresh weekend brunch is back at our Portland cafe today.", cta_type="none")
    assert report.ok is True
    assert "no_cta" in _codes(report)


def test_policy_long_for_gbp_warns() -> None:
    body = "word " * (GBP_RECOMMENDED_MAX // 2)  # over 300 chars but under 1500
    report = check_gbp_policy(body, cta_type="call")
    assert report.ok is True
    assert "long_for_gbp" in _codes(report)


def test_policy_excessive_caps_and_punctuation_warn() -> None:
    report = check_gbp_policy("HUGE SALE TODAY ONLY!!! Come visit our cafe.", cta_type="call")
    assert report.ok is True
    assert "excessive_caps" in _codes(report)
    assert "excessive_punctuation" in _codes(report)


def test_policy_phone_and_url_in_body_warn() -> None:
    phone = check_gbp_policy("Call us at +1 503 555 0199 to book a table.", cta_type="call")
    assert "phone_in_body" in _codes(phone)
    url = check_gbp_policy("Visit https://verde.example for the brunch menu.", cta_type="call")
    assert "url_in_body" in _codes(url)


def test_policy_missing_title_on_offer_warns() -> None:
    report = check_gbp_policy("Twenty percent off brunch this weekend at our cafe.", cta_type="call", post_type="offer")
    assert "missing_title" in _codes(report)


def test_policy_report_as_dict_shape() -> None:
    d = check_gbp_policy(f"Bad{EM}post", cta_type="teleport").as_dict()
    assert set(d) == {"ok", "charCount", "violations", "warnings"}
    assert d["ok"] is False
    assert all(set(v) == {"code", "message", "severity"} for v in d["violations"])


# --------------------------------------------------------------------------- #
# Generation core - degrade, gate, and the dash guarantee
# --------------------------------------------------------------------------- #
class _RecordingCostStore:
    def __init__(self, *, dial: DialMode = "api", budget: tuple[float, float] | None = None) -> None:
        self._dial = dial
        self._budget = budget
        self.records: list[tuple[str, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._dial

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self._budget

    def daily_spent(self) -> float:
        return 0.0

    def daily_stop(self) -> float:
        return 1000.0

    def is_halted(self) -> bool:
        return False

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.records.append((ctx.feature_key, cost, cached))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


class _FakeWriter:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.calls = 0

    def summarize(self, prompt: str, *, model: str, max_tokens: int) -> LLMResult:
        self.calls += 1
        return LLMResult(text=self.reply, input_tokens=40, output_tokens=30)


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="dev")


def _gate(store: _RecordingCostStore) -> CostGate:
    return CostGate(store, _NullCache())


def test_generation_keyless_degrades_without_touching_gate() -> None:
    store = _RecordingCostStore()
    result = run_gmb_generation(
        "weekend brunch launch",
        post_type="update", cta_type="call", cta_url="", title="",
        client_id="c1", client_name="Verde Cafe",
        summarizer=None, gate=_gate(store), settings=_settings(),
    )
    assert result.status == "degraded"
    assert result.reason == "anthropic_unconfigured"
    assert store.records == []  # the gate was never consulted


def test_generation_gate_block_degrades_without_provider_call() -> None:
    store = _RecordingCostStore(dial="off")  # the gmb dial is off -> skip
    writer = _FakeWriter("should never be called")
    result = run_gmb_generation(
        "weekend brunch launch",
        post_type="update", cta_type="call", cta_url="", title="",
        client_id="c1", client_name="Verde Cafe",
        summarizer=writer, gate=_gate(store), settings=_settings(),
    )
    assert result.status == "degraded"
    assert result.reason.startswith("cost_gate:")
    assert writer.calls == 0  # NO provider call happened
    assert store.records == []  # a skip is not billed


def test_generation_happy_path_is_scored_and_billed() -> None:
    store = _RecordingCostStore()
    writer = _FakeWriter("Fresh weekend brunch returns to our Portland cafe. Book your table today.")
    result = run_gmb_generation(
        "weekend brunch launch",
        post_type="update", cta_type="book", cta_url="https://verde.example/book", title="",
        client_id="c1", client_name="Verde Cafe",
        summarizer=writer, gate=_gate(store), settings=_settings(),
    )
    assert result.status == "ok"
    assert result.body
    assert result.policy.ok is True
    assert result.cost > 0
    # the gmb dial was billed the actual token cost.
    assert any(feature == "gmb" and cost > 0 for feature, cost, _c in store.records)


def test_generation_body_is_em_dash_free_even_when_writer_emits_dashes() -> None:
    store = _RecordingCostStore()
    writer = _FakeWriter(f"Brunch is back{EM}every weekend{EN}book 9{EN}11 now.")
    result = run_gmb_generation(
        "weekend brunch launch",
        post_type="update", cta_type="call", cta_url="", title="",
        client_id="c1", client_name="Verde Cafe",
        summarizer=writer, gate=_gate(store), settings=_settings(),
    )
    assert result.status == "ok"
    assert EM not in result.body and EN not in result.body  # THE guarantee
    assert result.policy.ok is True


def test_generation_caps_body_to_gbp_limit() -> None:
    store = _RecordingCostStore()
    writer = _FakeWriter("brunch " * 400)  # ~2800 chars, over the 1500 GBP limit
    result = run_gmb_generation(
        "weekend brunch launch",
        post_type="update", cta_type="call", cta_url="", title="",
        client_id="c1", client_name="Verde Cafe",
        summarizer=writer, gate=_gate(store), settings=_settings(),
    )
    assert len(result.body) <= GBP_MAX_CHARS
    assert result.policy.char_count <= GBP_MAX_CHARS


def test_gmb_cost_estimate_is_positive() -> None:
    assert GMB_COST_ESTIMATE > 0


# --------------------------------------------------------------------------- #
# Stats
# --------------------------------------------------------------------------- #
def test_compute_gmb_stats() -> None:
    rows = [
        {"status": "needs_review", "policy": {"ok": True}},
        {"status": "needs_review", "policy": {"ok": False}},
        {"status": "approved", "policy": {"ok": True}},
        {"status": "posted", "policy": {"ok": True}},
        {"status": "rejected", "policy": {"ok": True}},
    ]
    stats = compute_gmb_stats(rows)
    assert stats.total == 5
    assert stats.awaiting_review == 2
    assert stats.approved == 2  # approved + posted
    assert stats.needs_fix == 1
