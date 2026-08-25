"""Replication stage 3: rendered boxes -> Elementor structure.

This is where the first attempt died - 31 single-column sections for a page whose
real layout is multi-column throughout. Every bar in this file is MEASURED, and the
centrepiece is a self-grading test: the fixture page is itself Elementor-built, so its
own `elementor-col-N` classes ride along in the capture as ground truth. The inference
never reads them; the grader does.
"""

from __future__ import annotations

import json
import pathlib
import re
from collections import defaultdict
from typing import Any

import pytest

from app.services.layout_infer import (
    WIDGET_TYPES,
    InferredRow,
    classify,
    infer_layout,
    snap_widths,
)

pytestmark = pytest.mark.unit

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "replica" / "spotino_desktop.json"


@pytest.fixture(scope="module")
def raw() -> dict[str, Any]:
    return json.loads(_FIXTURE.read_text())


@pytest.fixture(scope="module")
def page(raw: dict[str, Any]) -> Any:
    return infer_layout(raw, viewport_width=1440)


def _all_rows(page: Any) -> list[InferredRow]:
    out: list[InferredRow] = []

    def add(row: InferredRow) -> None:
        out.append(row)
        for col in row.columns:
            for sub in col.rows:
                add(sub)

    for section in page.sections:
        for row in section.rows:
            add(row)
    return out


class TestTheShapeOfThePage:
    def test_it_sees_the_sections(self, page: Any) -> None:
        """The old path flattened everything; 12 of the 13 rendered bands survive
        (the 13th is a 23px marquee strip below the minimum section height)."""
        assert len(page.sections) >= 12

    def test_most_of_the_page_is_multi_column_and_it_knows(self, page: Any) -> None:
        assert page.multi_column_sections >= 8

    def test_the_container_is_measured_not_assumed(self, page: Any) -> None:
        """1236px, the mode of the section content boxes. An early draft summed row
        columns instead and got 684."""
        assert page.container_px == 1236

    def test_the_real_grids_are_found(self, page: Any) -> None:
        mixes = [tuple(c.width_pct for c in r.columns) for r in _all_rows(page)]
        assert mixes.count((25, 25, 25, 25)) >= 3, "product grid, gallery, testimonial strip"
        assert mixes.count((50, 50)) >= 3
        assert (67, 33) in mixes


class TestEveryRowSumsToExactlyOneHundred:
    """THE invariant. The old emitter's `100 // cols` shipped 33+33+33 = 99% - legal,
    rendered, and slightly wrong forever."""

    def test_on_the_real_page(self, page: Any) -> None:
        for row in _all_rows(page):
            widths = [c.width_pct for c in row.columns]
            assert sum(widths) == 100, f"row y={row.y}: {widths}"

    @pytest.mark.parametrize(("raw_pcts", "expected"), [
        ([33.3, 33.3, 33.3], [34, 33, 33]),  # remainder lands on the FIRST widest
        ([50.0, 50.0], [50, 50]),
        ([64.0, 36.0], [66, 34]),  # the point goes where the error is largest
        ([25.0, 25.0, 25.0, 25.0], [25, 25, 25, 25]),
        ([100.0], [100]),
    ])
    def test_snap_and_normalise(self, raw_pcts: list[float], expected: list[int]) -> None:
        assert snap_widths(raw_pcts) == expected

    def test_the_remainder_lands_on_the_widest(self) -> None:
        """A one-point surplus is invisible on the widest box, visible on the
        narrowest."""
        out = snap_widths([60.0, 20.0, 20.0])
        assert sum(out) == 100 and max(out) == 60


