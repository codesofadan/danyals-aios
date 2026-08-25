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
        ([64.0, 36.0], [67, 33]),
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
