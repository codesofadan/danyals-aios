"""The keyword-collision guard: never pay to write the same target twice.

The rule is deliberately NARROW - an exact match after normalisation - and the tests below
hold both halves of that: it must catch the unambiguous duplicate reliably, and it must NOT
fire on a pillar and its own supporting pages. A cluster shares a topic by design, and a
guard that warns about every legitimate page is a guard people learn to click through.
"""

from __future__ import annotations

import pytest

from app.services.content_collisions import (
    Collision,
    collision_detail,
    find_collisions,
    index_existing,
    normalise,
)

pytestmark = pytest.mark.unit


def _job(code: str, topic: str, *, keyword: str = "", status: str = "done") -> dict[str, object]:
    return {"code": code, "topic": topic, "keyword": keyword, "status": status}


class TestNormalising:
    def test_case_punctuation_and_connecting_words_do_not_make_two_targets(self) -> None:
        assert normalise("Emergency Plumber in Leeds!") == normalise("emergency plumber leeds")

    def test_a_different_target_stays_different(self) -> None:
        assert normalise("emergency plumber leeds") != normalise("emergency electrician leeds")


class TestCatchingTheDuplicate:
    def test_the_same_topic_collides_and_names_the_existing_page(self) -> None:
        hits = find_collisions([("", "emergency plumbing repair")],
                               [_job("CJ-4200", "Emergency Plumbing Repair")])
        assert len(hits) == 1
        assert hits[0].code == "CJ-4200"
        assert hits[0].matched == "topic"

    def test_the_keyword_is_reported_over_the_topic_when_both_match(self) -> None:
        """The keyword is what the page was optimised for. Reporting the topic instead
        would name the right page for the wrong reason."""
        existing = [_job("CJ-9", "A page about drains", keyword="blocked drain leeds")]
        hits = find_collisions([("blocked drain leeds", "something else")], existing)
        assert hits[0].matched == "keyword"

    def test_a_clash_inside_one_request_is_caught(self) -> None:
        """A research pass can return two items that normalise to one target. Fanning both
        out would CREATE the clash rather than inherit it, and a per-item check made after
        the first insert could not see it."""
        hits = find_collisions(
            [("emergency plumber leeds", "Emergency plumber Leeds"),
             ("emergency plumber in leeds", "Emergency plumber in Leeds")],
            [],
        )
        assert len(hits) == 1
        assert hits[0].code == "(this request)"

    def test_a_drafting_job_still_holds_its_keyword(self) -> None:
        """Two pages racing for one keyword is the thing being prevented; waiting for one
        to publish would be waiting until the money is spent."""
        hits = find_collisions([("", "boiler service")],
                               [_job("CJ-1", "Boiler service", status="drafting")])
        assert hits


class TestNotFiringWhereItShouldNot:
    def test_a_rejected_page_frees_its_keyword(self) -> None:
        assert not find_collisions([("", "boiler service")],
                                   [_job("CJ-1", "Boiler service", status="rejected")])

    def test_a_pillar_and_its_supporting_page_do_not_collide(self) -> None:
        """A cluster SHARES a topic by design. A fuzzy rule would fire here on every
        legitimate page in the set."""
        existing = [_job("CJ-1", "Emergency plumbing", keyword="emergency plumbing")]
        assert not find_collisions([("emergency plumbing leeds", "Emergency plumbing in Leeds")],
                                    existing)

    def test_an_empty_request_collides_with_nothing(self) -> None:
        assert find_collisions([], [_job("CJ-1", "anything")]) == []

    def test_a_page_with_no_keyword_or_topic_is_ignored(self) -> None:
        assert find_collisions([("", "")], [_job("CJ-1", "Something real")]) == []


class TestTheIndex:
    def test_the_earliest_job_wins_a_tie(self) -> None:
        """The collision should name the page that got there first, not whichever row the
        database happened to return last."""
        index = index_existing([_job("CJ-1", "Boiler service"), _job("CJ-2", "boiler service")])
        assert index[normalise("boiler service")]["code"] == "CJ-1"


class TestTheRefusalMessage:
    def test_it_names_the_page_and_the_way_out(self) -> None:
        text = collision_detail([
            Collision(term="boiler service", code="CJ-1", topic="Boiler service",
                      status="done", matched="topic")
        ])
        assert "CJ-1" in text
        assert "allowDuplicates" in text, "a refusal must say how to proceed deliberately"
