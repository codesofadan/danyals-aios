"""P6.1: the brand kit - measurement beats interpretation, and both are recorded."""

from __future__ import annotations

from typing import Any

import pytest

from app.services.brand_kit import BrandKit, from_measurements, merge, normalise_colour

pytestmark = pytest.mark.unit


def _capture(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "url": "https://delaneyplumbing.test",
        "viewports": [
            {
                "viewport": "desktop", "container_width_px": 1180.0,
                "sections": [
                    {"tag": "header", "bg_color": "#ffffff", "text_color": "#1a1a1a"},
                    {"tag": "section", "bg_color": "#f5f7fa", "text_color": "#1a1a1a"},
                    {"tag": "section", "bg_color": "#f5f7fa", "text_color": "#1a1a1a"},
                ],
                "typography": [
                    {"tag": "h1", "font_family": "Georgia, serif", "font_size": "44px",
                     "color": "#0b3d91"},
                    {"tag": "p", "font_family": "Inter, sans-serif", "font_size": "17px",
                     "color": "#1a1a1a"},
                ],
                "assets": [
                    {"url": "https://x.test/logo.svg", "kind": "logo"},
                    {"url": "https://x.test/team.jpg", "kind": "image"},
                ],
            },
            {
                "viewport": "mobile", "container_width_px": 390.0,
                "typography": [
                    {"tag": "h1", "font_family": "Georgia, serif", "font_size": "28px"},
                    {"tag": "p", "font_family": "Inter, sans-serif", "font_size": "15px"},
                ],
                "sections": [], "assets": [],
            },
        ],
    }
    base.update(over)
    return base


def _profile(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "palette": {"primary": "#ff0000", "accent": "#00ff88", "background": "#eeeeee"},
        "typography": {"heading_font": "Inter, sans-serif", "base_size": "16px"},
        "layout": {
            "container_width": "1200px", "hero_style": "split", "cta_style": "banner",
            "blueprint": [{"kind": "hero", "heading": "Slab leak repair"}],
        },
        "components": {"button_style": "solid rounded"},
    }
    base.update(over)
    return base


class TestColourNormalisation:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [("#ABC", "#aabbcc"), ("#AaBbCc", "#aabbcc"), ("rgb(11, 61, 145)", "#0b3d91"),
         ("rgba(11, 61, 145, 0.5)", "#0b3d91"), ("  #0B3D91  ", "#0b3d91")],
    )
    def test_two_spellings_of_one_colour_agree(self, raw: str, expected: str) -> None:
        """Without this a palette holds #ABC and #aabbcc as different brand colours."""
        assert normalise_colour(raw) == expected

    @pytest.mark.parametrize(
        "raw", ["", "transparent", "inherit", "none", "#fff", "#ffffff", "rgba(0, 0, 0, 0)"]
    )
    def test_colours_that_carry_no_brand_signal_are_dropped(self, raw: str) -> None:
        """A palette built from these describes the absence of styling, and picking an
        'accent' out of them is a confident wrong answer."""
        assert normalise_colour(raw) == ""


class TestMeasurementWins:
    def test_the_browsers_font_beats_the_models(self) -> None:
        """A model that says Inter when the browser resolved Georgia is wrong, not a
        second opinion to average against."""
        kit = merge(capture=_capture(), profile=_profile())
        assert kit.typography["heading_font"] == "Georgia, serif"
        assert kit.provenance["typography.heading_font"] == "measured"

    def test_the_measured_container_width_beats_the_described_one(self) -> None:
        kit = merge(capture=_capture(), profile=_profile())
        assert kit.spacing["container_width"] == "1180px"
        assert kit.provenance["spacing.container_width"] == "measured"

    def test_interpretation_fills_only_what_measurement_left_empty(self) -> None:
        kit = merge(capture=_capture(), profile=_profile())
        assert kit.palette["accent"] == "#00ff88"
        assert kit.provenance["palette.accent"] == "interpreted"

    def test_the_model_cannot_overwrite_a_measured_background(self) -> None:
        kit = merge(capture=_capture(), profile=_profile())
        assert kit.palette["background"] == "#f5f7fa", "the measured dominant, not #eeeeee"
        assert kit.provenance["palette.background"] == "measured"

    def test_blueprint_and_components_come_from_interpretation(self) -> None:
        """No measurement can tell you a hero is 'split' or what the section order is
        FOR - that is the reading, and it is the half a browser cannot do."""
        kit = merge(capture=_capture(), profile=_profile())
        assert kit.blueprint and kit.blueprint[0]["kind"] == "hero"
        assert kit.components["hero_style"] == "split"
        assert kit.provenance["components.hero_style"] == "interpreted"


class TestViewportsAreNotMixed:
    def test_typography_comes_from_desktop_only(self) -> None:
        """Mobile resolves a different computed size for the same element. Mixing
        viewports produces a base size the site never actually renders at."""
        measured, _ = from_measurements(_capture())
        assert measured["typography"]["base_size"] == "17px", "not the mobile 15px"

    def test_container_width_comes_from_desktop_only(self) -> None:
        measured, _ = from_measurements(_capture())
        assert measured["spacing"]["container_width"] == "1180px"

    def test_a_capture_with_no_desktop_still_yields_something(self) -> None:
        cap = _capture()
        cap["viewports"] = [v for v in cap["viewports"] if v["viewport"] != "desktop"]
        measured, _ = from_measurements(cap)
        assert measured["typography"]["heading_font"] == "Georgia, serif"


