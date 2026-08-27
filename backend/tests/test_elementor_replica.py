"""Stage 4: the oracle-validated emitter.

The oracle is Elementor 4.7's OWN controls registry, parsed from the editor bootstrap
of the target site. Its first two verdicts overturned beliefs the codebase had shipped
on: `title_typography_typography` (written by two emitters) and
`button_background_color` (written by the markdown emitter for weeks) are both absent
from the 4.7 registry - stored and silently ignored, pages rendering wrong with
nothing in any log.
"""

from __future__ import annotations

import json
import pathlib
from collections import Counter
from typing import Any

import pytest

from app.services.design_system import extract
from app.services.elementor_replica import (
    UnknownSettingError,
    build_tree,
    load_oracle,
    to_json,
    validate_tree,
)
from app.services.layout_infer import infer_layout

pytestmark = pytest.mark.unit

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "replica" / "spotino_desktop.json"


@pytest.fixture(scope="module")
def tree() -> list[dict[str, Any]]:
    raw = json.loads(_FIXTURE.read_text())
    nodes: list[dict[str, Any]] = []

    def walk(n: dict[str, Any]) -> None:
        nodes.append(n)
        for k in n.get("kids") or []:
            walk(k)

    walk(raw)
    page = infer_layout(raw, viewport_width=1440)
    from app.services.elementor_replica import (
        mobile_text_positions,
        responsive_heading_sizes,
    )

    captures = {}
    for dev in ("tablet", "mobile"):
        f = _FIXTURE.parent / f"spotino_{dev}.json"
        if f.exists():
            captures[dev] = json.loads(f.read_text())
    return build_tree(page, extract(nodes),
                      responsive_heading_sizes(captures),
                      mobile_text_positions(captures))


def _walk(nodes: list[dict[str, Any]]):
    for n in nodes:
        yield n
        yield from _walk(n.get("elements") or [])


class TestTheOracleIsTheLaw:
    def test_the_full_rebuild_validates(self, tree: list[dict[str, Any]]) -> None:
        validate_tree(tree)  # raises on any unknown key

    def test_a_key_from_the_old_heading_bug_is_refused(self) -> None:
        """`title_typography_typography` shipped in two emitters. The 4.7 registry
        does not contain it."""
        bad = [{"id": "a1", "elType": "section", "settings": {}, "elements": [
            {"id": "a2", "elType": "column",
             "settings": {"_column_size": 100, "_inline_size": 100}, "elements": [
                {"id": "a3", "elType": "widget", "widgetType": "heading",
                 "settings": {"title": "x", "title_typography_typography": "custom"},
                 "elements": []}]}]}]
        with pytest.raises(UnknownSettingError, match="title_typography_typography"):
            validate_tree(bad)

    def test_the_old_button_background_key_is_refused(self) -> None:
        """`button_background_color` is what the markdown emitter writes - meaning
        every button that path has pushed renders with the theme default. On 4.7 the
        valid key is plain `background_color`."""
        bad = [{"id": "b1", "elType": "section", "settings": {}, "elements": [
            {"id": "b2", "elType": "column",
             "settings": {"_column_size": 100, "_inline_size": 100}, "elements": [
                {"id": "b3", "elType": "widget", "widgetType": "button",
                 "settings": {"text": "x", "button_background_color": "#fff"},
                 "elements": []}]}]}]
        with pytest.raises(UnknownSettingError, match="button_background_color"):
            validate_tree(bad)

    def test_the_valid_button_background_key_passes(self) -> None:
        good = [{"id": "c1", "elType": "section", "settings": {}, "elements": [
            {"id": "c2", "elType": "column",
             "settings": {"_column_size": 100, "_inline_size": 100}, "elements": [
                {"id": "c3", "elType": "widget", "widgetType": "button",
                 "settings": {"text": "x", "background_color": "#a16207"},
                 "elements": []}]}]}]
        validate_tree(good)

    def test_an_unknown_widget_type_is_refused(self) -> None:
        bad = [{"id": "d1", "elType": "section", "settings": {}, "elements": [
            {"id": "d2", "elType": "column", "settings": {}, "elements": [
                {"id": "d3", "elType": "widget", "widgetType": "marquee",
                 "settings": {}, "elements": []}]}]}]
        with pytest.raises(UnknownSettingError, match="marquee"):
            validate_tree(bad)

    def test_the_oracle_records_its_provenance(self) -> None:
        oracle = load_oracle()
        assert "4.7" in oracle["source"] or oracle.get("elementor_version") == "4.7.0"


