"""DataForSEO: the location code, and the task error that hid behind a 200.

Both defects here were found by calling the LIVE API on 2026-08-25, and neither was
visible from the code or from any offline test. Together they meant this integration
returned zero rows on every call it had ever made, and reported nothing wrong.
"""

from __future__ import annotations

from typing import Any

import pytest

from integrations.keyword_data import (
    DEFAULT_LOCATION_CODE,
    DataForSeoTaskError,
    _dfs_items,
    _dfs_request_body,
    resolve_location_code,
)

pytestmark = pytest.mark.unit


class TestTheLocationCode:
    """`location_name` wants "United States"; the Protocol hands over "us". The live
    API answers 40501 Invalid Field: 'location_name' and returns no rows."""

    @pytest.mark.parametrize(
        ("geo", "code"),
        [("us", 2840), ("US", 2840), ("usa", 2840), ("United States", 2840),
         ("gb", 2826), ("uk", 2826), ("ca", 2124), ("au", 2036)],
    )
    def test_a_country_hint_resolves_to_a_numeric_code(self, geo: str, code: int) -> None:
        assert resolve_location_code(geo) == code

    @pytest.mark.parametrize("geo", [None, "", "   "])
    def test_an_absent_geo_uses_the_default_market(self, geo: str | None) -> None:
        assert resolve_location_code(geo) == DEFAULT_LOCATION_CODE

    @pytest.mark.parametrize("geo", ["fr-CA", "zz", "Mars", "san jose"])
    def test_an_unknown_hint_raises_rather_than_defaulting(self, geo: str) -> None:
        """Silently serving United States data for a request that said "fr" is worse
        than failing: the numbers look valid and nothing downstream can tell they
        describe the wrong country."""
        with pytest.raises(ValueError, match="unknown DataForSEO location"):
            resolve_location_code(geo)

    def test_the_request_body_sends_a_code_not_a_name(self) -> None:
        body = _dfs_request_body(["slab leak repair"], "us", 10)
        assert body["location_code"] == 2840
        assert "location_name" not in body, "the field the live API rejected"
        assert body["language_code"] == "en"

    @pytest.mark.parametrize(("limit", "expected"), [(0, 1), (-5, 1), (10, 10), (5000, 1000)])
    def test_the_limit_stays_inside_the_apis_bounds(self, limit: int, expected: int) -> None:
        assert _dfs_request_body(["k"], "us", limit)["limit"] == expected


class TestATaskErrorIsNotAnEmptyResult:
    """THE SILENT FAILURE. DataForSEO reports per-task errors inside an envelope whose
    own status_code is 20000 Ok. Walking past a failed task returns [], which is
    indistinguishable from "this keyword has no ideas" - so a malformed request looked
    like a keyword with no demand, on every call, forever."""

    def _envelope(self, task: dict[str, Any]) -> dict[str, Any]:
        return {"status_code": 20000, "status_message": "Ok.", "tasks": [task]}

    def test_a_failed_task_raises_with_the_apis_own_code(self) -> None:
        env = self._envelope(
            {"status_code": 40501, "status_message": "Invalid Field: 'location_name'.",
             "result": None}
        )
        with pytest.raises(DataForSeoTaskError) as exc:
            _dfs_items(env)
        assert exc.value.code == 40501
        assert "location_name" in exc.value.message

    def test_the_envelope_saying_ok_does_not_excuse_the_task(self) -> None:
        env = self._envelope({"status_code": 40200, "status_message": "Payment Required."})
        assert env["status_code"] == 20000, "the trap: the outer envelope looks fine"
        with pytest.raises(DataForSeoTaskError):
            _dfs_items(env)

    def test_a_successful_task_yields_its_items(self) -> None:
        env = self._envelope({
            "status_code": 20000, "status_message": "Ok.",
            "result": [{"items": [{"keyword": "leak detection"}, {"keyword": "leak detector"}]}],
        })
        assert [i["keyword"] for i in _dfs_items(env)] == ["leak detection", "leak detector"]

    def test_a_genuinely_empty_result_is_still_empty_not_an_error(self) -> None:
        """The point is to distinguish the two, not to make every empty result raise."""
        env = self._envelope({"status_code": 20000, "result": [{"items": []}]})
        assert _dfs_items(env) == []

    def test_a_task_with_no_status_code_is_tolerated(self) -> None:
        env = self._envelope({"result": [{"items": [{"keyword": "k"}]}]})
        assert len(_dfs_items(env)) == 1
