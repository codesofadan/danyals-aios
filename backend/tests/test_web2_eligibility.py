"""Per-client platform eligibility (R2-04 / R2-05).

The distinction under test: `automation_ready` says the PIPELINE can publish somewhere;
eligibility says THIS CLIENT should. Conflating them is what puts a plumber's marketing
article on a developer community - which dev.to's own Content Policy forbids, and which
is simply bad work regardless of policy.

The product consequence, and why the three-state board matters: the whole catalogue stays
visible and every excluded row carries its reason. An operator sees the system's full
reach AND why a platform is not offered for the client in front of them, which is a
better answer than a silently shorter list.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.services.web2_eligibility import (
    eligible_platform_names,
    evaluate_catalog,
    evaluate_platform,
    refuse_reason,
)

pytestmark = pytest.mark.unit


def _row(**over: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": "WordPress.com",
        "platform_enum": "WordPress.com",
        "ownership_tier": "per_client",
        "topical_scope": "agnostic",
        "automation_ready": True,
        "authority_tier": "high",
        "terms_position": "",
    }
    row.update(over)
    return row


# --------------------------------------------------------------------------- #
# The topical rule.
# --------------------------------------------------------------------------- #
def test_an_agnostic_platform_is_eligible_for_any_client() -> None:
    """A genuine branded blog suits every real business, which is why the agnostic set
    is what an unclassified client falls back to rather than an empty board."""
    for scope in ("agnostic", "developer", "research", "creative", "niche"):
        verdict = evaluate_platform(_row(), client_scope=scope, connected=True)
        assert verdict.eligible, scope


def test_a_developer_platform_is_refused_for_a_local_business() -> None:
    verdict = evaluate_platform(
        _row(name="dev.to", platform_enum="dev.to", topical_scope="developer"),
        client_scope="agnostic",
        connected=True,
    )
    assert verdict.status == "not_eligible"
    assert "developer" in verdict.reason


def test_the_same_developer_platform_is_eligible_for_a_developer_client() -> None:
    """The capability is not removed, it is scoped. A dev-tools client legitimately
    unlocks it - that is what makes 'offer the whole catalogue' honest."""
    verdict = evaluate_platform(
        _row(name="dev.to", platform_enum="dev.to", topical_scope="developer"),
        client_scope="developer",
        connected=True,
    )
    assert verdict.eligible


def test_a_do_not_use_platform_reports_its_own_terms_as_the_reason() -> None:
    """The reason must be the platform's stated position, not our verdict restated. An
    operator told 'Medium retired its publish API' learns the rule; one told 'not
    allowed' learns only that the software said no."""
    verdict = evaluate_platform(
        _row(
            name="Medium", platform_enum="Medium", ownership_tier="do_not_use",
            terms_position="Publish API retired; the repository was archived 2023-03-02.",
        ),
        client_scope="agnostic",
        connected=True,
    )
    assert verdict.status == "not_eligible"
    assert "archived" in verdict.reason


def test_an_unreviewed_do_not_use_row_is_not_reviewed_never_a_policy_verdict() -> None:
    """72 of 90 catalogue rows sit at the migration DEFAULT tier with no terms review.
    Presenting that default as 'its own terms make a placement indefensible' fabricates
    a judgement nobody made - the board must say 'nobody has looked' instead."""
    verdict = evaluate_platform(
        _row(name="Plurk", platform_enum="Plurk", ownership_tier="do_not_use"),
        client_scope="agnostic",
        connected=True,
    )
    assert verdict.status == "not_reviewed"
    assert "not yet reviewed" in verdict.reason.lower()
    assert "indefensible" not in verdict.reason


def test_a_reviewed_do_not_use_row_without_terms_text_still_reads_as_a_verdict() -> None:
    """`terms_checked_on` alone marks the row adjudicated (0103 stamps it on every
    reviewed row), so the generic exclusion is honest there."""
    import datetime

    verdict = evaluate_platform(
        _row(
            name="Write.as", platform_enum="Write.as", ownership_tier="do_not_use",
            terms_checked_on=datetime.date(2026, 8, 23),
        ),
        client_scope="agnostic",
        connected=True,
    )
    assert verdict.status == "not_eligible"
    assert verdict.terms_checked_on == "2026-08-23"


