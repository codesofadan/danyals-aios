"""The provider seam: is each probe actually asked at its own coordinate?

NO network - ``request_json`` is stubbed and the captured request body is asserted on.

**THE MOST IMPORTANT TEST IN THIS FILE** is
``test_the_probe_is_addressed_by_coordinate_not_by_place_name``.

The retired attempt at this feature
(``danyals-audit-system/audit_engine/integrations/geo_grid.py``) sent each point as
``location="lat,lng"`` to Serper's ``/search``. That parameter takes a canonical
location NAME, so the call does not fail - it quietly returns an unlocalised SERP.
Every point of the grid then gets the same answer, and the output is a perfectly
smooth heat map that is entirely fictional. Nothing downstream can detect it: the
positions are well-formed, the run completes, and the client is shown a service-area
map of a measurement that was never taken.

So this file pins the one line that distinguishes a real grid from a fictional one,
and the liveness rule that keeps a Serper-only deploy from running one at all.

Also pinned: DataForSEO answers **200 OK for a task that failed** and puts the real
outcome in ``tasks[0].status_code``. Reading that envelope as an empty pack would
record a clean 'absent' for a probe that never ran - the fabrication this module
exists to refuse.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import SecretStr

from app.modules.grid_tracker.provider import (
    DataForSeoGridProvider,
    FakeGridProvider,
    grid_provider_from_settings,
    grid_provider_is_live,
    resolve_center,
)

pytestmark = pytest.mark.unit


def _envelope(items: list[dict[str, Any]], *, status_code: int = 20000) -> dict[str, Any]:
    """A DataForSEO Maps response envelope: tasks[].result[].items[]."""
    return {"tasks": [{"status_code": status_code, "result": [{"items": items}]}]}


class _Settings:
    """Just the attributes the factory reads."""

    def __init__(self, *, dfs: bool = False, serper: bool = False) -> None:
        self.dataforseo_login = "user@example.com" if dfs else ""
        self.dataforseo_password = SecretStr("pw") if dfs else SecretStr("")
        self.serper_api_key = SecretStr("sk") if serper else SecretStr("")
        self.grid_probe_zoom = 14
        self.grid_point_cost_estimate = 0.003


def _provider(monkeypatch: pytest.MonkeyPatch, response: dict[str, Any]) -> tuple[Any, list[Any]]:
    """A real provider whose HTTP layer is replaced by a recorder."""
    captured: list[Any] = []
    p = DataForSeoGridProvider(login="u", password="p", zoom=14)

    def fake_request_json(method: str, url: str, **kw: Any) -> dict[str, Any]:
        captured.append({"method": method, "url": url, **kw})
        return response

    monkeypatch.setattr(p, "request_json", fake_request_json)
    return p, captured


class TestTheCoordinateContract:
    def test_the_probe_is_addressed_by_coordinate_not_by_place_name(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """THE LINE THE WHOLE MODULE EXISTS FOR."""
        p, captured = _provider(monkeypatch, _envelope([]))
        p.probe(keyword="dentist", lat=24.8607, lng=67.0011, place_id=None, business_name="Acme")

        body = captured[0]["json_body"][0]
        assert body["location_coordinate"] == "24.8607,67.0011,14"
        # A place NAME must not be how this request is addressed - that is the defect.
        assert "location_name" not in body
        assert "location" not in body

    def test_each_point_gets_its_own_coordinate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The regression that produces a smooth, fictional map: every probe carrying
        the same location."""
        p, captured = _provider(monkeypatch, _envelope([]))
        for lat, lng in [(24.86, 67.00), (24.87, 67.00), (24.86, 67.01)]:
            p.probe(keyword="dentist", lat=lat, lng=lng, place_id=None, business_name="Acme")

        coords = [c["json_body"][0]["location_coordinate"] for c in captured]
        assert len(set(coords)) == 3, f"every probe used the same location: {coords}"

    def test_the_zoom_is_carried_into_the_coordinate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p = DataForSeoGridProvider(login="u", password="p", zoom=11)
        captured: list[Any] = []
        monkeypatch.setattr(
            p, "request_json",
            lambda method, url, **kw: (captured.append(kw), _envelope([]))[1],
        )
        p.probe(keyword="x", lat=1.5, lng=2.5, place_id=None, business_name="Acme")
        assert captured[0]["json_body"][0]["location_coordinate"].endswith(",11")


