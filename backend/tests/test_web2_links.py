"""R2-15: no Web 2.0 property may link to another Web 2.0 property.

WHY THIS RULE GETS ITS OWN SUITE. Every other control in the module fights a statistical
tell that needs a threshold. This one is a hard graph edge: one crawl of our own published
pages reconstructs the network, whatever the prose looks like. R2 calls it "the single
clearest network tell we can emit". It was written into the record, given a data accessor,
and then never wired to anything - so until this suite existed the ban was documentation.
"""

from __future__ import annotations

import pytest

from app.services.web2_links import check_links, extract_urls, host_of, normalise

pytestmark = pytest.mark.unit

OURS = {
    "https://leedsdrainage.wordpress.com/2026/08/cctv-surveys",
    "https://acmeroofing.blogspot.com/2026/07/flat-roofs.html",
    "https://telegra.ph/Some-Property-08-11",
}
MONEY = "https://leedsdrainage.co.uk/services"


# --------------------------------------------------------------------------- #
# Finding the links at all.
# --------------------------------------------------------------------------- #
def test_bare_urls_count_as_links_because_they_resolve_when_published() -> None:
    """Treating an unlinked URL as 'not really a link' would be a hole in the rule, not
    a nicety - it renders as a live link in the published HTML either way."""
    body = "See https://example.com/guide for more."
    assert extract_urls(body) == ["https://example.com/guide"]


def test_markdown_links_and_trailing_punctuation_are_handled() -> None:
    body = "Read [the guide](https://example.com/guide), or https://example.com/other."
    assert extract_urls(body) == ["https://example.com/guide", "https://example.com/other"]


def test_the_same_url_twice_is_reported_once() -> None:
    body = "a https://example.com/x b https://example.com/x"
    assert extract_urls(body) == ["https://example.com/x"]


# --------------------------------------------------------------------------- #
# Normalisation: a trailing slash is not a defence.
# --------------------------------------------------------------------------- #
def test_two_spellings_of_one_page_compare_equal() -> None:
    forms = [
        "https://Leeds.WordPress.com/post/",
        "http://leeds.wordpress.com/post",
        "https://leeds.wordpress.com:443/post#section",
    ]
    assert len({normalise(f) for f in forms}) == 1


def test_host_extraction_survives_a_missing_scheme() -> None:
    assert host_of("leeds.wordpress.com/post") == "leeds.wordpress.com"


# --------------------------------------------------------------------------- #
# The ban itself.
# --------------------------------------------------------------------------- #
def test_a_link_to_another_property_is_refused() -> None:
    body = f"Useful background: {sorted(OURS)[0]}\n\nOur work: {MONEY}"
    verdict = check_links(body, target_url=MONEY, known_property_urls=OURS)
    assert verdict.blocked
    assert verdict.code.startswith("link_block:self_reference:")
    assert "R2-15" in verdict.detail


def test_the_property_root_is_refused_even_when_we_only_know_a_deep_url() -> None:
    """We store the POST url, but a link to the blog's front page is the same network
    edge. Matching only the exact stored string would miss the easiest way to draw it."""
    verdict = check_links(
        f"See https://leedsdrainage.wordpress.com and {MONEY}",
        target_url=MONEY,
        known_property_urls=OURS,
    )
    assert verdict.blocked


def test_a_stranger_on_a_shared_host_is_also_refused_and_that_is_deliberate() -> None:
    """On a path-based host our property and a stranger's share one hostname. Blocking
    both over-blocks a genuine reference; the trade is taken because the alternative is
    emitting the one signal good prose cannot hide."""
    verdict = check_links(
        f"Source: https://telegra.ph/Someone-Elses-Article-01-02 and {MONEY}",
        target_url=MONEY,
        known_property_urls=OURS,
    )
    assert verdict.blocked


def test_a_genuine_third_party_reference_passes() -> None:
    body = (
        "Per the [drainage code](https://gov.uk/drainage-standards) and "
        "https://ciwem.org/guidance, the survey matters.\n\n"
        f"We do this daily at {MONEY}."
    )
    assert not check_links(body, target_url=MONEY, known_property_urls=OURS).blocked


def test_the_cross_client_scope_is_the_point() -> None:
    """A link to ANOTHER client's property is the edge that joins two clients together -
    the exact correlation the per-client account model exists to prevent."""
    verdict = check_links(
        f"See https://acmeroofing.blogspot.com/2026/07/flat-roofs.html — also {MONEY}",
        target_url=MONEY,
        known_property_urls=OURS,
    )
    assert verdict.blocked


# --------------------------------------------------------------------------- #
# The money-site rule (WEB2-005).
# --------------------------------------------------------------------------- #
def test_exactly_one_money_link_is_allowed() -> None:
    assert not check_links(
        f"Intro. {MONEY} closes it.", target_url=MONEY, known_property_urls=OURS
    ).blocked


def test_a_second_money_link_is_refused() -> None:
    body = f"Start {MONEY} middle https://leedsdrainage.co.uk/contact end."
    verdict = check_links(body, target_url=MONEY, known_property_urls=OURS)
    assert verdict.blocked
    assert verdict.code.startswith("link_block:money_site_repeat:")


def test_the_money_site_is_never_treated_as_a_self_reference() -> None:
    """If a client's own site were also in the known set, blocking it would refuse the
    article's entire reason to exist."""
    assert not check_links(
        f"Our work: {MONEY}", target_url=MONEY, known_property_urls=OURS | {MONEY}
    ).blocked


def test_a_draft_with_no_links_at_all_passes() -> None:
    assert not check_links("Just prose.", target_url=MONEY, known_property_urls=OURS).blocked


# --------------------------------------------------------------------------- #
# Non-vacuity: the suite must go red on the defect it exists to catch.
# --------------------------------------------------------------------------- #
def test_the_ban_is_not_vacuous_when_the_known_set_is_empty() -> None:
    """The failure mode this guards is the REAL one that shipped: the accessor existed
    and nothing called it, so the gate ran with an empty corpus and passed everything.
    An empty set must therefore let a self-link through - proving the block above came
    from the data, not from an unconditional refusal that would pass either way."""
    body = f"Link: {sorted(OURS)[0]} and {MONEY}"
    assert check_links(body, target_url=MONEY, known_property_urls=OURS).blocked
    assert not check_links(body, target_url=MONEY, known_property_urls=frozenset()).blocked
