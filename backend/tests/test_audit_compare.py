"""What changed since the last audit.

"Fixed" is the word a client hears as a promise, so most of these tests are about the one
way this feature could lie: reporting a finding as FIXED when it only disappeared because
the later run stopped looking at that dimension. That is `unchecked`, and it is asserted
here from both directions.

The other guarded property is the score gate: two runs are only comparable when they
measured the same check set, and when they did not, the DELTA IS WITHHELD while the
findings - which are keyed on a fingerprint that survives a depth change - still compare.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.audit_compare import compare, identity

pytestmark = pytest.mark.unit


def _finding(
    check: str, fingerprint: str, *, dimension: str = "technical",
    severity: str = "major", pages: int = 3, title: str | None = None,
) -> dict[str, Any]:
    return {
        "scope_type": "site", "scope_key": "acme.test", "check_id": check,
        "fingerprint": fingerprint, "dimension": dimension, "severity": severity,
        "instance_count": pages, "title": title or check,
    }


def _site(score: float | None, *, basis: str = "H1", health: float | None = 60.0) -> dict[str, Any]:
    return {"level": "site", "score": score, "basis_hash": basis, "url_health_pct": health}


def _dim(key: str, score: float | None, *, ran: int = 40, basis: str = "H1") -> dict[str, Any]:
    return {"level": "dimension", "key": key, "label": key.title(), "score": score,
            "basis_hash": basis, "checks_ran": ran}


class TestIdentity:
    def test_a_cause_is_keyed_on_what_does_not_move_with_the_content(self) -> None:
        """The URL, the count and the page id all change when the SITE changes rather than
        when the problem does. A fingerprint that moved with content could not answer "is
        this the same problem we saw last month", which is the only question here."""
        a = _finding("TECH-1", "fp", pages=3)
        b = {**a, "instance_count": 99, "url": "https://acme.test/other", "id": "different"}
        assert identity(a) == identity(b)


class TestFixedNewPersisting:
    def test_the_three_buckets(self) -> None:
        before = [_finding("TECH-1", "a"), _finding("TECH-2", "b")]
        after = [_finding("TECH-2", "b", pages=7), _finding("TECH-3", "c")]
        result = compare(
            before_findings=before, after_findings=after,
            before_rollups=[_site(50), _dim("technical", 40)],
            after_rollups=[_site(70), _dim("technical", 65)],
        )
        assert [f.check_id for f in result.fixed] == ["TECH-1"]
        assert [f.check_id for f in result.new] == ["TECH-3"]
        assert [f.check_id for f in result.persisting] == ["TECH-2"]

    def test_a_persisting_finding_reports_how_its_reach_moved(self) -> None:
        result = compare(
            before_findings=[_finding("TECH-1", "a", pages=3)],
            after_findings=[_finding("TECH-1", "a", pages=9)],
            before_rollups=[_site(50), _dim("technical", 40)],
            after_rollups=[_site(50), _dim("technical", 40)],
        )
        assert result.persisting[0].pages_delta == 6

    def test_worst_first(self) -> None:
        after = [
            _finding("A", "1", severity="minor"),
            _finding("B", "2", severity="critical"),
            _finding("C", "3", severity="major"),
        ]
        result = compare(before_findings=[], after_findings=after,
                         before_rollups=[_site(50)], after_rollups=[_site(50)])
        assert [f.check_id for f in result.new] == ["B", "C", "A"]


