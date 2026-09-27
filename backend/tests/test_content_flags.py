"""The review signal: named problems, and never a score.

WHAT THIS PROTECTS. The QA scorecard's weighted total is no longer shown to a reviewer
(operator's decision, 2026-09-26) because ``content_qa`` itself declares the threshold and
weight vector uncalibrated against ranking outcomes or a human grade. The deterministic
detections underneath it are NOT provisional, and those are what the review surfaces now
render.

Two rules are easy to break by accident and are asserted here directly:

  * an UNMEASURED dimension must raise nothing - "we did not look" and "we looked and it is
    wrong" are opposite claims, and the old approve dialog had to special-case a provider
    degrade being rendered as a quality failure;
  * no number, threshold or total may leak back into the output, not even inside a label.
"""

from __future__ import annotations

import pytest

from app.services.content_flags import flags_for, flags_payload
from app.services.content_qa import HARD_GATE_DIMENSIONS, MIN_DIMENSION_SCORE, UNMEASURED

pytestmark = pytest.mark.unit


def _card(**dims: float) -> dict[str, object]:
    return {"dimensions": dims, "weighted_total": 61.0, "passed": False, "provisional": True}


class TestWhatIsRaised:
    def test_a_clean_draft_raises_nothing(self) -> None:
        flags = flags_for(_card(fact_grounding=95, cta_ux=88, internal_linking=80))
        assert flags == []

    def test_a_doctrine_floor_is_a_problem_and_others_are_notes(self) -> None:
        flags = flags_for(_card(fact_grounding=40, internal_linking=40))
        kinds = {f.key: f.kind for f in flags}
        assert kinds["fact_grounding"] == "problem"
        assert kinds["internal_linking"] == "note"

    def test_problems_sort_before_notes(self) -> None:
        flags = flags_for(_card(internal_linking=10, fact_grounding=69))
        assert [f.kind for f in flags] == ["problem", "note"]

    def test_every_hard_gate_dimension_has_reviewer_facing_copy(self) -> None:
        """A flag with no wording would render its raw key ("eeat_experience") to a lead."""
        flags = flags_for(_card(**dict.fromkeys(HARD_GATE_DIMENSIONS, 10.0)))
        for flag in flags:
            assert flag.title and "_" not in flag.title, flag.key
            assert flag.detail.endswith(".") or flag.detail.endswith("'"), flag.key


class TestWhatIsNeverRaised:
    def test_an_unmeasured_dimension_raises_nothing(self) -> None:
        """This is the case that mattered most: a provider degrade is not a quality
        failure, and the surface it used to appear on was an approve dialog."""
        assert flags_for(_card(fact_grounding=float(UNMEASURED))) == []

    def test_a_dimension_exactly_at_the_floor_passes(self) -> None:
        assert flags_for(_card(fact_grounding=float(MIN_DIMENSION_SCORE))) == []

    def test_an_absent_scorecard_raises_nothing(self) -> None:
        """A job that has not reached review, or one that predates the scorer. Inventing a
        warning from missing data is the same mistake as inventing a score."""
        assert flags_for(None) == []
        assert flags_for({}) == []
        assert flags_for({"dimensions": "not a dict"}) == []

    def test_no_score_threshold_or_total_appears_anywhere_in_the_output(self) -> None:
        """The whole point. A number that cannot support a verdict must not come back in
        through a label, a detail string or a count."""
        payload = flags_payload(_card(fact_grounding=40, cta_ux=12, originality=3))
        blob = repr(payload)
        for leak in ("61", "/100", "weighted", "threshold", "85", "score"):
            assert leak not in blob.lower(), f"{leak!r} leaked into the review payload"


class TestDegradedJudging:
    def test_a_proxy_note_is_disclosed(self) -> None:
        """A clean screen produced by a broken judge is the failure this guards against."""
        card = _card(fact_grounding=95)
        card["notes"] = ["judged dimensions fell back to deterministic proxies"]
        keys = [f.key for f in flags_for(card)]
        assert keys == ["judge_degraded"]

    def test_an_ordinary_note_is_not_mistaken_for_a_degrade(self) -> None:
        card = _card(fact_grounding=95)
        card["notes"] = ["entity coverage computed over 12 entities"]
        assert flags_for(card) == []


class TestThePayload:
    def test_counts_match_the_flags(self) -> None:
        payload = flags_payload(_card(fact_grounding=10, internal_linking=10, cta_ux=10))
        assert payload["problems"] == 1
        assert payload["notes"] == 2
        assert len(payload["flags"]) == 3
