"""Site-design EXTRACTOR: the pure VISION analysis core, its degrade paths, the endpoint
(summarizer + gate + firecrawl + fetcher all faked -> NO network / NO real provider), and
the source_pack seeding + the publish section-wrapping.

Proves:

* the pure ``extract_site_design`` parses a fixed-JSON reply (incl. ``wireframe_html``)
  into a ``SiteDesignProfile``, commits exactly ONE token-only cost under the ``content``
  dial, passes the design system prompt AND the screenshot through to the summarizer;
* TWO different fake replies yield TWO DIFFERENT profiles - proving the extract reflects
  the model's actual analysis, not hardcoded dataclass defaults (the bug);
* every degrade path (keyless summarizer / a gate block / an unparseable reply) returns a
  clean ``status='degraded'`` shell with ``profile=None`` and never crashes - and a gate
  block / keyless degrade makes NO provider call;
* a partial JSON reply still yields a usable profile (missing fields default);
* the endpoint returns 200 + the profile + the wireframe on fakes (Firecrawl render +
  vision, no network), FALLS BACK to the plain fetcher when Firecrawl is unconfigured,
  and degrades cleanly;
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
    get_design_analyzer,
    get_design_fetcher,
    get_design_firecrawl,
    get_design_gate,
    get_design_summarizer,
)
from app.services import pricing
from app.services.cost_gate import CostGate, DialMode, GateContext
from app.services.site_design import (
    DEGRADE_ANALYSIS_FAILED,
    DEGRADE_NO_ANTHROPIC,
    DesignResult,
    extract_site_design,
)
from integrations.firecrawl import FakeFirecrawl, FirecrawlPage
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
        "wireframe_html": (
            "<style>.hero{background:#0a0a0a;color:#fff;font-family:Poppins}</style>"
            "<section class='hero'><h1>Welcome</h1></section>"
        ),
    }
)

# A DIFFERENT site's reply - to prove the extract varies per site (not templated defaults).
_OTHER_JSON = json.dumps(
    {
        "palette": {
            "primary": "#14532d", "secondary": "#166534", "background": "#f0fdf4",
            "text": "#052e16", "accent": "#22c55e",
        },
        "typography": {
            "heading_font": "Merriweather, serif", "body_font": "Georgia, serif",
            "base_size": "17px",
        },
        "layout": {
            "container_width": "960px",
            "section_order": ["hero", "about", "gallery", "contact"],
            "hero_style": "full-bleed", "cta_style": "inline",
        },
        "components": {"button_style": "ghost", "card_style": "flat", "spacing_scale": "tight"},
        "notes": "Earthy, editorial.",
        "wireframe_html": "<style>.hero{background:#14532d}</style><section class='hero'>Green</section>",
    }
)


class FakeSystemSummarizer:
    """Deterministic ``SystemSummarizer``: returns a fixed payload, records the ``system``
    prompt + the ``image_b64`` it was handed + the token counts it reported. No network."""

    def __init__(self, *, payload: str = _VALID_JSON) -> None:
        self._payload = payload
        self.system: str | None = None
        self.image_b64: str | None = None
        self.calls = 0
        self.last_input_tokens = 0
        self.last_output_tokens = 0

    def summarize(
        self,
        prompt: str,
        *,
        model: str,
        max_tokens: int,
        system: str | None = None,
        image_b64: str | None = None,
    ) -> LLMResult:
        self.calls += 1
        self.system = system
        self.image_b64 = image_b64
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
# 1. The pure core: parse + wireframe + token-only commit + system/image pass-through
# --------------------------------------------------------------------------- #
def test_extract_ok_parses_profile_wireframe_commits_cost_passes_system_and_image() -> None:
    settings = _settings()
    summ = FakeSystemSummarizer()
    store = _FakeCostStore()
    result = extract_site_design(
        summarizer=summ, gate=_gate(store), settings=settings,
        content="# Rendered home\n\nReal markdown from Firecrawl.", screenshot_b64="c2hvdA==",
    )

    assert result.status == "ok"
    assert result.profile is not None
    assert result.profile.palette.primary == "#0a0a0a"
    assert result.profile.palette.accent == "#ff6600"
    assert result.profile.typography.heading_font == "Poppins, sans-serif"
    assert result.profile.layout.section_order == ["hero", "services", "faq", "cta"]
    assert result.profile.layout.hero_style == "split"
    assert result.profile.components.button_style == "pill"
    # The NEW wireframe is parsed onto the profile.
    assert "<section class='hero'>" in result.profile.wireframe_html
    assert result.profile.wireframe_html.startswith("<style>")

    # The design system prompt AND the screenshot were passed through to the summarizer.
    assert summ.calls == 1
    assert summ.system == site_design._DESIGN_SYSTEM_PROMPT
    assert summ.image_b64 == "c2hvdA=="

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


def test_two_different_replies_yield_two_different_profiles() -> None:
    # THE BUG WAS: every site collapsed to the SAME templated defaults. Prove the extract
    # reflects the model's real analysis by feeding two different site replies.
    settings = _settings()
    a = extract_site_design(
        summarizer=FakeSystemSummarizer(payload=_VALID_JSON), gate=_gate(), settings=settings,
        content="site A", screenshot_b64="AAAA",
    )
    b = extract_site_design(
        summarizer=FakeSystemSummarizer(payload=_OTHER_JSON), gate=_gate(), settings=settings,
        content="site B", screenshot_b64="BBBB",
    )
    assert a.profile is not None and b.profile is not None
    assert a.profile.palette.primary != b.profile.palette.primary
    assert a.profile.typography.heading_font != b.profile.typography.heading_font
    assert a.profile.layout.section_order != b.profile.layout.section_order
    assert a.profile.wireframe_html != b.profile.wireframe_html
    # And neither is the dataclass default palette (the templated-bug fingerprint).
    assert a.profile.palette.primary != site_design.Palette().primary
    assert b.profile.palette.primary != site_design.Palette().primary


def test_text_only_when_no_screenshot_passes_image_none() -> None:
    # The fallback path renders no screenshot; the analysis still runs text-only.
    summ = FakeSystemSummarizer()
    result = extract_site_design(
        summarizer=summ, gate=_gate(), settings=_settings(),
        content="joined fallback HTML", screenshot_b64=None,
    )
    assert result.status == "ok"
    assert summ.image_b64 is None


def test_partial_json_still_yields_usable_profile_with_defaults() -> None:
    # A thin reply (only a primary colour) must NOT degrade - missing fields default.
    settings = _settings()
    summ = FakeSystemSummarizer(payload='{"palette": {"primary": "#abcdef"}}')
    result = extract_site_design(
        summarizer=summ, gate=_gate(), settings=settings, content="<html></html>", screenshot_b64=None,
    )
    assert result.status == "ok"
    assert result.profile is not None
    assert result.profile.palette.primary == "#abcdef"
    # Defaulted fields are present + usable.
    assert result.profile.palette.background == "#ffffff"
    assert result.profile.layout.section_order == ["hero", "intro", "services", "proof", "faq", "cta"]
    assert result.profile.wireframe_html == ""  # none supplied -> empty, still usable


def test_wireframe_code_fence_is_stripped() -> None:
    # The model sometimes wraps the snippet in a ```html fence despite strict JSON; strip it.
    payload = json.dumps({"wireframe_html": "```html\n<section>Hi</section>\n```"})
    result = extract_site_design(
        summarizer=FakeSystemSummarizer(payload=payload), gate=_gate(), settings=_settings(),
        content="x", screenshot_b64=None,
    )
    assert result.profile is not None
    assert result.profile.wireframe_html == "<section>Hi</section>"


# --------------------------------------------------------------------------- #
# 2. Degrade paths
# --------------------------------------------------------------------------- #
def test_degrade_keyless_summarizer_none_before_gate() -> None:
    store = _FakeCostStore()
    result = extract_site_design(
        summarizer=None, gate=_gate(store), settings=_settings(), content="<html></html>",
        screenshot_b64=None,
    )
    assert result.status == "degraded"
    assert result.profile is None
    assert result.reason == DEGRADE_NO_ANTHROPIC
    assert store.records == []  # the gate was never consulted, no call


def test_degrade_gate_block_makes_no_call() -> None:
    store = _FakeCostStore(dials={"content": "off"})  # dial off -> skip
    summ = FakeSystemSummarizer()
    result = extract_site_design(
        summarizer=summ, gate=_gate(store), settings=_settings(), content="<html></html>",
        screenshot_b64="c2hvdA==",
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
        summarizer=summ, gate=_gate(store), settings=_settings(), content="<html></html>",
        screenshot_b64=None,
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
        summarizer=summ, gate=_gate(store), settings=_settings(), content="<html></html>",
        screenshot_b64=None,
    )
    assert result.status == "degraded"
    assert result.profile is None
    assert result.reason == DEGRADE_ANALYSIS_FAILED
    assert summ.calls == 1
    assert len(store.records) == 1  # the call ran, so its token spend is committed honestly


# --------------------------------------------------------------------------- #
# 2b. The MEASURED path: profile_from_capture + analyze_website_design (a hand-built
# SiteCapture fixture, no real Playwright/browser - mirrors
# tests/modules/site_builder/test_service.py's fixture).
# --------------------------------------------------------------------------- #
def _sample_capture() -> Any:
    from integrations.site_analyzer import SectionSnapshot, SiteCapture, TypographySample, ViewportCapture

    sections = [
        SectionSnapshot(tag="header", role="header", child_count=2),
        SectionSnapshot(
            tag="div", role="section", heading="Grow faster with AIOS",
            text_sample="The AI platform for agencies.", bg_color="rgb(10, 10, 10)",
            text_color="rgb(255, 255, 255)", width=1440, height=560, child_count=2,
        ),
        SectionSnapshot(
            tag="div", role="section", heading="Frequently asked questions",
            text_sample="Answers to common questions.", bg_color="rgb(10, 10, 10)",
            text_color="rgb(255, 255, 255)", width=1440, height=380, child_count=4,
        ),
        SectionSnapshot(tag="footer", role="footer", child_count=5),
    ]
    typography = [
        TypographySample(tag="h1", font_family="Sora, sans-serif", font_size="56px", color="rgb(255, 102, 0)"),
        TypographySample(tag="p", font_family="Inter, sans-serif", font_size="17px", color="rgb(255, 255, 255)"),
    ]
    desktop = ViewportCapture(
        viewport="desktop", width=1440, height=900, sections=sections,
        typography=typography, container_width_px=1200,
    )
    return SiteCapture(url="https://example.com", title="Example Co", viewports=[desktop])


def test_profile_from_capture_reflects_the_real_measured_values() -> None:
    """The MEASURED profile carries the capture's ACTUAL colours/fonts/section
    order - not the dataclass defaults - proving this is real evidence, not a
    templated fallback (the exact bug class the vision-LLM path's own docstring
    warns about)."""
    profile = site_design.profile_from_capture(_sample_capture())
    assert profile.typography.heading_font == "Sora, sans-serif"
    assert profile.layout.section_order == ["hero", "faq"]
    assert profile.layout.blueprint[0].kind == "hero"
    assert profile.layout.blueprint[0].heading == "Grow faster with AIOS"
    assert profile.layout.container_width == "1200px"


def test_analyze_website_design_degrades_when_the_analyzer_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No real Playwright/browser here - a fake analyzer returning ``degraded``
    proves the wrapper never crashes and carries the reason through, prefixed so a
    caller can tell this WAS the measured path that failed (not the vision-LLM one)."""
    import integrations.site_analyzer as site_analyzer_module
    from integrations.site_analyzer import DEGRADE_CAPTURE_FAILED, CaptureResult

    class _FailingAnalyzer:
        def capture(self, url: str, *, viewports: Any) -> CaptureResult:
            return CaptureResult(status="degraded", capture=None, reason=DEGRADE_CAPTURE_FAILED)

    monkeypatch.setattr(site_analyzer_module, "build_site_analyzer", lambda: _FailingAnalyzer())
    result = site_design.analyze_website_design("https://example.com")
    assert result.status == "degraded"
    assert result.profile is None
    assert result.reason == f"playwright:{DEGRADE_CAPTURE_FAILED}"


