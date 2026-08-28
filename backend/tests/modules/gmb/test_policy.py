"""The Google Business Profile post gate.

`policy.py` opens with "fully deterministic, so it is unit-tested exhaustively".
It was not tested at all - the whole `gmb` module carried 945 lines and zero
tests, and this is the part of it that decides whether a post is allowed to reach
a client's public profile. A gate nobody tests is a gate nobody can trust to be
refusing the right things.

The distinction the file rests on, and the one most worth pinning: a VIOLATION
hard-blocks publication, a WARNING is advice a reviewer weighs. Getting that
boundary wrong in either direction is expensive - a warning promoted to a
violation blocks legitimate posts, and a violation demoted to a warning puts
prohibited content on a client's Google listing.
"""

from __future__ import annotations

import pytest

from app.modules.gmb.policy import (
    CTA_NEEDS_URL,
    CTA_TYPES,
    GBP_MAX_CHARS,
    GBP_MIN_CHARS,
    GBP_RECOMMENDED_MAX,
    check_gbp_policy,
)

CLEAN = "Book a spring service with our team this week and keep the pool ready for summer."


def codes(report) -> set[str]:
    return {i.code for i in report.issues}


def violations(report) -> set[str]:
    return {i.code for i in report.violations}


def warnings(report) -> set[str]:
    return {i.code for i in report.warnings}


# ------------------------------------------------------------------ the happy path

def test_a_clean_post_with_a_valid_button_passes_with_no_findings_at_all():
    r = check_gbp_policy(CLEAN, cta_type="book", cta_url="https://example.com/book")
    assert r.ok
    assert r.issues == []
    assert r.char_count == len(CLEAN)


def test_ok_tracks_violations_only_and_warnings_never_block():
    # The whole severity split exists for this: advice must not stop a post.
    r = check_gbp_policy(CLEAN, cta_type="none")
    assert warnings(r) == {"no_cta"}
    assert r.ok is True


# --------------------------------------------------------------------- hard blocks

def test_an_empty_body_is_blocked():
    r = check_gbp_policy("   ")
    assert not r.ok
    assert "empty" in violations(r)
    assert r.char_count == 0


