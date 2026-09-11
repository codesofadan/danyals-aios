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
    resolve_selection,
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


# --------------------------------------------------------------------------- #
# Platform freedom: the operator chooses, with the platform's own rule quoted.
# --------------------------------------------------------------------------- #
def test_a_topical_mismatch_is_the_operators_call_not_a_refusal() -> None:
    """The change that unlocks the catalogue. 35 platforms hold working publisher code
    that NO client could reach, because a topical judgement refused exactly like a
    missing credential. A judgement is now advisory: quoted, acknowledged, allowed."""
    board = evaluate_catalog(
        [_row(name="dev.to", platform_enum="dev.to", topical_scope="developer")],
        client_scope="agnostic",
        connected_platforms={"dev.to"},
    )
    unacked = resolve_selection(board, ["dev.to"])
    assert unacked.allowed == []
    assert unacked.blocked == []
    assert "developer" in unacked.advisories[0], "the platform's OWN rule must be quoted"

    acked = resolve_selection(board, ["dev.to"], acknowledged=True)
    assert acked.allowed == ["dev.to"], "acknowledged, it is usable"


def test_an_unreviewed_platform_is_also_the_operators_call() -> None:
    board = evaluate_catalog(
        [_row(name="Plurk", platform_enum="Plurk", ownership_tier="do_not_use")],
        client_scope="agnostic",
        connected_platforms={"Plurk"},
    )
    assert resolve_selection(board, ["Plurk"]).advisories
    assert resolve_selection(board, ["Plurk"], acknowledged=True).allowed == ["Plurk"]


def test_no_credential_and_no_publisher_stay_hard_refusals() -> None:
    """An acknowledgement cannot conjure a credential or a publisher class. These two
    are facts about the machine, so no override exists - waving them through would
    queue work that can only fail after the drafting spend."""
    board = evaluate_catalog(
        [
            _row(name="Blogger", platform_enum="Blogger"),  # eligible but unconnected
            _row(name="Wix", platform_enum=None, automation_ready=False),
        ],
        client_scope="agnostic",
        connected_platforms=set(),
    )
    verdict = resolve_selection(board, ["Blogger", "Wix"], acknowledged=True)
    assert verdict.allowed == []
    assert len(verdict.blocked) == 2
    assert any("no account is connected" in b.lower() for b in verdict.blocked)
    assert any("build target" in b for b in verdict.blocked)


def test_an_unknown_platform_is_blocked_by_name() -> None:
    assert resolve_selection([], ["NotAPlatform"]).blocked == [
        "NotAPlatform: not in the platform catalogue."
    ]


def test_a_mixed_selection_splits_three_ways() -> None:
    board = evaluate_catalog(
        [
            _row(),  # WordPress.com, eligible + connected
            _row(name="dev.to", platform_enum="dev.to", topical_scope="developer"),
            _row(name="Wix", platform_enum=None, automation_ready=False),
        ],
        client_scope="agnostic",
        connected_platforms={"WordPress.com", "dev.to"},
    )
    verdict = resolve_selection(board, ["WordPress.com", "dev.to", "Wix"])
    assert verdict.allowed == ["WordPress.com"]
    assert len(verdict.advisories) == 1 and "dev.to" in verdict.advisories[0]
    assert len(verdict.blocked) == 1 and "Wix" in verdict.blocked[0]


# --------------------------------------------------------------------------- #
# 0135: the capability matrix outranks every per-client judgement.
# --------------------------------------------------------------------------- #
def test_an_unsupported_mechanism_is_a_hard_refusal_regardless_of_tier() -> None:
    """The matrix is a fact about the machine and the platform. A do-not-use lane
    stays refused even on a per-client tier with a connected account - and the reason
    is the RECORDED one (adapter_status), never a generic restatement."""
    verdict = evaluate_platform(
        _row(
            name="Pastebin.com", platform_enum="Pastebin.com",
            ownership_tier="per_client", mechanism="unsupported",
            adapter_status="Paste site: link placements read as spam signals.",
        ),
        client_scope="agnostic",
        connected=True,
    )
    assert verdict.status == "not_supported"
    assert verdict.reason == "Paste site: link placements read as spam signals."
    assert verdict.mechanism == "unsupported"


