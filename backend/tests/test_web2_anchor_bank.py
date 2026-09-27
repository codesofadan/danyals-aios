"""The anchor bank: a distribution held at plan time, not audited afterwards.

``web2_anchor`` refuses the one anchor shape with no editorial justification at any ratio
- an anchor that is exactly the money phrase the destination is trying to rank. That is a
floor, and it judges ONE anchor against ONE target.

A link profile is judged on its SHAPE. Fifty individually-defensible anchors are still a
pattern if forty of them are partial-match commercial phrases, and no per-anchor check can
see that. ``M05`` REQ-W2-010 asks for enforced shares; A5 asks that the exact-match share
never exceeds its cap across a full campaign.

Why this ASSIGNS rather than AUDITS: an audit describes a profile you have already
published, on pages you do not control, where the remedy is asking a platform to edit a
post. Assigning from a bank means the profile that gets built is the profile approved.
"""

from __future__ import annotations

import pytest

from app.modules.web2 import anchor_bank as ab

pytestmark = pytest.mark.unit

TARGET = "https://leedsdrainage.co.uk/cctv-drain-survey"
CLIENT = "Leeds Drainage Co"


def _classify(anchor: str) -> str:
    return ab.classify(anchor, target_url=TARGET, client_name=CLIENT)


def _full_bank() -> list[ab.BankedAnchor]:
    bank, _ = ab.build_bank(
        [
            "Leeds Drainage Co", "https://leedsdrainage.co.uk",
            "read more", "drain survey specialists",
        ],
        target_url=TARGET, client_name=CLIENT,
    )
    return bank


# --------------------------------------------------------------------------- #
# Classification is DERIVED, never declared
# --------------------------------------------------------------------------- #
def test_each_anchor_kind_is_derived_from_the_anchor_and_its_destination() -> None:
    """Derived rather than operator-declared: someone typing anchors into a form will not
    label them, and someone asked to will label them optimistically - which turns the
    whole distribution into a self-report."""
    assert _classify("Leeds Drainage Co") == "branded"
    assert _classify("https://leedsdrainage.co.uk") == "naked"
    assert _classify("read more") == "generic"
    assert _classify("drain survey specialists") == "partial"
    assert _classify("cctv drain survey") == "exact"


def test_a_bare_url_containing_the_brand_is_naked_not_branded() -> None:
    """Order matters. A URL is a naked link whatever words are inside it, and counting it
    as branded would inflate the safest bucket with links that are not it."""
    assert _classify("https://leedsdrainage.co.uk/about") == "naked"
    assert _classify("www.leedsdrainage.co.uk") == "naked"


def test_the_exact_match_rule_has_exactly_one_definition() -> None:
    """The bank asks ``check_anchor`` rather than re-deriving, so it cannot drift into a
    more permissive idea of "this is the money phrase" than the gate that refuses
    placements."""
    from app.services.web2_anchor import check_anchor

    assert not check_anchor(
        "cctv drain survey", target_url=TARGET, topic="", client_name=CLIENT
    ).allowed
    assert _classify("cctv drain survey") == "exact"


# --------------------------------------------------------------------------- #
# The bank
# --------------------------------------------------------------------------- #
def test_an_exact_match_anchor_never_reaches_the_bank_and_the_refusal_is_reported() -> None:
    """Reported, not silently dropped: an operator whose anchors disappear without
    explanation supplies the same list next time."""
    bank, notes = ab.build_bank(
        ["Leeds Drainage Co", "cctv drain survey"], target_url=TARGET, client_name=CLIENT
    )
    assert [b.text for b in bank] == ["Leeds Drainage Co"]
    assert any("was not banked" in note for note in notes)


def test_the_brand_is_the_safe_floor_when_nothing_survives() -> None:
    bank, notes = ab.build_bank(
        ["cctv drain survey"], target_url=TARGET, client_name=CLIENT
    )
    assert [b.text for b in bank] == [CLIENT]
    assert any("the brand" in note for note in notes)