# --------------------------------------------------------------------------- #
# The three states are genuinely distinct.
# --------------------------------------------------------------------------- #
def test_not_connected_is_distinct_from_not_eligible() -> None:
    """A missing credential is a ten-minute fix; ineligibility is a judgement no
    credential changes. Collapsing them would send an operator hunting for a token that
    could not help."""
    missing = evaluate_platform(_row(), client_scope="agnostic", connected=False)
    assert missing.status == "not_connected"
    assert "no account is connected" in missing.reason

    barred = evaluate_platform(
        _row(topical_scope="developer"), client_scope="agnostic", connected=True
    )
    assert barred.status == "not_eligible"


def test_eligibility_is_judged_before_connectivity() -> None:
    """Holding a token for a platform this client must not use is not a reason to offer
    it, and calling it merely unconnected invites fixing the wrong thing."""
    verdict = evaluate_platform(
        _row(topical_scope="developer"), client_scope="agnostic", connected=False
    )
    assert verdict.status == "not_eligible"


# --------------------------------------------------------------------------- #
# The catalogue/enum mapping trap (R2-04).
# --------------------------------------------------------------------------- #
def test_a_row_with_no_enum_mapping_is_never_offered() -> None:
    """`web2_platforms.name` is free text and 90 rows map onto 54 enum labels. A row the
    pipeline cannot NAME would fail at plan time, so offering it would queue work that
    can only fail."""
    verdict = evaluate_platform(
        _row(name="Mastodon (mas.to)", platform_enum=None), client_scope="agnostic", connected=True
    )
    assert verdict.status == "not_supported"
    assert "publishing-enum" in verdict.reason


def test_a_catalogued_build_target_without_a_publisher_is_not_offered() -> None:
    verdict = evaluate_platform(
        _row(name="Wix", platform_enum=None, automation_ready=False),
        client_scope="agnostic", connected=True,
    )
    assert verdict.status == "not_supported"
    assert "build target" in verdict.reason


# --------------------------------------------------------------------------- #
# Board + planner helpers.
# --------------------------------------------------------------------------- #
def test_the_board_keeps_every_row_and_preserves_order() -> None:
    """Nothing is hidden - the operator sees the system's full reach, with reasons."""
    rows = [
        _row(),
        _row(name="dev.to", platform_enum="dev.to", topical_scope="developer"),
        _row(
            name="Medium", platform_enum="Medium", ownership_tier="do_not_use",
            terms_position="Publish API retired.",
        ),
        _row(name="Plurk", platform_enum="Plurk", ownership_tier="do_not_use"),
    ]
    board = evaluate_catalog(rows, client_scope="agnostic", connected_platforms={"WordPress.com"})
    assert [v.name for v in board] == ["WordPress.com", "dev.to", "Medium", "Plurk"]
    assert [v.status for v in board] == ["eligible", "not_eligible", "not_eligible", "not_reviewed"]


def test_only_connected_eligible_platforms_are_campaign_targets() -> None:
    """A platform with no account cannot publish, so listing it as a target would queue
    work that can only hold at review."""
    rows = [_row(), _row(name="Blogger", platform_enum="Blogger")]
    board = evaluate_catalog(rows, client_scope="agnostic", connected_platforms={"WordPress.com"})
    assert eligible_platform_names(board) == ["WordPress.com"]


def test_refuse_reason_explains_an_ineligible_target_and_is_empty_for_a_good_one() -> None:
    board = evaluate_catalog(
        [_row(), _row(name="dev.to", platform_enum="dev.to", topical_scope="developer")],
        client_scope="agnostic",
        connected_platforms={"WordPress.com", "dev.to"},
    )
    assert refuse_reason(board, "WordPress.com") == ""
    assert "developer" in refuse_reason(board, "dev.to")


def test_an_unknown_platform_is_refused_by_name() -> None:
    assert "not in the platform catalogue" in refuse_reason([], "NotAPlatform")
