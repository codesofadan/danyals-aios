"""URL normalisation is the definition of "the same page" (owner decision O-2).

Ten checks depend on it, and it decides what "duplicate", "orphan" and
"internal link" mean in a client report. Every rule is pinned here so that
changing the policy breaks a test rather than quietly redefining the product.
"""
from __future__ import annotations

import pytest

from audit_engine.analyzers.urls import (
    DEFAULT_POLICY,
    NormalisationPolicy,
    is_internal,
    normalise,
    registrable_host,
    same_page,
)

S = "https://example.com/"


# --- the four O-2 rules -----------------------------------------------------

@pytest.mark.parametrize("a,b", [
    ("https://example.com/about", "https://example.com/about/"),
    ("https://example.com/a/b/", "https://example.com/a/b"),
])
def test_trailing_slash_is_the_same_page(a, b):
    assert same_page(a, b)


@pytest.mark.parametrize("index", [
    "index.html", "index.htm", "index.php", "default.aspx", "INDEX.HTML",
])
def test_directory_index_is_the_directory(index):
    assert same_page(f"https://example.com/dir/{index}", "https://example.com/dir")


@pytest.mark.parametrize("param", [
    "utm_source=x", "utm_campaign=y", "gclid=123", "fbclid=abc",
    "msclkid=z", "mc_cid=1", "_ga=2", "pk_campaign=q",
])
def test_tracking_parameters_do_not_make_a_different_page(param):
    assert same_page(f"https://example.com/p?{param}", "https://example.com/p")


@pytest.mark.parametrize("param", ["page=2", "id=7", "q=dentist", "sort=asc"])
def test_a_real_query_parameter_does_make_a_different_page(param):
    """Collapsing these would hide genuine duplicate content."""
    assert not same_page(f"https://example.com/p?{param}", "https://example.com/p")


def test_tracking_is_stripped_without_losing_real_parameters():
    assert normalise("https://example.com/p?utm_source=fb&id=7&utm_medium=cpc") == \
        "https://example.com/p?id=7"


# --- ordering, case, port, fragment ----------------------------------------

def test_query_order_does_not_matter():
    assert same_page("https://example.com/p?b=2&a=1", "https://example.com/p?a=1&b=2")


def test_host_is_case_insensitive_but_path_is_not():
    assert same_page("https://EXAMPLE.com/About", "https://example.com/About")
    assert not same_page("https://example.com/About", "https://example.com/about")


@pytest.mark.parametrize("url,expected", [
    ("https://example.com:443/p", "https://example.com/p"),
    ("http://example.com:80/p", "http://example.com/p"),
    ("https://example.com:8443/p", "https://example.com:8443/p"),
])
def test_default_ports_are_stripped_and_others_kept(url, expected):
    assert normalise(url) == expected


def test_fragment_never_reaches_the_server_so_it_is_dropped():
    assert same_page("https://example.com/p#section", "https://example.com/p")


def test_credentials_in_a_url_are_discarded():
    """A userinfo blob must never reach evidence_json and then a client PDF."""
    out = normalise("https://user:secret@example.com/p")
    assert "secret" not in out and "user" not in out
    assert out == "https://example.com/p"


def test_duplicate_slashes_collapse():
    assert same_page("https://example.com//a///b", "https://example.com/a/b")


# --- what normalisation deliberately does NOT do ---------------------------

def test_www_is_not_unified_because_that_is_its_own_finding():
    """Collapsing www here would hide the redirect defect TECH-013 reports."""
    assert not same_page("https://www.example.com/", "https://example.com/")


def test_scheme_is_not_unified_because_http_vs_https_is_a_finding():
    assert not same_page("http://example.com/p", "https://example.com/p")


# --- totality ---------------------------------------------------------------

@pytest.mark.parametrize("bad", ["", "   ", "not a url", "http://", "///", "mailto:a@b.c"])
def test_normalise_never_raises(bad):
    normalise(bad)  # must not raise


def test_normalise_is_idempotent():
    for u in ("https://example.com/a/?utm_source=x", "https://EX.com:443//b/index.html#f"):
        once = normalise(u)
        assert normalise(once) == once


# --- policy is honoured -----------------------------------------------------

def test_policy_can_keep_trailing_slash_distinct():
    p = NormalisationPolicy(unify_trailing_slash=False)
    assert not same_page("https://example.com/a", "https://example.com/a/", policy=p)


def test_policy_can_unify_www_when_the_owner_wants_it():
    p = NormalisationPolicy(unify_www=True)
    assert same_page("https://www.example.com/", "https://example.com/", policy=p)


def test_default_policy_is_the_documented_one():
    assert NormalisationPolicy(
        unify_trailing_slash=True, strip_directory_index=True,
        strip_tracking_params=True, sort_query=True, strip_fragment=True,
        lowercase_host=True, strip_default_port=True, unify_www=False,
    ) == DEFAULT_POLICY


# --- internal / external ----------------------------------------------------

@pytest.mark.parametrize("url,expected", [
    ("https://example.com/p", True),
    ("https://www.example.com/p", True),      # www IS the same site
    ("/relative/path", True),
    ("https://other.com/p", False),
    ("mailto:a@example.com", False),
    ("tel:+123", False),
    ("javascript:void(0)", False),
])
def test_is_internal(url, expected):
    assert is_internal(url, S) is expected


def test_registrable_host_drops_www_and_port():
    assert registrable_host("https://WWW.Example.com:8443/x") == "example.com"