# --------------------------------------------------------------------------- #
# The distribution (A5)
# --------------------------------------------------------------------------- #
def test_the_assigned_profile_matches_the_declared_distribution() -> None:
    actual = ab.assign(_full_bank(), 20).distribution()

    assert actual["branded"] == pytest.approx(0.55, abs=0.05)
    assert actual["naked"] == pytest.approx(0.20, abs=0.05)
    assert actual["generic"] == pytest.approx(0.15, abs=0.05)
    assert actual["partial"] == pytest.approx(0.10, abs=0.05)


def test_no_exact_match_anchor_appears_at_any_campaign_size() -> None:
    """A5, stated as the property it actually is."""
    for size in (1, 3, 7, 20, 50):
        assignment = ab.assign(_full_bank(), size)
        assert "exact" not in assignment.distribution()
        ok, why = ab.within_policy(assignment)
        assert ok, f"size {size}: {why}"


def test_the_profile_holds_at_every_prefix_not_only_at_the_end() -> None:
    """A campaign can be paused. A profile that only balances once every placement has
    published is not a profile that was controlled - it is one that happened to work out.
    """
    assignment = ab.assign(_full_bank(), 20)
    for prefix in range(4, len(assignment.kinds) + 1):
        partial = ab.Assignment(
            anchors=assignment.anchors[:prefix], kinds=assignment.kinds[:prefix]
        )
        ok, why = ab.within_policy(partial)
        assert ok, f"first {prefix} placements are out of policy: {why}"


def test_an_exact_match_reaching_the_bank_is_refused_not_rationed() -> None:
    """Belt and braces. One arriving here means something bypassed the gate, and
    rationing would spend a budget on the exact shape A5 caps at zero."""
    smuggled = [ab.BankedAnchor(text="cctv drain survey", kind="exact")]
    with pytest.raises(ab.AnchorBankRefused, match="no editorial justification"):
        ab.assign(smuggled, 5)


def test_a_custom_distribution_is_honoured() -> None:
    """The shares are a posture, not a finding - ``web2_anchor``'s header is explicit that
    no published safe ratio exists - so a client can be run tighter or looser."""
    assignment = ab.assign(
        _full_bank(), 20,
        shares={"branded": 0.9, "naked": 0.1, "generic": 0.0, "partial": 0.0},
    )
    assert assignment.distribution()["branded"] > 0.8


def test_an_exhausted_anchor_is_not_reused() -> None:
    """One anchor repeated across a campaign is its own footprint even when its KIND is
    safe."""
    bank = [
        ab.BankedAnchor(text="Leeds Drainage Co", kind="branded", used=2, cap=2),
        ab.BankedAnchor(text="https://leedsdrainage.co.uk", kind="naked"),
    ]
    assert "Leeds Drainage Co" not in ab.assign(bank, 5).anchors


def test_a_single_anchor_campaign_says_so() -> None:
    bank, _ = ab.build_bank([CLIENT], target_url=TARGET, client_name=CLIENT)
    assert any("its own footprint" in note for note in ab.assign(bank, 10).notes)


def test_a_bank_with_nothing_left_refuses_rather_than_reusing() -> None:
    bank = [ab.BankedAnchor(text="x", kind="branded", used=1, cap=1)]
    with pytest.raises(ab.AnchorBankRefused, match="reached its own cap"):
        ab.assign(bank, 3)


def test_zero_placements_is_refused() -> None:
    with pytest.raises(ab.AnchorBankRefused):
        ab.assign(_full_bank(), 0)


# --------------------------------------------------------------------------- #
# The policy check runs over real campaigns too
# --------------------------------------------------------------------------- #
def test_within_policy_catches_a_profile_edited_out_of_shape_after_planning() -> None:
    """A5 asserts over a FULL campaign, and a plan that was correct can still be
    undermined by manual edits - so the check runs over real anchors, not just plans."""
    tampered = ab.Assignment(
        anchors=("a", "b", "c", "d"), kinds=("partial", "partial", "partial", "branded")
    )
    ok, why = ab.within_policy(tampered)
    assert not ok
    assert "partial" in why


def test_one_exact_match_anywhere_fails_the_policy_check() -> None:
    tampered = ab.Assignment(anchors=("a", "b"), kinds=("branded", "exact"))
    ok, why = ab.within_policy(tampered)
    assert not ok
    assert "the cap is 0%" in why
