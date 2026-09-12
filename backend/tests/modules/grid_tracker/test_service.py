"""The grid summary: can an unmeasured point ever read as a ranking absence?

NO DB, NO network. Pure folds over hand-built probe lists.

**THE MOST IMPORTANT TEST IN THIS FILE** is
``test_an_unmeasured_point_never_enters_a_denominator``.

A grid run has three kinds of point: ranked, absent, and error - where 'error' means
the provider never answered. If error points are counted in the denominator of the
coverage ratio, every provider hiccup renders as lost visibility:

    17 points, 5 failed, 6 of the surviving 12 in the top 3
      by total    -> 35%   a decline the business never suffered
      by measured -> 50%   what was actually observed

That is the same defect class as ``local_seo``'s null-rank contract, restated for a
shape that must keep its holes rather than drop them. The number gets worse the
flakier the provider is, so it degrades exactly when it is least deserved, and it
would be charted to a client as a real trend.

Also pinned: a partially-measured run is ``degraded`` with a written reason (never
``completed``), because ``0138``'s CHECK refuses a non-clean terminal state without
one - and because a half-measured heat map presented as whole is a claim about a
service area nobody verified.
"""

from __future__ import annotations

import pytest

from app.modules.grid_tracker.provider import GridProbeResult
from app.modules.grid_tracker.service import coverage_band, summarize

pytestmark = pytest.mark.unit


def ranked(rank: int) -> GridProbeResult:
    return GridProbeResult(status="ranked", rank=rank)


def absent() -> GridProbeResult:
    return GridProbeResult(status="absent")


def failed(reason: str = "timeout") -> GridProbeResult:
    return GridProbeResult(status="error", error=reason)


class TestTheDenominator:
    def test_an_unmeasured_point_never_enters_a_denominator(self) -> None:
        """THE TEST THIS MODULE'S HONESTY RESTS ON.

        17-point grid; 5 probes failed; of the 12 that answered, 6 are in the top 3.
        The answer is 6/12, not 6/17.
        """
        probes = [ranked(1)] * 6 + [ranked(8)] * 2 + [absent()] * 4 + [failed()] * 5
        s = summarize(probes, points_total=17)

        assert s.points_ranked == 8
        assert s.points_absent == 4
        assert s.points_error == 5
        assert s.points_measured == 12
        assert s.share_top3 == pytest.approx(0.5), "must divide by measured, not total"
        # The pessimistic bug would produce 6/17 = 0.353.
        assert s.share_top3 != pytest.approx(round(6 / 17, 3))

    def test_points_the_worker_never_reached_are_errors_not_absences(self) -> None:
        """A run that dies halfway has 9 unreached points. 'We did not look there' is
        not 'we looked and found nothing' - counting the gap as absence would invent
        an absence at every point the worker never visited."""
        s = summarize([ranked(2)] * 8, points_total=17)
        assert s.points_error == 9
        assert s.points_absent == 0
        assert s.points_measured == 8
        assert s.status == "degraded"

    def test_a_clean_run_divides_by_everything_because_everything_was_measured(self) -> None:
        probes = [ranked(1)] * 9 + [absent()] * 8
        s = summarize(probes, points_total=17)
        assert s.points_error == 0
        assert s.points_measured == 17
        assert s.share_top3 == pytest.approx(round(9 / 17, 3))
        assert s.status == "completed"
        assert s.reason == ""


class TestAverages:
    def test_the_average_covers_ranked_points_only(self) -> None:
        """An absent point has no position. Averaging it as a sentinel (100, or the
        pack size) would report a number the provider never gave."""
        s = summarize([ranked(2), ranked(4), absent(), failed()], points_total=4)
        assert s.avg_rank == pytest.approx(3.0), "mean of 2 and 4, not of 2, 4 and a sentinel"

    def test_nothing_ranked_means_no_average_rather_than_zero(self) -> None:
        """None and 0.0 are different claims: 'never in the pack' vs 'ranked first
        everywhere'. Zero here would be the second, rendered as the best result."""
        s = summarize([absent(), absent()], points_total=2)
        assert s.avg_rank is None
        assert s.share_top3 == pytest.approx(0.0), "measured everywhere, in the pack nowhere"

    def test_nothing_measured_means_no_share_rather_than_zero(self) -> None:
        """Distinct from the case above: here the provider answered nowhere, so 0.0
        would assert coverage was measured and found to be nil."""
        s = summarize([failed(), failed()], points_total=2)
        assert s.share_top3 is None
        assert s.avg_rank is None