class TestTheAdversarialReviewsExecutedFailures:
    """Each case below was DEMONSTRATED against the previous code by an independent
    refuter running the real module - not argued. They stay as regressions."""

    @pytest.mark.parametrize("n", [6, 7, 8])
    def test_wide_equal_grids_never_go_negative(self, n: int) -> None:
        """The ladder's floor is 16 and 100/n for n>=6 snaps to it, so the whole
        correction landed on one column: measured [-12, 16 x7] for eight columns. A
        NEGATIVE width, published."""
        out = snap_widths([100.0 / n] * n)
        assert sum(out) == 100
        assert all(w >= 5 for w in out), out
        assert max(out) - min(out) <= 1, f"an equal grid must stay equal: {out}"

    def test_a_genuine_quarter_quarter_half_row_is_not_rewritten_to_thirds(self) -> None:
        """Equal start deltas alone are not an equal grid: 25/25/50 has equal deltas
        because the wide column is LAST and starts never see its width. Measured
        rewrite: 34/33/33, sums to 100, looks plausible, silently wrong."""
        kids = [
            {"t": "div", "box": [0, 0, 300, 200], "txt": "a", "s": {}, "kids": []},
            {"t": "div", "box": [310, 0, 300, 200], "txt": "b", "s": {}, "kids": []},
            {"t": "div", "box": [620, 0, 620, 200], "txt": "c", "s": {}, "kids": []},
        ]
        tree = {"t": "div", "box": [0, 0, 1240, 220], "s": {}, "kids": [
            {"t": "section", "box": [0, 0, 1240, 220], "s": {}, "kids": kids}]}
        page = infer_layout(tree, viewport_width=1240)
        widths = next(tuple(c.width_pct for c in r.columns)
                      for r in _all_rows(page) if len(r.columns) == 3)
        assert widths[2] >= 45, f"the half-width panel must stay wide: {widths}"

    def test_a_ribbon_over_text_is_an_overlay_not_a_column(self) -> None:
        """An absolutely-positioned badge overlapping in-flow content was shrunk into
        a fake 16% in-flow column with no note."""
        kids = [
            {"t": "div", "box": [0, 0, 1200, 400], "s": {}, "kids": [
                {"t": "h1", "box": [40, 60, 500, 80], "txt": "Headline", "s": {}, "kids": []},
                {"t": "p", "box": [40, 160, 900, 60], "txt": "Copy", "s": {}, "kids": []},
            ]},
            {"t": "div", "box": [700, 40, 180, 90], "txt": "",
             "s": {"backgroundColor": "rgb(161, 98, 7)", "position": "absolute"},
             "kids": []},
        ]
        tree = {"t": "div", "box": [0, 0, 1200, 420], "s": {}, "kids": [
            {"t": "section", "box": [0, 0, 1200, 420], "s": {}, "kids": kids}]}
        page = infer_layout(tree, viewport_width=1200)
        for row in _all_rows(page):
            assert len(row.columns) <= 1, "the ribbon must not become a column"
        notes = " ".join(n for r in _all_rows(page) for n in r.notes)
        assert "overlays are not columns" in notes

    def test_an_anchored_element_in_clear_space_stays_in_the_layout(self) -> None:
        """The counter-case, measured on the reference hero: the author ANCHORS a real
        strip absolutely, in space no in-flow content occupies - Elementor's own truth
        declares it columns. Excluding every `position:absolute` node lost it."""
        kids = [
            {"t": "div", "box": [0, 0, 500, 300], "s": {}, "kids": [
                {"t": "p", "box": [10, 10, 480, 60], "txt": "left copy", "s": {}, "kids": []}]},
            {"t": "div", "box": [700, 0, 400, 300], "txt": "anchored panel",
             "s": {"position": "absolute"}, "kids": []},
        ]
        tree = {"t": "div", "box": [0, 0, 1200, 320], "s": {}, "kids": [
            {"t": "section", "box": [0, 0, 1200, 320], "s": {}, "kids": kids}]}
        page = infer_layout(tree, viewport_width=1200)
        assert any(len(r.columns) == 2 for r in _all_rows(page)), (
            "clear-space anchored content must remain part of the layout")

    def test_a_tall_item_does_not_chain_unrelated_bands_into_one_row(self) -> None:
        """Membership was tested only against row[0], so one tall item glued bands
        sharing zero overlap with each other; the glued cluster then x-overlapped and
        a genuine multi-column section flattened to one column."""
        kids = [
            {"t": "img", "box": [0, 0, 480, 800], "src": "https://x.test/a.jpg",
             "alt": "", "s": {}, "kids": []},
            {"t": "div", "box": [520, 0, 600, 300], "txt": "top band", "s": {}, "kids": []},
            {"t": "div", "box": [520, 500, 600, 300], "txt": "bottom band", "s": {}, "kids": []},
        ]
        tree = {"t": "div", "box": [0, 0, 1200, 820], "s": {}, "kids": [
            {"t": "section", "box": [0, 0, 1200, 820], "s": {}, "kids": kids}]}
        page = infer_layout(tree, viewport_width=1200)
        texts = [" ".join(w.node.get("txt") or "" for c in r.columns for w in c.widgets)
                 for r in _all_rows(page)]
        joined = [t for t in texts if "top band" in t and "bottom band" in t]
        assert not joined, "the two bands share no vertical overlap and must not merge"


