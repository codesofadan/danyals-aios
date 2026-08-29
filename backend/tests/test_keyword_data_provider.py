"""DataForSEO: the location code, and the task error that hid behind a 200.

Both defects here were found by calling the LIVE API on 2026-08-25, and neither was
visible from the code or from any offline test. Together they meant this integration
returned zero rows on every call it had ever made, and reported nothing wrong.
"""

from __future__ import annotations

from typing import Any, ClassVar

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


class TestTheTwoEnvelopeShapes:
    """Found by calling the LIVE API on 2026-08-29, like the two defects above.

    `keyword_ideas` and `keyword_overview` put the term and its metrics at the TOP
    of each item. `related_keywords` wraps them in `keyword_data`. Reading only the
    flat shape returned a full-length list of COMPLETELY EMPTY metrics - five items
    in, five rows out with keyword='', volume=0 - and an empty string is not an
    error anywhere downstream, so the expansion contributed nothing and said so to
    nobody.
    """

    #: One `related_keywords` item, trimmed to the keys the parser reads.
    NESTED: ClassVar[dict[str, Any]] = {
        "se_type": "google",
        "depth": 1,
        "keyword_data": {
            "keyword": "emergency plumber dallas",
            "keyword_info": {"search_volume": 880, "cpc": 80.89, "competition": 0.14},
            "keyword_properties": {"keyword_difficulty": 7},
        },
        "related_keywords": ["24 hour emergency plumber dallas"],
    }

    #: One `keyword_ideas` / `keyword_overview` item.
    FLAT: ClassVar[dict[str, Any]] = {
        "keyword": "plumbing services",
        "keyword_info": {"search_volume": 49500, "cpc": 12.5, "competition": 0.3},
        "keyword_properties": {"keyword_difficulty": 2},
    }

    def test_the_nested_related_keywords_shape_is_unwrapped(self) -> None:
        from integrations.keyword_data import _metric_from_dfs

        metric = _metric_from_dfs(self.NESTED)
        assert metric.keyword == "emergency plumber dallas"
        assert metric.volume == 880
        assert metric.difficulty == 7.0
        assert metric.cpc == 80.89

    def test_the_flat_shape_still_parses(self) -> None:
        from integrations.keyword_data import _metric_from_dfs

        metric = _metric_from_dfs(self.FLAT)
        assert metric.keyword == "plumbing services"
        assert metric.volume == 49500
        assert metric.difficulty == 2.0

    def test_an_unrecognised_shape_yields_an_empty_metric_rather_than_raising(self) -> None:
        from integrations.keyword_data import _metric_from_dfs

        metric = _metric_from_dfs({"se_type": "google"})
        assert metric.keyword == "" and metric.volume == 0


class TestTheRequestFieldsEachEndpointActuallyRequires:
    """DataForSEO is not uniform across its own Labs endpoints, and it answers a
    wrong shape with a per-TASK 40501 inside a 200 envelope. Both of these were
    rejected on every call until 2026-08-29."""

    def _provider(self, captured: dict[str, Any]) -> Any:
        from integrations.keyword_data import DataForSeoProvider

        provider = DataForSeoProvider(login="user", password="pass")

        def fake_request_json(method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            captured["path"] = path
            captured["body"] = kwargs.get("json_body")
            return {"tasks": [{"status_code": 20000, "result": [{"items": []}]}]}

        provider.request_json = fake_request_json  # type: ignore[method-assign]
        return provider

    def test_related_keywords_sends_the_singular_keyword_field(self) -> None:
        captured: dict[str, Any] = {}
        self._provider(captured).related_keywords("emergency plumber dallas", geo="us")
        body = captured["body"][0]
        assert body["keyword"] == "emergency plumber dallas", (
            "related_keywords takes a SINGULAR keyword; the array form is rejected "
            "with 40501 Invalid Field: 'keyword'"
        )
        assert "keywords" not in body

    def test_the_array_endpoints_still_send_a_keywords_list(self) -> None:
        captured: dict[str, Any] = {}
        provider = self._provider(captured)
        provider.keyword_ideas("emergency plumber dallas", geo="us")
        assert captured["body"][0]["keywords"] == ["emergency plumber dallas"]
        provider.keyword_metrics_bulk(["a", "b"], geo="us")
        assert captured["body"][0]["keywords"] == ["a", "b"]

    def test_search_intent_sends_a_language(self) -> None:
        captured: dict[str, Any] = {}
        self._provider(captured).search_intent("emergency plumber dallas")
        body = captured["body"][0]
        assert body.get("language_code"), (
            "search_intent without a language is rejected with 40501 Invalid Field: "
            "'language_name', so intent silently fell back to the SERP heuristic"
        )
