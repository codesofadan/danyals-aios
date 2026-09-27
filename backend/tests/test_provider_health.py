"""A configured key is not a working key.

MEASURED 2026-09-26: the Anthropic key was present and valid and the account had no
credit. Every readiness check in the platform asks whether a credential is CONFIGURED, so
the capability board reported the content pipeline READY while every page died at the
writing stage with `400 - Your credit balance is too low`. An operator reading that board
would have demoed the product to a client on the strength of it.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.config import Settings
from app.services import provider_health
from app.services.preflight import preflight
from app.services.provider_health import anthropic_health

pytestmark = pytest.mark.unit


def _settings(**over: Any) -> Settings:
    base: dict[str, Any] = {
        "_env_file": None, "app_env": "dev", "vault_master_key": "0" * 64,
        "anthropic_api_key": "sk-ant-test-key-abcdefgh",
    }
    base.update(over)
    return Settings(**base)


@pytest.fixture(autouse=True)
def _clear() -> None:
    provider_health.reset_cache()


class _Boom:
    def __init__(self, message: str) -> None:
        self.message = message

    def __call__(self, *a: Any, **k: Any) -> Any:
        raise RuntimeError(self.message)


def _patch_probe(monkeypatch: pytest.MonkeyPatch, behaviour: Any) -> list[int]:
    """Replace the real client with a double; returns a call counter."""
    calls: list[int] = []

    class _Client:
        def __init__(self, **_: Any) -> None:
            pass

        def summarize(self, *a: Any, **k: Any) -> Any:
            calls.append(1)
            return behaviour()

    import integrations.llm as llm

    monkeypatch.setattr(llm, "AnthropicSummarizer", _Client)
    return calls


# --------------------------------------------------------------------------- #
class TestTheProbeDistinguishesFundingFromCredential:
    """The two fixes are unrelated - a billing page and a key rotation - so reporting
    them as one failure tells the operator to do the wrong thing half the time."""

    def test_an_exhausted_balance_reads_as_no_credit(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_probe(monkeypatch, _Boom(
            "Error code: 400 - {'error': {'message': 'Your credit balance is too low "
            "to access the Anthropic API.'}}"
        ))
        result = anthropic_health(_settings())
        assert result.verdict == "no_credit"
        assert not result.usable
        assert "no credit" in result.detail

    def test_a_rejected_key_reads_as_a_bad_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_probe(monkeypatch, _Boom("authentication_error: invalid x-api-key"))
        assert anthropic_health(_settings()).verdict == "bad_key"

    def test_anything_else_reads_as_unreachable_not_as_bad_news(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A network hiccup must not be reported as a dead account."""
        _patch_probe(monkeypatch, _Boom("Connection reset by peer"))
        assert anthropic_health(_settings()).verdict == "unreachable"

    def test_a_working_key_is_ok(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _patch_probe(monkeypatch, lambda: object())
        result = anthropic_health(_settings())
        assert result.verdict == "ok" and result.usable

    def test_no_key_at_all_needs_no_probe(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls = _patch_probe(monkeypatch, lambda: object())
        assert anthropic_health(_settings(anthropic_api_key="")).verdict == "bad_key"
        assert calls == [], "asking the provider about a key we do not have is a wasted call"


class TestTheProbeIsNotASpend:
    def test_the_result_is_cached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A dashboard polling readiness must not turn a health check into a bill."""
        calls = _patch_probe(monkeypatch, lambda: object())
        for _ in range(5):
            anthropic_health(_settings())
        assert len(calls) == 1

    def test_force_re_checks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The operator who just topped up should not wait out the TTL."""
        calls = _patch_probe(monkeypatch, lambda: object())
        anthropic_health(_settings())
        anthropic_health(_settings(), force=True)
        assert len(calls) == 2

    def test_a_different_key_is_probed_separately(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Rotating the key must invalidate the verdict, not inherit the old one."""
        calls = _patch_probe(monkeypatch, lambda: object())
        anthropic_health(_settings(anthropic_api_key="sk-ant-aaaaaaaa"))
        anthropic_health(_settings(anthropic_api_key="sk-ant-bbbbbbbb"))
        assert len(calls) == 2


class TestTheBoardReportsTheTruth:
    @staticmethod
    def _content_gaps(**kw: Any) -> list[str]:
        board = preflight(
            _settings(serper_api_key="s", image_gen_api_key="i"),
            vault_providers={"wordpress"}, dial_modes={}, spend_halted=False,
            engine_keys=set(), **kw,
        )
        for cap in board.capabilities:
            if cap.group == "Content" and "pipeline" in cap.name:
                return [g.what for g in cap.gaps]
        raise AssertionError("the content pipeline capability is missing from the board")

    def test_a_dead_key_blocks_the_content_capability(self) -> None:
        gaps = self._content_gaps(llm_health=("no_credit", "the account has no credit"))
        assert any("fails at the writing stage" in g for g in gaps)

    def test_an_unprobed_key_claims_nothing_either_way(self) -> None:
        """`None` means nobody asked. Inventing a verdict from silence is the failure
        this whole module exists to stop, in the other direction."""
        gaps = self._content_gaps(llm_health=None)
        assert not any("writing stage" in g for g in gaps)

    def test_an_unreachable_probe_does_not_block(self) -> None:
        gaps = self._content_gaps(llm_health=("unknown", ""))
        assert not any("writing stage" in g for g in gaps)
