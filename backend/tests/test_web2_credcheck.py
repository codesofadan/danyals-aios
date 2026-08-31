"""Verifying a stored credential before a campaign spends anything.

The defect this removes: an account counted as "connected" because its required fields
were non-empty. That proves SHAPE, not validity — a revoked token, a typo, and a key
pasted from the wrong platform are all indistinguishable from a working one under a
completeness check. The operator learned the truth only when a campaign failed, after
the drafting spend.

The property these tests defend is the same one the link checker defends: **"could not
check" is not "checked and fine".** A status board that collapses unknown into either
pass or fail is worse than one that admits it does not know, because both mistakes look
like a measurement.
"""

from __future__ import annotations

import json

import pytest

from app.services.web2_credcheck import (
    VerifyRequest,
    check_credential,
    interpret,
    request_for,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------------------- #
# Interpreting what the platform said.
# --------------------------------------------------------------------------- #
def test_a_2xx_is_the_only_pass() -> None:
    assert interpret(200, "{}").state == "ok"
    assert interpret(204, "").state == "ok"


@pytest.mark.parametrize("status", [401, 403])
def test_only_401_and_403_mean_the_credential_is_bad(status: int) -> None:
    """These are the platform explicitly rejecting us — actionable: re-issue the token."""
    res = interpret(status, "")
    assert res.state == "bad"
    assert "rejected" in res.detail


@pytest.mark.parametrize("status", [404, 429, 500, 502, 0])
def test_everything_else_is_unknown_not_bad(status: int) -> None:
    """A 404, a rate limit or a bad gateway says something about the endpoint or the
    platform's day — not about the token. Reporting those as a bad credential would send
    someone to re-issue a token that was fine."""
    assert interpret(status, "").state == "unknown"


def test_the_identity_is_surfaced_when_the_platform_gives_one() -> None:
    """Naming the account the token belongs to is what catches the subtlest error: a
    valid token for the WRONG account authenticates perfectly."""
    assert interpret(200, json.dumps({"username": "acme-blog"})).identity == "acme-blog"
    assert interpret(200, json.dumps({"data": {"me": {"username": "acme"}}})).identity == "acme"
    assert interpret(200, json.dumps({"site": {"title": "Acme"}})).identity == "Acme"


def test_an_unparseable_body_does_not_break_the_verdict() -> None:
    """Never raise on a body that is not JSON - and never call it a pass either.

    This test used to assert ``ok`` for an HTML body. That is precisely how a RETIRED
    endpoint reads as authenticated: Hashnode made its GraphQL API paid-only, 301'd to an
    announcement page, and the check reported "authenticated (200)" for a credential that
    could no longer publish. The no-crash intent is kept; the verdict is corrected.
    """
    res = interpret(200, "<html>not json</html>")
    assert res.state == "unknown"
    assert res.identity == ""


# --------------------------------------------------------------------------- #
# Building the per-platform read.
# --------------------------------------------------------------------------- #
def test_every_verifier_is_a_read_only_call() -> None:
    """A verification must never be able to create, publish or modify anything. GETs
    everywhere, and the one POST is a GraphQL *query*."""
    samples = {
        "dev.to": {"api_key": "k"},
        "GitHub Pages": {"token": "t"}, "GitHub Gist": {"token": "t"},
        "GitLab Pages": {"token": "t"}, "GitLab Snippets": {"token": "t"},
        "WordPress.com": {"oauth_token": "t"}, "Tumblr": {"oauth_token": "t"},
        "Blogger": {"oauth_token": "t"}, "Netlify": {"api_token": "t"},
        "Neocities": {"api_key": "k"}, "Ghost": {"api_url": "https://x.test"},
        "Hashnode": {"pat": "p"},
    }
    for platform, cred in samples.items():
        req = request_for(platform, cred)
        assert req is not None, platform
        if req.method == "POST":
            assert platform == "Hashnode"
            assert "query" in (req.json_body or {})
            assert "mutation" not in json.dumps(req.json_body or {}).lower()
        else:
            assert req.method == "GET", platform


def test_the_token_travels_in_a_header_never_the_url() -> None:
    """A token in a query string leaks into logs, proxies and referrers."""
    for platform, cred in (("dev.to", {"api_key": "SECRET"}),
                           ("Tumblr", {"oauth_token": "SECRET"}),
                           ("GitLab Pages", {"token": "SECRET"})):
        req = request_for(platform, cred)
        assert req is not None
        assert "SECRET" not in req.url, platform
        assert any("SECRET" in v for v in req.headers.values()), platform


def test_a_credential_missing_its_key_field_has_no_request() -> None:
    """Nothing to verify with, so there is nothing to ask - and asking anonymously would
    return a misleading 401 that reads as 'bad credential'."""
    assert request_for("dev.to", {"api_key": ""}) is None
    assert request_for("Tumblr", {}) is None


def test_an_unknown_platform_has_no_verifier() -> None:
    assert request_for("Storyblok", {"token": "t"}) is None


# --------------------------------------------------------------------------- #
# The end-to-end contract.
# --------------------------------------------------------------------------- #
def test_a_working_credential_reports_ok() -> None:
    res = check_credential("dev.to", {"api_key": "k"},
                           lambda req: (200, json.dumps({"username": "acme"})))
    assert res.ok and res.identity == "acme"


def test_a_rejected_credential_reports_bad() -> None:
    res = check_credential("dev.to", {"api_key": "k"}, lambda req: (401, ""))
    assert res.state == "bad"


def test_a_platform_with_no_verifier_is_unknown_not_ok() -> None:
    """Half the catalogue has no verifier yet. Those must not render as green."""
    res = check_credential("Storyblok", {"token": "t"}, lambda req: (200, "{}"))
    assert res.state == "unknown"
    assert not res.ok


def test_a_fetcher_that_raises_is_unknown_and_never_propagates() -> None:
    """Checking a credential must not be able to break the screen that shows it."""
    def boom(req: VerifyRequest) -> tuple[int, str]:
        raise TimeoutError("slow")

    res = check_credential("dev.to", {"api_key": "k"}, boom)
    assert res.state == "unknown"
    assert "request failed" in res.detail


def test_no_fetcher_is_unknown() -> None:
    assert check_credential("dev.to", {"api_key": "k"}, None).state == "unknown"


# --------------------------------------------------------------------------- #
# A 2xx is not automatically a pass
# --------------------------------------------------------------------------- #
def test_a_probe_that_sends_no_credential_is_never_reported_authenticated() -> None:
    """The Ghost verifier deliberately sends NO credential - it only reaches the
    instance, because the publisher owns the JWT signing. Mapping its 200 to
    "authenticated" reported a green tick for a token that was never presented: exactly
    the false success this module exists to remove. It is ``unknown``, not ``ok``."""
    from app.services.web2_credcheck import interpret, request_for

    req = request_for("Ghost", {"api_url": "https://example.test", "admin_api_key": "k"})
    assert req is not None
    assert req.authenticated is False, "the Ghost probe carries no credential"
    assert req.headers == {}

    verdict = interpret(200, '{"site":{"title":"Some Blog"}}', authenticated=False)
    assert verdict.state == "unknown"
    assert "does not present the credential" in verdict.detail


def test_a_graphql_rejection_is_bad_even_though_the_status_is_200() -> None:
    """GraphQL answers 200 with an ``errors`` array when it REJECTS a token. Reading only
    the status turned a rejection into a pass - and the module's own Hashnode publisher
    already checks that array, so the verifier disagreeing with the publisher meant the
    board said 'active' for a credential that could not publish."""
    from app.services.web2_credcheck import interpret

    verdict = interpret(200, '{"errors":[{"message":"Invalid token"}],"data":null}')
    assert verdict.state == "bad"
    assert "Invalid token" in verdict.detail


def test_a_real_authenticated_success_is_still_ok() -> None:
    """The fix must not turn every pass into 'unknown'."""
    from app.services.web2_credcheck import interpret

    assert interpret(200, '{"data":{"me":{"username":"zain"}}}').state == "ok"
    assert interpret(401, "").state == "bad"
    assert interpret(500, "").state == "unknown"


def test_a_retired_api_that_redirects_is_never_reported_authenticated() -> None:
    """MEASURED against Hashnode on 2026-08-30: it made its GraphQL API paid-only and
    301'd ``gql.hashnode.com`` to an announcement page. With redirects followed, the
    check landed on that HTML page, saw 200, and reported "authenticated (200)" for a
    credential that could no longer publish anything."""
    from app.services.web2_credcheck import interpret

    v = interpret(301, "")
    assert v.state == "unknown"
    assert "redirect" in v.detail.lower()


def test_a_json_api_answering_with_html_is_not_a_pass() -> None:
    """The second half of the same failure: even a 200 is not authentication when the
    body is a web page rather than an API response."""
    from app.services.web2_credcheck import interpret

    v = interpret(200, "<html><head><title>301 Moved</title></head><body>...</body></html>")
    assert v.state == "unknown"
    assert "non-json" in v.detail.lower()
    # A real JSON answer still passes.
    assert interpret(200, '{"data":{"me":{"username":"zain"}}}').state == "ok"


def test_the_credential_check_does_not_follow_redirects() -> None:
    """The guard belongs on the fetcher too: interpret can only judge what it is given,
    and a followed redirect hands it the wrong response entirely."""
    import inspect

    from app.routers import offpage

    src = inspect.getsource(offpage._account_fetcher)
    assert "follow_redirects=False" in src, (
        "the credential fetcher must not follow redirects"
    )