def test_analyze_website_design_succeeds_with_a_fake_analyzer(monkeypatch: pytest.MonkeyPatch) -> None:
    import integrations.site_analyzer as site_analyzer_module
    from integrations.site_analyzer import CaptureResult

    class _OkAnalyzer:
        def capture(self, url: str, *, viewports: Any) -> CaptureResult:
            return CaptureResult(status="ok", capture=_sample_capture())

    monkeypatch.setattr(site_analyzer_module, "build_site_analyzer", lambda: _OkAnalyzer())
    result = site_design.analyze_website_design("example.com")  # schemeless input too
    assert result.status == "ok"
    assert result.profile is not None
    assert result.profile.typography.heading_font == "Sora, sans-serif"


# --------------------------------------------------------------------------- #
# 3. The endpoint (summarizer + gate + firecrawl + fetcher all faked -> no network)
# --------------------------------------------------------------------------- #
def _user(role: str) -> CurrentUser:
    return CurrentUser(
        id="u-1", email="op@x.com", role=role, status="active",  # type: ignore[arg-type]
        name="Op", title="", avatar_color="#000", phone="", two_fa=False,
    )


def _fake_degraded_analyzer(site: str) -> DesignResult:
    """The default test override for ``get_design_analyzer``: always degrades (as if
    Playwright were not installed), so every EXISTING test exercises exactly the
    vision-LLM fallback path it always has - Playwright IS importable in this dev
    venv, so leaving the real ``analyze_website_design`` wired in a unit test would
    launch an actual browser + attempt a real navigation."""
    return DesignResult(status="degraded", profile=None, reason="playwright:not_installed")


