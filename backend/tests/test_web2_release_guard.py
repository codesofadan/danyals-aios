"""The last check before a property goes live - the rules a schedule cannot hold.

``M05`` A4: *"No two properties publish within the same minute; per-platform daily caps
hold under a 200-post campaign."*

``web2_pacing`` already lays out a lawful schedule. This exists because a schedule is a
plan and A4 is about what happens, and three things pull those apart:

1. a tick releases a BATCH - ten properties for ten clients, each individually lawful,
   all published at 14:03;
2. a retry publishes later than planned, into a minute something else already owns;
3. in this deployment ``scheduled_for`` is NULL by the owner's 2026-08-29 decision, so an
   approved campaign publishes every property at once - the exact footprint §1 names,
   with no schedule to have an opinion.

So the rule has to be an ADMISSION CHECK judged against what has already gone out.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from itertools import pairwise

import pytest

from app.modules.web2 import release_guard as rg

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 18, 14, 0, tzinfo=UTC)


def _published(minutes_ago: int, platform: str = "Ghost", web2_id: str = "w0") -> rg.RecentPublish:
    return rg.RecentPublish(
        web2_id=web2_id, platform=platform,
        published_at=NOW - timedelta(minutes=minutes_ago),
    )


# --------------------------------------------------------------------------- #
# The same-minute rule
# --------------------------------------------------------------------------- #
def test_a_property_holds_when_something_else_published_this_minute() -> None:
    """Not about rate. Two posts a minute apart are the same volume as two in one second;
    what differs is that simultaneous publication across unrelated properties is a machine
    signature no human schedule produces, visible in the platforms' own timestamps."""
    admission = rg.admit(
        web2_id="w1", platform="Blogger", now=NOW, recent=[_published(0, "Ghost")]
    )
    assert not admission.released
    assert "same" in admission.reason or "this minute" in admission.reason
    assert admission.retry_after is not None


def test_a_property_releases_once_the_minute_has_passed() -> None:
    assert rg.admit(
        web2_id="w1", platform="Blogger", now=NOW, recent=[_published(2, "Ghost")]
    ).released


def test_the_rule_is_global_not_per_client_or_per_platform() -> None:
    """Two DIFFERENT clients on two DIFFERENT platforms publishing in one minute is still
    two of our properties appearing simultaneously."""
    other_client = rg.RecentPublish(
        web2_id="w0", platform="Mataroa", published_at=NOW, client_id="other"
    )
    assert not rg.admit(
        web2_id="w1", platform="Blogger", client_id="mine", now=NOW, recent=[other_client]
    ).released


def test_releases_handed_out_in_this_same_tick_also_count() -> None:
    """THE failure the check itself would otherwise reproduce.

    Without this, a batch of ten due properties are each judged against the DATABASE
    alone, all find the last publish was an hour ago, and all release into one minute -
    which is precisely what A4 forbids, caused by the guard meant to prevent it.
    """
    assert not rg.admit(
        web2_id="w2", platform="Blogger", now=NOW, recent=[], already_admitted=[NOW]
    ).released


# --------------------------------------------------------------------------- #
# Per-platform daily caps
# --------------------------------------------------------------------------- #
def test_the_platform_cap_counts_across_every_client() -> None:
    """Deliberately separate from the per-client cap: this bounds how much the agency
    posts to ONE PLATFORM in total, which is the number that platform's own abuse tooling
    can see."""
    recent = [_published(60 + i, "dev.to", f"w{i}") for i in range(10)]
    held = rg.admit(web2_id="new", platform="dev.to", now=NOW, recent=recent, platform_daily_cap=10)

    assert not held.released
    assert "dev.to" in held.reason
    assert held.retry_after is not None and held.retry_after > NOW

    # A different platform is unaffected - the cap is per platform, not global volume.
    assert rg.admit(
        web2_id="new", platform="Ghost", now=NOW, recent=recent, platform_daily_cap=10
    ).released


def test_yesterdays_publishes_do_not_consume_todays_budget() -> None:
    """A calendar day rather than a rolling window, because platform rate accounting is
    almost always daily - a rolling one would hold work at 00:05 for something published
    at 23:55 under a different day's budget."""
    yesterday = [
        rg.RecentPublish(f"w{i}", "dev.to", NOW - timedelta(days=1, minutes=i))
        for i in range(20)
    ]
    assert rg.admit(
        web2_id="new", platform="dev.to", now=NOW, recent=yesterday, platform_daily_cap=10
    ).released


