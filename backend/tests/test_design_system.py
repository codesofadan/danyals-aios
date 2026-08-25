"""Replication stage 2: recovering a site's design language from what it renders.

Validated against the live reference page. Its author declared 44 CSS custom properties
(--oh-brass, --oh-charcoal, --oh-shell...); the hard case is a hand-coded site that
declares none, so the derived-only path is tested against those same tokens as ground
truth it never gets to see.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from app.services.design_system import (
    contrast,
    extract,
    luminance,
    saturation,
    to_hex,
)

pytestmark = pytest.mark.unit

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "replica" / "spotino_desktop.json"

# What the page's author actually declared. The derived path never sees these.
TRUTH = {
    "white": "#ffffff", "shell": "#f9fafb", "charcoal": "#111827", "brass": "#a16207",
    "body": "#4b5563", "muted": "#6b7280",
}


_CSSVARS = pathlib.Path(__file__).parent / "fixtures" / "replica" / "spotino_cssvars.json"


def _framework_vars() -> dict[str, str]:
    """Only the FRAMEWORK variables - readable on any site, unlike the author's own
    tokens, which the derived-only tests deliberately withhold as ground truth."""
    all_vars = json.loads(_CSSVARS.read_text())
    return {k: v for k, v in all_vars.items()
            if k.startswith(("--e-global", "--elementor", "--wp", "--ast", "--kit"))}


@pytest.fixture(scope="module")
def nodes() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []

    def walk(n: dict[str, Any]) -> None:
        out.append(n)
        for k in n.get("kids") or []:
            walk(k)

    walk(json.loads(_FIXTURE.read_text()))
    return out


class TestColourMaths:
    @pytest.mark.parametrize(("raw", "expected"), [
        ("rgb(161, 98, 7)", "#a16207"), ("#A16207", "#a16207"), ("#abc", "#aabbcc"),
        ("rgba(17, 24, 39, 0.9)", "#111827"),
    ])
    def test_colours_normalise(self, raw: str, expected: str) -> None:
        assert to_hex(raw) == expected

    @pytest.mark.parametrize("raw", ["rgba(0, 0, 0, 0)", "transparent", "", "rgba(1,2,3,0.01)"])
    def test_transparent_is_not_a_colour(self, raw: str) -> None:
        assert to_hex(raw) == ""

    def test_a_brand_colour_is_chromatic_and_a_slate_is_not(self) -> None:
        """This single distinction is what separates the accent from a grey. Measured:
        the page's brass is 0.92, the slate that beat it under a naive rule is 0.19."""
        assert saturation("#a16207") > 0.8
        assert saturation("#374151") < 0.25
        assert saturation("#ffffff") == 0.0

    def test_luminance_orders_light_to_dark(self) -> None:
        assert luminance("#ffffff") > luminance("#f9fafb") > luminance("#111827")

    def test_contrast_matches_intuition(self) -> None:
        assert contrast("#111827", "#ffffff") > 10
        assert contrast("#d1d5db", "#ffffff") < 2


