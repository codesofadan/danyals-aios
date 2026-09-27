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
    UNVERIFIABLE,
    VerifyRequest,
    check_credential,
    interpret,
    request_for,
    unverifiable_reason,
)
from integrations.web2_publishers import PLATFORM_CREDENTIAL_FIELDS

pytestmark = pytest.mark.unit

#: The sentinel that stands in for a real secret, so a sweep can assert the credential
#: actually reaches the request.
SECRET = "S3CRET-VALUE"

#: Fields that are a LOCATION rather than a secret. They must look like real URLs, or a
#: verifier that builds a path from one produces nonsense.
_URL_FIELDS = {"api_url", "base_url", "instance_url", "endpoint", "placeholder_image_url"}

#: Fields that NAME something rather than authenticate it.
#:
#: The distinction is the whole point of the "never in the URL" rule: a `project_id` in
#: a hostname is how Sanity's API is addressed, while a token there is a leak. Treating
#: every field as a secret made that test fail on correct code, which is the way a
#: sweeping test stops being believed.
_IDENTIFIER_FIELDS = {
    "alias", "blog_id", "blog_name", "catid", "collection_id", "community",
    "content_group_id", "dataset", "domain", "hatena_id", "identifier", "livedoor_id",
    "owner", "parent_page_id", "project_id", "repo", "signer_uuid", "site", "space_id",
    "username",
}


def _full_credential(platform: str) -> dict[str, str]:
    """Every field this platform declares, populated.

    Secrets get the sentinel; identifiers get a plausible, obviously-not-secret value.
    """
    cred: dict[str, str] = {}
    for field in PLATFORM_CREDENTIAL_FIELDS[platform]:
        if field in _URL_FIELDS:
            cred[field] = "https://instance.example"
        elif field in _IDENTIFIER_FIELDS:
            cred[field] = f"public-{field}"
        else:
            cred[field] = SECRET
    return cred


def _carries(req: VerifyRequest, needle: str) -> bool:
    """Does the secret reach the platform anywhere in this request?

    HTTP Basic encodes `user:pass` TOGETHER as one base64 blob, so neither the raw
    secret nor `base64(secret)` appears verbatim in the header. The pair is decoded
    here instead of pattern-matched: a search for the plain value alone reported Drupal
    as sending no credential at all, and a false alarm is how a sweeping test earns a
    reputation for noise and gets deleted.
    """
    import base64
    import contextlib

    parts = [req.url, json.dumps(req.json_body or {})]
    for value in req.headers.values():
        parts.append(value)
        scheme, _, payload = value.partition(" ")
        if scheme.lower() == "basic" and payload:
            # A malformed header simply carries nothing; that is the assertion's answer.
            with contextlib.suppress(Exception):
                parts.append(base64.b64decode(payload + "===").decode("utf-8", "replace"))
    return any(needle in part for part in parts)


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
#: The only verifiers allowed to POST, each with the reason it cannot be a GET. A POST
#: is permitted ONLY where the platform offers no read route for the credential; none of
#: these creates, publishes or modifies content.
_POST_ALLOWED = {
    "Hashnode": "GraphQL; the body is a query",
    "Hygraph": "GraphQL; the body is a query",
    "Sourcehut Pages": "GraphQL; the body is a query",
    "Misskey": "/api/i READS the current account and takes the token in the body",
    "Bluesky": "AT Protocol createSession is the only way to exercise an app password",
    "WhiteWind": "AT Protocol createSession is the only way to exercise an app password",
}

#: The only verifiers allowed to put the secret in the URL, because their API accepts it
#: nowhere else. A token in a query string can reach access logs and proxies, so this is
#: a per-platform exception and never a default.
_SECRET_IN_URL_ALLOWED = {
    "Telegra.ph": "the API takes access_token as a query parameter only",
    "Disqus": "the API takes api_key and access_token as query parameters only",
}


def test_every_platform_can_be_checked_or_says_why_not() -> None:
    """THE DRIFT GUARD, and the reason this file sweeps instead of sampling.

    A platform with a publisher but no verifier can never reach ``health='active'``, and
    ``account_health`` fails closed - so it can never publish, and the broadcast planner
    silently excludes it. That is exactly how the module arrived at 24 connected
    accounts of which one could be used: nothing failed, the platform was simply absent
    from a list nobody was holding to the publisher registry.

    So every platform the publisher layer knows about must EITHER have a verifier or a
    stated reason it cannot have one. Adding a platform without doing one of those two
    things fails here, at the moment the decision is being made.
    """
    unexplained = [
        p for p in sorted(PLATFORM_CREDENTIAL_FIELDS)
        if request_for(p, _full_credential(p)) is None and not unverifiable_reason(p)
    ]
    assert not unexplained, (
        "these platforms can be published to but never verified, and nothing says why: "
        f"{unexplained}. Add a verifier in `request_for`, or a reason to `UNVERIFIABLE` "
        "/ `_WSSE_PLATFORMS` / `_SESSION_LOGIN_REFUSED`."
    )


def test_the_coverage_is_real_and_not_all_exemptions() -> None:
    """Guards the guard: the test above also passes if EVERY platform is exempted."""
    verified = [p for p in PLATFORM_CREDENTIAL_FIELDS if request_for(p, _full_credential(p))]
    assert len(verified) >= 40, f"only {len(verified)} platforms have a real verifier"


