"""Anchor safety (R2-14): zero exact-match commercial anchors.

The rule is a FLOOR, not a quota. There is no published safe percentage for anchor
distribution - every number in circulation is somebody's correlation study - so this
encodes only the shape that has no editorial justification at any ratio: an anchor that
is exactly the phrase the destination is trying to rank.

The two failure directions both matter. Letting the exact phrase through is the pattern
that gets a profile actioned. Refusing a client's own brand name because it happens to
contain those words pushes the operator toward something less natural, not more - and a
guard that fires on legitimate work gets switched off.
"""

from __future__ import annotations

import pytest

from app.services.web2_anchor import check_anchor, first_allowed, money_phrase

pytestmark = pytest.mark.unit

TARGET = "https://leedsdrainage.co.uk/services/drain-unblocking"


def test_the_exact_money_phrase_is_refused() -> None:
    v = check_anchor("drain unblocking", target_url=TARGET, client_name="Leeds Drainage")
    assert v.verdict == "exact_match"
    assert not v.allowed
    assert v.suggestion  # a refusal must offer a way forward


def test_filler_words_do_not_defeat_the_rule() -> None:
    """'the drain unblocking' is the same anchor wearing a stopword. If that passed,
    the rule would be one word away from useless."""
    for variant in ("the drain unblocking", "drain unblocking service"[:16], "our drain unblocking"):
        v = check_anchor(variant, target_url=TARGET, client_name="Leeds Drainage")
        assert v.verdict == "exact_match", variant


def test_a_brand_anchor_is_always_allowed() -> None:
    assert check_anchor("Leeds Drainage", target_url=TARGET, client_name="Leeds Drainage").allowed


def test_a_brand_that_contains_the_money_words_is_still_allowed() -> None:
    """A company called 'Leeds Drain Unblocking' cannot be forbidden from using its own
    name. Refusing it would be the guard mistaking a legitimate anchor for a scheme."""
    v = check_anchor(
        "Leeds Drain Unblocking",
        target_url=TARGET,
        client_name="Leeds Drain Unblocking",
    )
    assert v.allowed
    assert v.reason == "brand anchor"


def test_a_natural_phrase_is_allowed() -> None:
    for anchor in ("how the survey works", "read the full breakdown", "leedsdrainage.co.uk"):
        assert check_anchor(anchor, target_url=TARGET, client_name="Leeds Drainage").allowed, anchor


def test_a_different_service_is_not_an_exact_match() -> None:
    """Only the phrase THIS destination ranks for is refused - an anchor about gutters
    pointing at the drains page is a relevance problem, not an over-optimisation one."""
    assert check_anchor("gutter clearing", target_url=TARGET, client_name="X").allowed


def test_a_sentence_length_anchor_is_refused() -> None:
    long = "click here to read all about our emergency drain unblocking service in Leeds today"
    v = check_anchor(long, target_url=TARGET, client_name="Leeds Drainage")
    assert v.verdict == "too_long"


def test_an_empty_or_filler_only_anchor_is_refused() -> None:
    assert check_anchor("", target_url=TARGET).verdict == "empty"
    assert check_anchor("the and of", target_url=TARGET).verdict == "empty"


# --------------------------------------------------------------------------- #
# Deriving the money phrase from the DESTINATION, not from a declared keyword.
# --------------------------------------------------------------------------- #
def test_the_money_phrase_comes_from_the_url_slug() -> None:
    assert money_phrase(TARGET) == ("drain", "unblocking")


def test_a_homepage_link_falls_back_to_the_topic() -> None:
    """A homepage has no slug to read, so with no fallback the rule would silently stop
    applying for exactly the links most likely to be over-optimised."""
    assert money_phrase("https://leedsdrainage.co.uk/", topic="drain unblocking") == (
        "drain", "unblocking",
    )


def test_a_file_extension_segment_is_not_the_slug() -> None:
    assert money_phrase("https://x.test/services/drain-unblocking/index.html") == (
        "drain", "unblocking",
    )


# --------------------------------------------------------------------------- #
# Choosing from an operator's list.
# --------------------------------------------------------------------------- #
def test_the_first_usable_anchor_is_chosen() -> None:
    chosen, verdict = first_allowed(
        ["drain unblocking", "Leeds Drainage", "the team"],
        target_url=TARGET, client_name="Leeds Drainage",
    )
    assert chosen == "Leeds Drainage"
    assert verdict.allowed


def test_a_list_of_only_bad_anchors_still_yields_something_usable() -> None:
    """A placement with no link text is a worse outcome than a duller one, so the brand
    is the floor rather than an error."""
    chosen, verdict = first_allowed(
        ["drain unblocking", "the drain unblocking"],
        target_url=TARGET, client_name="Leeds Drainage",
    )
    assert chosen == "Leeds Drainage"
    assert verdict.verdict == "exact_match"   # and the reason is still reported