class TestTheRebuiltTree:
    def test_column_count_lands_beside_the_reference(self, tree: list[dict[str, Any]]) -> None:
        """The real page's _elementor_data holds 81 columns. The first attempt held
        31 - all width 100."""
        cols = [n for n in _walk(tree) if n["elType"] == "column"]
        assert 70 <= len(cols) <= 95, len(cols)

    def test_it_is_actually_multi_column(self, tree: list[dict[str, Any]]) -> None:
        widths = Counter(n["settings"].get("_column_size") for n in _walk(tree)
                         if n["elType"] == "column")
        assert widths.get(25, 0) >= 8
        assert widths.get(50, 0) >= 6

    def test_every_column_carries_inline_size(self, tree: list[dict[str, Any]]) -> None:
        """`_inline_size` is what the editor's drag handle reads; `_column_size`
        alone leaves the handle showing a preset default."""
        for n in _walk(tree):
            if n["elType"] == "column":
                assert n["settings"].get("_inline_size") == n["settings"].get("_column_size")

    def test_multi_column_inner_sections_declare_their_structure(
        self, tree: list[dict[str, Any]]
    ) -> None:
        for n in _walk(tree):
            if n["elType"] == "section" and n.get("isInner"):
                cols = [c for c in n.get("elements") or [] if c["elType"] == "column"]
                if len(cols) > 1:
                    assert n["settings"].get("structure") == f"{len(cols)}0"

    def test_ids_are_unique(self, tree: list[dict[str, Any]]) -> None:
        ids = [n["id"] for n in _walk(tree)]
        assert len(ids) == len(set(ids))

    def test_measured_styling_travels_as_settings(self, tree: list[dict[str, Any]]) -> None:
        """The hybrid decision: the editor's own controls must work when clicked."""
        blob = to_json(tree)
        assert '"title_color":"#111827"' in blob, "the measured charcoal heading colour"
        assert "Bricolage Grotesque" in blob, "the measured heading face"

    def test_bem_classes_ride_along_for_the_stylesheet(self, tree: list[dict[str, Any]]) -> None:
        blob = to_json(tree)
        assert "product-card" in blob
        assert "review-card" in blob

    def test_the_json_round_trips(self, tree: list[dict[str, Any]]) -> None:
        assert json.loads(to_json(tree)) == tree

    def test_columns_never_directly_contain_columns(self, tree: list[dict[str, Any]]) -> None:
        """Elementor's editor cannot parse that shape; nesting goes through an inner
        section."""
        for n in _walk(tree):
            if n["elType"] == "column":
                for child in n.get("elements") or []:
                    assert child["elType"] in ("widget", "section"), child["elType"]


class TestIterationThreeRegressions:
    """Each pinned from a screenshot-verified failure on the live rebuild."""

    def test_split_inline_text_stays_one_widget(self, tree: list[dict[str, Any]]) -> None:
        """"4.9" wrapping a small "/5" emitted the child as its own stacked widget and
        the stats card rendered "/5" alone. text-editor owns its subtree now, joined
        punctuation-aware so it reads 4.9/5, not 4.9 /5."""
        blob = to_json(tree)
        assert "4.9/5" in blob
        assert "<p>/5</p>" not in blob

    def test_stretched_sections_keep_boxed_content(self, tree: list[dict[str, Any]]) -> None:
        """stretch + layout:"full_width" ran the text edge-to-edge and off the left
        viewport. A full-bleed BAND with BOXED content is what the source is."""
        for n in _walk(tree):
            st = n.get("settings") or {}
            if st.get("stretch_section"):
                assert st.get("layout") == "boxed"

    def test_measured_radius_reaches_the_column(self, tree: list[dict[str, Any]]) -> None:
        """The hero card's 16px rounding is measured off the page, not styled on."""
        radii = [n["settings"]["border_radius"]["top"] for n in _walk(tree)
                 if n["elType"] == "column" and "border_radius" in (n.get("settings") or {})]
        assert "16" in radii

    def test_a_measured_scrim_becomes_a_real_gradient(self, tree: list[dict[str, Any]]) -> None:
        blob = to_json(tree)
        assert '"background_background":"gradient"' in blob

    def test_rows_that_stay_inline_on_mobile_keep_their_columns(
        self, tree: list[dict[str, Any]]
    ) -> None:
        """Elementor stacks columns on mobile by default - right for most rows, wrong
        for the stats trio, which measurably stays side by side at 390px. The first
        threading missed NESTED rows (the trio lives inside the hero's column) and
        only top-level testimonials got the keys."""
        keyed = [n for n in _walk(tree)
                 if "_inline_size_mobile" in (n.get("settings") or {})]
        assert len(keyed) >= 7, "trio (3) + testimonial strip (4)"
        texts = to_json(keyed)
        assert "6 yrs" in texts, "the stats trio must be among them"


