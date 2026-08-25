"""Design replication, stage 1: measuring a page well enough to rebuild it.

`site_analyzer.capture()` finds 4 sections on a page that has 42, reads 7 computed
properties, and throws away the x/y it already computed. That is enough to describe a
site and not nearly enough to rebuild one.

Every number asserted here was measured against the live reference page
(https://spotino.org/hy/) and then frozen into `fixtures/replica/spotino_desktop.json`,
so the suite runs offline with no browser.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

import pytest

from integrations.replica_capture import (
    CAPTURED_PROPS,
    MAX_DEPTH,
    MAX_NODES,
    ReplicaNode,
    _extractor_js,
    capture_replica,
)

pytestmark = pytest.mark.unit

_FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "replica" / "spotino_desktop.json"


def _node(raw: dict[str, Any]) -> ReplicaNode:
    box = raw.get("box") or [0, 0, 0, 0]
    return ReplicaNode(
        tag=raw.get("t", ""), box=(box[0], box[1], box[2], box[3]),
        style=raw.get("s") or {}, classes=tuple(raw.get("cls") or ()),
        text=raw.get("txt") or "",
        children=[_node(k) for k in (raw.get("kids") or [])],
    )


@pytest.fixture(scope="module")
def page() -> ReplicaNode:
    return _node(json.loads(_FIXTURE.read_text()))


class TestItMeasuresEnoughToRebuild:
    def test_it_sees_the_page_not_a_summary_of_it(self, page: ReplicaNode) -> None:
        """The old extractor found 4 top-level blocks on this page. Rebuilding a layout
        from 4 boxes is not possible; this is the difference the whole stage exists for."""
        assert len(page.walk()) > 300

    def test_geometry_is_in_document_coordinates(self, page: ReplicaNode) -> None:
        """A viewport-relative y is meaningless on a page taller than the window, and
        layout inference is entirely about where things sit relative to each other."""
        ys = [n.y for n in page.walk()]
        assert max(ys) > 3000, "y must span the document, not the viewport"

    def test_boxes_have_real_size(self, page: ReplicaNode) -> None:
        assert all(n.width > 0 and n.height > 0 for n in page.walk())

    def test_the_box_model_is_captured(self, page: ReplicaNode) -> None:
        """Padding is what separates a section that breathes from one that does not, and
        the old extractor read none of it."""
        styled = [n for n in page.walk() if n.style]
        assert any(n.style.get("paddingTop", "0px") != "0px" for n in styled)
        assert any(n.style.get("display") == "flex" for n in styled)

    def test_multi_column_rows_are_visible(self, page: ReplicaNode) -> None:
        """The failure of the first attempt was emitting 31 single-column sections for a
        page with 19 multi-column ones. A row is only detectable if siblings share a y
        band and each is narrower than the parent."""
        rows = 0
        for n in page.walk():
            kids = [c for c in n.children if c.width > 40]
            if len(kids) >= 2 and len({c.y // 12 for c in kids}) == 1:
                rows += 1
        assert rows >= 10, f"only {rows} multi-column rows detected"


class TestPayloadStaysSurvivable:
    def test_the_capture_fits_in_budget(self, page: ReplicaNode) -> None:
        """~1,300 layout-bearing elements x 34 properties is ~0.9MB naively."""
        assert len(_FIXTURE.read_text()) < 1_800_000

    def test_styles_are_shared_across_nodes(self, page: ReplicaNode) -> None:
        """Interning is the single biggest size lever: every card in a grid resolves to
        an identical computed style, so they should share one table entry."""
        nodes = [n for n in page.walk() if n.style]
        distinct = {tuple(sorted(n.style.items())) for n in nodes}
        assert len(distinct) < len(nodes) * 0.75

    def test_the_caps_are_sane(self) -> None:
        assert MAX_NODES >= 1000 and MAX_DEPTH >= 12


class TestTheExtractorItself:
    def test_every_captured_property_reaches_the_script(self) -> None:
        """CAPTURED_PROPS is the single source of truth; a property added there must be
        captured, indexed and named with no second edit."""
        js = _extractor_js()
        for prop in CAPTURED_PROPS:
            assert prop in js

    def test_no_placeholder_survives_into_the_script(self) -> None:
        js = _extractor_js()
        for token in ("__PROPS__", "__MAX_NODES__", "__MAX_DEPTH__", "__MAX_TEXT__"):
            assert token not in js

    def test_it_covers_what_a_design_system_declares(self) -> None:
        """Measured on the reference stylesheet, its most-used properties are color,
        width, font-size, display, background, padding, font-weight, margin,
        border-radius and gap. Missing any of them means that part cannot be rebuilt."""
        for prop in ("color", "display", "backgroundColor", "paddingTop", "marginTop",
                     "borderRadius", "gap", "fontSize", "fontWeight", "gridTemplateColumns"):
            assert prop in CAPTURED_PROPS

    def test_replaced_elements_carry_their_source(self) -> None:
        js = _extractor_js()
        assert "naturalWidth" in js, "an image without its natural size causes layout shift"
        assert "currentSrc" in js, "currentSrc resolves what srcset actually chose"

    def test_lazy_images_are_given_a_chance_to_load(self) -> None:
        """An Elementor page ships a placeholder in `src` until the image nears the
        viewport. Capturing without scrolling rebuilds the page with grey rectangles."""
        import inspect

        from integrations import replica_capture

        assert "scrollTo" in inspect.getsource(replica_capture.capture_replica)


class TestItNeverBreaksTheCaller:
    def test_a_missing_browser_degrades_rather_than_raising(self, monkeypatch) -> None:
        import builtins

        real = builtins.__import__

        def no_playwright(name: str, *a: Any, **k: Any) -> Any:
            if name.startswith("playwright"):
                raise ImportError("no playwright")
            return real(name, *a, **k)

        monkeypatch.setattr(builtins, "__import__", no_playwright)
        cap = capture_replica("https://example.test/")
        assert cap.viewports == []
        assert any("playwright" in n for n in cap.notes)

    def test_an_unreachable_page_degrades(self) -> None:
        """A client's site is not ours to control; a worker must not die on it."""
        cap = capture_replica("http://127.0.0.1:9/nothing", timeout_ms=2000)
        assert cap.viewports == [] or all(v.root is None for v in cap.viewports)
        assert cap.notes
