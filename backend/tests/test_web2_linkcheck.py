"""Measuring whether our link actually survived on the published page.

The property this file defends: **"could not check" is not "checked and fine".** A
two-state control (found / not-found) turns every network hiccup into either a false
accusation that a platform stripped our link, or a silent pass. Both are worse than
saying "unknown", because both look like a measurement.
"""

from __future__ import annotations

import pytest

from app.services.web2_linkcheck import LinkCheck, check_link, inspect_html, normalize

pytestmark = pytest.mark.unit

TARGET = "https://leedsdrainage.co.uk/drains"


def test_a_plain_link_is_found_and_followed() -> None:
    html = f'<p>Read <a href="{TARGET}">Leeds Drainage</a> for more.</p>'
    c = inspect_html(html, TARGET)
    assert c.state == "found" and c.found is True
    assert c.followed is True


def test_nofollow_is_found_but_not_followed() -> None:
    """The distinction the whole column exists for: the link IS there, and it passes no
    equity. Reporting it as a plain success would overstate what the client received."""
    html = f'<a href="{TARGET}" rel="nofollow">Leeds Drainage</a>'
    c = inspect_html(html, TARGET)
    assert c.state == "found"
    assert c.followed is False
    assert c.rel == "nofollow"


@pytest.mark.parametrize("rel", ["sponsored", "ugc", "nofollow noopener", "UGC"])
def test_every_equity_stopping_rel_counts_as_not_followed(rel: str) -> None:
    """`sponsored` and `ugc` are different declarations from `nofollow` but the SEO
    outcome is the same, and a check that only knew the word "nofollow" would pass them."""
    c = inspect_html(f'<a href="{TARGET}" rel="{rel}">x</a>', TARGET)
    assert c.state == "found"
    assert c.followed is False


def test_a_page_without_our_link_is_missing_not_unknown() -> None:
    """We fetched it and the link was not there - that is a real, actionable finding."""
    c = inspect_html('<a href="https://someone-else.example/">other</a>', TARGET)
    assert c.state == "missing" and c.found is False


def test_a_redirected_link_is_reported_missing_on_purpose() -> None:
    """A platform that wraps our href in its own redirector has changed what the client
    got. Counting it as found would hide exactly that change."""
    html = f'<a href="https://out.example/r?u={TARGET}">Leeds Drainage</a>'
    assert inspect_html(html, TARGET).state == "missing"


def test_cosmetic_url_differences_do_not_read_as_missing() -> None:
    """Platforms echo links back with a trailing slash, a different case, or www. A
    naive compare would accuse them of stripping a link that is plainly there."""
    for variant in (
        "https://leedsdrainage.co.uk/drains/",
        "https://WWW.leedsdrainage.co.uk/drains",
        "HTTPS://leedsdrainage.co.uk/drains",
    ):
        assert inspect_html(f'<a href="{variant}">x</a>', TARGET).state == "found", variant


def test_normalize_keeps_the_query_because_it_selects_the_page() -> None:
    """A trailing slash is cosmetic; a query string usually is not - ?page=2 is a
    different page, and collapsing it would match the wrong URL."""
    assert normalize("https://x.test/a?b=1") != normalize("https://x.test/a")


# --------------------------------------------------------------------------- #
# The three-state contract.
# --------------------------------------------------------------------------- #
def test_no_fetcher_is_unknown_never_a_pass() -> None:
    c = check_link("https://blog.test/p", TARGET, None)
    assert c.state == "unknown" and c.found is None and c.followed is False


def test_a_fetch_that_raises_is_unknown_and_does_not_propagate() -> None:
    """The check must never fail the job it is checking - a publish that worked must not
    be marked failed because a verification request timed out."""
    def boom(url: str) -> str | None:
        raise TimeoutError("slow")

    c = check_link("https://blog.test/p", TARGET, boom)
    assert c.state == "unknown"
    assert "fetch failed" in c.detail


def test_an_unreadable_page_is_unknown_not_missing() -> None:
    c = check_link("https://blog.test/p", TARGET, lambda url: None)
    assert c.state == "unknown" and c.found is None


def test_a_real_fetch_is_measured() -> None:
    html = f'<a href="{TARGET}" rel="noopener">Leeds Drainage</a>'
    c = check_link("https://blog.test/p", TARGET, lambda url: html)
    assert c.state == "found" and c.followed is True


def test_an_empty_verdict_defaults_to_unknown() -> None:
    assert LinkCheck().state == "unknown"
    assert LinkCheck().found is None


# --------------------------------------------------------------------------- #
# Learned from the FIRST REAL PUBLISH (Ghost, 2026-08-28).
# --------------------------------------------------------------------------- #
def test_a_platform_appended_ref_parameter_does_not_read_as_a_stripped_link() -> None:
    """Ghost rewrote our href to `...?ref=<its own domain>` on publish.

    A strict compare called that MISSING - i.e. accused the platform of stripping a link
    that was plainly there, on the very first real placement. Attribution parameters do
    not change which page the link resolves to, so they must not change the verdict.
    """
    published = f"{TARGET}?ref=purple-cormorant.pikapod.net"
    c = inspect_html(f'<a href="{published}">drain unblocking in Leeds</a>', TARGET)
    assert c.state == "found"
    assert c.followed is True


def test_the_rewrite_is_reported_even_though_it_still_counts_as_found() -> None:
    """Tolerating the rewrite must not mean hiding it: the client received a slightly
    different href from the one we placed, and that is worth being able to see."""
    published = f"{TARGET}?ref=purple-cormorant.pikapod.net"
    c = inspect_html(f'<a href="{published}">x</a>', TARGET)
    assert "rewrote the href" in c.detail


@pytest.mark.parametrize("param", ["utm_source=x", "fbclid=abc", "gclid=1", "source=feed"])
def test_common_attribution_parameters_are_all_tolerated(param: str) -> None:
    c = inspect_html(f'<a href="{TARGET}?{param}">x</a>', TARGET)
    assert c.state == "found", param


def test_a_meaningful_query_still_distinguishes_pages() -> None:
    """The tolerance is scoped to attribution. `?page=2` selects a different page, and
    treating it as the same link would report a placement on the wrong URL as correct."""
    assert inspect_html(f'<a href="{TARGET}?page=2">x</a>', TARGET).state == "missing"


def test_a_tracking_param_on_a_genuinely_different_path_is_still_missing() -> None:
    """Stripping `ref` must not accidentally match a link to another page entirely."""
    other = "https://leedsdrainage.co.uk/gutters?ref=purple-cormorant.pikapod.net"
    assert inspect_html(f'<a href="{other}">x</a>', TARGET).state == "missing"
