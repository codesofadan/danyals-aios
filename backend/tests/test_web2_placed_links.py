"""The placed-link ledger: detecting a loss, which needs the previous fact kept.

``web2_properties`` has carried ``link_found`` / ``link_rel`` / ``link_checked_at`` since
migration 0028, and those record the LATEST look and nothing else - each re-check
overwrites the last answer. So "this link was live in March; when did we lose it?" had no
answer anywhere in the system, and A8 ("correctly detects a removed link and a link
changed to nofollow") asks for exactly that comparison.

Three behaviours carry the weight, and each is a way the naive version goes wrong:

1. **``unknown`` never overwrites a known state.** An unreachable page is a fact about our
   fetch, not about their link. Without this, one flaky night turns every live link in
   the portfolio into a client-visible loss.
2. **``lost_at`` is stamped on the TRANSITION, once.** Re-stamping nightly makes every
   historical loss look like it happened today and destroys the only evidence of when it
   really went.
3. **``nofollowed`` is its own state, not a flavour of live.** The link is on the page and
   passes nothing; reporting it as live reports authority the client never received.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.modules.web2 import placed_links as pl

pytestmark = pytest.mark.unit

MARCH = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
JUNE = datetime(2026, 6, 1, 12, 0, tzinfo=UTC)
JULY = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "state": "live", "rel": "", "first_seen_at": MARCH,
        "last_checked_at": MARCH, "lost_at": None,
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# Mapping a fetch onto the state vocabulary
# --------------------------------------------------------------------------- #
def test_the_checkers_tri_state_verdict_maps_without_losing_the_middle() -> None:
    """``found`` is deliberately tri-state in the existing checker and stays that way:
    None means nobody looked, which must not become "removed"."""
    assert pl.state_from_check(None, "") == "unknown"
    assert pl.state_from_check(False, "") == "removed"
    assert pl.state_from_check(True, "") == "live"


def test_a_nofollowed_link_is_its_own_state() -> None:
    """It is on the page and it passes nothing. Calling that `live` reports authority the
    client never received."""
    assert pl.state_from_check(True, "nofollow") == "nofollowed"
    assert pl.state_from_check(True, "ugc nofollow") == "nofollowed"
    assert pl.state_from_check(True, "NOFOLLOW") == "nofollowed"
    assert pl.state_from_check(True, "noopener") == "live"


# --------------------------------------------------------------------------- #
# 1. unknown never overwrites
# --------------------------------------------------------------------------- #
def test_an_unreachable_page_keeps_the_last_known_state() -> None:
    """THE failure mode this guards. Without it, one unreachable night reports every
    live link in the portfolio as lost - to the client."""
    transition = pl.observe(_row(state="live"), pl.LinkObservation("unknown"), now=JUNE)

    assert transition.current == "live", "a failed fetch is not a removal"
    assert not transition.newly_lost
    assert transition.fields == {"last_checked_at": JUNE}, (
        "only the check time moves; state, rel and lost_at are untouched"
    )


def test_an_unreachable_page_on_a_never_seen_link_records_unknown_explicitly() -> None:
    """There is no previous state to preserve here, so ``unknown`` is WRITTEN rather than
    left to the column default: a row that says "nobody has successfully looked yet" is a
    link the re-check sweep picks up, and it is legible to whoever reads the table. A
    state that arrived by default is indistinguishable from one nothing decided."""
    transition = pl.observe(None, pl.LinkObservation("unknown"), now=JUNE)
    assert transition.current == "unknown"
    assert not transition.changed
    assert transition.fields["state"] == "unknown"


# --------------------------------------------------------------------------- #
# 2. lost_at is a transition, not a state
# --------------------------------------------------------------------------- #
def test_a_removal_is_stamped_once_and_is_the_alertable_event() -> None:
    transition = pl.observe(_row(state="live"), pl.LinkObservation("removed"), now=JUNE)

    assert transition.newly_lost, "live -> removed is the event a task is raised on"
    assert transition.fields["lost_at"] == JUNE
    assert transition.fields["state"] == "removed"


def test_a_link_that_is_still_gone_is_not_lost_again_tonight() -> None:
    """Alerting on the STATE rather than the transition produces a nightly alert for
    every historical loss until somebody mutes the channel - at which point the next real
    loss is missed too."""
    already_lost = _row(state="removed", lost_at=JUNE)
    transition = pl.observe(already_lost, pl.LinkObservation("removed"), now=JULY)

    assert not transition.newly_lost
    assert "lost_at" not in transition.fields, "the original loss date must not move"


def test_a_link_downgraded_to_nofollow_counts_as_lost() -> None:
    transition = pl.observe(_row(state="live"), pl.LinkObservation("nofollowed", "nofollow"), now=JUNE)
    assert transition.newly_lost
    assert transition.fields["lost_at"] == JUNE
    assert transition.fields["rel"] == "nofollow"


# --------------------------------------------------------------------------- #
# 3. Recovery keeps the link's age
# --------------------------------------------------------------------------- #
def test_a_recovered_link_clears_its_loss_but_keeps_its_original_age() -> None:
    """"Live since March, briefly unreachable in June" is the truth. Resetting
    ``first_seen_at`` would quietly tell a client their oldest link is new."""
    lost = _row(state="removed", first_seen_at=MARCH, lost_at=JUNE)
    transition = pl.observe(lost, pl.LinkObservation("live"), now=JULY)

    assert transition.recovered
    assert transition.fields["lost_at"] is None
    assert "first_seen_at" not in transition.fields, "the original age is preserved"


def test_a_first_sighting_records_when_it_was_first_seen() -> None:
    transition = pl.observe(None, pl.LinkObservation("live"), now=MARCH)
    assert transition.fields["first_seen_at"] == MARCH
    assert transition.fields["state"] == "live"
    assert transition.fields["lost_at"] is None


def test_a_live_link_seen_again_does_not_restamp_its_age() -> None:
    transition = pl.observe(_row(state="live"), pl.LinkObservation("live"), now=JULY)
    assert "first_seen_at" not in transition.fields
    assert transition.fields["last_checked_at"] == JULY
    assert not transition.changed
