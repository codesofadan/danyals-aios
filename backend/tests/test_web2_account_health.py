"""Whether an account may publish - the two controls that existed on paper only.

``M05`` §1: *"Keep publishing to a limited account and you lose it. We stop."* and §4's
per-house-account property cap, "because a platform that can link 40 unrelated local
businesses to one account has been handed the exact pattern it polices".

Both were declared and neither bound:

* the publish path refused ``suspended`` and ``deleted`` but published through
  ``degraded`` exactly as if it were healthy - so the one state that is an EARLY WARNING
  was the one state nothing acted on;
* ``property_count`` is declared in migration 0100, read by the repo and rendered on the
  account board, and was incremented **nowhere in the codebase**. Every account read
  0/10 forever, so A6 was unenforceable rather than merely unenforced.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.modules.web2 import account_health as ah

pytestmark = pytest.mark.unit


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "acc-1", "platform": "Blogger", "ownership": "house",
        "health": "active", "property_count": 0, "max_properties": 10,
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# Health
# --------------------------------------------------------------------------- #
def test_a_healthy_account_below_its_cap_may_publish() -> None:
    verdict = ah.evaluate(_row())
    assert verdict.publishable
    assert verdict.verdict == "ok"
    assert verdict.headroom == 10


def test_a_degraded_account_is_removed_from_scheduling_and_raises_a_task() -> None:
    """THE regression this module exists for.

    ``degraded`` means rate-limited or failing publishes - the state that exists so we
    can stop BEFORE the platform escalates to a suspension nobody can undo. The publish
    path checked only the two terminal states, so this one published normally right up
    until the account was gone.
    """
    verdict = ah.evaluate(_row(health="degraded"))

    assert not verdict.publishable
    assert verdict.verdict == "degraded"
    assert verdict.raises_task, "REQ-W2-013: it raises a task, it does not silently drop posts"


@pytest.mark.parametrize("health", ["suspended", "deleted"])
def test_a_lost_account_never_publishes_and_raises_a_task(health: str) -> None:
    verdict = ah.evaluate(_row(health=health))
    assert not verdict.publishable
    assert verdict.verdict == "suspended"
    assert verdict.raises_task


def test_an_unverified_account_does_not_publish_but_is_not_an_incident() -> None:
    """"Nothing is known about this account" is a setup gap, not a failure - it needs a
    credential check, not an alert competing with real incidents."""
    verdict = ah.evaluate(_row(health="unverified"))
    assert not verdict.publishable
    assert verdict.verdict == "unverified"
    assert not verdict.raises_task


def test_an_unknown_health_value_fails_closed() -> None:
    """The cost of being wrong here is asymmetric: a held placement is released by an
    operator in seconds; a suspended account takes every property on it."""
    for value in ("limited", "", None, "ACTIVE-ish"):
        verdict = ah.evaluate(_row(health=value))
        assert not verdict.publishable, f"{value!r} must not publish"
    assert ah.evaluate(None).verdict == "unknown"


def test_publishable_health_is_an_allow_list_not_a_deny_list() -> None:
    """A deny-list makes every FUTURE state publishable by default, which is the wrong
    default for a control whose failure mode is losing a client's account."""
    assert frozenset({"active"}) == ah.PUBLISHABLE_HEALTH
    assert ah.PUBLISHABLE_HEALTH < ah.KNOWN_HEALTH


def test_every_known_health_state_has_a_decided_meaning() -> None:
    """A state added to the enum without a decision about what it means for publishing
    must fail here rather than fall into whichever branch happens to catch it."""
    for state in ah.KNOWN_HEALTH:
        verdict = ah.evaluate(_row(health=state))
        assert verdict.verdict != "unknown", f"{state} has no decided meaning"


# --------------------------------------------------------------------------- #
# The property cap
# --------------------------------------------------------------------------- #
def test_an_account_at_its_cap_refuses_another_property() -> None:
    verdict = ah.evaluate(_row(property_count=10, max_properties=10))
    assert not verdict.publishable
    assert verdict.verdict == "capped"
    assert verdict.headroom == 0
    assert not verdict.raises_task, "a full account is planning information, not an incident"


def test_the_cap_is_a_hard_stop_not_a_warning_at_the_boundary() -> None:
    assert ah.evaluate(_row(property_count=9, max_properties=10)).publishable
    assert not ah.evaluate(_row(property_count=10, max_properties=10)).publishable
    assert not ah.evaluate(_row(property_count=11, max_properties=10)).publishable


def test_health_is_reported_before_the_cap() -> None:
    """An account that is both suspended and full must report the problem that planning
    cannot fix, because the two send an operator to completely different actions."""
    verdict = ah.evaluate(_row(health="suspended", property_count=99, max_properties=10))
    assert verdict.verdict == "suspended"


def test_a_missing_or_unreadable_count_does_not_crash_the_verdict() -> None:
    assert ah.evaluate(_row(property_count=None, max_properties=None)).publishable
    assert ah.evaluate(_row(property_count="many")).publishable


# --------------------------------------------------------------------------- #
# Planning
# --------------------------------------------------------------------------- #
def test_selectable_filters_a_planner_down_to_accounts_that_will_accept_work() -> None:
    """Planning onto an account that refuses at publish time means a campaign silently
    delivers less than was approved - discovered thirty drafts later."""
    rows = [
        _row(id="ok"),
        _row(id="degraded", health="degraded"),
        _row(id="full", property_count=10, max_properties=10),
        _row(id="gone", health="suspended"),
    ]
    assert [r["id"] for r in ah.selectable(rows)] == ["ok"]
