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
    return build_tree(page, extract(nodes))


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