class TestSelfGradeAgainstTheSourcesOwnDeclarations:
    """The fixture page declares its columns via `elementor-col-N`. Inference never
    reads those classes; this grader matches them to inferred columns by geometry."""

    def test_at_least_seventy_percent_of_truth_columns_match(
        self, raw: dict[str, Any], page: Any
    ) -> None:
        truth: list[tuple[int, int, int]] = []

        def walk(n: dict[str, Any]) -> None:
            for c in n.get("cls") or []:
                m = re.match(r"elementor-col-(\d+)$", c)
                if m:
                    b = n["box"]
                    truth.append((b[0], b[1], int(m.group(1))))
            for k in n.get("kids") or []:
                walk(k)

        walk(raw)
        by_y: dict[int, list[tuple[int, int]]] = defaultdict(list)
        for x, y, n in truth:
            by_y[y].append((x, n))

        inferred: list[tuple[int, int, int, int]] = []

        def add(row: InferredRow) -> None:
            for c in row.columns:
                inferred.append((c.x, row.y, c.width_pct, len(row.columns)))
                for sub in c.rows:
                    add(sub)

        for s_ in page.sections:
            for r in s_.rows:
                add(r)

        graded = correct = 0
        for y, cols in by_y.items():
            if len(cols) < 2:
                continue
            for x, want in cols:
                graded += 1
                got = next(
                    (pct for cx, cy, pct, ncols in inferred
                     if ncols >= 2 and abs(cy - y) <= 80 and abs(cx - x) <= 20),
                    None,
                )
                if got is not None and abs(got - want) <= 2:
                    correct += 1
        assert graded >= 30, f"the ground truth thinned out ({graded} columns)"
        rate = correct / graded
        assert rate >= 0.70, f"self-grade fell to {rate:.0%} ({correct}/{graded})"


class TestNesting:
    """Elementor's one legal nesting level: section > column > inner section > column.
    The reference hero keeps a 33/33/33 trio inside its right column; flattening that
    is precisely the demolition the first attempt shipped."""

    def test_the_heros_right_column_nests_a_trio(self, page: Any) -> None:
        hero = next(s for s in page.sections if s.y == 101)
        nested = [
            tuple(c2.width_pct for c2 in sub.columns)
            for r in hero.rows for c in r.columns for sub in c.rows
        ]
        assert any(sorted(w) == [33, 33, 34] for w in nested), nested

    def test_a_row_whose_columns_hold_only_nested_rows_survives(self, page: Any) -> None:
        """The pre-nesting guard dropped any row with no direct widgets - the hero's
        whole lower band vanished while every cluster in it measured correctly."""
        assert any(
            any(c.rows and not c.widgets for c in r.columns) for r in _all_rows(page)
        )


