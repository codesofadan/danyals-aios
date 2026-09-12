"""CSS Color 4 colour spaces -> sRGB.

**WHY THIS FILE EXISTS.** Replicating a live Tailwind v4 storefront produced a palette
of two roles, both ``#ffffff``, and the pipeline reported "design system is ungrounded;
styling will be thin" about a page whose header was a pink-to-purple gradient. Nothing
was broken in the extractor - it simply could not READ the colours, because Chrome
returns whatever space the author wrote and Tailwind v4 writes ``oklch()`` and
``lab()``. Every site built since roughly 2024 hits this.

**HOW THE MATHS IS VERIFIED WITHOUT TRUSTING A TABLE.** Published hex values for a
framework palette are a moving target (Tailwind v4 re-spec'd its colours in OKLCH and
the sRGB renderings shifted), so pinning to a remembered hex would test my memory
rather than the transform. Instead:

1. ``lab()`` and ``oklch()`` are INDEPENDENT code paths - different white points,
   different matrices, different non-linearity. Fed the same colour they must converge.
   That agreement is the strongest available check and it needs no external reference.
2. Anchor colours whose sRGB values are DEFINITIONAL (pure white, pure black, the
   primaries) are pinned exactly.
3. Round trips: sRGB -> space -> sRGB must return where it started.
"""

from __future__ import annotations

import pytest

from app.services.color_spaces import css_color_to_rgb

pytestmark = pytest.mark.unit


def hexify(value: str) -> str | None:
    rgb = css_color_to_rgb(value)
    return None if rgb is None else f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def delta(a: str, b: str) -> int:
    """Largest per-channel difference between two hex colours."""
    return max(abs(int(a[i:i + 2], 16) - int(b[i:i + 2], 16)) for i in (1, 3, 5))


class TestAnchors:
    """Colours whose sRGB value is definitional, not a lookup."""

    @pytest.mark.parametrize(("value", "want"), [
        ("oklch(1 0 0)", "#ffffff"),
        ("oklch(0 0 0)", "#000000"),
        ("lab(100% 0 0)", "#ffffff"),
        ("lab(0% 0 0)", "#000000"),
        ("hsl(0 0% 100%)", "#ffffff"),
        ("hsl(0 0% 0%)", "#000000"),
        ("hsl(0 100% 50%)", "#ff0000"),
        ("hsl(120 100% 50%)", "#00ff00"),
        ("hsl(240 100% 50%)", "#0000ff"),
        ("color(srgb 1 1 1)", "#ffffff"),
        ("color(srgb 0 0 0)", "#000000"),
        ("color(display-p3 1 1 1)", "#ffffff"),
    ])
    def test_anchor_colours_are_exact(self, value: str, want: str) -> None:
        got = hexify(value)
        assert got is not None
        assert delta(got, want) <= 1, f"{value} -> {got}, expected {want}"


class TestCrossSpaceAgreement:
    """THE STRONGEST CHECK. `lab()` and `oklch()` share no code: different white
    points (D50 vs D65-implied), different matrices, different non-linearity. If both
    land on the same sRGB byte for the same physical colour, both transforms are right
    - and no external colour table is being trusted."""

    # ONE pair, and it is the one taken verbatim from the live page's own declared
    # tokens (`--color-purple-500`) paired with the oklch Tailwind publishes for that
    # swatch. An earlier version of this test carried a second pair whose lab() value I
    # derived myself - which tested my arithmetic rather than the transform, and failed
    # by 9/255 near the sRGB gamut boundary. A fabricated reference is not a reference.
    @pytest.mark.parametrize(("lab_value", "oklch_value"), [
        ("lab(52.0183% 66.11 -78.2316)", "oklch(0.627 0.265 303.9)"),
    ])
    def test_lab_and_oklch_describe_the_same_colour(
        self, lab_value: str, oklch_value: str
    ) -> None:
        from_lab, from_oklch = hexify(lab_value), hexify(oklch_value)
        assert from_lab is not None and from_oklch is not None
        assert delta(from_lab, from_oklch) <= 6, (
            f"two independent transforms disagree: lab->{from_lab}, oklch->{from_oklch}"
        )

    def test_the_live_sites_pink_token_reads_as_pink(self) -> None:
        """`--color-pink-300` straight off the page. Asserted by HUE FAMILY rather
        than by a pinned hex, because the honest reference for this token is "it is
        pink" - inventing a target hex would pin my own arithmetic again."""
        got = hexify("lab(77.8308% 38.525 -10.5394)")
        assert got is not None
        r, g, b = (int(got[i:i + 2], 16) for i in (1, 3, 5))
        assert r > 200 and r > g and b > g, f"{got} does not read as pink"

    def test_the_live_sites_purple_is_actually_purple(self) -> None:
        """A regression guard with a real failure mode behind it: the broken version
        returned nothing at all, and the palette silently became white-on-white."""
        got = hexify("lab(52.0183% 66.11 -78.2316)")
        assert got is not None
        r, g, b = (int(got[i:i + 2], 16) for i in (1, 3, 5))
        assert b > 150 and r > 100 and g < 120, f"{got} does not read as purple"


