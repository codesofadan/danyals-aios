"""Unit gate for RUNTIME cost computation (app/services/pricing.py).

Proves every logged cost is ACTUAL usage x a real provider unit price, never a flat
per-call constant: the model tiers correctly (incl. dated/unknown ids), each provider
cost scales with its usage unit, and the audit cost has a precise (engine-reported
token) path plus a derived (pages + agent-calls) fallback -- and free = $0.
"""

from __future__ import annotations

import pytest

from app.config import Settings
from app.services import pricing

pytestmark = pytest.mark.unit


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_anthropic_tier_maps_including_dated_and_unknown() -> None:
    assert pricing.anthropic_tier("claude-haiku-4-5-20251001") == "haiku"
    assert pricing.anthropic_tier("claude-sonnet-5") == "sonnet"
    assert pricing.anthropic_tier("claude-opus-4-8") == "opus"
    # An unrecognised model errs to the TOP tier (never silently priced free/cheap).
    assert pricing.anthropic_tier("mystery-model-9") == "opus"


def test_anthropic_cost_is_tokens_times_unit_price() -> None:
    s = _settings()
    # haiku defaults: 1.00 in / 5.00 out per MTok. 10k in + 2k out -> (10000+10000)/1e6.
    assert pricing.anthropic_cost(s, model="claude-haiku-4-5", input_tokens=10_000, output_tokens=2_000) == 0.02
    # sonnet is pricier than haiku for identical usage.
    haiku = pricing.anthropic_cost(s, model="claude-haiku-4-5", input_tokens=1_000, output_tokens=1_000)
    sonnet = pricing.anthropic_cost(s, model="claude-sonnet-5", input_tokens=1_000, output_tokens=1_000)
    assert sonnet > haiku
    # Negative/garbage usage never bills negative.
    assert pricing.anthropic_cost(s, model="x", input_tokens=-5, output_tokens=-9) == 0.0


def test_per_unit_providers_scale_with_usage() -> None:
    s = _settings()
    assert pricing.serper_cost(s, queries=10) == round(10 * s.price_serper_per_query, 6)
    assert pricing.google_api_cost(s, calls=3) == round(3 * s.price_google_per_call, 6)
    assert pricing.image_cost(s, images=2) == round(2 * s.price_image_per_image, 6)
    assert pricing.dataforseo_cost(s, calls=4) == round(4 * s.price_dataforseo_per_call, 6)
    assert pricing.serper_cost(s, queries=0) == 0.0


def test_voyage_embed_cost_scales_with_derived_tokens() -> None:
    s = _settings()
    tokens = pricing.approx_tokens("a" * 400)  # ~100 tokens at 4 chars/token
    assert tokens == 100
    assert pricing.voyage_embed_cost(s, tokens=tokens) == round(100 * s.price_voyage_per_mtok / 1_000_000, 6)


def test_audit_cost_free_is_zero() -> None:
    assert pricing.audit_cost(_settings(), pages_crawled=50, mode="free") == 0.0


def test_audit_cost_precise_path_uses_engine_reported_usage() -> None:
    s = _settings()
    usage = {"model": "claude-haiku-4-5", "input_tokens": 100_000, "output_tokens": 20_000,
             "serper_queries": 5, "places_calls": 2}
    expected = (
        pricing.anthropic_cost(s, model="claude-haiku-4-5", input_tokens=100_000, output_tokens=20_000)
        + pricing.serper_cost(s, queries=5)
        + pricing.google_api_cost(s, calls=2)
    )
    assert pricing.audit_cost(s, pages_crawled=80, mode="paid", usage=usage) == round(expected, 6)


def test_audit_cost_derived_fallback_scales_with_pages_and_agents() -> None:
    s = _settings()
    # No engine token usage -> derived: pages x per-page + agent_calls x haiku-per-agent.
    small = pricing.audit_cost(s, pages_crawled=10, mode="paid", usage=None)
    big = pricing.audit_cost(s, pages_crawled=200, mode="paid", usage=None)
    assert big > small > 0.0  # scales with real crawl breadth, never a flat constant