class TestComponents:
    def test_the_authors_own_component_names_are_read_not_invented(self, page: Any) -> None:
        names = {c.name for c in page.components}
        assert {"product-card", "review-card", "footer-col"} <= names

    def test_names_come_from_the_shared_bem_prefix(self, page: Any) -> None:
        """The rendered DOM carries `product-card__title` 43 times and the bare parent
        class ZERO times - Elementor 4.7 renders `_css_classes` on widgets, not
        columns. The parent exists only as the prefix its children share."""
        product = next(c for c in page.components if c.name == "product-card")
        assert product.count >= 3

    def test_every_component_recurs(self, page: Any) -> None:
        assert all(c.count >= 3 for c in page.components)


class TestClassification:
    def test_the_vocabulary_is_closed(self) -> None:
        """An unknown widget type must die in Python, not on a client's site."""
        from app.services.layout_infer import InferredWidget

        with pytest.raises(ValueError):
            InferredWidget(type="marquee", node={})

    def test_a_background_image_tile_is_an_image(self) -> None:
        """A 2x2 photo collage renders as empty divs carrying background-image.
        Classifying them None dropped the whole grid."""
        node = {"t": "div", "box": [0, 0, 271, 204], "txt": "",
                "s": {"backgroundImage": 'url("x.jpg")'}, "kids": []}
        assert classify(node) == "image"

    def test_a_painted_empty_box_is_a_spacer(self) -> None:
        node = {"t": "div", "box": [0, 0, 100, 80], "txt": "",
                "s": {"backgroundColor": "rgb(240, 240, 240)"}, "kids": []}
        assert classify(node) == "spacer"

    def test_a_small_painted_sliver_is_nothing(self) -> None:
        node = {"t": "div", "box": [0, 0, 30, 4], "txt": "",
                "s": {"backgroundColor": "rgb(0, 0, 0)"}, "kids": []}
        assert classify(node) is None

    def test_a_plain_link_is_not_a_button(self) -> None:
        node = {"t": "a", "box": [0, 0, 80, 18], "txt": "read more",
                "href": "/x", "s": {}, "kids": []}
        assert classify(node) is None

    def test_a_padded_painted_link_is_a_button(self) -> None:
        node = {"t": "a", "box": [0, 0, 160, 44], "txt": "Book now", "href": "/book",
                "s": {"backgroundColor": "rgb(161, 98, 7)", "paddingLeft": "24px"},
                "kids": []}
        assert classify(node) == "button"

    def test_the_spacer_is_in_the_closed_vocabulary(self) -> None:
        assert "spacer" in WIDGET_TYPES


class TestRefusals:
    def test_overlapping_items_do_not_become_columns(self) -> None:
        """An overlay guessed as columns becomes a broken page on a client's site; a
        conservative refusal merely loses a flourish."""
        tree = {"t": "div", "box": [0, 0, 1200, 400], "s": {}, "kids": [
            {"t": "div", "box": [0, 0, 1200, 400], "s": {}, "kids": [
                {"t": "p", "box": [100, 100, 800, 200], "txt": "under", "s": {}, "kids": []},
                {"t": "p", "box": [300, 120, 800, 200], "txt": "over", "s": {}, "kids": []},
            ]},
        ]}
        page = infer_layout(tree, viewport_width=1200)
        for row in _all_rows(page):
            assert len(row.columns) == 1

    def test_an_empty_capture_degrades(self) -> None:
        page = infer_layout({"t": "div", "box": [0, 0, 0, 0], "s": {}, "kids": []},
                            viewport_width=1440)
        assert page.sections == ()
        assert any("empty" in n for n in page.notes)

    def test_evenly_started_items_are_an_equal_grid(self) -> None:
        """Content-sized items in equal tracks start on a regular grid even when
        their own widths differ - gap arithmetic alone read the hero trio as
        42/33/25 when the author wrote thirds."""
        kids = [
            {"t": "div", "box": [x, 0, 100, 80], "txt": f"item {i}", "s": {}, "kids": []}
            for i, x in enumerate((0, 140, 280))
        ]
        # The band itself must be viewport-wide or it is skipped as a fragment -
        # which an earlier draft of this very test tripped over.
        tree = {"t": "div", "box": [0, 0, 1200, 100], "s": {}, "kids": [
            {"t": "section", "box": [0, 0, 1200, 100], "s": {}, "kids": [
                {"t": "div", "box": [0, 0, 420, 100], "s": {}, "kids": kids}]}]}
        page = infer_layout(tree, viewport_width=1200)
        widths = [tuple(c.width_pct for c in r.columns) for r in _all_rows(page)
                  if len(r.columns) == 3]
        assert (33, 33, 34) in [tuple(sorted(w)) for w in widths] or (34, 33, 33) in widths