class TestDeterminism:
    def test_the_same_capture_produces_the_same_kit(self) -> None:
        """Two runs must agree, or "the same developer built them" stops being true
        across a rebuild."""
        a = merge(capture=_capture(), profile=_profile())
        b = merge(capture=_capture(), profile=_profile())
        assert a.palette == b.palette and a.typography == b.typography

    def test_a_colour_tie_breaks_on_first_appearance(self) -> None:
        cap = _capture()
        cap["viewports"][0]["sections"] = [
            {"tag": "a", "bg_color": "#111111", "text_color": "#222222"},
            {"tag": "b", "bg_color": "#333333", "text_color": "#222222"},
        ]
        assert merge(capture=cap).palette["background"] == "#111111"


class TestHonestyAboutWhatIsKnown:
    def test_a_profile_only_kit_is_marked_not_grounded(self) -> None:
        kit = merge(profile=_profile())
        assert kit.is_grounded is False
        assert any("not a measurement" in n for n in kit.notes)
        assert set(kit.provenance.values()) == {"interpreted"}

    def test_a_measured_kit_is_grounded(self) -> None:
        assert merge(capture=_capture(), profile=_profile()).is_grounded is True

    def test_a_thin_capture_says_so_rather_than_looking_solid(self) -> None:
        thin = {"url": "https://x.test", "viewports": [
            {"viewport": "desktop", "sections": [], "typography": [], "assets": []}]}
        kit = merge(capture=thin, profile={})
        assert kit.is_grounded is False
        assert any("description rather than a measurement" in n for n in kit.notes)

    def test_every_populated_field_has_a_provenance_entry(self) -> None:
        """Provenance is what answers "why is this page's heading font Georgia" a year
        later. A field without one is a value nobody can account for."""
        kit = merge(capture=_capture(), profile=_profile())
        for section in ("palette", "typography", "spacing"):
            for name in getattr(kit, section):
                assert f"{section}.{name}" in kit.provenance


class TestAssets:
    def test_asset_urls_are_captured_logos_first(self) -> None:
        """v1 measured these and threw them away - which is why a client with their own
        photo on the page still got a generated stock image."""
        kit = merge(capture=_capture())
        assert kit.assets == ("https://x.test/logo.svg", "https://x.test/team.jpg")

    def test_the_kit_says_the_assets_are_not_re_hosted_yet(self) -> None:
        assert any("still remote" in n for n in merge(capture=_capture()).notes)

    def test_duplicate_urls_across_viewports_appear_once(self) -> None:
        cap = _capture()
        cap["viewports"][1]["assets"] = [{"url": "https://x.test/logo.svg", "kind": "logo"}]
        assert merge(capture=cap).assets.count("https://x.test/logo.svg") == 1


def test_an_empty_merge_does_not_raise() -> None:
    """The operator opens a kit before analysis finishes. That is a real state."""
    kit = merge()
    assert isinstance(kit, BrandKit) and kit.is_grounded is False


class TestTheAssetKindVocabularies:
    """`site_analyzer` says Literal["logo", "image"]; the `brand_asset_kind` enum says
    ('logo', 'photo', 'icon', 'favicon'). The two share no import, so nothing made them
    agree - and "image" is not in the enum.

    MEASURED against a real Postgres: recording a captured image raised
    `invalid input value for enum brand_asset_kind: "image"` at INSERT time, inside a
    worker, saying nothing about which of the two vocabularies was wrong.
    """

    @pytest.mark.parametrize(("analyzer", "enum"), [("logo", "logo"), ("image", "photo"),
                                                    ("LOGO", "logo"), ("  image  ", "photo")])
    def test_the_analyzers_kinds_map_onto_the_enum(self, analyzer: str, enum: str) -> None:
        from app.services.brand_kit import asset_kind_for

        assert asset_kind_for(analyzer) == enum

    def test_every_mapped_value_is_actually_in_the_enum(self) -> None:
        from app.services.brand_kit import (
            _ANALYZER_KIND_TO_ASSET_KIND,
            BRAND_ASSET_KINDS,
        )

        assert set(_ANALYZER_KIND_TO_ASSET_KIND.values()) <= BRAND_ASSET_KINDS

    @pytest.mark.parametrize("bad", ["photo", "banner", "", "svg"])
    def test_an_unmapped_kind_raises_naming_both_vocabularies(self, bad: str) -> None:
        """"photo" is in the enum but is NOT something the analyzer emits. Accepting it
        here would paper over a caller that had guessed rather than mapped."""
        from app.services.brand_kit import asset_kind_for

        with pytest.raises(ValueError, match="no brand_asset_kind"):
            asset_kind_for(bad)

    def test_the_enum_constant_matches_the_migration(self) -> None:
        """A drifting copy of an enum is worse than no copy: it validates successfully
        and then the database rejects the write."""
        import pathlib
        import re

        from app.services.brand_kit import BRAND_ASSET_KINDS

        sql = (pathlib.Path(__file__).resolve().parents[2]
               / "db" / "migrations" / "0089_client_brand_kits.sql").read_text()
        m = re.search(r"create type public\.brand_asset_kind as enum \(([^)]*)\)", sql)
        assert m, "the enum declaration moved; this guard has gone stale"
        assert set(re.findall(r"'([a-z_]+)'", m.group(1))) == BRAND_ASSET_KINDS
