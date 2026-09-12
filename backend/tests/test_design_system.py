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


# --------------------------------------------------------------------------- #
# Modern-CSS extraction: gradients, colour spaces, and token-name matching.
#
# Added after a live Tailwind v4 storefront replicated with a TWO-role palette
# (background and text, both #ffffff) and the note "design system is ungrounded;
# styling will be thin" - on a page whose header was a pink-to-purple gradient.
# Three separate defects produced that, and each has a test below.
# --------------------------------------------------------------------------- #
class TestGradientColours:
    """DEFECT 1: the extractor read only `backgroundColor`. A modern site paints with
    `background-image: linear-gradient(...)` and leaves `background-color`
    transparent, so the strongest brand signal on the page was invisible."""

    def test_stops_are_recovered_from_a_linear_gradient(self) -> None:
        from app.services.design_system import gradient_colours
        assert gradient_colours(
            "linear-gradient(to bottom right, rgb(236, 72, 153), rgb(168, 85, 247))"
        ) == ["#ec4899", "#a855f7"]

    def test_hex_and_modern_spaces_both_parse(self) -> None:
        from app.services.design_system import gradient_colours
        assert gradient_colours("linear-gradient(90deg, #ff0088, #8800ff)") == [
            "#ff0088", "#8800ff"
        ]
        assert len(gradient_colours("linear-gradient(oklch(0.7 0.2 30), lab(50% 40 -40))")) == 2

    def test_a_photograph_is_not_a_design_token(self) -> None:
        """Sampling a `url()` background would put an arbitrary pixel colour into the
        palette and call it the brand."""
        from app.services.design_system import gradient_colours
        assert gradient_colours('url("/hero.jpg")') == []
        assert gradient_colours("none") == []
        assert gradient_colours("") == []

    def test_a_gradient_layered_over_an_image_still_yields_its_stops(self) -> None:
        from app.services.design_system import gradient_colours
        assert gradient_colours("url(/a.png), linear-gradient(#ffffff, #000000)") == [
            "#ffffff", "#000000"
        ]

    def test_transparent_stops_are_dropped(self) -> None:
        from app.services.design_system import gradient_colours
        assert gradient_colours("radial-gradient(circle, #123456, rgba(0,0,0,0))") == [
            "#123456"
        ]

    def test_duplicate_stops_collapse(self) -> None:
        from app.services.design_system import gradient_colours
        assert gradient_colours("linear-gradient(#fff, #ffffff, #fff)") == ["#ffffff"]


class TestModernColourSpaces:
    """DEFECT 2: `to_hex` understood only #hex and rgb(). Tailwind v4 - most sites
    built since ~2024 - emits oklch() and lab(), so every brand colour returned "" and
    only literal whites survived into the palette."""

    def test_to_hex_reads_the_spaces_a_modern_framework_emits(self) -> None:
        from app.services.design_system import to_hex
        assert to_hex("lab(52.0183% 66.11 -78.2316)") != ""
        assert to_hex("oklch(0.627 0.265 303.9)") != ""
        assert to_hex("hsl(210 100% 50%)") == "#0080ff"
        assert to_hex("color(srgb 0 0.5 1)") == "#0080ff"

    def test_the_legacy_paths_are_unchanged(self) -> None:
        from app.services.design_system import to_hex
        assert to_hex("#abc") == "#aabbcc"
        assert to_hex("#a1b2c3") == "#a1b2c3"
        assert to_hex("rgb(1, 2, 3)") == "#010203"
        assert to_hex("rgba(1, 2, 3, 0)") == ""
        assert to_hex("") == ""

    def test_an_unreadable_colour_is_still_no_measurement(self) -> None:
        from app.services.design_system import to_hex
        assert to_hex("notacolour(1 2 3)") == ""


class TestDeclaredTokenMatching:
    """DEFECT 3: role names were matched as SUBSTRINGS of the CSS variable name, so
    "ink" matched `--color-PINK-300` and a page's heading colour resolved to its pink
    swatch while the measured #101828 was discarded."""

    def test_a_role_name_matches_whole_segments_only(self) -> None:
        from app.services.design_system import _segments
        assert "ink" not in _segments("--color-pink-300")
        assert "ink" in _segments("--color-ink")

    def test_the_segments_are_the_words_of_the_token(self) -> None:
        from app.services.design_system import _segments
        assert _segments("--color-pink-300") == frozenset({"color", "pink", "300"})

    def test_other_short_role_names_are_protected_too(self) -> None:
        """Every role name here is short enough for the same accident: "bg" inside
        "bgrey", "hair" inside "chair"."""
        from app.services.design_system import _segments
        assert "bg" not in _segments("--color-bgrey")
        assert "hair" not in _segments("--chair-rail")
        assert "bg" in _segments("--bg-page")
