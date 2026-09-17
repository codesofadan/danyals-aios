"""What JavaScript changes, and whether Google's first pass can see the page.

The engine's crawler executes no JavaScript, so what it fetches IS Googlebot's
first pass. Every check here compares that against a real browser render.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from audit_engine.analyzers import rendering as r
from audit_engine.analyzers.rendering import RenderedPage


@dataclass
class P:
    title: str | None = "A dental clinic in Lahore"
    h1s: list = field(default_factory=lambda: ["Dental implants"])
    word_count: int = 800
    links: list = field(default_factory=lambda: [object()] * 20)
    images: list = field(default_factory=lambda: [object()] * 10)
    schema_blocks: list = field(default_factory=lambda: [{"@type": "Organization"}])
    viewport: str | None = "width=device-width, initial-scale=1"


def page(**kw) -> RenderedPage:
    raw = kw.pop("raw", P())
    rendered = kw.pop("rendered", P())
    return RenderedPage(
        url="https://example.com/",
        raw_html=kw.pop("raw_html", "<html><body><p>hi</p></body></html>"),
        rendered_html=kw.pop("rendered_html", "<html><body><p>hi</p></body></html>"),
        raw=raw, rendered=rendered, **kw,
    )


ALL = [
    r.check_javascript_rendering, r.check_client_side_rendering,
    r.check_dom_content_comparison, r.check_hidden_content,
    r.check_js_hidden_content, r.check_dom_size, r.check_lazy_load_indexing,
    r.check_mobile_rendering, r.check_responsive_design,
]


# --- the n_a contract -------------------------------------------------------

@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_a_failed_render_is_n_a_not_a_failing_page(fn):
    """We could not look. That is not the same as the page being broken."""
    v = fn(RenderedPage(url="https://example.com/", error="timed out"))
    assert v.status == "n_a" and v.confidence == 0.0
    assert not v.remediation


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_no_pre_render_capture_is_n_a(fn):
    """Without the first-pass HTML there is nothing to compare against."""
    v = fn(RenderedPage(url="https://example.com/", rendered_html="<html></html>",
                        rendered=P(), raw=None))
    assert v.status == "n_a"


@pytest.mark.parametrize("fn", ALL, ids=lambda f: f.__name__)
def test_every_verdict_is_well_formed(fn):
    for p in (page(), RenderedPage(url="x", error="nope")):
        v = fn(p)
        assert v.status in {"pass", "warn", "fail", "n_a"}
        assert 0.0 <= v.score <= 10.0 and 0.0 <= v.confidence <= 1.0


# --- how much of the page needs JavaScript ----------------------------------

def test_a_server_rendered_page_passes():
    assert r.check_javascript_rendering(page()).status == "pass"


def test_a_page_that_is_mostly_javascript_fails():
    v = r.check_javascript_rendering(page(raw=P(word_count=40), rendered=P(word_count=800)))
    assert v.status == "fail"
    assert v.evidence["share_present_before_js"] == 0.05
    assert "best-effort" in v.remediation


def test_a_partly_javascript_page_warns_without_overstating():
    """Google DOES render. The finding is delay and risk, not invisibility."""
    v = r.check_javascript_rendering(page(raw=P(word_count=400), rendered=P(word_count=800)))
    assert v.status == "warn"
    assert "renders eventually" in v.remediation


def test_the_ratio_threshold_is_labelled_judgement():
    assert "judgement" in r.check_javascript_rendering(page()).evidence["threshold_basis"]


# --- title and H1 -----------------------------------------------------------

def test_a_title_that_only_exists_after_javascript_is_major():
    v = r.check_client_side_rendering(page(raw=P(title=None), rendered=P()))
    assert v.status == "fail" and v.severity == "major"
    assert v.remediation.startswith("The title")


def test_the_remediation_does_not_lowercase_h1():
    """`.capitalize()` uppercases the first character and LOWERCASES the rest,
    which turned "the H1" into "the h1" in a client-facing sentence."""
    v = r.check_client_side_rendering(page(raw=P(h1s=[]), rendered=P()))
    assert "H1" in v.remediation and "h1 " not in v.remediation


def test_an_h1_that_only_exists_after_javascript_is_caught():
    v = r.check_client_side_rendering(page(raw=P(h1s=[]), rendered=P()))
    assert v.status == "fail" and "H1" in v.remediation


def test_a_page_with_both_before_render_passes():
    assert r.check_client_side_rendering(page()).status == "pass"


# --- what rendering adds ----------------------------------------------------

def test_schema_that_exists_only_after_javascript_is_major():
    v = r.check_dom_content_comparison(page(raw=P(schema_blocks=[]), rendered=P()))
    assert v.status == "fail"
    assert "schema_blocks" in v.evidence["added_by_js"]


def test_rendering_that_adds_nothing_passes():
    assert r.check_dom_content_comparison(page()).status == "pass"


def test_rendering_that_merely_adds_more_warns():
    v = r.check_dom_content_comparison(
        page(raw=P(links=[object()] * 5), rendered=P(links=[object()] * 20)))
    assert v.status == "warn"


# --- hidden content ---------------------------------------------------------

def test_hidden_content_is_reported_without_crying_cloaking():
    """Most hidden content is menus, tabs and modals. Google discounts rather
    than penalises it, and an audit that calls it cloaking is crying wolf."""
    html = '<div style="display:none">menu</div><span style="visibility:hidden">x</span>'
    v = r.check_js_hidden_content(page(rendered_html=html))
    assert v.status == "warn" and v.severity == "minor"
    assert "legitimate" in v.remediation
    assert v.confidence <= 0.6


def test_a_page_with_nothing_hidden_passes():
    assert r.check_hidden_content(page()).status == "pass"


# --- DOM size ---------------------------------------------------------------

def test_dom_size_uses_lighthouses_own_thresholds():
    small = page(rendered_html="<div>" * 100)
    assert r.check_dom_size(small).status == "pass"
    mid = page(rendered_html="<div>" * 1000)
    assert r.check_dom_size(mid).status == "warn"
    huge = page(rendered_html="<div>" * 2000)
    v = r.check_dom_size(huge)
    assert v.status == "fail"
    assert v.evidence["threshold_basis"] == "Lighthouse dom-size audit"


# --- lazy loading -----------------------------------------------------------

def test_native_lazy_loading_is_not_penalised():
    """Google handles loading="lazy". The risk is a JS loader with no src."""
    html = '<img loading="lazy" src="/a.png"><img loading="lazy" src="/b.png">'
    v = r.check_lazy_load_indexing(page(rendered_html=html, raw=P(images=[object()] * 10)))
    assert v.status == "pass"
    assert v.evidence["native_lazy_loading"] == 2


def test_images_with_no_source_before_javascript_are_flagged():
    v = r.check_lazy_load_indexing(page(raw=P(images=[]), rendered=P(images=[object()] * 10)))
    assert v.status == "fail"
    assert v.evidence["images_only_after_js"] == 10
    assert "may never" in v.remediation


def test_a_page_with_no_images_is_n_a():
    v = r.check_lazy_load_indexing(page(raw=P(images=[]), rendered=P(images=[])))
    assert v.status == "n_a"


# --- mobile -----------------------------------------------------------------

def test_a_desktop_render_cannot_judge_mobile():
    v = r.check_mobile_rendering(page(mobile=False))
    assert v.status == "n_a"
    assert "desktop viewport" in v.evidence["reason"]


def test_a_mobile_render_with_no_viewport_tag_is_critical():
    v = r.check_mobile_rendering(page(mobile=True, rendered=P(viewport=None)))
    assert v.status == "fail" and v.severity == "critical"


def test_a_healthy_mobile_render_passes():
    assert r.check_mobile_rendering(page(mobile=True)).status == "pass"


def test_the_mobile_only_index_is_stated():
    assert "mobile-only" in r.check_mobile_rendering(page(mobile=True)).evidence["context"]


# --- responsive -------------------------------------------------------------

def test_responsive_design_states_what_it_cannot_prove():
    """Markup signals cannot prove a LAYOUT works. The evidence says so."""
    v = r.check_responsive_design(page(rendered_html="<style>@media screen{}</style>"))
    assert "screenshots" in v.evidence["limit"]


def test_a_missing_viewport_dominates_the_responsive_verdict():
    v = r.check_responsive_design(page(rendered=P(viewport=None)))
    assert v.status == "fail" and v.severity == "major"


def test_media_queries_and_a_viewport_pass():
    v = r.check_responsive_design(page(rendered_html="<style>@media (min-width:40em){}</style>"))
    assert v.status == "pass"
