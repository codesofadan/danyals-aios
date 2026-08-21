"""Unit gate for ``app.services.visual_diff``: STRUCTURED visual-QA diagnostics
(spec section 27) - typography/layout/spacing/color/size/image/responsive
mismatches, each with a section + a human detail line, never just one score.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.visual_diff import diff_design_against_capture
from integrations.site_analyzer import (
    AssetSnapshot,
    SectionSnapshot,
    SiteCapture,
    TypographySample,
    ViewportCapture,
)

pytestmark = pytest.mark.unit


def _design(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "typography": {"base_size": "17px"},
        "layout": {"container_width_px": 1200},
        "sections": [
            {"kind": "hero", "bg_color": "rgb(255, 255, 255)", "width": 1440, "height": 560},
            {"kind": "benefits", "bg_color": "rgb(246, 248, 251)", "width": 1440, "height": 420},
        ],
        "assets": [{"url": "https://example.com/logo.png", "kind": "logo"}],
        "responsive": [
            {"viewport": "desktop", "section_count": 2},
            {"viewport": "mobile", "section_count": 2},
        ],
    }
    base.update(over)
    return base


def _rendered_capture(**over: Any) -> SiteCapture:
    sections: list[SectionSnapshot] = over.get("sections", [
        SectionSnapshot(tag="div", role="section", bg_color="rgb(255, 255, 255)", width=1440, height=560),
        SectionSnapshot(tag="div", role="section", bg_color="rgb(246, 248, 251)", width=1440, height=420),
    ])
    typography: list[TypographySample] = over.get("typography", [TypographySample(tag="p", font_size="17px")])
    assets: list[AssetSnapshot] = over.get("assets", [AssetSnapshot(url="https://example.com/logo.png", kind="logo")])
    container: float | None = over.get("container_width_px", 1200)
    desktop = ViewportCapture(
        viewport="desktop", width=1440, height=900, sections=sections, typography=typography,
        assets=assets, container_width_px=container,
    )
    mobile: ViewportCapture = over.get("mobile_viewport", ViewportCapture(
        viewport="mobile", width=390, height=844,
        sections=[SectionSnapshot(tag="div", role="section")] * 2,
    ))
    return SiteCapture(url="https://built.example.com", viewports=[desktop, mobile])


def test_identical_capture_passes_clean() -> None:
    result = diff_design_against_capture(_design(), _rendered_capture())
    assert result.status == "pass"
    assert result.diagnostics == []


def test_font_size_drift_is_a_typography_mismatch() -> None:
    rendered = _rendered_capture(typography=[TypographySample(tag="p", font_size="13px")])
    result = diff_design_against_capture(_design(), rendered)
    kinds = {d.kind for d in result.diagnostics}
    assert "typography" in kinds
    assert result.status in ("warn", "fail")


def test_missing_section_is_a_layout_mismatch() -> None:
    rendered = _rendered_capture(sections=[SectionSnapshot(tag="div", role="section", bg_color="rgb(255, 255, 255)")])
    result = diff_design_against_capture(_design(), rendered)
    assert any(d.kind == "layout" for d in result.diagnostics)


def test_container_width_drift_is_a_spacing_mismatch() -> None:
    rendered = _rendered_capture(container_width_px=900)
    result = diff_design_against_capture(_design(), rendered)
    assert any(d.kind == "spacing" for d in result.diagnostics)


def test_background_color_drift_is_a_color_mismatch() -> None:
    rendered = _rendered_capture(
        sections=[
            SectionSnapshot(tag="div", role="section", bg_color="rgb(10, 10, 10)", width=1440, height=560),
            SectionSnapshot(tag="div", role="section", bg_color="rgb(246, 248, 251)", width=1440, height=420),
        ]
    )
    result = diff_design_against_capture(_design(), rendered)
    assert any(d.kind == "color" and d.section == "hero" for d in result.diagnostics)


def test_width_drift_is_a_size_mismatch() -> None:
    rendered = _rendered_capture(
        sections=[
            SectionSnapshot(tag="div", role="section", bg_color="rgb(255, 255, 255)", width=700, height=560),
            SectionSnapshot(tag="div", role="section", bg_color="rgb(246, 248, 251)", width=1440, height=420),
        ]
    )
    result = diff_design_against_capture(_design(), rendered)
    assert any(d.kind == "size" for d in result.diagnostics)


def test_missing_images_is_an_image_mismatch() -> None:
    rendered = _rendered_capture(assets=[])
    result = diff_design_against_capture(_design(), rendered)
    assert any(d.kind == "image" for d in result.diagnostics)


def test_mobile_section_count_drift_is_a_responsive_mismatch() -> None:
    rendered = _rendered_capture(
        mobile_viewport=ViewportCapture(
            viewport="mobile", width=390, height=844,
            sections=[SectionSnapshot(tag="div", role="section")],  # only 1, design expected 2
        )
    )
    result = diff_design_against_capture(_design(), rendered)
    assert any(d.kind == "responsive" and d.section == "mobile" for d in result.diagnostics)


def test_many_mismatches_escalate_to_fail() -> None:
    rendered = _rendered_capture(
        sections=[SectionSnapshot(tag="div", role="section", bg_color="rgb(0,0,0)", width=200, height=100)],
        typography=[TypographySample(tag="p", font_size="9px")],
        container_width_px=400,
        assets=[],
    )
    result = diff_design_against_capture(_design(), rendered)
    assert result.status == "fail"


def test_diagnostic_as_dict_is_json_safe() -> None:
    rendered = _rendered_capture(container_width_px=400)
    result = diff_design_against_capture(_design(), rendered)
    d = result.as_dict()
    assert d["status"] in ("warn", "fail")
    assert all(isinstance(item["magnitude"], float) for item in d["diagnostics"])