class TestDerivedFromMeasurementAlone:
    """The hand-coded case: no CSS variables, everything clustered from computed styles."""

    def test_it_recovers_the_brand_accent(self, nodes: list[dict[str, Any]]) -> None:
        """The one that is VISIBLE if wrong. Two earlier rules failed here: ranking
        links by count returned #ffffff (white link text on a dark band), and a low
        saturation floor returned a slate while the real brass sat further down."""
        assert extract(nodes, css_vars=_framework_vars()).palette["accent"] == TRUTH["brass"]

    def test_it_recovers_the_page_background_and_surface(self, nodes: list[dict[str, Any]]) -> None:
        ds = extract(nodes)
        assert ds.palette["background"] == TRUTH["white"]
        assert ds.palette["surface"] == TRUTH["shell"]

    def test_surface_and_border_are_not_swapped(self, nodes: list[dict[str, Any]]) -> None:
        """Frequency ranking had these backwards: the hairline appears more often than
        the surface. A surface is the tone NEAREST the background."""
        ds = extract(nodes)
        bg, surface, border = (ds.palette["background"], ds.palette["surface"],
                               ds.palette["border"])
        assert abs(luminance(surface) - luminance(bg)) <= abs(luminance(border) - luminance(bg))

    def test_it_recovers_the_heading_colour(self, nodes: list[dict[str, Any]]) -> None:
        assert extract(nodes).palette["heading"] == TRUTH["charcoal"]

    def test_body_text_is_readable_on_the_background(self, nodes: list[dict[str, Any]]) -> None:
        """Taking the modal colour across every text node picked the footer's
        light-on-dark grey - a correct measurement of the wrong thing."""
        ds = extract(nodes)
        assert contrast(ds.palette["text"], ds.palette["background"]) >= 3.0

    def test_it_recovers_the_scales(self, nodes: list[dict[str, Any]]) -> None:
        ds = extract(nodes)
        assert len(ds.type_scale) >= 4
        assert set(ds.radius_scale) >= {4, 8, 12}
        assert all(r < 100 for r in ds.radius_scale), "9999px is a pill, not a scale step"

    def test_icon_fonts_are_not_typography(self, nodes: list[dict[str, Any]]) -> None:
        """Elementor ships `eicons` and it is the third most common family on this page.
        Capturing it would set every paragraph in an icon font."""
        ds = extract(nodes)
        assert "eicon" not in ds.fonts.get("body", "").lower()
        assert ds.fonts.get("body")

    def test_it_reports_itself_as_grounded(self, nodes: list[dict[str, Any]]) -> None:
        assert extract(nodes).is_grounded is True

    def test_it_recovers_the_body_and_muted_greys(self, nodes: list[dict[str, Any]]) -> None:
        """These two only came out right once the contrast maths applied the sRGB gamma.
        Raw channel values scored #4B5563 at 2.8:1 against white (actually 7.6:1), so a
        >= 3.0 readability filter was discarding the page's real body colour."""
        ds = extract(nodes)
        assert ds.palette["text"] == TRUTH["body"]
        assert ds.palette["muted"] == TRUTH["muted"]

    def test_it_recovers_the_whole_palette_from_measurement_alone(
        self, nodes: list[dict[str, Any]]
    ) -> None:
        """The headline claim: a hand-coded site with no CSS variables still yields the
        author's real design tokens. Measured 6/6 on the reference page."""
        got = set(extract(nodes, css_vars=_framework_vars()).palette.values())
        missing = [name for name, hexv in TRUTH.items() if hexv not in got]
        assert not missing, f"did not recover: {missing}"


class TestDeclaredTokensWin:
    """A name the author wrote is worth more than any clustering of ours."""

    def _declared(self) -> dict[str, str]:
        return {"--oh-brass": "#A16207", "--oh-charcoal": "#111827",
                "--oh-shell": "#F9FAFB", "--oh-body": "#4B5563",
                "--oh-muted": "#6B7280", "--oh-hair": "#E5E7EB", "--oh-white": "#FFFFFF"}

    def test_declared_values_are_used_and_marked(self, nodes: list[dict[str, Any]]) -> None:
        ds = extract(nodes, css_vars=self._declared())
        assert ds.palette["text"] == "#4b5563", "the declared body colour, not the clustered one"
        assert ds.provenance["palette.text"] == "declared"
        assert ds.declared_count >= 6

    def test_the_framework_s_own_variables_are_ignored(self, nodes: list[dict[str, Any]]) -> None:
        """`--e-global-*` and `--ast-*` describe Elementor's and the theme's defaults,
        not this site's design decisions."""
        ds = extract(nodes, css_vars={"--e-global-color-primary": "#ff0000",
                                      "--ast-global-color-0": "#00ff00"})
        assert ds.palette.get("accent") != "#ff0000"
        assert not ds.declared_tokens

    def test_every_resolved_role_records_its_provenance(self, nodes: list[dict[str, Any]]) -> None:
        """A design system nobody can account for six months later is a liability."""
        ds = extract(nodes, css_vars=self._declared())
        for role in ds.palette:
            assert ds.provenance.get(f"palette.{role}") in ("declared", "derived")


def test_an_empty_capture_degrades_rather_than_raising() -> None:
    ds = extract([])
    assert ds.is_grounded is False
    assert any("no palette" in n for n in ds.notes)