def test_mobile_position_facts_are_measured(tmp_path: pathlib.Path) -> None:
    from app.services.elementor_replica import (
        _row_stays_inline_on_mobile,
        mobile_text_positions,
    )

    captures = {"mobile": {"t": "div", "box": [0, 0, 390, 800], "kids": [
        {"t": "span", "box": [10, 100, 80, 20], "txt": "A", "kids": []},
        {"t": "span", "box": [140, 102, 80, 20], "txt": "B", "kids": []},
        {"t": "span", "box": [10, 300, 80, 20], "txt": "C", "kids": []},
    ]}}
    pos = mobile_text_positions(captures)
    assert pos["A"][1] == 100 and pos["B"][1] == 102

    from app.services.layout_infer import InferredColumn, InferredRow, InferredWidget

    def col(text: str) -> InferredColumn:
        return InferredColumn(width_pct=33, x=0, width_px=100, widgets=(
            InferredWidget(type="text-editor", node={"txt": text, "box": [0, 0, 10, 10]}),))

    inline = InferredRow(columns=(col("A"), col("B")), y=0)
    stacked = InferredRow(columns=(col("A"), col("C")), y=0)
    assert _row_stays_inline_on_mobile(inline, pos) is True
    assert _row_stays_inline_on_mobile(stacked, pos) is False


