"""The provisioning tick - what advances without a human, and what deliberately does not.

The load-bearing claims: an auto-lane signup that fails BLOCKS with a reason instead of
retrying forever, a confirmation email that has not arrived yet is NOT a failure (that
would turn ordinary waiting into noise operators learn to ignore), and nothing here ever
drives a browser through a signup form.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from app.services.web2_provision_tick import decide_auto_signup, decide_verification

pytestmark = pytest.mark.unit

NOW = datetime(2026, 9, 1, 9, 0, tzinfo=UTC)


def _item(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": "pv-1", "platform": "Telegra.ph", "handle": "leedsdrainage",
        "registration_email": "web@leedsdrainage.co.uk",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# The auto lane.
# --------------------------------------------------------------------------- #
def test_a_successful_api_signup_carries_its_credential_to_live() -> None:
    action = decide_auto_signup(
        _item(), signup=lambda _p, _h: ("created", {"access_token": "tok"}, "")
    )
    assert action is not None
    assert action.to_status == "live"
    assert action.credential == {"access_token": "tok"}


def test_a_refused_signup_blocks_with_a_reason_rather_than_retrying_forever() -> None:
    """A blocked signup means the platform refused something only a human can resolve.
    Silently re-attempting each tick would hide that indefinitely."""
    action = decide_auto_signup(
        _item(), signup=lambda _p, _h: ("blocked", {}, "captcha required")
    )
    assert action is not None
    assert action.to_status == "blocked"
    assert "captcha" in action.note


def test_a_signup_that_returns_no_credential_is_never_called_live() -> None:
    """'created' with an empty credential would seal nothing and show green - the exact
    failure the usable-account SQL was written after."""
    action = decide_auto_signup(_item(), signup=lambda _p, _h: ("created", {}, ""))
    assert action is not None
    assert action.to_status == "blocked"


def test_a_guided_platform_is_never_touched_by_the_auto_lane() -> None:
    """Tumblr's own guidelines forbid programmatic account creation. The tick must not
    quietly treat a guided platform as automatable."""
    called: list[str] = []

    def _signup(platform: str, _handle: str) -> tuple[str, dict[str, str], str]:
        called.append(platform)
        return ("created", {"oauth_token": "t"}, "")

    assert decide_auto_signup(_item(platform="Tumblr"), signup=_signup) is None
    assert called == [], "no signup may even be attempted for a guided platform"


# --------------------------------------------------------------------------- #
# The verification watch.
# --------------------------------------------------------------------------- #
def test_a_found_confirmation_email_moves_the_item_on_and_keeps_its_link() -> None:
    action = decide_verification(
        _item(status="awaiting_verification"),
        check=lambda _a, _w: (True, "https://platform.example/confirm/abc"),
        since=NOW,
    )
    assert action is not None
    assert action.to_status == "awaiting_credential"
    assert action.verify_link.endswith("/confirm/abc")


def test_mail_that_has_not_arrived_yet_is_not_a_failure() -> None:
    """Platforms send on their own schedule. Reporting a failure here would make the
    queue cry wolf on every tick until the mail lands."""
    assert decide_verification(
        _item(status="awaiting_verification"), check=lambda _a, _w: (False, ""), since=NOW
    ) is None


def test_a_confirmation_with_no_link_still_moves_on_and_says_so() -> None:
    """Some platforms send a code rather than a link. The operator still needs to know
    the mail arrived."""
    action = decide_verification(
        _item(status="awaiting_verification"), check=lambda _a, _w: (True, ""), since=NOW
    )
    assert action is not None
    assert action.to_status == "awaiting_credential"
    assert "no link" in action.note


# --------------------------------------------------------------------------- #
# The owner decisions this feature must not quietly overturn.
# --------------------------------------------------------------------------- #
def test_the_tick_is_reachable_by_the_worker_but_is_not_scheduled() -> None:
    """Two claims at once, and both are load-bearing.

    REACHABLE: a task the worker cannot resolve fails at call time with a name error,
    so registration is what makes the operator's button do anything at all.

    NOT SCHEDULED: beat is parked by standing owner instruction. Adding a schedule is an
    owner decision, never a side effect of shipping a feature - so this pins the absence
    rather than trusting a future session to remember.
    """
    import workers.tasks.offpage  # noqa: F401 - registers the task
    from workers.celery_app import celery_app

    assert "web2_provision_tick" in celery_app.tasks

    beat = celery_app.conf.beat_schedule or {}
    scheduled = [name for name, entry in beat.items() if "web2" in str(entry.get("task", ""))]
    assert scheduled == [], (
        f"beat is parked by owner instruction; these web2 entries appeared: {scheduled}"
    )