def test_an_unsupported_row_without_a_recorded_reason_still_refuses_honestly() -> None:
    verdict = evaluate_platform(
        _row(mechanism="unsupported", adapter_status=""),
        client_scope="agnostic",
        connected=True,
    )
    assert verdict.status == "not_supported"
    assert "do-not-use" in verdict.reason


def test_no_acknowledgement_moves_an_unsupported_platform() -> None:
    """`not_eligible`/`not_reviewed` are judgements an operator may override; the
    matrix's do-not-use lane is not - an acknowledgement cannot make a paste site a
    defensible placement."""
    board = evaluate_catalog(
        [_row(name="Pastebin.com", platform_enum="Pastebin.com",
              mechanism="unsupported", adapter_status="Paste site.")],
        client_scope="agnostic",
        connected_platforms={"Pastebin.com"},
    )
    verdict = resolve_selection(board, ["Pastebin.com"], acknowledged=True)
    assert verdict.allowed == []
    assert len(verdict.blocked) == 1 and "Paste site." in verdict.blocked[0]


def test_the_extension_lane_is_its_own_state_not_eligible_and_not_refused() -> None:
    """`eligible_extension` exists so placement routing (Phase 7) can key off it.
    It is deliberately NOT `eligible`: the API pipeline cannot drive an operator's
    browser session, so folding the two together would plan publishes no worker can
    run."""
    verdict = evaluate_platform(
        _row(name="Substack", platform_enum=None, automation_ready=False,
             mechanism="extension"),
        client_scope="agnostic",
        connected=False,  # no credential needed - the operator's own session publishes
    )
    assert verdict.status == "eligible_extension"
    assert not verdict.eligible
    assert verdict.mechanism == "extension"
    assert "operator" in verdict.reason.lower()


def test_extension_reason_carries_the_recorded_adapter_status() -> None:
    verdict = evaluate_platform(
        _row(name="Medium", platform_enum="Medium", mechanism="extension",
             adapter_status="Publish API retired."),
        client_scope="agnostic",
        connected=True,
    )
    assert verdict.status == "eligible_extension"
    assert "Publish API retired." in verdict.reason


def test_extension_rows_are_never_api_campaign_targets() -> None:
    """Neither the eligible list nor an acknowledged selection may leak an
    extension-lane platform into the API publish path - the block reason explains the
    lane instead of pretending a credential or adapter is missing."""
    board = evaluate_catalog(
        [_row(name="Medium", platform_enum="Medium", mechanism="extension")],
        client_scope="agnostic",
        connected_platforms={"Medium"},
    )
    assert eligible_platform_names(board) == []
    verdict = resolve_selection(board, ["Medium"], acknowledged=True)
    assert verdict.allowed == []
    assert verdict.advisories == []
    assert len(verdict.blocked) == 1 and "placement task" in verdict.blocked[0]


def test_the_human_lane_reports_itself_not_a_missing_adapter() -> None:
    """'Someone should build this adapter' and 'a person places this by hand' are
    different answers, and the board must give the second for a human-lane row."""
    verdict = evaluate_platform(
        _row(name="Wattpad", platform_enum=None, automation_ready=False,
             mechanism="human"),
        client_scope="agnostic",
        connected=True,
    )
    assert verdict.status == "not_supported"
    assert "by hand" in verdict.reason
    assert "build target" not in verdict.reason


def test_an_unclassified_mechanism_falls_through_to_the_pre_matrix_rules() -> None:
    """mechanism='' (a pre-0135 row, or a fake row in an older test) must behave
    exactly as before the matrix existed - back-compat is what keeps every existing
    eligibility pin green without edits."""
    verdict = evaluate_platform(
        _row(mechanism=""), client_scope="agnostic", connected=True
    )
    assert verdict.eligible


def test_the_matrix_is_judged_before_tier_scope_and_review() -> None:
    """An extension row keeps its lane even when its tier/scope would otherwise say
    not_reviewed or not_eligible: what lane a placement can physically travel is not
    a per-client judgement (Medium: do_not_use-with-review was about the dead API
    path; the extension lane is its replacement, not its contradiction)."""
    verdict = evaluate_platform(
        _row(
            name="Medium", platform_enum="Medium", ownership_tier="do_not_use",
            topical_scope="developer", mechanism="extension",
            terms_position="Publish API retired.",
        ),
        client_scope="agnostic",
        connected=False,
    )
    assert verdict.status == "eligible_extension"
