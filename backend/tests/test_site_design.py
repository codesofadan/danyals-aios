"""Site-design EXTRACTOR: the pure analysis core, its degrade paths, the endpoint
(summarizer + gate + fetcher all faked -> NO network / NO real provider), and the
source_pack seeding + the publish section-wrapping.

Proves:

* the pure ``extract_site_design`` parses a fixed-JSON reply into a ``SiteDesignProfile``,
  commits exactly ONE token-only cost under the ``content`` dial, and passes the design
  system prompt through to the summarizer;
* every degrade path (keyless summarizer / a gate block / an unparseable reply) returns a
  clean ``status='degraded'`` shell with ``profile=None`` and never crashes - and a gate
  block / keyless degrade makes NO provider call;
* a partial JSON reply still yields a usable profile (missing fields default);
* the endpoint returns 200 + the profile on fakes (no network), and degrades cleanly;
* a content job's ``source_pack`` stores a supplied ``design_profile``, and the publish
  body is wrapped in ordered ``<section class="aios-<name>">`` blocks when a profile is
  present and is byte-for-byte unchanged when absent.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from fastapi import FastAPI

import app.services.site_design as site_design
from app.config import Settings
from app.core.auth import CurrentUser, get_current_user
from app.routers.content import (
    _seed_source_pack,
    get_design_fetcher,
    get_design_gate,
    get_design_summarizer,
)
from app.services import pricing
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.site_design import (
    DEGRADE_ANALYSIS_FAILED,
    DEGRADE_NO_ANTHROPIC,
    extract_site_design,
)
from integrations.llm import LLMResult
from workers.tasks.content import _shape_body_html, md_to_html

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Fakes
# --------------------------------------------------------------------------- #
_VALID_JSON = json.dumps(
    {
        "palette": {
            "primary": "#0a0a0a", "secondary": "#333333", "background": "#ffffff",
            "text": "#111111", "accent": "#ff6600",
        },
        "typography": {
            "heading_font": "Poppins, sans-serif", "body_font": "Inter, sans-serif",
            "base_size": "18px",
        },
        "layout": {
            "container_width": "1140px",
            "section_order": ["hero", "services", "faq", "cta"],
            "hero_style": "split", "cta_style": "banner",
        },
        "components": {"button_style": "pill", "card_style": "bordered", "spacing_scale": "airy"},
        "notes": "Bold headings, lots of whitespace.",
    }
)


class FakeSystemSummarizer:
    """Deterministic ``SystemSummarizer``: returns a fixed payload, records the ``system``
    prompt it was handed + the token counts it reported. No network."""

    def __init__(self, *, payload: str = _VALID_JSON) -> None:
        self._payload = payload
        self.system: str | None = None
        self.calls = 0
        self.last_input_tokens = 0
        self.last_output_tokens = 0

    def summarize(
        self, prompt: str, *, model: str, max_tokens: int, system: str | None = None
    ) -> LLMResult:
        self.calls += 1
        self.system = system
        self.last_input_tokens = max(1, len(prompt) // 4)
        self.last_output_tokens = max(1, len(self._payload) // 4)
        return LLMResult(
            text=self._payload,
            input_tokens=self.last_input_tokens,
            output_tokens=self.last_output_tokens,
        )


class _FakeCostStore:
    """A configurable ``CostStore``; records every logged cost as (feature, cost, cached)."""

    def __init__(
        self, *, dials: dict[str, DialMode] | None = None,
        budget: tuple[float, float] | None = None, halted: bool = False,
    ) -> None:
        self._dials = dials or {}
        self._budget = budget
        self._halted = halted
        self.records: list[tuple[str, float, bool]] = []

    def dial_mode(self, feature_key: str) -> DialMode:
        return self._dials.get(feature_key, "api")

    def client_budget(self, client_id: str) -> tuple[float, float] | None:
        return self._budget

    def is_halted(self) -> bool:
        return self._halted

    def record_cost(self, ctx: GateContext, cost: float, *, cached: bool) -> None:
        self.records.append((ctx.feature_key, cost, cached))


class _NullCache:
    def get(self, key: str) -> Any | None:
        return None

    def set(self, key: str, value: Any) -> None:
        return None


def _settings(**over: Any) -> Settings:
    return Settings(_env_file=None, app_env="dev", **over)


def _gate(store: _FakeCostStore | None = None) -> CostGate:
    return CostGate(store or _FakeCostStore(), _NullCache())


# --------------------------------------------------------------------------- #
# 1. The pure core: parse + token-only commit + system pass-through
# --------------------------------------------------------------------------- #
def test_extract_ok_parses_profile_commits_token_cost_and_passes_system() -> None:
    settings = _settings()
    summ = FakeSystemSummarizer()
    store = _FakeCostStore()
    result = extract_site_design(
        summarizer=summ, gate=_gate(store), settings=settings, pages=["<html><body>hi</body></html>"]
    )

    assert result.status == "ok"
    assert result.profile is not None
    assert result.profile.palette.primary == "#0a0a0a"
    assert result.profile.palette.accent == "#ff6600"
    assert result.profile.typography.heading_font == "Poppins, sans-serif"
    assert result.profile.layout.section_order == ["hero", "services", "faq", "cta"]
    assert result.profile.layout.hero_style == "split"
    assert result.profile.components.button_style == "pill"

    # The design system prompt was passed through to the summarizer.
    assert summ.calls == 1
    assert summ.system == site_design._DESIGN_SYSTEM_PROMPT

    # Exactly ONE commit, TOKEN-only, under the content dial, not cached.
    assert len(store.records) == 1
    feature, cost, cached = store.records[0]
    assert feature == "content"
    assert cached is False
    expected = pricing.anthropic_cost(
        settings, model=settings.content_design_model,
        input_tokens=summ.last_input_tokens, output_tokens=summ.last_output_tokens,
    )
    assert cost == expected
    assert cost > 0  # token cost, not a flat/free constant


def test_partial_json_still_yields_usable_profile_with_defaults() -> None:
    # A thin reply (only a primary colour) must NOT degrade - missing fields default.
    settings = _settings()
    summ = FakeSystemSummarizer(payload='{"palette": {"primary": "#abcdef"}}')
    result = extract_site_design(
        summarizer=summ, gate=_gate(), settings=settings, pages=["<html></html>"]
    )
    assert result.status == "ok"
    assert result.profile is not None
    assert result.profile.palette.primary == "#abcdef"
    # Defaulted fields are present + usable.
    assert result.profile.palette.background == "#ffffff"
    assert result.profile.layout.section_order == ["hero", "intro", "services", "proof", "faq", "cta"]


# --------------------------------------------------------------------------- #
# 2. Degrade paths
# --------------------------------------------------------------------------- #
def test_degrade_keyless_summarizer_none_before_gate() -> None:
    store = _FakeCostStore()
    result = extract_site_design(
        summarizer=None, gate=_gate(store), settings=_settings(), pages=["<html></html>"]
    )
    assert result.status == "degraded"
    assert result.profile is None
    assert result.reason == DEGRADE_NO_ANTHROPIC
    assert store.records == []  # the gate was never consulted, no call


def test_degrade_gate_block_makes_no_call() -> None:
    store = _FakeCostStore(dials={"content": "off"})  # dial off -> skip
    summ = FakeSystemSummarizer()
    result = extract_site_design(
        summarizer=summ, gate=_gate(store), settings=_settings(), pages=["<html></html>"]
    )
    assert result.status == "degraded"
    assert result.profile is None
    assert result.reason == "cost_gate:skip"
    assert summ.calls == 0  # NO provider call happened
    assert store.records == []  # nothing committed


def test_degrade_spend_halt_makes_no_call() -> None:
    store = _FakeCostStore(halted=True)
    summ = FakeSystemSummarizer()
    result = extract_site_design(
        summarizer=summ, gate=_gate(store), settings=_settings(), pages=["<html></html>"]
    )
    assert result.status == "degraded"
    assert result.reason == "cost_gate:blocked_halt"
    assert summ.calls == 0
    assert store.records == []


def test_degrade_bad_json_reply() -> None:
    # A reply with no JSON object at all degrades - the real token spend is still committed.
    store = _FakeCostStore()
    summ = FakeSystemSummarizer(payload="Sorry, I could not analyze that page.")
    result = extract_site_design(
        summarizer=summ, gate=_gate(store), settings=_settings(), pages=["<html></html>"]
    )
    assert result.status == "degraded"
    assert result.profile is None
    assert result.reason == DEGRADE_ANALYSIS_FAILED
    assert summ.calls == 1
    assert len(store.records) == 1  # the call ran, so its token spend is committed honestly


# --------------------------------------------------------------------------- #
# 3. The endpoint (summarizer + gate + fetcher all faked -> no network)
# --------------------------------------------------------------------------- #
def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


def _wire(app: FastAPI, summarizer: Any, *, role: str = "manager") -> _FakeCostStore:
    store = _FakeCostStore()

    async def _fake_fetch(site: str, max_pages: int) -> list[str]:
        return ["<html><body><h1>Home</h1></body></html>"]  # fixed HTML, no network

    app.dependency_overrides[get_current_user] = lambda: _user(role)
    app.dependency_overrides[get_design_summarizer] = lambda: summarizer
    app.dependency_overrides[get_design_gate] = lambda: _gate(store)
    app.dependency_overrides[get_design_fetcher] = lambda: _fake_fetch
    return store


async def test_endpoint_returns_profile_on_fakes(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    _wire(app, FakeSystemSummarizer())
    # A public IP literal so the SSRF guard needs NO DNS lookup (fully offline).
    resp = await client.post(
        "/api/v1/content/site-design", json={"site": "https://1.2.3.4", "maxPages": 2}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["reason"] == ""
    assert body["profile"]["palette"]["primary"] == "#0a0a0a"
    assert body["profile"]["layout"]["section_order"] == ["hero", "services", "faq", "cta"]
    assert body["profile"]["typography"]["heading_font"] == "Poppins, sans-serif"


async def test_endpoint_degrades_cleanly_without_key(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    _wire(app, None)  # keyless summarizer
    resp = await client.post("/api/v1/content/site-design", json={"site": "https://1.2.3.4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["profile"] is None
    assert body["reason"] == DEGRADE_NO_ANTHROPIC


async def test_endpoint_requires_publish_content(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    _wire(app, FakeSystemSummarizer(), role="analyst")  # holds view_reports, NOT publish_content
    resp = await client.post("/api/v1/content/site-design", json={"site": "https://1.2.3.4"})
    assert resp.status_code == 403


# --------------------------------------------------------------------------- #
# 4. source_pack seeding + publish section-wrapping
# --------------------------------------------------------------------------- #
_PROFILE_DICT: dict[str, Any] = {
    "palette": {"primary": "#0a0a0a"},
    "layout": {"section_order": ["hero", "services", "cta"]},
}


def test_seed_source_pack_stores_design_profile() -> None:
    pack = _seed_source_pack(
        {"name": "Verde Cafe"}, None, target="PDF/Markdown", design_profile=_PROFILE_DICT
    )
    assert pack["design_profile"] == _PROFILE_DICT
    assert pack["client_name"] == "Verde Cafe"


def test_seed_source_pack_omits_design_profile_when_absent() -> None:
    pack = _seed_source_pack({"name": "Verde Cafe"}, None, target="PDF/Markdown")
    assert "design_profile" not in pack


_DRAFT = (
    "# Best Brunch\n\nWe serve the best brunch in town.\n\n"
    "## Our Services\n\nWeekend brunch and espresso.\n\n"
    "## Get in Touch\n\nCome visit us today.\n"
)


def test_publish_body_wraps_sections_when_profile_present() -> None:
    row = {"source_pack": {"design_profile": {"layout": {"section_order": ["hero", "services", "cta"]}}}}
    out = _shape_body_html(row, _DRAFT)
    assert '<section class="aios-hero">' in out
    assert '<section class="aios-services">' in out
    assert '<section class="aios-cta">' in out
    # The content itself is preserved inside the wrapped structure.
    assert "<h1>Best Brunch</h1>" in out
    assert "<h2>Our Services</h2>" in out


def test_publish_body_unchanged_without_profile() -> None:
    row = {"source_pack": {"client_name": "Verde Cafe"}}  # no design_profile
    out = _shape_body_html(row, _DRAFT)
    assert out == md_to_html(_DRAFT)  # byte-for-byte today's behavior (no regression)
    assert "<section" not in out