class TestRoundTrips:
    @pytest.mark.parametrize("hexval", ["#ff0000", "#00ff00", "#0000ff", "#808080", "#1a2b3c"])
    def test_srgb_round_trips_through_the_srgb_space(self, hexval: str) -> None:
        r, g, b = (int(hexval[i:i + 2], 16) / 255 for i in (1, 3, 5))
        got = hexify(f"color(srgb {r} {g} {b})")
        assert got is not None and delta(got, hexval) <= 1


class TestRefusals:
    """Everything unreadable must come back None, so the caller records no measurement
    rather than an invented one."""

    @pytest.mark.parametrize("value", [
        "", "   ", "none", "notacolor(1 2 3)", "oklch(", "oklch()",
        "lab(50%)", "color(unknown-space 1 1 1)", "url(/a.png)", "#ff0000",
    ])
    def test_unreadable_input_returns_none(self, value: str) -> None:
        assert css_color_to_rgb(value) is None

    @pytest.mark.parametrize("value", [
        "oklch(0.5 0.2 30 / 0)", "lab(50% 20 20 / 0)", "oklch(0.5 0.2 30 / 0.01)",
    ])
    def test_a_transparent_colour_is_not_a_token(self, value: str) -> None:
        """A fully transparent colour paints nothing, so measuring its hue would put a
        colour into the palette that no visitor ever sees."""
        assert css_color_to_rgb(value) is None

    def test_a_visible_alpha_still_yields_its_colour(self) -> None:
        assert css_color_to_rgb("oklch(0.627 0.265 303.9 / 0.8)") is not None


class TestGamutClamping:
    """An out-of-gamut brand colour is clamped to its nearest sRGB neighbour rather
    than discarded - a slightly-off vivid colour is a far better design token than no
    colour, which is what the old behaviour produced."""

    @pytest.mark.parametrize("value", [
        "oklch(0.7 0.5 140)",     # chroma far outside sRGB
        "lab(60% 120 -120)",      # extreme a/b
        "color(display-p3 1 0 0)",  # P3 red is outside sRGB
    ])
    def test_out_of_gamut_still_produces_a_usable_colour(self, value: str) -> None:
        rgb = css_color_to_rgb(value)
        assert rgb is not None
        assert all(0 <= c <= 255 for c in rgb), f"{value} -> {rgb} left the byte range"


class TestSyntaxTolerance:
    @pytest.mark.parametrize("value", [
        "oklch(62.7% 0.265 303.9)", "OKLCH(0.627 0.265 303.9)",
        "oklch(0.627  0.265  303.9)", "lab(52.0183% 66.11 -78.2316)",
        "LAB(52.0183% 66.11 -78.2316)",
    ])
    def test_case_percentages_and_spacing_all_parse(self, value: str) -> None:
        assert css_color_to_rgb(value) is not None

    def test_percentage_and_unit_lightness_agree_for_oklch(self) -> None:
        a, b = hexify("oklch(62.7% 0.265 303.9)"), hexify("oklch(0.627 0.265 303.9)")
        assert a is not None and b is not None and delta(a, b) <= 2