class TestTheOneWayThisCouldLie:
    def test_a_finding_whose_dimension_was_not_re_run_is_unchecked_not_fixed(self) -> None:
        """The whole reason this reads both runs' COVERAGE and not just their findings.

        A shallower depth, a lapsed provider key or an agent that did not fire all make a
        finding disappear. Reporting that as work completed would be the one outright lie
        the feature is capable of.
        """
        result = compare(
            before_findings=[_finding("OFF-1", "a", dimension="offpage")],
            after_findings=[],
            before_rollups=[_site(50), _dim("offpage", 30, ran=20)],
            after_rollups=[_site(50), _dim("offpage", None, ran=0)],
        )
        assert [f.check_id for f in result.unchecked] == ["OFF-1"]
        assert result.fixed == []

    def test_a_finding_whose_dimension_did_run_again_is_genuinely_fixed(self) -> None:
        result = compare(
            before_findings=[_finding("OFF-1", "a", dimension="offpage")],
            after_findings=[],
            before_rollups=[_site(50), _dim("offpage", 30, ran=20)],
            after_rollups=[_site(50), _dim("offpage", 80, ran=20)],
        )
        assert [f.check_id for f in result.fixed] == ["OFF-1"]
        assert result.unchecked == []

    def test_an_unknown_dimension_is_treated_as_re_run(self) -> None:
        """A run whose rollups do not mention the dimension at all (an older audit) is
        compared rather than silently dropped; the alternative is a delta that reports
        nothing changed because nothing could be classified."""
        result = compare(
            before_findings=[_finding("X-1", "a", dimension="mystery")],
            after_findings=[],
            before_rollups=[_site(50)], after_rollups=[_site(50)],
        )
        assert [f.check_id for f in result.fixed] == ["X-1"]


class TestTheScoreGate:
    def test_a_matching_basis_gives_a_delta(self) -> None:
        result = compare(
            before_findings=[], after_findings=[],
            before_rollups=[_site(50, basis="H1")], after_rollups=[_site(70, basis="H1")],
        )
        assert result.comparable
        assert result.score_delta == 20.0
        assert result.reason == ""

    def test_a_different_basis_withholds_the_delta_and_says_why(self) -> None:
        result = compare(
            before_findings=[], after_findings=[],
            before_rollups=[_site(50, basis="FREE")], after_rollups=[_site(90, basis="DEEP")],
        )
        assert not result.comparable
        assert result.score_delta is None
        assert "not comparable" in result.reason

    def test_page_health_survives_a_basis_change(self) -> None:
        """Its denominator is PAGES, not checks - which is exactly why 0094 introduced it."""
        result = compare(
            before_findings=[], after_findings=[],
            before_rollups=[_site(50, basis="FREE", health=60)],
            after_rollups=[_site(90, basis="DEEP", health=85)],
        )
        assert (result.health_before, result.health_after) == (60.0, 85.0)

    def test_a_missing_score_is_not_a_zero(self) -> None:
        result = compare(
            before_findings=[], after_findings=[],
            before_rollups=[_site(None)], after_rollups=[_site(70)],
        )
        assert result.score_before is None
        assert result.score_delta is None


class TestPerDimension:
    def test_each_dimension_carries_its_own_counts_and_gate(self) -> None:
        result = compare(
            before_findings=[_finding("T-1", "a", dimension="technical")],
            after_findings=[_finding("O-1", "b", dimension="offpage")],
            before_rollups=[_site(50), _dim("technical", 40), _dim("offpage", 30)],
            after_rollups=[
                _site(50), _dim("technical", 80),
                # A different basis on ONE dimension withholds only that delta.
                _dim("offpage", 20, basis="OTHER"),
            ],
        )
        by_key = {d.key: d for d in result.dimensions}
        assert by_key["technical"].fixed == 1
        assert by_key["technical"].score_delta == 40.0
        assert by_key["offpage"].new == 1
        assert by_key["offpage"].score_delta is None
        assert by_key["offpage"].score_withheld == "different check sets"


class TestTheHeadline:
    def test_nothing_changed_says_nothing(self) -> None:
        result = compare(
            before_findings=[_finding("T-1", "a")], after_findings=[_finding("T-1", "a")],
            before_rollups=[_site(50), _dim("technical", 40)],
            after_rollups=[_site(50), _dim("technical", 40)],
        )
        assert result.headline == ""

    def test_a_change_is_summarised_in_one_line(self) -> None:
        result = compare(
            before_findings=[_finding("T-1", "a")], after_findings=[_finding("T-2", "b")],
            before_rollups=[_site(50), _dim("technical", 40)],
            after_rollups=[_site(50), _dim("technical", 40)],
        )
        assert result.headline == "1 fixed, 1 new"
