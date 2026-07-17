"""Rank-tracker analysis core: the movement maths, the ranked-only average, staleness,
and the N-A subscription cost projection.

Pure functions - no DB, no network, no app. Three properties here are the ones that
cost real money or real trust when they break:

1. **change = previous - latest.** Rank is INVERTED (smaller is better), so an
   improvement is a decrease. Getting the subtraction backwards reports every recovery
   as a fall - the classic rank-tracker bug - and no other test would notice.
2. **Average position over RANKED rows only.** Counting an unranked keyword as 0 would
   make it out-rank #1; counting it as the window floor would make the tile lurch as
   long-tail terms drift in and out of the top 100.
3. **The N-A commitment gate.** This is what stands between the agency and silently
   signing a client up to a runaway monthly bill.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.modules.rank_tracker.service import (
    CADENCE_INTERVAL_DAYS,
    WORKSPACE_TABLE_COLS,
    apply_subscription_change,
    average_position,
    build_stats,
    build_workspace,
    change_for_row,
    checks_per_month,
    evaluate_projection,
    is_stale,
    merge_cadence_counts,
    normalize_keyword,
    project_monthly_cost,
    rank_change,
    to_response,
    top_three,
)

pytestmark = pytest.mark.unit

_NOW = datetime(2026, 7, 17, 12, 0, tzinfo=UTC)


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "code": "RK-00001", "client_id": "cl-secret", "client_name": "NorthPeak Dental",
        "keyword": "dental implants karachi", "target_url": "", "engine": "google",
        "device": "desktop", "location": "", "cadence": "weekly", "status": "active",
        "latest_position": 3, "previous_position": 7, "best_position": 2,
        "latest_url": "https://np.example/y", "tags": [], "latest_features": [],
        "latest_checked_at": _NOW - timedelta(hours=2),
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# 1. Movement - the inverted-scale subtraction.
# --------------------------------------------------------------------------- #
def test_a_climb_is_reported_as_an_improvement() -> None:
    """7 -> 3 is FOUR PLACES BETTER. If this ever reads 'down', the module is telling
    every client their recoveries are falls."""
    change = rank_change(7, 3)
    assert change.direction == "up"
    assert change.value == "4"


def test_a_fall_is_reported_as_a_decline() -> None:
    change = rank_change(3, 7)
    assert change.direction == "down"
    assert change.value == "4"  # the MAGNITUDE; the direction carries the sign


def test_no_movement_is_flat_zero() -> None:
    assert rank_change(5, 5) == rank_change(5, 5)
    assert rank_change(5, 5).direction == "flat"
    assert rank_change(5, 5).value == "0"


def test_first_time_ranking_is_new_not_an_infinite_climb() -> None:
    # None -> 4 has no magnitude (there is no previous to subtract), so it must be its
    # own state rather than being coerced into a bogus delta.
    change = rank_change(None, 4)
    assert change.direction == "new" and change.value == "new"


def test_falling_out_of_the_window_is_lost() -> None:
    change = rank_change(4, None)
    assert change.direction == "lost" and change.value == "lost"


def test_never_ranked_is_flat_not_lost() -> None:
    """None -> None is a keyword that has simply never ranked. Calling that 'lost'
    would fire a false alarm on every brand-new unranked subscription."""
    change = rank_change(None, None)
    assert change.direction == "flat" and change.value == "0"


@pytest.mark.parametrize(
    ("previous", "latest", "direction"),
    [(100, 1, "up"), (1, 100, "down"), (2, 1, "up"), (1, 2, "down")],
)
def test_direction_holds_across_the_whole_scale(
    previous: int, latest: int, direction: str
) -> None:
    assert rank_change(previous, latest).direction == direction


def test_change_for_row_reads_the_denormalised_columns() -> None:
    assert change_for_row(_row(previous_position=9, latest_position=4)).value == "5"


# --------------------------------------------------------------------------- #
# 2. Average position - RANKED rows only.
# --------------------------------------------------------------------------- #
def test_average_position_ignores_unranked_rows() -> None:
    """The documented choice: an unranked keyword has no position to average."""
    rows = [_row(latest_position=2), _row(latest_position=4), _row(latest_position=None)]
    assert average_position(rows) == 3.0  # (2+4)/2 - the None is not a 0


def test_an_unranked_row_would_have_dragged_the_average_if_counted_as_zero() -> None:
    # Belt-and-braces on the above: pin the WRONG answer so a regression to `or 0`
    # names itself instead of just shifting a number.
    rows = [_row(latest_position=2), _row(latest_position=4), _row(latest_position=None)]
    assert average_position(rows) != round((2 + 4 + 0) / 3, 1)


def test_an_all_unranked_book_averages_zero_not_a_crash() -> None:
    # Zero rows to average is a division by zero if not guarded; the caller renders
    # this 0.0 as an em-dash rather than as "position 0".
    assert average_position([_row(latest_position=None), _row(latest_position=None)]) == 0.0


def test_an_empty_book_averages_zero() -> None:
    assert average_position([]) == 0.0


def test_average_is_rounded_to_one_decimal() -> None:
    assert average_position([_row(latest_position=1), _row(latest_position=2), _row(latest_position=2)]) == 1.7


def test_top_three_counts_only_ranked_rows_at_or_above_three() -> None:
    rows = [
        _row(latest_position=1), _row(latest_position=3), _row(latest_position=4),
        _row(latest_position=None),
    ]
    assert top_three(rows) == 2


def test_build_stats_counts_every_row_as_tracked_but_averages_only_the_ranked() -> None:
    """The two tiles are honest side by side: 3 tracked, avg 3.0 where we rank."""
    rows = [_row(latest_position=2), _row(latest_position=4), _row(latest_position=None)]
    stats = build_stats(rows)
    assert stats.tracked == 3  # the unranked keyword IS tracked (and IS billed)
    assert stats.avg_position == 3.0  # ... but does not enter the average


# --------------------------------------------------------------------------- #
# 3. Staleness - the visible half of the degrade path.
# --------------------------------------------------------------------------- #
def test_a_freshly_checked_keyword_is_not_stale() -> None:
    assert is_stale(_row(latest_checked_at=_NOW - timedelta(hours=1)), now=_NOW) is False


def test_a_weekly_keyword_goes_stale_past_two_cadence_windows() -> None:
    # 15 days > 2 x 7: the nightly check has demonstrably stalled.
    assert is_stale(_row(cadence="weekly", latest_checked_at=_NOW - timedelta(days=15)), now=_NOW)


def test_a_weekly_keyword_tolerates_one_missed_window() -> None:
    # 8 days: one missed night is a blip, not a stall - crying wolf trains people to
    # ignore the flag.
    assert (
        is_stale(_row(cadence="weekly", latest_checked_at=_NOW - timedelta(days=8)), now=_NOW)
        is False
    )


def test_a_daily_keyword_goes_stale_far_sooner_than_a_weekly_one() -> None:
    aged = _NOW - timedelta(days=3)
    assert is_stale(_row(cadence="daily", latest_checked_at=aged), now=_NOW) is True
    assert is_stale(_row(cadence="weekly", latest_checked_at=aged), now=_NOW) is False


def test_a_never_checked_active_keyword_is_stale() -> None:
    assert is_stale(_row(latest_checked_at=None), now=_NOW) is True


def test_a_paused_keyword_is_never_stale() -> None:
    """A paused subscription is not SUPPOSED to be checked - flagging it stale would
    be crying wolf about a deliberate decision."""
    assert is_stale(_row(status="paused", latest_checked_at=None), now=_NOW) is False


def test_a_naive_timestamp_is_treated_as_utc_rather_than_crashing() -> None:
    # psycopg returns tz-aware stamps, but a fake/legacy row must not blow up the board
    # with "can't subtract offset-naive and offset-aware datetimes".
    naive = (_NOW - timedelta(days=30)).replace(tzinfo=None)
    assert is_stale(_row(latest_checked_at=naive), now=_NOW) is True


def test_an_unparseable_timestamp_does_not_invent_a_stall() -> None:
    assert is_stale(_row(latest_checked_at="not-a-date"), now=_NOW) is False


def test_to_response_carries_both_the_movement_and_the_staleness_verdict() -> None:
    body = to_response(_row(latest_checked_at=_NOW - timedelta(days=30)), now=_NOW)
    assert body.change.direction == "up" and body.change.value == "4"
    assert body.stale is True


# --------------------------------------------------------------------------- #
# 4. N-A: the cost projection maths.
# --------------------------------------------------------------------------- #
def test_checks_per_month_is_derived_from_the_schedulers_own_interval_table() -> None:
    """Pricing and scheduling MUST share one source, or the bill drifts from reality."""
    assert CADENCE_INTERVAL_DAYS == {"daily": 1, "weekly": 7}
    assert checks_per_month("daily") == pytest.approx(30.4375, abs=0.001)
    assert checks_per_month("weekly") == pytest.approx(4.3482, abs=0.001)


def test_a_daily_keyword_costs_seven_times_a_weekly_one() -> None:
    assert checks_per_month("daily") == pytest.approx(checks_per_month("weekly") * 7, abs=0.001)


def test_an_unknown_cadence_prices_as_the_default_never_as_free() -> None:
    # An unpriced subscription is the one that surprises everyone on the invoice.
    assert checks_per_month("fortnightly") == checks_per_month("weekly")
    assert checks_per_month("fortnightly") > 0


def test_project_monthly_cost_sums_every_cadence_bucket() -> None:
    # 10 weekly x 4.3482 + 2 daily x 30.4375 = 43.482 + 60.875 = 104.357 checks
    cost = project_monthly_cost({"weekly": 10, "daily": 2}, 0.001)
    assert cost == pytest.approx(0.1044, abs=0.0005)


def test_projection_scales_linearly_with_the_per_check_price() -> None:
    # So a vendor swap (a different estimated_cost) re-prices the commitment for free.
    cheap = project_monthly_cost({"weekly": 100}, 0.001)
    dear = project_monthly_cost({"weekly": 100}, 0.010)
    assert dear == pytest.approx(cheap * 10, abs=0.001)


def test_an_empty_book_costs_nothing() -> None:
    assert project_monthly_cost({}, 0.001) == 0.0
    assert project_monthly_cost({"weekly": 0}, 0.001) == 0.0


def test_merge_cadence_counts_prices_the_book_as_it_would_be_after_the_add() -> None:
    """Pricing only the NEW keywords would let a client be walked past their cap in
    small batches, each of which looks affordable on its own."""
    assert merge_cadence_counts({"weekly": 10}, {"weekly": 5}) == {"weekly": 15}
    assert merge_cadence_counts({"weekly": 10}, {"daily": 3}) == {"weekly": 10, "daily": 3}
    assert merge_cadence_counts({}, {"daily": 3}) == {"daily": 3}


def test_merge_does_not_mutate_the_current_book() -> None:
    current = {"weekly": 10}
    merge_cadence_counts(current, {"weekly": 5})
    assert current == {"weekly": 10}


# --------------------------------------------------------------------------- #
# 5b. N-A: re-pricing a RECONFIGURED subscription (the add-gate's other door).
# --------------------------------------------------------------------------- #
def test_a_cadence_upgrade_moves_the_keyword_between_buckets() -> None:
    """weekly -> daily is SEVEN times the monthly cost. Without this, the add gate is
    trivially bypassable: add cheap weekly keywords, then flip them all to daily."""
    after = apply_subscription_change(
        {"weekly": 10, "daily": 2}, before=("active", "weekly"), after=("active", "daily")
    )
    assert after == {"weekly": 9, "daily": 3}


def test_pausing_removes_the_keyword_from_the_priced_book() -> None:
    # A paused subscription costs nothing, so it must leave the book entirely.
    after = apply_subscription_change(
        {"weekly": 10}, before=("active", "weekly"), after=("paused", "weekly")
    )
    assert after == {"weekly": 9}


def test_resuming_adds_the_keyword_back_to_the_priced_book() -> None:
    """A resume takes a subscription from $0 back to a full cadence - a real increase
    in the standing bill, and one the add gate never saw."""
    after = apply_subscription_change(
        {"weekly": 9}, before=("paused", "weekly"), after=("active", "weekly")
    )
    assert after == {"weekly": 10}


def test_resuming_at_a_new_cadence_lands_in_the_new_bucket() -> None:
    # It was paused, so it was never in the weekly bucket to remove - only the new
    # (daily) bucket grows.
    after = apply_subscription_change(
        {"daily": 1}, before=("paused", "weekly"), after=("active", "daily")
    )
    assert after == {"daily": 2}


def test_a_paused_to_paused_change_costs_nothing_either_way() -> None:
    after = apply_subscription_change(
        {"weekly": 10}, before=("paused", "weekly"), after=("paused", "daily")
    )
    assert after == {"weekly": 10}  # untouched: it was never in the book


def test_the_bucket_never_goes_negative_on_an_inconsistent_book() -> None:
    # Defensive: a stale/racing count must not produce a negative bucket, which would
    # silently UNDER-price the rest of the book.
    after = apply_subscription_change(
        {}, before=("active", "weekly"), after=("paused", "weekly")
    )
    assert after == {"weekly": 0}


def test_apply_subscription_change_does_not_mutate_the_current_book() -> None:
    current = {"weekly": 10}
    apply_subscription_change(current, before=("active", "weekly"), after=("active", "daily"))
    assert current == {"weekly": 10}


# --------------------------------------------------------------------------- #
# 5. N-A: the over-budget rejection.
# --------------------------------------------------------------------------- #
def _project(**over: Any) -> Any:
    kwargs: dict[str, Any] = {
        "client_name": "Acme",
        "cadence_counts": {"daily": 100},
        "cost_per_check": 0.01,
        "budget": (50.0, 10.0),
        "provider": "serper",
        "live": True,
    }
    kwargs.update(over)
    return evaluate_projection(**kwargs)


def test_a_book_inside_the_remaining_budget_is_allowed() -> None:
    # 10 daily x 30.44 x $0.01 = ~$3.04/mo against $40 remaining.
    projection = _project(cadence_counts={"daily": 10})
    assert projection.within_budget is True
    assert projection.monthly_cost == pytest.approx(3.04, abs=0.01)
    assert projection.budget_remaining == 40.0


def test_a_book_that_would_breach_the_remaining_budget_is_rejected() -> None:
    """THE N-A REQUIREMENT: 100 daily keywords = ~$30.44/mo against only $10 left.
    The refusal has to land here, at configuration time - not at 2am on the 40th check."""
    projection = _project(cadence_counts={"daily": 100}, budget=(50.0, 40.0))
    assert projection.within_budget is False
    assert projection.monthly_cost == pytest.approx(30.44, abs=0.01)
    assert projection.budget_remaining == 10.0


def test_the_rejection_message_names_both_numbers_and_the_way_out() -> None:
    # A bare "rejected" forces the operator to go reverse-engineer the cost screen.
    message = _project(cadence_counts={"daily": 100}, budget=(50.0, 40.0)).message
    assert "Rejected" in message
    assert "$30.4" in message and "$10.00" in message and "$50.00" in message
    assert "Raise the cap" in message and "cadence" in message


def test_the_boundary_is_inclusive_so_spending_exactly_what_is_left_is_allowed() -> None:
    # Exactly at the cap is within the cap; refusing it would be off-by-one theatre.
    projection = _project(cadence_counts={"weekly": 1}, cost_per_check=1.0, budget=(10.0, 10.0 - 4.3482))
    assert projection.monthly_cost == pytest.approx(projection.budget_remaining, abs=0.001)
    assert projection.within_budget is True


def test_a_client_with_no_budget_row_is_uncapped_not_blocked() -> None:
    """Inventing a limit where ops set none would block legitimate work."""
    projection = _project(budget=None)
    assert projection.within_budget is True
    assert projection.budget_cap == 0.0 and projection.budget_remaining == 0.0
    assert "No monthly cap" in projection.message


def test_a_zero_cap_means_uncapped_per_the_0006_schema() -> None:
    # 0006 documents `cap = 0` as "uncapped"; reading it as "$0 allowed" would block
    # every client who has a budget row but no ceiling set.
    projection = _project(budget=(0.0, 0.0))
    assert projection.within_budget is True
    assert "No monthly cap" in projection.message


def test_an_overspent_client_has_zero_remaining_not_a_negative_allowance() -> None:
    # spent > cap: remaining floors at 0, so a negative "budget" can never read as
    # headroom.
    projection = _project(cadence_counts={"weekly": 1}, budget=(50.0, 80.0))
    assert projection.budget_remaining == 0.0
    assert projection.within_budget is False


def test_a_degraded_provider_projects_zero_and_says_so_rather_than_quoting_a_fake_bill() -> None:
    """A keyless deploy runs the fake at $0. Quoting that to a client as their real
    commitment would be worse than useless - the message has to name the caveat."""
    projection = _project(cost_per_check=0.0, provider="fake", live=False)
    assert projection.monthly_cost == 0.0
    assert projection.within_budget is True
    assert "simulated" in projection.message and "fake" in projection.message


def test_the_projection_reports_its_cadence_breakdown_and_provider() -> None:
    projection = _project(cadence_counts={"daily": 2, "weekly": 8})
    assert projection.tracked == 10
    assert projection.daily == 2 and projection.weekly == 8
    assert projection.provider == "serper" and projection.live is True
    assert projection.checks_per_month == pytest.approx(2 * 30.4375 + 8 * 4.3482, abs=0.05)


# --------------------------------------------------------------------------- #
# 6. Keyword normalization - one subscription = one bill.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Plumber Karachi", "plumber karachi"),
        ("  plumber karachi  ", "plumber karachi"),
        ("plumber   karachi", "plumber karachi"),
        ("PLUMBER\tKARACHI", "plumber karachi"),
        ("", ""),
    ],
)
def test_normalization_folds_case_and_whitespace(raw: str, expected: str) -> None:
    """These all name ONE subscription - and therefore ONE nightly bill. A stray double
    space must not be able to buy a duplicate."""
    assert normalize_keyword(raw) == expected


# --------------------------------------------------------------------------- #
# 7. The workspace adapter.
# --------------------------------------------------------------------------- #
def test_workspace_cols_are_the_pinned_tools_ts_set() -> None:
    extra = build_workspace(build_stats([_row()]), [_row()])
    assert extra.table is not None
    assert extra.table.cols == WORKSPACE_TABLE_COLS == ["Keyword", "Client", "Position", "Change"]


def test_workspace_rows_are_positional_and_carry_the_client_snapshot() -> None:
    extra = build_workspace(build_stats([_row()]), [_row()])
    assert extra.table is not None
    row = extra.table.rows[0]
    assert row[0] == "dental implants karachi"
    assert row[1] == "NorthPeak Dental"  # the snapshot, never the id
    assert row[2] == "3"


def test_an_improvement_renders_an_up_arrow_with_an_ok_tone() -> None:
    extra = build_workspace(build_stats([_row()]), [_row(previous_position=7, latest_position=3)])
    assert extra.table is not None
    assert extra.table.rows[0][3].model_dump() == {"v": "▲ 4", "tone": "ok"}  # type: ignore[union-attr]


def test_a_fall_renders_a_down_arrow_with_a_crit_tone() -> None:
    extra = build_workspace(build_stats([_row()]), [_row(previous_position=9, latest_position=12)])
    assert extra.table is not None
    assert extra.table.rows[0][3].model_dump() == {"v": "▼ 3", "tone": "crit"}  # type: ignore[union-attr]


def test_a_lost_ranking_renders_as_lost_and_crit() -> None:
    extra = build_workspace(build_stats([_row()]), [_row(previous_position=4, latest_position=None)])
    assert extra.table is not None
    assert extra.table.rows[0][3].model_dump() == {"v": "lost", "tone": "crit"}  # type: ignore[union-attr]


def test_an_unranked_position_cell_is_an_em_dash_never_zero() -> None:
    extra = build_workspace(build_stats([_row()]), [_row(latest_position=None)])
    assert extra.table is not None
    assert extra.table.rows[0][2] == "—"


def test_an_empty_book_renders_an_em_dash_average_not_a_perfect_zero() -> None:
    """0.0 in the Avg. position tile would read as better than #1. An empty board must
    say "no data"."""
    extra = build_workspace(build_stats([]), [])
    assert [k.value for k in extra.kpis] == ["0", "—", "0"]


def test_workspace_kpi_labels_are_the_pinned_tools_ts_set() -> None:
    extra = build_workspace(build_stats([_row()]), [_row()])
    assert [k.label for k in extra.kpis] == [
        "Tracked keywords", "Avg. position", "Top-3 keywords"
    ]


def test_workspace_caps_the_table_at_eight_rows() -> None:
    extra = build_workspace(build_stats([_row()]), [_row() for _ in range(20)])
    assert extra.table is not None
    assert len(extra.table.rows) == 8


def test_workspace_primary_and_bullets_match_tools_ts() -> None:
    extra = build_workspace(build_stats([]), [])
    assert extra.primary is not None
    assert extra.primary.model_dump() == {"label": "Add keywords", "icon": "add"}
    assert extra.bullets == [
        "Track keyword positions daily",
        "See ranking history & trends",
        "Group keywords by client & intent",
    ]