def test_every_verifier_is_a_read_only_call() -> None:
    """A verification must never be able to create, publish or modify anything."""
    for platform in sorted(PLATFORM_CREDENTIAL_FIELDS):
        req = request_for(platform, _full_credential(platform))
        if req is None or req.method == "GET":
            continue
        assert req.method == "POST", f"{platform} uses {req.method}"
        assert platform in _POST_ALLOWED, (
            f"{platform} verifies with a POST and is not on the allow-list. A POST is "
            "permitted only where the platform has no read route for the credential."
        )
        assert "mutation" not in json.dumps(req.json_body or {}).lower(), platform


def test_every_verifier_actually_presents_the_credential() -> None:
    """A request that does not carry the secret cannot prove anything about it.

    This is the false success ``interpret`` guards at the other end: a probe that omits
    the credential gets a cheerful 200 from any healthy instance. Ghost is the one
    verifier that deliberately cannot present one, and it is marked
    ``authenticated=False`` so its 200 reports as ``unknown`` rather than ``ok``.
    """
    for platform in sorted(PLATFORM_CREDENTIAL_FIELDS):
        req = request_for(platform, _full_credential(platform))
        if req is None:
            continue
        if not req.authenticated:
            assert platform == "Ghost", (
                f"{platform} sends no credential but is not flagged unauthenticated"
            )
            continue
        assert _carries(req, SECRET), f"{platform}'s request never sends the credential"


def test_the_token_travels_in_a_header_never_the_url() -> None:
    """A token in a query string leaks into access logs, proxies and referrers."""
    for platform in sorted(PLATFORM_CREDENTIAL_FIELDS):
        req = request_for(platform, _full_credential(platform))
        if req is None or SECRET not in req.url:
            continue
        assert platform in _SECRET_IN_URL_ALLOWED, (
            f"{platform} puts the credential in the URL. Move it to a header, or record "
            "in `_SECRET_IN_URL_ALLOWED` why the API accepts it nowhere else."
        )


def test_a_credential_supplied_host_is_flagged_for_the_ssrf_guard() -> None:
    """Any verifier whose host comes from the account must say so.

    The flag is what routes it through ``validate_public_host``. An unflagged one is a
    server-side request to wherever the operator typed: ``http://169.254.169.254/``
    reads cloud metadata, and the body comes back inside the check's own detail string.
    """
    for platform in sorted(PLATFORM_CREDENTIAL_FIELDS):
        req = request_for(platform, _full_credential(platform))
        if req is None:
            continue
        if "instance.example" in req.url:
            assert req.host_from_credential, (
                f"{platform} builds its URL from the credential but is not flagged, so "
                "it would skip the SSRF guard"
            )


def test_a_private_host_is_refused_before_any_request_is_made() -> None:
    """The guard has to run BEFORE the fetch, not as a judgement on the response."""
    calls: list[VerifyRequest] = []

    def _fetch(req: VerifyRequest) -> tuple[int, str]:
        calls.append(req)
        return 200, "{}"

    result = check_credential(
        "Mastodon",
        {"access_token": "t", "instance_url": "http://169.254.169.254/"},
        _fetch,
    )
    assert result.state == "bad"
    assert "public address" in result.detail
    assert not calls, "the SSRF guard let the request through"


def test_a_platform_that_cannot_be_checked_says_why_rather_than_not_built() -> None:
    """"Not built yet" reads as a TODO and sends an operator back to wait. These cannot
    ever be checked, and the message has to say so."""
    for platform in UNVERIFIABLE:
        result = check_credential(
            platform, _full_credential(platform), lambda req: (200, "{}")
        )
        assert result.state == "unknown"
        assert result.detail == UNVERIFIABLE[platform][:400]
        assert "not built" not in result.detail


def test_a_text_api_is_not_punished_for_answering_text() -> None:
    """The JSON rule catches a retired endpoint serving a docs page. Micro.blog's
    verify route legitimately answers text/html for BOTH outcomes, so applying that
    rule to it turned a working credential into "probably not the API any more"."""
    req = request_for("Micro.blog", {"token": "t"})
    assert req is not None and req.expects_json is False

    assert interpret(200, "Verified.", expects_json=False).state == "ok"
    # And the rule still bites where it should.
    assert interpret(200, "<html>docs</html>", expects_json=True).state == "unknown"
    # A rejection is still a rejection whatever the content type.
    assert interpret(401, "Invalid token", expects_json=False).state == "bad"


def test_a_lockout_risky_login_is_refused_rather_than_attempted() -> None:
    """LiveJournal counts a failed probe toward lockout, so checking a password there
    could lock the CLIENT out of their own account. Not knowing is the lesser harm."""
    result = check_credential(
        "LiveJournal", {"username": "u", "password": "p"}, lambda req: (200, "{}")
    )
    assert result.state == "unknown"
    assert "lockout" in result.detail


def test_a_credential_missing_its_key_field_has_no_request() -> None:
    """Nothing to verify with, so there is nothing to ask - and asking anonymously would
    return a misleading 401 that reads as 'bad credential'."""
    assert request_for("dev.to", {"api_key": ""}) is None
    assert request_for("Tumblr", {}) is None


def test_an_unknown_platform_has_no_verifier() -> None:
    # Was "Storyblok", which now HAS one - a stand-in for "unknown" has to be a name the
    # registry will never learn, or the test quietly stops testing anything.
    assert request_for("Some Platform Nobody Has Built", {"token": "t"}) is None


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
