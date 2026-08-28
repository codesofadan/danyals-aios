"""Publish pacing (R2-13) - the control that stops a campaign looking manufactured.

The similarity gate stops two properties looking alike. This stops the whole SET looking
like a burst, which is a different tell and one no content check can see: thirty articles
across a client's properties in an afternoon reads as machinery regardless of how good
each article is.

The load-bearing test here is
``test_a_campaign_is_spread_rather_than_stacked_on_one_slot``. Scheduling every property
against the same starting ledger is the obvious implementation, and it would hand all
thirty the identical "earliest" slot and publish them together - producing exactly the
burst the caps exist to prevent, while appearing to enforce them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.services.web2_pacing import (
    PacingCaps,
    Placement,
    earliest_slot,
    projected_completion,
    schedule_campaign,
)

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)
CLIENT = "cl-1"
# Jitter off in most tests: it is a real anti-pattern control (tested on its own), but
# leaving it on would blur every interval assertion by up to 36 hours.
NO_JITTER = PacingCaps(publish_jitter_max_hours=0)


def _slot(**over: object) -> datetime:
    kwargs: dict[str, object] = {
        "now": NOW, "caps": NO_JITTER, "client_id": CLIENT, "platform": "Blogger",
        "web2_id": "w2-1", "apply_jitter": False,
    }
    kwargs.update(over)
    return earliest_slot(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# THE campaign property.
# --------------------------------------------------------------------------- #
def test_a_campaign_is_spread_rather_than_stacked_on_one_slot() -> None:
    """Each placement must be folded into the ledger before the next is scheduled."""
    props = [(f"w2-{i}", "Blogger") for i in range(5)]
    schedule = schedule_campaign(now=NOW, caps=NO_JITTER, client_id=CLIENT, properties=props)
    slots = [s for _id, s in schedule]
    assert len(set(slots)) == len(slots), "every property landed on the same slot"
    assert slots == sorted(slots)
    # One publish per client per day: five properties cannot fit inside five hours.
    assert (slots[-1] - slots[0]) >= timedelta(days=4)


def test_spreading_a_campaign_across_platforms_is_dramatically_faster() -> None:
    """A measured product fact, not a preference - and the reason the wizard must show a
    completion date rather than a vague "it drips".

    Thirty properties on ONE platform are governed by the 72-hour same-client-same-
    platform rule, so they take roughly three months. The same thirty spread across
    several platforms fall back to the 24-hour any-platform rule and finish in about a
    month. Platform diversity is therefore both the faster route AND the safer one (a
    client whose every property sits on one host is a thinner disguise), which is a
    genuinely nice property: the incentive points the right way.
    """
    one_platform = schedule_campaign(
        now=NOW, caps=NO_JITTER, client_id=CLIENT,
        properties=[(f"w2-{i}", "Blogger") for i in range(30)],
    )
    platforms = ["Blogger", "WordPress.com", "Tumblr", "Telegra.ph", "Micro.blog"]
    spread = schedule_campaign(
        now=NOW, caps=NO_JITTER, client_id=CLIENT,
        properties=[(f"w2-{i}", platforms[i % len(platforms)]) for i in range(30)],
    )
    single_days = (projected_completion(one_platform) - NOW).days  # type: ignore[operator]
    spread_days = (projected_completion(spread) - NOW).days  # type: ignore[operator]

    assert single_days > 80, "one platform is governed by the 72h rule"
    assert 28 <= spread_days <= 40, "spread across platforms falls back to the 24h rule"
    assert spread_days < single_days / 2


# --------------------------------------------------------------------------- #
# The individual intervals.
# --------------------------------------------------------------------------- #
def test_the_same_property_waits_a_week() -> None:
    prior = Placement(published_at=NOW, web2_id="w2-1", client_id=CLIENT, platform="Blogger")
    assert _slot(history=[prior]) >= NOW + timedelta(days=7)


def test_the_same_client_on_the_same_platform_waits_72_hours() -> None:
    prior = Placement(published_at=NOW, web2_id="w2-other", client_id=CLIENT, platform="Blogger")
    assert _slot(history=[prior]) >= NOW + timedelta(hours=72)


def test_the_same_client_on_a_different_platform_still_waits_24_hours() -> None:
    prior = Placement(
        published_at=NOW, web2_id="w2-other", client_id=CLIENT, platform="WordPress.com"
    )
    got = _slot(history=[prior])
    assert got >= NOW + timedelta(hours=24)
    assert got < NOW + timedelta(hours=72)  # the platform rule does not apply here


def test_another_client_never_delays_this_one() -> None:
    """Pacing protects each client's own footprint; coupling unrelated clients would
    make the agency's throughput a function of its client count for no safety gain."""
    prior = Placement(published_at=NOW, web2_id="w2-x", client_id="cl-other", platform="Blogger")
    assert _slot(history=[prior]) == NOW


