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
        responsive_band_padding,
        responsive_heading_sizes,
    )

    captures = _captures()
    return build_tree(page, extract(nodes),
                      responsive_heading_sizes(captures),
                      mobile_text_positions(captures),
                      responsive_band_padding(captures))


def _captures() -> dict[str, Any]:
    """The tablet + mobile captures of the same reference page."""
    captures: dict[str, Any] = {}
    for dev in ("tablet", "mobile"):
        f = _FIXTURE.parent / f"spotino_{dev}.json"
        if f.exists():
            captures[dev] = json.loads(f.read_text())
    return captures


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

    def test_a_pro_site_publishes_rather_than_aborting_on_an_unemittable_widget(
        self,
    ) -> None:
        """This test used to assert a Pro site gets a real `nav-menu`. That is the
        right AMBITION and it was, as written, a total outage.

        `nav-menu` is in every Elementor Pro registry and is NOT in
        `oracle_4_7.json`. `build_navbar` promoted to it on capability alone,
        `validate_tree` then refused the finished tree, and `replicate()` returned
        "refused by the oracle" having published NOTHING - not a degraded page, no
        page. The better the client's site, the more total the failure.

        A widget must satisfy BOTH authorities: the site must be able to render it
        and the oracle must be able to validate it. Until the oracle carries
        nav-menu's real control ids - which have to be read off a live Pro editor
        bootstrap, never invented, because inventing them is the exact bug the
        oracle exists to catch - the honest output is the approximation plus a note.

        The guard is data-driven, so this reverses itself: add nav-menu to the
        oracle and Pro sites get real menus again with no code change.
        """
        from app.services.design_system import DesignSystem
        from app.services.elementor_replica import build_navbar, load_oracle
        from app.services.replica_capability import TargetCapability

        pro = TargetCapability.from_ping({
            "elementor": True, "elementor_pro": True,
            "elementor_version": "4.7.0", "elementor_pro_version": "3.2.0",
            "elementor_widgets": ["heading", "icon-list", "image", "button", "nav-menu"],
        })
        section, notes = build_navbar(self._nav(), DesignSystem(), 1200, pro)
        emittable = set(load_oracle().get("widget_keys", {}))
        if "nav-menu" in emittable:
            # The oracle has since gained the widget: the ambition is met for real.
            assert '"widgetType": "nav-menu"' in json.dumps(section)
            return
        validate_tree([{  # the whole point: the tree must SURVIVE the oracle
            "id": "s1", "elType": "section", "settings": {},
            "elements": [section] if section.get("elType") == "column" else section.get(
                "elements", [])
        }] if section.get("elType") != "section" else [section])
        assert any("nav-menu" in n for n in notes), (
            "a Pro site that cannot get its real menu must be TOLD, not silently "
            f"downgraded: {notes}"
        )

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
        assert addons.can("tabs"), "the registry, not a Pro boolean, is the answer"

        # ...but rendering is only half of it. This assertion used to be
        # `widget == "tabs" and note is None`, which asserted a promotion to a
        # widget type `oracle_4_7.json` does not carry and this codebase has no
        # emitter for (there is no `_w_tabs`) - so it would have been refused at
        # validation, taking the whole publish with it. Six of the seven UPGRADES
        # entries name such a widget.
        from app.services.elementor_replica import load_oracle

        widget, note = addons.resolve("tabs")
        if "tabs" in load_oracle().get("widget_keys", {}):
            assert widget == "tabs" and note is None
        else:
            assert widget == "accordion" and note, (
                "a construct AIOS cannot emit must degrade with a note, not be "
                "promoted into a tree the oracle will refuse"
            )

    def test_a_missing_widget_degrades_to_something_renderable(self) -> None:
        from app.services.replica_capability import FREE_WIDGETS, UPGRADES, TargetCapability

        bare = TargetCapability.free_tier()
        for construct in UPGRADES:
            widget, note = bare.resolve(construct)
            assert widget in FREE_WIDGETS, f"{construct} degraded to unrenderable {widget}"
            assert note, f"{construct} degraded silently"


