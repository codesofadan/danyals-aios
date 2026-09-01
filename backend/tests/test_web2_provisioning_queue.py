"""The account provisioning queue (0123) - lanes, transitions, readiness.

WHAT IS ACTUALLY UNDER TEST. Not "does a row save", but the three claims that make the
queue safe to run across twenty clients: a lane is never claimed for a platform the code
cannot drive, a handle is never generated (R2-08's footprint rule), and a status can
never jump a step that had real work in it.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.web2_provisioning_queue import (
    IdentityFacts,
    TransitionRefusedError,
    handle_for,
    lane_for,
    next_status,
    plan_items,
    readiness_for,
)

pytestmark = pytest.mark.unit

FULL = IdentityFacts(
    handle_base="Leeds Drainage Co", contact_email="web@leedsdrainage.co.uk", mailbox_ready=True
)


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"platform": "Blogger", "status": "identity_ready"}
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# Lanes describe the code that exists, not the code we wish existed.
# --------------------------------------------------------------------------- #
def test_only_platforms_with_a_real_api_signup_get_the_auto_lane() -> None:
    """Claiming `auto` for a platform `api_signup_provider_for` cannot drive would park
    the item in awaiting_account forever while the board reported it automatic."""
    assert lane_for("Telegra.ph") == "auto"
    assert lane_for("Write.as") == "auto"
    for guided in ("WordPress.com", "Blogger", "Tumblr", "dev.to", "GitHub Pages"):
        assert lane_for(guided) == "guided", guided


# --------------------------------------------------------------------------- #
# The handle rule (R2-08) - the footprint no content check can see.
# --------------------------------------------------------------------------- #
def test_a_handle_comes_from_the_brand_and_carries_no_platform_or_hash_tell() -> None:
    handle = handle_for("Blogger", FULL)
    assert handle == "leedsdrainageco"
    assert "blogger" not in handle, "a platform slug lets one suspension find the rest"
    assert not any(c.isdigit() for c in handle), "no client-id hash run"


def test_no_brand_stem_means_no_handle_rather_than_an_invented_one() -> None:
    """The absence is reported as a blocker. Generating one here is exactly how every
    account across every client ends up sharing two joinable keys."""
    assert handle_for("Blogger", IdentityFacts(contact_email="a@b.com")) == ""
    check = readiness_for("Blogger", IdentityFacts(contact_email="a@b.com"))
    assert not check.ready
    assert "handle base" in check.reason


def test_a_missing_client_email_blocks_with_the_reason_named() -> None:
    check = readiness_for("Blogger", IdentityFacts(handle_base="acme"))
    assert not check.ready
    assert "client" in check.reason.lower() and "domain" in check.reason.lower()


def test_a_complete_identity_is_ready() -> None:
    assert readiness_for("Blogger", FULL).ready


# --------------------------------------------------------------------------- #
# Transitions: a step with real work in it cannot be skipped.
# --------------------------------------------------------------------------- #
def test_an_item_cannot_reach_live_without_a_credential_step() -> None:
    """`live` means a credential is sealed and an account row exists. Jumping there from
    'the account was created' would leave the accounts board green with nothing behind
    it - the exact failure `_USABLE_ACCOUNT_FROM` was written after measuring."""
    with pytest.raises(TransitionRefusedError) as refused:
        next_status("awaiting_account", "live")
    assert "awaiting_account" in str(refused.value)
    assert "awaiting_credential" in str(refused.value), "the refusal names what IS allowed"

    assert next_status("awaiting_account", "awaiting_credential") == "awaiting_credential"
    assert next_status("awaiting_credential", "live") == "live"


def test_verification_may_be_skipped_because_some_platforms_send_no_mail() -> None:
    assert next_status("awaiting_account", "awaiting_credential") == "awaiting_credential"


def test_a_live_account_can_fall_back_into_the_queue_when_it_breaks() -> None:
    """A revoked token has to become visible work again rather than a silent failure."""
    assert next_status("live", "blocked") == "blocked"


def test_a_cancelled_item_is_terminal() -> None:
    with pytest.raises(TransitionRefusedError):
        next_status("cancelled", "queued")


def test_anything_may_be_cancelled() -> None:
    for state in ("queued", "identity_ready", "awaiting_account", "awaiting_credential", "live"):
        assert next_status(state, "cancelled") == "cancelled"


# --------------------------------------------------------------------------- #
# Planning a run.
# --------------------------------------------------------------------------- #
def test_planning_assigns_lanes_and_snapshots_the_identity() -> None:
    plan = plan_items(["Telegra.ph", "Blogger"], identity=FULL)
    by_platform = {p["platform"]: p for p in plan}
    assert by_platform["Telegra.ph"]["lane"] == "auto"
    assert by_platform["Blogger"]["lane"] == "guided"
    assert by_platform["Blogger"]["handle"] == "leedsdrainageco"
    assert by_platform["Blogger"]["registration_email"] == "web@leedsdrainage.co.uk"
    assert all(p["status"] == "identity_ready" for p in plan)


def test_re_running_the_builder_reports_what_is_already_in_flight() -> None:
    """The partial unique index would refuse a duplicate anyway; an operator re-running
    the builder should read 'already queued', not an error."""
    plan = plan_items(
        ["Blogger", "Tumblr"], identity=FULL, existing=[_row(platform="Blogger")]
    )
    by_platform = {p["platform"]: p for p in plan}
    assert by_platform["Blogger"]["action"] == "skipped"
    assert "already" in by_platform["Blogger"]["note"]
    assert by_platform["Tumblr"]["action"] == "queued"


def test_a_cancelled_attempt_does_not_block_a_retry() -> None:
    plan = plan_items(
        ["Blogger"], identity=FULL, existing=[_row(platform="Blogger", status="cancelled")]
    )
    assert plan[0]["action"] == "queued"


def test_an_incomplete_identity_queues_the_item_blocked_with_the_reason() -> None:
    """Queued-and-blocked beats refusing the whole run: the operator sees the full list
    of what they asked for, with the one missing prerequisite named once."""
    plan = plan_items(["Blogger"], identity=IdentityFacts())
    assert plan[0]["status"] == "blocked"
    assert plan[0]["note"]