class TestIterationFiveRegressions:
    """The alligator lessons, emitter side: shadows, shattered headings, contained
    badges, empty icon-lists, geometric button centring, the page's own ground."""

    def test_parse_shadow_reads_chromes_colour_first_form(self) -> None:
        from app.services.elementor_replica import _parse_shadow
        s = _parse_shadow("rgba(0, 0, 0, 0.5) 0px 0px 10px 0px")
        assert s == {"horizontal": 0, "vertical": 0, "blur": 10, "spread": 0,
                     "color": "rgba(0, 0, 0, 0.5)"}
        hard = _parse_shadow("rgb(0, 0, 0) 4px 5px 0px 0px")
        assert hard is not None
        assert (hard["horizontal"], hard["vertical"], hard["blur"]) == (4, 5, 0)
        assert _parse_shadow("none") is None
        assert _parse_shadow("") is None

    def test_a_heading_whose_words_live_on_nested_spans_joins_them(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import _w_heading
        from app.services.layout_infer import InferredWidget
        node = {"t": "h3", "box": [0, 0, 556, 144], "txt": "",
                "s": {"fontSize": "64px", "textAlign": "center"},
                "kids": [
                    {"t": "span", "box": [0, 0, 360, 72], "txt": "Pool Service Made",
                     "s": {}, "kids": []},
                    {"t": "span", "box": [0, 72, 154, 72], "txt": "Easy!",
                     "s": {}, "kids": []},
                ]}
        out = _w_heading(InferredWidget(type="heading", node=node), DesignSystem())
        assert out["title"] == "Pool Service Made Easy!"
        assert out["align"] == "center"

    def test_a_contained_badge_keeps_natural_size_and_centres(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import _w_image
        from app.services.layout_infer import InferredWidget
        node = {"t": "div", "box": [217, 1190, 1006, 100], "txt": "",
                "s": {"backgroundImage": "url(https://x/badge.png)",
                      "backgroundSize": "contain",
                      "backgroundPosition": "50% 50%"},
                "kids": []}
        out = _w_image(InferredWidget(type="image", node=node), DesignSystem())
        assert "width" not in out, "box-width blew a 250px badge up to 1006px"
        assert out.get("align") == "center"

    def test_a_real_img_keeps_its_measured_width(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import _w_image
        from app.services.layout_infer import InferredWidget
        node = {"t": "img", "box": [323, 1821, 86, 86], "txt": "",
                "src": "https://x/icon.png", "s": {}, "kids": []}
        out = _w_image(InferredWidget(type="image", node=node), DesignSystem())
        assert out["width"] == {"unit": "px", "size": 86}

    def test_a_data_uri_never_ships_as_an_image_source(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import _w_image
        from app.services.layout_infer import InferredWidget
        node = {"t": "img", "box": [0, 0, 100, 100], "txt": "",
                "src": "data:image/svg+xml;base64,xyz", "s": {}, "kids": []}
        out = _w_image(InferredWidget(type="image", node=node), DesignSystem())
        assert out["image"]["url"] == ""

    def test_icon_list_items_read_their_whole_inline_subtree(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import _w_icon_list
        from app.services.layout_infer import InferredWidget
        node = {"t": "ul", "box": [0, 0, 268, 92], "txt": "", "s": {}, "kids": [
            {"t": "li", "box": [0, 0, 268, 29], "txt": "", "s": {}, "kids": [
                {"t": "a", "box": [0, 0, 268, 24], "txt": "", "s": {}, "kids": [
                    {"t": "span", "box": [0, 0, 225, 24],
                     "txt": "Pool Cleaning - Coral Gables", "s": {}, "kids": []}]}]},
            {"t": "li", "box": [0, 34, 268, 29], "txt": "", "s": {}, "kids": [
                {"t": "a", "box": [0, 34, 268, 24], "txt": "", "s": {}, "kids": [
                    {"t": "span", "box": [0, 34, 206, 24],
                     "txt": "Pool Repair - Coral Gables", "s": {}, "kids": []}]}]},
        ]}
        out = _w_icon_list(InferredWidget(type="icon-list", node=node), DesignSystem())
        texts = [i["text"] for i in out["icon_list"]]
        assert texts == ["Pool Cleaning - Coral Gables", "Pool Repair - Coral Gables"]

    def test_a_bordered_shadowed_column_carries_both_groups(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import _column, _IdGen
        from app.services.layout_infer import InferredColumn
        col = InferredColumn(width_pct=100, x=120, width_px=1200, radius_px=25,
                             border_px=5, border_style="double",
                             border_color="rgb(62, 71, 81)",
                             shadow="rgba(0, 0, 0, 0.5) 0px 0px 10px 0px")
        el = _column(col, DesignSystem(), _IdGen(), 1200)
        s = el["settings"]
        assert s["border_border"] == "double"
        assert s["border_width"]["top"] == "5"
        assert s["box_shadow_box_shadow_type"] == "yes"
        assert s["box_shadow_box_shadow"]["blur"] == 10

    def test_a_button_on_the_columns_centre_line_centres(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import _column, _IdGen
        from app.services.layout_infer import InferredColumn, InferredWidget
        btn = InferredWidget(type="button", node={
            "t": "a", "box": [542, 2071, 357, 58], "txt": "All Pool Services",
            "s": {"backgroundColor": "rgb(242, 183, 47)"}, "kids": [],
            "href": "/services"})
        col = InferredColumn(width_pct=100, x=189, width_px=1062, widgets=(btn,))
        el = _column(col, DesignSystem(), _IdGen(), 1062)
        assert el["elements"][0]["settings"]["align"] == "center"

    def test_a_buttons_hard_shadow_is_design_and_ships(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import _w_button
        from app.services.layout_infer import InferredWidget
        node = {"t": "a", "box": [563, 3627, 313, 52], "txt": "Book a Call",
                "s": {"backgroundColor": "rgb(242, 183, 47)",
                      "boxShadow": "rgb(0, 0, 0) 4px 5px 0px 0px"},
                "kids": [], "href": "/call"}
        out = _w_button(InferredWidget(type="button", node=node), DesignSystem())
        assert out["button_box_shadow_box_shadow_type"] == "yes"
        assert out["button_box_shadow_box_shadow"]["horizontal"] == 4

    def test_the_new_keys_still_satisfy_the_oracle(self, tree: list[dict[str, Any]]) -> None:
        validate_tree(tree, load_oracle())


class TestNavbarEmission:
    def test_three_regions_three_columns_marker_class_oracle_valid(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import build_navbar
        from app.services.layout_infer import InferredNavbar, NavLink
        nav = InferredNavbar(
            height=80, background="rgb(213, 233, 232)",
            logo_src="https://x/logo.png", logo_width=150,
            links=(NavLink("Services", "/services/"), NavLink("About", "/about/")),
            cta_node={"t": "a", "box": [1280, 20, 120, 40], "txt": "Contact",
                      "s": {"backgroundColor": "rgb(242, 183, 47)"}, "kids": [],
                      "href": "/contact/"},
        )
        section, _notes = build_navbar(nav, DesignSystem(), 1200)
        assert section["settings"]["css_classes"] == "aios-replica-nav"
        assert section["settings"]["structure"] == "30"
        assert [c["settings"]["_column_size"] for c in section["elements"]] == [25, 50, 25]
        menu = section["elements"][1]["elements"][0]
        assert menu["widgetType"] == "icon-list"
        assert menu["settings"]["view"] == "inline"
        assert [i["text"] for i in menu["settings"]["icon_list"]] == ["Services", "About"]
        validate_tree([section], load_oracle())

    def test_menu_only_headers_still_build(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import build_navbar
        from app.services.layout_infer import InferredNavbar, NavLink
        nav = InferredNavbar(height=60, links=(NavLink("A", "/a"), NavLink("B", "/b")))
        section, _notes = build_navbar(nav, DesignSystem(), 1200)
        assert len(section["elements"]) == 1
        assert section["elements"][0]["settings"]["_column_size"] == 100
        validate_tree([section], load_oracle())


class TestItBuildsToWhatTheTargetCanRender:
    """A client paying for Elementor Pro must not get a downgraded rebuild of their
    own site - and a client without it must not get a tree full of widgets their
    editor stores and silently ignores."""

    @staticmethod
    def _nav():
        from app.services.layout_infer import InferredNavbar, NavLink
        return InferredNavbar(
            height=80, background="rgb(213, 233, 232)",
            logo_src="https://x/logo.png", logo_width=150,
            link_color="rgb(20, 30, 40)",
            links=(NavLink("Services", "/services/"), NavLink("About", "/about/")),
        )

    def test_a_pro_site_gets_a_real_navigation_menu(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import build_navbar
        from app.services.replica_capability import TargetCapability

        pro = TargetCapability.from_ping({
            "elementor": True, "elementor_pro": True,
            "elementor_version": "4.7.0", "elementor_pro_version": "3.2.0",
            "elementor_widgets": ["heading", "icon-list", "image", "button", "nav-menu"],
        })
        section, notes = build_navbar(self._nav(), DesignSystem(), 1200, pro)
        blob = json.dumps(section)
        assert '"widgetType": "nav-menu"' in blob
        assert "icon-list" not in blob, "the free-tier approximation must not also ship"
        assert notes == [], "using the right widget is not a degradation"

    def test_a_free_site_gets_the_link_list_and_is_told_why(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import build_navbar
        from app.services.replica_capability import TargetCapability

        free = TargetCapability.from_ping({
            "elementor": True, "elementor_pro": False,
            "elementor_version": "4.7.0",
            "elementor_widgets": ["heading", "icon-list", "image", "button"],
        })
        section, notes = build_navbar(self._nav(), DesignSystem(), 1200, free)
        blob = json.dumps(section)
        assert '"widgetType": "icon-list"' in blob
        assert "nav-menu" not in blob, (
            "an unknown widgetType is STORED and silently ignored by the editor, "
            "so the header would render as a hole with no error anywhere"
        )
        # The degradation is reported, not left for someone to notice.
        assert any("no nav-menu widget" in n for n in notes), notes

    def test_an_unmeasurable_site_is_treated_as_free_never_guessed_upward(self) -> None:
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import build_navbar
        from app.services.replica_capability import TargetCapability

        # An older plugin that cannot report its registry.
        unknown = TargetCapability.from_ping({"elementor": True, "elementor_version": "4.7.0"})
        assert unknown.measured is False
        section, notes = build_navbar(self._nav(), DesignSystem(), 1200, unknown)
        assert '"widgetType": "icon-list"' in json.dumps(section)
        assert notes, "silence about the target is itself worth reporting"

    def test_the_capability_probe_covers_third_party_packs_not_just_pro(self) -> None:
        # The registry is the answer, not a Pro boolean: a site with a widget pack
        # that provides `tabs` can keep its tab strip even without Elementor Pro.
        from app.services.replica_capability import TargetCapability

        addons = TargetCapability.from_ping({
            "elementor": True, "elementor_pro": False,
            "elementor_widgets": ["heading", "accordion", "tabs"],
        })
        widget, note = addons.resolve("tabs")
        assert widget == "tabs" and note is None

    def test_a_missing_widget_degrades_to_something_renderable(self) -> None:
        from app.services.replica_capability import FREE_WIDGETS, UPGRADES, TargetCapability

        bare = TargetCapability.free_tier()
        for construct in UPGRADES:
            widget, note = bare.resolve(construct)
            assert widget in FREE_WIDGETS, f"{construct} degraded to unrenderable {widget}"
            assert note, f"{construct} degraded silently"