class TestVerdict:
    def test_a_total_failure_is_failed_with_a_reason(self) -> None:
        s = summarize([failed("429")] * 17, points_total=17)
        assert s.status == "failed"
        assert s.reason, "0138's CHECK refuses a non-clean status with no reason"

    def test_a_partial_run_is_degraded_and_says_what_the_percentages_cover(self) -> None:
        s = summarize([ranked(1)] * 10 + [failed()] * 7, points_total=17)
        assert s.status == "degraded"
        assert "7" in s.reason and "10" in s.reason, (
            "the caveat must carry BOTH numbers: what was lost and what the figures "
            "are actually over"
        )

    @pytest.mark.parametrize("status", ["completed", "degraded", "failed"])
    def test_every_non_completed_verdict_carries_a_reason(self, status: str) -> None:
        """Mirrors ``grid_runs_reason_required_ck``. A summary that produced a
        reasonless 'degraded' would be refused by Postgres at write time, turning a
        presentation bug into a lost run."""
        cases = {
            "completed": ([ranked(1)], 1),
            "degraded": ([ranked(1), failed()], 2),
            "failed": ([failed()], 1),
        }
        probes, total = cases[status]
        s = summarize(probes, points_total=total)
        assert s.status == status
        assert (s.reason == "") is (status == "completed")


class TestCoverageBand:
    def test_unmeasured_is_its_own_band_and_not_the_worst_one(self) -> None:
        """No data is not bad data. Rendering None as 'absent' would paint a grid the
        provider never answered for in the same colour as one it answered badly."""
        assert coverage_band(None) == "unmeasured"
        assert coverage_band(0.0) == "absent"

    @pytest.mark.parametrize(
        ("share", "band"),
        [(1.0, "strong"), (0.75, "strong"), (0.74, "mixed"), (0.40, "mixed"),
         (0.39, "weak"), (0.01, "weak"), (0.0, "absent")],
    )
    def test_the_bands_are_stable_at_their_boundaries(self, share: float, band: str) -> None:
        assert coverage_band(share) == band

def test_creating_the_same_grid_twice_is_idempotent_not_a_500() -> None:
    """THE BUG THIS PINS, reported from production on 2026-09-12.

    0138 declares `unique (profile_id, keyword)` - one standing grid per business per
    keyword, which is right: a duplicate would double the weekly probe bill and split
    one keyword's history across two charts. But the raw INSERT let that constraint
    surface as an unhandled `psycopg.errors.UniqueViolation`, so an operator who
    submitted "health center near me" twice for the same client got:

        POST /api/v1/grid/definitions -> 500 Internal Server Error

    A constraint doing its job must never reach the operator as a crash. The insert is
    now `on conflict (profile_id, keyword) do nothing` with a read-back, so asking
    twice returns the grid that already exists.

    This asserts the SQL carries both halves, because the behaviour needs a database to
    exercise and this module's suite is deliberately DB-free (the repo is faked
    everywhere else). A source assertion is weaker than a round trip - so it checks the
    two things whose absence caused the 500, and says so.
    """
    import inspect

    from app.modules.grid_tracker.repo import GridRepo

    src = inspect.getsource(GridRepo.create_definition)
    assert "on conflict (profile_id, keyword) do nothing" in src, (
        "a duplicate keyword must not raise UniqueViolation at the operator"
    )
    assert "select * from public.grid_definitions" in src, (
        "on conflict do nothing returns NO row, so the existing grid must be read back "
        "- without this the caller gets None and reports a failure for a grid that exists"
    )