def test_an_empty_history_publishes_immediately() -> None:
    assert _slot() == NOW


# --------------------------------------------------------------------------- #
# House-account ceilings: a shared resource with a shared blast radius.
# --------------------------------------------------------------------------- #
def test_a_house_account_at_its_daily_limit_rolls_to_the_next_day() -> None:
    """Keyed on the ACCOUNT, not the client: a suspension there costs every client on it,
    so the meter has to be the shared thing."""
    history = [
        Placement(
            published_at=NOW + timedelta(minutes=i), web2_id=f"w2-h{i}", client_id=f"cl-{i}",
            platform="Telegra.ph", account_id="acct-house", ownership="house",
        )
        for i in range(3)  # already at max_publishes_per_house_account_day
    ]
    got = _slot(
        platform="Telegra.ph", account_id="acct-house", ownership="house", history=history,
    )
    assert got.date() > NOW.date()


def test_a_per_client_account_is_not_bound_by_house_ceilings() -> None:
    # Other clients only - `CLIENT` must not appear here or the same-client rules apply
    # and the test would pass for the wrong reason.
    history = [
        Placement(
            published_at=NOW + timedelta(minutes=i), web2_id=f"w2-h{i}", client_id=f"cl-other-{i}",
            platform="Blogger", account_id="acct-a", ownership="house",
        )
        for i in range(5)
    ]
    got = _slot(platform="Tumblr", account_id="acct-mine", ownership="per_client", history=history)
    assert got == NOW


# --------------------------------------------------------------------------- #
# Jitter and caps hygiene.
# --------------------------------------------------------------------------- #
def test_jitter_varies_between_properties_but_is_stable_for_one() -> None:
    """Publishing every property at exactly the scheduled minute is itself a machine
    signature. Stable per property so a redraft does not shuffle a communicated date."""
    caps = PacingCaps(publish_jitter_max_hours=36)
    a1 = earliest_slot(now=NOW, caps=caps, client_id=CLIENT, platform="Blogger", web2_id="w2-1")
    a2 = earliest_slot(now=NOW, caps=caps, client_id=CLIENT, platform="Blogger", web2_id="w2-1")
    b = earliest_slot(now=NOW, caps=caps, client_id=CLIENT, platform="Blogger", web2_id="w2-2")
    assert a1 == a2
    assert a1 != b
    assert NOW <= a1 <= NOW + timedelta(hours=36)


def test_a_missing_settings_row_falls_back_to_the_conservative_defaults() -> None:
    """A failed read must never mean 'no limits' - that turns an outage into an
    uncapped burst, the worst possible way for this to fail."""
    caps = PacingCaps.from_row(None)
    assert caps.max_publishes_per_client_per_day == 1
    assert caps.min_interval_same_property_days == 7


def test_settings_override_the_defaults_and_partial_rows_keep_the_rest() -> None:
    caps = PacingCaps.from_row({"max_publishes_per_client_per_day": 3})
    assert caps.max_publishes_per_client_per_day == 3
    assert caps.min_interval_same_client_h == 24  # untouched


def test_loosened_caps_genuinely_compress_the_schedule() -> None:
    """The operator's choice is real: relaxing the caps really does pack the campaign
    tighter. The system's job is to make the trade-off visible, not to refuse it."""
    props = [(f"w2-{i}", "Blogger") for i in range(5)]
    tight = schedule_campaign(now=NOW, caps=NO_JITTER, client_id=CLIENT, properties=props)
    loose = schedule_campaign(
        now=NOW,
        caps=PacingCaps(
            publish_jitter_max_hours=0, max_publishes_per_client_per_day=10,
            min_interval_same_client_h=1, min_interval_same_client_platform_h=1,
            min_interval_same_property_days=1,
        ),
        client_id=CLIENT,
        properties=props,
    )
    assert projected_completion(loose) < projected_completion(tight)  # type: ignore[operator]