# --------------------------------------------------------------------------- #
# A4 at its stated load
# --------------------------------------------------------------------------- #
def test_a_200_post_campaign_never_puts_two_properties_in_one_minute() -> None:
    """A4, asserted at the size A4 names."""
    platforms = ["Ghost", "Blogger", "dev.to", "Mataroa"]
    rows = [{"id": f"w{i}", "platform": platforms[i % len(platforms)]} for i in range(200)]

    results = rg.admit_batch(rows, now=NOW, recent=[], platform_daily_cap=10)
    released = [a for _, a in results if a.released]
    minutes = {
        (a.retry_after or NOW).replace(second=0, microsecond=0) for a in released
    }

    assert len(minutes) == len(released), "two properties share a minute"
    assert len(released) == 40, "four platforms at a cap of 10 each"


def test_the_daily_cap_holds_across_a_200_post_campaign() -> None:
    platforms = ["Ghost", "Blogger", "dev.to", "Mataroa"]
    rows = [{"id": f"w{i}", "platform": platforms[i % len(platforms)]} for i in range(200)]

    results = dict(rg.admit_batch(rows, now=NOW, recent=[], platform_daily_cap=10))
    per_platform = Counter(
        row["platform"] for row in rows if results[row["id"]].released
    )

    assert set(per_platform) == set(platforms)
    assert all(count == 10 for count in per_platform.values())


def test_everything_over_the_cap_is_held_with_a_reason_not_dropped() -> None:
    rows = [{"id": f"w{i}", "platform": "Ghost"} for i in range(15)]
    results = rg.admit_batch(rows, now=NOW, recent=[], platform_daily_cap=10)

    held = [a for _, a in results if not a.released]
    assert len(held) == 5
    assert all(a.reason for a in held), "a held property must say why"
    assert all(a.retry_after is not None for a in held), "and when to try again"


def test_a_batch_spaces_releases_forward_rather_than_refusing_them() -> None:
    """The first releases now and the rest are spaced - holding nine of ten properties
    because they arrived together would make a campaign take ten ticks to start."""
    rows = [{"id": f"w{i}", "platform": "Ghost"} for i in range(5)]
    results = rg.admit_batch(rows, now=NOW, recent=[], platform_daily_cap=10)

    assert all(a.released for _, a in results)
    times = [a.retry_after or NOW for _, a in results]
    assert times == sorted(times)
    gaps = [(b - a) for a, b in pairwise(times)]
    assert all(gap >= rg.SAME_MINUTE for gap in gaps)


# --------------------------------------------------------------------------- #
# Robustness
# --------------------------------------------------------------------------- #
def test_a_naive_historical_timestamp_is_read_as_utc_rather_than_raising() -> None:
    """The ledger has rows written before the columns were consistently timezone-aware.
    A comparison that raised on one would stop the release tick entirely - and a pacing
    check that halts publishing is a worse failure than one that reads an old row as UTC.
    """
    naive = rg.RecentPublish("w0", "Ghost", datetime(2026, 9, 18, 14, 0))
    admission = rg.admit(web2_id="w1", platform="Ghost", now=NOW, recent=[naive])
    assert not admission.released, "it was still read, and it still clashed"


def test_a_row_with_no_id_is_skipped_rather_than_crashing_the_batch() -> None:
    rows = [{"id": "", "platform": "Ghost"}, {"id": "w1", "platform": "Ghost"}]
    results = rg.admit_batch(rows, now=NOW, recent=[])
    assert [web2_id for web2_id, _ in results] == ["w1"]


def test_a_zero_cap_disables_the_platform_limit_without_disabling_the_minute_rule() -> None:
    recent = [_published(30 + i, "Ghost", f"w{i}") for i in range(50)]
    assert rg.admit(
        web2_id="new", platform="Ghost", now=NOW, recent=recent, platform_daily_cap=0
    ).released
    assert not rg.admit(
        web2_id="new", platform="Ghost", now=NOW, recent=[_published(0)], platform_daily_cap=0
    ).released
