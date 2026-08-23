"""The rank tracker's depth and its price model - the platform's largest line item.

Two defects lived here together, and each hid the other:

  * `DEFAULT_DEPTH = 100` and `settings.rank_tracker_depth = 100`. Both vendors bill
    per 10-result page, so every scheduled rank check cost **5x** what a depth-20 check
    costs, to learn positions (87th, 94th) that nobody acts on.
  * `_dfs_cost` used `ceil(depth/100)` - DataForSEO's model from BEFORE 19 September
    2025, when the base price of Organic SERP endpoints covered 100 results. After that
    date it covers 10. So the tracker **under-reported** the overspend by 10x: the
    ledger showed one unit where the vendor billed ten.

Together those produced a specific trap. Reading the two cost functions and comparing
their output made Serper look ~10x more expensive than DataForSEO for identical data,
which is an argument for switching vendor. It was an artifact of comparing a correct
function against a stale one. Once `_dfs_cost` is right the two vendors price the
same per page, and the real saving is depth, not vendor. That is asserted below so the
wrong conclusion cannot be re-derived from the code.

Sourced from R5 §3.2, which verified the 19-September-2025 change and its price table
at DataForSEO's own help centre.
"""

from __future__ import annotations

import pytest

from app.config import get_settings
from app.modules.rank_tracker.provider import DEFAULT_DEPTH, _dfs_cost, _serper_cost

pytestmark = pytest.mark.unit

#: Above this, a position is not commercially meaningful and costs multiply.
_MAX_TRACKING_DEPTH = 20
_BASE = 0.003


# --------------------------------------------------------------------------- #
# Depth - and both of its sources of truth
# --------------------------------------------------------------------------- #
def test_the_tracking_window_is_commercially_meaningful() -> None:
    assert DEFAULT_DEPTH <= _MAX_TRACKING_DEPTH, (
        f"DEFAULT_DEPTH={DEFAULT_DEPTH} costs {DEFAULT_DEPTH // 10}x a depth-10 read on "
        "the platform's largest line item, to learn positions nobody acts on"
    )


def test_the_setting_and_the_constant_agree() -> None:
    """The live path reads the SETTING, not the constant.

    `tasks.py:149` and `router.py:127/147` pass `settings.rank_tracker_depth`. Fixing
    `DEFAULT_DEPTH` alone would leave every scheduled check still reading depth 100 -
    the defect would look fixed in the module and be untouched in production.
    """
    assert int(get_settings().rank_tracker_depth) == DEFAULT_DEPTH


# --------------------------------------------------------------------------- #
# The price model
# --------------------------------------------------------------------------- #
def test_dataforseo_organic_is_priced_per_ten_results() -> None:
    """The post-19-September-2025 model. `ceil(depth/100)` was the old one."""
    assert _dfs_cost(_BASE, 10) == pytest.approx(_BASE * 1)
    assert _dfs_cost(_BASE, 20) == pytest.approx(_BASE * 2)
    assert _dfs_cost(_BASE, 100) == pytest.approx(_BASE * 10)


def test_serper_is_priced_per_ten_results() -> None:
    assert _serper_cost(_BASE, 10) == pytest.approx(_BASE * 1)
    assert _serper_cost(_BASE, 20) == pytest.approx(_BASE * 2)
    assert _serper_cost(_BASE, 100) == pytest.approx(_BASE * 10)


@pytest.mark.parametrize("depth", [1, 5, 10, 11, 20, 50, 100, 137])
def test_the_two_vendors_price_organic_identically(depth: int) -> None:
    """The assertion that stops a wrong conclusion being re-derived.

    While `_dfs_cost` was stale, comparing the two functions made Serper look ~10x
    more expensive for identical data - a compelling case for a vendor switch that
    was really just one function being wrong. Both bill per 10-result page, so for
    ORGANIC they cost the same. Vendor choice (D-6) rests on SLA, quota and coverage,
    never on this comparison.
    """
    assert _dfs_cost(_BASE, depth) == pytest.approx(_serper_cost(_BASE, depth))


def test_depth_one_hundred_costs_five_times_depth_twenty() -> None:
    """The saving this change actually banks, on either vendor."""
    for price in (_serper_cost, _dfs_cost):
        assert price(_BASE, 100) == pytest.approx(price(_BASE, 20) * 5)


@pytest.mark.parametrize("depth", [0, -1, -100])
def test_a_nonsense_depth_still_bills_at_least_one_page(depth: int) -> None:
    """Never zero: a check that ran must never price as free."""
    assert _dfs_cost(_BASE, depth) == pytest.approx(_BASE)
    assert _serper_cost(_BASE, depth) == pytest.approx(_BASE)


def test_the_monthly_shape_of_the_change() -> None:
    """What this is worth, stated as the arithmetic rather than a claim.

    R5's model: 100 clients x 20 keywords, checked weekly = 8,000 checks/month.
    """
    checks = 100 * 20 * 4
    before = _serper_cost(_BASE, 100) * checks
    after = _serper_cost(_BASE, 20) * checks
    assert before == pytest.approx(240.0)
    assert after == pytest.approx(48.0)
    assert before - after == pytest.approx(192.0)
