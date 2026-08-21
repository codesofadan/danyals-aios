"""``app.modules.site_builder.service``: the pure DesignIR builder.

Pure + deterministic (no network/DB/clock) - built from a hand-authored
:class:`SiteCapture` fixture, exactly like ``test_site_design.py`` builds a profile
from parsed JSON. Proves the MEASURED path (a real capture) and the TEMPLATE path
(one of the 7 ``page_blueprints`` templates) both yield a DesignIR body whose
``kind``/``layout`` vocabulary is the SAME one ``page_blueprints`` defines.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.site_builder.service import (
    design_ir_from_capture,
    design_ir_from_template,
    design_ir_to_page_model,
    page_title_for_design,
    rank_templates,
    slugify,
)
from app.services.page_blueprints import LAYOUT_VARIANTS, SECTION_KINDS
from integrations.site_analyzer import (
    AssetSnapshot,
    SectionSnapshot,
    SiteCapture,
    TypographySample,
    ViewportCapture,
)

pytestmark = pytest.mark.unit


def _sample_capture() -> SiteCapture:
    desktop_sections = [
        SectionSnapshot(tag="header", role="header", child_count=2),
        SectionSnapshot(
            tag="div", role="section", heading="Grow faster with AIOS",
            text_sample="The AI platform for agencies.", bg_color="rgb(255, 255, 255)",
            text_color="rgb(17, 24, 39)", width=1440, height=560, child_count=2,
        ),
        SectionSnapshot(
            tag="div", role="section", heading="Why choose us",
            text_sample="Fast. Secure. Proven.", bg_color="rgb(255, 255, 255)",
            text_color="rgb(17, 24, 39)", width=1440, height=420, child_count=3,
        ),
        SectionSnapshot(
            tag="div", role="section", heading="Frequently asked questions",
            text_sample="Answers to common questions.", bg_color="rgb(246, 248, 251)",
            text_color="rgb(17, 24, 39)", width=1440, height=380, child_count=4,
        ),
        SectionSnapshot(tag="footer", role="footer", child_count=5),
    ]
    typography = [
        TypographySample(tag="h1", font_family="Sora, sans-serif", font_size="56px", color="rgb(15, 23, 42)"),
        TypographySample(tag="p", font_family="Inter, sans-serif", font_size="17px", color="rgb(17, 24, 39)"),
        TypographySample(tag="a", color="rgb(37, 99, 235)"),
    ]
    assets = [
        AssetSnapshot(url="https://example.com/logo.png", kind="logo", width=120, height=40),
        AssetSnapshot(url="https://example.com/hero.jpg", kind="image", width=800, height=500),
    ]
    desktop = ViewportCapture(
        viewport="desktop", width=1440, height=900, sections=desktop_sections,
        typography=typography, assets=assets, container_width_px=1200,
    )
    mobile = ViewportCapture(
        viewport="mobile", width=390, height=844,
        sections=[s for s in desktop_sections if s.role == "section"][:2],  # fewer sections: they stacked/merged
        typography=[TypographySample(tag="p", font_size="15px")],
        container_width_px=358,
    )
    return SiteCapture(url="https://example.com", title="Example Co", viewports=[desktop, mobile])


def test_design_ir_from_capture_classifies_hero_first() -> None:
    body = design_ir_from_capture(
        _sample_capture(), source_type="existing_site", source_url="https://example.com",
        industry="saas", page_type="homepage",
    )
    assert body["source_type"] == "existing_site"
    sections = body["sections"]
    assert sections[0]["kind"] == "hero"  # the first main content block is ALWAYS the hero
    assert sections[0]["heading"] == "Grow faster with AIOS"
    # header/footer (page chrome) never become content sections.
    assert all(s["kind"] not in ("header", "footer", "nav") for s in sections)
    kinds = [s["kind"] for s in sections]
    assert "faq" in kinds  # heading-keyword classification found the FAQ block


def test_design_ir_sections_use_the_page_blueprints_vocabulary() -> None:
    body = design_ir_from_capture(
        _sample_capture(), source_type="existing_site", source_url="https://example.com",
    )
    for section in body["sections"]:
        assert section["kind"] in SECTION_KINDS or section["kind"] == "intro"
        assert section["layout"] in LAYOUT_VARIANTS


def test_design_ir_measures_palette_and_typography_from_real_values() -> None:
    body = design_ir_from_capture(
        _sample_capture(), source_type="existing_site", source_url="https://example.com",
    )
    # Measured, not guessed: the palette/typography come straight off the capture.
    assert body["palette"]["background"] == "rgb(255, 255, 255)"
    assert body["palette"]["accent"] == "rgb(37, 99, 235)"
    assert body["typography"]["heading_font"] == "Sora, sans-serif"
    assert body["typography"]["body_font"] == "Inter, sans-serif"
    assert body["layout"]["container_width_px"] == 1200


def test_design_ir_captures_responsive_breakpoints() -> None:
    body = design_ir_from_capture(
        _sample_capture(), source_type="existing_site", source_url="https://example.com",
    )
    responsive = body["responsive"]
    assert {r["viewport"] for r in responsive} == {"desktop", "mobile"}
    desktop = next(r for r in responsive if r["viewport"] == "desktop")
    mobile = next(r for r in responsive if r["viewport"] == "mobile")
    # The mobile capture genuinely observed FEWER sections (real reflow, not guessed).
    assert mobile["section_count"] < desktop["section_count"]
    assert mobile["container_width_px"] == 358


def test_design_ir_dedupes_and_caps_assets() -> None:
    body = design_ir_from_capture(
        _sample_capture(), source_type="existing_site", source_url="https://example.com",
    )
    urls = [a["url"] for a in body["assets"]]
    assert urls == ["https://example.com/logo.png", "https://example.com/hero.jpg"]
    assert body["assets"][0]["kind"] == "logo"


def test_design_ir_from_unknown_template_is_none() -> None:
    assert design_ir_from_template("not-a-real-template") is None


def test_design_ir_from_template_seeds_the_audited_blueprint() -> None:
    body = design_ir_from_template("service", industry="plumbing", page_type="service")
    assert body is not None
    assert body["source_type"] == "template"
    assert body["design_style"] == "service"
    assert body["sections"][0]["kind"] == "hero"
    assert body["layout"]["section_order"][-1] == "cta"  # cta is always last (page_blueprints invariant)
    assert body["palette"]["accent"]  # a classic default, not a blank palette


def test_slugify() -> None:
    assert slugify("Grow Faster With AIOS!") == "grow-faster-with-aios"
    assert slugify("") == "page"


# --------------------------------------------------------------------------- #
# rank_templates (spec section 35: industry + pageType -> recommend N templates)
# --------------------------------------------------------------------------- #
def _row(name: str, *, industry: str = "", page_type: str = "", rating: float | None = None) -> dict[str, Any]:
    return {"name": name, "industry": industry, "page_type": page_type, "rating": rating}


def test_exact_industry_and_page_type_match_ranks_first() -> None:
    rows = [
        _row("Generic Homepage", page_type="homepage"),
        _row("Real Estate Homepage", industry="real_estate", page_type="homepage"),
        _row("Unrelated Blog", page_type="blog"),
    ]
    ranked = rank_templates(rows, industry="real_estate", page_type="homepage")
    assert ranked[0]["name"] == "Real Estate Homepage"
    assert ranked[1]["name"] == "Generic Homepage"  # generic-for-page-type beats unrelated
    assert ranked[-1]["name"] == "Unrelated Blog"  # never dropped, just ranked last


def test_ties_break_by_rating_then_name() -> None:
    rows = [
        _row("B Template", page_type="homepage", rating=4.0),
        _row("A Template", page_type="homepage", rating=4.5),
        _row("C Template", page_type="homepage", rating=None),
    ]
    ranked = rank_templates(rows, page_type="homepage")
    assert [r["name"] for r in ranked] == ["A Template", "B Template", "C Template"]


def test_no_filters_still_returns_a_stable_order() -> None:
    rows = [_row("Z"), _row("A")]
    ranked = rank_templates(rows)
    assert [r["name"] for r in ranked] == ["A", "Z"]


# --------------------------------------------------------------------------- #
# design_ir_to_page_model / page_title_for_design (Phase 6: DesignIR -> PageModel)
# --------------------------------------------------------------------------- #
def _measured_design(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "source_type": "existing_site",
        "palette": {"primary": "#111"}, "typography": {}, "components": {},
        "sections": [
            {"kind": "hero", "heading": "Grow Faster", "layout": "split",
             "text_sample": "We help agencies scale.", "content": True},
            {"kind": "faq", "heading": "FAQ", "layout": "accordion", "text_sample": "", "content": True},
        ],
    }
    base.update(over)
    return base


def test_design_ir_to_page_model_carries_real_measured_text_for_existing_site() -> None:
    model = design_ir_to_page_model(_measured_design(), title="Grow Faster")
    hero = model["sections"][0]
    assert hero["kind"] == "hero"
    assert hero["visible"] is True
    assert hero["data"]["subhead"] == "We help agencies scale."


def test_design_ir_to_page_model_hides_a_section_with_no_structured_content() -> None:
    model = design_ir_to_page_model(_measured_design(), title="Grow Faster")
    faq = model["sections"][1]
    assert faq["kind"] == "faq"
    assert faq["visible"] is False  # no real Q&A pairs exist yet - a hidden placeholder


def test_design_ir_to_page_model_never_copies_reference_site_text() -> None:
    """spec section 5: a reference-site's design is borrowed, its COPY is not."""
    model = design_ir_to_page_model(_measured_design(source_type="reference_site"), title="T")
    hero = model["sections"][0]
    assert hero["data"].get("subhead", "") == ""


def test_design_ir_to_page_model_carries_palette_through() -> None:
    model = design_ir_to_page_model(_measured_design(), title="T")
    assert model["design"]["palette"]["primary"] == "#111"


def test_page_title_prefers_the_hero_heading() -> None:
    assert page_title_for_design(_measured_design()) == "Grow Faster"


def test_page_title_falls_back_to_page_type() -> None:
    design = {"sections": [], "page_type": "service_area"}
    assert page_title_for_design(design) == "Service Area"


def test_page_title_never_blank() -> None:
    assert page_title_for_design({"sections": []}) == "New Page"
