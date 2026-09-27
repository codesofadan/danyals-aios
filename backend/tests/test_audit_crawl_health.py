"""Did we actually get to look at this site?

The verdict changes what the whole report MEANS, so the tests here are mostly about
restraint: `blocked` is an accusation ("your site refused us") and must only be made on
unambiguous evidence. Everything weaker is `thin`, which states what was seen without
blaming anyone.

The first live run of this check called a real one-page audit of example.com "blocked",
because the page budget was 15 and the site has one page. That case is now a test.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.audit_crawl_health import assess

pytestmark = pytest.mark.unit


def _pages(*statuses: int) -> list[dict[str, Any]]:
    return [{"http_status": s} for s in statuses]


class TestBlockedNeedsRefusals:
    def test_a_majority_of_refusals_is_blocked(self) -> None:
        health = assess(_pages(403, 403, 403, 403, 403, 403, 200, 200), planned=10)
        assert health.verdict == "blocked"
        assert "refused" in health.note

    def test_nothing_fetched_at_all_is_blocked(self) -> None:
        """The strongest and least ambiguous evidence: there is no audit here."""
        health = assess([], planned=15)
        assert health.verdict == "blocked"
        assert health.fetched == 0

    def test_a_missing_status_counts_as_unreachable(self) -> None:
        assert assess([*_pages(403), {"http_status": None}], planned=4).verdict == "blocked"

    def test_one_real_page_of_a_large_budget_is_thin_and_not_blocked(self) -> None:
        """MEASURED on the first live run: a genuine one-page site (example.com) against a
        15-page budget was reported as blocked. A 200 response is not a wall, and calling a
        small site blocked is exactly the accusation this module is supposed to withhold."""
        health = assess(_pages(200), planned=15)
        assert health.verdict == "thin"
        assert "1 page of a planned 15" in health.note

    def test_a_site_full_of_404s_is_not_blocked(self) -> None:
        """404s are a real, reportable finding ABOUT the site - not a wall in front of us,
        and not something to excuse the audit with."""
        assert assess(_pages(404, 404, 404, 200), planned=4).verdict == "ok"

    def test_server_errors_are_not_treated_as_refusals(self) -> None:
        assert assess(_pages(500, 500, 200, 200), planned=4).verdict == "ok"


class TestThinAndOk:
    def test_a_small_site_crawled_completely_is_ok(self) -> None:
        assert assess(_pages(200, 200, 200), planned=3).verdict == "ok"

    def test_a_tiny_budget_never_produces_a_thin_verdict(self) -> None:
        """A 3-page quote for a 3-page site returning 2 pages is a complete audit."""
        assert assess(_pages(200, 200), planned=3).verdict == "ok"

    def test_a_fraction_of_a_large_budget_is_thin(self) -> None:
        assert assess(_pages(*([200] * 3)), planned=40).verdict == "thin"

    def test_most_of_a_budget_is_ok(self) -> None:
        assert assess(_pages(*([200] * 18)), planned=20).verdict == "ok"


class TestTheNote:
    def test_a_clean_run_says_nothing(self) -> None:
        """A banner with nothing to say trains people to skip banners."""
        health = assess(_pages(*([200] * 18)), planned=20)
        assert health.note == ""
        assert health.is_clean

    def test_a_blocked_note_names_a_cause_and_what_to_do(self) -> None:
        note = assess(_pages(403, 403, 403), planned=10).note
        assert "bot protection" in note.lower() or "ip block" in note.lower()
        assert "re-run" in note.lower()

    def test_the_counts_are_reported_for_the_row(self) -> None:
        health = assess(_pages(403, 200, 200), planned=8)
        assert (health.refused, health.fetched, health.planned) == (1, 2, 8)
