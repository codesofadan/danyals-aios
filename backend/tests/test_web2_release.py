"""The release tick - publishing approved properties when their slot comes due.

The load-bearing test is ``test_a_tick_finding_several_due_rows_does_not_release_them_all``.
Releasing every due row is the obvious implementation and it converts a carefully paced
campaign into a burst at exactly the moment the caps were supposed to bite: the schedule
would be correct on paper and the publishing would be a spike.

The second property worth pinning is that a due row whose caps have since been breached
is DEFERRED rather than published anyway. A schedule laid out three weeks ago cannot know
what happened since - another campaign, a manual placement, a retry - so the caps are
re-checked at release, and the safe direction (later, never sooner) is the one taken.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from app.services.web2_pacing import PacingCaps, Placement
from app.services.web2_release import MAX_TICK_INTERVAL, plan_release

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
CAPS = PacingCaps(publish_jitter_max_hours=0)


def _due(web2_id: str, **over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": web2_id, "client_id": "cl-1", "platform": "Blogger",
        "status": "publishing", "account_id": None, "ownership": "per_client",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# THE burst guard.
# --------------------------------------------------------------------------- #
def test_a_tick_finding_several_due_rows_does_not_release_them_all() -> None:
    """Each release must be folded into the ledger before the next row is judged, or the
    per-client daily cap only applies to history and never within the tick itself."""
    plan = plan_release(
        now=NOW, caps=CAPS, due_rows=[_due(f"w2-{i}") for i in range(5)]
    )
    assert len(plan.released) == 1, "the per-client daily cap must bite inside the tick"
    assert len(plan.deferred) == 4


def test_properties_for_different_clients_release_together() -> None:
    """The caps are per client; coupling unrelated clients would make one agency's
    throughput a function of its client count for no safety gain."""
    rows = [_due(f"w2-{i}", client_id=f"cl-{i}") for i in range(4)]
    plan = plan_release(now=NOW, caps=CAPS, due_rows=rows)
    assert len(plan.released) == 4


# --------------------------------------------------------------------------- #
# Re-checking at release, not just at planning.
# --------------------------------------------------------------------------- #
def test_a_due_row_whose_caps_have_since_been_breached_is_deferred_not_published() -> None:
    history = [
        Placement(
            published_at=NOW - timedelta(hours=1), web2_id="w2-earlier", client_id="cl-1",
            platform="Blogger",
        )
    ]
    plan = plan_release(now=NOW, caps=CAPS, due_rows=[_due("w2-1")], history=history)
    assert plan.released == []
    assert plan.deferred == ["w2-1"]
    decision = plan.decisions[0]
    assert decision.defer_until is not None and decision.defer_until > NOW


def test_deferring_moves_the_slot_forward_rather_than_dropping_the_property() -> None:
    """A deferred property is still going out - the worst case is 'later than planned',
    which is invisible to everyone except the schedule."""
    history = [
        Placement(
            published_at=NOW, web2_id="w2-earlier", client_id="cl-1", platform="Blogger"
        )
    ]
    plan = plan_release(now=NOW, caps=CAPS, due_rows=[_due("w2-1")], history=history)
    assert plan.decisions[0].action == "defer"
    assert plan.decisions[0].defer_until >= NOW + timedelta(hours=24)  # type: ignore[operator]


# --------------------------------------------------------------------------- #
# Only approved rows are ours.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("status", ["needs_review", "draft", "published", "rejected", "failed"])
def test_only_a_row_in_publishing_is_released(status: str) -> None:
    """Approval is what moves a row to `publishing`. Releasing anything else would
    publish something a human never approved - the one thing this module must never do."""
    plan = plan_release(now=NOW, caps=CAPS, due_rows=[_due("w2-1", status=status)])
    assert plan.released == []
    assert plan.decisions[0].action == "skip"
    assert status in plan.decisions[0].reason


def test_a_row_with_no_id_is_ignored_rather_than_crashing_the_tick() -> None:
    plan = plan_release(now=NOW, caps=CAPS, due_rows=[{"status": "publishing"}])
    assert plan.decisions == []


# --------------------------------------------------------------------------- #
# Re-arming.
# --------------------------------------------------------------------------- #
def test_the_tick_rearms_for_the_soonest_remaining_work() -> None:
    plan = plan_release(
        now=NOW, caps=CAPS, due_rows=[], upcoming=[NOW + timedelta(minutes=30)]
    )
    assert plan.next_tick_at == NOW + timedelta(minutes=30)


def test_the_tick_never_sleeps_longer_than_an_hour() -> None:
    """Not a latency choice, a durability one: a multi-day ETA parked on the broker is a
    message a restart can lose under acks_late. The chain re-arms hourly and re-derives
    the real due time from the DB, so the DATABASE is the schedule and the message is
    only a nudge."""
    plan = plan_release(now=NOW, caps=CAPS, due_rows=[], upcoming=[NOW + timedelta(days=9)])
    assert plan.next_tick_at == NOW + MAX_TICK_INTERVAL


def test_a_burst_of_deferrals_cannot_spin_the_tick_into_a_hot_loop() -> None:
    plan = plan_release(
        now=NOW, caps=CAPS, due_rows=[], upcoming=[NOW - timedelta(hours=5)]
    )
    assert plan.next_tick_at is not None
    assert plan.next_tick_at >= NOW + timedelta(minutes=1)


def test_a_campaign_with_nothing_left_stops_ticking() -> None:
    """The chain has to END, or every finished campaign leaves a timer running forever."""
    plan = plan_release(now=NOW, caps=CAPS, due_rows=[], upcoming=[])
    assert plan.next_tick_at is None