class TestTheRebuildIsResponsive:
    """Three viewports are captured; before these tests, two of them contributed
    only heading font sizes and every section shipped its DESKTOP spacing to phones.

    Measured on this exact fixture: all 153 text anchors present at every viewport
    had a mobile band padding different from desktop (88px desktop vs 10-25px
    mobile), so inheriting desktop was wrong on every section, not a rare edge.
    """

    def test_the_band_padding_map_is_not_empty(self) -> None:
        """THE NON-VACUITY GUARD, and it is not hypothetical: the first version of
        `responsive_band_padding` took the page width as `max(width of any node)`.
        The tablet capture contains a 2,468px carousel track inside an 834px
        viewport, so the band threshold became 2,221px, nothing matched, the
        function returned an empty map and the entire responsive pass was a silent
        no-op that emitted a perfectly valid tree. Only a test that asserts real
        CONTENT catches that; asserting "it returns a dict" would have passed.
        """
        from app.services.elementor_replica import responsive_band_padding

        band = responsive_band_padding(_captures())
        assert set(band) == {"tablet", "mobile"}
        for device, measured in band.items():
            assert len(measured) > 50, f"{device}: only {len(measured)} anchors resolved"
            assert all(isinstance(v, tuple) and len(v) == 2 for v in measured.values())

    def test_an_overflowing_child_does_not_break_band_detection(self) -> None:
        """The regression above, reduced to its shape: a node far wider than the
        viewport must not move the page width."""
        from app.services.elementor_replica import responsive_band_padding

        root = {
            "t": "div", "box": [0, 0, 390, 2000], "s": {},
            "kids": [
                {"t": "section", "box": [0, 0, 390, 900],
                 "s": {"paddingTop": "44px", "paddingBottom": "44px"},
                 "txt": "", "kids": [
                     {"t": "h2", "box": [20, 44, 350, 40], "s": {}, "txt": "A heading"},
                     # the carousel track: 6x the viewport width
                     {"t": "div", "box": [0, 100, 2340, 300], "s": {}, "kids": []},
                 ]},
            ],
        }
        band = responsive_band_padding({"mobile": root})
        assert band["mobile"].get("A heading") == (44, 44)

    def test_every_padded_section_carries_its_measured_breakpoints(
        self, tree: list[dict[str, Any]]
    ) -> None:
        sections = [n for n in tree if n.get("elType") == "section" and not n.get("isInner")]
        padded = [s for s in sections if "padding" in (s.get("settings") or {})]
        assert padded, "the fixture's sections do measure a vertical rhythm"
        with_variants = [
            s for s in padded
            if "padding_mobile" in s["settings"] or "padding_tablet" in s["settings"]
        ]
        assert len(with_variants) == len(padded), (
            f"only {len(with_variants)} of {len(padded)} padded sections carry a "
            "breakpoint variant; the rest silently inherit desktop spacing on a phone"
        )

    def test_the_mobile_rhythm_is_actually_tighter_than_the_desktop_one(
        self, tree: list[dict[str, Any]]
    ) -> None:
        """The point of the exercise. A replica whose phone padding equals its
        desktop padding has not transferred the source's responsiveness."""
        tighter = 0
        for node in _walk(tree):
            settings = node.get("settings") or {}
            base, mobile = settings.get("padding"), settings.get("padding_mobile")
            if not base or not mobile:
                continue
            if int(mobile["top"]) < int(base["top"]):
                tighter += 1
        assert tighter >= 5, f"only {tighter} sections tightened their spacing on mobile"

    def test_a_section_matching_desktop_exactly_emits_no_variant(self) -> None:
        """Noise control: an explicit variant identical to the base is dead weight in
        every page's stored JSON."""
        from app.services.elementor_replica import _section_anchor, build_tree
        from app.services.layout_infer import infer_layout

        raw = json.loads(_FIXTURE.read_text())
        page = infer_layout(raw, viewport_width=1440)
        target = next(s for s in page.sections if s.pad_top or s.pad_bottom)
        anchor = _section_anchor(target)
        assert anchor, "the section must be identifiable by its copy"
        same = {"tablet": {anchor: (target.pad_top, target.pad_bottom)}}
        built = build_tree(page, extract([raw]), None, None, same)
        section = next(
            n for n in built
            if _section_anchor(target) and n.get("elType") == "section"
            and (n.get("settings") or {}).get("padding", {}).get("top") == str(target.pad_top)
        )
        assert "padding_tablet" not in section["settings"]

    def test_every_heading_can_be_looked_up_in_the_responsive_map(self) -> None:
        """The map's KEY must be the expression `_w_heading` looks up with.

        It was not. This walk required `n["txt"]` and keyed on it, while
        `_w_heading` titles from `node.get("txt") or _inline_text(node)`. A heading
        whose words live on nested spans - "Comfort that feels like <em>home</em>",
        the hero-headline pattern - has no own text, so it was never entered in the
        map and its lookup could never hit. 12 of this fixture's 37 headings, and
        they are exactly the big display headings whose desktop size most needs
        reducing on a phone.

        Asserts the MATCH RATE, not the number of emitted variants: whether a
        matched heading actually resizes is a property of the page, and on this
        fixture most of the newly-matched ones happen not to.
        """
        from app.services.elementor_replica import (
            _inline_text,
            _px,
            responsive_heading_sizes,
        )

        band = responsive_heading_sizes(_captures())
        desktop = json.loads(_FIXTURE.read_text())

        headings: list[str] = []

        def walk(n: dict[str, Any]) -> None:
            if n.get("t") in ("h1", "h2", "h3", "h4", "h5", "h6"):
                text = n.get("txt") or _inline_text(n)
                if text and _px((n.get("s") or {}).get("fontSize", "")):
                    headings.append(text)
            for k in n.get("kids") or []:
                walk(k)

        walk(desktop)
        assert headings, "the fixture must contain headings"
        for device in ("tablet", "mobile"):
            missed = [h for h in headings if h not in band[device]]
            assert not missed, (
                f"{len(missed)} of {len(headings)} headings cannot be looked up in "
                f"the {device} map, so they can never get a responsive size: "
                f"{missed[:3]}"
            )

    def test_repeated_card_labels_cannot_force_columns_inline_on_a_phone(self) -> None:
        """A row of cards whose buttons all read the same thing must NOT be judged
        "stays inline".

        `mobile_text_positions` kept the FIRST position per text and ignored every
        later one, so three cards each ending in "View more" all resolved to the
        same coordinates: identical y, zero spread, "they share a band" - and the
        row was pinned to 33% width on a 390px phone. On the reference capture 21 of
        160 distinct strings repeat, and they are exactly the across-a-row labels:
        "View more" 4x spread over 1,287px, "Get a quote" 3x over 10,343px.

        Elementor stacks columns on mobile by default. Forcing them inline is only
        correct when the source PROVABLY keeps them inline, so an ambiguous anchor
        must fail closed.
        """
        from app.services.elementor_replica import mobile_text_positions

        mobile = {
            "t": "div", "box": [0, 0, 390, 3000], "s": {}, "kids": [
                # three cards stacked vertically on the phone, each ending in the
                # same call to action
                {"t": "div", "box": [20, 100, 350, 300], "s": {}, "kids": [
                    {"t": "h3", "box": [20, 110, 350, 30], "s": {}, "txt": "Card one"},
                    {"t": "a", "box": [20, 360, 120, 40], "s": {}, "txt": "View more"}]},
                {"t": "div", "box": [20, 500, 350, 300], "s": {}, "kids": [
                    {"t": "h3", "box": [20, 510, 350, 30], "s": {}, "txt": "Card two"},
                    {"t": "a", "box": [20, 760, 120, 40], "s": {}, "txt": "View more"}]},
                {"t": "div", "box": [20, 900, 350, 300], "s": {}, "kids": [
                    {"t": "h3", "box": [20, 910, 350, 30], "s": {}, "txt": "Card three"},
                    {"t": "a", "box": [20, 1160, 120, 40], "s": {}, "txt": "View more"}]},
            ],
        }
        pos = mobile_text_positions({"mobile": mobile})

        assert "View more" not in pos, (
            "a text occurring three times at three different y positions cannot "
            "identify one position; keeping the first is how three stacked cards "
            "were judged to sit side by side"
        )
        # The unambiguous headings still resolve, and to their real positions.
        assert pos["Card one"] == (20, 110)
        assert pos["Card two"] == (20, 510)
        assert pos["Card three"] == (20, 910)

    def test_unambiguous_inline_rows_are_still_detected(self) -> None:
        """The conservative fix must not destroy the feature it guards: a genuine
        side-by-side row with distinct labels still reports its positions."""
        from app.services.elementor_replica import mobile_text_positions

        mobile = {
            "t": "div", "box": [0, 0, 390, 400], "s": {}, "kids": [
                {"t": "div", "box": [10, 100, 120, 60], "s": {}, "txt": "2,400+"},
                {"t": "div", "box": [140, 100, 120, 60], "s": {}, "txt": "10 yr"},
                {"t": "div", "box": [270, 100, 110, 60], "s": {}, "txt": "4.9/5"},
            ],
        }
        pos = mobile_text_positions({"mobile": mobile})
        ys = [pos[t][1] for t in ("2,400+", "10 yr", "4.9/5")]
        assert max(ys) - min(ys) <= 30, "a real inline trio must still read as one band"