def _wire(
    app: FastAPI, summarizer: Any, *, role: str = "manager",
    firecrawl: Any = None, fetched: list[str] | None = None,
    analyzer: Any = None,
) -> _FakeCostStore:
    """Override the whole site-design dep graph with fakes (no network).

    ``firecrawl`` defaults to a real ``FakeFirecrawl`` (render + screenshot); pass
    ``None`` to exercise the plain-fetcher FALLBACK path. ``fetched`` is what the fake
    fallback fetcher returns. ``analyzer`` defaults to a fake that always degrades (so
    every pre-existing test still exercises the vision-LLM path); pass a fake that
    returns ``status='ok'`` to prove the MEASURED path wins when it succeeds."""
    store = _FakeCostStore()
    fetched_pages = fetched if fetched is not None else ["<html><body><h1>Home</h1></body></html>"]

    async def _fake_fetch(site: str, max_pages: int) -> list[str]:
        return fetched_pages  # fixed HTML, no network

    app.dependency_overrides[get_current_user] = lambda: _user(role)
    app.dependency_overrides[get_design_summarizer] = lambda: summarizer
    app.dependency_overrides[get_design_gate] = lambda: _gate(store)
    app.dependency_overrides[get_design_firecrawl] = lambda: firecrawl
    app.dependency_overrides[get_design_fetcher] = lambda: _fake_fetch
    app.dependency_overrides[get_design_analyzer] = lambda: (analyzer or _fake_degraded_analyzer)
    return store