class TestEnvelopeHandling:
    def test_a_failed_task_inside_a_200_is_an_error_not_an_empty_pack(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DataForSEO reports task failures INSIDE a 200 response. Treating that as an
        empty pack records a clean 'absent' for a probe that never ran."""
        p, _ = _provider(monkeypatch, _envelope([], status_code=40501))
        result = p.probe(
            keyword="dentist", lat=24.86, lng=67.0, place_id=None, business_name="Acme"
        )
        assert result.status == "error"
        assert result.measured is False
        assert "40501" in result.error

    def test_a_transport_failure_is_an_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        p = DataForSeoGridProvider(login="u", password="p")

        def boom(method: str, url: str, **kw: Any) -> dict[str, Any]:
            raise RuntimeError("connection reset")

        monkeypatch.setattr(p, "request_json", boom)
        result = p.probe(keyword="x", lat=1.0, lng=2.0, place_id=None, business_name="Acme")
        assert result.status == "error" and result.rank is None

    def test_a_genuinely_empty_pack_is_absent(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The task SUCCEEDED and the business is not there: a real observation."""
        p, _ = _provider(monkeypatch, _envelope([{"title": "Someone Else"}]))
        result = p.probe(
            keyword="dentist", lat=24.86, lng=67.0, place_id=None, business_name="Acme"
        )
        assert result.status == "absent"
        assert result.measured is True
        assert result.top_competitors == ["Someone Else"]

    def test_a_match_records_its_one_based_position(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        p, _ = _provider(monkeypatch, _envelope([
            {"title": "Rival"}, {"title": "Acme Dental", "website": "https://acme.test"},
        ]))
        result = p.probe(
            keyword="dentist", lat=24.86, lng=67.0, place_id=None, business_name="Acme Dental"
        )
        assert result.status == "ranked"
        assert result.rank == 2, "the pack is 1-based; index 1 is position 2"
        assert result.in_map_pack is True
        assert result.found_url == "https://acme.test"

    def test_a_place_id_identifies_a_listing_whose_name_drifted(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The provider-issued handle is what finds a listing whose display name has
        drifted from the client record - without it the business reads as absent."""
        p, _ = _provider(monkeypatch, _envelope([
            {"title": "Rival Dental", "placeId": "other"},
            {"title": "Acme Dental Clinic (Main St)", "placeId": "ChIJ-ours"},
        ]))
        result = p.probe(
            keyword="dentist", lat=24.86, lng=67.0,
            place_id="ChIJ-ours", business_name="Acme Dental",
        )
        assert result.rank == 2

    def test_matching_is_first_entry_wins_a_known_limitation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """DOCUMENTING BEHAVIOUR THIS MODULE INHERITS, not endorsing it.

        ``_match_index`` (shared with ``local_seo``, so the two surfaces cannot
        disagree about whether a business is ranking) walks the pack in order and, for
        each entry, tries place_id and then a normalised name. It does NOT make a
        global place_id pass first. So when a DIFFERENT business earlier in the pack
        carries the same display name, that entry matches and our own place_id is
        never reached - the position reported is the rival's.

        This is pre-existing behaviour in a module outside this change's scope, it is
        rare (it needs an exact normalised name collision in the same local pack), and
        the fix - one place_id pass before the name pass - belongs with ``local_seo``'s
        own suite rather than being changed underneath it from here. It is pinned so
        the behaviour is a known quantity rather than a surprise, and so the day it is
        fixed, this test is what says which surfaces change.
        """
        p, _ = _provider(monkeypatch, _envelope([
            {"title": "Acme Dental", "placeId": "a-rival-with-the-same-name"},
            {"title": "Acme Dental", "placeId": "ChIJ-ours"},
        ]))
        result = p.probe(
            keyword="dentist", lat=24.86, lng=67.0,
            place_id="ChIJ-ours", business_name="Acme Dental",
        )
        assert result.rank == 1, (
            "first-entry-wins: the rival at position 1 matched on NAME before our "
            "place_id at position 2 was considered"
        )


class TestLiveness:
    def test_serper_alone_is_not_enough(self) -> None:
        """DELIBERATELY STRICTER than ``local_pack_provider_is_live``, which accepts a
        Serper key. A single-locale check can be asked with a place name; a grid
        cannot. Returning True here on a Serper-only deploy is what would let the
        worker write a full grid of positions all measured at the same SERP.
        """
        assert grid_provider_is_live(_Settings(serper=True)) is False  # type: ignore[arg-type]
        assert grid_provider_is_live(_Settings(dfs=True)) is True  # type: ignore[arg-type]
        assert grid_provider_is_live(_Settings()) is False  # type: ignore[arg-type]

    def test_the_factory_returns_none_rather_than_a_fake(self) -> None:
        """Every other provider factory degrades to a deterministic fake so its module
        stays usable offline. This one must NOT: its output lands in an append-only
        evidence table that a client reads as measured performance.
        """
        assert grid_provider_from_settings(_Settings()) is None  # type: ignore[arg-type]
        assert grid_provider_from_settings(_Settings(serper=True)) is None  # type: ignore[arg-type]
        live = grid_provider_from_settings(_Settings(dfs=True))  # type: ignore[arg-type]
        assert live is not None and not isinstance(live, FakeGridProvider)


class TestCenterResolution:
    def test_a_response_without_coordinates_is_unresolved_not_zero_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """(0, 0) is in the Atlantic. An unresolved centre must be None so the caller
        asks the operator, rather than silently centring the grid off West Africa."""
        import app.modules.grid_tracker.provider as mod

        class _Client:
            def request_json(self, *a: Any, **kw: Any) -> dict[str, Any]:
                return {"places": [{"title": "Acme", "placeId": "x"}]}  # no lat/lng

        monkeypatch.setattr(mod, "HttpProviderClient", lambda **kw: _Client())
        assert resolve_center(
            _Settings(serper=True), business_name="Acme", address="Karachi"  # type: ignore[arg-type]
        ) is None

    def test_out_of_range_coordinates_are_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.modules.grid_tracker.provider as mod

        class _Client:
            def request_json(self, *a: Any, **kw: Any) -> dict[str, Any]:
                return {"places": [{"latitude": 999.0, "longitude": 67.0}]}

        monkeypatch.setattr(mod, "HttpProviderClient", lambda **kw: _Client())
        assert resolve_center(
            _Settings(serper=True), business_name="Acme", address="Karachi"  # type: ignore[arg-type]
        ) is None

    def test_a_resolved_centre_carries_its_coordinates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.modules.grid_tracker.provider as mod

        class _Client:
            def request_json(self, *a: Any, **kw: Any) -> dict[str, Any]:
                # A `title` is included because every real Places result has one, and
                # the resolver now REFUSES a listing it cannot match against the
                # searched business name - a title-less result is unjudgeable, and for
                # a paid measurement unjudgeable falls the safe way.
                return {"places": [{
                    "title": "Acme Dental", "latitude": 24.8607123456,
                    "longitude": 67.0011, "placeId": "ChIJ-x",
                    "address": "12 Main St, Karachi",
                }]}

        monkeypatch.setattr(mod, "HttpProviderClient", lambda **kw: _Client())
        got = resolve_center(
            _Settings(serper=True), business_name="Acme Dental", address="Karachi"  # type: ignore[arg-type]
        )
        assert got is not None
        assert got.lat == 24.860712, "rounded to 6dp (~0.1 m), so runs stay comparable"
        assert got.place_id == "ChIJ-x"
        # The matched listing travels with the coordinates, so a centre resolved to the
        # wrong business is visible before a run is paid for (0142).
        assert got.matched_name == "Acme Dental"
        assert "Main St" in got.matched_address

    def test_no_serper_key_means_unresolved(self) -> None:
        assert resolve_center(
            _Settings(), business_name="Acme", address="Karachi"  # type: ignore[arg-type]
        ) is None


class TestMatchPlausibility:
    """A resolved centre decides where a PAID, append-only measurement is taken, so a
    listing that is obviously not the client's must be refused rather than labelled.

    Measured on first real use: a client called "Brand Kit Test" resolved to Walgreens
    in Delaware, then to Meijer in Michigan. Both would have produced 17 honest probes
    of an unrelated US retailer, forever.
    """

    @pytest.mark.parametrize(("searched", "matched"), [
        ("Brand Kit Test", "Walgreens"),
        ("Brand Kit Test", "Meijer, Grand Rapids, MI"),
        ("Acme Dental", "Bright Smiles Orthodontics"),
    ])
    def test_an_unrelated_listing_is_refused(self, searched: str, matched: str) -> None:
        from app.modules.grid_tracker.provider import _plausible_match
        assert _plausible_match(searched, matched) is False

    @pytest.mark.parametrize(("searched", "matched"), [
        ("Alligator Pools", "Alligator Pools, 8934 SW 129th Terrace, Miami"),
        ("Acme Dental", "Acme Dental Clinic (Main St)"),
        ("Brand Kit Test", "Brand Kit Test Co"),
    ])
    def test_the_same_business_under_a_longer_name_passes(
        self, searched: str, matched: str
    ) -> None:
        """A LOW bar on purpose. Real listings differ from client records - a trading
        name, a branch suffix, a franchise - and a stricter test rejects correct
        matches as readily as wrong ones."""
        from app.modules.grid_tracker.provider import _plausible_match
        assert _plausible_match(searched, matched) is True

    def test_a_name_of_pure_corporate_noise_is_refused_not_waved_through(self) -> None:
        """UNJUDGEABLE FALLS THE SAFE WAY. "The Co Ltd" yields no comparable token, so
        the match cannot be assessed - and for a paid measurement "I cannot tell" must
        mean refuse. An earlier version returned True here, which is how the Walgreens
        match got through in the first place."""
        from app.modules.grid_tracker.provider import _plausible_match
        assert _plausible_match("The Co Ltd", "Walgreens") is False

    def test_an_empty_name_makes_no_claim_to_check(self) -> None:
        from app.modules.grid_tracker.provider import _plausible_match
        assert _plausible_match("", "Anything At All") is True

    def test_stopwords_describe_language_not_the_failing_sample(self) -> None:
        """The first version stopworded "brand", "kit" and "test" - words lifted from
        the single client that exposed the bug. That emptied its token set and sent it
        down the unjudgeable branch, which then passed. Overfitting a guard to its
        first counterexample disables it."""
        from app.modules.grid_tracker.provider import _MATCH_STOPWORDS
        for word in ("brand", "kit", "test", "demo", "services", "solutions"):
            assert word not in _MATCH_STOPWORDS