def test_the_hard_character_ceiling_blocks_and_the_recommended_one_only_warns():
    over = check_gbp_policy("a " * (GBP_MAX_CHARS // 2 + 20), cta_type="none")
    assert "too_long" in violations(over)

    # Between the two limits: long enough to advise, not to refuse.
    mid = check_gbp_policy("a " * (GBP_RECOMMENDED_MAX // 2 + 20), cta_type="none")
    assert mid.ok
    assert "long_for_gbp" in warnings(mid)
    assert "too_long" not in codes(mid)


def test_an_empty_body_is_not_also_reported_as_too_long():
    # `elif` in the source: the two length findings are exclusive, and reporting
    # both for one body would double-count a single fact.
    assert violations(check_gbp_policy("")) == {"empty"}


# Built from code points, not typed: this repo's linter flags a literal em/en
# dash as ambiguous, and it is right to - these two characters are the thing
# under test, not punctuation the file is choosing to use.
EM, EN = chr(0x2014), chr(0x2013)


@pytest.mark.parametrize("dash", [EM, EN])
def test_an_em_or_en_dash_blocks_publication(dash):
    r = check_gbp_policy(f"Spring service {dash} book today.", cta_type="none")
    assert not r.ok
    assert "forbidden_dash" in violations(r)


@pytest.mark.parametrize(
    ("body", "category"),
    [
        ("Cheap escort listings available now.", "adult"),
        ("Try our miracle cure for back pain today.", "misleading"),
        ("We sell counterfeit bags at low prices.", "dangerous_illegal"),
        ("Join the online casino tonight and win.", "regulated_goods"),
    ],
)
def test_prohibited_content_blocks_and_names_its_category(body, category):
    r = check_gbp_policy(body, cta_type="none")
    assert not r.ok
    assert "prohibited_content" in violations(r)
    msg = next(i.message for i in r.violations if i.code == "prohibited_content")
    assert category in msg


def test_the_prohibited_screen_is_case_insensitive():
    assert not check_gbp_policy("MIRACLE CURE for everything.", cta_type="none").ok


def test_an_unknown_cta_type_is_refused():
    r = check_gbp_policy(CLEAN, cta_type="teleport")
    assert "invalid_cta" in violations(r)


@pytest.mark.parametrize("cta", sorted(CTA_NEEDS_URL))
def test_every_button_that_needs_a_link_is_blocked_without_one(cta):
    assert "cta_url_missing" in violations(check_gbp_policy(CLEAN, cta_type=cta))


@pytest.mark.parametrize("bad", ["example.com/book", "javascript:alert(1)", "ftp://x.test/a", "/relative"])
def test_a_cta_url_that_is_not_http_is_refused(bad):
    r = check_gbp_policy(CLEAN, cta_type="book", cta_url=bad)
    assert "cta_url_invalid" in violations(r)


def test_a_call_button_needs_no_url():
    # The one CTA whose destination is a phone number, not a link.
    assert "call" in CTA_TYPES and "call" not in CTA_NEEDS_URL
    assert check_gbp_policy(CLEAN, cta_type="call").ok


def test_a_missing_and_an_invalid_url_are_never_reported_together():
    # `elif`: one URL problem per post, or a reviewer sees two findings for one field.
    r = check_gbp_policy(CLEAN, cta_type="shop", cta_url="")
    assert "cta_url_invalid" not in codes(r)


# ---------------------------------------------------------------------- advisories

def test_a_very_short_post_is_advised_but_allowed():
    r = check_gbp_policy("Open today", cta_type="call")
    assert r.char_count < GBP_MIN_CHARS
    assert "very_short" in warnings(r)
    assert r.ok


def test_shouting_is_a_warning_and_ordinary_capitals_are_not():
    loud = check_gbp_policy("HUGE SALE ENDS SOON, come along.", cta_type="call")
    assert "excessive_caps" in warnings(loud)
    # Two capitalised words are emphasis, not spam - the rule needs three.
    assert "excessive_caps" not in codes(check_gbp_policy("A BIG SALE is on.", cta_type="call"))


def test_repeated_punctuation_is_a_warning():
    assert "excessive_punctuation" in warnings(
        check_gbp_policy("Book now!!! Spaces are limited.", cta_type="call")
    )


def test_contact_details_belong_in_the_profile_not_the_post():
    phone = check_gbp_policy("Call us on 0161 496 0000 to book a spring service.", cta_type="call")
    assert "phone_in_body" in warnings(phone)
    url = check_gbp_policy("Book at https://example.com/spring today please.", cta_type="call")
    assert "url_in_body" in warnings(url)


@pytest.mark.parametrize("post_type", ["offer", "event"])
def test_an_offer_or_event_without_a_title_is_advised(post_type):
    assert "missing_title" in warnings(
        check_gbp_policy(CLEAN, cta_type="call", post_type=post_type)
    )
    assert "missing_title" not in codes(
        check_gbp_policy(CLEAN, cta_type="call", post_type=post_type, title="Spring offer")
    )


def test_an_update_post_needs_no_title():
    assert "missing_title" not in codes(check_gbp_policy(CLEAN, cta_type="call"))


# ------------------------------------------------------------------- determinism

def test_the_same_post_always_gets_the_same_verdict():
    """The file's own claim. A gate that varies cannot be reviewed."""
    args = {"cta_type": "book", "cta_url": "https://example.com",
            "post_type": "offer", "title": ""}
    first = check_gbp_policy(CLEAN, **args)
    for _ in range(5):
        again = check_gbp_policy(CLEAN, **args)
        assert [i.as_dict() for i in again.issues] == [i.as_dict() for i in first.issues]
        assert again.ok == first.ok


def test_every_issue_carries_a_code_a_sentence_and_a_known_severity():
    r = check_gbp_policy("BUY NOW!!! miracle cure — call 0161 496 0000 https://x.test", cta_type="nope")
    assert len(r.issues) >= 6
    for i in r.issues:
        assert i.code and i.message.strip()
        assert i.severity in ("violation", "warning")
        assert i.as_dict() == {"code": i.code, "message": i.message, "severity": i.severity}


def test_violations_and_warnings_partition_the_issue_list():
    r = check_gbp_policy("BUY NOW!!! miracle cure — x", cta_type="nope")
    assert len(r.violations) + len(r.warnings) == len(r.issues)
    assert not (set(violations(r)) & set(warnings(r)))