async def test_endpoint_returns_profile_and_wireframe_via_firecrawl(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    summ = FakeSystemSummarizer()
    fc = FakeFirecrawl(page=FirecrawlPage(markdown="# Real home", screenshot_b64="c2hvdA=="))
    _wire(app, summ, firecrawl=fc)
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
    # The NEW wireframe is on the wire as camelCase (serialization alias).
    assert "<section" in body["profile"]["wireframeHtml"]
    # Firecrawl was used (screenshot requested + fed to Claude vision), NOT the fetcher.
    assert fc.calls == 1
    assert fc.last_want_screenshot is True
    assert summ.image_b64 == "c2hvdA=="


async def test_endpoint_falls_back_to_fetcher_when_firecrawl_unconfigured(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    summ = FakeSystemSummarizer()
    _wire(app, summ, firecrawl=None, fetched=["<html><body>fallback</body></html>"])
    resp = await client.post("/api/v1/content/site-design", json={"site": "https://1.2.3.4"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    # No Firecrawl -> the plain fetcher ran and NO screenshot reached the vision call.
    assert summ.image_b64 is None


async def test_endpoint_degrades_cleanly_without_key(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    _wire(app, None, firecrawl=FakeFirecrawl())  # keyless summarizer
    resp = await client.post("/api/v1/content/site-design", json={"site": "https://1.2.3.4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["profile"] is None
    assert body["reason"] == DEGRADE_NO_ANTHROPIC


async def test_endpoint_prefers_the_measured_playwright_profile_when_it_succeeds(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    """When the injected analyzer (the real Playwright measurement, in production)
    returns 'ok', the endpoint uses THAT profile and never touches Firecrawl or the
    vision-LLM summarizer at all - proving the measured path is genuinely preferred,
    not just an unused extra branch."""
    measured_profile = site_design.SiteDesignProfile(
        palette=site_design.Palette(primary="#123456"),
        typography=site_design.Typography(heading_font="Measured Sans"),
    )

    def _fake_ok_analyzer(site: str) -> DesignResult:
        return DesignResult(status="ok", profile=measured_profile, reason="")

    summ = FakeSystemSummarizer()
    fc = FakeFirecrawl(page=FirecrawlPage(markdown="# ignored", screenshot_b64="aWdub3JlZA=="))
    _wire(app, summ, firecrawl=fc, analyzer=_fake_ok_analyzer)
    resp = await client.post("/api/v1/content/site-design", json={"site": "https://1.2.3.4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["profile"]["palette"]["primary"] == "#123456"
    assert body["profile"]["typography"]["heading_font"] == "Measured Sans"
    assert fc.calls == 0  # the vision-LLM fallback never ran
    assert summ.calls == 0


async def test_endpoint_falls_back_to_vision_when_the_measured_capture_degrades(
    client: httpx.AsyncClient, app: FastAPI
) -> None:
    """A degraded analyzer result (Playwright unconfigured, or the target site could
    not be captured) falls through to the EXISTING vision-LLM path exactly as before -
    the default ``_wire()`` analyzer already proves this for every other test in this
    file; this test names the fallback explicitly."""
    summ = FakeSystemSummarizer()
    fc = FakeFirecrawl(page=FirecrawlPage(markdown="# Real home", screenshot_b64="c2hvdA=="))
    _wire(app, summ, firecrawl=fc)  # default analyzer always degrades
    resp = await client.post("/api/v1/content/site-design", json={"site": "https://1.2.3.4"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["profile"]["palette"]["primary"] == "#0a0a0a"  # the vision-LLM's profile
    assert fc.calls == 1
    assert summ.calls == 1


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


def test_extracts_the_full_ordered_blueprint() -> None:
    # A reply carrying the deep BLUEPRINT (one object per section) is parsed into the
    # profile's ordered layout.blueprint AND round-trips through as_dict; section_order is
    # DERIVED from the blueprint kinds when the reply omits an explicit section_order.
    payload = json.dumps(
        {
            "palette": {"primary": "#0a0a0a", "background": "#fff", "text": "#111", "accent": "#f60"},
            "layout": {
                "blueprint": [
                    {"kind": "hero", "heading": "We build homes", "layout": "split"},
                    {"kind": "services", "heading": "What we do", "layout": "grid"},
                    "faq",
                    {"kind": "cta", "heading": "Get a quote", "layout": "banner"},
                ]
            },
        }
    )
    summarizer = FakeSystemSummarizer(payload=payload)
    result = extract_site_design(
        summarizer=summarizer, gate=_gate(_FakeCostStore()), settings=_settings(),
        content="rendered text", screenshot_b64=None,
    )
    assert result.status == "ok" and result.profile is not None
    bp = result.profile.layout.blueprint
    assert [s.kind for s in bp] == ["hero", "services", "faq", "cta"]
    assert bp[0].heading == "We build homes" and bp[1].layout == "grid"
    # section_order derived from the blueprint kinds (no explicit array supplied).
    assert result.profile.layout.section_order == ["hero", "services", "faq", "cta"]
    # as_dict carries the blueprint so it round-trips into source_pack.
    d = result.profile.as_dict()
    assert d["layout"]["blueprint"][1] == {"kind": "services", "heading": "What we do", "layout": "grid"}


def test_seed_source_pack_carries_an_explicit_template() -> None:
    pack = _seed_source_pack({"name": "Verde Cafe"}, None, target="PDF/Markdown", template="service")
    assert pack["template"] == "service"


def test_seed_source_pack_omits_template_when_absent() -> None:
    pack = _seed_source_pack({"name": "Verde Cafe"}, None, target="PDF/Markdown")
    assert "template" not in pack  # Auto -> unset (worker derives from page type / analyzed site)


_DRAFT = (
    "# Best Brunch\n\nWe serve the best brunch in town.\n\n"
    "## Our Services\n\nWeekend brunch and espresso.\n\n"
    "## Get in Touch\n\nCome visit us today.\n"
)


def test_publish_body_wraps_sections_when_profile_present() -> None:
    """A profile present -> a DESIGNED page -> native Gutenberg block markup (not the
    flat class-hooked <div> wrap), matching workers.tasks.content's own
    _is_full_width_page rule."""
    row = {"source_pack": {"design_profile": {"layout": {"section_order": ["hero", "services", "cta"]}}}}
    out = _shape_body_html(row, _DRAFT)
    # The analyzed section order drives the block groups (aios-sec aios-<kind>).
    assert '"className":"aios-sec aios-hero' in out
    assert '"className":"aios-sec aios-services' in out
    assert '"className":"aios-sec aios-cta' in out
    # The content itself is preserved inside the block structure.
    assert "Best Brunch" in out
    assert "Our Services" in out


def test_publish_body_unchanged_without_shaping() -> None:
    # A page type with NO full-page template (gbp_post) and no analyzed profile has
    # nothing to shape by -> the body is the plain render (no regression).
    row = {"page_type": "gbp_post", "source_pack": {"client_name": "Verde Cafe"}}
    out = _shape_body_html(row, _DRAFT)
    assert out == md_to_html(_DRAFT)  # byte-for-byte the plain render
    assert "<section" not in out


def test_publish_body_gets_default_template_from_page_type() -> None:
    # No profile, no chosen template, but a real LANDING page type ("service", not
    # blog/faq) -> a DESIGNED page per _is_full_width_page -> the page-type DEFAULT
    # template shapes it as native Gutenberg block markup, so every page looks
    # structured (and is fully block-editable) out of the box.
    row = {"page_type": "service", "source_pack": {"client_name": "Verde Cafe"}}
    out = _shape_body_html(row, _DRAFT)
    # No inline <style> (wp_kses_post would dump it as raw CSS text); the theme + plugin
    # article.css style the aios-sec class hooks instead.
    assert "<style>" not in out
    assert "<!-- wp:group" in out
    assert '"className":"aios-sec' in out