class TestTheAlligatorLessons:
    """Iteration 4-5 against a second live site (a pool company drawn entirely as
    rounded-outline cards). Each test reproduces a defect that shipped: the fix is
    the assertion."""

    @staticmethod
    def _n(t: str, box: list[int], s: dict[str, str] | None = None,
           kids: list[dict[str, Any]] | None = None, txt: str = "",
           **extra: Any) -> dict[str, Any]:
        return {"t": t, "box": box, "s": s or {}, "cls": [], "txt": txt,
                "kids": kids or [], **extra}

    def _card_page(self, *, interior_nests: bool = False) -> dict[str, Any]:
        """A band whose sole content chain lands on a PAINTED wrapper (the card)."""
        n = self._n
        card_style = {"borderRadius": "25px", "borderTopStyle": "double",
                      "borderTopWidth": "5px", "borderTopColor": "rgb(62, 71, 81)",
                      "backgroundColor": "rgba(0, 0, 0, 0)"}
        eyebrow = n("div", [160, 1030, 1120, 53],
                    kids=[n("h2", [160, 1030, 1120, 19], txt="Trust Us")])
        heading = n("h3", [160, 1084, 1120, 64], txt="Five-Star Reputation")
        divider = n("div", [160, 1148, 1120, 43], kids=[
            n("div", [160, 1148, 1120, 9], kids=[
                n("span", [160, 1152, 1120, 1],
                  s={"borderTopWidth": "1px", "borderTopStyle": "solid",
                     "borderTopColor": "rgb(12, 13, 14)"})])])
        button = n("div", [160, 2020, 1120, 123], kids=[
            n("a", [540, 2070, 357, 58],
              s={"backgroundColor": "rgb(242, 183, 47)", "paddingLeft": "48px"},
              kids=[n("span", [640, 2090, 157, 16], txt="All Pool Services")],
              href="/services")])
        interior: list[dict[str, Any]] = [eyebrow, heading, divider, button]
        if interior_nests:
            # LEFT column itself holds a 2-col row -> the interior already nests
            left = n("div", [200, 1300, 500, 400], kids=[
                n("div", [200, 1300, 240, 120],
                  kids=[n("p", [210, 1310, 220, 100], txt="stat one")]),
                n("div", [460, 1300, 240, 120],
                  kids=[n("p", [470, 1310, 220, 100], txt="stat two")]),
            ])
            right = n("div", [760, 1300, 500, 400],
                      kids=[n("p", [770, 1310, 480, 120], txt="right text")])
            interior = [eyebrow, left, right, button]
        card = n("div", [120, 978, 1200, 1230], s=card_style, kids=interior)
        section = n("section", [0, 868, 1440, 1450],
                    kids=[n("div", [120, 868, 1200, 1450], kids=[card])])
        return self._n("div", [0, 0, 1440, 2400], kids=[section])

    def test_a_painted_wrapper_becomes_a_card_column_with_its_outline(self) -> None:
        page = infer_layout(self._card_page(), viewport_width=1440)
        assert len(page.sections) == 1
        row = page.sections[0].rows[0]
        assert len(row.columns) == 1
        card = row.columns[0]
        assert card.radius_px == 25
        assert card.border_px == 5
        assert card.border_style == "double"

    def test_the_bands_padding_measures_to_the_card_box_not_its_widgets(self) -> None:
        page = infer_layout(self._card_page(), viewport_width=1440)
        s = page.sections[0]
        # band y=868, card y=978 -> 110; NOT the 162 to the first widget
        assert s.pad_top == 110

    def test_an_eyebrow_wrapped_leaf_and_a_lone_button_row_both_survive(self) -> None:
        page = infer_layout(self._card_page(), viewport_width=1440)

        def widget_types(p: Any) -> list[str]:
            out = []
            for sec in p.sections:
                for r in _all_rows_local(sec):
                    for c in r.columns:
                        out += [w.type for w in c.widgets]
            return out

        def _all_rows_local(sec: Any) -> list[Any]:
            rows = []

            def add(r: Any) -> None:
                rows.append(r)
                for c in r.columns:
                    for sub in c.rows:
                        add(sub)

            for r in sec.rows:
                add(r)
            return rows

        kinds = widget_types(page)
        assert "button" in kinds, "the lone-button row used to vanish"
        headings = kinds.count("heading")
        assert headings >= 2, "the wrapped eyebrow h2 used to vanish"
        assert "divider" in kinds, "the hairline divider used to vanish"

    def test_a_nesting_interior_refuses_the_wrap_for_elementor_legality(self) -> None:
        page = infer_layout(self._card_page(interior_nests=True), viewport_width=1440)
        notes = [n for r in page.sections[0].rows for n in r.notes]
        assert not any("card column" in n for n in notes), (
            "an interior that already nests must not gain a second nesting level"
        )

    def test_an_off_page_carousel_slide_is_dropped_a_visible_item_is_not(self) -> None:
        n = self._n
        slide1 = n("div", [217, 100, 1006, 100],
                   s={"backgroundImage": "url(https://x/a.png)"})
        slide2 = n("div", [1223, 100, 1006, 100],
                   s={"backgroundImage": "url(https://x/b.png)"})
        wrapper = n("div", [217, 100, 1006, 100], kids=[slide1, slide2])
        section = n("section", [0, 0, 1440, 300], kids=[
            n("div", [120, 0, 1200, 300], kids=[
                n("div", [120, 0, 1200, 300], kids=[
                    n("h2", [160, 10, 1120, 40], txt="Reviews"), wrapper])])])
        root = n("div", [0, 0, 1440, 400], kids=[section])
        page = infer_layout(root, viewport_width=1440)
        imgs = [w for s in page.sections for r in s.rows for c in r.columns
                for cc in c.all_columns() for w in cc.widgets if w.type == "image"]
        assert len(imgs) == 1, "the overflow slide (x=1223, 21% on-page) must drop"
        notes = " ".join(nn for s in page.sections for r in s.rows for nn in r.notes)
        assert "carousel overflow" in notes

    def test_a_wide_hairline_classifies_as_a_divider_not_a_spacer(self) -> None:
        hairline = {"t": "span", "box": [0, 0, 1118, 1], "cls": [], "txt": "",
                    "s": {"borderTopWidth": "1px", "borderTopStyle": "solid"},
                    "kids": []}
        assert classify(hairline) == "divider"

    def test_a_painted_question_pill_decorates_its_row_column(self) -> None:
        n = self._n
        pill_style = {"borderTopWidth": "1px", "borderTopStyle": "solid",
                      "borderTopColor": "rgb(3, 76, 82)", "borderRadius": "12px",
                      "backgroundColor": "rgb(255, 255, 255)"}
        pills = [n("div", [160, 100 + i * 84, 1120, 68], s=pill_style,
                   kids=[n("p", [212, 116 + i * 84, 1050, 36],
                           txt=f"Question number {i}?")])
                 for i in range(3)]
        section = n("section", [0, 0, 1440, 400], kids=[
            n("div", [120, 0, 1200, 400], kids=pills)])
        root = n("div", [0, 0, 1440, 500], kids=[section])
        page = infer_layout(root, viewport_width=1440)
        cols = [c for s in page.sections for r in s.rows for c in r.columns]
        decorated = [c for c in cols if c.border_px == 1 and c.radius_px == 12]
        assert len(decorated) == 3, "each FAQ pill keeps its outline on the column"
